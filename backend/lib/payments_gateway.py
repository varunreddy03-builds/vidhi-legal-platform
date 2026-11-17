"""Payments through the official Stripe SDK (no third-party wrapper).

Configuration (environment):
  STRIPE_SECRET_KEY       secret API key (sk_test_... / sk_live_...). STRIPE_API_KEY is accepted as an alias.
  STRIPE_WEBHOOK_SECRET   signing secret of the webhook endpoint (whsec_...). Without it webhooks are rejected.
  PAYMENTS_STUB=true      TESTS/DEV ONLY: a fake gateway whose sessions are marked paid through the database.

The price itself lives in lib/plans.py (PRO_PRICE_AMOUNT / PRO_PRICE_CURRENCY); Pro is a MONTHLY subscription.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

ZERO_DECIMAL = {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"}


def minor_units(amount: float | Decimal, currency: str) -> int:
    """Stripe amounts are in the smallest unit: paise for INR, cents for USD."""
    d = Decimal(str(amount))
    if currency.lower() in ZERO_DECIMAL:
        return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return int((d * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def stub_enabled() -> bool:
    return os.environ.get("PAYMENTS_STUB", "false").lower() == "true"


def _secret_key() -> str:
    key = os.environ.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_API_KEY")
    if not key or "emergent" in key.lower():  # a leftover key from the old platform must never be used
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    return key


def _plain(obj):
    """The Stripe SDK returns objects that are NOT dicts (no .get). Everything below works on plain dicts."""
    return obj.to_dict() if hasattr(obj, "to_dict") else obj


def _id_of(value) -> str | None:
    """Stripe returns a related object either as an id string or, when expanded, as an object."""
    if not value:
        return None
    return value if isinstance(value, str) else value.get("id")


def _period_end(sub) -> datetime | None:
    """Newer API versions keep the billing period on the subscription item, older ones on the subscription."""
    ts = sub.get("current_period_end")
    if not ts:
        items = (sub.get("items") or {}).get("data") or []
        ts = items[0].get("current_period_end") if items else None
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


class StripeGateway:
    def __init__(self) -> None:
        import stripe

        self.client = stripe.StripeClient(_secret_key())

    async def create_checkout(
        self, *, amount: float, currency: str, name: str, success_url: str, cancel_url: str, metadata: dict,
        client_reference_id: str, recurring_interval: str | None = None, customer_email: str | None = None,
    ) -> dict:
        price_data: dict = {
            "currency": currency.lower(),
            "unit_amount": minor_units(amount, currency),
            "product_data": {"name": name},
        }
        params: dict = {
            "line_items": [{"quantity": 1, "price_data": price_data}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": client_reference_id,
            "metadata": metadata,
        }
        if recurring_interval:  # a subscription: renews every period until the customer cancels
            price_data["recurring"] = {"interval": recurring_interval}
            params["mode"] = "subscription"
            params["subscription_data"] = {"metadata": metadata}
        else:
            params["mode"] = "payment"
            params["payment_intent_data"] = {"metadata": metadata}
        if customer_email:
            params["customer_email"] = customer_email
        s = await self.client.v1.checkout.sessions.create_async(params=params)
        return {"id": s["id"], "url": s["url"]}

    async def retrieve(self, session_id: str) -> dict:
        s = _plain(await self.client.v1.checkout.sessions.retrieve_async(session_id))
        return {
            "id": s["id"],
            "payment_status": s.get("payment_status"),
            "status": s.get("status"),
            "amount_total": s.get("amount_total"),
            "currency": (s.get("currency") or "").lower(),
            "metadata": dict(s.get("metadata") or {}),
            "payment_intent_id": _id_of(s.get("payment_intent")),
            "subscription_id": _id_of(s.get("subscription")),
            "customer_id": _id_of(s.get("customer")),
        }

    async def get_subscription(self, subscription_id: str) -> dict:
        sub = _plain(await self.client.v1.subscriptions.retrieve_async(subscription_id))
        return {
            "id": sub["id"],
            "status": sub.get("status"),
            "current_period_end": _period_end(sub),
            "cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
            "customer_id": _id_of(sub.get("customer")),
        }

    async def set_cancel_at_period_end(self, subscription_id: str, cancel: bool) -> None:
        await self.client.v1.subscriptions.update_async(subscription_id, params={"cancel_at_period_end": cancel})

    async def card_details(self, payment_intent_id: str) -> dict:
        """Brand + last four of the card for the receipt (best effort)."""
        pi = _plain(await self.client.v1.payment_intents.retrieve_async(payment_intent_id, params={"expand": ["latest_charge"]}))
        charge = pi.get("latest_charge") or {}
        card = (charge.get("payment_method_details") or {}).get("card") or {}
        return {"brand": card.get("brand"), "last4": card.get("last4")}


class StubGateway:
    """A fake gateway for tests/dev. A test marks a session paid by inserting into `payment_stub`, and controls a
    subscription's state through `subscription_stub`."""

    async def create_checkout(
        self, *, amount, currency, name, success_url, cancel_url, metadata, client_reference_id,
        recurring_interval=None, customer_email=None,
    ) -> dict:
        sid = f"cs_stub_{uuid.uuid4().hex[:24]}"
        return {"id": sid, "url": success_url.replace("{CHECKOUT_SESSION_ID}", sid)}

    async def retrieve(self, session_id: str) -> dict:
        from lib.db import db

        row = await db.payment_stub.find_one({"session_id": session_id})
        if not row:
            return {"id": session_id, "payment_status": "unpaid", "status": "open", "amount_total": None, "currency": "",
                    "metadata": {}, "payment_intent_id": None, "subscription_id": None, "customer_id": None}
        return {
            "id": session_id,
            "payment_status": row.get("payment_status", "paid"),
            "status": "complete",
            "amount_total": row.get("amount_total"),
            "currency": row.get("currency", ""),
            "metadata": row.get("metadata", {}),
            "payment_intent_id": None,
            "subscription_id": row.get("subscription_id"),
            "customer_id": row.get("customer_id", "cus_stub" if row.get("subscription_id") else None),
        }

    async def get_subscription(self, subscription_id: str) -> dict:
        from lib.db import db

        row = await db.subscription_stub.find_one({"id": subscription_id})
        if not row:
            return {"id": subscription_id, "status": "active", "current_period_end": datetime.now(timezone.utc) + timedelta(days=30),
                    "cancel_at_period_end": False, "customer_id": "cus_stub", "cycles_completed": 1}
        end = row.get("current_period_end")
        return {"id": subscription_id, "status": row.get("status", "active"), "current_period_end": end,
                "cancel_at_period_end": bool(row.get("cancel_at_period_end")), "customer_id": row.get("customer_id", "cus_stub"),
                "cycles_completed": row.get("cycles_completed", 1)}

    async def set_cancel_at_period_end(self, subscription_id: str, cancel: bool) -> None:
        from lib.db import db

        await db.subscription_stub.update_one({"id": subscription_id}, {"$set": {"cancel_at_period_end": cancel}}, upsert=True)

    async def card_details(self, payment_intent_id: str) -> dict:
        return {"brand": None, "last4": None}


def enabled_providers() -> list[str]:
    """Providers customers may pay with; the first is the default. PAYMENT_PROVIDERS can restrict/reorder ("razorpay,stripe")."""
    listed = [x.strip().lower() for x in os.environ.get("PAYMENT_PROVIDERS", "").split(",") if x.strip()]
    if stub_enabled():
        return [x for x in listed if x in ("razorpay", "stripe", "paypal")] or ["stripe", "razorpay", "paypal"]
    found = []
    if os.environ.get("RAZORPAY_KEY_ID") and os.environ.get("RAZORPAY_KEY_SECRET"):
        found.append("razorpay")
    if os.environ.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_API_KEY"):
        found.append("stripe")
    from lib.paypal_gateway import configured as paypal_configured

    if paypal_configured():
        found.append("paypal")
    return [x for x in listed if x in found] if listed else found


def get_gateway(provider: str | None = None):
    if stub_enabled():
        return StubGateway()
    if (provider or "stripe") == "razorpay":
        from lib.razorpay_gateway import RazorpayGateway

        return RazorpayGateway()
    if provider == "paypal":
        from lib.paypal_gateway import PayPalGateway

        return PayPalGateway()
    return StripeGateway()


def construct_event(payload: bytes, signature: str | None) -> dict:
    """Verify Stripe's signature and return the event. Raises ValueError for anything not authentic."""
    import stripe

    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret or not signature:
        raise ValueError("webhook not configured or unsigned")
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
        return event.to_dict() if hasattr(event, "to_dict") else event  # plain dicts: .get() and nested lookups just work
    except Exception as exc:  # noqa: BLE001 - SignatureVerificationError, bad JSON, stale timestamp...
        raise ValueError("invalid webhook") from exc
