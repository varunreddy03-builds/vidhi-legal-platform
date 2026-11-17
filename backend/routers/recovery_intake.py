"""Recovery case intake, readiness check and notice drafting.

The owner states the facts (invoice, terms, disputes, charges, credits). Code does the arithmetic
(lib/balance.py), lists missing evidence (lib/evidence_check.py) and raises route warnings
(lib/route_checks.py). The AI only writes the wording around figures that code supplies, and the statement of
account and the enclosure list are inserted by code, so a model can never alter a number or invent a document.
"""

import logging
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.ai import RECOVERY_PROMPT, ai_failure, ask_json, log_ai_failure
from lib.safety import fence
from lib.auth import audit, current_user, now
from lib.balance import compute_balance, statement_text
from lib.db import db
from lib.evidence_check import check_evidence, enclosures as enclosure_list
from lib.notice_checks import blockers_for
from lib.ratelimit import AI_LIMIT
from models.schemas import Charge, CaseIntake, Credit, Disputes, PromiseToPay, RecoveryCase, RouteAnswers
from routers.recovery import NOTICE_SCHEMA, _fmt_date, _get_case, _interest_now, _today, advance_status, blocker_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recovery", tags=["recovery-intake"])


def _iso(value: str | None, what: str, *, not_future: bool = False) -> str | None:
    if not value:
        return None
    try:
        d = date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"The {what} is not a valid date.") from exc
    if d.year < 1990 or (not_future and d > _today()):
        raise HTTPException(status_code=422, detail=f"The {what} does not look right.")
    return d.isoformat()


# ---------------------------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------------------------
class IntakeIn(BaseModel):
    """Everything is optional: send only what changed. Lists (charges, credits) replace the stored list."""

    amount: float | None = Field(default=None, ge=0, le=1_000_000_000_000, allow_inf_nan=False)
    debtor_email: str | None = Field(default=None, max_length=200)
    invoice_number: str | None = Field(default=None, max_length=60)
    invoice_date: str | None = Field(default=None, max_length=10)
    supply_description: str | None = Field(default=None, max_length=1000)
    payment_terms: str | None = Field(default=None, max_length=500)
    creditor_email: str | None = Field(default=None, max_length=200)
    creditor_phone: str | None = Field(default=None, max_length=30)
    debtor_phone: str | None = Field(default=None, max_length=30)
    promise_to_pay: PromiseToPay | None = None
    disputes: Disputes | None = None
    route: RouteAnswers | None = None
    response_days: int | None = Field(default=None, ge=7, le=60)
    charges: list[Charge] | None = Field(default=None, max_length=30)
    credits: list[Credit] | None = Field(default=None, max_length=30)


@router.patch("/cases/{case_id}/intake", response_model=RecoveryCase)
async def set_intake(case_id: str, body: IntakeIn, user: dict = Depends(current_user)):
    case = await _get_case(case_id, user)
    patch: dict = {"updated_at": now()}
    intake = dict(case.get("intake") or {})
    sent = body.model_dump(exclude_unset=True)

    if "amount" in sent and body.amount is not None:
        patch["amount"] = round(body.amount, 2)  # whole paise
    if "debtor_email" in sent:
        patch["debtor_email"] = (body.debtor_email or "").strip()
    for key in ("invoice_number", "supply_description", "payment_terms", "creditor_email", "creditor_phone", "debtor_phone"):
        if key in sent and sent[key] is not None:
            intake[key] = sent[key].strip()
    if "invoice_date" in sent:
        intake["invoice_date"] = _iso(body.invoice_date, "invoice date", not_future=True)
        if intake["invoice_date"] and case.get("due_date") and str(case["due_date"])[:10] < intake["invoice_date"]:
            raise HTTPException(status_code=422, detail="The invoice date cannot be after the date the payment fell due. Change the due date first, or check the invoice date.")
    if body.promise_to_pay is not None:
        p = body.promise_to_pay.model_dump()
        p["date"] = _iso(p.get("date"), "date of the promise", not_future=True)
        p["text"] = (p.get("text") or "").strip()
        intake["promise_to_pay"] = p
    if body.disputes is not None:
        intake["disputes"] = body.disputes.model_dump()
    if body.route is not None:
        intake["route"] = body.route.model_dump()
    if body.response_days is not None:
        intake["response_days"] = body.response_days
    if body.charges is not None:
        if any(not c.basis.strip() for c in body.charges):
            raise HTTPException(
                status_code=422,
                detail="Each extra charge needs a written basis (for example the clause of your agreement). "
                "Without one it cannot be added.",
            )
        patch["charges"] = [{**c.model_dump(), "label": c.label.strip(), "basis": c.basis.strip()} for c in body.charges]
    if body.credits is not None:
        patch["credits"] = [{**c.model_dump(), "label": c.label.strip(), "reason": c.reason.strip()} for c in body.credits]
    patch["intake"] = CaseIntake(**intake).model_dump()  # validates the merged result
    await db.recovery_cases.update_one({"id": case_id}, {"$set": patch})
    await audit(user, "RECOVERY_INTAKE", detail=f"{case_id}: {', '.join(sorted(sent))}")
    return RecoveryCase(**await _get_case(case_id, user))


# ---------------------------------------------------------------------------------------------
# Readiness: balance + evidence + warnings + who said what
# ---------------------------------------------------------------------------------------------
async def _proofs(case_id: str) -> list[dict]:
    return await db.recovery_proofs.find({"case_id": case_id}).sort("created_at", 1).to_list(200)


def _provenance(case: dict, bal: dict) -> list[dict]:
    """Every fact the notice rests on, labelled by where it came from."""
    intake = case.get("intake") or {}
    you = "YOU_ENTERED"
    rows = [
        {"label": "Your business", "value": case.get("creditor_name", ""), "source": you},
        {"label": "Customer", "value": case.get("debtor_name", ""), "source": you},
        {"label": "Invoice number", "value": intake.get("invoice_number") or "", "source": you},
        {"label": "Invoice date", "value": intake.get("invoice_date") or "", "source": you},
        {"label": "Supplied", "value": intake.get("supply_description") or "", "source": you},
        {"label": "Payment terms", "value": intake.get("payment_terms") or "", "source": you},
        {"label": "Due date", "value": case.get("due_date") or "", "source": you},
        {"label": "Invoice amount", "value": f"{bal['invoice_amount']:,.2f} {bal['currency']}", "source": you},
        {"label": "Balance due", "value": f"{bal['balance']:,.2f} {bal['currency']}", "source": "CALCULATED"},
    ]
    if case.get("detected_amount"):
        rows.append({"label": "Amount the AI read from your documents", "value": f"{case['detected_amount']:,.2f} {bal['currency']}", "source": "READ_FROM_DOCUMENTS"})
    if case.get("summary"):
        rows.append({"label": "Plain-language summary", "value": case["summary"], "source": "AI_SUGGESTION"})
    return [r for r in rows if r["value"] != ""]


@router.get("/cases/{case_id}/readiness")
async def readiness(case_id: str, user: dict = Depends(current_user)):
    """One call for the 'check before drafting' panel. Nothing here is generated by a model."""
    from lib.route_checks import check_routes

    case = await _get_case(case_id, user)
    proofs = await _proofs(case_id)
    bal = compute_balance(case)
    routes = check_routes(case, _today())
    evidence = check_evidence(case, proofs)
    blockers: list[str] = []
    if bal["invoice_amount"] <= 0:
        blockers.append("Enter the invoice amount.")
    elif bal["balance"] <= 0:
        blockers.append("Nothing is outstanding according to the figures entered.")
    for key, label in (("creditor_address", "your business address"), ("debtor_address", "the customer's address")):
        if not (case.get(key) or "").strip():
            blockers.append(f"Add {label}.")
    return {
        "balance": bal,
        "evidence": evidence,
        "routes": routes,
        "provenance": _provenance(case, bal),
        "draft_blockers": blockers,
        "can_draft": not blockers,
        "route_acknowledgement_needed": routes["blocks_notice"],
        "response_days": (case.get("intake") or {}).get("response_days", 15),
        "disclaimer": "VIDHI helps prepare documents. It does not give legal advice and a notice it drafts is not "
        "automatically legally valid. You are responsible for the facts in it.",
    }


# ---------------------------------------------------------------------------------------------
# Notice drafting
# ---------------------------------------------------------------------------------------------
STATEMENT_MARK, ENCLOSURE_MARK = "{{STATEMENT}}", "{{ENCLOSURES}}"
_CLOSING = re.compile(r"(?im)^\s*yours\s+(faithfully|sincerely|truly)")


def assemble_notice(text: str, statement: str, enclosure_block: str) -> str:
    """Put the code-written blocks where the model marked them, or before the closing line if it forgot."""
    for mark, block in ((STATEMENT_MARK, statement), (ENCLOSURE_MARK, enclosure_block)):
        if mark in text:
            text = text.replace(mark, block)
        else:
            m = _CLOSING.search(text)
            text = (text[: m.start()] + block + "\n\n" + text[m.start():]) if m else (text.rstrip() + "\n\n" + block)
    return text


def enclosure_text(proofs: list[dict]) -> str:
    names = enclosure_list(proofs)
    if not names:
        return "Enclosures\n  No documents are enclosed with this notice."
    return "Enclosures\n" + "\n".join(f"  {i}. {n}" for i, n in enumerate(names, 1))


class NoticeGenIn(BaseModel):
    acknowledge_route: bool = False  # the owner has read the STOP warnings and still wants an ordinary letter
    response_days: int | None = Field(default=None, ge=7, le=60)


@router.post("/cases/{case_id}/notice", response_model=RecoveryCase, dependencies=[Depends(AI_LIMIT)])
async def generate_notice(case_id: str, body: NoticeGenIn = NoticeGenIn(), user: dict = Depends(current_user)):
    """Draft a payment-demand notice from the facts the owner entered. A DRAFT: nothing is sent by this."""
    from lib.route_checks import check_routes

    case = await _get_case(case_id, user)
    from lib.notice_workflow import state_of

    if state_of(case) == "CLOSED":  # checked before any AI request is spent
        raise HTTPException(status_code=409, detail="This notice process is closed.")
    missing = [
        label
        for label, key in (("your address", "creditor_address"), ("the other party's address", "debtor_address"))
        if not (case.get(key) or "").strip()
    ]
    if missing:
        raise HTTPException(status_code=422, detail=f"Add {' and '.join(missing)} before drafting the notice.")
    bal = compute_balance(case)
    if bal["invoice_amount"] <= 0:
        raise HTTPException(status_code=422, detail="Enter the invoice amount yourself before drafting the notice.")
    if bal["balance"] <= 0:
        raise HTTPException(status_code=422, detail="Nothing is outstanding according to the figures entered, so there is nothing to demand.")
    routes = check_routes(case, _today())
    if routes["blocks_notice"] and not body.acknowledge_route:
        titles = "; ".join(f["title"] for f in routes["flags"] if f["level"] == "STOP")
        raise HTTPException(
            status_code=409,
            detail=f"Before drafting: {titles}. An ordinary demand letter may not be the right step - read the warnings and "
            "confirm that you still want to draft one.",
        )
    intake = case.get("intake") or {}
    days = body.response_days or intake.get("response_days") or 15
    cur = bal["currency"]
    today = _today()
    proofs = await _proofs(case_id)
    interest = _interest_now(case, today)
    statement = statement_text(bal, interest, _fmt_date(interest["start"]) if interest else "", _fmt_date(interest["as_of"]) if interest else "")
    tl = "\n".join(f"- {t.get('date', '')}: {t.get('description', '')}" for t in case.get("timeline", []))
    promise = intake.get("promise_to_pay") or {}
    disputes = intake.get("disputes") or {}
    disputed = [k for k in ("invoice", "quality", "delivery", "amount") if disputes.get(k)]
    facts = [
        f"- Notice date: {_fmt_date(today.isoformat())}",
        f"- From (creditor): {case['creditor_name']}, {case['creditor_address'].strip()}"
        + (f"; phone {intake['creditor_phone']}" if intake.get("creditor_phone") else "")
        + (f"; email {intake['creditor_email']}" if intake.get("creditor_email") else ""),
        f"- To (customer): {case['debtor_name']}, {case['debtor_address'].strip()}",
        f"- Invoice: {intake.get('invoice_number') or '(number not given)'}"
        + (f" dated {_fmt_date(intake['invoice_date'])}" if intake.get("invoice_date") else ""),
        f"- Goods or services supplied: {intake.get('supply_description') or '(not described)'}",
        f"- Payment terms: {intake.get('payment_terms') or '(not stated)'}",
        f"- Payment fell due on: {_fmt_date(case['due_date']) if case.get('due_date') else '(due date not given)'}",
        f"- Balance due: {bal['balance']:,.2f} {cur} (the statement of account is inserted by our system at the marker)",
        f"- The customer has {days} days from receiving the notice to pay or reply",
    ]
    if promise.get("text"):
        facts.append(
            "- The sender reports a written promise to pay"
            + (f" dated {_fmt_date(promise['date'])}" if promise.get("date") else "")
            + f": \"{promise['text']}\""
        )
    if disputed:
        facts.append(
            f"- The customer is reported to dispute: {', '.join(disputed)}"
            + (f" ({disputes['note']})" if disputes.get("note") else "")
            + ". Mention this neutrally and invite the customer to say specifically what is disputed. Do not argue or accuse."
        )
    prompt = (
        "Draft a formal payment-demand notice in English for an unpaid invoice in India. Use EXACTLY these facts and "
        "do not change, omit or invent any of them:\n" + "\n".join(facts) + "\n"
        f"Background summary: {fence(case.get('summary') or case.get('description') or '', 'SUMMARY')}\n"
        f"Timeline:\n{fence(tl or '(none provided)', 'TIMELINE')}\n\n"
        "Structure: date line, to/from, subject line naming the invoice, numbered factual paragraphs, then the line "
        f"{STATEMENT_MARK} on its own (our system replaces it with the statement of account - do NOT write any "
        f"calculation yourself), a clear request to pay the balance due within {days} days of receiving the notice or to "
        f"reply in writing saying what is disputed, then the line {ENCLOSURE_MARK} on its own, and a closing signed "
        f"'Yours faithfully, {case['creditor_name']}'. Plain, firm, courteous language.\n"
        "STRICT RULES: (1) Do NOT mention any law, section, Act, rule, article or court case anywhere - nothing in this "
        "tool is verified against the law. (2) Do NOT use square brackets, except that if a fact you genuinely need is "
        "missing write exactly [ ] in its place. (3) Do not invent facts, amounts or dates; state the balance due exactly "
        "as given and do not restate other figures. (4) Never mention arrest, police, criminal action, fraud, cheating or "
        "dishonesty, and never say or imply that anyone lied. Do not promise any outcome. The only consequence you may "
        "mention is that the creditor may take advice and pursue lawful remedies. (5) End with one line saying this is a "
        "draft to be reviewed before sending."
    )
    try:
        data = await ask_json(f"recovery-notice-{case_id}", prompt, NOTICE_SCHEMA, system=RECOVERY_PROMPT)
    except Exception as exc:  # noqa: BLE001
        await audit(user, "RECOVERY_NOTICE", result="FAILED", detail=case_id)
        log_ai_failure("recovery notice", exc)
        raise ai_failure(exc) from exc
    text = str(data.get("notice") or "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="The notice came back empty — please retry.")
    notice = assemble_notice(text, statement, enclosure_text(proofs))
    if len(notice) > 14000:  # never cut a notice: the statement of account at its end could be lost
        raise HTTPException(status_code=422, detail="The drafted notice is too long to keep. Shorten the summary or the timeline and try again.")
    meta = {
        "generated_at": now(),
        "response_days": days,
        "balance": bal["balance"],
        "statement": statement,  # kept so every later check can confirm the statement of account is untouched and still matches the case
        "currency": cur,
        "enclosures": enclosure_list(proofs),
        "route_acknowledged": bool(routes["blocks_notice"] and body.acknowledge_route),
        "ai_drafted": True,
    }
    from lib.notice_workflow import add_version, current_version

    await current_version(case)  # an earlier text is kept as its own version before it is replaced
    await db.recovery_cases.update_one(
        {"id": case_id},
        {"$set": {"notice_body": notice, "notice_meta": meta, "updated_at": now(), "intake.response_days": days}},
    )
    await advance_status(case_id, "NOTICE_READY")
    await add_version(await _get_case(case_id, user), notice, "AI_DRAFT", user, {k: v for k, v in meta.items() if k != "generated_at"})
    await audit(user, "RECOVERY_NOTICE", detail=case_id)
    return RecoveryCase(**await _get_case(case_id, user))


class TemplateNoticeIn(BaseModel):
    text: str = Field(min_length=40, max_length=12000)  # the letter written from the lawyer-editable template, with {{STATEMENT}} and {{ENCLOSURES}} where VIDHI puts its blocks
    response_days: int | None = Field(default=None, ge=7, le=60)


@router.post("/cases/{case_id}/notice/template", response_model=RecoveryCase)
async def notice_from_template(case_id: str, body: TemplateNoticeIn, user: dict = Depends(current_user)):
    """Make the notice from a template instead of the AI. The statement of account and the enclosure list are written by our code, exactly as for an
    AI draft; the same checks (no blanks, no legal references, no threats, no stray figures) apply later, before the PDF, the approval or an email."""
    from lib.notice_workflow import add_version, current_version, state_of

    case = await _get_case(case_id, user)
    if state_of(case) == "CLOSED":
        raise HTTPException(status_code=409, detail="This notice process is closed.")
    missing = [
        label
        for label, key in (("your address", "creditor_address"), ("the other party's address", "debtor_address"))
        if not (case.get(key) or "").strip()
    ]
    if missing:
        raise HTTPException(status_code=422, detail=f"Add {' and '.join(missing)} before making the notice.")
    bal = compute_balance(case)
    if bal["invoice_amount"] <= 0:
        raise HTTPException(status_code=422, detail="Enter the invoice amount yourself before making the notice.")
    if bal["balance"] <= 0:
        raise HTTPException(status_code=422, detail="Nothing is outstanding according to the figures entered, so there is nothing to demand.")
    days = body.response_days or (case.get("intake") or {}).get("response_days") or 15
    today = _today()
    proofs = await _proofs(case_id)
    interest = _interest_now(case, today)
    statement = statement_text(bal, interest, _fmt_date(interest["start"]) if interest else "", _fmt_date(interest["as_of"]) if interest else "")
    notice = assemble_notice(body.text.strip(), statement, enclosure_text(proofs))
    if len(notice) > 14000:
        raise HTTPException(status_code=422, detail="The notice is too long to keep. Shorten the description and try again.")
    meta = {
        "generated_at": now(), "response_days": days, "balance": bal["balance"], "statement": statement, "currency": bal["currency"],
        "enclosures": enclosure_list(proofs), "route_acknowledged": False, "ai_drafted": False, "from_template": True,
    }
    await current_version(case)
    await db.recovery_cases.update_one(
        {"id": case_id}, {"$set": {"notice_body": notice, "notice_meta": meta, "updated_at": now(), "intake.response_days": days}}
    )
    await advance_status(case_id, "NOTICE_READY")
    await add_version(await _get_case(case_id, user), notice, "TEMPLATE", user, {k: v for k, v in meta.items() if k != "generated_at"})
    await audit(user, "RECOVERY_NOTICE_TEMPLATE", detail=case_id)
    return RecoveryCase(**await _get_case(case_id, user))


@router.get("/cases/{case_id}/notice-preview")
async def notice_preview(case_id: str, user: dict = Depends(current_user)):
    """The whole notice as it would go out, with what is still blocking it and what each part rests on."""
    case = await _get_case(case_id, user)
    if not case.get("notice_body"):
        raise HTTPException(status_code=409, detail="Create the demand notice first.")
    check = blockers_for(case)
    meta = case.get("notice_meta") or {}
    return {
        "notice_text": case["notice_body"],
        "blockers": check,
        "blocker_message": blocker_message(check) if check["blocked"] else None,
        "enclosures": meta.get("enclosures", []),
        "response_days": meta.get("response_days"),
        "balance": compute_balance(case),
        "ai_drafted": bool(meta.get("ai_drafted")),
        "notes": [
            "The wording was drafted by an AI from the facts you entered; the statement of account and the enclosure "
            "list were produced by VIDHI from your figures and uploads.",
            "Read every line. You are responsible for the facts in it.",
            "A notice does not by itself create or prove any legal right, and sending it is not legal service.",
        ],
    }
