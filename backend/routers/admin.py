"""The operator's admin console (API). Every route here requires `require_platform_admin` (lib/platform.py): confirmed email, listed in
PLATFORM_ADMIN_EMAILS, two-step sign-in on. Nothing here returns passwords, secrets, API keys, document text or answers: it shows people,
counts, costs and the state of the service. Every action is written to the audit log."""

import os
import re
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib import verified_store as vstore
from lib import aibudget, business, monitoring, pilot
from lib.auth import audit, now
from lib.db import db
from lib.platform import admin_emails, is_platform_admin, require_platform_admin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_platform_admin)])
from routers.legal import admin_router as _legal_admin  # noqa: E402  (loading and reviewing legal text: same guard as every admin route)
from routers.legal_links import admin_router as _legal_links_admin  # noqa: E402
from routers.judgments import admin_router as _judgments_admin  # noqa: E402
from routers.deadlinerules import admin_router as _deadline_rules_admin  # noqa: E402  (entering and reviewing deadline rules: same guard)

from routers.knowledge import admin_router as _knowledge_admin  # noqa: E402  (catalogue, rights and ingestion of the knowledge library: same guard)

router.routes.extend(_knowledge_admin.routes)
from routers.admin_weekly import admin_router as _weekly_admin  # noqa: E402  (the weekly view: same guard)

router.routes.extend(_weekly_admin.routes)
from routers.admin_plans import admin_router as _plans_admin  # noqa: E402  (plans and putting an organisation on one: same guard)

router.routes.extend(_plans_admin.routes)
from routers.admin_product import admin_router as _product_admin  # noqa: E402  (anonymous product numbers: same guard)

router.routes.extend(_product_admin.routes)
router.routes.extend(_legal_admin.routes)
router.routes.extend(_legal_links_admin.routes)  # added directly (not nested) so the one guard on this router covers them and the guard test can see them
router.routes.extend(_judgments_admin.routes)  # judgment relations: review by a named person
router.routes.extend(_deadline_rules_admin.routes)
from routers.reviewers import admin_router as _reviewers_admin  # noqa: E402  (advocate register and recording their confirmations: same guard)

router.routes.extend(_reviewers_admin.routes)

WATCHLIST = ("AUTH_2FA_FAILED", "DOCUMENT_INSTRUCTION_LIKE_TEXT", "PRIVACY_REQUEST", "ADMIN_BLOCK", "IMAGE_GENERATED", "VOICE_TRANSCRIBE")


def _configured(*names: str) -> bool:
    return any((os.environ.get(n) or "").strip() for n in names)


def _services() -> dict[str, bool]:
    """Which outside services have credentials set. Booleans only: never the values."""
    from lib.crypto import enabled as encryption_on

    return {
        "ai_gemini": _configured("GEMINI_API_KEY"), "ai_claude": _configured("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "OPENROUTER_API_KEY"), "ai_groq": _configured("GROQ_API_KEY"), "ai_nvidia": _configured("NVIDIA_API_KEY"),
        "email": _configured("RESEND_API_KEY", "SENDGRID_API_KEY"), "payments_stripe": _configured("STRIPE_SECRET_KEY"), "payments_razorpay": _configured("RAZORPAY_KEY_ID"),
        "payments_paypal": _configured("PAYPAL_CLIENT_ID"), "sms_twilio": _configured("TWILIO_ACCOUNT_SID"), "voice_elevenlabs": _configured("ELEVENLABS_API_KEY"),
        "google_sign_in": _configured("GOOGLE_CLIENT_ID") and _configured("GOOGLE_CLIENT_SECRET"), "error_tracking_sentry": monitoring.enabled(),
        "file_encryption": encryption_on(), "bot_check": _configured("TURNSTILE_SECRET_KEY"), "uptime_alert_contact": _configured("UPTIME_ALERT_CONTACT"),
        "owner_alert_email": _configured("OWNER_ALERT_EMAIL"),
    }


@router.get("/overview")
async def overview():
    since = now() - timedelta(days=7)
    try:
        await db.command("ping")
        database = "ok"
    except Exception:  # noqa: BLE001
        database = "unreachable"
    users = await db.users.count_documents({})
    plans = {p["_id"] or "FREE": p["n"] for p in await db.users.aggregate([{"$match": {"role": "OWNER"}}, {"$group": {"_id": "$plan", "n": {"$sum": 1}}}]).to_list(10)}
    services = _services()
    todo = []
    if business.missing():
        todo.append("Business and privacy details are missing: " + ", ".join(business.missing()))
    todo += business.problems()
    if not services["error_tracking_sentry"]:
        todo.append("Error tracking is off (set SENTRY_DSN)")
    if not services["owner_alert_email"]:
        todo.append("AI budget alerts have nowhere to go (set OWNER_ALERT_EMAIL)")
    if not services["file_encryption"]:
        todo.append("Uploaded files are NOT encrypted (set DATA_ENCRYPTION_KEY)")
    if not services["uptime_alert_contact"]:
        todo.append("No uptime alert contact is recorded (set UPTIME_ALERT_CONTACT and configure the uptime monitor)")
    return {
        "database": database,
        "users": {"total": users, "new_7_days": await db.users.count_documents({"created_at": {"$gte": since}}), "blocked": await db.users.count_documents({"blocked": {"$exists": True}}),
                  "organisations": await db.organizations.count_documents({}), "pro_owners": plans.get("PRO", 0), "free_owners": plans.get("FREE", 0)},
        "ai_budget": await aibudget.get_budget().status(),
        "work": {"open_support": await db.support_tickets.count_documents({"status": "OPEN"}), "open_data_requests": await db.data_requests.count_documents({"status": {"$in": ["RECEIVED", "IN_PROGRESS"]}}),
                 "pending_lawyer_review_entries": await vstore.count("legal_source_candidates")},
        "services": services,
        "business": {"missing": business.missing(), "problems": business.problems()},
        "todo": todo,
        "admins_configured": len(admin_emails()),
    }


@router.get("/users")
async def users(q: str = "", skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    flt: dict = {}
    if q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        flt = {"$or": [{"email": rx}, {"full_name": rx}, {"organization_name": rx}]}
    rows = await db.users.find(flt, {"password_hash": 0, "two_factor": 0, "two_factor_pending": 0, "phone": 0, "phone_pending": 0, "google_sub": 0, "email_verification": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    out = []
    for r in rows:
        org = r["organization_id"]
        out.append({
            "id": r["id"], "email": r["email"], "name": r.get("full_name"), "role": r.get("role"), "organization": r.get("organization_name"), "plan": r.get("plan", "FREE"),
            "created_at": r.get("created_at"), "email_verified": bool(r.get("email_verified")), "two_step": bool((r.get("two_factor") or {}).get("enabled")) if "two_factor" in r else False,
            "blocked": r.get("blocked"), "matters": await db.matters.count_documents({"organization_id": org}), "recovery_cases": await db.recovery_cases.count_documents({"organization_id": org}),
            "is_platform_admin": is_platform_admin(r),
        })
    return {"total": await db.users.count_documents(flt), "users": out}


# ------------------------------------------------------------------ refunds: recorded here AFTER the money was returned in the provider's dashboard
# VIDHI does not move money. The operator refunds in Stripe, Razorpay or PayPal (their own, tested flows), then records it here so the history, the
# customer's account and the audit log agree. Automatic provider refunds would need each provider's sandbox to verify, and a refund policy the owner has not set.

@router.get("/pricing")
async def pricing():
    """Which currencies have prices configured and which countries are open. Read-only; no tax is calculated anywhere."""
    from lib import pricing as pr

    return {"rows": pr.table(), "tax": "No tax or GST is calculated or shown by VIDHI. That is a decision for the owner and an accountant (docs/PAYMENTS.md)."}


@router.get("/payments")
async def payments(q: str = "", limit: int = Query(30, ge=1, le=100)):
    flt: dict = {}
    if q.strip():
        users = await db.users.find({"email": {"$regex": re.escape(q.strip()), "$options": "i"}}, {"id": 1}).limit(50).to_list(50)
        flt = {"$or": [{"user_id": {"$in": [u["id"] for u in users]}}, {"session_id": q.strip()}]}
    rows = await db.payment_transactions.find(flt).sort("created_at", -1).limit(limit).to_list(limit)
    emails = {u["id"]: u["email"] async for u in db.users.find({"id": {"$in": [r.get("user_id") for r in rows if r.get("user_id")]}}, {"id": 1, "email": 1})}
    return [{"session_id": r["session_id"], "email": emails.get(r.get("user_id")), "provider": r.get("provider"), "package_id": r.get("package_id"), "interval": r.get("interval"),
             "amount": r.get("amount"), "currency": r.get("currency"), "status": r.get("status"), "payment_status": r.get("payment_status"), "renewal": bool(r.get("renewal")),
             "refunded_amount": r.get("refunded_amount", 0.0), "created_at": r.get("created_at")} for r in rows]


class RefundIn(BaseModel):
    amount: float | None = Field(default=None, gt=0, le=10_000_000, description="leave empty for everything not yet refunded")
    reason: str = Field(min_length=5, max_length=300)
    returned_through_provider: bool = Field(description="must be true: you have ALREADY returned this money in the provider's dashboard")
    end_pro_now: bool = False  # also switch the organisation to the Free plan at once (cancel the subscription in the provider's dashboard yourself)
    tell_customer: bool = True


@router.post("/payments/{session_id}/refund")
async def record_refund(session_id: str, body: RefundIn, admin: dict = Depends(require_platform_admin)):
    from decimal import Decimal

    if not body.returned_through_provider:
        raise HTTPException(status_code=422, detail="Refund the money in the payment provider's dashboard first, then record it here and tick the box.")
    tx = await db.payment_transactions.find_one({"session_id": session_id})
    if not tx:
        raise HTTPException(status_code=404, detail="No such payment")
    if tx.get("payment_status") != "paid" or tx.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Only a completed, paid payment can be refunded.")
    total, done = Decimal(str(tx.get("amount", 0))), Decimal(str(tx.get("refunded_amount", 0)))
    amount = Decimal(str(body.amount)) if body.amount is not None else total - done
    if amount <= 0 or done + amount > total:
        raise HTTPException(status_code=409, detail=f"At most {total - done} of this payment can still be refunded.")
    new_total = done + amount
    res = await db.payment_transactions.update_one(
        # two operators recording at once: only one wins (the amount refunded so far must still be what we just read)
        {"session_id": session_id, "refunded_amount": tx["refunded_amount"] if "refunded_amount" in tx else {"$exists": False}},
        {"$set": {"refunded_amount": float(new_total), "refund_status": "full" if new_total >= total else "partial", "updated_at": now()}},
    )
    if not res.modified_count:
        raise HTTPException(status_code=409, detail="This payment was just changed. Reload and try again.")
    import uuid

    refund = {"id": str(uuid.uuid4()), "session_id": session_id, "user_id": tx.get("user_id"), "organization_id": tx.get("organization_id"), "amount": float(amount),
              "currency": tx.get("currency"), "provider": tx.get("provider"), "reason": body.reason.strip(), "recorded_by": admin["email"], "end_pro_now": body.end_pro_now, "created_at": now()}
    await db.refunds.insert_one(dict(refund))
    buyer = await db.users.find_one({"id": tx.get("user_id")}) if tx.get("user_id") else None
    if body.end_pro_now and buyer:
        await db.users.update_one({"id": buyer["id"]}, {"$set": {"plan": "FREE", "subscription_status": "refunded", "pro_until": now()}})
    told = False
    if body.tell_customer and buyer and buyer.get("email"):
        from html import escape

        from lib.outbound import send_logged, simple_email
        from routers.payments import money_text

        try:
            await send_logged(to=buyer["email"], subject="Your VIDHI refund", kind="refund", user=buyer, respect_suppression=False, html=simple_email([
                f"We have refunded {escape(money_text(float(amount), tx.get('currency') or 'inr'))} for your VIDHI Pro payment (reference {escape(session_id[-8:])}).",
                "It can take several working days to appear with your bank or card provider. Reply to this email or use Contact support if it does not arrive.",
            ]))
            told = True
        except Exception:  # noqa: BLE001 - the refund record stands; only the courtesy email failed
            pass
    await audit(admin, "ADMIN_REFUND_RECORDED", detail=f"{session_id[-8:]} {amount} {tx.get('currency')}: {body.reason.strip()[:150]}")
    return {"ok": True, "refunded_total": float(new_total), "fully_refunded": new_total >= total, "customer_told": told, "pro_ended": bool(body.end_pro_now and buyer),
            "reminder": "If the subscription is still active with the provider, cancel it there too, or the customer will be charged again."}


class BlockIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


async def _target(user_id: str, admin: dict) -> dict:
    t = await db.users.find_one({"id": user_id})
    if not t:
        raise HTTPException(status_code=404, detail="No such user")
    if t["id"] == admin["id"] or is_platform_admin(t):
        raise HTTPException(status_code=409, detail="An administrator cannot be blocked from here.")
    return t


class PilotInviteIn(BaseModel):
    email: str = Field(min_length=5, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    send_email: bool = False


@router.get("/pilot/invites")
async def pilot_invites():
    """Every invitation with its state (open, used, revoked, expired). Codes are never shown again after creation."""
    return {"mode": "invite" if pilot.invite_only() else "open", "invites": await pilot.listing()}


@router.post("/pilot/invites", status_code=201)
async def pilot_invite_create(body: PilotInviteIn, admin: dict = Depends(require_platform_admin)):
    """Invite one email address. The code is returned ONCE here (and emailed if asked); only a hash is kept."""
    email = body.email.strip().lower()
    base = os.environ.get("APP_URL", "").rstrip("/")
    if body.send_email and not base.startswith("https://"):
        raise HTTPException(status_code=422, detail="Set APP_URL to the site's https address before emailing invitations: an email may only carry an https link. Nothing was created.")
    row, code = await pilot.create(email, admin["email"])
    link = f"{base}/login?mode=signup&invite={code}&email={email}"
    sent = False
    if body.send_email:
        from lib.outbound import send_logged

        await send_logged(to=email, subject="Your invitation to VIDHI", kind="pilot-invite", respect_suppression=False, html=pilot.invite_email_html(link))
        sent = True
    await audit(admin, "PILOT_INVITE_CREATED", detail=email)
    return {**row, "code": code, "link": link, "emailed": sent}


@router.delete("/pilot/invites/{invite_id}")
async def pilot_invite_revoke(invite_id: str, admin: dict = Depends(require_platform_admin)):
    if not await pilot.revoke(invite_id):
        raise HTTPException(status_code=404, detail="No open invitation with that id")
    await audit(admin, "PILOT_INVITE_REVOKED", detail=invite_id)
    return {"ok": True}


@router.post("/users/{user_id}/block")
async def block(user_id: str, body: BlockIn, admin: dict = Depends(require_platform_admin)):
    t = await _target(user_id, admin)
    await db.users.update_one({"id": user_id}, {"$set": {"blocked": {"at": now(), "by": admin["email"], "reason": body.reason.strip()}}})
    ended = (await db.sessions.delete_many({"user_id": user_id})).deleted_count  # they are signed out everywhere at once
    await audit(admin, "ADMIN_BLOCK", detail=f"{t['email']}: {body.reason.strip()[:200]}")
    return {"ok": True, "sessions_ended": ended}


@router.post("/users/{user_id}/unblock")
async def unblock(user_id: str, admin: dict = Depends(require_platform_admin)):
    t = await db.users.find_one({"id": user_id})
    if not t:
        raise HTTPException(status_code=404, detail="No such user")
    await db.users.update_one({"id": user_id}, {"$unset": {"blocked": ""}})
    await audit(admin, "ADMIN_UNBLOCK", detail=t["email"])
    return {"ok": True}


@router.get("/ai-spend")
async def ai_spend():
    recent = await db.ai_ledger.find({}, {"_id": 0}).sort("created_at", -1).limit(30).to_list(30)
    b = aibudget.get_budget()
    return {"budget": await b.status(), "reliability_30d": await b.reliability(), "recent_calls": recent}  # provider, task, tokens and cost only: never prompts or answers


class CapIn(BaseModel):
    cap_inr: float = Field(gt=0, le=10_000_000)


@router.post("/ai-spend/cap")
async def set_cap(body: CapIn, admin: dict = Depends(require_platform_admin)):
    """Change this month's cap (for example to raise it after checking the provider bills). The default for future months is AI_MONTHLY_CAP_INR."""
    b = aibudget.get_budget()
    await b._doc(b._mid())
    await b.spend.update_one({"_id": b._mid()}, {"$set": {"cap_override_inr": body.cap_inr}})
    await audit(admin, "ADMIN_AI_CAP", detail=f"{body.cap_inr:,.0f}")
    return await b.status()


@router.get("/support")
async def support(status: str = "OPEN"):
    rows = await db.support_tickets.find({"status": status} if status != "ALL" else {}, {"_id": 0}).sort("created_at", -1).limit(100).to_list(100)
    return {"tickets": [{**r, "reference": r["id"][:8]} for r in rows]}


class StatusIn(BaseModel):
    status: Literal["OPEN", "IN_PROGRESS", "CLOSED"]


@router.patch("/support/{ticket_id}")
async def set_support_status(ticket_id: str, body: StatusIn, admin: dict = Depends(require_platform_admin)):
    res = await db.support_tickets.update_one({"id": ticket_id}, {"$set": {"status": body.status, "updated_at": now()}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="No such ticket")
    await audit(admin, "ADMIN_SUPPORT_STATUS", detail=f"{ticket_id[:8]} -> {body.status}")
    return {"ok": True}


@router.get("/data-requests")
async def data_requests(status: str = "OPEN"):
    flt = {"status": {"$in": ["RECEIVED", "IN_PROGRESS"]}} if status == "OPEN" else ({} if status == "ALL" else {"status": status})
    rows = await db.data_requests.find(flt, {"_id": 0}).sort("created_at", 1).limit(200).to_list(200)
    return {"requests": rows, "response_days": business.response_days()}


class DataRequestIn(BaseModel):
    status: Literal["IN_PROGRESS", "COMPLETED", "REJECTED"]
    outcome: str = Field(default="", max_length=1000)


@router.patch("/data-requests/{request_id}")
async def update_data_request(request_id: str, body: DataRequestIn, admin: dict = Depends(require_platform_admin)):
    if body.status in ("COMPLETED", "REJECTED") and len(body.outcome.strip()) < 3:
        raise HTTPException(status_code=422, detail="Say what was done (or why it was refused) so the person can be told.")
    fields = {"status": body.status, "outcome": body.outcome.strip()}
    if body.status != "IN_PROGRESS":
        fields["closed_at"] = now()
    res = await db.data_requests.update_one({"id": request_id}, {"$set": fields, "$push": {"events": {"at": now(), "what": body.status, "by": admin["email"]}}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="No such request")
    await audit(admin, "ADMIN_DATA_REQUEST", detail=f"{request_id[:8]} -> {body.status}")
    return {"ok": True}


@router.get("/pilot/feedback")
async def pilot_feedback_list():
    """What pilot lawyers said: the results they marked wrong (reference text and the tool's label only), their feedback forms, and the thumbs-down on answers in pilot organisations."""
    rows = await db.pilot_feedback.find({}, {"_id": 0, "organization_id": 0}).sort("created_at", -1).limit(500).to_list(500)
    pilot_orgs = [o["id"] async for o in db.organizations.find({"pilot": True}, {"id": 1})]
    down = (
        await db.answer_feedback.find({"rating": "down", "organization_id": {"$in": pilot_orgs}}, {"_id": 0, "comment": 1, "created_at": 1}).sort("created_at", -1).limit(200).to_list(200)
        if pilot_orgs
        else []
    )
    return {
        "wrong_results": [r for r in rows if r["kind"] == "wrong_result"],
        "forms": [r for r in rows if r["kind"] == "form"],
        "answers_marked_down": down,
        "pilot_organisations": len(pilot_orgs),
    }


class EraseUserIn(BaseModel):
    confirm_email: str = Field(min_length=3, max_length=320)


@router.post("/users/{user_id}/erase")
async def erase_user(user_id: str, body: EraseUserIn, admin: dict = Depends(require_platform_admin)):
    """Carry out one person's erasure request. The operator types the person's email to confirm. The only owner of an organisation is refused (see lib.purge.purge_user)."""
    from lib.purge import CannotErase, purge_user

    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="No such person")
    if target["email"].strip().lower() != body.confirm_email.strip().lower():
        raise HTTPException(status_code=422, detail="Type the person's email exactly to confirm.")
    try:
        counts = await purge_user(user_id)
    except CannotErase as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await audit(admin, "ADMIN_ERASE_USER", detail=f"{user_id[:8]}")  # the id only: the person's name and email are not kept
    return {"erased": True, "counts": counts}


@router.get("/signals")
async def signals(hours: int = Query(24, ge=1, le=720)):
    """Things worth a look: counts of watched events, and who triggered them most. No content, only who and how often."""
    since = now() - timedelta(hours=hours)
    rows = await db.audit_events.aggregate([
        {"$match": {"operation": {"$in": list(WATCHLIST)}, "created_at": {"$gte": since}}},
        {"$group": {"_id": {"op": "$operation", "who": "$user_email"}, "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 100},
    ]).to_list(100)
    by_op: dict[str, dict] = {}
    for r in rows:
        d = by_op.setdefault(r["_id"]["op"], {"total": 0, "top": []})
        d["total"] += r["n"]
        if len(d["top"]) < 5:
            d["top"].append({"user": r["_id"]["who"], "count": r["n"]})
    return {"hours": hours, "signals": by_op, "blocked_users": await db.users.count_documents({"blocked": {"$exists": True}})}