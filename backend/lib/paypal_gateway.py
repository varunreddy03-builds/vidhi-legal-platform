"""PayPal subscriptions for customers outside India (US dollars). Plain HTTPS calls to PayPal's REST API: no extra dependency.

Configuration: PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_WEBHOOK_ID (from the webhook you create in the PayPal developer dashboard),
PAYPAL_ENV=sandbox|live (default sandbox), and PRO_PRICE_USD (the monthly dollar price; PayPal is offered only when it is set).
After approving, PayPal sends the customer back to us with ?subscription_id=...; the app still ASKS PayPal whether the first payment
was taken and never trusts the browser. PayPal cancels at once, so a cancelled customer keeps Pro until the end of the month already paid."""

import hmac
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from lib.payments_gateway import minor_units, stub_enabled
from lib.razorpay_gateway import GatewayUnsupported

_TRANSPORT = None  # tests inject an httpx.MockTransport here
_TOKEN: dict = {"value": None, "until": 0.0}
STATUS = {"ACTIVE": "active", "APPROVAL_PENDING": "incomplete", "APPROVED": "incomplete", "SUSPENDED": "past_due", "CANCELLED": "canceled", "EXPIRED": "canceled"}


def configured() -> bool:
    return bool(os.environ.get("PAYPAL_CLIENT_ID") and os.environ.get("PAYPAL_CLIENT_SECRET") and os.environ.get("PRO_PRICE_USD"))


def base_url() -> str:
    return "https://api-m.paypal.com" if os.environ.get("PAYPAL_ENV", "sandbox").lower() == "live" else "https://api-m.sandbox.paypal.com"


def _when(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class PayPalGateway:
    def __init__(self) -> None:
        if not (os.environ.get("PAYPAL_CLIENT_ID") and os.environ.get("PAYPAL_CLIENT_SECRET")):
            raise RuntimeError("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not configured")

    async def _token(self, c) -> str:
        if _TOKEN["value"] and _TOKEN["until"] > time.time() + 30:
            return _TOKEN["value"]
        r = await c.post("/v1/oauth2/token", data={"grant_type": "client_credentials"}, auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]))
        if r.status_code >= 400:
            raise RuntimeError(f"PayPal sign-in failed with {r.status_code}")
        j = r.json()
        _TOKEN.update(value=j["access_token"], until=time.time() + int(j.get("expires_in", 300)))
        return j["access_token"]

    async def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        import httpx

        async with httpx.AsyncClient(base_url=base_url(), timeout=25.0, transport=_TRANSPORT) as c:
            token = await self._token(c)
            r = await c.request(method, path, json=body, headers={"Authorization": f"Bearer {token}", "PayPal-Request-Id": uuid.uuid4().hex})
        if r.status_code >= 400:
            raise RuntimeError(f"PayPal {method} {path} failed with {r.status_code}")
        return r.json() if r.content else {}

    async def _plan_id(self, amount: float, currency: str, name: str, interval: str) -> str:
        from lib.db import db

        key = f"paypal:{minor_units(amount, currency)}:{currency.lower()}:{interval}"
        row = await db.payment_plans.find_one({"key": key})
        if row:
            return row["plan_id"]
        product = await self._call("POST", "/v1/catalogs/products", {"name": name, "type": "SERVICE", "category": "SOFTWARE"})
        plan = await self._call("POST", "/v1/billing/plans", {
            "product_id": product["id"], "name": name, "status": "ACTIVE",
            "billing_cycles": [{
                "frequency": {"interval_unit": "MONTH" if interval == "month" else "YEAR", "interval_count": 1}, "tenure_type": "REGULAR", "sequence": 1, "total_cycles": 0,
                "pricing_scheme": {"fixed_price": {"value": f"{Decimal(str(amount)):.2f}", "currency_code": currency.upper()}},
            }],
            "payment_preferences": {"auto_bill_outstanding": True, "setup_fee_failure_action": "CANCEL", "payment_failure_threshold": 3},
        })
        await db.payment_plans.update_one({"key": key}, {"$set": {"key": key, "plan_id": plan["id"]}}, upsert=True)
        return plan["id"]

    async def create_checkout(
        self, *, amount: float, currency: str, name: str, success_url: str, cancel_url: str, metadata: dict,
        client_reference_id: str, recurring_interval: str | None = None, customer_email: str | None = None,
    ) -> dict:
        plan_id = await self._plan_id(amount, currency, name, recurring_interval or "month")
        body: dict = {
            "plan_id": plan_id, "custom_id": str(metadata.get("user_id", client_reference_id))[:127],
            "application_context": {
                "brand_name": "VIDHI", "user_action": "SUBSCRIBE_NOW", "shipping_preference": "NO_SHIPPING",
                "return_url": success_url.replace("?session_id={CHECKOUT_SESSION_ID}", "?provider=paypal"), "cancel_url": cancel_url,
            },
        }
        if customer_email:
            body["subscriber"] = {"email_address": customer_email}
        sub = await self._call("POST", "/v1/billing/subscriptions", body)
        approve = next((link["href"] for link in sub.get("links", []) if link.get("rel") == "approve"), None)
        if not approve:
            raise RuntimeError("PayPal gave no approval link")
        return {"id": sub["id"], "url": approve}

    async def retrieve(self, session_id: str) -> dict:
        sub = await self._call("GET", f"/v1/billing/subscriptions/{session_id}")
        last = (sub.get("billing_info") or {}).get("last_payment") or {}
        amount = last.get("amount") or {}
        paid = sub.get("status") == "ACTIVE" and bool(last.get("time")) and bool(amount.get("value"))
        return {
            "id": session_id, "payment_status": "paid" if paid else "unpaid", "status": "complete" if paid else "open",
            "amount_total": minor_units(Decimal(amount["value"]), amount.get("currency_code", "USD")) if amount.get("value") else None,
            "currency": (amount.get("currency_code") or "").lower(), "metadata": {"user_id": sub.get("custom_id")}, "payment_intent_id": None,
            "subscription_id": sub["id"], "customer_id": (sub.get("subscriber") or {}).get("payer_id"),
        }

    async def get_subscription(self, subscription_id: str) -> dict:
        sub = await self._call("GET", f"/v1/billing/subscriptions/{subscription_id}")
        info = sub.get("billing_info") or {}
        done = max([int(x.get("cycles_completed") or 0) for x in info.get("cycle_executions", []) if x.get("tenure_type") == "REGULAR"] or [0])
        return {
            "id": sub["id"], "status": STATUS.get(sub.get("status"), "incomplete"), "current_period_end": _when(info.get("next_billing_time")),
            "cancel_at_period_end": sub.get("status") == "CANCELLED", "customer_id": (sub.get("subscriber") or {}).get("payer_id"), "cycles_completed": done,
        }

    async def set_cancel_at_period_end(self, subscription_id: str, cancel: bool) -> None:
        if not cancel:
            raise GatewayUnsupported("PayPal cannot undo a cancellation. Subscribe again after Pro ends.")
        await self._call("POST", f"/v1/billing/subscriptions/{subscription_id}/cancel", {"reason": "Cancelled by the customer"})

    async def card_details(self, payment_intent_id: str) -> dict:
        return {"brand": None, "last4": None}


async def verify_webhook(headers, body: bytes) -> dict:
    """PayPal's own service confirms the signature (it needs PAYPAL_WEBHOOK_ID). Raises ValueError unless authentic; returns the event."""
    try:
        event = json.loads(body)
    except ValueError as exc:
        raise ValueError("bad payload") from exc
    webhook_id = os.environ.get("PAYPAL_WEBHOOK_ID", "")
    sig = headers.get("PAYPAL-TRANSMISSION-SIG")
    if not webhook_id or not sig:
        raise ValueError("webhook not configured or unsigned")
    if stub_enabled():  # tests/dev only: an HMAC with the webhook id plays PayPal's verification service
        if not hmac.compare_digest(hmac.new(webhook_id.encode(), body, hashlib.sha256).hexdigest(), sig):
            raise ValueError("invalid webhook")
        return event
    try:
        out = await PayPalGateway()._call("POST", "/v1/notifications/verify-webhook-signature", {
            "auth_algo": headers.get("PAYPAL-AUTH-ALGO"), "cert_url": headers.get("PAYPAL-CERT-URL"), "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID"),
            "transmission_sig": sig, "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME"), "webhook_id": webhook_id, "webhook_event": event,
        })
    except Exception as exc:  # noqa: BLE001
        raise ValueError("could not verify") from exc
    if out.get("verification_status") != "SUCCESS":
        raise ValueError("invalid webhook")
    return event