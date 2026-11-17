"""Encryption at rest (AES-256-GCM).

DATA_ENCRYPTION_KEY holds one or more urlsafe-base64 32-byte keys separated by commas. The FIRST key encrypts; every key
is tried when reading, so a key can be rotated by putting the new one first and keeping the old one until old files are
re-saved. Without a key, uploaded files are stored as before (so a missing key can never lock anyone out of their papers)
and the startup log says so. Stored files carry a short header, so files saved before encryption was switched on still read.
Generate a key with:  python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
"""

import base64
import hashlib
import hmac
import logging
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

MAGIC = b"VDENC1"  # six-byte header on every encrypted blob
NONCE = 12


def _decode(k: str) -> bytes:
    raw = base64.urlsafe_b64decode(k.strip() + "=" * (-len(k.strip()) % 4))
    if len(raw) != 32:
        raise ValueError("each key in DATA_ENCRYPTION_KEY must be 32 bytes (urlsafe base64)")
    return raw


def configured_keys() -> list[bytes]:
    raw = os.environ.get("DATA_ENCRYPTION_KEY", "").strip()
    return [_decode(k) for k in raw.split(",") if k.strip()]


def enabled() -> bool:
    return bool(configured_keys())


def _derived_key() -> bytes:
    """A fallback for SMALL secrets only (two-step sign-in keys): derived from LINK_SECRET, which the app already requires."""
    seed = os.environ.get("LINK_SECRET", "")
    if not seed:
        raise RuntimeError("Set DATA_ENCRYPTION_KEY (or LINK_SECRET) so secrets can be protected.")
    return hmac.new(seed.encode(), b"vidhi-small-secrets-v1", hashlib.sha256).digest()


def encrypt(data: bytes, aad: bytes = b"", *, fallback: bool = False) -> bytes:
    keys = configured_keys()
    if not keys:
        if not fallback:
            return data
        keys = [_derived_key()]
    nonce = os.urandom(NONCE)
    return MAGIC + nonce + AESGCM(keys[0]).encrypt(nonce, data, aad)


def decrypt(blob: bytes, aad: bytes = b"", *, fallback: bool = False) -> bytes:
    """Plain (legacy) blobs come back unchanged; encrypted ones need a key that opens them."""
    if not blob.startswith(MAGIC):
        return blob
    body = blob[len(MAGIC):]
    nonce, ct = body[:NONCE], body[NONCE:]
    keys = configured_keys()
    if fallback:
        keys = keys + [_derived_key()]
    for k in keys:
        try:
            return AESGCM(k).decrypt(nonce, ct, aad)
        except InvalidTag:
            continue
    raise ValueError("this file is encrypted and none of the configured keys opens it")


def seal_text(text: str, aad: bytes) -> str:
    """For small secrets kept in the database (always encrypted: with DATA_ENCRYPTION_KEY, else a LINK_SECRET-derived key)."""
    return base64.urlsafe_b64encode(encrypt(text.encode(), aad, fallback=True)).decode()


def open_text(sealed: str, aad: bytes) -> str:
    return decrypt(base64.urlsafe_b64decode(sealed.encode()), aad, fallback=True).decode()