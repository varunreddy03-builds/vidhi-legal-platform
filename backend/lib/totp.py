"""Time-based one-time codes (RFC 6238, 6 digits, 30 seconds, SHA-1: what every authenticator app expects)."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    n = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10**DIGITS)
    return str(n).zfill(DIGITS)


def current_step(at: float | None = None) -> int:
    return int((time.time() if at is None else at) // STEP)


def code_at(secret: str, at: float | None = None) -> str:
    return _code(secret, current_step(at))


def verify(secret: str, code: str, *, last_step: int = 0, at: float | None = None) -> int | None:
    """The time step the code belongs to, or None. A step at or before `last_step` is refused (a code works once).
    One step either side is allowed for clock drift."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now_step = current_step(at)
    for step in (now_step - 1, now_step, now_step + 1):
        if step > last_step and hmac.compare_digest(_code(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, account: str, issuer: str = "VIDHI") -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP}"