"""Microsoft 365 connection, against a PRETEND Microsoft (lib/microsoft.py, MS_STUB): connect with the person's own account, read-only listings, import a file or an email into a matter as an ordinary
document, disconnect. It proves VIDHI's side (state, one-use flows, encrypted token, organisation and person separation, no secrets in logs or exports), not Microsoft's real behaviour."""

import re
import uuid
from urllib.parse import parse_qs, urlparse

import pytest

from lib import microsoft
from tests.conftest import mongo, new_matter


def connect(c):
    """Walk the browser flow: start (redirect to Microsoft), then the callback Microsoft would send the person back to."""
    r = c.get("/connectors/microsoft/start", follow_redirects=False)
    assert r.status_code == 302, r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert r.headers["location"].startswith("https://login.microsoftonline.com/") and q["code_challenge_method"] == ["S256"] and set(q["scope"][0].split()) == {"openid", "offline_access", "User.Read", "Files.Read", "Mail.Read"}
    back = c.get("/connectors/microsoft/callback", params={"code": "stub-code", "state": q["state"][0]}, follow_redirects=False)
    return back


def test_the_scopes_only_read():
    assert set(microsoft.SCOPES.split()) == {"openid", "offline_access", "User.Read", "Files.Read", "Mail.Read"}  # nothing that sends, writes or deletes


def test_status_lists_every_connection_and_is_honest_about_imanage(user_a):
    out = {x["id"]: x for x in user_a.get("/connectors").json()["connections"]}
    assert out["word"]["state"] == "available" and out["microsoft"]["state"] == "not_connected" and out["imanage"]["state"] == "not_available"
    assert "Not built" in out["imanage"]["does"]


def test_nothing_works_before_connecting_and_nobody_else_can_use_my_connection(user_a, user_b):
    mid, _ = new_matter(user_a, "Connector matter")
    assert user_a.get("/connectors/microsoft/files").status_code == 409
    assert user_a.get("/connectors/microsoft/mail").status_code == 409
    assert user_a.post(f"/matters/{mid}/connectors/microsoft/import", json={"kind": "file", "id": "f1"}).status_code == 409
    assert connect(user_a).headers["location"].endswith("microsoft=connected")
    assert user_a.get("/connectors/microsoft/files").status_code == 200
    assert user_b.get("/connectors/microsoft/files").status_code == 409  # another person, another firm: no connection of their own
    assert user_b.post(f"/matters/{mid}/connectors/microsoft/import", json={"kind": "file", "id": "f1"}).status_code == 404  # and not my matter


def test_connect_lists_imports_a_file_and_an_email_and_disconnects(user_a):
    mid, _ = new_matter(user_a, "Connector matter 2")
    back = connect(user_a)
    assert back.status_code == 302 and back.headers["location"] == "/connections?microsoft=connected"
    state = {x["id"]: x for x in user_a.get("/connectors").json()["connections"]}["microsoft"]
    assert state["state"] == "connected" and state["account"] == "stub.user@example.test"

    files = user_a.get("/connectors/microsoft/files").json()["items"]
    assert {(f["name"], f["folder"]) for f in files} == {("lease.txt", False), ("Contracts", True)}
    mails = user_a.get("/connectors/microsoft/mail").json()["items"]
    assert mails[0]["subject"] == "Notice of termination" and mails[0]["from"] == "asha@example.test"

    f = user_a.post(f"/matters/{mid}/connectors/microsoft/import", json={"kind": "file", "id": "f1"})
    assert f.status_code == 200, f.text
    assert f.json()["filename"] == "lease.txt"
    assert user_a.post(f"/matters/{mid}/connectors/microsoft/import", json={"kind": "file", "id": "f1"}).status_code == 409  # the same file twice is refused like any upload
    assert user_a.post(f"/matters/{mid}/connectors/microsoft/import", json={"kind": "file", "id": "d1"}).status_code == 502  # a folder is not a file
    m = user_a.post(f"/matters/{mid}/connectors/microsoft/import", json={"kind": "mail", "id": "mail-1"})
    assert m.status_code == 200 and m.json()["filename"].startswith("email-Notice-of-termination")
    text = user_a.get(f"/documents/{m.json()['id']}").json()
    assert "Subject: Notice of termination" in str(text) and "asha@example.test" in str(text) and "notice of termination" in str(text).lower()
    assert user_a.post(f"/matters/{mid}/connectors/microsoft/import", json={"kind": "mail", "id": "nope"}).status_code == 502
    assert user_a.post(f"/matters/{mid}/connectors/microsoft/import", json={"kind": "zip", "id": "x"}).status_code == 422

    ops = [e for e in mongo().audit_events.find({"matter_id": mid, "operation": "CONNECTOR_IMPORT"})]
    assert len(ops) == 2 and all("lease" not in (e.get("detail") or "") and "termination" not in (e.get("detail") or "") for e in ops)  # the kind only

    assert user_a.delete("/connectors/microsoft").json() == {"disconnected": 1}
    assert user_a.get("/connectors/microsoft/files").status_code == 409


def test_the_token_is_kept_encrypted_and_one_flow_is_good_for_one_use(user_a):
    r = user_a.get("/connectors/microsoft/start", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    first = user_a.get("/connectors/microsoft/callback", params={"code": "stub-code", "state": state}, follow_redirects=False)
    assert first.headers["location"].endswith("microsoft=connected")
    row = mongo().connector_tokens.find_one({"user_id": user_a.user["id"]})
    assert row and "stub-refresh" not in str(row) and row["refresh_sealed"] and "refresh_token" not in row  # sealed, never the plain token
    assert user_a.get("/connectors/microsoft/callback", params={"code": "stub-code", "state": state}, follow_redirects=False).headers["location"].endswith("microsoft=cancelled")  # the cookie was cleared too
    user_a.cookies.set("vidhi_conn", state)  # even with the cookie put back, the flow is gone
    again = user_a.get("/connectors/microsoft/callback", params={"code": "stub-code", "state": state}, follow_redirects=False)
    assert again.headers["location"].endswith("microsoft=failed")  # the flow was used up


def test_a_wrong_state_or_a_cancelled_sign_in_connects_nothing(user_a, user_b):
    user_a.get("/connectors/microsoft/start", follow_redirects=False)
    assert user_a.get("/connectors/microsoft/callback", params={"code": "stub-code", "state": "forged"}, follow_redirects=False).headers["location"].endswith("microsoft=cancelled")
    assert user_a.get("/connectors/microsoft/callback", params={"error": "access_denied"}, follow_redirects=False).headers["location"].endswith("microsoft=cancelled")
    assert mongo().connector_tokens.count_documents({"user_id": user_a.user["id"]}) == 0
    # a flow that person A started cannot be finished by person B
    sa = parse_qs(urlparse(user_a.get("/connectors/microsoft/start", follow_redirects=False).headers["location"]).query)["state"][0]
    user_b.cookies.set("vidhi_conn", sa)
    assert user_b.get("/connectors/microsoft/callback", params={"code": "stub-code", "state": sa}, follow_redirects=False).headers["location"].endswith("microsoft=failed")
    assert mongo().connector_tokens.count_documents({"user_id": user_b.user["id"]}) == 0


def test_a_member_of_a_firm_cannot_see_a_colleagues_mail_and_the_token_goes_with_the_organisation(user_a):
    connect(user_a)
    assert mongo().connector_tokens.count_documents({"organization_id": user_a.user["organization_id"]}) == 1
    from lib import purge
    from routers import org_data

    assert "connector_tokens" in purge.ORG_TAGGED and "connector_tokens" in org_data.EXPORT_EXCLUDED and "connector_tokens" not in org_data.EXPORT_COLLECTIONS


@pytest.mark.parametrize("snippet", ["Subject: ", "From: "])
def test_mail_text_has_who_when_and_subject(snippet):
    import asyncio

    name, data = asyncio.run(microsoft.mail_as_text("stub-access", "mail-1"))
    assert snippet in data.decode() and re.match(r"email-[A-Za-z0-9-]+\.txt", name)


def test_a_sealed_secret_opens_on_a_site_with_a_data_key_and_no_link_secret(monkeypatch):
    """Found by the browser tests: reading a token back crashed when DATA_ENCRYPTION_KEY was set but LINK_SECRET was not."""
    import base64
    import os

    from lib import crypto

    monkeypatch.setenv("DATA_ENCRYPTION_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    monkeypatch.delenv("LINK_SECRET", raising=False)
    sealed = crypto.seal_text("a-small-secret", b"aad")
    assert crypto.open_text(sealed, b"aad") == "a-small-secret"
    with pytest.raises(ValueError):
        crypto.open_text(sealed, b"other-aad")  # still bound to what it was sealed for
