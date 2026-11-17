"""Where you are signed in, sign-in alerts, bot protection at signup, and two-step sign-in for team owners."""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from lib import botcheck, devices
from tests.conftest import API_URL, mongo, new_member, outbox
from tests.test_twofactor import _enable

CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
SAFARI_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0"


def run(c):
    return asyncio.run(c)


def client(ua: str) -> httpx.Client:
    return httpx.Client(base_url=API_URL, timeout=30.0, headers={"User-Agent": ua})


def sign_in(user, ua):
    c = client(ua)
    r = c.post("/auth/login", json={"email": user.user["email"], "password": user.password})
    assert r.status_code == 200, r.text
    return c


# ---- describing devices ----
def test_devices_are_described_in_plain_words():
    assert devices.describe(CHROME_WIN) == "Chrome on Windows"
    assert devices.describe(SAFARI_IPHONE) == "Safari on iPhone or iPad"
    assert devices.describe(FIREFOX_LINUX) == "Firefox on Linux"
    assert devices.describe("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36") == "Chrome on Android"
    assert devices.describe("Mozilla/5.0 ... Edg/126.0") .startswith("Edge") and devices.describe(None) == "A browser on an unknown device"
    assert devices.fingerprint(CHROME_WIN) == devices.fingerprint(CHROME_WIN.replace("126.0.0.0", "127.0.0.0"))  # a browser update is the same device
    assert devices.fingerprint(CHROME_WIN) != devices.fingerprint(FIREFOX_LINUX)


def test_only_part_of_an_address_is_kept():
    assert devices.mask_ip("203.0.113.57") == "203.0.113.x" and devices.mask_ip("2001:db8:1:2::5") == "2001:0db8:0001:x"
    assert devices.mask_ip("not an ip") == "unknown" and devices.mask_ip(None) == "unknown"


# ---- the session list ----
def test_you_can_see_every_place_you_are_signed_in_and_end_one(user_a):
    other = sign_in(user_a, SAFARI_IPHONE)
    rows = user_a.get("/auth/sessions").json()
    assert len(rows) == 2 and rows[0]["current"] is True and rows[1]["current"] is False
    phone = next(r for r in rows if not r["current"])
    assert phone["device"] == "Safari on iPhone or iPad" and phone["network"].endswith(".x") and "token" not in str(rows)
    assert other.get("/auth/me").status_code == 200
    assert user_a.delete(f"/auth/sessions/{phone['id']}").json() == {"ok": True, "was_current": False}
    assert other.get("/auth/me").status_code == 401  # that device is signed out at once
    assert len(user_a.get("/auth/sessions").json()) == 1


def test_you_cannot_see_or_end_someone_elses_session(user_a, user_b):
    theirs = user_b.get("/auth/sessions").json()[0]["id"]
    assert user_a.delete(f"/auth/sessions/{theirs}").status_code == 404
    assert theirs not in [s["id"] for s in user_a.get("/auth/sessions").json()]
    assert user_b.get("/auth/me").status_code == 200


def test_ending_the_current_session_signs_you_out(user_a):
    me = next(s for s in user_a.get("/auth/sessions").json() if s["current"])
    assert user_a.delete(f"/auth/sessions/{me['id']}").json()["was_current"] is True
    assert user_a.get("/auth/me").status_code == 401


def test_sessions_need_sign_in(anon):
    assert anon.get("/auth/sessions").status_code in (401, 403) and anon.delete("/auth/sessions/x").status_code in (401, 403)


# ---- alerts ----
def confirm(user):
    mongo().users.update_one({"id": user.user["id"]}, {"$set": {"email_verified": True}})


def test_a_new_device_triggers_an_alert_and_a_known_one_does_not(user_a):
    confirm(user_a)
    sign_in(user_a, CHROME_WIN)  # the first device after signing up is just remembered... (signup was from httpx's own agent)
    before = len(outbox(to=user_a.user["email"], subject_has="New sign-in"))
    sign_in(user_a, FIREFOX_LINUX)
    mails = outbox(to=user_a.user["email"], subject_has="New sign-in")
    assert len(mails) == before + 1
    body = mails[-1]["html"]
    assert "Firefox on Linux" in body and ".x" in body and "change your password" in body and "token" not in body.lower()
    sign_in(user_a, FIREFOX_LINUX)
    assert len(outbox(to=user_a.user["email"], subject_has="New sign-in")) == before + 1  # same device again: quiet


def test_no_alert_goes_to_an_unconfirmed_address_or_for_the_first_device(user_a):
    sign_in(user_a, SAFARI_IPHONE)
    assert outbox(to=user_a.user["email"], subject_has="New sign-in") == []  # not confirmed: it might not be their inbox


def test_password_and_two_step_changes_are_announced(user_a):
    confirm(user_a)
    new_pw = "Another-Strong-Pass-" + uuid.uuid4().hex[:6]
    assert user_a.post("/auth/change-password", json={"current_password": user_a.password, "new_password": new_pw}).status_code == 200
    assert outbox(to=user_a.user["email"], subject_has="password was changed")
    secret, _ = _enable(user_a)
    assert outbox(to=user_a.user["email"], subject_has="turned on")


# ---- bot protection ----
def test_the_fallback_check_stops_simple_bots():
    assert run(botcheck.human(None, "1.2.3.4", honeypot="http://spam")) is False  # a field only a bot fills
    assert run(botcheck.human(None, "1.2.3.4", elapsed_ms=200)) is False  # submitted faster than a person can
    assert run(botcheck.human(None, "1.2.3.4", elapsed_ms=5000)) is True and run(botcheck.human(None, "1.2.3.4")) is True


@pytest.fixture
def turnstile(monkeypatch):
    seen = {}

    def make(handler):
        monkeypatch.setattr(botcheck, "_TRANSPORT", httpx.MockTransport(handler))
        monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret")
        monkeypatch.setenv("TURNSTILE_SITE_KEY", "site-key")
        return seen

    return make


def test_turnstile_must_confirm_the_token_with_cloudflare(turnstile):
    seen = {}

    def ok(request):
        seen["form"] = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(200, json={"success": True})

    turnstile(ok)
    assert botcheck.configured() and botcheck.site_key() == "site-key"
    assert run(botcheck.human("good-token", "1.2.3.4")) is True
    assert seen["form"]["secret"] == "secret" and seen["form"]["response"] == "good-token" and seen["form"]["remoteip"] == "1.2.3.4"
    assert run(botcheck.human(None, "1.2.3.4")) is False and run(botcheck.human("x" * 5000, "1.2.3.4")) is False  # no token, absurd token
    assert run(botcheck.human("t", "1.2.3.4", honeypot="bot")) is False


def test_turnstile_failures_never_let_anyone_in(turnstile):
    turnstile(lambda r: httpx.Response(200, json={"success": False}))
    assert run(botcheck.human("t", None)) is False
    turnstile(lambda r: httpx.Response(500, json={}))
    assert run(botcheck.human("t", None)) is False

    def down(request):
        raise httpx.ConnectError("no network")

    turnstile(down)
    assert run(botcheck.human("t", None)) is False  # Cloudflare unreachable: fail closed


def test_signup_rejects_a_filled_trap_and_an_instant_submit(anon):
    base = {"password": "Str0ng-pass-" + uuid.uuid4().hex[:6], "full_name": "Bot", "organization_name": "Bot Org", "accept_privacy": True}
    assert anon.post("/auth/signup", json={**base, "email": f"b-{uuid.uuid4().hex[:8]}@example.com", "website": "http://spam.example"}).status_code == 400
    assert anon.post("/auth/signup", json={**base, "email": f"b-{uuid.uuid4().hex[:8]}@example.com", "elapsed_ms": 50}).status_code == 400
    ok = anon.post("/auth/signup", json={**base, "email": f"b-{uuid.uuid4().hex[:8]}@example.com", "elapsed_ms": 6000})
    assert ok.status_code == 200


# ---- two-step sign-in for team owners ----
def team_owner(user_a):
    confirm(user_a)
    new_member(user_a, "LAWYER")
    return user_a


def test_a_solo_owner_is_never_required_to_use_two_step(user_a):
    mongo().users.update_one({"id": user_a.user["id"]}, {"$set": {"two_step_due_at": datetime.now(timezone.utc) - timedelta(days=30)}})
    assert user_a.get("/matters").status_code == 200
    me = user_a.get("/auth/me").json()
    assert me["two_step_required"] is False


def test_a_team_owner_gets_a_grace_period_then_is_asked_to_turn_it_on(user_a):
    team_owner(user_a)
    me = user_a.get("/auth/me").json()
    assert me["two_step_required"] is True and me["two_step_due_at"]
    due = datetime.fromisoformat(me["two_step_due_at"])
    assert timedelta(days=6) < due - datetime.now(timezone.utc) <= timedelta(days=7, minutes=1)
    assert user_a.get("/matters").status_code == 200  # still in the grace period
    mongo().users.update_one({"id": user_a.user["id"]}, {"$set": {"two_step_due_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    blocked = user_a.get("/matters")
    assert blocked.status_code == 403 and "Two-step sign-in is now required" in blocked.json()["detail"]
    assert user_a.get("/research").status_code == 403 and user_a.post("/matters", json={"title": "x", "parties": "", "description": ""}).status_code == 403


def test_the_way_out_stays_open_and_turning_it_on_restores_everything(user_a):
    team_owner(user_a)
    mongo().users.update_one({"id": user_a.user["id"]}, {"$set": {"two_step_due_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    assert user_a.get("/auth/me").status_code == 200 and user_a.get("/auth/sessions").status_code == 200  # account routes stay open
    assert user_a.post("/public/support", json={"name": "A", "email": user_a.user["email"], "message": "Help me with two-step"}).status_code == 200
    assert user_a.get("/privacy/requests").status_code == 200
    _enable(user_a)
    assert user_a.get("/matters").status_code == 200
    me = user_a.get("/auth/me").json()
    assert me["two_factor"] is True and me["two_step_required"] is False


def test_team_members_who_are_not_owners_or_admins_are_not_affected(user_a):
    team_owner(user_a)
    lawyer = new_member(user_a, "LAWYER")
    mongo().users.update_one({"id": lawyer.user["id"]}, {"$set": {"two_step_due_at": datetime.now(timezone.utc) - timedelta(days=9)}})
    assert lawyer.get("/matters").status_code == 200 and lawyer.get("/auth/me").json()["two_step_required"] is False


def test_an_admin_of_a_team_is_covered_too(user_a):
    team_owner(user_a)
    admin = new_member(user_a, "ADMIN")
    assert admin.get("/auth/me").json()["two_step_required"] is True
    mongo().users.update_one({"id": admin.user["id"]}, {"$set": {"two_step_due_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    assert admin.get("/matters").status_code == 403


# ---- automatic dependency updates ----
def test_dependabot_covers_every_ecosystem_we_use():
    path = os.path.join(os.path.abspath(os.path.dirname(__file__)), "..", "..", ".github", "dependabot.yml")
    text = open(path, encoding="utf-8").read()
    for eco in ("pip", "npm", "github-actions", "docker"):
        assert f"package-ecosystem: {eco}" in text