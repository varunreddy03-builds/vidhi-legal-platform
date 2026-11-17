"""Two-step sign-in with an authenticator app (RFC 6238), plus one-time recovery codes.

Stored on the user: two_factor = {enabled, secret (sealed), last_step, recovery (hashes), enabled_at}. The secret is encrypted
(lib/crypto.py), a code works once (the last used time step is remembered), recovery codes are kept only as hashes and each
works once."""

import hashlib
import hmac
import os
import secrets

from lib import crypto, totp
from lib.db import db

AAD = b"vidhi-2fa-secret"
RECOVERY_COUNT = 8
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I: easy to read off a printout


def seal(secret: str) -> str:
    return crypto.seal_text(secret, AAD)


def unseal(sealed: str) -> str:
    return crypto.open_text(sealed, AAD)


def _pepper() -> bytes:
    return os.environ.get("LINK_SECRET", "vidhi").encode()


def _hash(code: str) -> str:
    norm = "".join(ch for ch in code.upper() if ch.isalnum())
    return hmac.new(_pepper(), norm.encode(), hashlib.sha256).hexdigest()


def new_recovery_codes() -> tuple[list[str], list[str]]:
    """(codes to show the person once, hashes to store)."""
    codes = []
    for _ in range(RECOVERY_COUNT):
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes, [_hash(c) for c in codes]


def is_enabled(user: dict) -> bool:
    return bool((user.get("two_factor") or {}).get("enabled"))


async def check_second_factor(user: dict, code: str) -> bool:
    """True if `code` is a fresh authenticator code or an unused recovery code (which is then used up)."""
    tf = user.get("two_factor") or {}
    if not tf.get("enabled"):
        return True
    step = totp.verify(unseal(tf["secret"]), code, last_step=int(tf.get("last_step") or 0))
    if step is not None:
        # only the first request carrying this step wins: a second one at the same moment finds last_step already moved
        res = await db.users.update_one(
            {"id": user["id"], "$or": [{"two_factor.last_step": {"$lt": step}}, {"two_factor.last_step": {"$exists": False}}]},
            {"$set": {"two_factor.last_step": step}},
        )
        return res.modified_count == 1
    h = _hash(code)
    if len(h) and any(hmac.compare_digest(h, x) for x in tf.get("recovery", [])):
        res = await db.users.update_one({"id": user["id"], "two_factor.recovery": h}, {"$pull": {"two_factor.recovery": h}})
        return res.modified_count == 1
    return False