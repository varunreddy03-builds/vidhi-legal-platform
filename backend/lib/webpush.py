"""Browser push notifications (Web Push with VAPID). Works in Chrome, Edge, Firefox and Safari (installed app on iPhone).

Settings:  VAPID_PRIVATE_KEY   the signing key, made once with `python scripts/make-vapid-keys.py` (secret: .env only)
           VAPID_SUBJECT       optional mailto: contact for the push services (default: SUPPORT_EMAIL, else PRIVACY_CONTACT_EMAIL)
WEBPUSH_STUB=true is for tests/dev only (messages are captured in the push_outbox collection; nothing leaves the machine).

The public key shown to browsers is derived from the private key, so there is only one value to keep. Messages carry NO case details:
they only say a saved date is near. A subscription's address is where the server sends data, so it is accepted only for the real push
services of the browsers (never an arbitrary address a user could point the server at)."""

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from lib.db import db

logger = logging.getLogger(__name__)
# The push services of Chrome/Edge/Android (Google), Firefox (Mozilla), Edge on Windows, and Safari (Apple).
PUSH_HOSTS = ("fcm.googleapis.com", "push.services.mozilla.com", "notify.windows.com", "push.apple.com")
MAX_PER_USER = 5
STUB_KEY = "BPyQ2T6c5vGJm-stub-public-key-for-tests-only-0000000000000000000000000000000000000000000000000000000000000"[:87]


def stub_enabled() -> bool:
    return os.environ.get("WEBPUSH_STUB", "false").lower() == "true"


def _vapid():
    from py_vapid import Vapid

    raw = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    return Vapid.from_string(private_key=raw) if raw else None


def public_key() -> str | None:
    if stub_enabled():
        return STUB_KEY
    try:
        v = _vapid()
        if v is None:
            return None
        from cryptography.hazmat.primitives import serialization

        raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    except Exception:  # noqa: BLE001 - a bad key means push is simply unavailable
        logger.error("VAPID_PRIVATE_KEY is not valid; browser notifications are off")
        return None


def subject() -> str | None:
    contact = os.environ.get("SUPPORT_EMAIL") or os.environ.get("PRIVACY_CONTACT_EMAIL")
    return os.environ.get("VAPID_SUBJECT") or (f"mailto:{contact}" if contact else None)


def configured() -> bool:
    return stub_enabled() or bool(public_key() and subject())


def endpoint_allowed(endpoint: str) -> bool:
    try:
        p = urlparse(endpoint)
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    return p.scheme == "https" and not p.username and p.port in (None, 443) and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


async def send(sub: dict, payload: dict) -> bool:
    """Send one notification. True if delivered to the push service. A subscription the service says is gone is deleted."""
    if stub_enabled():
        await db.push_outbox.insert_one({"user_id": sub["user_id"], "endpoint": sub["endpoint"], "payload": payload, "created_at": datetime.now(timezone.utc)})
        return True
    if not configured():
        return False

    def go():
        from pywebpush import WebPushException, webpush

        try:
            webpush(
                subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]}, data=json.dumps(payload),
                vapid_private_key=_vapid(), vapid_claims={"sub": subject()}, ttl=3600, timeout=15,
            )
            return "ok"
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            return "gone" if code in (404, 410) else "failed"

    result = await asyncio.to_thread(go)
    if result == "gone":
        await db.push_subscriptions.delete_one({"endpoint": sub["endpoint"]})
    return result == "ok"


async def notify_user(user_id: str, title: str, body: str, url: str = "/deadlines") -> int:
    """Send to every device the person subscribed. Returns how many were delivered. Never raises."""
    delivered = 0
    try:
        async for sub in db.push_subscriptions.find({"user_id": user_id}):
            try:
                delivered += 1 if await send(sub, {"title": title, "body": body, "url": url}) else 0
            except Exception:  # noqa: BLE001 - one dead device must not stop the others
                logger.info("push to one device failed", exc_info=True)
    except Exception:  # noqa: BLE001
        logger.info("push not sent", exc_info=True)
    return delivered