"""Twilio SMS / WhatsApp, used ONLY for short alerts to the account owner who verified their own phone and opted in.
It is never used to contact a customer (the person who owes money): that would be unsolicited messaging.

Configuration: TWILIO_ACCOUNT_SID plus EITHER TWILIO_AUTH_TOKEN OR an API key (TWILIO_API_KEY_SID + TWILIO_API_KEY_SECRET, preferred: it can be revoked on its own),
and TWILIO_FROM (an SMS-capable number) and/or TWILIO_WHATSAPP_FROM
(e.g. whatsapp:+14155238886 for the sandbox). Inbound STOP replies come to <APP_URL>/api/webhooks/twilio (signed by Twilio).
TWILIO_STUB=true is for tests/dev only (messages are captured in the sms_outbox collection)."""

import base64
import hashlib
import hmac
import os
import re

_TRANSPORT = None  # tests inject an httpx.MockTransport here
E164 = re.compile(r"^\+[1-9]\d{7,14}$")
STOP_WORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}


class SmsError(Exception):
    pass


def stub_enabled() -> bool:
    return os.environ.get("TWILIO_STUB", "false").lower() == "true"


def _credentials() -> tuple[str, str] | None:
    """(username, password) for Twilio's API: an API key pair if set, else the account SID with its auth token."""
    if os.environ.get("TWILIO_API_KEY_SID") and os.environ.get("TWILIO_API_KEY_SECRET"):
        return os.environ["TWILIO_API_KEY_SID"], os.environ["TWILIO_API_KEY_SECRET"]
    if os.environ.get("TWILIO_ACCOUNT_SID") and os.environ.get("TWILIO_AUTH_TOKEN"):
        return os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]
    return None


def configured(channel: str = "sms") -> bool:
    if stub_enabled():
        return True
    if not (os.environ.get("TWILIO_ACCOUNT_SID") and _credentials()):
        return False
    return bool(os.environ.get("TWILIO_WHATSAPP_FROM" if channel == "whatsapp" else "TWILIO_FROM"))


def normalise(number: str) -> str:
    """+91 98765 43210 -> +919876543210 ; raises ValueError unless it is a valid international number."""
    n = re.sub(r"[\s\-().]", "", number or "")
    if not E164.match(n):
        raise ValueError("Enter the number with its country code, for example +91 98765 43210.")
    return n


def pepper() -> bytes:
    return os.environ.get("LINK_SECRET", "vidhi").encode()


def number_hash(number: str) -> str:
    return hmac.new(pepper(), number.encode(), hashlib.sha256).hexdigest()


async def send(to: str, body: str, channel: str = "sms") -> str:
    """Send one message; returns Twilio's message sid. Raises SmsError."""
    if stub_enabled():
        from datetime import datetime, timezone

        from lib.db import db

        await db.sms_outbox.insert_one({"to": to, "channel": channel, "body": body, "created_at": datetime.now(timezone.utc)})
        return "SMstub"
    if not configured(channel):
        raise SmsError("Twilio is not configured for this channel")
    import httpx

    sid, creds = os.environ["TWILIO_ACCOUNT_SID"], _credentials()
    sender = os.environ["TWILIO_WHATSAPP_FROM" if channel == "whatsapp" else "TWILIO_FROM"]
    dest = f"whatsapp:{to}" if channel == "whatsapp" else to
    async with httpx.AsyncClient(timeout=20.0, transport=_TRANSPORT) as c:
        r = await c.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", auth=creds, data={"From": sender, "To": dest, "Body": body})
    if r.status_code >= 400:
        raise SmsError(f"Twilio failed with {r.status_code}")
    return r.json().get("sid", "")


def valid_signature(url: str, params: dict, signature: str | None) -> bool:
    """Twilio signs the full URL followed by each POST parameter (sorted by name, name+value) with HMAC-SHA1 and the auth token."""
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not token or not signature:
        return False
    data = url + "".join(k + str(params[k]) for k in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature)