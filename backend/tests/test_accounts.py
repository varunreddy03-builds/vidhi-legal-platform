"""Account security: password change, sign out everywhere, forgotten password, privacy acknowledgement."""

import time
import uuid

import httpx

from tests.conftest import API_URL, login_client, mongo, outbox, token_from_mail, wait_for_mail


def _fresh_user():
    email, pw = f"acct-{uuid.uuid4().hex[:10]}@example.com", "Pw-" + uuid.uuid4().hex
    c = httpx.Client(base_url=API_URL, timeout=30.0)
    r = c.post("/auth/signup", json={"email": email, "password": pw, "full_name": "Acct User", "organization_name": f"Org {uuid.uuid4().hex[:6]}", "accept_privacy": True})
    assert r.status_code == 200, r.text
    c.user, c.password = r.json(), pw
    return c


# ---------------- signup acknowledgement ----------------
def test_signup_requires_the_privacy_acknowledgement_and_records_it(anon):
    body = {"email": f"p-{uuid.uuid4().hex[:8]}@example.com", "password": "Pw-" + uuid.uuid4().hex, "full_name": "P", "organization_name": "P Org"}
    assert anon.post("/auth/signup", json=body).status_code == 422
    assert anon.post("/auth/signup", json={**body, "accept_privacy": False}).status_code == 422
    r = anon.post("/auth/signup", json={**body, "accept_privacy": True})
    assert r.status_code == 200 and r.json()["capabilities"] and r.json()["role"] == "OWNER"
    assert mongo().users.find_one({"email": body["email"]})["privacy_accepted_at"] is not None


# ---------------- change password ----------------
def test_change_password_ends_other_sessions_but_keeps_this_one():
    c1 = _fresh_user()
    c2 = login_client(c1.user["email"], c1.password)  # a second device
    new = "Pw-" + uuid.uuid4().hex
    assert c1.post("/auth/change-password", json={"current_password": "wrong-password-1", "new_password": new}).status_code == 403
    assert c1.post("/auth/change-password", json={"current_password": c1.password, "new_password": "password123"}).status_code == 422
    assert c1.post("/auth/change-password", json={"current_password": c1.password, "new_password": new}).status_code == 200
    assert c1.get("/auth/me").status_code == 200  # this session survives
    assert c2.get("/auth/me").status_code == 401  # the other device is signed out
    with httpx.Client(base_url=API_URL) as anon:
        assert anon.post("/auth/login", json={"email": c1.user["email"], "password": c1.password}).status_code == 401  # old password dead
    assert login_client(c1.user["email"], new).get("/auth/me").status_code == 200


def test_logout_all_ends_every_session():
    c1 = _fresh_user()
    c2 = login_client(c1.user["email"], c1.password)
    r = c1.post("/auth/logout-all")
    assert r.status_code == 200 and r.json()["sessions_ended"] >= 2
    assert c1.get("/auth/me").status_code == 401 and c2.get("/auth/me").status_code == 401


# ---------------- forgotten password ----------------
def test_forgot_password_never_reveals_whether_an_account_exists(anon):
    unknown = f"nobody-{uuid.uuid4().hex[:8]}@example.com"
    a = anon.post("/auth/forgot-password", json={"email": unknown})
    c = _fresh_user()
    b = anon.post("/auth/forgot-password", json={"email": c.user["email"]})
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    wait_for_mail(c.user["email"], "Reset your VIDHI password")
    time.sleep(0.5)
    assert outbox(to=unknown) == []  # nothing is sent for an unknown address


def test_reset_link_works_once_signs_everyone_out_and_proves_the_email(anon):
    c = _fresh_user()
    other = login_client(c.user["email"], c.password)
    anon.post("/auth/forgot-password", json={"email": c.user["email"]})
    mail = wait_for_mail(c.user["email"], "Reset your VIDHI password")
    token = token_from_mail(mail, "token=")
    new = "Pw-" + uuid.uuid4().hex
    assert anon.post("/auth/reset-password", json={"token": token, "new_password": "password123"}).status_code == 422  # weak: link still usable
    assert anon.post("/auth/reset-password", json={"token": token, "new_password": new}).status_code == 200
    assert anon.post("/auth/reset-password", json={"token": token, "new_password": new + "x"}).status_code == 400  # single use
    assert c.get("/auth/me").status_code == 401 and other.get("/auth/me").status_code == 401  # all sessions ended
    fresh = login_client(c.user["email"], new)
    assert fresh.get("/auth/me").json()["email_verified"] is True
    with httpx.Client(base_url=API_URL) as a2:
        assert a2.post("/auth/login", json={"email": c.user["email"], "password": c.password}).status_code == 401


def test_reset_links_expire_and_garbage_is_rejected(anon):
    from datetime import datetime, timedelta, timezone

    c = _fresh_user()
    anon.post("/auth/forgot-password", json={"email": c.user["email"]})
    token = token_from_mail(wait_for_mail(c.user["email"], "Reset your VIDHI password"), "token=")
    mongo().password_resets.update_many({"user_id": c.user["id"]}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    assert anon.post("/auth/reset-password", json={"token": token, "new_password": "Pw-" + uuid.uuid4().hex}).status_code == 400
    assert anon.post("/auth/reset-password", json={"token": "x" * 40, "new_password": "Pw-" + uuid.uuid4().hex}).status_code == 400


def test_forgot_password_is_rate_limited_per_address(anon):
    c = _fresh_user()
    codes = [anon.post("/auth/forgot-password", json={"email": c.user["email"]}).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and 429 in codes[3:]