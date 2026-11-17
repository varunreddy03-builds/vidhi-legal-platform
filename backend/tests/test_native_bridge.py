"""The Android app signs in with a bearer token (X-VIDHI-App) instead of cookies."""

import uuid

import httpx

from tests.conftest import API_URL

APP = {"X-VIDHI-App": "1"}


def _signup(c: httpx.Client, extra_headers: dict) -> httpx.Response:
    tag = uuid.uuid4().hex[:12]
    return c.post(
        "/auth/signup",
        headers=extra_headers,
        json={"email": f"app-{tag}@example.com", "password": f"Pw-{uuid.uuid4().hex}", "full_name": "App User", "organization_name": f"App Org {tag}", "accept_privacy": True},
    )


def test_app_gets_a_token_and_uses_it_without_cookies():
    with httpx.Client(base_url=API_URL, timeout=30.0) as c:
        r = _signup(c, APP)
        assert r.status_code == 200, r.text
        token = r.headers.get("x-vidhi-token")
        assert token and len(token) > 20
    with httpx.Client(base_url=API_URL, timeout=30.0) as fresh:  # no cookie jar contents at all
        assert fresh.get("/auth/me").status_code == 401
        me = fresh.get("/auth/me", headers={**APP, "Authorization": f"Bearer {token}"})
        assert me.status_code == 200, me.text
        assert "x-vidhi-token" not in me.headers  # only sent when the server sets the session cookie


def test_bearer_is_ignored_without_the_app_header_and_when_wrong():
    with httpx.Client(base_url=API_URL, timeout=30.0) as c:
        token = _signup(c, APP).headers["x-vidhi-token"]
    with httpx.Client(base_url=API_URL, timeout=30.0) as fresh:
        assert fresh.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401  # browsers never get this path
        assert fresh.get("/auth/me", headers={**APP, "Authorization": "Bearer not-a-real-token"}).status_code == 401


def test_browser_sign_up_does_not_expose_the_token():
    with httpx.Client(base_url=API_URL, timeout=30.0) as c:
        r = _signup(c, {})
        assert r.status_code == 200
        assert "x-vidhi-token" not in r.headers
        assert c.get("/auth/me").status_code == 200  # the cookie still works for browsers


def test_logout_clears_the_app_token():
    with httpx.Client(base_url=API_URL, timeout=30.0) as c:
        token = _signup(c, APP).headers["x-vidhi-token"]
    with httpx.Client(base_url=API_URL, timeout=30.0) as fresh:
        h = {**APP, "Authorization": f"Bearer {token}"}
        out = fresh.post("/auth/logout", headers=h)
        assert out.status_code == 200, out.text
        assert out.headers.get("x-vidhi-token") == ""
        assert fresh.get("/auth/me", headers=h).status_code == 401


def test_cors_allows_the_app_headers():
    r = httpx.options(
        f"{API_URL}/auth/me",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization,x-vidhi-app"},
        timeout=30.0,
    )
    assert r.status_code == 200
    allowed = r.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in allowed and "x-vidhi-app" in allowed
