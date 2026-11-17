"""The invite-only pilot (decision D6). The main test server runs in open mode, so a second API process is started with SIGNUP_MODE=invite on the same database to test the real gate.
Invitations are single-use, bound to one email address, expire, and are stored only as a hash."""

import asyncio
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from lib import pilot
from tests.conftest import mongo, outbox
from tests.inproc import run
from tests.test_admin import admin  # noqa: F401  (fixture)

BACKEND = Path(__file__).resolve().parent.parent
PW = "Invite-test-Pass-1234"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def invite_api():
    """A second copy of the API, same database, in invite-only mode."""
    port = free_port()
    env = {**os.environ, "SIGNUP_MODE": "invite"}
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--port", str(port), "--log-level", "warning"], cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}/api"
    try:
        for _ in range(120):
            try:
                if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise AssertionError("the invite-only API did not start")
        yield base
    finally:
        p.terminate()
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()


def signup(base, email, code=None, **over):
    body = {"email": email, "password": PW, "full_name": "Pilot Person", "organization_name": f"Pilot Chambers {uuid.uuid4().hex[:6]}", "accept_privacy": True, **over}
    if code is not None:
        body["invite_code"] = code
    return httpx.post(f"{base}/auth/signup", json=body, timeout=30)


def new_email():
    return f"pilot-{uuid.uuid4().hex[:10]}@example.com"


# ---- the invitation records (lib/pilot.py) ----

def test_an_invitation_is_hashed_single_use_bound_to_its_address_and_expires():
    email = new_email()
    row, code = run(pilot.create(email, "op@example.com"))
    assert "code_hash" not in row and code not in str(mongo().pilot_invites.find_one({"id": row["id"]}).values())  # only a hash is stored
    assert run(pilot.valid(email, code)) is not None
    assert run(pilot.valid(email.upper(), code)) is not None  # addresses compare in lower case
    assert run(pilot.valid(email, code + "x")) is None and run(pilot.valid(new_email(), code)) is None and run(pilot.valid(email, "")) is None and run(pilot.valid(email, None)) is None
    assert run(pilot.claim(row["id"])) is True and run(pilot.claim(row["id"])) is False  # single use, even when asked twice
    assert run(pilot.valid(email, code)) is None
    run(pilot.release(row["id"]))
    assert run(pilot.valid(email, code)) is not None  # given back when the account could not be made
    mongo().pilot_invites.update_one({"id": row["id"]}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert run(pilot.valid(email, code)) is None and run(pilot.open_for_email(email)) is None


def test_a_new_invitation_cancels_the_earlier_open_one_for_the_same_address():
    email = new_email()
    _, first = run(pilot.create(email, "op@example.com"))
    _, second = run(pilot.create(email, "op@example.com"))
    assert run(pilot.valid(email, first)) is None and run(pilot.valid(email, second)) is not None


# ---- the operator's routes ----

def test_the_operator_creates_lists_and_revokes_invitations_and_codes_are_shown_once(admin):  # noqa: F811
    email = new_email()
    r = admin.post("/admin/pilot/invites", json={"email": email})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"] and f"invite={body['code']}" in body["link"] and f"email={email}" in body["link"] and body["emailed"] is False
    listing = admin.get("/admin/pilot/invites").json()
    mine = next(i for i in listing["invites"] if i["id"] == body["id"])
    assert mine["state"] == "open" and "code" not in mine and "code_hash" not in mine and body["code"] not in str(listing)
    assert admin.delete(f"/admin/pilot/invites/{body['id']}").status_code == 200
    assert next(i for i in admin.get("/admin/pilot/invites").json()["invites"] if i["id"] == body["id"])["state"] == "revoked"
    assert admin.delete(f"/admin/pilot/invites/{body['id']}").status_code == 404
    assert admin.post("/admin/pilot/invites", json={"email": "not-an-email"}).status_code == 422


def test_emailing_an_invitation_needs_an_https_site_address_and_creates_nothing_otherwise(admin):  # noqa: F811
    email = new_email()
    r = admin.post("/admin/pilot/invites", json={"email": email, "send_email": True})  # the test server's APP_URL is plain http
    assert r.status_code == 422 and "https" in r.json()["detail"]
    assert mongo().pilot_invites.count_documents({"email": email}) == 0 and outbox(email, "invitation") == []


def test_the_invitation_email_carries_the_link_and_the_not_legal_advice_line():
    html = pilot.invite_email_html("https://app.example.in/login?mode=signup&invite=CODE123&email=a@b.co")
    assert "invite=CODE123" in html and "not legal advice" in html and f"{pilot.INVITE_DAYS} days" in html


def test_only_the_operator_can_manage_invitations(user_a, anon):
    for method, path, body in [("get", "/admin/pilot/invites", None), ("post", "/admin/pilot/invites", {"email": "a@b.co"}), ("delete", "/admin/pilot/invites/x", None)]:
        expected = user_a.get("/admin/overview")
        r = getattr(user_a, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == expected.status_code, path
        assert getattr(anon, method)(path, **({"json": body} if body is not None else {})).status_code in (401, 403), path


def test_the_open_server_still_lets_anyone_sign_up_and_says_so(anon):
    assert anon.get("/auth/options").json()["signup_mode"] == "open"


# ---- the gate itself, on a server in invite mode ----

def test_signup_needs_an_invitation_for_that_exact_address_and_it_works_once(invite_api, admin):  # noqa: F811
    assert httpx.get(f"{invite_api}/auth/options", timeout=30).json()["signup_mode"] == "invite"
    email = new_email()
    refused = signup(invite_api, email)
    assert refused.status_code == 403 and "invite-only" in refused.json()["detail"]
    assert mongo().users.count_documents({"email": email}) == 0 and mongo().organizations.count_documents({"name": {"$regex": "^Pilot Chambers"}, "created_at": {"$gt": datetime.now(timezone.utc) - timedelta(seconds=30)}}) == 0
    code = admin.post("/admin/pilot/invites", json={"email": email}).json()["code"]
    assert signup(invite_api, email, "wrong-code").status_code == 403
    assert signup(invite_api, new_email(), code).status_code == 403  # a code is for one address
    ok = signup(invite_api, email, code)
    assert ok.status_code == 200, ok.text
    again = signup(invite_api, email, code)
    assert again.status_code == 403  # used
    assert next(i for i in admin.get("/admin/pilot/invites").json()["invites"] if i["email"] == email)["state"] == "used"
    # signing in is never gated
    login = httpx.post(f"{invite_api}/auth/login", json={"email": email, "password": PW}, timeout=30)
    assert login.status_code == 200


def test_a_refused_signup_does_not_reveal_whether_the_address_already_has_an_account(invite_api, user_a):
    existing = user_a.get("/auth/me").json()["email"]
    r = signup(invite_api, existing)
    assert r.status_code == 403 and "invite-only" in r.json()["detail"]  # not "an account with this email already exists"


def test_an_expired_or_revoked_invitation_is_refused(invite_api, admin):  # noqa: F811
    email = new_email()
    made = admin.post("/admin/pilot/invites", json={"email": email}).json()
    mongo().pilot_invites.update_one({"id": made["id"]}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    assert signup(invite_api, email, made["code"]).status_code == 403
    email2 = new_email()
    made2 = admin.post("/admin/pilot/invites", json={"email": email2}).json()
    admin.delete(f"/admin/pilot/invites/{made2['id']}")
    assert signup(invite_api, email2, made2["code"]).status_code == 403


def test_an_existing_address_is_told_so_only_when_the_invitation_is_valid_and_the_invitation_is_given_back(invite_api, admin, user_a):  # noqa: F811
    existing = user_a.get("/auth/me").json()["email"]
    made = admin.post("/admin/pilot/invites", json={"email": existing}).json()
    r = signup(invite_api, existing, made["code"])
    assert r.status_code == 409
    assert next(i for i in admin.get("/admin/pilot/invites").json()["invites"] if i["id"] == made["id"])["state"] == "open"  # not wasted


def _google(base, email):
    code = "code-" + uuid.uuid4().hex
    mongo().google_stub.insert_one({"code": code, "bad_nonce": False, "claims": {"sub": "g-" + uuid.uuid4().hex[:12], "email": email, "email_verified": True, "name": "Google Pilot"}})
    with httpx.Client(base_url=base, timeout=30, follow_redirects=False) as c:
        start = c.get("/auth/google/start")
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        return c.get("/auth/google/callback", params={"code": code, "state": state})


def test_a_new_google_account_needs_an_open_invitation_for_its_address(invite_api, admin):  # noqa: F811
    email = new_email()
    no = _google(invite_api, email)
    assert no.status_code == 302 and no.headers["location"].endswith("/login?error=invite_only")
    assert mongo().users.count_documents({"email": email}) == 0
    made = admin.post("/admin/pilot/invites", json={"email": email}).json()
    yes = _google(invite_api, email)
    assert yes.status_code == 302 and yes.headers["location"].endswith("/start") and mongo().users.count_documents({"email": email}) == 1
    assert next(i for i in admin.get("/admin/pilot/invites").json()["invites"] if i["id"] == made["id"])["state"] == "used"
    again = _google(invite_api, email)  # the same person signing in again: an existing account, no invitation needed
    assert again.headers["location"].endswith("/start")
