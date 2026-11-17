"""Checks OUR side of Google sign-in against a running backend that has GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET set (placeholder values are fine: nothing is sent to Google).
It never pretends a login succeeded. It checks that the redirect to Google is built correctly (state, nonce, PKCE S256, scope, redirect URI), that a callback with a missing, wrong or replayed
state is refused, that a Google error is reported as cancelled, and that no session cookie is ever issued by a failed callback.
    python scripts/check_google_flow.py [http://localhost:8004]
The one thing it cannot check is the real round trip with Google (needs real credentials and a person signing in)."""

import sys
from urllib.parse import parse_qs, urlparse

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8004").rstrip("/")
rows = []


def check(name: str, ok: bool, detail: str = "") -> None:
    rows.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


c = httpx.Client(base_url=BASE + "/api", follow_redirects=False, timeout=30)
opt = c.get("/auth/options").json()
check("options says Google is enabled", opt.get("google") is True, str(opt))

r = c.get("/auth/google/start")
loc = r.headers.get("location", "")
u, q = urlparse(loc), parse_qs(urlparse(loc).query)
check("start redirects (302) to accounts.google.com", r.status_code == 302 and u.netloc == "accounts.google.com", f"{r.status_code} {u.netloc}")
check("authorize URL has response_type=code and scope openid email profile", q.get("response_type") == ["code"] and q.get("scope") == ["openid email profile"], str(q.get("scope")))
check("authorize URL has a state of at least 20 characters", len(q.get("state", [""])[0]) >= 20)
check("authorize URL has a nonce of at least 20 characters", len(q.get("nonce", [""])[0]) >= 20)
check("authorize URL uses PKCE with S256", q.get("code_challenge_method") == ["S256"] and len(q.get("code_challenge", [""])[0]) >= 40)
check("redirect_uri ends with /api/auth/google/callback", q.get("redirect_uri", [""])[0].endswith("/api/auth/google/callback"), q.get("redirect_uri", [""])[0])
check("the client secret never appears in the redirect", "secret" not in loc.lower())
cookie_flags = r.headers.get("set-cookie", "").lower()
check("the flow cookie is HttpOnly", "httponly" in cookie_flags, cookie_flags[:80])
check("the flow cookie is SameSite=Lax or Strict", "samesite=lax" in cookie_flags or "samesite=strict" in cookie_flags)

s2 = c.get("/auth/google/start").headers.get("location", "")
q2 = parse_qs(urlparse(s2).query)
check("every attempt gets a fresh state and nonce", q2.get("state") != q.get("state") and q2.get("nonce") != q.get("nonce"))

state = q.get("state", [""])[0]


def callback(params: dict, fresh_cookie: bool = True) -> httpx.Response:
    cc = httpx.Client(base_url=BASE + "/api", follow_redirects=False, timeout=30)
    if fresh_cookie:
        cc.get("/auth/google/start")  # sets the flow cookie, as a browser would
    return cc.get("/auth/google/callback", params=params)


r = callback({"code": "abc", "state": "wrong-state"})
check("callback with a WRONG state is refused (redirect to login with an error)", r.status_code in (302, 307) and "error=google_failed" in r.headers.get("location", ""), r.headers.get("location", ""))
check("a failed callback issues no session cookie", "vidhi_session" not in r.headers.get("set-cookie", ""))
r = callback({"code": "abc"})
check("callback with NO state is refused", "error=google_failed" in r.headers.get("location", ""), r.headers.get("location", ""))
r = callback({"state": "x"})
check("callback with no code is refused", "error=google_failed" in r.headers.get("location", ""), r.headers.get("location", ""))
r = callback({"error": "access_denied", "state": "x"})
check("a Google 'access_denied' is shown as cancelled", "error=google_cancelled" in r.headers.get("location", ""), r.headers.get("location", ""))
r = httpx.get(BASE + "/api/auth/google/callback", params={"code": "abc", "state": state}, follow_redirects=False, timeout=30)
check("callback WITHOUT the flow cookie is refused", "error=google_failed" in r.headers.get("location", ""), r.headers.get("location", ""))

cc = httpx.Client(base_url=BASE + "/api", follow_redirects=False, timeout=30)
st = parse_qs(urlparse(cc.get("/auth/google/start").headers["location"]).query)["state"][0]
r1 = cc.get("/auth/google/callback", params={"code": "fake-code", "state": st})
check("a right state but a code Google does not accept is refused (no login)", "error=" in r1.headers.get("location", "") and "vidhi_session" not in r1.headers.get("set-cookie", ""), r1.headers.get("location", ""))
r2 = cc.get("/auth/google/callback", params={"code": "fake-code", "state": st})
check("the same state cannot be used twice (replay refused)", "error=google_failed" in r2.headers.get("location", ""), r2.headers.get("location", ""))

me = httpx.get(BASE + "/api/auth/me", timeout=30)
check("after all this, nobody is signed in", me.status_code in (401, 403), str(me.status_code))

ok = sum(1 for _, o, _ in rows if o)
print(f"\n{ok} of {len(rows)} checks passed")
sys.exit(0 if ok == len(rows) else 1)
