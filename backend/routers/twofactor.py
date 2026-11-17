"""Turn two-step sign-in on or off for your own account."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib import totp
from lib.auth import audit, current_user, now, verify_password
from lib.db import db
from lib.ratelimit import user_limit
from lib.signin_alerts import security_notice
from lib.twofactor import check_second_factor, is_enabled, new_recovery_codes, seal, unseal

router = APIRouter(prefix="/auth/2fa", tags=["two-step sign-in"])


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class ConfirmIn(CodeIn):
    password: str


@router.post("/setup", dependencies=[Depends(user_limit("2fa-setup", 10, 3600))])
async def setup(user: dict = Depends(current_user)):
    """Start: make a new secret (not active yet) and show it so it can be added to an authenticator app."""
    if is_enabled(user):
        raise HTTPException(status_code=409, detail="Two-step sign-in is already on. Turn it off first to set it up again.")
    secret = totp.new_secret()
    await db.users.update_one({"id": user["id"]}, {"$set": {"two_factor_pending": {"secret": seal(secret), "created_at": now()}}})
    await audit(user, "TWO_FACTOR_SETUP_STARTED")
    return {"secret": secret, "otpauth_uri": totp.otpauth_uri(secret, user["email"])}


@router.post("/enable", dependencies=[Depends(user_limit("2fa-enable", 10, 900))])
async def enable(body: CodeIn, user: dict = Depends(current_user)):
    if not user.get("email_verified"):
        raise HTTPException(status_code=403, detail="Confirm your email address first, then turn on two-step sign-in.")
    """Finish: prove the app shows the right code, then switch on and hand out one-time recovery codes (shown only now)."""
    pending = user.get("two_factor_pending")
    if not pending:
        raise HTTPException(status_code=409, detail="Start the setup first.")
    secret = unseal(pending["secret"])
    step = totp.verify(secret, body.code)
    if step is None:
        raise HTTPException(status_code=400, detail="That code is not right. Check the time on your phone and try the newest code.")
    codes, hashes = new_recovery_codes()
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"two_factor": {"enabled": True, "secret": pending["secret"], "last_step": step, "recovery": hashes, "enabled_at": now()}},
         "$unset": {"two_factor_pending": ""}},
    )
    await audit(user, "AUTH_2FA_ENABLED")
    await security_notice(user, "Two-step sign-in was turned on", "Two-step sign-in is now on for your VIDHI account. You will need your authenticator app to sign in.")
    return {"enabled": True, "recovery_codes": codes}


@router.post("/disable", dependencies=[Depends(user_limit("2fa-disable", 10, 900))])
async def disable(body: ConfirmIn, user: dict = Depends(current_user)):
    if not is_enabled(user):
        raise HTTPException(status_code=409, detail="Two-step sign-in is not on.")
    if not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=403, detail="That password is not right.")
    if not await check_second_factor(user, body.code):
        raise HTTPException(status_code=400, detail="That code is not right or was already used.")
    await db.users.update_one({"id": user["id"]}, {"$unset": {"two_factor": "", "two_factor_pending": ""}})
    await audit(user, "AUTH_2FA_DISABLED")
    await security_notice(user, "Two-step sign-in was turned off", "Two-step sign-in was turned off on your VIDHI account.")
    return {"enabled": False}


@router.post("/recovery-codes", dependencies=[Depends(user_limit("2fa-recovery", 5, 3600))])
async def new_codes(body: ConfirmIn, user: dict = Depends(current_user)):
    """Replace the recovery codes (the old ones stop working)."""
    if not is_enabled(user):
        raise HTTPException(status_code=409, detail="Two-step sign-in is not on.")
    if not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=403, detail="That password is not right.")
    if not await check_second_factor(user, body.code):
        raise HTTPException(status_code=400, detail="That code is not right or was already used.")
    codes, hashes = new_recovery_codes()
    await db.users.update_one({"id": user["id"]}, {"$set": {"two_factor.recovery": hashes}})
    await audit(user, "AUTH_2FA_RECOVERY_RENEWED")
    return {"recovery_codes": codes}