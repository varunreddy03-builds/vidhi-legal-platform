"""Lets the Android app (which is not on the API's own origin) sign in without cookies.

A request that carries the header ``X-VIDHI-App: 1`` is treated as coming from the app:
- ``Authorization: Bearer <token>`` is turned into the normal session cookie before the request is handled, so every
  route and permission check works unchanged (the token is the same random, hashed-at-rest session token).
- A session cookie the server sets (login, sign-up, invite, 2FA ...) is also returned in the ``X-VIDHI-Token`` header
  (empty when the cookie is being cleared, e.g. on log out) so the app can keep it.
Cookies are never used for these requests, so another website cannot make the browser send them (no cross-site request
forgery), and browsers keep using the httpOnly cookie exactly as before.
"""

from lib.auth import COOKIE_NAME

APP_HEADER = "x-vidhi-app"
TOKEN_HEADER = "X-VIDHI-Token"


def _session_cookie_value(set_cookie: str) -> str | None:
    """The session token in a Set-Cookie line, "" when that line deletes it, None when it is another cookie."""
    first, _, rest = set_cookie.partition(";")
    name, _, value = first.partition("=")
    if name.strip() != COOKIE_NAME:
        return None
    lowered = rest.lower().replace(" ", "")
    if not value.strip('"') or "max-age=0" in lowered:
        return ""
    return value.strip('"')


async def native_token_bridge(request, call_next):
    is_app = request.headers.get(APP_HEADER) == "1"
    if is_app:
        headers = [(k, v) for k, v in request.scope["headers"] if k not in (b"cookie", b"authorization")]
        auth = request.headers.get("authorization", "")
        if auth[:7].lower() == "bearer " and auth[7:].strip():
            headers.append((b"cookie", f"{COOKIE_NAME}={auth[7:].strip()}".encode("latin-1")))
        request.scope["headers"] = headers
    response = await call_next(request)
    if is_app:
        for key, value in response.raw_headers:
            if key.lower() == b"set-cookie":
                token = _session_cookie_value(value.decode("latin-1"))
                if token is not None:
                    response.headers[TOKEN_HEADER] = token
    return response
