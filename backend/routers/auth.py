import asyncio
import hmac
import logging
import os
import secrets
import uuid
from datetime import timedelta, timezone
from html import escape

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from lib.auth import (
    BLOCKED_MESSAGE,
    COOKIE_NAME,
    two_step_status,
    audit,
    cookie_kwargs,
    create_session,
    current_user,
    destroy_session,
    entitlement_for,
    dummy_hash,
    hash_password,
    needs_rehash,
    now,
    renew_session,
    verify_password,
)
from lib import botcheck, google_auth, pilot, recovery_mode
from lib.ratelimit import client_ip
from lib.signin_alerts import record_sign_in, security_notice
from lib.db import db
from lib.languages import LANGUAGE_CODES
from lib.outbound import VERIFY_HOURS, expiry, link_html, new_token, sha256, send_logged, simple_email
from lib.rbac import caps_for
from lib.platform import is_platform_admin
from lib.twofactor import check_second_factor, is_enabled
from lib.ratelimit import hit, ip_limit, peek, user_limit
from pymongo.errors import DuplicateKeyError
from models.schemas import (
    ChangePasswordIn,
    Entitlement,
    ForgotPasswordIn,
    LoginIn,
    ResetPasswordIn,
    SignupIn,
    UserOut,
    password_problem,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _out(user: dict) -> UserOut:
    return UserOut(
        id=user["id"],
        email=user["email"],
        email_verified=bool(user.get("email_verified")),
        capabilities=caps_for(user.get("role")),
        full_name=user["full_name"],
        role=user["role"],
        organization_id=user["organization_id"],
        organization_name=user["organization_name"],
        language=(user.get("preferences") or {}).get("language"),
        theme=(user.get("preferences") or {}).get("theme"),
        two_factor=is_enabled(user),
        platform_admin=is_platform_admin(user),
        pilot=bool(user.get("pilot")),
    )


@router.post(
    "/signup", response_model=UserOut, dependencies=[Depends(ip_limit("signup", 5, 3600))]
)
async def signup(body: SignupIn, response: Response, request: Request):
    if not await botcheck.human(body.turnstile_token, client_ip(request), honeypot=body.website, elapsed_ms=body.elapsed_ms):
        raise HTTPException(status_code=400, detail="We could not confirm that you are a person. Please try again.")
    email = body.email.lower().strip()
    invite = None
    if pilot.invite_only():  # checked first, so nobody without an invitation can even learn whether an address has an account
        invite = await pilot.valid(email, body.invite_code)
        if not invite or not await pilot.claim(invite["id"]):
            raise HTTPException(status_code=403, detail=pilot.REFUSAL)
    if await db.users.find_one({"email": email}):
        if invite:
            await pilot.release(invite["id"])
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    org_id = str(uuid.uuid4())
    await db.organizations.insert_one(
        {"id": org_id, "name": body.organization_name.strip(), "created_at": now(), **({"pilot": True} if invite else {})}
    )
    user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "full_name": body.full_name.strip(),
        "password_hash": await asyncio.to_thread(hash_password, body.password),
        "role": "OWNER",
        "organization_id": org_id,
        "organization_name": body.organization_name.strip(),
        "plan": "FREE",
        "trial_started_at": now(),
        "privacy_accepted_at": now(),
        "created_at": now(),
        **({"pilot": True} if invite else {}),  # created with a pilot invitation: the screens remind the person to use sample or public drafts only
    }
    try:
        await db.users.insert_one(user)
    except DuplicateKeyError:  # lost a signup race on the unique email index
        await db.organizations.delete_one({"id": org_id})
        if invite:
            await pilot.release(invite["id"])
        raise HTTPException(status_code=409, detail="An account with this email already exists") from None
    token = await create_session(user["id"], request)
    await record_sign_in(user, request, new_account=True)
    response.set_cookie(COOKIE_NAME, token, **cookie_kwargs())
    await audit(user, "AUTH_SIGNUP")
    try:  # never block signup on email trouble; the user can resend from the app
        await _send_verification(user)
    except Exception:  # noqa: BLE001
        logger.exception("verification email failed at signup")
    return _out(user)


@router.post("/login", response_model=UserOut, dependencies=[Depends(ip_limit("login-ip", 30, 300))])
async def login(body: LoginIn, response: Response, request: Request):
    email = body.email.lower().strip()
    who = f"{email}|{client_ip(request)}"
    await hit("login-email", email, 60, 300)  # a generous ceiling per account from anywhere: stops guessing spread over many addresses
    if await peek("login-fail", who, 300) >= 8:  # wrong passwords from THIS address for THIS account; someone else typing the email cannot lock the owner out
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Please wait a few minutes and try again.", headers={"Retry-After": "300"})
    user = await db.users.find_one({"email": email})
    # Always run one hash verification so response time doesn't reveal whether the email exists.
    stored = user["password_hash"] if user else dummy_hash()
    ok = await asyncio.to_thread(verify_password, body.password, stored)  # off the event loop: a hash takes a fraction of a second
    if not user or not ok:
        await hit("login-fail", who, 8, 300)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.get("blocked"):
        raise HTTPException(status_code=403, detail=BLOCKED_MESSAGE)
    if is_enabled(user):  # the password was right: now the second step
        if not body.otp:
            raise HTTPException(status_code=428, detail="Enter the 6-digit code from your authenticator app.")
        await hit("login-otp", email, 10, 900)  # limits guessing of the 6 digits
        if not await check_second_factor(user, body.otp):
            await audit(user, "AUTH_2FA_FAILED")
            raise HTTPException(status_code=401, detail="That code is not right or was already used.")
    if needs_rehash(stored):
        await db.users.update_one({"id": user["id"]}, {"$set": {"password_hash": await asyncio.to_thread(hash_password, body.password)}})
    token = await create_session(user["id"], request)
    await record_sign_in(user, request)
    response.set_cookie(COOKIE_NAME, token, **cookie_kwargs())
    await audit(user, "AUTH_LOGIN")
    return _out(user)


@router.get("/me", response_model=UserOut)
async def me(response: Response, user: dict = Depends(current_user), vidhi_session: str | None = Cookie(default=None)):
    if vidhi_session and user.get("_session_digest") and await renew_session(user["_session_digest"]):
        response.set_cookie(COOKIE_NAME, vidhi_session, **cookie_kwargs())  # keep active people signed in
    if user.get("_session_digest"):  # "last active", updated at most every five minutes
        await db.sessions.update_one({"token_hash": user["_session_digest"], "last_seen_at": {"$lt": now() - timedelta(minutes=5)}}, {"$set": {"last_seen_at": now()}})
    out = _out(user)
    st = await two_step_status(user)
    out.two_step_required, out.two_step_due_at = st["required"], st["due_at"]
    return out


@router.get("/sessions")
async def my_sessions(user: dict = Depends(current_user)):
    """Where you are signed in: this device and any others, with a way to end each one."""
    rows = await db.sessions.find({"user_id": user["id"]}).sort("created_at", -1).to_list(50)
    out = []
    for r in rows:
        exp = r["expires_at"] if r["expires_at"].tzinfo else r["expires_at"].replace(tzinfo=timezone.utc)
        if exp < now():
            continue
        out.append({"id": r["id"], "current": r["token_hash"] == user.get("_session_digest"), "device": r.get("device") or "Unknown device", "network": r.get("ip_masked"),
                    "signed_in_at": r["created_at"], "last_active": r.get("last_seen_at") or r["created_at"], "expires_at": exp})
    return sorted(out, key=lambda s: (not s["current"], str(s["last_active"])), reverse=False)


@router.delete("/sessions/{session_id}")
async def end_session(session_id: str, response: Response, user: dict = Depends(current_user)):
    """End one session (yours only). Ending the current one signs you out here."""
    row = await db.sessions.find_one({"id": session_id, "user_id": user["id"]})
    if not row:
        raise HTTPException(status_code=404, detail="That session was not found.")
    await db.sessions.delete_one({"id": session_id})
    if row["token_hash"] == user.get("_session_digest"):
        response.delete_cookie(COOKIE_NAME, path="/")
    await audit(user, "AUTH_SESSION_ENDED", detail=row.get("device"))
    return {"ok": True, "was_current": row["token_hash"] == user.get("_session_digest")}


@router.get("/options")
async def sign_in_options():
    """Which ways of signing in this installation offers (the login page shows buttons for these)."""
    return {"password": True, "google": google_auth.enabled(), "turnstile_site_key": botcheck.site_key() if botcheck.configured() else None, "signup_mode": "invite" if pilot.invite_only() else "open", "recovery": recovery_mode.enabled()}  # "recovery": whether Legal Recovery is part of this installation (the page hides it when not)


OAUTH_COOKIE = "vidhi_oauth"


def _login_redirect(error: str | None = None) -> RedirectResponse:
    base = os.environ.get("APP_URL", "").rstrip("/")
    r = RedirectResponse(f"{base}/login" + (f"?error={error}" if error else ""), status_code=302)
    r.delete_cookie(OAUTH_COOKIE, path="/")
    return r


@router.get("/google/start", dependencies=[Depends(ip_limit("google-start", 30, 300))])
async def google_start():
    """Send the browser to Google. State, nonce and the PKCE verifier are kept here; the browser only holds the state."""
    if not google_auth.enabled():
        raise HTTPException(status_code=404, detail="Sign in with Google is not set up.")
    flow = google_auth.new_flow()
    await db.oauth_flows.insert_one({"state_hash": sha256(flow["state"]), "nonce": flow["nonce"], "verifier": flow["verifier"], "expires_at": now() + timedelta(minutes=10)})
    r = RedirectResponse(google_auth.authorize_url(flow), status_code=302)
    r.set_cookie(OAUTH_COOKIE, flow["state"], httponly=True, samesite="lax", secure=cookie_kwargs()["secure"], path="/", max_age=600)
    return r


@router.get("/google/callback", dependencies=[Depends(ip_limit("google-callback", 30, 300))])
async def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None, vidhi_oauth: str | None = Cookie(default=None)):
    if error or not code or not state or not vidhi_oauth or not hmac.compare_digest(state, vidhi_oauth):
        return _login_redirect("google_cancelled" if error else "google_failed")
    flow = await db.oauth_flows.find_one_and_delete({"state_hash": sha256(state)})  # one use only
    if not flow or flow["expires_at"].replace(tzinfo=timezone.utc) < now():
        return _login_redirect("google_failed")
    try:
        who = await google_auth.exchange(code, {"state": state, "nonce": flow["nonce"], "verifier": flow["verifier"]})
    except ValueError:
        logger.info("google sign-in refused", exc_info=True)
        return _login_redirect("google_failed")
    user = await db.users.find_one({"google_sub": who["sub"]}) or await db.users.find_one({"email": who["email"]})
    created = False
    invite = None
    if not user and pilot.invite_only():
        invite = await pilot.open_for_email(who["email"])  # Google has proved the address; an open invitation for it is what lets a new account be made
        if not invite or not await pilot.claim(invite["id"]):
            return _login_redirect("invite_only")
    if not user:
        org_id, name = str(uuid.uuid4()), (who["name"] or who["email"].split("@")[0]).strip()
        await db.organizations.insert_one({"id": org_id, "name": name, "created_at": now()})
        user = {
            "id": str(uuid.uuid4()), "email": who["email"], "full_name": name, "password_hash": hash_password(secrets.token_urlsafe(32)),
            "role": "OWNER", "organization_id": org_id, "organization_name": name, "plan": "FREE", "trial_started_at": now(),
            "privacy_accepted_at": now(), "created_at": now(), "email_verified": True, "google_sub": who["sub"], "auth_methods": ["google"],
        }
        try:
            await db.users.insert_one(user)
        except DuplicateKeyError:
            await db.organizations.delete_one({"id": org_id})
            if invite:
                await pilot.release(invite["id"])
            return _login_redirect("google_failed")
        created = True
    else:
        if user.get("blocked"):
            return _login_redirect("suspended")
        if is_enabled(user):  # the app's own two-step sign-in must not be skipped
            return _login_redirect("two_step_use_password")
        fields = {"google_sub": who["sub"], "email_verified": True}
        if not user.get("email_verified"):
            # Someone may have registered this address with a password BEFORE its real owner proved they own it. Linking Google must not
            # leave that password (or any session made with it) working: replace the password and end every existing session.
            fields["password_hash"] = hash_password(secrets.token_urlsafe(32))
            await db.sessions.delete_many({"user_id": user["id"]})
            await db.password_resets.delete_many({"user_id": user["id"]})
        await db.users.update_one({"id": user["id"]}, {"$set": fields, "$addToSet": {"auth_methods": "google"}})
    token = await create_session(user["id"], request)
    await record_sign_in({**user, "email_verified": True}, request, new_account=created)
    base = os.environ.get("APP_URL", "").rstrip("/")
    r = RedirectResponse(f"{base}/start", status_code=302)
    r.set_cookie(COOKIE_NAME, token, **cookie_kwargs())
    r.delete_cookie(OAUTH_COOKIE, path="/")
    await audit(user, "AUTH_GOOGLE_SIGNUP" if created else "AUTH_GOOGLE_LOGIN")
    return r





class PreferencesIn(BaseModel):
    language: str | None = None
    theme: str | None = None


@router.patch("/preferences", response_model=UserOut)
async def set_preferences(body: PreferencesIn, user: dict = Depends(current_user)):
    """Remember the person's display language and theme so they follow them to another device."""
    changes: dict = {}
    if body.language is not None:
        if body.language not in LANGUAGE_CODES:
            raise HTTPException(422, "That language is not available.")
        changes["preferences.language"] = body.language
    if body.theme is not None:
        if body.theme not in ("dark", "light", "system"):
            raise HTTPException(422, "Choose dark, light or system.")
        changes["preferences.theme"] = body.theme
    if changes:
        await db.users.update_one({"id": user["id"]}, {"$set": changes})
        user = {**user, "preferences": {**(user.get("preferences") or {}), **{k.split(".")[1]: v for k, v in changes.items()}}}
        await audit(user, "PREFERENCES_CHANGED", detail=", ".join(sorted(k.split(".")[1] for k in changes)))
    return _out(user)


@router.get("/ai-usage")
async def ai_usage(user: dict = Depends(current_user)):
    """How much of each of this person's AI limits is used and when each renews, as shares (never rupees), for a usage meter like Claude's: the rolling few-hour window, the day, the week
    and the month on Pro; the day on the free plan."""
    from lib import aibudget

    plan = aibudget._plan_of(user)
    budget = aibudget.get_budget()
    rows = await budget.usage(str(user["id"]), plan) if hasattr(budget, "usage") else []
    return {"plan": plan, "limits": rows}


@router.get("/entitlement", response_model=Entitlement)
async def get_entitlement(user: dict = Depends(current_user)):
    from lib.plans import summary, usage_today

    return Entitlement(**entitlement_for(user), **await usage_today(user), limits=summary())


async def _send_verification(user: dict) -> None:
    raw, digest = new_token()
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"email_verification": {"token_hash": digest, "expires_at": expiry(hours=VERIFY_HOURS)}}},
    )
    app_url = os.environ.get("APP_URL", "").rstrip("/")
    link = f"{app_url}/verify-email?token={raw}"
    html = simple_email(
        [
            f"Hi {escape(user.get('full_name') or 'there')},",
            "Please confirm this is your email address so you can send notices and statements from VIDHI:",
            link_html(link, "Confirm my email address"),
            "If you did not create a VIDHI account, you can ignore this message.",
        ]
    )
    await send_logged(
        to=user["email"], subject="Confirm your email address for VIDHI", html=html,
        kind="verify-email", user=user, respect_suppression=False,
    )


@router.post("/verify-email/request", dependencies=[Depends(user_limit("verify-request", 5, 86400))])
async def request_verification(user: dict = Depends(current_user)):
    if user.get("email_verified"):
        return {"ok": True, "already_verified": True}
    try:
        await _send_verification(user)
    except Exception as exc:  # noqa: BLE001
        logger.exception("verification email failed")
        raise HTTPException(status_code=502, detail="We could not send the email right now. Please try again in a minute.") from exc
    return {"ok": True, "already_verified": False}


class VerifyEmailIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


@router.post("/verify-email", dependencies=[Depends(ip_limit("verify-email", 30, 3600))])
async def verify_email(body: VerifyEmailIn):
    user = await db.users.find_one({"email_verification.token_hash": sha256(body.token)})
    exp = (user or {}).get("email_verification", {}).get("expires_at")
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if not user or exp is None or exp < now():
        raise HTTPException(status_code=400, detail="This link is invalid or has expired. Request a new one from your account.")
    await db.users.update_one({"id": user["id"]}, {"$set": {"email_verified": True}, "$unset": {"email_verification": ""}})
    await audit(user, "EMAIL_VERIFIED")
    return {"ok": True}


# NOTE: there is intentionally no self-service "upgrade" route. PRO is granted only by the verified
# Stripe payment flow in routers/payments.py (_mark_paid_and_upgrade).

@router.post("/logout")
async def logout(response: Response, vidhi_session: str | None = Cookie(default=None)):
    response.delete_cookie(COOKIE_NAME, path="/")
    if vidhi_session:
        await destroy_session(vidhi_session)
    return {"ok": True}

# ---------------------------------------------------------------------------------------------
# Password change, sign-out-everywhere, forgotten password
# ---------------------------------------------------------------------------------------------
RESET_HOURS = 1


@router.post("/change-password")
async def change_password(body: ChangePasswordIn, user: dict = Depends(current_user)):
    """Signed-in user changes their own password. Every OTHER session is ended (a stolen cookie stops working)."""
    await hit("pw-change", user["id"], 10, 3600)
    stored = (await db.users.find_one({"id": user["id"]}))["password_hash"]
    if not await asyncio.to_thread(verify_password, body.current_password, stored):
        raise HTTPException(status_code=403, detail="Your current password is not correct.")
    problem = password_problem(body.new_password, user["email"])
    if problem:
        raise HTTPException(status_code=422, detail=f"New {problem}.")
    await db.users.update_one({"id": user["id"]}, {"$set": {"password_hash": await asyncio.to_thread(hash_password, body.new_password)}})
    await db.sessions.delete_many({"user_id": user["id"], "token_hash": {"$ne": user["_session_digest"]}})
    await audit(user, "AUTH_PASSWORD_CHANGE")
    await security_notice(user, "Your VIDHI password was changed", "The password on your VIDHI account was just changed. All your other devices were signed out.")
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(response: Response, user: dict = Depends(current_user)):
    """End every session of this user on every device, including this one."""
    res = await db.sessions.delete_many({"user_id": user["id"]})
    response.delete_cookie(COOKIE_NAME, path="/")
    await audit(user, "AUTH_LOGOUT_ALL", detail=f"sessions={res.deleted_count}")
    return {"ok": True, "sessions_ended": res.deleted_count}


async def _send_reset_email(user: dict) -> None:
    raw, digest = new_token()
    await db.password_resets.insert_one(
        {"user_id": user["id"], "token_hash": digest, "expires_at": expiry(hours=RESET_HOURS), "used": False, "created_at": now()}
    )
    link = f"{os.environ.get('APP_URL', '').rstrip('/')}/reset-password?token={raw}"
    html = simple_email(
        [
            f"Hi {escape(user.get('full_name') or 'there')},",
            "Someone asked to reset the password for your VIDHI account. If it was you, choose a new password here "
            f"(the link works once and expires in {RESET_HOURS} hour):",
            link_html(link, "Choose a new password"),
            "If it was not you, ignore this message - your password has not changed.",
        ]
    )
    await send_logged(
        to=user["email"], subject="Reset your VIDHI password", html=html, kind="password-reset", user=user, respect_suppression=False
    )


async def _forgot_in_background(email: str) -> None:
    user = await db.users.find_one({"email": email})
    if not user:
        return
    try:
        await _send_reset_email(user)
    except Exception:  # noqa: BLE001 - never reveal (or crash on) delivery problems
        logger.exception("password reset email failed")


@router.post("/forgot-password", dependencies=[Depends(ip_limit("forgot-ip", 10, 3600))])
async def forgot_password(body: ForgotPasswordIn, background: BackgroundTasks):
    """Always answers the same way, so it cannot be used to discover which emails have accounts."""
    email = body.email.lower().strip()
    # Short window on purpose: anyone can use up an address's allowance, so a long one would let a stranger keep the real owner from asking for a link.
    await hit("forgot-email", email, 3, 900)
    background.add_task(_forgot_in_background, email)  # work happens after the reply: same response time either way
    return {"ok": True, "message": "If that email has a VIDHI account, a reset link is on its way."}


@router.post("/reset-password", dependencies=[Depends(ip_limit("reset-ip", 20, 3600))])
async def reset_password(body: ResetPasswordIn):
    row = await db.password_resets.find_one_and_update(
        {"token_hash": sha256(body.token), "used": False, "expires_at": {"$gt": now()}}, {"$set": {"used": True, "used_at": now()}}
    )
    if not row:
        raise HTTPException(status_code=400, detail="This link is invalid or has expired. Ask for a new one.")
    user = await db.users.find_one({"id": row["user_id"]})
    if not user:
        raise HTTPException(status_code=400, detail="This link is invalid or has expired. Ask for a new one.")
    problem = password_problem(body.new_password, user["email"])
    if problem:
        await db.password_resets.update_one({"_id": row["_id"]}, {"$set": {"used": False}})  # let them retry with the same link
        raise HTTPException(status_code=422, detail=f"New {problem}.")
    # Following the emailed link proves they control the address; every old session is ended.
    patch: dict = {"$set": {"password_hash": await asyncio.to_thread(hash_password, body.new_password), "email_verified": True}}
    if not user.get("email_verified"):  # the address was never confirmed, so whoever signed up first may have set a two-step the real owner cannot pass
        patch["$unset"] = {"two_factor": ""}
    await db.users.update_one({"id": user["id"]}, patch)
    await db.sessions.delete_many({"user_id": user["id"]})
    await audit(user, "AUTH_PASSWORD_RESET")
    return {"ok": True}