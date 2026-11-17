"""Outbound email that reaches OTHER PEOPLE (debtor, accountants): preview + confirm, consent, delivery status.

Rules enforced here:
  - the sender must have verified their own email address (require_verified_sender)
  - a demand notice is sent only after the owner has seen exactly what will go and to whom, and ticked
    a confirmation; the server then sends ONLY to the recipients stored in that confirmation
  - nothing may be sent while the notice still has blanks or unverified legal references
  - an accountant is emailed (CC or statement) only after THEY confirmed by link; they can stop any time
  - every message is logged; Resend's signed delivery webhook (Svix) updates that log, and permanent bounces
    and spam complaints suppress the address
"""

import base64
import json
import logging
import os
import re
import uuid
from datetime import timedelta
from html import escape
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from lib import svix
from lib.auth import audit, current_user, now, require_verified_sender
from lib.branding import email_logo_header, get_branding
from lib.db import db
from lib.notice_checks import blockers_for
from lib.notice_workflow import current_version, sendable, set_state
from lib.translation import LANGUAGES
from lib.outbound import (
    CONSENT_DAYS,
    EmailSuppressed,
    is_suppressed,
    link_html,
    make_link_token,
    norm,
    read_link_token,
    send_logged,
    sha256,
    simple_email,
    suppress,
)
from lib.ratelimit import EMAIL_LIMIT, ip_limit, user_limit
from lib.recovery_mode import require_enabled, require_full_flow
from models.schemas import RecoveryCase
from routers.recovery_translation import courtesy_line, usable_translation
from routers.recovery import _build_notice_pdf, _get_case, _notice_html, blocker_message, confirmed_cc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recovery", tags=["recovery-mail"])
public = APIRouter(tags=["public"])

CONFIRMATION_MINUTES = 15
MAX_ACCOUNTANTS = 10


def _enclosure_note(notice: str) -> str:
    """The notice names its enclosures, but only the notice itself is attached to the email. Say so in the email instead of letting it read as if the documents came too."""
    if re.search(r"^Enclosures\s*\n\s+1\.", notice, re.M):
        return " The documents listed under Enclosures are not attached to this email."
    return ""


def _subject(case: dict) -> str:
    return f"Demand notice regarding payment owed to {case['creditor_name']}"


# ---------------------------------------------------------------------------------------------
# Demand notice: prepare (preview) -> confirm (send)
# ---------------------------------------------------------------------------------------------
class PrepareIn(BaseModel):
    debtor_email: EmailStr
    cc_accountants: bool = False
    translation_id: str | None = None  # an APPROVED courtesy translation to include under the English notice
    subject: str | None = Field(default=None, max_length=150)  # the sender's own subject line; the standard one is used when empty
    cover_message: str | None = Field(default=None, max_length=600)  # a short note shown above the standard sentence in the email


def _checked_words(text: str, what: str) -> str:
    """A subject or cover note goes to the other party, so it must obey the notice rules: one line for a subject, no blanks, no legal references,
    no threats or accusations, no claim that the notice was served."""
    from lib.notice_checks import PLACEHOLDER_RE, RISKY_OTHER, RISKY_RE, SERVICE_RE, _LEGAL_REF_PATTERNS

    text = (text or "").strip()
    if what == "subject" and re.search(r"[\r\n]", text):
        raise HTTPException(status_code=422, detail="The subject must be one line.")
    if PLACEHOLDER_RE.search(text):
        raise HTTPException(status_code=422, detail=f"The {what} still has a blank such as [name] to fill in.")
    if any(p.search(text) for p in _LEGAL_REF_PATTERNS):
        raise HTTPException(status_code=422, detail=f"Take the legal reference out of the {what}. VIDHI does not put law in what it sends.")
    if RISKY_RE.search(text) or any(w in text for w in RISKY_OTHER):
        raise HTTPException(status_code=422, detail=f"The {what} has wording that threatens or accuses. Keep it to the facts of the unpaid invoice.")
    if SERVICE_RE.search(text):
        raise HTTPException(status_code=422, detail=f"The {what} says the notice was served or received. Only a delivery record can say that.")
    return text


@router.post("/cases/{case_id}/email/prepare", dependencies=[Depends(require_full_flow), Depends(user_limit("email-prepare", 60, 3600))])
async def prepare_notice_email(case_id: str, body: PrepareIn, user: dict = Depends(require_verified_sender)):
    """Show exactly what would be sent and to whom. Nothing is emailed by this call."""
    case = await _get_case(case_id, user)
    if not case.get("notice_body"):
        raise HTTPException(status_code=409, detail="Create the demand notice first.")
    check = blockers_for(case)
    if check["blocked"]:
        raise HTTPException(status_code=409, detail=blocker_message(check))
    ok, why = sendable(case, case["notice_body"])
    if not ok:
        raise HTTPException(status_code=409, detail=why)
    to = norm(str(body.debtor_email))
    if await is_suppressed(to):
        raise HTTPException(
            status_code=409,
            detail="That address cannot receive email from VIDHI (it bounced or asked not to be contacted). "
            "Send the notice by post or another route.",
        )
    cc: list[str] = []
    if body.cc_accountants:
        for e in confirmed_cc(case):
            if norm(e) not in (to, norm(user["email"])) and not await is_suppressed(e):
                cc.append(norm(e))
    translation = None
    if body.translation_id:
        translation = await usable_translation(case, body.translation_id, user["organization_id"])
    subject = _checked_words(body.subject, "subject") if body.subject and body.subject.strip() else _subject(case)
    cover = _checked_words(body.cover_message, "cover message") if body.cover_message and body.cover_message.strip() else ""
    conf_id = str(uuid.uuid4())
    await db.email_confirmations.insert_one(
        {
            "subject": subject,
            "cover": cover,
            "translation_id": translation["id"] if translation else None,
            "translation_sha": translation["sha"] if translation else None,
            "id": conf_id,
            "case_id": case_id,
            "user_id": user["id"],
            "organization_id": user["organization_id"],
            "to": to,
            "cc": cc,
            "notice_sha": sha256(case["notice_body"]),
            "used": False,
            "created_at": now(),
            "expires_at": now() + timedelta(minutes=CONFIRMATION_MINUTES),
        }
    )
    return {
        "confirmation_id": conf_id,
        "to": to,
        "cc": cc,
        "sender_copy_to": norm(user["email"]),
        "subject": subject,
        "cover_message": cover,
        "notice_text": case["notice_body"],
        "translation": (
            {"language": translation["language"], "language_name": LANGUAGES[translation["language"]], "text": translation["body"]}
            if translation else None
        ),
        "attachment_name": f"demand-notice-{case_id[:8]}.pdf",
        "expires_in_minutes": CONFIRMATION_MINUTES,
    }


class SendIn(BaseModel):
    confirmation_id: str = Field(min_length=10, max_length=64)
    acknowledged: bool = False


@router.post("/cases/{case_id}/email", dependencies=[Depends(require_full_flow), Depends(EMAIL_LIMIT)])
async def email_notice(case_id: str, body: SendIn, user: dict = Depends(require_verified_sender)):
    """Send the notice to the recipients the owner confirmed in the preview - and only those."""
    if not body.acknowledged:
        raise HTTPException(
            status_code=422,
            detail="Please tick the box to confirm the recipient is right and you have read the notice.",
        )
    case = await _get_case(case_id, user)
    # Consume the confirmation atomically so one preview can never send twice.
    conf = await db.email_confirmations.find_one_and_update(
        {
            "id": body.confirmation_id,
            "case_id": case_id,
            "user_id": user["id"],
            "used": False,
            "expires_at": {"$gt": now()},
        },
        {"$set": {"used": True, "used_at": now()}},
    )
    if not conf:
        raise HTTPException(
            status_code=409, detail="That confirmation has expired or was already used. Please review and confirm again."
        )
    notice = case.get("notice_body") or ""
    if sha256(notice) != conf["notice_sha"]:
        raise HTTPException(status_code=409, detail="The notice changed after you reviewed it. Please review it again.")
    check = blockers_for(case, notice)
    if check["blocked"]:
        raise HTTPException(status_code=409, detail=blocker_message(check))
    ok, why = sendable(case, notice)
    if not ok:
        raise HTTPException(status_code=409, detail=why)

    translation = None
    if conf.get("translation_id"):
        translation = await usable_translation(case, conf["translation_id"], user["organization_id"])
        if translation["sha"] != conf.get("translation_sha"):
            raise HTTPException(status_code=409, detail="The translation changed after you reviewed it. Please review it again.")
    tr_block = (courtesy_line(translation["language"]), translation["body"]) if translation else None

    recipient = conf["to"]
    await db.recovery_cases.update_one(
        {"id": case_id},
        {"$set": {"debtor_email": recipient, "debtor_email_status": "ACCEPTED", "updated_at": now()}},
    )
    subject = conf.get("subject") or _subject(case)
    cover = conf.get("cover") or ""
    branding = await get_branding(user["organization_id"])
    header = await email_logo_header(user["organization_id"])
    attach = [
        {
            "filename": f"demand-notice-{case_id[:8]}.pdf",
            "content": base64.b64encode(_build_notice_pdf(notice, branding)).decode(),
        }
    ]
    try:
        notice_log_id = await send_logged(
            to=recipient,
            subject=subject,
            html=_notice_html(
                (f"{escape(cover)} " if cover else "")
                + f"Dear {escape(case['debtor_name'])}, please find below a formal demand notice "
                f"from {escape(case['creditor_name'])}. A PDF copy is attached."
                + _enclosure_note(notice)
                + (" A translation is included below the English notice." if tr_block else ""),
                notice,
                header,
                tr_block,
            ),
            kind="notice-debtor",
            user=user,
            case_id=case_id,
            attachments=attach,
        )
    except EmailSuppressed as exc:
        raise HTTPException(status_code=409, detail="That address can no longer receive email from VIDHI.") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("notice email failed")
        await audit(user, "RECOVERY_NOTICE_EMAIL", result="FAILED", detail=case_id)
        await db.recovery_cases.update_one({"id": case_id}, {"$set": {"debtor_email_status": "FAILED"}})
        raise HTTPException(
            status_code=502, detail="We could not email the notice. Check the address and try again."
        ) from exc

    try:  # the sender's own copy must never fail the main send
        await send_logged(
            to=user["email"],
            subject=f"Copy: {subject}",
            html=_notice_html(
                f"We have emailed your demand notice to {escape(recipient)}. Here is a copy for your records (PDF attached)."
                + _enclosure_note(notice).replace("this email", "the email sent to them; send them separately if you want them to have copies"),
                notice,
                header,
            ),
            kind="notice-copy",
            user=user,
            case_id=case_id,
            attachments=attach,
            respect_suppression=False,
        )
    except Exception:  # noqa: BLE001
        logger.warning("sender copy failed", exc_info=True)

    cc_sent: list[str] = []
    cc_failed: list[str] = []
    confirmed_now = {norm(e) for e in confirmed_cc(case)}  # re-check: consent may have been withdrawn
    for a in conf["cc"]:
        if norm(a) not in confirmed_now:
            continue
        try:
            await send_logged(
                to=a,
                subject=f"Copy: {subject}",
                html=_notice_html(
                    f"Copy for your records: a demand notice was sent to {escape(case['debtor_name'])} on behalf of "
                    f"{escape(case['creditor_name'])}. A PDF copy is attached.",
                    notice,
                    header,
                ),
                kind="notice-cc",
                user=user,
                case_id=case_id,
                attachments=attach,
            )
            cc_sent.append(a)
        except Exception:  # noqa: BLE001
            cc_failed.append(a)
    ver = await current_version(case)
    await db.email_log.update_one({"id": notice_log_id}, {"$set": {"notice_version": ver["number"] if ver else None, "notice_sha": sha256(notice)}})
    await set_state(
        case_id, "SENT", user, f"Emailed to {recipient} (accepted by the email provider; delivery not confirmed)", "",
        sent={"at": now(), "to": recipient, "version": ver["number"] if ver else None, "sha": sha256(notice), "cc": cc_sent},
    )
    await audit(user, "RECOVERY_NOTICE_EMAIL", detail=f"{case_id} -> {recipient} cc={cc_sent} failed={cc_failed}")
    return {"ok": True, "sent_to": recipient, "cc_sent": cc_sent, "cc_failed": cc_failed, "status": "ACCEPTED"}


@router.get("/cases/{case_id}/emails")
async def case_email_log(case_id: str, user: dict = Depends(current_user)):
    """What was sent for this case and what we know about delivery. ACCEPTED is not proof of delivery."""
    await _get_case(case_id, user)
    rows = await db.email_log.find({"case_id": case_id, "organization_id": user["organization_id"]}).sort("created_at", -1).to_list(50)
    return [
        {"id": r["id"], "kind": r["kind"], "to": r["to"], "status": r["status"], "reason": r.get("reason"), "created_at": r["created_at"]}
        for r in rows
        if r["kind"] != "verify-email"
    ]


# ---------------------------------------------------------------------------------------------
# Accountants: nobody is copied until they confirm
# ---------------------------------------------------------------------------------------------
class AccountantsIn(BaseModel):
    emails: list[EmailStr] = Field(default_factory=list, max_length=MAX_ACCOUNTANTS)


async def _request_consent(user: dict, case: dict, email: str) -> None:
    app = os.environ.get("APP_URL", "").rstrip("/")
    token = make_link_token({"c": case["id"], "e": norm(email), "t": int(now().timestamp())})
    url = f"{app}/consent/{token}"
    html = simple_email(
        [
            f"{escape(user.get('full_name') or 'Someone')} ({escape(user['email'])}) has asked to copy you on "
            f"balance statements AND on any demand notice they send about money owed to {escape(case['creditor_name'])}, sent through VIDHI. "
            "A notice names the customer and sets out the claim; you can stop the copies at any time with the link in each email.",
            "You will receive nothing unless you agree. Please choose:",
            link_html(url, "Review this request"),
            f"This request expires in {CONSENT_DAYS} days. If you do not know this person, just ignore this message.",
        ]
    )
    await send_logged(
        to=email, subject="Please confirm: copy on payment statements", html=html, kind="consent-request", user=user, case_id=case["id"]
    )


@router.put("/cases/{case_id}/accountants", response_model=RecoveryCase, dependencies=[Depends(EMAIL_LIMIT)])
async def set_accountants(case_id: str, body: AccountantsIn, user: dict = Depends(require_verified_sender)):
    """Replace the accountant list. New addresses get a confirmation request and stay PENDING until they agree."""
    case = await _get_case(case_id, user)
    existing = {norm(a["email"]): a for a in case.get("accountants", [])}
    contacts, to_ask = [], []
    for raw in dict.fromkeys(norm(str(e)) for e in body.emails):
        if raw in existing:
            contacts.append(existing[raw])
            continue
        suppressed = await is_suppressed(raw)
        contacts.append({"email": raw, "status": "BOUNCED" if suppressed else "PENDING", "requested_at": now(), "responded_at": None})
        if not suppressed:
            to_ask.append(raw)
    # A person who declined stays on record (blocked) even if the owner removes them, so they
    # cannot be asked again by simply re-adding the address.
    kept = {c["email"] for c in contacts}
    contacts += [a for e, a in existing.items() if a["status"] == "DECLINED" and e not in kept]
    await db.recovery_cases.update_one(
        {"id": case_id},
        {"$set": {"accountants": contacts, "accountant_emails": [c["email"] for c in contacts if c["status"] == "CONFIRMED"], "updated_at": now()}},
    )
    case = await _get_case(case_id, user)
    for e in to_ask:
        try:
            await _request_consent(user, case, e)
        except Exception:  # noqa: BLE001
            logger.warning("consent request failed", exc_info=True)  # no email address in the log
    await audit(user, "RECOVERY_ACCOUNTANTS", detail=f"{case_id} asked={len(to_ask)} total={len(contacts)}")
    return RecoveryCase(**await _get_case(case_id, user))


class ResendIn(BaseModel):
    email: EmailStr


@router.post("/cases/{case_id}/accountants/resend", dependencies=[Depends(EMAIL_LIMIT)])
async def resend_consent(case_id: str, body: ResendIn, user: dict = Depends(require_verified_sender)):
    case = await _get_case(case_id, user)
    email = norm(str(body.email))
    contact = next((a for a in case.get("accountants", []) if norm(a["email"]) == email), None)
    if not contact or contact["status"] != "PENDING":
        raise HTTPException(status_code=409, detail="Only a pending request can be sent again.")
    try:
        await _request_consent(user, case, email)
    except EmailSuppressed as exc:
        raise HTTPException(status_code=409, detail="That address can no longer receive email from VIDHI.") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("resend consent failed")
        raise HTTPException(status_code=502, detail="We could not send the request right now. Please try again.") from exc
    await audit(user, "RECOVERY_ACCOUNTANT_REQUEST_RESENT", detail=case_id)
    return {"ok": True}


# ---------------------------------------------------------------------------------------------
# Public pages (no login): the accountant's confirm / decline / stop links
# ---------------------------------------------------------------------------------------------
def _read_consent(token: str) -> dict:
    data = read_link_token(token)
    if not data or not all(k in data for k in ("c", "e", "t")):
        raise HTTPException(status_code=404, detail="This link is not valid.")
    return data


@public.get("/public/consent/{token}", dependencies=[Depends(require_enabled), Depends(ip_limit("consent-view", 60, 60))])
async def consent_info(token: str):
    data = _read_consent(token)
    case = await db.recovery_cases.find_one({"id": data["c"]})
    contact = next((a for a in (case or {}).get("accountants", []) if norm(a["email"]) == data["e"]), None)
    if not case or not contact:
        raise HTTPException(status_code=404, detail="This request is no longer active.")
    owner = await db.users.find_one({"id": case.get("created_by")}) or {}
    age_days = (now().timestamp() - data["t"]) / 86400
    return {
        "email": data["e"],
        "status": contact["status"],
        "owner_name": owner.get("full_name", ""),
        "owner_email": owner.get("email", ""),
        "creditor_name": case["creditor_name"],
        "can_confirm": contact["status"] == "PENDING" and age_days <= CONSENT_DAYS,
        "expired": contact["status"] == "PENDING" and age_days > CONSENT_DAYS,
    }


class ConsentAction(BaseModel):
    action: Literal["confirm", "decline"]


@public.post("/public/consent/{token}", dependencies=[Depends(require_enabled), Depends(ip_limit("consent-act", 30, 60))])
async def consent_act(token: str, body: ConsentAction):
    data = _read_consent(token)
    case = await db.recovery_cases.find_one({"id": data["c"]})
    contact = next((a for a in (case or {}).get("accountants", []) if norm(a["email"]) == data["e"]), None)
    if not case or not contact:
        raise HTTPException(status_code=404, detail="This request is no longer active.")
    if body.action == "confirm":
        if (now().timestamp() - data["t"]) / 86400 > CONSENT_DAYS:
            raise HTTPException(status_code=410, detail="This request has expired. Ask the sender to send it again.")
        if contact["status"] == "DECLINED":
            raise HTTPException(status_code=409, detail="You already declined this request.")
        new_status = "CONFIRMED"
    else:
        new_status = "DECLINED"  # stopping is always allowed, at any time, with no expiry
    await db.recovery_cases.update_one(
        {"id": case["id"], "accountants.email": contact["email"]},
        {"$set": {"accountants.$.status": new_status, "accountants.$.responded_at": now(), "updated_at": now()}},
    )
    refreshed = await db.recovery_cases.find_one({"id": case["id"]})
    await db.recovery_cases.update_one(
        {"id": case["id"]}, {"$set": {"accountant_emails": confirmed_cc(refreshed)}}
    )
    return {"ok": True, "status": new_status}


# ---------------------------------------------------------------------------------------------
# Provider delivery events (wired to the real provider in the migration phase)
# ---------------------------------------------------------------------------------------------
_EVENT_STATUS = {"email.delivered": "DELIVERED", "email.bounced": "BOUNCED", "email.complained": "COMPLAINED"}


async def apply_delivery_event(provider_id: str, status: str, reason: str | None, suppress_address: bool = True) -> bool:
    """Record what the provider told us about a message. Returns False if we never sent that message."""
    log = await db.email_log.find_one({"provider_id": provider_id})
    if not log:
        return False
    await db.email_log.update_one(
        {"id": log["id"]},
        {"$set": {"status": status, "reason": reason, "updated_at": now()}, "$push": {"events": {"type": status, "at": now(), "reason": reason}}},
    )
    if log.get("case_id") and log["kind"] == "notice-debtor":
        from lib.notice_workflow import _event
        from lib.phone_alerts import notify_user

        case_owner = await db.recovery_cases.find_one({"id": log["case_id"]}, {"created_by": 1})
        if case_owner and status in ("DELIVERED", "BOUNCED", "COMPLAINED"):  # no names or amounts in an SMS
            await notify_user(case_owner.get("created_by", ""), "There is an update on the delivery of a notice. Open the app to see it.")

        text = {
            "DELIVERED": "the provider reports it was delivered to the recipient's mail server (this does not show it was read)",
            "BOUNCED": "it bounced and did not reach the customer",
            "COMPLAINED": "the recipient marked it as spam",
        }.get(status, status.lower())
        await _event(log["case_id"], f"Email to {log['to']}: {text}", None)
    if status in ("BOUNCED", "COMPLAINED"):
        if suppress_address:  # a permanent bounce or a spam complaint: never email this address again
            await suppress(log["to"], f"{status.lower()}: {reason or ''}".strip())
        if log.get("case_id"):
            if log["kind"] == "notice-debtor":
                await db.recovery_cases.update_one({"id": log["case_id"]}, {"$set": {"debtor_email_status": status}})
            elif log["kind"] in ("notice-cc", "statement-cc", "consent-request"):
                await db.recovery_cases.update_one(
                    {"id": log["case_id"], "accountants.email": log["to"]},
                    {"$set": {"accountants.$.status": "BOUNCED", "accountants.$.responded_at": now()}},
                )
                case = await db.recovery_cases.find_one({"id": log["case_id"]})
                if case:
                    await db.recovery_cases.update_one({"id": case["id"]}, {"$set": {"accountant_emails": confirmed_cc(case)}})
    elif log.get("case_id") and log["kind"] == "notice-debtor":
        await db.recovery_cases.update_one({"id": log["case_id"]}, {"$set": {"debtor_email_status": status}})
    return True


_SENDGRID_STATUS = {"delivered": "DELIVERED", "bounce": "BOUNCED", "dropped": "BOUNCED", "spamreport": "COMPLAINED"}


def _sendgrid_authentic(headers, body: bytes) -> bool:
    """SendGrid signs timestamp + raw body with ECDSA (P-256, SHA-256); SENDGRID_WEBHOOK_PUBLIC_KEY is the base64 public key."""
    import base64
    import time

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key_b64 = os.environ.get("SENDGRID_WEBHOOK_PUBLIC_KEY", "")
    sig, ts = headers.get("X-Twilio-Email-Event-Webhook-Signature"), headers.get("X-Twilio-Email-Event-Webhook-Timestamp")
    if not key_b64 or not sig or not ts:
        return False
    try:
        if abs(time.time() - int(ts)) > 600:  # a captured request cannot be replayed later
            return False
        pub = serialization.load_der_public_key(base64.b64decode(key_b64))
        pub.verify(base64.b64decode(sig), ts.encode() + body, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


@public.post("/webhooks/sendgrid", dependencies=[Depends(ip_limit("email-webhook", 600, 60))])
async def sendgrid_webhook(request: Request):
    """SendGrid -> us (Event Webhook). Authenticity is proven by its ECDSA signature over the raw body."""
    body = await request.body()
    if not _sendgrid_authentic(request.headers, body):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        events = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad payload") from None
    unknown = 0
    for ev in events if isinstance(events, list) else []:
        status = _SENDGRID_STATUS.get(str(ev.get("event")))
        mid = str(ev.get("sg_message_id") or "").split(".")[0]  # the id we stored is the part before the first dot
        if not status or not mid:
            continue
        soft = str(ev.get("type", "")).lower() == "blocked"  # temporary trouble: report, do not blacklist
        if not await apply_delivery_event(mid, status, ev.get("reason"), suppress_address=not soft):
            unknown += 1
    return {"ok": True, "unknown_messages": unknown}


@public.post("/webhooks/resend", dependencies=[Depends(ip_limit("email-webhook", 600, 60))])
async def resend_webhook(request: Request):
    """Resend -> us. Authenticity is proven by the Svix signature over the raw body (RESEND_WEBHOOK_SECRET)."""
    secret = os.environ.get("RESEND_WEBHOOK_SECRET", "")
    body = await request.body()
    if not secret or not svix.verify(secret, request.headers, body):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad payload") from None
    status = _EVENT_STATUS.get(str(event.get("type")))
    data = event.get("data") or {}
    if not status or not data.get("email_id"):
        return {"ok": True, "ignored": True}  # sent/opened/clicked/etc: nothing to record
    bounce = data.get("bounce") or {}
    transient = str(bounce.get("type", "")).lower() == "transient"  # temporary trouble: report, don't blacklist
    known = await apply_delivery_event(str(data["email_id"]), status, bounce.get("message"), suppress_address=not transient)
    return {"ok": True, "unknown_message": not known}