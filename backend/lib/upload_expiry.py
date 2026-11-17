"""Upload expiry: a hard ceiling on how long an uploaded document is kept (decision D5: 30 days at most).

Off unless UPLOAD_MAX_DAYS is set (the production and staging settings set it to 30). When on:
  * NOTICE_DAYS before a document reaches the ceiling, the organisation's owners are emailed the list of files and the date they will be deleted; each file is marked with
    expiry_notice_at only AFTER the email went out, so a failed email is tried again on the next run.
  * once a document is UPLOAD_MAX_DAYS old and its notice was sent, it is deleted for real with lib/purge.purge_document (the same code as the delete button).
    If the notice could not be sent, the document is still deleted GRACE_DAYS after the ceiling, because the ceiling is the promise.
  * a matter under legal hold is never touched, and a user can always delete a document at once from the matter.
  * the audit trail records that an upload expired (document id only, no file name or text)."""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from html import escape

from lib.db import db
from lib.outbound import send_logged, simple_email
from lib.purge import purge_document

logger = logging.getLogger(__name__)

NOTICE_DAYS = 7
GRACE_DAYS = 3
MIN_DAYS, MAX_DAYS = 8, 365  # shorter than the notice period would delete without warning


def max_days() -> int:
    """The ceiling in days, or 0 when expiry is off. A value outside the allowed range counts as off, and is logged."""
    raw = os.environ.get("UPLOAD_MAX_DAYS", "").strip()
    if not raw:
        return 0
    try:
        n = int(raw)
    except ValueError:
        logger.warning("UPLOAD_MAX_DAYS is not a whole number: upload expiry stays off")
        return 0
    if n == 0:
        return 0
    if not MIN_DAYS <= n <= MAX_DAYS:
        logger.warning("UPLOAD_MAX_DAYS must be between %s and %s: upload expiry stays off", MIN_DAYS, MAX_DAYS)
        return 0
    return n


def _aware(dt) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _notify(org_id: str, org_name: str, rows: list[tuple[str, str]], days: int) -> None:
    owners = await db.users.find({"organization_id": org_id, "role": "OWNER"}).to_list(20)
    items = "".join(f"<li>{escape(name)} (delete on {when})</li>" for name, when in rows)
    html = simple_email([
        f"Files uploaded to <strong>{escape(org_name)}</strong> on VIDHI are kept for at most {days} days. These files will be <strong>permanently deleted</strong> on the dates shown:",
        f"<ul>{items}</ul>",
        "To keep a file, download it from its matter before then. You can also delete any file at once from its matter. A matter under legal hold is never deleted.",
    ])
    for o in owners:
        await send_logged(to=o["email"], subject=f"Uploaded files will be deleted within {NOTICE_DAYS} days", html=html, kind="upload-expiry-notice", organization_id=org_id, respect_suppression=False)


async def run_upload_expiry(days: int | None = None, now: datetime | None = None, only_org: str | None = None) -> dict:
    """`only_org` limits one run to a single organisation (used by tests so that runs do not touch each other's data); `now` lets a test move the clock."""
    days = max_days() if days is None else days
    summary = {"enabled": bool(days), "notified": 0, "deleted": 0, "notice_failed": 0}
    if not days:
        return summary
    now = now or datetime.now(timezone.utc)
    held = {m["id"] async for m in db.matters.find({"legal_hold": True}, {"id": 1})}
    warn_before = now - timedelta(days=days - NOTICE_DAYS)
    ceiling = now - timedelta(days=days)
    hard_ceiling = now - timedelta(days=days + GRACE_DAYS)

    # 1. delete what reached the ceiling (notice sent) or the ceiling plus the grace period
    scope = {"organization_id": only_org} if only_org else {}
    async for d in db.documents.find({"created_at": {"$lte": ceiling}, **scope}):
        if d["matter_id"] in held:
            continue
        created = _aware(d.get("created_at"))
        if not created:
            continue
        if d.get("expiry_notice_at") is None and created > hard_ceiling:
            continue  # the notice has not gone out yet; it is sent below, and the grace period still protects the owner's right to be told
        await purge_document(d)
        await db.audit_events.insert_one({"id": str(uuid.uuid4()), "organization_id": d["organization_id"], "user_id": "system", "user_email": "system", "matter_id": d["matter_id"],
                                          "operation": "UPLOAD_EXPIRED", "result": "SUCCESS", "detail": d["id"], "created_at": now})
        summary["deleted"] += 1

    # 2. tell the owners about files that will expire within NOTICE_DAYS
    by_org: dict[str, list[dict]] = {}
    async for d in db.documents.find({"created_at": {"$lte": warn_before}, "expiry_notice_at": None, **scope}):
        if d["matter_id"] not in held:
            by_org.setdefault(d["organization_id"], []).append(d)
    for org_id, docs in by_org.items():
        org = await db.organizations.find_one({"id": org_id}) or {}
        rows = [(d["filename"], (_aware(d["created_at"]) + timedelta(days=days)).date().isoformat()) for d in docs]
        try:
            await _notify(org_id, org.get("name", ""), rows, days)
        except Exception:  # noqa: BLE001 - tried again next run; the others must still be swept
            logger.exception("upload expiry notice failed")
            summary["notice_failed"] += 1
            continue
        await db.documents.update_many({"id": {"$in": [d["id"] for d in docs]}}, {"$set": {"expiry_notice_at": now}})
        summary["notified"] += len(docs)
    return summary
