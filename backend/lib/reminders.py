"""The reminder job for saved dates: email, browser notification and (opt-in) text message.

Runs every few minutes (POST /api/cron/deadline-reminders). Each reminder is CLAIMED with one atomic update before anything is sent, so two
overlapping runs, a retried trigger or several servers can never send the same reminder twice. If a send channel fails, the reminder is not
retried (a late or repeated reminder about a court date is worse than a missed channel); the other channels still go out.

What is sent: the saved title goes only in the email to the person who saved the date. Text messages and browser notifications are generic
(no names, no case details), because they pass through phone networks and push services."""

import logging
import os
from datetime import timedelta
from html import escape

from lib import deadlines as dl
from lib import phone_alerts, webpush
from lib.auth import now
from lib.branding import email_logo_header
from lib.db import db
from lib.outbound import send_logged

logger = logging.getLogger(__name__)
LOOKAHEAD = timedelta(minutes=max(dl.ALLOWED_OFFSETS) + 60)


def generic_text(minutes: int) -> str:
    return f"A date you saved in VIDHI is coming up {dl.LABEL.get(minutes, 'soon')}. Open the app for details."


async def _email(d: dict, user: dict, minutes: int) -> None:
    app = os.environ.get("APP_URL", "").rstrip("/")
    link = f'<p><a href="{escape(app)}/deadlines">Open your dates</a></p>' if app.startswith("https://") else ""
    when = dl.pretty(d["starts_at"], d.get("tz") or dl.DEFAULT_TZ)
    html = (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;max-width:560px">'
        f"{await email_logo_header(d['organization_id'])}"
        f"<p>Hi {escape(user.get('full_name') or 'there')},</p>"
        f"<p>A date you saved is coming up {escape(dl.LABEL.get(minutes, 'soon'))}:</p>"
        f"<p><strong>{escape(d['title'])}</strong><br>{escape(when)}</p>{link}"
        f'<p style="font-size:12px;color:#888">{escape(dl.DISCLAIMER)}</p></td></tr></table>'
    )
    await send_logged(to=user["email"], subject=f"Reminder: {d['title']}"[:150], html=html, kind="deadline-reminder",
                      user=user, organization_id=d["organization_id"], respect_suppression=False)


async def send_reminder(d: dict, minutes: int) -> dict:
    """Send one claimed reminder on the channels the date asked for. Returns what happened per channel (never raises)."""
    channels, out = d.get("channels") or {}, {}
    user = await db.users.find_one({"id": d["created_by"]})
    if not user:
        return out
    if channels.get("email", True) and user.get("email"):
        try:
            await _email(d, user, minutes)
            out["email"] = True
        except Exception:  # noqa: BLE001
            logger.info("deadline email not sent", exc_info=True)
            out["email"] = False
    if channels.get("push", True):
        out["push"] = await webpush.notify_user(user["id"], "VIDHI reminder", generic_text(minutes)) > 0
    if channels.get("sms", False):  # only reaches a phone the person verified and switched alerts on for (lib/phone_alerts.py)
        out["sms"] = await phone_alerts.notify_user(user["id"], generic_text(minutes))
    return out


async def run_deadline_reminders() -> dict:
    moment, sent, looked = now(), 0, 0
    cursor = db.deadlines.find({"status": "OPEN", "starts_at": {"$gt": moment, "$lte": moment + LOOKAHEAD}})
    async for d in cursor:
        looked += 1
        for minutes in dl.due_offsets(d, moment):
            claimed = await db.deadlines.update_one({"id": d["id"], f"sent.{minutes}": {"$exists": False}}, {"$set": {f"sent.{minutes}": moment}})
            if not claimed.modified_count:
                continue  # another run has it
            result = await send_reminder(d, minutes)
            await db.deadlines.update_one({"id": d["id"]}, {"$set": {f"sent_via.{minutes}": result}})
            sent += 1
    return {"checked": looked, "reminders_sent": sent}