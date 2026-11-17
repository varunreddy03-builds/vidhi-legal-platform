"""Retention: CLOSED matters and RESOLVED recovery cases are deleted automatically N days after they were closed/resolved, when the organisation chose N, or when the operator set a
platform default (DEFAULT_RETENTION_DAYS_AFTER_CLOSE, off unless set) and the organisation did not choose. An organisation can always choose its own number, or 0 to keep everything until
it deletes it. On top of that, the platform's own operational records (email log, support tickets, usage counters, activity log, questions asked outside any matter) expire after
fixed default periods (`OPERATIONAL` below); each period can be changed with its setting, and 0 turns that one off. All of these defaults are choices made in code, not legal advice:
an advocate must confirm them (docs/PRIVACY_REVIEW.md).

Safety rules
  * two steps: first the owners are emailed a list and the items get a deletion_notice_at; only after NOTICE_DAYS
    more days are they actually deleted. Re-opening an item (or putting a matter under legal hold) cancels it.
  * a matter under legal hold is never touched.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from html import escape

from lib.db import db
from lib.outbound import send_logged, simple_email
from lib.purge import purge_case, purge_matter

logger = logging.getLogger(__name__)

NOTICE_DAYS = 30
MIN_DAYS = 30
MAX_DAYS = 3650


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _env_days(name: str, default: int) -> int:
    """A number of days from a setting: 0 means off; a missing, invalid or negative value means the default."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        days = int(raw)
    except ValueError:
        return default
    return days if 0 <= days <= MAX_DAYS else default


def platform_default_days() -> int:
    """The closed-matter period used for organisations that did not choose their own (0 = none). Never shorter than MIN_DAYS."""
    days = _env_days("DEFAULT_RETENTION_DAYS_AFTER_CLOSE", 0)
    return days if days >= MIN_DAYS else 0


# (collection, date field, setting, default days, what it holds). The audit trail of a deleted matter is already blanked; these are the platform's own records, kept for a fixed time.
OPERATIONAL = (
    ("email_log", "created_at", "EMAIL_LOG_DAYS", 365, "who the platform emailed and the first words of the subject"),
    ("support_tickets", "created_at", "SUPPORT_TICKET_DAYS", 365, "messages people wrote to support"),
    ("usage_events", "timestamp", "USAGE_EVENT_DAYS", 400, "counters of what was used (ids only)"),
    ("audit_events", "created_at", "AUDIT_EVENT_DAYS", 730, "the activity log of each organisation"),
)
RESEARCH_NO_MATTER_DEFAULT_DAYS = 90  # questions and answers not tied to any matter (typed straight into Ask): nothing deletes them with a matter


async def purge_operational(now: datetime | None = None) -> dict:
    """Delete platform records past their period. Returns counts per collection. A period of 0 skips that collection."""
    now = now or _now()
    out: dict[str, int] = {}
    for coll, field, setting, default, _ in OPERATIONAL:
        days = _env_days(setting, default)
        if days:
            out[coll] = (await db[coll].delete_many({field: {"$lt": now - timedelta(days=days)}})).deleted_count
    days = _env_days("RESEARCH_NO_MATTER_DAYS", RESEARCH_NO_MATTER_DEFAULT_DAYS)
    if days:
        old = {"matter_id": None, "created_at": {"$lt": now - timedelta(days=days)}}
        ids = [r["id"] async for r in db.research_results.find(old, {"id": 1})]
        if ids:
            await db.answer_feedback.delete_many({"research_id": {"$in": ids}})
            out["research_results"] = (await db.research_results.delete_many({"id": {"$in": ids}})).deleted_count
    return out


# Toolkit reports (Authority Check, List of dates, Pre-filing defect check, Old-code checker) hold sentences from a client's draft. They are not tied to a matter, so they expire on their own:
# each new report records `expires_at`, and the sweep below deletes it after that. The default is 30 days (the same as the notice period above); TOOLKIT_REPORT_DAYS changes it.
TOOLKIT_COLLECTIONS = ("authority_reports", "date_lists", "defect_checks", "old_code_checks")
TOOLKIT_REPORT_DEFAULT_DAYS = 30


def toolkit_report_days() -> int:
    try:
        days = int(os.environ.get("TOOLKIT_REPORT_DAYS", TOOLKIT_REPORT_DEFAULT_DAYS))
    except ValueError:
        return TOOLKIT_REPORT_DEFAULT_DAYS
    return days if 1 <= days <= MAX_DAYS else TOOLKIT_REPORT_DEFAULT_DAYS


def report_expiry() -> str:
    """When a report made now is deleted automatically (an ISO date-time, UTC)."""
    return (_now() + timedelta(days=toolkit_report_days())).isoformat()


async def purge_toolkit_reports() -> int:
    """Deletes every Toolkit report past its expiry. A report made before expiry dates existed is judged by its creation time instead."""
    now = _now()
    old = (now - timedelta(days=toolkit_report_days())).isoformat()
    total = 0
    for name in TOOLKIT_COLLECTIONS:
        res = await db[name].delete_many({"$or": [{"expires_at": {"$lt": now.isoformat()}}, {"expires_at": {"$exists": False}, "created_at": {"$lt": old}}]})
        total += res.deleted_count
    return total


def _aware(dt) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _notify_owners(org_id: str, org_name: str, matters: list[str], cases: list[str], days: int) -> None:
    owners = await db.users.find({"organization_id": org_id, "role": "OWNER"}).to_list(20)
    rows = "".join(f"<li>{escape(t)}</li>" for t in matters + cases)
    html = simple_email(
        [
            f"Your organisation <strong>{escape(org_name)}</strong> keeps closed matters and resolved recoveries for "
            f"{days} days. These items will be <strong>permanently deleted in {NOTICE_DAYS} days</strong>:",
            f"<ul>{rows}</ul>",
            "To keep one, re-open it (or place a matter under legal hold) before then. Owners and admins can also download "
            "an export of everything from Settings > Data & privacy.",
        ]
    )
    for o in owners:
        try:
            await send_logged(
                to=o["email"], subject="Items will be deleted in 30 days", html=html, kind="retention-notice",
                organization_id=org_id, respect_suppression=False,
            )
        except Exception:  # noqa: BLE001 - a mail problem must not stop the sweep; the notice is re-sent next run
            logger.exception("retention notice email failed")
            raise


async def run_retention() -> dict:
    summary = {"notified": 0, "deleted_matters": 0, "deleted_cases": 0, "organisations": 0, "deleted_reports": 0}
    now = _now()
    summary["deleted_reports"] = await purge_toolkit_reports()
    summary["operational"] = await purge_operational(now)
    from lib import product_stats

    summary["product_rows_removed"] = await product_stats.trim(now)
    default_days = platform_default_days()
    flt = {} if default_days else {"retention_days_after_close": {"$gte": MIN_DAYS}}  # with no platform default only organisations that chose a period are looked at
    async for org in db.organizations.find(flt):
        chosen = org.get("retention_days_after_close")  # absent: use the default; 0 or None-after-choosing: keep everything
        days = int(chosen) if isinstance(chosen, int) and not isinstance(chosen, bool) else default_days
        if days < MIN_DAYS:
            continue  # 0 = this organisation keeps everything until it deletes it
        cutoff = now - timedelta(days=days)
        due_before = now - timedelta(days=NOTICE_DAYS)
        summary["organisations"] += 1
        to_notify_m: list[tuple[str, str]] = []
        to_notify_c: list[tuple[str, str]] = []
        for m in await db.matters.find({"organization_id": org["id"], "status": "CLOSED", "legal_hold": {"$ne": True}}).to_list(5000):
            closed = _aware(m.get("closed_at")) or _aware(m.get("updated_at"))
            if not closed or closed > cutoff:
                continue
            notice = _aware(m.get("deletion_notice_at"))
            if notice is None:
                to_notify_m.append((m["id"], m["title"]))
            elif notice <= due_before:
                await purge_matter(m["id"])
                summary["deleted_matters"] += 1
        for c in await db.recovery_cases.find({"organization_id": org["id"], "status": "RESOLVED"}).to_list(5000):
            resolved = _aware(c.get("resolved_at")) or _aware(c.get("updated_at"))
            if not resolved or resolved > cutoff:
                continue
            notice = _aware(c.get("deletion_notice_at"))
            label = f"Recovery: {c.get('creditor_name', '')} vs {c.get('debtor_name', '')}"
            if notice is None:
                to_notify_c.append((c["id"], label))
            elif notice <= due_before:
                await purge_case(c["id"])
                summary["deleted_cases"] += 1
        if to_notify_m or to_notify_c:
            try:
                await _notify_owners(org["id"], org.get("name", ""), [t for _, t in to_notify_m], [t for _, t in to_notify_c], days)
            except Exception:  # noqa: BLE001 - this organisation is tried again next run; the others must still be swept
                summary["notice_failed"] = summary.get("notice_failed", 0) + 1
                continue
            # mark only after the owners were told, so a failed email means the notice is tried again next run
            for mid, _ in to_notify_m:
                await db.matters.update_one({"id": mid}, {"$set": {"deletion_notice_at": now}})
            for cid, _ in to_notify_c:
                await db.recovery_cases.update_one({"id": cid}, {"$set": {"deletion_notice_at": now}})
            summary["notified"] += len(to_notify_m) + len(to_notify_c)
    return summary
