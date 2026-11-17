"""Razorpay (UPI, cards, netbanking, monthly auto-pay) through plain HTTPS calls to its REST API: no extra dependency.

Configuration: RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET (rzp_test_... / rzp_live_...) and RAZORPAY_WEBHOOK_SECRET (signs webhooks).
Pro is a Razorpay *subscription*: a plan (amount per month) plus a subscription the customer authorises on Razorpay's hosted page.
Razorpay cannot send the customer back to us afterwards, so the app learns that a payment happened by ASKING Razorpay (its signed
webhook, or the 'Check my payment' button) and never by trusting the browser.
"""

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

from lib.payments_gateway import minor_units

_TRANSPORT = None  # tests inject an httpx.MockTransport here
STATUS = {  # Razorpay subscription status -> the vocabulary the rest of the app uses (Stripe's)
    "created": "incomplete", "authenticated": "active", "active": "active", "pending": "past_due", "paused": "past_due",
    "halted": "unpaid", "cancelled": "canceled", "completed": "canceled", "expired": "canceled",
}


class GatewayUnsupported(Exception):
    """The provider cannot do this (Razorpay cannot undo a scheduled cancellation)."""


def _ts(ts) -> datetime | None:
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


class RazorpayGateway:
    def __init__(self) -> None:
        key, secret = os.environ.get("RAZORPAY_KEY_ID", ""), os.environ.get("RAZORPAY_KEY_SECRET", "")
        if not key or not secret:
            raise RuntimeError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not configured")
        self._auth = (key, secret)

    async def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        import httpx

        async with httpx.AsyncClient(base_url="https://api.razorpay.com/v1", auth=self._auth, timeout=20.0, transport=_TRANSPORT) as c:
            r = await c.request(method, path, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"Razorpay {method} {path} failed with {r.status_code}")
        return r.json()

    async def _plan_id(self, amount: float, currency: str, name: str, interval: str) -> str:
        from lib.db import db

        key = f"razorpay:{minor_units(amount, currency)}:{currency.lower()}:{interval}"
        row = await db.payment_plans.find_one({"key": key})
        if row:
            return row["plan_id"]
        plan = await self._call("POST", "/plans", {
            "period": "monthly" if interval == "month" else "yearly", "interval": 1,
            "item": {"name": name, "amount": minor_units(amount, currency), "currency": currency.upper()},
        })
        await db.payment_plans.update_one({"key": key}, {"$set": {"key": key, "plan_id": plan["id"]}}, upsert=True)
        return plan["id"]

    async def create_checkout(
        self, *, amount: float, currency: str, name: str, success_url: str, cancel_url: str, metadata: dict,
        client_reference_id: str, recurring_interval: str | None = None, customer_email: str | None = None,
    ) -> dict:
        plan_id = await self._plan_id(amount, currency, name, recurring_interval or "month")
        body: dict = {
            "plan_id": plan_id, "total_count": 120, "quantity": 1, "customer_notify": 1,
            "notes": {k: str(v) for k, v in {**metadata, "client_reference_id": client_reference_id}.items()},
        }
        if customer_email:
            body["notify_info"] = {"notify_email": customer_email}
        sub = await self._call("POST", "/subscriptions", body)
        return {"id": sub["id"], "url": sub["short_url"]}

    async def retrieve(self, session_id: str) -> dict:
        sub = await self._call("GET", f"/subscriptions/{session_id}")
        plan = await self._call("GET", f"/plans/{sub['plan_id']}")
        item = plan.get("item") or {}
        paid = sub.get("status") in ("active", "authenticated", "completed") and int(sub.get("paid_count") or 0) >= 1
        return {
            "id": session_id, "payment_status": "paid" if paid else "unpaid", "status": "complete" if paid else "open",
            "amount_total": item.get("amount"), "currency": (item.get("currency") or "").lower(),
            "metadata": dict(sub.get("notes") or {}), "payment_intent_id": None,
            "subscription_id": sub["id"], "customer_id": sub.get("customer_id"),
        }

    async def get_subscription(self, subscription_id: str) -> dict:
        sub = await self._call("GET", f"/subscriptions/{subscription_id}")
        return {
            "id": sub["id"], "status": STATUS.get(sub.get("status"), "incomplete"), "current_period_end": _ts(sub.get("current_end")),
            "cancel_at_period_end": bool(sub.get("has_scheduled_changes")) or sub.get("status") == "cancelled",
            "customer_id": sub.get("customer_id"),
        }

    async def set_cancel_at_period_end(self, subscription_id: str, cancel: bool) -> None:
        if not cancel:
            raise GatewayUnsupported("Razorpay cannot undo a cancellation. Subscribe again after Pro ends.")
        await self._call("POST", f"/subscriptions/{subscription_id}/cancel", {"cancel_at_cycle_end": 1})

    async def card_details(self, payment_intent_id: str) -> dict:
        return {"brand": None, "last4": None}


def construct_event(payload: bytes, signature: str | None) -> dict:
    """Razorpay signs the raw body with HMAC-SHA256 (hex) using the webhook secret. Raises ValueError if not authentic."""
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret or not signature:
        raise ValueError("webhook not configured or unsigned")
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.strip()):
        raise ValueError("invalid webhook")
    try:
        return json.loads(payload)
    except ValueError as exc:
        raise ValueError("invalid webhook") from exc
