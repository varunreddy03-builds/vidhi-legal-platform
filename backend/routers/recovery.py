import asyncio
import base64
import hashlib
import io
import logging
import math
import os
import re
import uuid
from datetime import date, datetime, timedelta
from typing import Literal
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, EmailStr, Field

from lib.ai import RECOVERY_PROMPT, ai_failure, ask_json, log_ai_failure, read_image_text
from lib.auth import audit, current_user, now, require_verified_sender
from lib.balance import fmt_money, interest_principal, position
from lib.evidence_check import PROOF_KINDS
from lib.branding import email_logo_header, get_branding, logo_flowable
from lib.dates import today_iso
from lib import filestore
from lib import recovery_mode
from lib.db import db
from lib.purge import purge_case
from lib.email import send_email
from lib.extract import extract_pages
from lib.interest import compute_simple_interest
from lib.limitation import assess as assess_limitation
from lib.notice_checks import blockers_for
from lib.outbound import EmailSuppressed, link_html, make_link_token, norm, send_logged
from lib.ratelimit import AI_LIMIT, EMAIL_LIMIT, UPLOAD_LIMIT, hit
from lib import ocr
from lib.safety import fence
from lib.uploads import read_limited, safe_filename, validate_content
from routers.cron import _aware, reminder_email
from models.schemas import (
    Matter,
    RecoveryCase,
    RecoveryCaseCreate,
    RecoveryProof,
    RecoveryTimelineItem,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recovery", tags=["recovery"])

MAX_BYTES = 15 * 1024 * 1024
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
ALLOWED = (".pdf", ".docx", ".txt", ".md") + IMAGE_EXT

_OCR_PROMPT = (
    "This is a photo or screenshot someone is using as proof they are owed money — it may be a "
    "WhatsApp or SMS chat, an invoice, a receipt or an agreement. Read ALL the text you can see "
    "and type it out plainly, in order. Keep names, amounts, dates and any promise to pay exactly "
    "as shown. Do NOT add anything that is not visible in the image."
)

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


async def _get_case(case_id: str, user: dict) -> dict:
    doc = await db.recovery_cases.find_one(
        {"id": case_id, "organization_id": user["organization_id"]}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    return doc


def _principal(case: dict) -> float:
    """What interest (if asked for) is counted on: the amount the OWNER entered, less credits (never charges)."""
    return interest_principal(case)


def _today():
    from datetime import date

    return date.fromisoformat(today_iso(os.environ.get("APP_TZ", "Asia/Kolkata")))


def _fmt_date(iso: str) -> str:
    from datetime import date

    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d.strftime('%b %Y')}"


def confirmed_cc(case: dict) -> list[str]:
    """Accountants who confirmed by link. Legacy/unconfirmed addresses are never emailed."""
    return [a["email"] for a in case.get("accountants", []) if a.get("status") == "CONFIRMED"]


def _interest_now(case: dict, as_of) -> dict | None:
    """Interest to date, only if the owner entered BOTH a due date and a rate; never defaults either."""
    if not case.get("due_date") or case.get("interest_rate_pct") is None:
        return None
    return compute_simple_interest(
        _principal(case),
        [(p["date"], p["amount"]) for p in case.get("payments", [])],
        case["due_date"],
        case["interest_rate_pct"],
        as_of,
    )


def blocker_message(check: dict) -> str:
    parts = []
    if check.get("placeholders"):
        parts.append("fill in the blanks (" + ", ".join(check["placeholders"][:6]) + ")")
    if check.get("legal_references"):
        parts.append(
            "remove these legal references or have a lawyer verify them ("
            + ", ".join(check["legal_references"][:4])
            + ")"
        )
    if check.get("risky_language"):
        parts.append(
            "take out words that threaten or accuse (" + ", ".join(check["risky_language"][:5]) + "): an unpaid invoice is a "
            "civil matter and a notice must stay factual"
        )
    if check.get("amount_mismatches"):
        parts.append("remove or correct these amounts, which do not match the statement of account VIDHI calculated (" + ", ".join(check["amount_mismatches"][:5]) + ")")
    if check.get("service_claims"):
        parts.append("take out wording that says the notice has been served or received (" + ", ".join(check["service_claims"][:3]) + "): only a delivery record can show that")
    if check.get("statement_changed"):
        parts.append("restore the statement of account, which must stay exactly as VIDHI wrote it (draft the notice again to get a fresh one)")
    if check.get("figures_changed"):
        parts.append("draft the notice again: the figures on the case have changed since it was written (a payment, credit or charge), so it would demand a sum that is no longer owed")
    if not parts:
        parts.append("fix the problems shown on the notice")
    return "Before you can download or send this notice, " + " and ".join(parts) + "."


@router.get("/options")
async def recovery_options(user: dict = Depends(current_user)):
    """Which parts of Legal Recovery this installation shows (lib/recovery_mode.py). Off by default: the small free helper."""
    return {"full_flow": recovery_mode.full_flow()}


@router.get("/cases", response_model=list[RecoveryCase])
async def list_cases(user: dict = Depends(current_user)):
    docs = (
        await db.recovery_cases.find({"organization_id": user["organization_id"]})
        .sort("created_at", -1)
        .to_list(500)
    )
    return [RecoveryCase(**d) for d in docs]


@router.post("/cases", response_model=RecoveryCase)
async def create_case(body: RecoveryCaseCreate, user: dict = Depends(current_user)):
    case = RecoveryCase(
        organization_id=user["organization_id"], created_by=user["id"], **body.model_dump()
    )
    await db.recovery_cases.insert_one(case.model_dump())
    await audit(user, "RECOVERY_CASE_CREATE", detail=f"{case.id}: {case.creditor_name} vs {case.debtor_name}")
    return case


@router.get("/cases/{case_id}", response_model=RecoveryCase)
async def read_case(case_id: str, user: dict = Depends(current_user)):
    return RecoveryCase(**await _get_case(case_id, user))


@router.delete("/cases/{case_id}")
async def delete_case(case_id: str, user: dict = Depends(current_user)):
    case = await _get_case(case_id, user)
    await purge_case(case_id)
    await audit(user, "RECOVERY_CASE_DELETE", detail=case_id)
    # A matter opened by the lawyer handoff is a separate working copy (a lawyer may already have worked in it), so it is never deleted along with the case: say so.
    return {"ok": True, "linked_matter_kept": case.get("linked_matter_id") or None}


@router.get("/cases/{case_id}/proofs", response_model=list[RecoveryProof])
async def list_proofs(case_id: str, user: dict = Depends(current_user)):
    await _get_case(case_id, user)
    docs = await db.recovery_proofs.find({"case_id": case_id}).sort("created_at", -1).to_list(100)
    return [RecoveryProof(**d) for d in docs]


@router.post(
    "/cases/{case_id}/proofs", response_model=RecoveryProof, dependencies=[Depends(UPLOAD_LIMIT)]
)
async def upload_proof(
    case_id: str, file: UploadFile = File(...), kind: str = Form("OTHER"), user: dict = Depends(current_user)
):
    await _get_case(case_id, user)
    if kind not in PROOF_KINDS:
        raise HTTPException(status_code=422, detail="Choose what kind of document this is.")
    filename = safe_filename(file.filename, "proof")
    data = await read_limited(file, MAX_BYTES, "Please keep files under 15 MB.")
    if not data:
        raise HTTPException(status_code=400, detail="That file was empty — try again.")
    validate_content(
        filename,
        data,
        ALLOWED,
        "Upload a PDF, Word (.docx), text file, or a photo/screenshot (PNG/JPG).",
    )
    checksum = hashlib.sha256(data).hexdigest()
    dup = await db.recovery_proofs.find_one({"case_id": case_id, "checksum": checksum})
    if dup:
        raise HTTPException(status_code=409, detail=f"This exact file is already on the case as '{dup['filename']}'. If your connection dropped while you were sending it, it arrived the first time: you do not need to send it again.")
    if filename.lower().endswith(IMAGE_EXT):
        await hit("ai", user["id"], 40, 3600)  # image proofs call the vision model

    lower = filename.lower()
    err: str | None = None
    if lower.endswith(IMAGE_EXT):
        # WhatsApp Proof — Claude Sonnet 5.5 vision reads text out of the screenshot/photo.
        b64 = base64.b64encode(data).decode()
        try:
            text = await read_image_text(
                f"recovery-ocr-{case_id}", b64, _OCR_PROMPT, _IMAGE_MIME[os.path.splitext(filename.lower())[1]]
            )
        except Exception:  # noqa: BLE001
            logger.exception("image OCR failed")
            text, err = "", "We could not read that image right now. Try again, or upload a clearer copy."
        pages = [text] if text.strip() else []
        if not pages and not err:
            err = "We could not find any readable text in that image."
    else:
        pages, err = await asyncio.to_thread(extract_pages, filename, data)
        if not pages and lower.endswith(".pdf") and (err or "").startswith("No extractable text"):
            await hit("ai", user["id"], 40, 3600)  # reading a scan calls the vision model
            from lib.aibudget import ensure_available

            await ensure_available(user)  # the spending caps and an owner's "AI off" switch apply to reading scans too
            try:
                pages, err = await ocr.ocr_pdf(f"recovery-scan-{case_id}", data), None
                if not any(p.strip() for p in pages):
                    pages, err = [], "We could not find any readable text in that scan. Try a clearer copy."
            except ValueError as exc:
                pages, err = [], str(exc)
            except Exception:  # noqa: BLE001
                logger.info("scanned proof could not be read", exc_info=True)
                pages, err = [], "We could not read that scan right now. Try again, or upload a clearer copy."
    excerpt = "\n\n".join(pages)[:12000]
    # The ORIGINAL file is kept (evidence must be preserved, not just a text excerpt of it).
    file_id = await filestore.put(filename, data, {"case_id": case_id, "organization_id": user["organization_id"]})
    proof = {
        "id": str(uuid.uuid4()),
        "case_id": case_id,
        "organization_id": user["organization_id"],
        "filename": filename,
        "document_type": filename.rsplit(".", 1)[-1].upper(),
        "kind": kind,
        "size_bytes": len(data),
        "page_count": len(pages),
        "processing_status": "READY" if pages else "FAILED",
        "failure_reason": err,
        "excerpt": excerpt,
        "checksum": checksum,
        "has_file": True,
        "gridfs_id": file_id,
        "created_at": now(),
    }
    await db.recovery_proofs.insert_one(dict(proof))
    if proof["processing_status"] == "READY":
        await advance_status(case_id, "PROOF_ADDED")
    await audit(user, "RECOVERY_PROOF_UPLOAD", detail=f"{case_id}: {filename} ({kind})")
    return RecoveryProof(**proof)


class ProofKindIn(BaseModel):
    kind: str


@router.patch("/cases/{case_id}/proofs/{proof_id}", response_model=RecoveryProof)
async def set_proof_kind(case_id: str, proof_id: str, body: ProofKindIn, user: dict = Depends(current_user)):
    """Say what an uploaded document is (invoice, delivery proof...). Only the owner's label; VIDHI does not judge the file."""
    await _get_case(case_id, user)
    if body.kind not in PROOF_KINDS:
        raise HTTPException(status_code=422, detail="Choose what kind of document this is.")
    res = await db.recovery_proofs.update_one({"id": proof_id, "case_id": case_id}, {"$set": {"kind": body.kind}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Document not found")
    await audit(user, "RECOVERY_PROOF_LABEL", detail=f"{case_id}: {proof_id} -> {body.kind}")
    return RecoveryProof(**await db.recovery_proofs.find_one({"id": proof_id}))


@router.get("/cases/{case_id}/proofs/{proof_id}/file")
async def download_proof(case_id: str, proof_id: str, user: dict = Depends(current_user)):
    """The original uploaded file, exactly as received, for this organisation only."""
    from urllib.parse import quote

    await _get_case(case_id, user)
    proof = await db.recovery_proofs.find_one({"id": proof_id, "case_id": case_id})
    if not proof or not proof.get("gridfs_id"):
        raise HTTPException(status_code=404, detail="The original file was not kept for this document.")
    data = await filestore.read(proof["gridfs_id"])
    ext = os.path.splitext(proof["filename"].lower())[1]
    mime = {**_IMAGE_MIME, ".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/plain"}.get(ext, "application/octet-stream")
    await audit(user, "RECOVERY_PROOF_DOWNLOAD", detail=f"{case_id}: {proof['filename']}")
    return Response(
        content=data, media_type=mime,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(proof['filename'])}"},
    )

EXTRACT_SCHEMA = (
    '{"summary": string, "detected_amount": number|null, "currency": string, '
    '"timeline": [{"date": string, "description": string, "amount": number|null}]}'
)


@router.post("/cases/{case_id}/extract", response_model=RecoveryCase, dependencies=[Depends(AI_LIMIT)])
async def extract_case(case_id: str, user: dict = Depends(current_user)):
    """Read the proof documents and extract an amount + a plain-language timeline."""
    case = await _get_case(case_id, user)
    proofs = await db.recovery_proofs.find(
        {"case_id": case_id, "processing_status": "READY"}
    ).to_list(20)
    evidence = "\n\n".join(f"[{p['filename']}]\n{p['excerpt']}" for p in proofs)[:18000]

    prompt = (
        f"A person says they are owed money. Creditor (owed): {case['creditor_name']}. "
        f"Debtor (owes): {case['debtor_name']}. They state the amount as "
        f"{case.get('amount') or 'unknown'} {case.get('currency', 'INR')}. "
        f"Their note: {fence(case.get('description') or '(none)', 'USER NOTE')}\n\n"
        + (f"PROOF DOCUMENTS:\n{fence(evidence, 'PROOF DOCUMENTS')}\n\n" if evidence else "No proof documents were uploaded.\n\n")
        + "Write a short, friendly plain-language summary of what is owed and why. There may be "
        "SEVERAL proof files (invoices, receipts, chat screenshots) — read ALL of them and MERGE "
        "everything into ONE clean, chronological timeline (invoice raised, part payment, "
        "reminders, due date), in date order, removing duplicate events. Use ONLY what appears in "
        "the note or the proof. If the proof shows an amount, report it as detected_amount; "
        "otherwise null. Never invent dates or amounts."
    )
    try:
        data = await ask_json(
            f"recovery-extract-{case_id}", prompt, EXTRACT_SCHEMA, system=RECOVERY_PROMPT
        )
    except Exception as exc:  # noqa: BLE001
        await audit(user, "RECOVERY_EXTRACT", result="FAILED", detail=case_id)
        log_ai_failure("recovery extract", exc)
        raise ai_failure(exc) from exc

    from lib.neutral import neutralize

    def finite(x) -> float | None:
        return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and 0 <= x <= 1_000_000_000_000 else None

    timeline: list[RecoveryTimelineItem] = []
    for t in data.get("timeline", []) if isinstance(data.get("timeline"), list) else []:
        if not isinstance(t, dict) or not (t.get("date") or t.get("description")):
            continue
        timeline.append(
            RecoveryTimelineItem(
                date=str(t.get("date", ""))[:40],
                description=neutralize(str(t.get("description", ""))[:300])[0],  # the AI's wording is held to the same neutral-wording rule as everything else
                amount=finite(t.get("amount")),
            )
        )
    code = str(data.get("currency") or "").strip().upper()
    patch = {
        "summary": neutralize(str(data.get("summary") or "")[:2000])[0],
        "detected_amount": finite(data.get("detected_amount")),
        "currency": code if re.fullmatch(r"[A-Z]{3}", code) else case.get("currency", "INR"),  # only a three-letter currency code is accepted from the AI
        "timeline": [t.model_dump() for t in timeline],
        "updated_at": now(),
    }
    await db.recovery_cases.update_one({"id": case_id}, {"$set": patch})
    await advance_status(case_id, "TIMELINE_READY")
    await audit(user, "RECOVERY_EXTRACT", detail=case_id)
    return RecoveryCase(**await _get_case(case_id, user))


NOTICE_SCHEMA = '{"notice": string}'


class CaseDetailsIn(BaseModel):
    creditor_address: str | None = Field(default=None, max_length=500)
    debtor_address: str | None = Field(default=None, max_length=500)
    due_date: str | None = Field(default=None, max_length=10)  # ISO date
    interest_rate_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    clear_due_date: bool = False
    clear_interest: bool = False


@router.patch("/cases/{case_id}/details", response_model=RecoveryCase)
async def set_case_details(case_id: str, body: CaseDetailsIn, user: dict = Depends(current_user)):
    """Addresses, due date and (optional) interest rate - everything a notice needs that we must not guess."""
    from datetime import date

    await _get_case(case_id, user)
    patch: dict = {"updated_at": now()}
    if body.creditor_address is not None:
        patch["creditor_address"] = body.creditor_address.strip()
    if body.debtor_address is not None:
        patch["debtor_address"] = body.debtor_address.strip()
    if body.clear_due_date:
        patch["due_date"] = None
    elif body.due_date:
        try:
            d = date.fromisoformat(body.due_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="That due date is not valid.") from exc
        if d.year < 1990 or d > _today() + timedelta(days=366):
            raise HTTPException(status_code=422, detail="That due date does not look right.")
        inv = ((await _get_case(case_id, user)).get("intake") or {}).get("invoice_date")
        if inv and d.isoformat() < str(inv)[:10]:
            raise HTTPException(status_code=422, detail="The due date cannot be before the invoice date.")
        patch["due_date"] = d.isoformat()
    if body.clear_interest:
        patch["interest_rate_pct"] = None
    elif body.interest_rate_pct is not None:
        patch["interest_rate_pct"] = body.interest_rate_pct
    await db.recovery_cases.update_one({"id": case_id}, {"$set": patch})
    await audit(user, "RECOVERY_DETAILS", detail=case_id)
    return RecoveryCase(**await _get_case(case_id, user))




class GuideAnswers(BaseModel):
    """The five eligibility answers. They only decide which route is shown first; they are never a legal opinion."""

    udyam: Literal["yes", "no", "not_sure"] | None = None
    buyer: Literal["business", "individual"] | None = None
    has_documents: bool | None = None
    overdue: Literal["under_15", "15_to_45", "over_45"] | None = None
    amount: float | None = Field(default=None, ge=0, le=1_000_000_000_000, allow_inf_nan=False)


_ISO_DAY = r"^(\d{4}-\d{2}-\d{2})?$"


class GuideTracker(BaseModel):
    """Three dates the person types for their own follow-up. VIDHI does not work them out and does not check them; an empty value clears a date."""

    notice_date: str | None = Field(default=None, pattern=_ISO_DAY)
    due_date: str | None = Field(default=None, pattern=_ISO_DAY)
    next_date: str | None = Field(default=None, pattern=_ISO_DAY)


class GuideIn(BaseModel):
    tracker: GuideTracker | None = None
    stage: Literal["NOT_STARTED", "PORTAL_FILED", "NOTICE_SENT", "ESCALATED"] | None = None
    answers: GuideAnswers | None = None
    delivery_method: Literal["downloaded", "emailed", "lawyer"] | None = None
    portal_reference: str | None = Field(default=None, max_length=60, pattern=r"^[A-Za-z0-9 /_.\-]*$")  # typed in by the person from their own portal filing; VIDHI cannot check it


@router.patch("/cases/{case_id}/guide", response_model=RecoveryCase)
async def set_guide(case_id: str, body: GuideIn, user: dict = Depends(current_user)):
    """Where the person is in the guided flow, so they can leave and come back. 'Notice sent by email' is accepted only when our own
    email log shows the provider accepted the notice; for 'downloaded' and 'lawyer' it is the person's own statement."""
    case = await _get_case(case_id, user)
    guide = dict(case.get("guide") or {})
    if body.answers is not None:
        guide["answers"] = {**(guide.get("answers") or {}), **body.answers.model_dump(exclude_none=True)}
    if body.portal_reference is not None:
        guide["portal_reference"] = body.portal_reference.strip()
    if body.tracker is not None:
        tracker = {**(guide.get("tracker") or {}), **body.tracker.model_dump(exclude_none=True)}
        for key, value in tracker.items():
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail="That is not a real date.") from exc
        guide["tracker"] = {k: v for k, v in tracker.items() if v}
    if body.delivery_method is not None:
        if body.delivery_method == "emailed":
            sent = await db.email_log.find_one(
                {"case_id": case_id, "organization_id": user["organization_id"], "kind": "notice-debtor", "status": {"$ne": "FAILED"}}
            )
            if not sent:
                raise HTTPException(status_code=409, detail="No notice email has been accepted for sending yet, so it cannot be marked as emailed.")
        guide["delivery_method"] = body.delivery_method
    if body.stage is not None:
        if body.stage == "NOTICE_SENT" and not guide.get("delivery_method"):
            raise HTTPException(status_code=422, detail="Say how the notice was delivered first.")
        guide["stage"] = body.stage
        guide["stage_changed_at"] = now().isoformat()
    guide.setdefault("stage", "NOT_STARTED")
    await db.recovery_cases.update_one({"id": case_id}, {"$set": {"guide": guide, "updated_at": now()}})
    await audit(user, "RECOVERY_GUIDE", detail=f"{case_id}: {guide['stage']}")
    return RecoveryCase(**await _get_case(case_id, user))


@router.get("/cases/{case_id}/interest")
async def case_interest(case_id: str, as_of: str | None = None, user: dict = Depends(current_user)):
    """Itemised simple-interest working. The rate is whatever the owner entered; we only do the arithmetic."""
    from datetime import date

    case = await _get_case(case_id, user)
    if not case.get("due_date"):
        raise HTTPException(status_code=422, detail="Add the date the money was due first.")
    if case.get("interest_rate_pct") is None:
        raise HTTPException(status_code=422, detail="Enter the interest rate you want to use first.")
    try:
        end = date.fromisoformat(as_of) if as_of else _today()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="That date is not valid.") from exc
    result = _interest_now(case, end)
    result["currency"] = case.get("currency", "INR")
    return result


@router.get("/cases/{case_id}/limitation")
async def case_limitation(case_id: str, user: dict = Depends(current_user)):
    """Age of the debt plus, only where a lawyer-verified rule exists, its deadline. Never invents a period."""
    case = await _get_case(case_id, user)
    return assess_limitation(case.get("due_date"), _today())


class NoticeEditIn(BaseModel):
    notice_body: str = Field(min_length=20, max_length=12000)


@router.patch("/cases/{case_id}/notice", response_model=RecoveryCase)
async def edit_notice(case_id: str, body: NoticeEditIn, user: dict = Depends(current_user)):
    """Let the owner fill in blanks / remove legal references in the drafted notice."""
    case = await _get_case(case_id, user)
    if not case.get("notice_body"):
        raise HTTPException(status_code=409, detail="Create the demand notice first.")
    from lib.notice_workflow import add_version, current_version, state_of

    if state_of(case) == "CLOSED":
        raise HTTPException(status_code=409, detail="This notice process is closed.")
    await current_version(case)  # make sure the text being replaced is itself preserved as a version
    text = body.notice_body.strip()
    await db.recovery_cases.update_one({"id": case_id}, {"$set": {"notice_body": text, "updated_at": now()}})
    await add_version(await _get_case(case_id, user), text, "EDIT", user)
    await audit(user, "RECOVERY_NOTICE_EDIT", detail=case_id)
    return RecoveryCase(**await _get_case(case_id, user))


def _letterhead(branding: dict | None) -> list:
    """Logo + firm name + address flowables for the top of a PDF letterhead."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Spacer

    branding = branding or {}
    flow: list = []
    logo = logo_flowable(branding.get("logo"))
    if logo is not None:
        flow += [logo, Spacer(1, 6)]
    name = (branding.get("firm_name") or "").strip()
    addr = (branding.get("firm_address") or "").strip()
    if name:
        flow.append(
            Paragraph(
                escape(name),
                ParagraphStyle("fname", fontName="Helvetica-Bold", fontSize=12, leading=15),
            )
        )
    if addr:
        astyle = ParagraphStyle("faddr", fontName="Helvetica", fontSize=9, leading=12)
        for ln in addr.split("\n"):
            if ln.strip():
                flow.append(Paragraph(escape(ln), astyle))
    if flow:
        flow.append(Spacer(1, 14))
    return flow


def _build_notice_pdf(text: str, branding: dict | None = None) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title="Demand Notice",
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=2.2 * cm,
        rightMargin=2.2 * cm,
    )
    style = ParagraphStyle("notice", fontName="Helvetica", fontSize=10.5, leading=15)
    flow: list = _letterhead(branding)
    for line in text.split("\n"):
        if line.strip() == "":
            flow.append(Spacer(1, 6))
        else:
            flow.append(Paragraph(escape(line), style))
    doc.build(flow)
    return buf.getvalue()


@router.get("/cases/{case_id}/notice.pdf")
async def notice_pdf(case_id: str, user: dict = Depends(current_user)):
    """Download the demand notice as a ready-to-send PDF."""
    case = await _get_case(case_id, user)
    if not case.get("notice_body"):
        raise HTTPException(status_code=409, detail="Create the demand notice first.")
    check = blockers_for(case)
    if check["blocked"]:
        raise HTTPException(status_code=409, detail=blocker_message(check))
    pdf = _build_notice_pdf(case["notice_body"], await get_branding(user["organization_id"]))
    await audit(user, "RECOVERY_NOTICE_PDF", detail=case_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="demand-notice-{case_id[:8]}.pdf"'},
    )


def _build_statement_pdf(case: dict, branding: dict | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    cur = case.get("currency", "INR")

    def money(n: float) -> str:
        # PDF base fonts have no rupee glyph (it printed as a black square), so the PDF spells it "Rs".
        return fmt_money(n, cur, "Rs") if cur == "INR" else fmt_money(n, cur)

    pos = position(case)
    owed, received, remaining = pos["owed"], pos["received"], pos["remaining"]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Recovery statement", topMargin=2 * cm, bottomMargin=2 * cm)
    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=16, leading=20)
    b = ParagraphStyle("b", fontName="Helvetica", fontSize=11, leading=17)
    flow: list = _letterhead(branding)
    flow += [
        Paragraph("Recovery statement", h),
        Spacer(1, 8),
        Paragraph(f"Creditor: {escape(case['creditor_name'])}", b),
        Paragraph(f"Debtor: {escape(case['debtor_name'])}", b),
        Spacer(1, 8),
        Paragraph(f"Amount owed: {money(owed)}", b),
        Paragraph(f"Total received: {money(received)}", b),
        Paragraph(f"Remaining balance: {money(remaining)}", b),
        Spacer(1, 14),
        Paragraph("Payments received", b),
        Spacer(1, 6),
    ]
    rows = [["Date", "Amount"]] + [
        [str(p.get("date", ""))[:10], money(float(p.get("amount", 0)))]
        for p in case.get("payments", [])
    ]
    if len(rows) == 1:
        rows.append(["—", "No payments recorded"])
    table = Table(rows, colWidths=[8 * cm, 6 * cm])
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.lightgrey),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    flow += [table, Spacer(1, 16), Paragraph("Generated by VIDHI Legal Recovery. Not legal advice.", b)]
    doc.build(flow)
    return buf.getvalue()


@router.get("/cases/{case_id}/statement.pdf")
async def statement_pdf(case_id: str, user: dict = Depends(current_user)):
    """One-page PDF statement of the balance and every recorded payment."""
    case = await _get_case(case_id, user)
    pdf = _build_statement_pdf(case, await get_branding(user["organization_id"]))
    await audit(user, "RECOVERY_STATEMENT_PDF", detail=case_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="statement-{case_id[:8]}.pdf"'},
    )


def cc_stop_footer(case: dict, email: str) -> str:
    """Footer for copies sent to an accountant: who asked, and a one-click way to stop."""
    app = os.environ.get("APP_URL", "").rstrip("/")
    token = make_link_token({"c": case["id"], "e": norm(email), "t": int(now().timestamp())})
    return (
        '<p style="font-size:12px;color:#666">You are receiving this copy because '
        f"{escape(case.get('creditor_name', ''))} asked VIDHI to copy you on statements and you agreed. "
        f"Stop receiving these: {link_html(f'{app}/consent/{token}', 'unsubscribe')}</p>"
    )


def statement_html(case: dict, header: str = "", footer: str = "") -> str:
    """Server-side email body for a balance statement (shared by the API + the cron)."""
    cur = case.get("currency", "INR")

    def money(n: float) -> str:
        return fmt_money(n, cur, "₹") if cur == "INR" else fmt_money(n, cur)

    pos = position(case)
    owed, received, remaining = pos["owed"], pos["received"], pos["remaining"]
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;'
        'font-family:Arial,sans-serif;max-width:560px">'
        f"{header}"
        f"<p>Balance statement for money owed by <strong>{escape(case.get('debtor_name', ''))}</strong> "
        f"to <strong>{escape(case.get('creditor_name', ''))}</strong>.</p>"
        '<div style="border:1px solid #ddd;border-radius:8px;padding:16px;font-size:13px;'
        'line-height:1.7;color:#222">'
        f"Amount owed: {escape(money(owed))}<br>"
        f"Total received: {escape(money(received))}<br>"
        f"<strong>Remaining balance: {escape(money(remaining))}</strong>"
        "</div>"
        "<p>A full PDF statement listing every recorded payment is attached.</p>"
        f"{footer}"
        '<p style="font-size:12px;color:#888">Sent by VIDHI Legal Recovery, a free self-help tool. '
        "This is information, not legal advice. We never ask for your password or card details by "
        "email.</p></td></tr></table>"
    )


class StatementEmailIn(BaseModel):
    email: EmailStr


@router.post("/cases/{case_id}/statement-email", dependencies=[Depends(EMAIL_LIMIT)])
async def email_statement(
    case_id: str, body: StatementEmailIn, user: dict = Depends(require_verified_sender)
):
    """Email the PDF balance statement to the owner or a CONFIRMED accountant - nobody else."""
    case = await _get_case(case_id, user)
    recipient = norm(str(body.email))
    allowed = {norm(user["email"]), *[norm(e) for e in confirmed_cc(case)]}
    if recipient not in allowed:
        raise HTTPException(
            status_code=403,
            detail="You can only email statements to yourself or to an accountant who has confirmed. "
            "Add them under 'Accountants' and ask them to confirm first.",
        )
    pos = position(case)
    owed, received, balance = pos["owed"], pos["received"], pos["remaining"]
    accountants = [e for e in confirmed_cc(case) if norm(e) != recipient]
    branding = await get_branding(user["organization_id"])
    header = await email_logo_header(user["organization_id"])
    subject = f"Balance statement — recovery against {case['debtor_name']}"
    attach = [
        {
            "filename": f"statement-{case_id[:8]}.pdf",
            "content": base64.b64encode(_build_statement_pdf(case, branding)).decode(),
        }
    ]
    # 1) Primary copy to the owner / typed recipient — this one MUST succeed.
    own = recipient == norm(user["email"])
    try:
        await send_logged(
            to=recipient,
            subject=subject,
            html=statement_html(case, header, "" if own else cc_stop_footer(case, recipient)),
            kind="statement-owner" if own else "statement-cc",
            user=user,
            case_id=case_id,
            attachments=attach,
        )
    except EmailSuppressed as exc:
        raise HTTPException(
            status_code=409, detail="That address can no longer receive email from VIDHI."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        await audit(user, "RECOVERY_STATEMENT_EMAIL", result="FAILED", detail=case_id)
        raise HTTPException(
            status_code=502,
            detail="We could not email the statement. Check the address and try again.",
        ) from exc
    # 2) Each CONFIRMED accountant gets their own copy, best-effort — one bounce never blocks the rest.
    cc_sent: list[str] = []
    cc_failed: list[str] = []
    for a in accountants:
        try:
            await send_logged(
                to=a,
                subject=subject,
                html=statement_html(case, header, cc_stop_footer(case, a)),
                kind="statement-cc",
                user=user,
                case_id=case_id,
                attachments=attach,
            )
            cc_sent.append(a)
        except Exception:  # noqa: BLE001
            cc_failed.append(a)
    await db.recovery_cases.update_one(
        {"id": case_id},
        {
            "$set": {"updated_at": now()},
            "$push": {
                "statement_log": {
                    "id": str(uuid.uuid4()),
                    "email": recipient,
                    "date": now(),
                    "via": "manual",
                    "owed": owed,
                    "received": received,
                    "balance": balance,
                    "cc": cc_sent,
                    "cc_failed": cc_failed,
                }
            },
        },
    )
    await audit(
        user,
        "RECOVERY_STATEMENT_EMAIL",
        detail=f"{case_id} -> {recipient} cc={cc_sent} failed={cc_failed}",
    )
    return {"ok": True, "sent_to": recipient, "cc_sent": cc_sent, "cc_failed": cc_failed}


def _compute_preview(case: dict) -> dict:
    """Server-anchored summary of a case's statement schedule/pause/CC + next send date."""
    import calendar

    remaining = position(case)["remaining"]
    schedule = case.get("statement_schedule", "MONTHLY")
    cc = [e for e in case.get("accountant_emails", []) if e]
    cc_txt = f" · CC {len(cc)} accountant{'s' if len(cc) != 1 else ''}" if cc else ""
    paused = case.get("statement_paused_until")
    today = now()
    next_date = None
    if remaining <= 0:
        summary = "No balance outstanding — no statement will be sent."
    elif schedule == "OFF":
        summary = "Automatic statements are off."
    elif paused and _aware(paused) > today:
        summary = f"Paused until {_aware(paused).strftime('%d %b %Y')}{cc_txt}"
    elif schedule == "MONTHLY":
        day = case.get("statement_day", 1)
        y, m = today.year, today.month
        if today.day <= min(day, calendar.monthrange(y, m)[1]):
            nd = today.replace(day=min(day, calendar.monthrange(y, m)[1]))
        else:
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
            nd = today.replace(year=y, month=m, day=min(day, calendar.monthrange(y, m)[1]))
        next_date = nd.date().isoformat()
        summary = f"Next statement on {nd.strftime('%d %b %Y')} · Monthly (day {day}){cc_txt}"
    else:  # FORTNIGHTLY
        last = case.get("last_statement_sent_at")
        nd = (_aware(last) + timedelta(days=14)) if last else today
        if nd < today:
            nd = today
        next_date = nd.date().isoformat()
        summary = f"Next statement on {nd.strftime('%d %b %Y')} · Every 14 days{cc_txt}"
    return {
        "case_id": case.get("id"),
        "summary": summary,
        "next_date": next_date,
        "schedule": schedule,
        "paused_until": (_aware(paused).isoformat() if paused else None),
        "cc": cc,
    }


@router.get("/statement-previews")
async def statement_previews(user: dict = Depends(current_user)):
    """Bulk statement preview per active case — powers the recoveries list."""
    docs = await db.recovery_cases.find(
        {"organization_id": user["organization_id"], "status": {"$ne": "RESOLVED"}}
    ).to_list(500)
    return [_compute_preview(d) for d in docs]


@router.get("/cases/{case_id}/statement-preview")
async def statement_preview(case_id: str, user: dict = Depends(current_user)):
    """Human-readable summary of the active statement schedule, pause and CC recipients."""
    return _compute_preview(await _get_case(case_id, user))


class RetryCcIn(BaseModel):
    log_id: str


@router.post("/cases/{case_id}/statement-retry-cc", dependencies=[Depends(EMAIL_LIMIT)])
async def retry_statement_cc(
    case_id: str, body: RetryCcIn, user: dict = Depends(require_verified_sender)
):
    """One-tap resend of a past statement to just the CONFIRMED accountants that failed."""
    case = await _get_case(case_id, user)
    entry = next((e for e in case.get("statement_log", []) if e.get("id") == body.log_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Statement record not found.")
    still_ok = {norm(e) for e in confirmed_cc(case)}
    failed = [e for e in entry.get("cc_failed", []) if e and norm(e) in still_ok]
    if not failed:
        raise HTTPException(status_code=409, detail="No bounced addresses to retry.")
    branding = await get_branding(user["organization_id"])
    header = await email_logo_header(user["organization_id"])
    subject = f"Balance statement — recovery against {case['debtor_name']}"
    attach = [
        {
            "filename": f"statement-{case_id[:8]}.pdf",
            "content": base64.b64encode(_build_statement_pdf(case, branding)).decode(),
        }
    ]
    now_sent: list[str] = []
    still_failed: list[str] = []
    for a in failed:
        try:
            await send_logged(
                to=a,
                subject=subject,
                html=statement_html(case, header, cc_stop_footer(case, a)),
                kind="statement-cc",
                user=user,
                case_id=case_id,
                attachments=attach,
            )
            now_sent.append(a)
        except Exception:  # noqa: BLE001
            still_failed.append(a)
    new_cc = list(dict.fromkeys(list(entry.get("cc", [])) + now_sent))
    await db.recovery_cases.update_one(
        {"id": case_id, "statement_log.id": body.log_id},
        {
            "$set": {
                "statement_log.$.cc": new_cc,
                "statement_log.$.cc_failed": still_failed,
                "updated_at": now(),
            }
        },
    )
    await audit(
        user,
        "RECOVERY_STATEMENT_RETRY_CC",
        detail=f"{case_id} {body.log_id} sent={now_sent} failed={still_failed}",
    )
    return {"ok": True, "cc_sent": now_sent, "cc_failed": still_failed}


class StatementScheduleIn(BaseModel):
    schedule: str | None = None  # OFF | MONTHLY | FORTNIGHTLY
    day: int | None = None
    pause_until: str | None = None  # ISO date — pause auto-statements until then
    resume: bool | None = None  # clear any pause
    accountant_emails: list[str] | None = None


@router.patch("/cases/{case_id}/statement-schedule", response_model=RecoveryCase)
async def set_statement_schedule(
    case_id: str, body: StatementScheduleIn, user: dict = Depends(current_user)
):
    """Owner control: cadence (monthly day 1–28 / fortnightly / off), pause window, accountant CCs."""
    await _get_case(case_id, user)
    patch: dict = {"updated_at": now()}
    if body.schedule in ("OFF", "MONTHLY", "FORTNIGHTLY"):
        patch["statement_schedule"] = body.schedule
    if body.day is not None:
        if not 1 <= body.day <= 28:
            raise HTTPException(status_code=400, detail="Pick a day between 1 and 28.")
        patch["statement_day"] = body.day
    if body.resume:
        patch["statement_paused_until"] = None
    elif body.pause_until:
        try:
            dt = datetime.fromisoformat(body.pause_until)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="That pause date is invalid.") from exc
        patch["statement_paused_until"] = dt
    # accountant_emails is accepted for old clients but ignored: accountants are added through
    # PUT /cases/{id}/accountants so each one has to confirm before they are ever emailed.
    await db.recovery_cases.update_one({"id": case_id}, {"$set": patch})
    await audit(
        user, "RECOVERY_STATEMENT_SCHEDULE", detail=f"{case_id} {body.model_dump(exclude_none=True)}"
    )
    return RecoveryCase(**await _get_case(case_id, user))


def _notice_html(intro: str, notice_body: str, header: str = "", translation: tuple[str, str] | None = None) -> str:
    """`translation` = (courtesy line, translated text): shown under the English notice, which stays the authoritative one."""
    lines = "<br>".join(escape(ln) for ln in notice_body.split("\n"))
    if translation:
        t_lines = "<br>".join(escape(ln) for ln in translation[1].split("\n"))
        lines += (
            f'</div><p style="font-size:12px;color:#555;margin-top:16px">{escape(translation[0])}</p>'
            f'<div style="border:1px solid #ddd;border-radius:8px;padding:16px;font-size:13px;line-height:1.5;color:#222">{t_lines}'
        )
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;'
        'font-family:Arial,sans-serif;max-width:620px">'
        f"{header}"
        f"<p>{intro}</p>"
        f'<div style="border:1px solid #ddd;border-radius:8px;padding:16px;font-size:13px;'
        f'line-height:1.5;color:#222">{lines}</div>'
        '<p style="font-size:12px;color:#888">Sent by VIDHI Legal Recovery, a free self-help tool. '
        "This is information, not legal advice. We never ask for your password or card details by "
        "email.</p></td></tr></table>"
    )


class RemindersIn(BaseModel):
    enabled: bool | None = None
    snooze_days: int | None = Field(default=None, ge=0, le=365)
    cadence_days: int | None = None


@router.patch("/cases/{case_id}/reminders", response_model=RecoveryCase)
async def set_reminders(case_id: str, body: RemindersIn, user: dict = Depends(current_user)):
    """Turn nudges on/off, snooze them for N days, or set the cadence (1/3/7 days)."""
    await _get_case(case_id, user)
    patch: dict = {"updated_at": now()}
    if body.enabled is not None:
        patch["reminders_enabled"] = body.enabled
    if body.snooze_days is not None:
        patch["snooze_until"] = now() + timedelta(days=body.snooze_days) if body.snooze_days > 0 else None
    if body.cadence_days in (1, 3, 7):
        patch["reminder_cadence_days"] = body.cadence_days
    await db.recovery_cases.update_one({"id": case_id}, {"$set": patch})
    await audit(user, "RECOVERY_REMINDERS", detail=f"{case_id} {body.model_dump(exclude_none=True)}")
    return RecoveryCase(**await _get_case(case_id, user))


@router.post("/cases/{case_id}/resolve", response_model=RecoveryCase)
async def resolve_case(case_id: str, user: dict = Depends(current_user)):
    """Mark a recovery Paid / Resolved so it drops out of the active list and stops reminders."""
    await _get_case(case_id, user)
    await db.recovery_cases.update_one(
        {"id": case_id}, {"$set": {"status": "RESOLVED", "resolved_at": now(), "updated_at": now()}}
    )
    await audit(user, "RECOVERY_RESOLVE", detail=case_id)
    return RecoveryCase(**await _get_case(case_id, user))


@router.post("/cases/{case_id}/reopen", response_model=RecoveryCase)
async def reopen_case(case_id: str, user: dict = Depends(current_user)):
    """Move a resolved recovery back to its furthest active step (e.g. a payment fell through)."""
    case = await _get_case(case_id, user)
    status = "DRAFT"
    if case.get("notice_body"):
        status = "NOTICE_READY"
    elif case.get("timeline"):
        status = "TIMELINE_READY"
    elif await db.recovery_proofs.count_documents(
        {"case_id": case_id, "processing_status": "READY"}
    ):
        status = "PROOF_ADDED"
    await db.recovery_cases.update_one(
        {"id": case_id}, {"$set": {"status": status, "updated_at": now()}, "$unset": {"resolved_at": "", "deletion_notice_at": ""}}
    )
    await audit(user, "RECOVERY_REOPEN", detail=f"{case_id} -> {status}")
    return RecoveryCase(**await _get_case(case_id, user))


MIN_PAYMENT_YEAR = 1990


def _payment_day(raw: str | None):
    """A payment date typed by a person: a real calendar date from 1990 to today (India time). Stored as midnight UTC of that day, so it never shifts a day."""
    from datetime import date, datetime, time, timezone

    today = _today()
    if not raw or not str(raw).strip():
        d = today
    else:
        try:
            d = date.fromisoformat(str(raw).strip()[:10])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="That payment date is not valid. Use a date like 2026-03-31.") from exc
        if d.year < MIN_PAYMENT_YEAR or d > today:
            raise HTTPException(status_code=422, detail="A payment date must be between 1990 and today.")
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _whole_paise(v: float) -> float:
    q = round(float(v), 2)
    if q < 0.01:
        raise HTTPException(status_code=422, detail="Enter an amount of at least 0.01.")
    return q


async def _sync_paid(case_id: str) -> None:
    """paid_amount is always the exact sum of the payment list (kept for older views), never a running total that could drift."""
    row = await db.recovery_cases.find_one({"id": case_id}, {"payments": 1})
    paid = round(sum(float(p.get("amount", 0)) for p in (row or {}).get("payments", [])), 2)
    await db.recovery_cases.update_one({"id": case_id}, {"$set": {"paid_amount": paid}})


RANK = {"DRAFT": 0, "PROOF_ADDED": 1, "TIMELINE_READY": 2, "NOTICE_READY": 3}


async def advance_status(case_id: str, new: str) -> None:
    """Move a case FORWARD along its steps. A resolved case or one handed to a lawyer keeps its status, and a step already passed is never undone."""
    row = await db.recovery_cases.find_one({"id": case_id}, {"status": 1})
    cur = (row or {}).get("status")
    if cur in RANK and RANK[new] > RANK[cur]:
        await db.recovery_cases.update_one({"id": case_id, "status": cur}, {"$set": {"status": new, "updated_at": now()}})


class PaymentIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000_000_000, allow_inf_nan=False)
    date: str | None = Field(default=None, max_length=10)  # the day it was received (YYYY-MM-DD); today if left out


@router.post("/cases/{case_id}/payment", response_model=RecoveryCase)
async def record_payment(case_id: str, body: PaymentIn, user: dict = Depends(current_user)):
    """Record a part-payment received; the remaining balance updates on the case."""
    amount, when = _whole_paise(body.amount), _payment_day(body.date)
    await _get_case(case_id, user)
    await db.recovery_cases.update_one(
        {"id": case_id, "organization_id": user["organization_id"]},
        {"$push": {"payments": {"id": str(uuid.uuid4()), "amount": amount, "date": when}}, "$set": {"updated_at": now()}},
    )
    await _sync_paid(case_id)
    await audit(user, "RECOVERY_PAYMENT", detail=f"{case_id} +{amount}")
    return RecoveryCase(**await _get_case(case_id, user))


@router.delete("/cases/{case_id}/payment/{payment_id}", response_model=RecoveryCase)
async def delete_payment(case_id: str, payment_id: str, user: dict = Depends(current_user)):
    """Remove a part-payment recorded by mistake and recompute the balance."""
    await _get_case(case_id, user)
    res = await db.recovery_cases.update_one(
        {"id": case_id, "organization_id": user["organization_id"], "payments.id": payment_id},
        {"$pull": {"payments": {"id": payment_id}}, "$set": {"updated_at": now()}},
    )
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Payment not found")
    await _sync_paid(case_id)
    await audit(user, "RECOVERY_PAYMENT_DELETE", detail=f"{case_id} {payment_id}")
    return RecoveryCase(**await _get_case(case_id, user))


_NEXT_HINT = {
    "DRAFT": "add a proof document or screenshot",
    "PROOF_ADDED": "tap “Understand my case”",
    "TIMELINE_READY": "create your demand notice",
    "NOTICE_READY": "download the notice or send it for a lawyer to review",
}


@router.get("/cases/{case_id}/nudge-preview")
async def nudge_preview(case_id: str, user: dict = Depends(current_user)):
    """Preview the reminder email text the owner would receive for this case."""
    case = await _get_case(case_id, user)
    hint = _NEXT_HINT.get(case.get("status", ""), "continue your recovery")
    subject = f"A quick nudge on your recovery against {case['debtor_name']}"
    body = (
        f"Hi {user.get('full_name') or 'there'},\n\n"
        f"Your recovery of money from {case['debtor_name']} has been paused for a few days. "
        f"You're closer than you think — the next small step is to {hint}.\n\n"
        "Open your recovery in VIDHI to continue.\n\n"
        "— VIDHI Legal Recovery (a free self-help tool; information, not legal advice). "
        "We never ask for your password or card details by email."
    )
    return {"subject": subject, "body": body}


@router.post("/cases/{case_id}/nudge-send", dependencies=[Depends(EMAIL_LIMIT)])
async def nudge_send(case_id: str, user: dict = Depends(require_verified_sender)):
    """Send the reminder email to the owner's own inbox right now (from the preview)."""
    case = await _get_case(case_id, user)
    link = f"{os.environ.get('APP_URL', '').rstrip('/')}/recovery/cases/{case_id}"
    header = await email_logo_header(user["organization_id"])
    subject, html = reminder_email(case, user.get("full_name") or "there", link, header)
    try:
        await send_email(to=user["email"], subject=subject, html=html)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail="We couldn't send the reminder — your email address looks undeliverable.",
        ) from exc
    await audit(user, "RECOVERY_NUDGE_SEND", detail=case_id)
    return {"ok": True, "sent_to": user["email"]}


class EditPaymentIn(BaseModel):
    amount: float | None = Field(default=None, gt=0, le=1_000_000_000_000, allow_inf_nan=False)
    date: str | None = Field(default=None, max_length=10)


@router.patch("/cases/{case_id}/payment/{payment_id}", response_model=RecoveryCase)
async def edit_payment(
    case_id: str, payment_id: str, body: EditPaymentIn, user: dict = Depends(current_user)
):
    """Correct the amount or date of a recorded part-payment in place."""
    await _get_case(case_id, user)
    changes: dict = {}
    if body.amount is not None:
        changes["payments.$[p].amount"] = _whole_paise(body.amount)
    if body.date:
        changes["payments.$[p].date"] = _payment_day(body.date)
    if not changes:
        raise HTTPException(status_code=422, detail="Give a new amount or a new date.")
    res = await db.recovery_cases.update_one(
        {"id": case_id, "organization_id": user["organization_id"], "payments.id": payment_id},
        {"$set": {**changes, "updated_at": now()}},
        array_filters=[{"p.id": payment_id}],
    )
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Payment not found")
    await _sync_paid(case_id)
    await audit(user, "RECOVERY_PAYMENT_EDIT", detail=f"{case_id} {payment_id}")
    return RecoveryCase(**await _get_case(case_id, user))


@router.post("/cases/{case_id}/handoff", response_model=Matter)
async def handoff_to_lawyer(case_id: str, user: dict = Depends(current_user)):
    """Bridge Division 2 → Division 1: open a Matter in Legal Intelligence for lawyer review."""
    case = await _get_case(case_id, user)
    if case.get("linked_matter_id"):
        existing = await db.matters.find_one({"id": case["linked_matter_id"]})
        if existing:
            return Matter(**existing)
    pos = position(case)  # one exact calculation, the same one the notice and statements use
    cur = pos["currency"]
    pay_lines = (
        "\n".join(
            f"- {str(p.get('date', ''))[:10]}: +{fmt_money(p.get('amount', 0), cur)}"
            for p in case.get("payments", [])
        )
        or "- none recorded"
    )
    desc = (
        f"Opened from a Legal Recovery case.\n\n"
        f"Amount claimed: {fmt_money(pos['owed'], cur)}\n"
        f"Total received: {fmt_money(pos['received'], cur)}\n"
        f"Remaining balance: {fmt_money(pos['remaining'], cur)}\n\n"
        f"Payment history:\n{pay_lines}\n\n"
        f"{case.get('summary') or case.get('description') or ''}"
    )
    matter = Matter(
        organization_id=user["organization_id"],
        created_by=user["id"],
        title=f"Recovery: {case['creditor_name']} vs {case['debtor_name']}",
        description=desc[:4000],
        parties=f"{case['creditor_name']} vs {case['debtor_name']}",
        jurisdiction_id="IN",
    )
    await db.matters.insert_one(matter.model_dump())
    # Carry the generated notice over as a draft the lawyer can edit.
    if case.get("notice_body"):
        from models.schemas import Draft

        draft = Draft(
            organization_id=user["organization_id"],
            matter_id=matter.id,
            created_by=user["id"],
            title=f"Demand notice — {case['debtor_name']}",
            body=case["notice_body"],
        )
        await db.drafts.insert_one(draft.model_dump())
    # Carry the timeline over as matter timeline events.
    for t in case.get("timeline", []):
        if t.get("date"):
            await db.timeline_events.insert_one(
                {
                    "id": str(uuid.uuid4()),
                    "matter_id": matter.id,
                    "organization_id": user["organization_id"],
                    "event_date": str(t.get("date"))[:40],
                    "description": str(t.get("description", ""))[:300],
                    "actor": "",
                    "document_id": None,
                    "page_reference": None,
                    "status": "DOCUMENT_SUPPORTED",
                    "created_at": now(),
                }
            )
    await db.recovery_cases.update_one(
        {"id": case_id},
        {"$set": {"linked_matter_id": matter.id, "updated_at": now(), **({} if case.get("status") == "RESOLVED" else {"status": "SENT_FOR_REVIEW"})}},
    )
    await audit(user, "RECOVERY_HANDOFF", matter_id=matter.id, detail=case_id)
    return matter
