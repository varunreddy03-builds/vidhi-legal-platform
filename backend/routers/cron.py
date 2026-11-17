"""Platform-cron endpoint: gentle reminder emails for stalled recovery cases."""

import hmac
import logging
import os
from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from lib.auth import now
from lib.balance import position
from lib import recovery_mode
from lib.locks import acquire, release
from lib.monitoring import error_label, where
from lib.branding import email_logo_header
from lib.db import db
from lib.outbound import send_logged

logger = logging.getLogger(__name__)
router = APIRouter(tags=["cron"])

CRON_SECRET = os.environ.get("WEBHOOK_CRON_SECRET", "")
APP_URL = os.environ.get("APP_URL", "").rstrip("/")
STALE_DAYS = 3
ACTIVE_STATUSES = ("DRAFT", "PROOF_ADDED", "TIMELINE_READY", "NOTICE_READY")

NEXT_STEP = {
    "DRAFT": "add a proof document or screenshot",
    "PROOF_ADDED": "tap “Understand my case”",
    "TIMELINE_READY": "create your demand notice",
    "NOTICE_READY": "download the notice or send it for a lawyer to review",
}


def _aware(dt) -> datetime:
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def reminder_email(case: dict, owner_name: str, link: str, header: str = "") -> tuple[str, str]:
    """Build the reminder (subject, html). Shared by the cron and the manual 'send now'."""
    cta = (
        f'<p><a href="{escape(link)}" style="color:#5B8CFF">Open your recovery</a></p>'
        if link.startswith("https://")
        else ""
    )
    step_hint = escape(NEXT_STEP.get(case.get("status", ""), "continue your recovery"))
    subject = f"A quick nudge on your recovery against {case.get('debtor_name', '')}".strip()
    html = (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;'
        'font-family:Arial,sans-serif;max-width:560px">'
        f"{header}"
        f"<p>Hi {escape(owner_name)},</p>"
        f"<p>Your recovery of money from <strong>{escape(case.get('debtor_name', ''))}</strong> "
        "has been paused for a few days. You're closer than you think — the next small step is to "
        f"<strong>{step_hint}</strong>.</p>"
        f"{cta}"
        '<p style="font-size:12px;color:#888">Sent by VIDHI Legal Recovery, a free self-help tool. '
        "This is information, not legal advice. We never ask for your password or card details by "
        "email.</p></td></tr></table>"
    )
    return subject, html


async def _run_reminders() -> None:
    async for c in db.recovery_cases.find({"status": {"$in": list(ACTIVE_STATUSES)}}).sort("updated_at", 1):  # every case, oldest first, however many there are
        if not c.get("reminders_enabled", True):
            continue  # owner turned nudges off
        snooze = c.get("snooze_until")
        if snooze and _aware(snooze) > now():
            continue  # snoozed
        cadence = c.get("reminder_cadence_days", STALE_DAYS)
        case_cutoff = now() - timedelta(days=cadence)
        if _aware(c.get("updated_at")) > case_cutoff:
            continue  # moved within its cadence window — no nudge yet
        last = c.get("last_reminded_at")
        if last and _aware(last) > case_cutoff:
            continue  # already nudged within the cadence window
        owner = await db.users.find_one({"id": c.get("created_by")})
        if not owner or not owner.get("email") or not owner.get("email_verified"):
            continue  # only ever mail an address its owner has confirmed
        link = f"{APP_URL}/recovery/cases/{c['id']}" if APP_URL else ""
        header = await email_logo_header(c["organization_id"])
        subject, html = reminder_email(c, owner.get("full_name") or "there", link, header)
        try:
            await send_logged(
                to=owner["email"], subject=subject, html=html, kind="reminder",
                organization_id=c["organization_id"], case_id=c["id"], respect_suppression=False,
            )
            await db.recovery_cases.update_one(
                {"id": c["id"]}, {"$set": {"last_reminded_at": now()}}
            )
        except Exception:  # noqa: BLE001 — one bad send must not stop the batch
            continue


async def _run_locked(name: str, job) -> None:
    """Run a scheduled job, remember how it went (read by /api/health/ready), and always free the lock."""
    started = now()
    try:
        result = await job()
        await db.job_runs.update_one(
            {"_id": name}, {"$set": {"last_ok_at": now(), "last_started_at": started, "last_error": None, "last_result": result if isinstance(result, dict) else None}}, upsert=True
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("scheduled job %s failed: %s at %s", name, error_label(exc), where(exc))  # no message: it could repeat what the job was reading
        await db.job_runs.update_one(
            {"_id": name}, {"$set": {"last_failed_at": now(), "last_started_at": started, "last_error": error_label(exc)}}, upsert=True
        )
    finally:
        await release(name)


def _check_cron_auth(authorization: str | None) -> None:
    if not CRON_SECRET or not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ", 1)[1]
    if not hmac.compare_digest(token, CRON_SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/cron/recovery-reminders")
async def recovery_reminders(
    background: BackgroundTasks, authorization: str | None = Header(default=None)
):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _check_cron_auth(authorization)
    if not recovery_mode.enabled():
        return {"status": "disabled"}  # Legal Recovery is switched off: no e-mail is sent about it
    if not await acquire("recovery-reminders", 1800):
        return {"status": "already_running"}
    background.add_task(_run_locked, "recovery-reminders", _run_reminders)
    return {"status": "accepted"}


async def _run_scheduled_statements() -> None:
    """Email active case owners a balance statement on their chosen cadence (cases still owing)."""
    import base64
    import calendar
    import uuid as _uuid

    from lib.branding import get_branding
    from lib.outbound import send_logged
    from routers.recovery import _build_statement_pdf, cc_stop_footer, confirmed_cc, statement_html

    today = now()
    async for c in db.recovery_cases.find({"status": {"$in": list(ACTIVE_STATUSES)}}).sort("updated_at", 1):
        schedule = c.get("statement_schedule", "MONTHLY")
        if schedule not in ("MONTHLY", "FORTNIGHTLY"):
            continue  # owner turned auto-statements off
        paused = c.get("statement_paused_until")
        if paused and _aware(paused) > today:
            continue  # owner paused auto-statements until a future date
        pos = position(c)  # the owner's own figures only, to the paisa
        owed, received, balance = pos["owed"], pos["received"], pos["remaining"]
        if balance <= 0:
            continue  # nothing outstanding (or no amount entered) - skip
        last = c.get("last_statement_sent_at")
        last_aware = _aware(last) if last else None
        if last_aware and last_aware.date() == today.date():
            continue  # already sent today
        if schedule == "MONTHLY":
            day = c.get("statement_day", 1)
            dim = calendar.monthrange(today.year, today.month)[1]
            if today.day != min(day, dim):
                continue
        elif last_aware is not None and (today - last_aware) < timedelta(days=14):
            continue  # FORTNIGHTLY — not yet 14 days since the last send
        owner = await db.users.find_one({"id": c.get("created_by")})
        if not owner or not owner.get("email") or not owner.get("email_verified"):
            continue  # only ever mail an address its owner has confirmed
        branding = await get_branding(c["organization_id"])
        header = await email_logo_header(c["organization_id"])
        attach = [
            {
                "filename": f"statement-{c['id'][:8]}.pdf",
                "content": base64.b64encode(_build_statement_pdf(c, branding)).decode(),
            }
        ]
        subject = f"Your balance statement — {c.get('debtor_name', '')}".strip()
        try:
            await send_logged(
                to=owner["email"],
                subject=subject,
                html=statement_html(c, header),
                kind="statement-owner",
                organization_id=c["organization_id"],
                case_id=c["id"],
                attachments=attach,
                respect_suppression=False,
            )
        except Exception:  # noqa: BLE001 — owner undeliverable; skip this case
            continue
        cc_sent: list[str] = []
        # Only accountants who confirmed by link are ever copied; each copy carries a stop link.
        for a in [e for e in confirmed_cc(c) if e.lower() != owner["email"].lower()]:
            try:
                await send_logged(
                    to=a,
                    subject=subject,
                    html=statement_html(c, header, cc_stop_footer(c, a)),
                    kind="statement-cc",
                    organization_id=c["organization_id"],
                    case_id=c["id"],
                    attachments=attach,
                )
                cc_sent.append(a)
            except Exception:  # noqa: BLE001 — one bad CC must not block the rest
                pass
        await db.recovery_cases.update_one(
            {"id": c["id"]},
            {
                "$set": {"last_statement_sent_at": now()},
                "$push": {
                    "statement_log": {
                        "id": str(_uuid.uuid4()),
                        "email": owner["email"],
                        "date": now(),
                        "via": "scheduled",
                        "owed": owed,
                        "received": received,
                        "balance": balance,
                        "cc": cc_sent,
                    }
                },
            },
        )


@router.post("/cron/scheduled-statements")
async def scheduled_statements(
    background: BackgroundTasks, authorization: str | None = Header(default=None)
):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _check_cron_auth(authorization)
    if not recovery_mode.enabled():
        return {"status": "disabled"}  # scheduled statements belong to Legal Recovery
    if not await acquire("scheduled-statements", 1800):
        return {"status": "already_running"}
    background.add_task(_run_locked, "scheduled-statements", _run_scheduled_statements)
    return {"status": "accepted"}


@router.post("/cron/deadline-reminders")
async def deadline_reminders(background: BackgroundTasks, authorization: str | None = Header(default=None)):
    """Every few minutes: reminders for saved dates that are coming up (email, browser notification, opt-in text)."""
    _check_cron_auth(authorization)
    if not await acquire("deadline-reminders", 600):
        return {"status": "already_running"}
    from lib.reminders import run_deadline_reminders

    background.add_task(_run_locked, "deadline-reminders", run_deadline_reminders)
    return {"status": "accepted"}


@router.post("/cron/jobs")
async def run_background_jobs(background: BackgroundTasks, authorization: str | None = Header(default=None)):
    """Every few minutes: long background work (such as reading scanned law PDFs). Jobs are leased, retried a limited number of times, and safe to run again."""
    _check_cron_auth(authorization)
    if not await acquire("jobs", 600):
        return {"status": "already_running"}
    from lib import jobs
    from lib.job_handlers import HANDLERS

    async def run():
        return await jobs.run_batch(HANDLERS, 5)

    background.add_task(_run_locked, "jobs", run)
    return {"status": "accepted"}


@router.post("/cron/upload-expiry")
async def upload_expiry_sweep(background: BackgroundTasks, authorization: str | None = Header(default=None)):
    """Deletes uploaded documents that reached the ceiling set by UPLOAD_MAX_DAYS (after emailing the owners). Does nothing when that setting is off."""
    _check_cron_auth(authorization)
    if not await acquire("upload-expiry", 3600):
        return {"status": "already_running"}
    from lib.upload_expiry import run_upload_expiry

    background.add_task(_run_locked, "upload-expiry", run_upload_expiry)
    return {"status": "accepted"}


@router.post("/cron/retention")
async def retention_sweep(background: BackgroundTasks, authorization: str | None = Header(default=None)):
    """Deletes (after notice) closed matters / resolved cases of organisations that set a retention period."""
    _check_cron_auth(authorization)
    if not await acquire("retention", 3600):
        return {"status": "already_running"}
    from lib.retention import run_retention

    background.add_task(_run_locked, "retention", run_retention)
    return {"status": "accepted"}
