"""Two-step sign-in with an authenticator app (RFC 6238) and one-time recovery codes."""

import httpx

from lib import totp
from tests.conftest import API_URL, mongo

# RFC 6238 appendix B test vector (secret "12345678901234567890", SHA-1): the code at T=59 is 94287082 -> last 6 digits
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # secret-scan: ok (fake test value)


def test_rfc_6238_vector():
    assert totp.code_at(RFC_SECRET, 59) == "287082"
    assert totp.code_at(RFC_SECRET, 1111111109) == "081804"
    assert totp.code_at(RFC_SECRET, 1234567890) == "005924"


def test_a_code_works_once_and_tolerates_a_little_clock_drift():
    s = totp.new_secret()
    t = 1_700_000_000
    step = totp.verify(s, totp.code_at(s, t), at=t)
    assert step == totp.current_step(t)
    assert totp.verify(s, totp.code_at(s, t), last_step=step, at=t) is None  # replay refused
    assert totp.verify(s, totp.code_at(s, t - 30), at=t) is not None  # one step old
    assert totp.verify(s, totp.code_at(s, t - 120), at=t) is None  # too old
    assert totp.verify(s, "12345", at=t) is None and totp.verify(s, "abcdef", at=t) is None


def _confirmed(c) -> None:
    """Two-step sign-in can only be turned on once the email address is confirmed (see test_audit_findings)."""
    from tests.conftest import verify_email

    if not c.get("/auth/me").json().get("email_verified"):
        verify_email(c)


def _enable(c) -> tuple[str, list[str]]:
    _confirmed(c)
    setup = c.post("/auth/2fa/setup")
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/VIDHI:") and secret in setup.json()["otpauth_uri"]
    r = c.post("/auth/2fa/enable", json={"code": totp.code_at(secret)})
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


def _login(c, **extra):
    fresh = httpx.Client(base_url=API_URL, timeout=30.0)
    r = fresh.post("/auth/login", json={"email": c.user["email"], "password": c.password, **extra})
    return fresh, r


def _next_code(secret: str) -> str:
    """A valid code for a LATER step than any used so far (the server accepts each step once)."""
    return totp.code_at(secret, totp.current_step() * totp.STEP + totp.STEP)


def test_setup_does_nothing_until_the_app_proves_it_works(user_a):
    _confirmed(user_a)
    user_a.post("/auth/2fa/setup")
    assert user_a.get("/auth/me").json()["two_factor"] is False
    assert user_a.post("/auth/2fa/enable", json={"code": "000000"}).status_code == 400
    assert user_a.get("/auth/me").json()["two_factor"] is False
    _, r = _login(user_a)
    assert r.status_code == 200  # still just a password


def test_after_enabling_a_password_alone_is_not_enough(user_a):
    secret, codes = _enable(user_a)
    assert user_a.get("/auth/me").json()["two_factor"] is True and len(codes) == 8
    _, r = _login(user_a)
    assert r.status_code == 428 and "6-digit" in r.json()["detail"]
    _, bad = _login(user_a, otp="000000")
    assert bad.status_code == 401
    _, wrong_pw = _login(user_a, otp="123456")
    assert wrong_pw.status_code in (401, 428)
    good, ok = _login(user_a, otp=_next_code(secret))
    assert ok.status_code == 200 and ok.json()["two_factor"] is True
    assert good.get("/auth/me").status_code == 200


def test_a_code_cannot_be_used_twice(user_a):
    secret, _ = _enable(user_a)
    code = _next_code(secret)
    assert _login(user_a, otp=code)[1].status_code == 200
    assert _login(user_a, otp=code)[1].status_code == 401


def test_the_secret_is_not_stored_in_plain_text(user_a):
    secret, codes = _enable(user_a)
    doc = mongo().users.find_one({"id": user_a.user["id"]})
    blob = repr(doc["two_factor"])
    assert secret not in blob
    assert not any(c in blob or c.replace("-", "") in blob for c in codes)  # recovery codes are kept only as hashes


def test_a_recovery_code_works_once(user_a):
    _, codes = _enable(user_a)
    assert _login(user_a, otp=codes[0])[1].status_code == 200
    assert _login(user_a, otp=codes[0])[1].status_code == 401
    assert _login(user_a, otp=codes[1].lower().replace("-", ""))[1].status_code == 200  # spacing and case do not matter


def test_wrong_codes_are_rate_limited(user_a):
    _enable(user_a)
    statuses = [_login(user_a, otp=f"{i:06d}")[1].status_code for i in range(14)]
    assert 429 in statuses


def test_turning_it_off_needs_the_password_and_a_code(user_a):
    secret, _ = _enable(user_a)
    assert user_a.post("/auth/2fa/disable", json={"password": "nope", "code": _next_code(secret)}).status_code == 403
    assert user_a.post("/auth/2fa/disable", json={"password": user_a.password, "code": "000000"}).status_code == 400
    r = user_a.post("/auth/2fa/disable", json={"password": user_a.password, "code": _next_code(secret)})
    assert r.status_code == 200
    assert user_a.get("/auth/me").json()["two_factor"] is False
    assert _login(user_a)[1].status_code == 200


def test_new_recovery_codes_replace_the_old_ones(user_a):
    secret, old = _enable(user_a)
    r = user_a.post("/auth/2fa/recovery-codes", json={"password": user_a.password, "code": _next_code(secret)})
    assert r.status_code == 200
    new = r.json()["recovery_codes"]
    assert len(new) == 8 and not set(new) & set(old)
    assert _login(user_a, otp=old[0])[1].status_code == 401
    assert _login(user_a, otp=new[0])[1].status_code == 200


def test_cannot_set_up_twice_and_needs_sign_in(user_a, anon):
    _enable(user_a)
    assert user_a.post("/auth/2fa/setup").status_code == 409
    for path, body in (("setup", {}), ("enable", {"code": "123456"}), ("disable", {"password": "x", "code": "123456"})):
        assert anon.post(f"/auth/2fa/{path}", json=body).status_code in (401, 403)


def test_two_step_is_per_account(user_a, user_b):
    _enable(user_a)
    assert user_b.get("/auth/me").json()["two_factor"] is False
    assert _login(user_b)[1].status_code == 200
