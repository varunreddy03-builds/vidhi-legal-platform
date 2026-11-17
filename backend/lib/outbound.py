"""Every outbound email goes through here so it is logged, suppressible and its delivery is trackable.

Status meanings (be honest about what we know):
  ACCEPTED   handed to the email provider - NOT proof it reached the inbox
  DELIVERED  the provider told us it was delivered (webhook)
  BOUNCED    the provider told us the address could not receive it (webhook)
  COMPLAINED the recipient marked it as spam (webhook)
  FAILED     the provider refused it immediately
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from html import escape

from lib.db import db
from lib.email import send_email
from lib.monitoring import redact


class EmailSuppressed(Exception):
    """The address asked not to be emailed, or hard-bounced / complained earlier."""


def now() -> datetime:
    return datetime.now(timezone.utc)


def norm(address: str) -> str:
    return address.strip().lower()


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """(raw token to put in a link, sha256 to store)."""
    raw = secrets.token_urlsafe(32)
    return raw, sha256(raw)


async def is_suppressed(address: str) -> bool:
    return bool(await db.email_suppressions.find_one({"email": norm(address)}))


async def suppress(address: str, reason: str) -> None:
    await db.email_suppressions.update_one(
        {"email": norm(address)},
        {"$setOnInsert": {"email": norm(address), "reason": reason, "created_at": now()}},
        upsert=True,
    )


def link_html(url: str, text: str) -> str:
    """Clickable link when https; plain text otherwise (the email safety guard rejects non-https hrefs)."""
    if url.startswith("https://"):
        return f'<a href="{escape(url)}" style="color:#5B8CFF">{escape(text)}</a>'
    return escape(url)


def simple_email(paragraphs: list[str], header: str = "") -> str:
    """Wrap ALREADY-ESCAPED paragraph html in the standard VIDHI email shell."""
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;'
        'font-family:Arial,sans-serif;max-width:560px">'
        f"{header}{body}"
        '<p style="font-size:12px;color:#888">Sent by VIDHI. We never ask for your password or '
        "card details by email.</p></td></tr></table>"
    )


async def send_logged(
    *,
    to: str,
    subject: str,
    html: str,
    kind: str,
    user: dict | None = None,
    organization_id: str | None = None,
    case_id: str | None = None,
    attachments: list[dict] | None = None,
    respect_suppression: bool = True,
) -> str:
    """Send one email and record it. Raises EmailSuppressed or the provider error."""
    if respect_suppression and await is_suppressed(to):
        raise EmailSuppressed(to)
    log_id = str(uuid.uuid4())
    base = {
        "id": log_id,
        "organization_id": organization_id or (user or {}).get("organization_id"),
        "user_id": (user or {}).get("id"),
        "case_id": case_id,
        "kind": kind,
        "to": norm(to),
        "subject": subject[:200],
        "created_at": now(),
    }
    try:
        provider_id = await send_email(
            to=to, subject=subject, html=html, attachments=attachments, idempotency_key=log_id
        )
    except Exception as exc:  # noqa: BLE001
        await db.email_log.insert_one({**base, "status": "FAILED", "reason": redact(str(exc)), "provider_id": None})
        raise
    await db.email_log.insert_one({**base, "status": "ACCEPTED", "reason": None, "provider_id": provider_id})
    return log_id


CONSENT_DAYS = 30
VERIFY_HOURS = 48


def expiry(**kw) -> datetime:
    return now() + timedelta(**kw)


# ---------- signed links (consent / stop-receiving) ----------
_PROCESS_SECRET = secrets.token_bytes(32)


def _link_secret() -> bytes:
    """LINK_SECRET if set, else the cron secret; last resort is per-process (links die on restart)."""
    raw = os.environ.get("LINK_SECRET") or os.environ.get("WEBHOOK_CRON_SECRET")
    return raw.encode() if raw else _PROCESS_SECRET


def make_link_token(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(hmac.new(_link_secret(), body, hashlib.sha256).digest()).rstrip(b"=")
    return f"{body.decode()}.{sig.decode()}"


def read_link_token(token: str) -> dict | None:
    """The payload if the signature is valid, else None. Callers enforce their own expiry."""
    try:
        body, sig = token.split(".", 1)
        want = base64.urlsafe_b64encode(hmac.new(_link_secret(), body.encode(), hashlib.sha256).digest()).rstrip(b"=")
        if not hmac.compare_digest(sig.encode(), want):
            return None
        pad = "=" * (-len(body) % 4)
        data = json.loads(base64.urlsafe_b64decode(body + pad))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None
