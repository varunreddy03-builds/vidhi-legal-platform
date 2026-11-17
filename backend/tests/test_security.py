"""Phase 1 security fixes (AUDIT.md S1-S9, S11). Each test guards one fix against regression."""

import io
import os
import uuid
import zipfile

import httpx
import pytest
from pymongo import MongoClient

from tests.conftest import API_URL

APP_ORIGIN = os.environ.get("APP_URL", "http://localhost:3000")


def _mongo():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


# ---------- S1 / S6: removed routes ----------
def test_self_upgrade_endpoint_is_gone(user_a):
    assert user_a.post("/auth/entitlement/upgrade").status_code in (404, 405)
    from tests.conftest import set_plan

    set_plan(user_a, "FREE")
    assert user_a.get("/auth/entitlement").json()["plan"] != "PRO"


def test_template_status_routes_removed(anon):
    assert anon.get("/status").status_code == 404
    assert anon.post("/status", json={"client_name": "x"}).status_code == 404


def test_health_is_public_and_minimal(anon):
    r = anon.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


# ---------- S7: search is literal ----------
def test_search_treats_input_as_literal(user_a):
    user_a.post("/matters", json={"title": "Smith (No. 1) [draft]"})
    assert user_a.get("/search", params={"q": "(["}).status_code == 200
    groups = user_a.get("/search", params={"q": "(No. 1)"}).json()["groups"]
    assert any(g["type"] == "Matters" and g["items"] for g in groups)


# ---------- S3: CORS ----------
def test_cors_does_not_reflect_arbitrary_origin(user_a):
    r = user_a.get("/auth/me", headers={"Origin": "https://evil.example"})
    assert r.headers.get("access-control-allow-origin") not in ("https://evil.example", "*")


def test_cors_allows_the_configured_origin(user_a):
    r = user_a.get("/auth/me", headers={"Origin": APP_ORIGIN})
    assert r.headers.get("access-control-allow-origin") == APP_ORIGIN
    assert r.headers.get("access-control-allow-credentials") == "true"


# ---------- headers / docs ----------
def test_security_headers_present(user_a):
    h = user_a.get("/auth/me").headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["cache-control"] == "no-store"


def test_api_docs_disabled_by_default(anon):
    base = API_URL.removesuffix("/api")
    assert httpx.get(f"{base}/docs").status_code == 404
    assert httpx.get(f"{base}/openapi.json").status_code == 404


# ---------- S4: cookie flags ----------
def test_cookie_is_secure_by_default(monkeypatch):
    from lib.auth import cookie_kwargs

    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    kw = cookie_kwargs()
    assert kw["secure"] is True and kw["httponly"] is True and kw["samesite"] == "lax"
    monkeypatch.setenv("COOKIE_SECURE", "false")
    assert cookie_kwargs()["secure"] is False  # explicit opt-out for plain-http local dev


# ---------- S5: rate limiting ----------
def test_login_is_rate_limited(anon):
    email = f"nobody-{uuid.uuid4().hex[:8]}@example.com"
    codes = []
    last = None
    for _ in range(14):
        last = anon.post("/auth/login", json={"email": email, "password": "wrong-password-1"})
        codes.append(last.status_code)
    assert codes[0] == 401 and 429 in codes
    assert last.headers.get("retry-after")


def test_unknown_email_and_wrong_password_look_identical(user_a, anon):
    wrong = anon.post("/auth/login", json={"email": user_a.user["email"], "password": "not-the-password-1"})
    unknown = anon.post(
        "/auth/login", json={"email": f"x-{uuid.uuid4().hex[:8]}@example.com", "password": "not-the-password-1"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


# ---------- passwords ----------
def test_password_hash_is_bcrypt_and_handles_long_passphrases():
    from lib.auth import hash_password, needs_rehash, verify_password

    long_a = "a" * 80 + "X"
    h = hash_password(long_a)
    assert h.startswith("$2") and not needs_rehash(h)
    assert verify_password(long_a, h)
    assert not verify_password("a" * 80 + "Y", h)  # char past bcrypt's 72-byte limit still counts


def test_legacy_pbkdf2_hashes_still_verify_and_are_upgraded_on_login(user_a):
    from lib.auth import _legacy_hash, needs_rehash, verify_password

    legacy = _legacy_hash("Legacy-Pass-12345", "abcdef0123456789")
    assert needs_rehash(legacy) and verify_password("Legacy-Pass-12345", legacy)

    db = _mongo()
    db.users.update_one({"id": user_a.user["id"]}, {"$set": {"password_hash": legacy}})
    with httpx.Client(base_url=API_URL) as c:
        r = c.post("/auth/login", json={"email": user_a.user["email"], "password": "Legacy-Pass-12345"})
    assert r.status_code == 200
    assert db.users.find_one({"id": user_a.user["id"]})["password_hash"].startswith("$2")


@pytest.mark.parametrize("pw", ["short1", "password123", "aaaaaaaaaaaa", "1234567890"])
def test_weak_passwords_rejected_at_signup(anon, pw):
    r = anon.post(
        "/auth/signup",
        json={"email": f"w-{uuid.uuid4().hex[:8]}@example.com", "password": pw, "full_name": "W", "organization_name": "W", "accept_privacy": True},
    )
    assert r.status_code == 422


# ---------- sessions ----------
def test_session_token_is_stored_hashed_and_logout_revokes_it(user_a):
    db = _mongo()
    raw = user_a.cookies.get("vidhi_session")
    assert raw
    assert db.sessions.find_one({"token": raw}) is None
    assert db.sessions.find_one({"token_hash": {"$exists": True}, "user_id": user_a.user["id"]})
    assert user_a.post("/auth/logout").status_code == 200
    with httpx.Client(base_url=API_URL, cookies={"vidhi_session": raw}) as c:
        assert c.get("/auth/me").status_code == 401


def test_session_and_rate_limit_ttl_indexes_exist(user_a):
    db = _mongo()
    assert db.sessions.index_information()["expires_ttl"]["expireAfterSeconds"] == 0
    assert db.rate_limits.index_information()["expires_ttl"]["expireAfterSeconds"] == 0


# ---------- S9: uploads ----------
def _matter(c):
    return c.post("/matters", json={"title": "Upload test"}).json()["id"]


def test_upload_content_must_match_extension(user_a):
    m = _matter(user_a)
    up = lambda name, data: user_a.post(f"/matters/{m}/documents", files={"file": (name, data)})  # noqa: E731
    assert up("fake.pdf", b"this is not a pdf").status_code == 415
    assert up("fake.docx", b"PK\x03\x04 garbage").status_code == 415
    assert up("bin.txt", b"hello\x00world").status_code == 415
    assert up("run.txt", b"MZ\x90\x00 evil").status_code == 415
    assert up("page.html", b"<script>1</script>").status_code == 415
    assert up("ok.txt", b"A normal text note.").status_code == 200


def test_docx_with_too_many_entries_is_rejected(user_a):
    m = _matter(user_a)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
        for i in range(3100):
            z.writestr(f"x/{i}.txt", "")
    r = user_a.post(f"/matters/{m}/documents", files={"file": ("bomb.docx", buf.getvalue())})
    assert r.status_code == 415


def test_upload_filename_is_sanitised(user_a):
    m = _matter(user_a)
    r = user_a.post(f"/matters/{m}/documents", files={"file": ("../../etc/evil.txt", b"hello there")})
    assert r.status_code == 200 and r.json()["filename"] == "evil.txt"


def test_oversize_upload_rejected(user_a):
    m = _matter(user_a)
    r = user_a.post(f"/matters/{m}/documents", files={"file": ("big.txt", b"a" * (15 * 1024 * 1024 + 10))})
    assert r.status_code == 413


def test_proof_and_logo_uploads_check_content(user_a):
    case = user_a.post("/recovery/cases", json={"creditor_name": "A", "debtor_name": "B"}).json()["id"]
    assert user_a.post(f"/recovery/cases/{case}/proofs", files={"file": ("p.png", b"not a png")}).status_code == 415
    assert user_a.post("/org/logo", files={"file": ("l.png", b"not a png")}).status_code == 415


# ---------- S8: payment redirect ----------
def test_checkout_rejects_foreign_return_address(user_a):
    r = user_a.post("/payments/checkout", json={"package_id": "vidhi_pro", "origin_url": "https://evil.example"})
    assert r.status_code == 400


# ---------- input bounds ----------
def test_money_and_snooze_inputs_are_bounded(user_a):
    case = user_a.post("/recovery/cases", json={"creditor_name": "A", "debtor_name": "B", "amount": 10}).json()["id"]
    assert user_a.post(f"/recovery/cases/{case}/payment", json={"amount": 0}).status_code == 422
    assert user_a.post(f"/recovery/cases/{case}/payment", json={"amount": 1e30}).status_code == 422
    assert user_a.patch(f"/recovery/cases/{case}/reminders", json={"snooze_days": 10**9}).status_code == 422
    assert user_a.post("/recovery/cases", json={"creditor_name": "A", "debtor_name": "B", "amount": -5}).status_code == 422
    assert user_a.post(f"/recovery/cases/{case}/payment", json={"amount": 5}).status_code == 200
