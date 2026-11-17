"""Sign in with Google (a stand-in plays Google's token endpoint), plus longer-lasting sessions."""

import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from lib import google_auth
from lib.auth import SESSION_DAYS
from tests.conftest import API_URL, mongo
from tests.test_twofactor import _enable


def client() -> httpx.Client:
    return httpx.Client(base_url=API_URL, timeout=30.0, follow_redirects=False)


def begin(c: httpx.Client) -> str:
    r = c.get("/auth/google/start")
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["scope"] == ["openid email profile"] and q["response_type"] == ["code"]
    assert c.cookies.get("vidhi_oauth") == q["state"][0]
    return q["state"][0]


def google_says(email: str, sub: str | None = None, name="Asha Verma", verified=True, bad_nonce=False) -> str:
    code = "code-" + uuid.uuid4().hex
    mongo().google_stub.insert_one({"code": code, "bad_nonce": bad_nonce, "claims": {"sub": sub or "g-" + uuid.uuid4().hex[:12], "email": email, "email_verified": verified, "name": name}})
    return code


def finish(c, state, code):
    return c.get("/auth/google/callback", params={"code": code, "state": state})


def test_options_say_google_is_available():
    with client() as c:
        assert c.get("/auth/options").json() == {"password": True, "google": True, "turnstile_site_key": None, "signup_mode": "open", "recovery": True}  # "recovery": the test server runs with Legal Recovery switched on (it is off by default)


def test_a_new_person_gets_an_account_and_is_signed_in():
    email = f"g-{uuid.uuid4().hex[:10]}@example.com"
    with client() as c:
        r = finish(c, begin(c), google_says(email))
        assert r.status_code == 302 and r.headers["location"].endswith("/start") and "vidhi_session" in c.cookies
        me = c.get("/auth/me").json()
        assert me["email"] == email and me["email_verified"] is True and me["role"] == "OWNER" and me["full_name"] == "Asha Verma"
    row = mongo().users.find_one({"email": email})
    assert row["auth_methods"] == ["google"] and row["plan"] == "FREE" and row["password_hash"]


def test_the_same_google_account_signs_in_again_without_a_second_account():
    email = f"g-{uuid.uuid4().hex[:10]}@example.com"
    sub = "g-" + uuid.uuid4().hex
    for _ in range(2):
        with client() as c:
            assert finish(c, begin(c), google_says(email, sub)).status_code == 302
            assert c.get("/auth/me").json()["email"] == email
    assert mongo().users.count_documents({"email": email}) == 1


def test_google_links_to_an_existing_password_account_with_the_same_verified_email(user_a):
    mongo().users.update_one({"id": user_a.user["id"]}, {"$set": {"email_verified": True}})  # the owner had already confirmed the address
    with client() as c:
        r = finish(c, begin(c), google_says(user_a.user["email"]))
        assert r.status_code == 302 and c.get("/auth/me").json()["id"] == user_a.user["id"]
    assert set(mongo().users.find_one({"id": user_a.user["id"]})["auth_methods"]) == {"google"}
    fresh = httpx.Client(base_url=API_URL, timeout=30.0)
    assert fresh.post("/auth/login", json={"email": user_a.user["email"], "password": user_a.password}).status_code == 200  # the password still works


def test_an_unverified_google_email_is_refused():
    with client() as c:
        r = finish(c, begin(c), google_says(f"u-{uuid.uuid4().hex[:8]}@example.com", verified=False))
        assert "error=google_failed" in r.headers["location"] and "vidhi_session" not in c.cookies


def test_a_wrong_nonce_is_refused():
    with client() as c:
        r = finish(c, begin(c), google_says(f"n-{uuid.uuid4().hex[:8]}@example.com", bad_nonce=True))
        assert "error=google_failed" in r.headers["location"]


def test_the_state_must_match_this_browser_and_works_once():
    with client() as a, client() as b:
        state = begin(a)
        code = google_says(f"s-{uuid.uuid4().hex[:8]}@example.com")
        b.cookies.set("vidhi_oauth", "some-other-state")
        assert "error=google_failed" in finish(b, state, code).headers["location"]  # another browser cannot finish it
        ok = finish(a, state, code)
        assert ok.headers["location"].endswith("/start")
        a2 = client()
        a2.cookies.set("vidhi_oauth", state)
        assert "error=google_failed" in finish(a2, state, google_says(f"s-{uuid.uuid4().hex[:8]}@example.com")).headers["location"]  # replay


def test_cancelling_at_google_returns_to_login():
    with client() as c:
        begin(c)
        r = c.get("/auth/google/callback", params={"error": "access_denied", "state": c.cookies.get("vidhi_oauth")})
        assert "error=google_cancelled" in r.headers["location"]


def test_accounts_with_two_step_must_use_their_password_and_code(user_a):
    _enable(user_a)
    with client() as c:
        r = finish(c, begin(c), google_says(user_a.user["email"]))
        assert "error=two_step_use_password" in r.headers["location"] and "vidhi_session" not in c.cookies


def test_claims_are_checked_strictly():
    good = {"iss": "https://accounts.google.com", "aud": "cid", "exp": time.time() + 60, "nonce": "n", "sub": "1", "email": "A@Example.com", "email_verified": True}
    assert google_auth.check_claims(good, "n", "cid")["email"] == "a@example.com"
    for bad in ({"iss": "https://evil.example"}, {"aud": "other"}, {"exp": time.time() - 5}, {"nonce": "x"}, {"email_verified": False}, {"sub": ""}):
        with pytest.raises(ValueError):
            google_auth.check_claims({**good, **bad}, "n", "cid")


# ---- people stay signed in ----
def test_an_active_session_is_renewed_before_it_runs_out(user_a):
    assert SESSION_DAYS == 30
    token = user_a.cookies.get("vidhi_session")
    import hashlib

    digest = hashlib.sha256(token.encode()).hexdigest()
    mongo().sessions.update_one({"token_hash": digest}, {"$set": {"expires_at": datetime.now(timezone.utc) + timedelta(days=2)}})
    r = user_a.get("/auth/me")
    assert r.status_code == 200 and "vidhi_session" in r.headers.get("set-cookie", "")
    exp = mongo().sessions.find_one({"token_hash": digest})["expires_at"].replace(tzinfo=timezone.utc)
    assert exp > datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS - 1)


def test_a_fresh_session_is_not_touched_on_every_request(user_a):
    r = user_a.get("/auth/me")
    assert "set-cookie" not in r.headers

def test_linking_google_to_an_unverified_password_account_locks_out_whoever_set_that_password():
    """Pre-registration attack: an attacker signs up with the victim's email first. When the real owner signs in with Google, the attacker's access must end."""
    email = f"victim-{uuid.uuid4().hex[:8]}@example.com"
    attacker = httpx.Client(base_url=API_URL, timeout=30.0)
    pw = f"Pw-{uuid.uuid4().hex}"
    assert attacker.post("/auth/signup", json={"email": email, "password": pw, "full_name": "Not The Owner", "organization_name": "X", "accept_privacy": True}).status_code == 200
    assert not mongo().users.find_one({"email": email}).get("email_verified")
    assert attacker.get("/auth/me").status_code == 200
    with client() as owner:
        assert finish(owner, begin(owner), google_says(email)).status_code == 302
        assert owner.get("/auth/me").json()["email"] == email
    assert attacker.get("/auth/me").status_code == 401  # the attacker's session is gone
    fresh = httpx.Client(base_url=API_URL, timeout=30.0)
    assert fresh.post("/auth/login", json={"email": email, "password": pw}).status_code == 401  # and so is the password


def test_a_verified_account_keeps_its_password_when_google_is_linked(user_a):
    mongo().users.update_one({"id": user_a.user["id"]}, {"$set": {"email_verified": True}})
    with client() as c:
        assert finish(c, begin(c), google_says(user_a.user["email"])).status_code == 302
    fresh = httpx.Client(base_url=API_URL, timeout=30.0)
    assert fresh.post("/auth/login", json={"email": user_a.user["email"], "password": user_a.password}).status_code == 200
