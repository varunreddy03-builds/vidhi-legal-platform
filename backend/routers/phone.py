"""Add and verify your own phone for opt-in alerts (SMS or WhatsApp). The number is stored encrypted."""

import hashlib
import hmac
import os
import secrets
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from lib import phone_alerts, twilio_sms
from lib.auth import audit, current_user, now
from lib.db import db
from lib.ratelimit import hit, ip_limit, user_limit

router = APIRouter(tags=["phone"])
public = APIRouter(tags=["phone"])


def _code_hash(user_id: str, code: str) -> str:
    return hmac.new(twilio_sms.pepper(), f"{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


def _view(user: dict) -> dict:
    p = user.get("phone") or {}
    return {
        "available": twilio_sms.configured("sms") or twilio_sms.configured("whatsapp"),
        "channels": [c for c in ("sms", "whatsapp") if twilio_sms.configured(c)],
        "verified": bool(p.get("verified")), "last4": p.get("last4"), "channel": p.get("channel"), "alerts": bool(p.get("alerts")),
    }


@router.get("/auth/phone")
async def get_phone(user: dict = Depends(current_user)):
    return _view(user)


class StartIn(BaseModel):
    phone: str = Field(min_length=8, max_length=24)
    channel: str = "sms"


@router.post("/auth/phone/start", dependencies=[Depends(user_limit("phone-start", 5, 3600))])
async def start(body: StartIn, user: dict = Depends(current_user)):
    """Send a 6-digit code to the number so only its owner can switch alerts on."""
    if not user.get("email_verified"):  # texting costs money and could be misused: only people who proved their email may ask for a code
        raise HTTPException(status_code=403, detail="Please confirm your email address first, then add your phone.")
    if body.channel not in ("sms", "whatsapp") or not twilio_sms.configured(body.channel):
        raise HTTPException(status_code=503, detail="Phone alerts are not available right now.")
    try:
        number = twilio_sms.normalise(body.phone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await hit("phone-number", twilio_sms.number_hash(number), 3, 3600)  # nobody can be spammed with codes by many accounts
    other = await db.users.find_one({"phone.hash": twilio_sms.number_hash(number), "phone.verified": True, "id": {"$ne": user["id"]}})
    if other:
        raise HTTPException(status_code=409, detail="That number is already used by another account.")
    code = f"{secrets.randbelow(10**6):06d}"
    await db.users.update_one({"id": user["id"]}, {"$set": {"phone_pending": {
        "number": phone_alerts.seal(number), "hash": twilio_sms.number_hash(number), "channel": body.channel,
        "code": _code_hash(user["id"], code), "expires_at": now() + timedelta(minutes=10), "tries": 0}}})
    try:
        await twilio_sms.send(number, f"VIDHI verification code: {code}. It works for 10 minutes. Do not share it.", body.channel)
    except twilio_sms.SmsError as exc:
        raise HTTPException(status_code=502, detail="We could not send the code. Check the number and try again.") from exc
    await audit(user, "PHONE_CODE_SENT", detail=body.channel)  # never the number itself
    return {"sent": True}


class VerifyIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


@router.post("/auth/phone/verify", dependencies=[Depends(user_limit("phone-verify", 10, 3600))])
async def verify(body: VerifyIn, user: dict = Depends(current_user)):
    pend = user.get("phone_pending")
    if not pend:
        raise HTTPException(status_code=409, detail="Ask for a code first.")
    exp = pend["expires_at"].replace(tzinfo=timezone.utc)
    if exp < now() or pend.get("tries", 0) >= 5:
        await db.users.update_one({"id": user["id"]}, {"$unset": {"phone_pending": ""}})
        raise HTTPException(status_code=410, detail="That code has expired. Ask for a new one.")
    if not hmac.compare_digest(pend["code"], _code_hash(user["id"], body.code)):
        await db.users.update_one({"id": user["id"]}, {"$inc": {"phone_pending.tries": 1}})
        raise HTTPException(status_code=400, detail="That code is not right.")
    number = phone_alerts.unseal(pend["number"])
    await db.users.update_one({"id": user["id"]}, {
        "$set": {"phone": {"number": pend["number"], "hash": pend["hash"], "last4": number[-4:], "channel": pend["channel"], "verified": True, "alerts": True, "verified_at": now()}},
        "$unset": {"phone_pending": ""}})
    await audit(user, "PHONE_VERIFIED")
    return _view(await db.users.find_one({"id": user["id"]}))


class AlertsIn(BaseModel):
    alerts: bool


@router.patch("/auth/phone")
async def set_alerts(body: AlertsIn, user: dict = Depends(current_user)):
    if not (user.get("phone") or {}).get("verified"):
        raise HTTPException(status_code=409, detail="Verify your phone first.")
    await db.users.update_one({"id": user["id"]}, {"$set": {"phone.alerts": body.alerts}})
    await audit(user, "PHONE_ALERTS", detail="on" if body.alerts else "off")
    return _view(await db.users.find_one({"id": user["id"]}))


@router.delete("/auth/phone")
async def remove_phone(user: dict = Depends(current_user)):
    await db.users.update_one({"id": user["id"]}, {"$unset": {"phone": "", "phone_pending": ""}})
    await audit(user, "PHONE_REMOVED")
    return {"ok": True}


@public.post("/webhooks/twilio", dependencies=[Depends(ip_limit("twilio-webhook", 300, 60))])
async def twilio_inbound(request: Request):
    """Twilio -> us when someone replies to an alert. STOP switches that number's alerts off. The signature is checked."""
    form = dict((await request.form()).items())
    url = os.environ.get("TWILIO_WEBHOOK_URL") or os.environ.get("APP_URL", "").rstrip("/") + "/api/webhooks/twilio"
    if not twilio_sms.valid_signature(url, form, request.headers.get("X-Twilio-Signature")):
        raise HTTPException(status_code=401, detail="Unauthorized")
    sender = str(form.get("From", "")).replace("whatsapp:", "")
    if str(form.get("Body", "")).strip().upper() in twilio_sms.STOP_WORDS and twilio_sms.E164.match(sender):
        await db.users.update_many({"phone.hash": twilio_sms.number_hash(sender)}, {"$set": {"phone.alerts": False}})
    return {"ok": True}