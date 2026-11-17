"""Emails about sign-ins and security changes, sent to the account's CONFIRMED email address only (an unconfirmed address may belong to someone else).

A sign-in alert is sent when a person signs in from a device not seen before. Their first device (the one they signed up on) is simply remembered.
Alerts never contain the session token or any secret; they say what happened and what to do if it was not them."""

import logging
from datetime import timezone, timedelta
from html import escape

from lib import devices
from lib.auth import now
from lib.db import db
from lib.email import send_email

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
KNOWN_DEVICES_KEPT = 20


async def _send(user: dict, subject: str, paragraphs: list[str]) -> None:
    if not user.get("email_verified"):
        return
    body = "".join(f'<p style="font-family:Arial,sans-serif">{p}</p>' for p in paragraphs)
    try:
        await send_email(to=user["email"], subject=subject, html=body)
    except Exception:  # noqa: BLE001 - an alert that cannot be sent must never block signing in
        logger.info("security email not sent", exc_info=True)


async def record_sign_in(user: dict, request, *, new_account: bool = False) -> None:
    """Remember the device; warn the person if it is a new one."""
    ua = request.headers.get("user-agent") if request is not None else None
    fp = devices.fingerprint(ua)
    known = user.get("known_devices") or []
    if fp in known:
        return
    await db.users.update_one({"id": user["id"]}, {"$push": {"known_devices": {"$each": [fp], "$slice": -KNOWN_DEVICES_KEPT}}})
    if new_account or not known:
        return  # the first device ever is not news
    from lib.ratelimit import client_ip

    when = now().astimezone(IST).strftime("%d %b %Y, %H:%M IST")
    await _send(user, "New sign-in to your VIDHI account", [
        f"Someone signed in to your VIDHI account from <strong>{escape(devices.describe(ua))}</strong> (network {escape(devices.mask_ip(client_ip(request)))}) on {when}.",
        "If this was you, there is nothing to do. If it was not you, change your password now and, in Settings, sign out of the devices you do not recognise.",
    ])


async def security_notice(user: dict, subject: str, what: str) -> None:
    await _send(user, subject, [escape(what), "If you did not do this, change your password and contact support straight away."])