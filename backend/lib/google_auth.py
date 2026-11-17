"""Sign in with Google (OpenID Connect, authorization-code flow with PKCE, state and nonce).

Configuration: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET (Google Cloud Console > APIs & Services > Credentials > OAuth client "Web application").
Authorized redirect URI to register there:  <APP_URL>/api/auth/google/callback  (or set GOOGLE_REDIRECT_URI).
GOOGLE_STUB=true is for tests/dev only: the 'code' is looked up in the database instead of being sent to Google.

The ID token is received directly from Google's token endpoint over TLS, which OpenID Connect Core 3.1.3.7 accepts in place of a signature
check; we still verify issuer, audience, expiry, nonce and that Google says the email is verified."""

import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
_TRANSPORT = None  # tests inject an httpx.MockTransport here


def stub_enabled() -> bool:
    return os.environ.get("GOOGLE_STUB", "false").lower() == "true"


def enabled() -> bool:
    return stub_enabled() or bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def redirect_uri() -> str:
    return os.environ.get("GOOGLE_REDIRECT_URI") or os.environ.get("APP_URL", "http://localhost:3000").rstrip("/") + "/api/auth/google/callback"


def new_flow() -> dict:
    """Fresh state, nonce and PKCE verifier for one sign-in attempt."""
    return {"state": secrets.token_urlsafe(24), "nonce": secrets.token_urlsafe(24), "verifier": secrets.token_urlsafe(48)}


def authorize_url(flow: dict) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(flow["verifier"].encode()).digest()).decode().rstrip("=")
    q = {
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", "stub-client"), "redirect_uri": redirect_uri(), "response_type": "code",
        "scope": "openid email profile", "state": flow["state"], "nonce": flow["nonce"], "code_challenge": challenge,
        "code_challenge_method": "S256", "prompt": "select_account",
    }
    return AUTH_URL + "?" + urlencode(q)


def _payload(id_token: str) -> dict:
    part = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def check_claims(claims: dict, nonce: str, client_id: str, at: float | None = None) -> dict:
    """Raises ValueError unless the identity is current, meant for us, fresh (nonce) and has a Google-verified email."""
    if claims.get("iss") not in ISSUERS:
        raise ValueError("wrong issuer")
    aud = claims.get("aud")
    if client_id not in (aud if isinstance(aud, list) else [aud]):
        raise ValueError("wrong audience")
    if float(claims.get("exp", 0)) < (time.time() if at is None else at):
        raise ValueError("expired")
    if claims.get("nonce") != nonce:
        raise ValueError("wrong nonce")
    if not claims.get("sub") or not claims.get("email") or claims.get("email_verified") not in (True, "true"):
        raise ValueError("email not verified by Google")
    return {"sub": str(claims["sub"]), "email": str(claims["email"]).lower().strip(), "name": claims.get("name") or "", "picture": claims.get("picture")}


async def exchange(code: str, flow: dict) -> dict:
    """Turn the one-time code into the person's verified Google identity. Raises ValueError for anything not valid."""
    if stub_enabled():
        from lib.db import db

        row = await db.google_stub.find_one({"code": code})
        if not row:
            raise ValueError("unknown code")
        claims = {"iss": "https://accounts.google.com", "aud": os.environ.get("GOOGLE_CLIENT_ID", "stub-client"), "exp": time.time() + 600,
                  "nonce": flow["nonce"] if not row.get("bad_nonce") else "other", **row["claims"]}
        return check_claims(claims, flow["nonce"], os.environ.get("GOOGLE_CLIENT_ID", "stub-client"))
    import httpx

    cid = os.environ["GOOGLE_CLIENT_ID"]
    async with httpx.AsyncClient(timeout=20.0, transport=_TRANSPORT) as c:
        r = await c.post(TOKEN_URL, data={
            "code": code, "client_id": cid, "client_secret": os.environ["GOOGLE_CLIENT_SECRET"], "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code", "code_verifier": flow["verifier"],
        })
    if r.status_code != 200 or "id_token" not in r.json():
        raise ValueError("Google refused the code")
    return check_claims(_payload(r.json()["id_token"]), flow["nonce"], cid)