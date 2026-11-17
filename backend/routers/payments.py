"""Pro is a MONTHLY Stripe subscription. The server owns the price; nothing the browser says can change it.

A first payment only counts when Stripe itself reports payment_status == "paid" AND the amount, currency and buyer
match what we recorded when the checkout was created. After that, Stripe's signed webhooks (invoice paid, payment
failed, subscription updated / deleted) keep the paid-until date current: we re-ask Stripe for the subscription
instead of trusting the event body, and Pro simply lapses when the date passes (lib/auth.entitlement_for).
"""

import base64
import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from lib.auth import audit, current_user, entitlement_for, now
from lib.branding import get_logo_bytes, logo_flowable
from lib.db import db
from lib.origins import is_allowed_origin
from lib.outbound import send_logged
from lib.payments_gateway import construct_event, enabled_providers, get_gateway, minor_units
from lib.paypal_gateway import verify_webhook as verify_paypal_webhook
from lib.razorpay_gateway import GatewayUnsupported, construct_event as construct_razorpay_event
from lib.ratelimit import CHECKOUT_LIMIT, EMAIL_LIMIT, ip_limit
from models.schemas import PaymentTransactionOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["payments"])

# Price and currency are configuration, never client input. Change the env vars to change the price
# (e.g. PRO_PRICE_AMOUNT=4999 PRO_PRICE_CURRENCY=inr for rupee pricing).
# The YEARLY plan exists only when its price is set (PRO_PRICE_YEARLY_AMOUNT, and PRO_PRICE_USD_YEARLY for PayPal): no price is ever invented here.
PACKAGE_CURRENCY = os.environ.get("PRO_PRICE_CURRENCY", "inr").lower()
PACKAGES: dict[str, float] = {"vidhi_pro": float(Decimal(os.environ.get("PRO_PRICE_AMOUNT", "1999")))}
PACKAGE_INTERVALS: dict[str, str] = {"vidhi_pro": "month"}
if (os.environ.get("PRO_PRICE_YEARLY_AMOUNT") or "").strip():
    PACKAGES["vidhi_pro_yearly"] = float(Decimal(os.environ["PRO_PRICE_YEARLY_AMOUNT"]))
    PACKAGE_INTERVALS["vidhi_pro_yearly"] = "year"
PACKAGE_INTERVAL = "month"  # the monthly plan (kept for older callers)


def price_for(provider: str, package_id: str) -> tuple[float, str] | None:
    """(amount, currency) the customer pays through this provider, or None if this provider does not offer the plan.
    Rupees through Stripe/Razorpay; PayPal bills in US dollars (PRO_PRICE_USD monthly, PRO_PRICE_USD_YEARLY yearly)."""
    if provider == "paypal":
        env = "PRO_PRICE_USD_YEARLY" if PACKAGE_INTERVALS.get(package_id) == "year" else "PRO_PRICE_USD"
        return (float(Decimal(os.environ[env])), "usd") if (os.environ.get(env) or "").strip() else None
    return PACKAGES[package_id], PACKAGE_CURRENCY


def interval_word(package_id: str | None) -> str:
    return "year" if PACKAGE_INTERVALS.get(package_id or "") == "year" else "month"
SYMBOL = {"usd": "$", "inr": "Rs ", "eur": "EUR ", "gbp": "GBP "}  # plain text: PDF base fonts have no rupee glyph


def money_text(amount: float, currency: str) -> str:
    c = (currency or "usd").lower()
    return f"{SYMBOL.get(c, c.upper() + ' ')}{amount:,.2f}" + ("" if c in SYMBOL else "")


@router.get("/payments/packages")
async def list_packages(user: dict = Depends(current_user)):
    return [
        {
            "id": pid, "amount": amt, "currency": PACKAGE_CURRENCY, "interval": PACKAGE_INTERVALS[pid], "providers": enabled_providers(),
            "prices": {p: dict(zip(("amount", "currency"), price_for(p, pid))) for p in enabled_providers() if price_for(p, pid)},
        }
        for pid, amt in PACKAGES.items()
    ]


class CheckoutIn(BaseModel):
    package_id: str
    origin_url: str
    provider: str | None = None  # "razorpay" (UPI, cards, netbanking) or "stripe" (international cards); default = the first enabled


def _mismatch(record: dict, st: dict) -> str | None:
    """Why a 'paid' session must NOT be accepted, or None if it matches what we expected."""
    if st.get("amount_total") != minor_units(record["amount"], record["currency"]):
        return "amount differs from the checkout we created"
    if (st.get("currency") or "").lower() != record["currency"].lower():
        return "currency differs from the checkout we created"
    if (st.get("metadata") or {}).get("user_id") != record.get("user_id"):
        return "buyer differs from the checkout we created"
    return None


async def _settle(record: dict) -> dict:
    """Ask the gateway (not the browser) whether this checkout is paid; upgrade the buyer exactly once."""
    session_id = record["session_id"]
    st = await get_gateway(record.get("provider")).retrieve(session_id)
    if st.get("payment_status") != "paid":
        return record
    problem = _mismatch(record, st)
    if problem:
        logger.error("payment %s reported paid but %s - NOT upgraded", session_id, problem)
        await db.payment_transactions.update_one(
            {"session_id": session_id}, {"$set": {"status": "needs_review", "review_reason": problem, "updated_at": now()}}
        )
        return await db.payment_transactions.find_one({"session_id": session_id}) or record
    await _mark_paid_and_upgrade(session_id, record, st)
    return await db.payment_transactions.find_one({"session_id": session_id}) or record


async def _mark_paid_and_upgrade(session_id: str, record: dict, st: dict) -> None:
    """Idempotent: flip the transaction to paid and unlock Pro exactly once."""
    res = await db.payment_transactions.update_one(
        {"session_id": session_id, "payment_status": {"$ne": "paid"}},
        {"$set": {"status": "completed", "payment_status": "paid", "updated_at": now()}},
    )
    if not res.modified_count:
        return
    if record.get("user_id"):
        fields: dict = {"plan": "PRO", "payment_provider": record.get("provider") or "stripe"}
        if st.get("subscription_id"):  # a subscription: Pro lasts to the end of the period that was paid for
            try:
                sub = await get_gateway(record.get("provider")).get_subscription(st["subscription_id"])
            except Exception:  # noqa: BLE001 - never lose a paid upgrade over a lookup failure; the webhook will refine it
                logger.warning("could not read subscription %s after payment", st["subscription_id"], exc_info=True)
                sub = {"status": "active", "current_period_end": now() + timedelta(days=31), "cancel_at_period_end": False, "customer_id": st.get("customer_id")}
            fields.update(
                subscription_id=st["subscription_id"], stripe_customer_id=st.get("customer_id") or sub.get("customer_id"),
                pro_until=sub.get("current_period_end") or now() + timedelta(days=31), subscription_status=sub.get("status"),
                cancel_at_period_end=bool(sub.get("cancel_at_period_end")),
            )
        await db.users.update_one({"id": record["user_id"]}, {"$set": fields})
    try:  # card brand + last four for the receipt (best effort)
        if st.get("payment_intent_id"):
            card = await get_gateway(record.get("provider")).card_details(st["payment_intent_id"])
            if card.get("brand") or card.get("last4"):
                await db.payment_transactions.update_one(
                    {"session_id": session_id}, {"$set": {"card_brand": card.get("brand"), "card_last4": card.get("last4")}}
                )
    except Exception:  # noqa: BLE001
        logger.info("could not read card details for receipt", exc_info=True)
    try:  # email the buyer their receipt (best effort, once)
        buyer = await db.users.find_one({"id": record.get("user_id")})
        rec = await db.payment_transactions.find_one({"session_id": session_id})
        if buyer and buyer.get("email") and rec:
            pdf = _receipt_pdf(rec, buyer, await get_logo_bytes(buyer["organization_id"]))
            await send_logged(
                to=buyer["email"],
                subject="Your VIDHI Pro receipt",
                html=_receipt_email_html(rec),
                kind="receipt",
                user=buyer,
                attachments=[{"filename": f"vidhi-receipt-{session_id[:8]}.pdf", "content": base64.b64encode(pdf).decode()}],
                respect_suppression=False,
            )
    except Exception:  # noqa: BLE001
        logger.info("receipt email failed", exc_info=True)


def _test_mode() -> bool:
    """True when payments run against Stripe test keys or the stub - the receipt then says so."""
    key = os.environ.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_API_KEY") or ""
    rzp = os.environ.get("RAZORPAY_KEY_ID") or ""
    return key.startswith("sk_test") or rzp.startswith("rzp_test") or os.environ.get("PAYMENTS_STUB", "false").lower() == "true"


def _receipt_email_html(r: dict) -> str:
    amt = money_text(r.get("amount", 0), r.get("currency", "usd"))
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;'
        'font-family:Arial,sans-serif;max-width:560px">'
        "<p>Thank you for subscribing to <strong>VIDHI Pro</strong>.</p>"
        f"<p>We have received your payment of {escape(amt)}. Your receipt is attached as a PDF. Pro renews every {interval_word(r.get('package_id'))} until "
        "you cancel it in Settings.</p>"
        "<p>Legal Intelligence — research, document analysis and citation verification — is now "
        "unlocked on your account.</p>"
        '<p style="font-size:12px;color:#888">Sent by VIDHI. We never ask for your password or '
        "card details by email.</p></td></tr></table>"
    )


@router.post("/payments/checkout", dependencies=[Depends(CHECKOUT_LIMIT)])
async def create_checkout(body: CheckoutIn, request: Request, user: dict = Depends(current_user)):
    if body.package_id not in PACKAGES:
        raise HTTPException(status_code=400, detail="Unknown package")
    if entitlement_for(user)["tier"] == "pro" and user.get("subscription_id") and user.get("subscription_status") not in ("canceled", "unpaid"):
        raise HTTPException(status_code=409, detail="Your organisation already has an active Pro subscription.")
    # The browser tells us where to return after paying; only our own origins are acceptable,
    # otherwise Stripe would redirect a buyer to an attacker-chosen site.
    if not is_allowed_origin(body.origin_url, extra=str(request.base_url)):
        raise HTTPException(status_code=400, detail="Unrecognised return address.")
    origin = body.origin_url.rstrip("/")
    providers = enabled_providers()
    provider = (body.provider or (providers[0] if providers else "stripe")).lower()
    if provider not in providers:
        raise HTTPException(status_code=400, detail="That payment method is not available.")
    offered = price_for(provider, body.package_id)
    if not offered:
        raise HTTPException(status_code=400, detail="That payment method does not offer this plan.")
    amount, currency = offered
    if provider == "razorpay" and currency != "inr":
        raise HTTPException(status_code=400, detail="That payment method is only available for rupee pricing.")
    try:
        session = await get_gateway(provider).create_checkout(
            amount=amount,
            currency=currency,
            name=f"VIDHI Pro - Legal Intelligence ({'yearly' if interval_word(body.package_id) == 'year' else 'monthly'})",
            recurring_interval=interval_word(body.package_id),
            customer_email=user["email"],
            success_url=f"{origin}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{origin}/payment/cancel",
            metadata={"user_id": user["id"], "package_id": body.package_id, "purpose": "vidhi_pro"},
            client_reference_id=user["id"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("could not create checkout session")
        raise HTTPException(status_code=502, detail="We could not start the payment. Please try again in a minute.") from exc
    await db.payment_transactions.insert_one(
        {
            "session_id": session["id"],
            "user_id": user["id"],
            "organization_id": user["organization_id"],
            "package_id": body.package_id,
            "interval": interval_word(body.package_id),
            "provider": provider,
            "amount": amount,
            "currency": currency,
            "status": "initiated",
            "payment_status": "pending",
            "created_at": now(),
            "updated_at": now(),
        }
    )
    await audit(user, "CHECKOUT_START", detail=body.package_id)
    return {"checkout_url": session["url"], "session_id": session["id"]}


@router.get("/payments/status/{session_id}", dependencies=[Depends(ip_limit("pay-status", 120, 60))])
async def payment_status(session_id: str):
    """Unauthenticated poll - returns only status fields; asks Stripe, upgrades the buyer on a verified 'paid'."""
    record = await db.payment_transactions.find_one({"session_id": session_id})
    if not record:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if record.get("payment_status") != "paid":
        try:
            record = await _settle(record)
        except Exception:  # noqa: BLE001 - transient gateway error; fall back to what we have stored
            logger.info("payment status check failed", exc_info=True)
    return {
        "session_id": record["session_id"],
        "status": record["status"],
        "payment_status": record["payment_status"],
    }


SUB_EVENTS = {"invoice.paid", "invoice.payment_failed", "customer.subscription.updated", "customer.subscription.deleted"}


def _event_subscription_id(event: dict) -> str | None:
    obj = event["data"]["object"]
    if event["type"].startswith("customer.subscription."):
        return obj.get("id")
    sub = obj.get("subscription") or ((obj.get("parent") or {}).get("subscription_details") or {}).get("subscription")
    return sub if isinstance(sub, str) else (sub or {}).get("id")


async def _sync_subscription(subscription_id: str) -> dict | None:
    """Copy Stripe's view of a subscription (status, paid-until, cancelling?) onto the buyer. Stripe is asked, not trusted."""
    buyer = await db.users.find_one({"subscription_id": subscription_id})
    if not buyer:
        return None
    sub = await get_gateway(buyer.get("payment_provider")).get_subscription(subscription_id)
    fields = {
        "subscription_status": sub.get("status"),
        "cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
        "stripe_customer_id": sub.get("customer_id") or buyer.get("stripe_customer_id"),
    }
    if sub.get("current_period_end"):
        fields["pro_until"] = sub["current_period_end"]
    await db.users.update_one({"id": buyer["id"]}, {"$set": fields})
    return {**buyer, **fields}


async def _package_of(buyer: dict) -> str:
    """The plan this buyer originally paid for (monthly or yearly), so a renewal is recorded and described the right way."""
    first = await db.payment_transactions.find_one({"user_id": buyer["id"], "payment_status": "paid", "renewal": {"$ne": True}}, sort=[("created_at", -1)])
    return (first or {}).get("package_id") or "vidhi_pro"


async def _record_renewal(event: dict, buyer: dict) -> None:
    """A renewal invoice that was paid: add it to the billing history (once) and email the receipt."""
    inv = event["data"]["object"]
    if inv.get("billing_reason") != "subscription_cycle" or not inv.get("id"):
        return
    if await db.payment_transactions.find_one({"session_id": inv["id"]}):
        return
    currency = (inv.get("currency") or PACKAGE_CURRENCY).lower()
    record = {
        "session_id": inv["id"], "user_id": buyer["id"], "organization_id": buyer["organization_id"], "package_id": await _package_of(buyer),
        "amount": Decimal(inv.get("amount_paid") or 0) / (1 if currency in ("jpy", "krw") else 100), "currency": currency,
        "status": "completed", "payment_status": "paid", "renewal": True, "created_at": now(), "updated_at": now(),
    }
    record["amount"] = float(record["amount"])
    record["provider"] = "stripe"
    await _store_renewal(record, buyer)


async def _store_renewal(record: dict, buyer: dict) -> None:
    """Add a renewal to the billing history and email its receipt (best effort)."""
    await db.payment_transactions.insert_one(dict(record))
    try:
        pdf = _receipt_pdf(record, buyer, await get_logo_bytes(buyer["organization_id"]))
        await send_logged(
            to=buyer["email"], subject="Your VIDHI Pro renewal receipt", html=_receipt_email_html(record), kind="receipt", user=buyer,
            attachments=[{"filename": f"vidhi-receipt-{record['session_id'][-8:]}.pdf", "content": base64.b64encode(pdf).decode()}],
            respect_suppression=False,
        )
    except Exception:  # noqa: BLE001
        logger.info("renewal receipt email failed", exc_info=True)


RZP_EVENTS = {
    "subscription.authenticated", "subscription.activated", "subscription.charged", "subscription.completed", "subscription.updated",
    "subscription.pending", "subscription.halted", "subscription.cancelled", "subscription.paused", "subscription.resumed",
}


PAYPAL_EVENTS = {
    "BILLING.SUBSCRIPTION.ACTIVATED", "BILLING.SUBSCRIPTION.CANCELLED", "BILLING.SUBSCRIPTION.SUSPENDED", "BILLING.SUBSCRIPTION.EXPIRED",
    "BILLING.SUBSCRIPTION.UPDATED", "BILLING.SUBSCRIPTION.PAYMENT.FAILED", "PAYMENT.SALE.COMPLETED",
}


@router.post("/webhook/paypal")
async def paypal_webhook(request: Request):
    """PayPal -> us. PayPal's own service confirms the signature; we then re-ask PayPal for the subscription's real state."""
    try:
        event = await verify_paypal_webhook(request.headers, await request.body())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook") from exc
    name, res = event.get("event_type", ""), event.get("resource") or {}
    if name not in PAYPAL_EVENTS:
        return {"status": "ok"}
    sub_id = res.get("billing_agreement_id") if name == "PAYMENT.SALE.COMPLETED" else res.get("id")
    if not sub_id:
        return {"status": "ok"}
    try:
        record = await db.payment_transactions.find_one({"session_id": sub_id})
        if record and record.get("payment_status") != "paid":
            await _settle(record)
        buyer = await _sync_subscription(sub_id)
        if buyer and name == "PAYMENT.SALE.COMPLETED" and res.get("id"):
            sub = await get_gateway("paypal").get_subscription(sub_id)
            if int(sub.get("cycles_completed") or 0) > 1 and not await db.payment_transactions.find_one({"session_id": res["id"]}):
                amt = res.get("amount") or {}
                await _store_renewal(
                    {
                        "session_id": res["id"], "user_id": buyer["id"], "organization_id": buyer["organization_id"], "package_id": await _package_of(buyer),
                        "provider": "paypal", "amount": float(Decimal(str(amt.get("total") or 0))), "currency": (amt.get("currency") or "usd").lower(),
                        "status": "completed", "payment_status": "paid", "renewal": True, "created_at": now(), "updated_at": now(),
                    },
                    buyer,
                )
    except Exception:  # noqa: BLE001
        logger.exception("paypal webhook failed for %s", sub_id)
        raise HTTPException(status_code=500, detail="Try again") from None  # PayPal retries
    return {"status": "ok"}


@router.post("/webhook/razorpay")
async def razorpay_webhook(request: Request):
    """Razorpay -> us. The signature is verified; we then re-ask Razorpay for the subscription's real state."""
    body = await request.body()
    try:
        event = construct_razorpay_event(body, request.headers.get("X-Razorpay-Signature"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook") from exc
    name = event.get("event", "")
    payload = event.get("payload") or {}
    sub = (payload.get("subscription") or {}).get("entity") or {}
    sub_id = sub.get("id")
    if name not in RZP_EVENTS or not sub_id:
        return {"status": "ok"}
    try:
        record = await db.payment_transactions.find_one({"session_id": sub_id})
        if record and record.get("payment_status") != "paid":
            await _settle(record)  # upgrades only if Razorpay itself reports a captured first charge that matches
        buyer = await _sync_subscription(sub_id)
        pay = (payload.get("payment") or {}).get("entity") or {}
        if buyer and name == "subscription.charged" and int(sub.get("paid_count") or 0) > 1 and pay.get("id"):
            if not await db.payment_transactions.find_one({"session_id": pay["id"]}):
                currency = (pay.get("currency") or PACKAGE_CURRENCY).lower()
                await _store_renewal(
                    {
                        "session_id": pay["id"], "user_id": buyer["id"], "organization_id": buyer["organization_id"], "package_id": await _package_of(buyer),
                        "provider": "razorpay", "amount": float(Decimal(pay.get("amount") or 0) / 100), "currency": currency,
                        "status": "completed", "payment_status": "paid", "renewal": True, "created_at": now(), "updated_at": now(),
                    },
                    buyer,
                )
    except Exception:  # noqa: BLE001
        logger.exception("razorpay webhook failed for %s", sub_id)
        raise HTTPException(status_code=500, detail="Try again") from None  # Razorpay retries
    return {"status": "ok"}


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Stripe -> us. The signature is verified; we then re-ask Stripe for the session's / subscription's real state."""
    body = await request.body()
    try:
        event = construct_event(body, request.headers.get("Stripe-Signature"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook") from exc
    if event["type"] in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        session_id = event["data"]["object"]["id"]
        record = await db.payment_transactions.find_one({"session_id": session_id})
        if record and record.get("payment_status") != "paid":
            try:
                await _settle(record)
            except Exception:  # noqa: BLE001
                logger.exception("webhook settle failed for %s", session_id)
                raise HTTPException(status_code=500, detail="Try again") from None  # Stripe will retry
    elif event["type"] in SUB_EVENTS:
        sub_id = _event_subscription_id(event)
        if sub_id:
            try:
                buyer = await _sync_subscription(sub_id)
                if buyer and event["type"] == "invoice.paid":
                    await _record_renewal(event, buyer)
            except Exception:  # noqa: BLE001
                logger.exception("subscription webhook failed for %s", sub_id)
                raise HTTPException(status_code=500, detail="Try again") from None
    return {"status": "ok"}


async def _owner_with_subscription(user: dict) -> dict:
    """The organisation's subscription is on its paying owner; only an owner may change it (policy: billing)."""
    row = await db.users.find_one({"id": user["id"]})
    if not row or not row.get("subscription_id"):
        raise HTTPException(status_code=409, detail="There is no active subscription to change.")
    return row


@router.post("/payments/subscription/cancel")
async def cancel_subscription(user: dict = Depends(current_user)):
    """Stop renewing. Pro stays until the end of the period already paid for."""
    row = await _owner_with_subscription(user)
    try:
        await get_gateway(row.get("payment_provider")).set_cancel_at_period_end(row["subscription_id"], True)
        updated = await _sync_subscription(row["subscription_id"])
    except Exception as exc:  # noqa: BLE001
        logger.exception("could not cancel subscription")
        raise HTTPException(status_code=502, detail="We could not cancel just now. Please try again in a minute.") from exc
    await audit(user, "SUBSCRIPTION_CANCEL")
    return {"ok": True, "pro_until": (updated or {}).get("pro_until"), "cancel_at_period_end": True}


@router.post("/payments/subscription/resume")
async def resume_subscription(user: dict = Depends(current_user)):
    """Undo a cancellation made earlier in the same period."""
    row = await _owner_with_subscription(user)
    try:
        await get_gateway(row.get("payment_provider")).set_cancel_at_period_end(row["subscription_id"], False)
        updated = await _sync_subscription(row["subscription_id"])
    except GatewayUnsupported as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("could not resume subscription")
        raise HTTPException(status_code=502, detail="We could not do that just now. Please try again in a minute.") from exc
    await audit(user, "SUBSCRIPTION_RESUME")
    return {"ok": True, "pro_until": (updated or {}).get("pro_until"), "cancel_at_period_end": False}

@router.get("/payments/history", response_model=list[PaymentTransactionOut])
async def payment_history(user: dict = Depends(current_user)):
    rows = (
        await db.payment_transactions.find({"user_id": user["id"]})
        .sort("created_at", -1)
        .to_list(100)
    )
    return [
        PaymentTransactionOut(
            session_id=r["session_id"],
            amount=r.get("amount", 0),
            currency=r.get("currency", "usd"),
            status=r.get("status", ""),
            payment_status=r.get("payment_status", ""),
            package_id=r.get("package_id", ""),
            card_brand=r.get("card_brand"),
            card_last4=r.get("card_last4"),
            created_at=r["created_at"],
        )
        for r in rows
    ]


def _receipt_pdf(r: dict, user: dict, logo_bytes: bytes | None = None) -> bytes:
    import io

    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Receipt", topMargin=2 * cm, bottomMargin=2 * cm)
    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=16, leading=20)
    b = ParagraphStyle("b", fontName="Helvetica", fontSize=11, leading=17)
    created = r.get("created_at")
    when = created.strftime("%d %b %Y, %H:%M UTC") if isinstance(created, datetime) else str(created)
    amt = money_text(r.get("amount", 0), r.get("currency", "usd"))
    card = ""
    if r.get("card_brand") and r.get("card_last4"):
        card = f"{str(r['card_brand']).upper()} ending {r['card_last4']}"
    firm = escape(user.get("organization_name", "") or "VIDHI client")
    brand = ParagraphStyle("brand", fontName="Helvetica-Bold", fontSize=20, leading=24)
    sub = ParagraphStyle("sub", fontName="Helvetica", fontSize=9, leading=12, textColor=HexColor("#888888"))
    rows = []
    _lf = logo_flowable(logo_bytes)
    if _lf is not None:
        rows += [_lf, Spacer(1, 10)]
    rows += [
        Paragraph(firm, brand),
        Paragraph("Receipt issued via VIDHI — Legal Intelligence", sub),
        Spacer(1, 14),
        Paragraph("Payment receipt", h),
        Spacer(1, 10),
        Paragraph(f"Billed to: {escape(user.get('full_name', ''))} ({escape(user.get('email', ''))})", b),
        Spacer(1, 10),
        Paragraph(f"Item: VIDHI Pro, Legal Intelligence - one {interval_word(r.get('package_id'))}" + (" (renewal)" if r.get("renewal") else ""), b),
        Paragraph(f"Amount paid: {amt}", b),
    ]
    if card:
        rows.append(Paragraph(f"Card: {escape(card)}", b))
    rows += [
        Paragraph(f"Status: {escape(r.get('payment_status', ''))}", b),
        Paragraph(f"Date: {escape(when)}", b),
        Paragraph(f"Transaction: {escape(r.get('session_id', ''))}", b),
        Spacer(1, 16),
        Paragraph("Thank you." + (" (Test-mode transaction.)" if _test_mode() else ""), b),
    ]
    doc.build(rows)
    return buf.getvalue()


@router.get("/payments/receipt/{session_id}.pdf")
async def payment_receipt(session_id: str, user: dict = Depends(current_user)):
    r = await db.payment_transactions.find_one({"session_id": session_id, "user_id": user["id"]})
    if not r:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if r.get("payment_status") != "paid":
        raise HTTPException(status_code=409, detail="Receipt is available once payment is confirmed.")
    pdf = _receipt_pdf(r, user, await get_logo_bytes(user["organization_id"]))
    await audit(user, "PAYMENT_RECEIPT", detail=session_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="vidhi-receipt-{session_id[:8]}.pdf"'},
    )


@router.post("/payments/receipt/{session_id}/email", dependencies=[Depends(EMAIL_LIMIT)])
async def email_receipt(session_id: str, user: dict = Depends(current_user)):
    """Re-send a past receipt (PDF) to the lawyer's own inbox."""
    r = await db.payment_transactions.find_one({"session_id": session_id, "user_id": user["id"]})
    if not r:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if r.get("payment_status") != "paid":
        raise HTTPException(status_code=409, detail="Receipt is available once payment is confirmed.")
    pdf = _receipt_pdf(r, user, await get_logo_bytes(user["organization_id"]))
    try:
        await send_logged(
            to=user["email"],
            subject="Your VIDHI Pro receipt",
            html=_receipt_email_html(r),
            kind="receipt",
            user=user,
            attachments=[
                {"filename": f"vidhi-receipt-{session_id[:8]}.pdf", "content": base64.b64encode(pdf).decode()}
            ],
            respect_suppression=False,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="We could not email the receipt. Try again.") from exc
    await audit(user, "PAYMENT_RECEIPT_EMAIL", detail=session_id)
    return {"ok": True, "sent_to": user["email"]}
