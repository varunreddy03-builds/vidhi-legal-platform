"""PayPal subscriptions (US dollars) next to Stripe and Razorpay: same safety rules, PayPal-verified webhook."""

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from lib import paypal_gateway as pg
from lib import payments_gateway as pgw
from tests.conftest import API_URL, mark_stub_paid, mongo, set_plan

WEBHOOK_ID = "paypal-test-webhook-id"


def run(c):
    return asyncio.run(c)


class Recorder:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = None
        if request.content:
            body = dict(httpx.QueryParams(request.content.decode())) if request.url.path.endswith("/token") else json.loads(request.content)
        self.calls.append((request.method, request.url.path, body))
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 300})
        return httpx.Response(200, json=self.replies[(request.method, request.url.path)])


@pytest.fixture
def paypal(monkeypatch):
    def make(replies):
        rec = Recorder(replies)
        monkeypatch.setattr(pg, "_TRANSPORT", httpx.MockTransport(rec))
        monkeypatch.setitem(pg._TOKEN, "value", None)
        monkeypatch.setenv("PAYPAL_CLIENT_ID", "cid")
        monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "sec")
        monkeypatch.setenv("PAYPAL_ENV", "sandbox")

        async def plan_id(self, *a, **k):
            return "P-PLAN"

        monkeypatch.setattr(pg.PayPalGateway, "_plan_id", plan_id)
        return rec, pg.PayPalGateway()

    return make


def test_the_customer_is_sent_to_paypals_approval_page(paypal):
    rec, gw = paypal({("POST", "/v1/billing/subscriptions"): {"id": "I-ABC", "links": [{"rel": "self", "href": "x"}, {"rel": "approve", "href": "https://www.sandbox.paypal.com/webapps/billing/subscriptions?ba_token=BA-1"}]}})
    out = run(gw.create_checkout(
        amount=24, currency="usd", name="VIDHI Pro", success_url="https://app.example.in/payment/success?session_id={CHECKOUT_SESSION_ID}",
        cancel_url="https://app.example.in/payment/cancel", metadata={"user_id": "u1"}, client_reference_id="u1", recurring_interval="month", customer_email="a@example.com",
    ))
    assert out == {"id": "I-ABC", "url": "https://www.sandbox.paypal.com/webapps/billing/subscriptions?ba_token=BA-1"}
    sent = rec.calls[-1][2]
    assert sent["plan_id"] == "P-PLAN" and sent["custom_id"] == "u1" and sent["subscriber"] == {"email_address": "a@example.com"}
    assert sent["application_context"]["return_url"] == "https://app.example.in/payment/success?provider=paypal"
    assert "{CHECKOUT_SESSION_ID}" not in json.dumps(sent)


def test_paid_means_active_with_a_captured_payment(paypal):
    sub = {"id": "I-ABC", "status": "APPROVAL_PENDING", "custom_id": "u1", "subscriber": {"payer_id": "PAYER1"}, "billing_info": {}}
    rec, gw = paypal({("GET", "/v1/billing/subscriptions/I-ABC"): sub})
    assert run(gw.retrieve("I-ABC"))["payment_status"] == "unpaid"
    sub.update(status="ACTIVE", billing_info={"last_payment": {"amount": {"currency_code": "USD", "value": "24.00"}, "time": "2026-10-20T10:00:00Z"}})
    st = run(gw.retrieve("I-ABC"))
    assert st["payment_status"] == "paid" and st["amount_total"] == 2400 and st["currency"] == "usd" and st["metadata"] == {"user_id": "u1"}
    sub["billing_info"] = {}
    assert run(gw.retrieve("I-ABC"))["payment_status"] == "unpaid"  # active but nothing captured yet


def test_subscription_state_is_translated(paypal):
    sub = {"id": "I-ABC", "status": "ACTIVE", "billing_info": {"next_billing_time": "2026-11-20T10:00:00Z", "cycle_executions": [{"tenure_type": "REGULAR", "cycles_completed": 2}]}}
    rec, gw = paypal({("GET", "/v1/billing/subscriptions/I-ABC"): sub})
    s = run(gw.get_subscription("I-ABC"))
    assert s["status"] == "active" and s["cycles_completed"] == 2 and s["current_period_end"] == datetime(2026, 11, 20, 10, tzinfo=timezone.utc) and not s["cancel_at_period_end"]
    for theirs, ours in (("SUSPENDED", "past_due"), ("CANCELLED", "canceled"), ("EXPIRED", "canceled"), ("APPROVED", "incomplete")):
        sub["status"] = theirs
        assert run(gw.get_subscription("I-ABC"))["status"] == ours
    assert run(gw.get_subscription("I-ABC"))["cancel_at_period_end"] is False
    sub["status"] = "CANCELLED"
    assert run(gw.get_subscription("I-ABC"))["cancel_at_period_end"] is True


def test_cancelling_works_and_cannot_be_undone(paypal):
    rec, gw = paypal({("POST", "/v1/billing/subscriptions/I-ABC/cancel"): {}})
    run(gw.set_cancel_at_period_end("I-ABC", True))
    assert rec.calls[-1][0:2] == ("POST", "/v1/billing/subscriptions/I-ABC/cancel")
    with pytest.raises(pg.GatewayUnsupported):
        run(gw.set_cancel_at_period_end("I-ABC", False))


def test_paypal_is_offered_only_with_keys_and_a_dollar_price(monkeypatch):
    monkeypatch.setenv("PAYMENTS_STUB", "false")
    for k in ("RAZORPAY_KEY_ID", "STRIPE_SECRET_KEY", "STRIPE_API_KEY", "PAYMENT_PROVIDERS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "c")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "s")
    monkeypatch.delenv("PRO_PRICE_USD", raising=False)
    assert pgw.enabled_providers() == []
    monkeypatch.setenv("PRO_PRICE_USD", "24")
    assert pgw.enabled_providers() == ["paypal"]


def test_the_webhook_is_verified_by_paypals_own_service(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"verification_status": seen.get("answer", "SUCCESS")})

    monkeypatch.setattr(pg, "_TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setitem(pg._TOKEN, "value", None)
    monkeypatch.setenv("PAYMENTS_STUB", "false")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-1")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "c")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "s")
    headers = {"PAYPAL-TRANSMISSION-SIG": "sig", "PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://api.paypal.com/cert", "PAYPAL-TRANSMISSION-ID": "tid", "PAYPAL-TRANSMISSION-TIME": "2026-10-20T10:00:00Z"}
    ev = run(pg.verify_webhook(headers, b'{"event_type":"BILLING.SUBSCRIPTION.ACTIVATED","resource":{"id":"I-1"}}'))
    assert ev["resource"]["id"] == "I-1" and seen["body"]["webhook_id"] == "WH-1" and seen["body"]["transmission_sig"] == "sig"
    seen["answer"] = "FAILURE"
    with pytest.raises(ValueError):
        run(pg.verify_webhook(headers, b"{}"))
    with pytest.raises(ValueError):
        run(pg.verify_webhook({}, b"{}"))  # unsigned


# ---- through the app (the stub plays PayPal) ----
def sign(body: bytes, key: str = WEBHOOK_ID) -> dict:
    return {"PAYPAL-TRANSMISSION-SIG": hmac.new(key.encode(), body, hashlib.sha256).hexdigest(), "Content-Type": "application/json"}


def checkout(c):
    set_plan(c, "FREE")
    return c.post("/payments/checkout", json={"package_id": "vidhi_pro", "origin_url": "http://localhost:3000", "provider": "paypal"})


def pay(c, cycles=1):
    r = checkout(c)
    assert r.status_code == 200, r.text
    sub_id = "I-" + uuid.uuid4().hex[:12].upper()
    mongo().payment_transactions.update_one({"session_id": r.json()["session_id"]}, {"$set": {"session_id": sub_id}})
    mongo().subscription_stub.insert_one({"id": sub_id, "status": "active", "current_period_end": datetime.now(timezone.utc) + timedelta(days=30), "cancel_at_period_end": False, "cycles_completed": cycles})
    mark_stub_paid(sub_id, amount_total=2400, currency="usd", user_id=c.user["id"], subscription_id=sub_id)
    return sub_id


def test_a_paypal_checkout_is_priced_in_dollars_by_the_server(user_a):
    r = checkout(user_a)
    row = mongo().payment_transactions.find_one({"session_id": r.json()["session_id"]})
    assert row["provider"] == "paypal" and row["amount"] == 24.0 and row["currency"] == "usd"


def test_a_paypal_payment_unlocks_pro(user_a):
    sub_id = pay(user_a)
    assert user_a.get(f"/payments/status/{sub_id}").json()["payment_status"] == "paid"
    row = mongo().users.find_one({"id": user_a.user["id"]})
    assert row["plan"] == "PRO" and row["payment_provider"] == "paypal" and row["subscription_id"] == sub_id


def test_the_amount_and_currency_are_checked(user_a):
    r = checkout(user_a)
    sid = r.json()["session_id"]
    mark_stub_paid(sid, amount_total=2400, currency="inr", user_id=user_a.user["id"], subscription_id="I-CHEAP")  # right number, wrong currency
    assert user_a.get(f"/payments/status/{sid}").json()["status"] == "needs_review"
    assert mongo().users.find_one({"id": user_a.user["id"]})["plan"] == "FREE"


def event(name: str, resource: dict) -> bytes:
    return json.dumps({"event_type": name, "resource": resource}).encode()


def post(body, headers):
    return httpx.post(f"{API_URL}/webhook/paypal", content=body, headers=headers, timeout=30)


def test_the_webhook_must_be_verified():
    body = event("BILLING.SUBSCRIPTION.ACTIVATED", {"id": "I-X"})
    assert post(body, {}).status_code == 400
    assert post(body, sign(body, "forged")).status_code == 400
    assert post(body, sign(body)).status_code == 200


def test_the_webhook_settles_a_payment_the_browser_never_reported(user_a):
    sub_id = pay(user_a)
    body = event("BILLING.SUBSCRIPTION.ACTIVATED", {"id": sub_id})
    assert post(body, sign(body)).status_code == 200
    assert mongo().users.find_one({"id": user_a.user["id"]})["plan"] == "PRO"


def test_a_renewal_is_recorded_once_and_the_first_payment_is_not_a_renewal(user_a):
    sub_id = pay(user_a, cycles=1)
    user_a.get(f"/payments/status/{sub_id}")
    first = "SALE" + uuid.uuid4().hex[:8]
    body = event("PAYMENT.SALE.COMPLETED", {"id": first, "billing_agreement_id": sub_id, "amount": {"total": "24.00", "currency": "USD"}})
    assert post(body, sign(body)).status_code == 200
    assert mongo().payment_transactions.count_documents({"session_id": first}) == 0
    mongo().subscription_stub.update_one({"id": sub_id}, {"$set": {"cycles_completed": 2}})
    again = "SALE" + uuid.uuid4().hex[:8]
    body = event("PAYMENT.SALE.COMPLETED", {"id": again, "billing_agreement_id": sub_id, "amount": {"total": "24.00", "currency": "USD"}})
    for _ in range(2):
        assert post(body, sign(body)).status_code == 200
    rows = list(mongo().payment_transactions.find({"session_id": again}))
    assert len(rows) == 1 and rows[0]["renewal"] and rows[0]["provider"] == "paypal" and rows[0]["amount"] == 24.0 and rows[0]["currency"] == "usd"


def test_cancel_and_resume(user_a):
    sub_id = pay(user_a)
    user_a.get(f"/payments/status/{sub_id}")
    r = user_a.post("/payments/subscription/cancel")
    assert r.status_code == 200 and r.json()["cancel_at_period_end"] is True