"""Verify a Svix-signed webhook (this is how Resend signs its delivery webhooks).

Spec: signed content is f"{svix-id}.{svix-timestamp}.{raw body}", HMAC-SHA256 with the secret's base64-decoded
part after the "whsec_" prefix; the svix-signature header holds space-separated "v1,<base64>" entries (any
one may match, which supports secret rotation); the timestamp must be within a tolerance window.
"""

import base64
import hashlib
import hmac
import time
from collections.abc import Mapping


def sign(secret: str, msg_id: str, timestamp: str, body: bytes) -> str:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    digest = hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def verify(secret: str, headers: Mapping[str, str], body: bytes, tolerance: int = 300, now: float | None = None) -> bool:
    """True only for an authentic, recent webhook. Never raises."""
    try:
        msg_id = headers["svix-id"]
        timestamp = headers["svix-timestamp"]
        signatures = headers["svix-signature"]
        if abs((now if now is not None else time.time()) - int(timestamp)) > tolerance:
            return False
        expected = sign(secret, msg_id, timestamp, body)
        for part in signatures.split():
            version, _, sig = part.partition(",")
            if version == "v1" and hmac.compare_digest(sig, expected):
                return True
    except Exception:  # noqa: BLE001 - missing header, bad base64, non-numeric timestamp...
        return False
    return False
