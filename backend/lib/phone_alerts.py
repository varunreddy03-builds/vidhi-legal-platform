"""Short alerts to the account owner's own verified phone (opt-in). Never to a customer. Never contains names or amounts."""

import logging

from lib import crypto, twilio_sms
from lib.db import db
from lib.ratelimit import hit

logger = logging.getLogger(__name__)
AAD = b"vidhi-phone"
DAILY_CAP = 20


def seal(number: str) -> str:
    return crypto.seal_text(number, AAD)


def unseal(sealed: str) -> str:
    return crypto.open_text(sealed, AAD)


def active(user: dict) -> bool:
    p = user.get("phone") or {}
    return bool(p.get("verified") and p.get("alerts") and p.get("number"))


async def notify_user(user_id: str, text: str) -> bool:
    """Best effort: True if an alert was sent. Never raises (an alert must never break the thing that caused it)."""
    try:
        user = await db.users.find_one({"id": user_id})
        if not user or not active(user):
            return False
        p = user["phone"]
        if not twilio_sms.configured(p.get("channel", "sms")):
            return False
        await hit("sms-alert", user_id, DAILY_CAP, 86400)
        await twilio_sms.send(unseal(p["number"]), f"VIDHI: {text}", p.get("channel", "sms"))
        return True
    except Exception:  # noqa: BLE001
        logger.info("phone alert not sent", exc_info=True)
        return False