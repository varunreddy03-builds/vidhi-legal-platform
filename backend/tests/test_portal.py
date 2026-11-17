"""The client portal: a client sees only what a lawyer shared, read-only, scoped per matter, and everything else is refused by the server."""

import re
import uuid

import httpx
import pytest

from lib.rbac import ROLE_CAPS, required_cap
from tests.conftest import API_URL, mongo, new_member, outbox, token_from_mail, upload, verify_email

SECRET = "INTERNAL STRATEGY: settle below 40 percent"


def matter_with_secret(c, label="Portal"):
    r = c.post("/matters", json={"title": f"{label} {uuid.uuid4().hex[:8]}", "description": SECRET, "parties": "Acme v Secret Party Ltd"})
    assert r.status_code == 200, r.text
    return r.json()["id"], r.json()["title"]


def invite_client(owner, matter_id, email=None):
    email = email or f"client-{uuid.uuid4().hex[:10]}@example.com"
    r = owner.post(f"/matters/{matter_id}/portal/clients", json={"email": email})
    assert r.status_code == 200, r.text
    return email, r.json()


def accept(email, password=None):
    password = password or f"Pw-{uuid.uuid4().hex}"
    mail = outbox(to=email, subject_has="client portal")[-1]
    token = token_from_mail(mail, "token=")
    c = httpx.Client(base_url=API_URL, timeout=30.0)
    r = c.post("/auth/accept-invite", json={"token": token, "full_name": "Client Person", "password": password, "accept_privacy": True})
    assert r.status_code == 200, r.text
    c.user, c.password = r.json(), password
    return c


def make_client(owner, matter_id):
    email, _ = invite_client(owner, matter_id)
    return accept(email)


@pytest.fixture
def firm(user_a):
    verify_email(user_a)
    return user_a


def test_a_lawyer_invites_a_client_who_accepts_and_gets_only_the_portal_role(firm):
    mid, _ = matter_with_secret(firm)
    email, out = invite_client(firm, mid)
    assert out["pending"] is True
    state = firm.get(f"/matters/{mid}/portal").json()
    assert [(c["email"], c["pending"]) for c in state["clients"]] == [(email, True)]
    mail = outbox(to=email, subject_has="client portal")[-1]
    assert SECRET not in mail["html"] and "Matter" not in mail["subject"]  # the invitation reveals nothing about the matter
    client = accept(email)
    assert client.user["role"] == "CLIENT" and client.user["capabilities"] == ["account", "portal"]
    assert client.get("/auth/me").json()["email"] == email
    state = firm.get(f"/matters/{mid}/portal").json()
    assert [(c["email"], c["pending"]) for c in state["clients"]] == [(email, False)]
    assert mongo().portal_access.count_documents({"matter_id": mid, "user_id": client.user["id"], "revoked_at": None}) == 1


def test_a_client_sees_only_shared_updates_and_documents_and_never_the_internal_notes(firm):
    mid, title = matter_with_secret(firm)
    client = make_client(firm, mid)
    shared = upload(firm, mid, "letter-to-client.txt", "Dear client, here is the plan.")
    hidden = upload(firm, mid, "internal-memo.txt", "Do not share this.")
    assert firm.post(f"/matters/{mid}/portal/updates", json={"text": "The hearing is fixed for next month."}).status_code == 200
    assert firm.post(f"/matters/{mid}/portal/documents", json={"document_id": shared["id"]}).status_code == 200
    listing = client.get("/portal/matters").json()
    assert listing["matters"] == [{"id": mid, "title": title, "status": "OPEN", "updates": 1, "documents": 1}]
    detail = client.get(f"/portal/matters/{mid}")
    body = detail.text
    assert detail.status_code == 200 and "The hearing is fixed for next month." in body and "letter-to-client.txt" in body
    assert SECRET not in body and "Secret Party" not in body and "internal-memo.txt" not in body and "description" not in detail.json() and "parties" not in detail.json()
    file = client.get(f"/portal/matters/{mid}/documents/{shared['id']}/file")
    assert file.status_code == 200 and file.content == b"Dear client, here is the plan." and "attachment" in file.headers["content-disposition"]
    assert client.get(f"/portal/matters/{mid}/documents/{hidden['id']}/file").status_code == 404  # uploaded to the matter, never shared
    assert any(e["operation"] == "PORTAL_DOCUMENT_VIEWED" and e["user_id"] == client.user["id"] for e in mongo().audit_events.find({"matter_id": mid}))


def test_access_is_per_matter_and_across_organisations_nothing_leaks(firm, user_b):
    m1, _ = matter_with_secret(firm)
    m2, _ = matter_with_secret(firm)
    d2 = upload(firm, m2, "other.txt", "other matter")
    firm.post(f"/matters/{m2}/portal/documents", json={"document_id": d2["id"]})
    client = make_client(firm, m1)
    assert [m["id"] for m in client.get("/portal/matters").json()["matters"]] == [m1]
    assert client.get(f"/portal/matters/{m2}").status_code == 404  # same firm, not shared with this client
    assert client.get(f"/portal/matters/{m2}/documents/{d2['id']}/file").status_code == 404
    assert client.get(f"/portal/matters/{m1}/documents/{d2['id']}/file").status_code == 404  # a document of another matter through an allowed matter
    mb, _ = matter_with_secret(user_b)
    assert client.get(f"/portal/matters/{mb}").status_code == 404
    assert client.get("/portal/matters/does-not-exist").status_code == 404
    # another firm cannot touch this firm's matter or its clients
    verify_email(user_b)
    assert user_b.get(f"/matters/{m1}/portal").status_code == 404
    assert user_b.post(f"/matters/{m1}/portal/clients", json={"email": "x@example.com"}).status_code == 404
    assert user_b.post(f"/matters/{m1}/portal/updates", json={"text": "hi"}).status_code == 404
    assert user_b.post(f"/matters/{mb}/portal/documents", json={"document_id": d2["id"]}).status_code == 404  # a document of another firm


def test_removing_a_client_ends_access_at_once_and_deleting_a_document_stops_sharing_it(firm):
    mid, _ = matter_with_secret(firm)
    client = make_client(firm, mid)
    doc = upload(firm, mid, "shared.txt", "content")
    firm.post(f"/matters/{mid}/portal/documents", json={"document_id": doc["id"]})
    assert client.get(f"/portal/matters/{mid}/documents/{doc['id']}/file").status_code == 200
    assert firm.delete(f"/documents/{doc['id']}").status_code == 200
    assert client.get(f"/portal/matters/{mid}").json()["documents"] == [] and mongo().portal_shares.count_documents({"matter_id": mid}) == 0
    ref = firm.get(f"/matters/{mid}/portal").json()["clients"][0]["id"]
    assert firm.delete(f"/matters/{mid}/portal/clients/{ref}").status_code == 200
    assert client.get(f"/portal/matters/{mid}").status_code == 404 and client.get("/portal/matters").json()["matters"] == []
    assert client.get("/auth/me").status_code == 200  # the account itself stays
    assert firm.delete(f"/matters/{mid}/portal/clients/{ref}").status_code == 404


def test_a_pending_invitation_can_be_withdrawn_and_then_cannot_be_used(firm):
    mid, _ = matter_with_secret(firm)
    email, out = invite_client(firm, mid)
    assert firm.delete(f"/matters/{mid}/portal/clients/{out['id']}").status_code == 200
    token = token_from_mail(outbox(to=email, subject_has="client portal")[-1], "token=")
    r = httpx.post(f"{API_URL}/auth/accept-invite", json={"token": token, "full_name": "X Y", "password": f"Pw-{uuid.uuid4().hex}", "accept_privacy": True})
    assert r.status_code == 404


def test_the_same_client_can_be_given_a_second_matter_but_an_outside_account_cannot_be_invited(firm, user_b):
    m1, _ = matter_with_secret(firm)
    m2, _ = matter_with_secret(firm)
    email, _ = invite_client(firm, m1)
    client = accept(email)
    again = firm.post(f"/matters/{m2}/portal/clients", json={"email": email})
    assert again.status_code == 200 and again.json()["pending"] is False
    assert {m["id"] for m in client.get("/portal/matters").json()["matters"]} == {m1, m2}
    assert firm.post(f"/matters/{m2}/portal/clients", json={"email": email}).status_code == 409  # already has it
    assert firm.post(f"/matters/{m1}/portal/clients", json={"email": user_b.user["email"]}).status_code == 409  # has an account with another firm
    assert firm.post(f"/matters/{m1}/portal/clients", json={"email": firm.user["email"]}).status_code == 409  # a colleague is not a client


def test_a_new_update_emails_the_client_without_any_content(firm):
    mid, title = matter_with_secret(firm)
    client = make_client(firm, mid)
    text = "Confidential: the other side offered 5 lakh"
    firm.post(f"/matters/{mid}/portal/updates", json={"text": text})
    mails = outbox(to=client.user["email"], subject_has="new update")
    assert len(mails) == 1 and text not in mails[0]["html"] and title not in mails[0]["html"] and "Confidential" not in mails[0]["subject"]
    ups = firm.get(f"/matters/{mid}/portal").json()["updates"]
    assert firm.delete(f"/matters/{mid}/portal/updates/{ups[0]['id']}").status_code == 200
    assert client.get(f"/portal/matters/{mid}").json()["updates"] == []


def test_only_people_who_may_email_third_parties_can_share(firm):
    mid, _ = matter_with_secret(firm)
    member = new_member(firm, "MEMBER")  # read and write, but no emailing third parties
    lawyer = new_member(firm, "LAWYER")
    doc = upload(firm, mid, "a.txt", "a")
    assert member.get(f"/matters/{mid}/portal").status_code == 403
    assert member.post(f"/matters/{mid}/portal/updates", json={"text": "hi"}).status_code == 403
    assert member.post(f"/matters/{mid}/portal/documents", json={"document_id": doc["id"]}).status_code == 403
    assert lawyer.post(f"/matters/{mid}/portal/documents", json={"document_id": doc["id"]}).status_code == 200
    assert lawyer.post(f"/matters/{mid}/portal/clients", json={"email": f"c-{uuid.uuid4().hex[:8]}@example.com"}).status_code == 200


def test_unverified_senders_cannot_invite_a_client(user_a):
    mid, _ = matter_with_secret(user_a)
    assert user_a.post(f"/matters/{mid}/portal/clients", json={"email": "someone@example.com"}).status_code == 403


def test_a_clients_role_cannot_be_changed_but_an_owner_can_remove_the_client(firm):
    mid, _ = matter_with_secret(firm)
    client = make_client(firm, mid)
    r = firm.patch(f"/org/members/{client.user['id']}", json={"role": "LAWYER"})
    assert r.status_code == 409 and "cannot be changed" in r.json()["detail"]
    assert firm.post("/org/invites", json={"email": f"x-{uuid.uuid4().hex[:6]}@example.com", "role": "CLIENT"}).status_code == 422  # clients are invited from a matter only
    assert firm.delete(f"/org/members/{client.user['id']}").status_code == 200
    assert client.get("/auth/me").status_code == 401  # signed out at once
    assert mongo().portal_access.count_documents({"user_id": client.user["id"]}) == 0


def test_deleting_a_matter_removes_its_portal_data(firm):
    mid, _ = matter_with_secret(firm)
    make_client(firm, mid)
    firm.post(f"/matters/{mid}/portal/updates", json={"text": "hello"})
    assert firm.delete(f"/matters/{mid}").status_code == 200
    for coll in ("portal_access", "portal_updates", "portal_shares"):
        assert mongo()[coll].count_documents({"matter_id": mid}) == 0


def test_a_client_is_refused_by_every_route_except_the_portal_and_their_own_account(firm):
    """Walks every route the API has. A client's session must get 403 from each one that is not public and not in the portal/account set."""
    from server import app

    mid, _ = matter_with_secret(firm)
    client = make_client(firm, mid)
    caps = ROLE_CAPS["CLIENT"]
    checked = refused = 0
    for template, ops in app.openapi()["paths"].items():
        for method in ops:
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            cap = required_cap(method.upper(), template)
            if cap is None or cap in caps:
                continue  # public routes and the client's own routes: not what this test is about
            path = re.sub(r"\{[^}]+\}", "x", template).removeprefix("/api")
            r = client.request(method.upper(), path, json={} if method != "get" else None)
            checked += 1
            assert r.status_code == 403, f"{method.upper()} {template} answered {r.status_code} to a client"
            refused += 1
    assert checked > 100 and refused == checked  # the walk really covered the API
    # and the routes a client does own are open to them
    assert client.get("/portal/matters").status_code == 200 and client.get("/auth/sessions").status_code == 200 and client.get("/support/messages").status_code != 403


def test_every_staff_role_keeps_what_it_had_and_gains_only_account():
    assert "account" in ROLE_CAPS["OWNER"] and "portal" not in ROLE_CAPS["OWNER"] and "read" in ROLE_CAPS["MEMBER"]
    assert ROLE_CAPS["CLIENT"] == frozenset({"account", "portal"})
    for role in ("OWNER", "ADMIN", "LAWYER", "MEMBER"):
        assert "portal" not in ROLE_CAPS[role]  # staff do not use the client portal routes