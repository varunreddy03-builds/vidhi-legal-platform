"""Session auth: bcrypt password hashing + httpOnly cookie sessions backed by Mongo.

Session tokens are random and only their SHA-256 is stored, so a leaked database cannot be replayed
as live cookies. Legacy PBKDF2 password hashes still verify and are upgraded on the next login.
"""

import base64
import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Request

from lib.db import db
from lib.rbac import ROLE_CAPS, required_cap

COOKIE_NAME = "vidhi_session"
BLOCKED_MESSAGE = "This account has been suspended. Please contact support if you think this is a mistake."
SESSION_DAYS = 30  # people stay signed in; active people are kept signed in (see renew_session)
BCRYPT_COST = int(os.environ.get("BCRYPT_COST", "12"))


def _prehash(password: str) -> bytes:
    # bcrypt only reads 72 bytes; hashing first lets long passphrases count in full.
    return base64.b64encode(hashlib.sha256(password.encode()).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(BCRYPT_COST)).decode()


def _legacy_hash(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("$2"):
        try:
            return bcrypt.checkpw(_prehash(password), stored.encode())
        except ValueError:
            return False
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(_legacy_hash(password, salt), stored)


def needs_rehash(stored: str) -> bool:
    return not stored.startswith("$2")


_dummy_hash: str | None = None


def dummy_hash() -> str:
    """A real hash to verify against when the email is unknown, so timing doesn't reveal accounts."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_hex(8))
    return _dummy_hash


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def now() -> datetime:
    return datetime.now(timezone.utc)


async def create_session(user_id: str, request: Request | None = None) -> str:
    """A new session token (a fresh one at every sign-in). With the request, remember what device and network it came from so the person can see and end it."""
    from lib import devices

    token = secrets.token_urlsafe(32)
    ua = request.headers.get("user-agent") if request is not None else None
    if request is not None:
        from lib.ratelimit import client_ip

        ip = client_ip(request)
    else:
        ip = None
    await db.sessions.insert_one(
        {
            "id": str(uuid.uuid4()),
            "token_hash": token_digest(token),
            "user_id": user_id,
            "device": devices.describe(ua) if request is not None else "Unknown device",
            "ip_masked": devices.mask_ip(ip) if ip else None,
            "last_seen_at": now(),
            "created_at": now(),
            "expires_at": now() + timedelta(days=SESSION_DAYS),
        }
    )
    return token


async def renew_session(digest: str) -> bool:
    """Active people stay signed in: once less than half the session is left, start a fresh full period. True if renewed."""
    sess = await db.sessions.find_one({"token_hash": digest})
    if not sess:
        return False
    exp = sess['expires_at'] if sess['expires_at'].tzinfo else sess['expires_at'].replace(tzinfo=timezone.utc)
    if exp - now() > timedelta(days=SESSION_DAYS / 2):
        return False
    await db.sessions.update_one({"token_hash": digest}, {"$set": {"expires_at": now() + timedelta(days=SESSION_DAYS)}})
    return True


async def destroy_session(token: str) -> None:
    await db.sessions.delete_one({"token_hash": token_digest(token)})


async def _load_user(vidhi_session: str | None) -> dict:
    if not vidhi_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    digest = token_digest(vidhi_session)
    sess = await db.sessions.find_one({"token_hash": digest})
    if not sess:
        raise HTTPException(status_code=401, detail="Session expired")
    exp = sess["expires_at"]
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now():
        await db.sessions.delete_one({"token_hash": digest})
        raise HTTPException(status_code=401, detail="Session expired")
    user = await db.users.find_one({"id": sess["user_id"]})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.get("blocked"):
        raise HTTPException(status_code=403, detail=BLOCKED_MESSAGE)
    if user.get("role") != "OWNER":
        user = await _with_org_plan(user)
    user["_session_digest"] = digest
    return user


async def _with_org_plan(user: dict) -> dict:
    """Members use the plan their organisation's owner has: the subscription belongs to the organisation."""
    owners = await db.users.find({"organization_id": user["organization_id"], "role": "OWNER"}).to_list(20)
    if not owners:
        return user
    best = next((o for t in ("firm", "pro") for o in owners if entitlement_for(o)["tier"] == t), owners[0])
    keys = ("plan", "pro_until", "subscription_status", "cancel_at_period_end")
    return {**user, **{k: best.get(k) for k in keys if k in best}}


async def current_user(request: Request, vidhi_session: str | None = Cookie(default=None)) -> dict:
    """The signed-in user, loaded once per request (the role check and the handler share it)."""
    cached = getattr(request.state, "user", None)
    if cached is not None:
        return cached
    bearer = request.headers.get("authorization", "")
    if not vidhi_session and bearer.lower().startswith("bearer vk_"):
        from lib import addin_keys  # an add-in key is accepted for the two Katalyst check routes ONLY (lib/addin_keys.py); every other route still needs the session cookie

        if route_template(request) not in addin_keys.ADDIN_KEY_ROUTES:
            raise HTTPException(status_code=401, detail="Not authenticated")
        user = await addin_keys.user_for(bearer[7:].strip())
        request.state.user = user
        return user
    user = await _load_user(vidhi_session)
    request.state.user = user
    return user


def route_template(request: Request) -> str:
    """The matched route's template with its /api prefix, e.g. /api/matters/{matter_id}.

    Recent FastAPI versions keep the include-prefix out of route.path, so add it back when it is missing."""
    route = request.scope.get("route")
    tpl = getattr(route, "path_format", None) or getattr(route, "path", None)
    if not tpl:
        return "(unmatched)"  # never the raw path: it can hold tokens and ids
    return tpl if tpl.startswith("/api/") or tpl == "/api" else "/api" + tpl


TWO_STEP_MESSAGE = (
    "Two-step sign-in is now required for owners and admins of a team. Turn it on in Settings (it takes a minute) and everything works again."
)
TWO_STEP_EXEMPT = ("/api/auth/", "/api/privacy/", "/api/support/", "/api/public/")  # these stay open so the person can turn it on, sign out, or ask for help


async def two_step_status(user: dict) -> dict:
    """Owners and admins of an organisation with other people in it must use two-step sign-in. They get TWO_STEP_GRACE_DAYS (default 7) from the first
    time this applies to them; after that, everything except the account and help routes is closed until they turn it on. Solo users are never affected."""
    from lib.twofactor import is_enabled

    off = {"required": False, "due_at": None, "overdue": False}
    if os.environ.get("TWO_STEP_FOR_TEAMS", "true").lower() == "false" or user.get("role") not in ("OWNER", "ADMIN") or is_enabled(user):
        return off
    if await db.users.count_documents({"organization_id": user["organization_id"]}, limit=2) < 2:
        return off
    due = user.get("two_step_due_at")
    if due is None:
        due = now() + timedelta(days=int(os.environ.get("TWO_STEP_GRACE_DAYS", "7")))
        await db.users.update_one({"id": user["id"], "two_step_due_at": {"$exists": False}}, {"$set": {"two_step_due_at": due}})
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return {"required": True, "due_at": due, "overdue": due < now()}


async def enforce_policy(request: Request, vidhi_session: str | None = Cookie(default=None)) -> None:
    """Router-level role check for EVERY API route, from the one table in lib/rbac.py."""
    tpl = route_template(request)
    cap = required_cap(request.method, tpl)
    if cap is None:
        return  # public, or the route authenticates itself (webhooks, cron, signup...)
    user = await current_user(request, vidhi_session)
    if not tpl.startswith(TWO_STEP_EXEMPT) and (await two_step_status(user))["overdue"]:
        raise HTTPException(status_code=403, detail=TWO_STEP_MESSAGE)
    if cap not in ROLE_CAPS.get(user.get("role", ""), frozenset()):
        raise HTTPException(
            status_code=403,
            detail=f"Your role ({user.get('role', 'unknown').title()}) is not allowed to do this. Ask an owner or admin of your organisation.",
        )


async def audit(
    user: dict,
    operation: str,
    result: str = "SUCCESS",
    matter_id: str | None = None,
    detail: str | None = None,
) -> None:
    await db.audit_events.insert_one(
        {
            "id": str(uuid.uuid4()),
            "organization_id": user["organization_id"],
            "user_id": user["id"],
            "user_email": user["email"],
            "matter_id": matter_id,
            "operation": operation,
            "result": result,
            "detail": detail,
            "created_at": now(),
        }
    )


def _aware_dt(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def entitlement_for(user: dict) -> dict:
    """Server-authoritative plan. Legal Recovery is free for everyone. Legal Intelligence has a limited FREE plan
    and a PRO monthly subscription (lib/plans.py says what each includes). Pro is active while the subscription's
    paid-until date (plus a short grace) is in the future; an account upgraded before subscriptions existed has no
    date and stays Pro."""
    from lib.plans import GRACE

    until = _aware_dt(user.get("pro_until"))
    paid = user.get("plan") in ("PRO", "FIRM") and (until is None or until + GRACE > now())
    pro = paid
    name = user.get("plan") if paid else "FREE"
    return {
        "plan": name,
        "tier": name.lower(),
        "intelligence_access": True,  # FREE is a real plan, not a lock-out; limits are applied per request
        "recovery_access": True,
        "trial_days_left": 0,
        "pro_until": until if pro else None,
        "subscription_status": user.get("subscription_status"),
        "cancel_at_period_end": bool(user.get("cancel_at_period_end")),
    }


async def require_intelligence(request: Request, vidhi_session: str | None = Cookie(default=None)) -> dict:
    """Dependency on every Division 1 AI endpoint. Both plans may enter; the per-task limits are in lib/plans.gate_ai."""
    return await current_user(request, vidhi_session)

EMAIL_UNVERIFIED_DETAIL = (
    "Please verify your email address before sending email to other people - we sent you a link."
)


async def require_verified_sender(request: Request, vidhi_session: str | None = Cookie(default=None)) -> dict:
    """Guard for any route that emails a third party: the sender must have proved their address,
    so the platform cannot be used as an anonymous mail relay."""
    user = await current_user(request, vidhi_session)
    if not user.get("email_verified"):
        raise HTTPException(status_code=403, detail=EMAIL_UNVERIFIED_DETAIL)
    return user


def cookie_kwargs() -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        # Secure by default; set COOKIE_SECURE=false only for plain-http local development.
        "secure": os.environ.get("COOKIE_SECURE", "true").lower() != "false",
        "path": "/",
        "max_age": SESSION_DAYS * 24 * 3600,
    }
