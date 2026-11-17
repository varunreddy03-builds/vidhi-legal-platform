"""Razorpay (UPI, cards, netbanking, monthly auto-pay) next to Stripe: same safety rules, its own signed webhook."""

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from lib import razorpay_gateway as rg
from tests.conftest import API_URL, mark_stub_paid, mongo, set_plan

WEBHOOK_SECRET = "razorpay-test-webhook-secret-not-real"  # secret-scan: ok (fake test value)


def run(coro):
    return asyncio.run(coro)


# ---- the gateway's requests and how it reads Razorpay's answers (Razorpay itself is replaced by a recorded transport) ----
class Recorder:
    def __init__(self, replies: dict):
        self.replies, self.calls = replies, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body, request.headers.get("authorization", "")))
        return httpx.Response(200, json=self.replies[(request.method, request.url.path)])


@pytest.fixture
def rzp(monkeypatch):
    def make(replies):
        rec = Recorder(replies)
        monkeypatch.setattr(rg, "_TRANSPORT", httpx.MockTransport(rec))
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_abc")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")

        async def plan_id(self, *a, **k):
            return "plan_X"

        monkeypatch.setattr(rg.RazorpayGateway, "_plan_id", plan_id)
        return rec, rg.RazorpayGateway()

    return make


def test_creating_a_checkout_sends_the_right_subscription(rzp):
    rec, gw = rzp({("POST", "/v1/subscriptions"): {"id": "sub_1", "short_url": "https://rzp.io/i/abc"}})
    out = run(gw.create_checkout(
        amount=1999, currency="inr", name="VIDHI Pro", success_url="x", cancel_url="y", metadata={"user_id": "u1", "purpose": "vidhi_pro"},
        client_reference_id="u1", recurring_interval="month", customer_email="a@example.com",
    ))
    assert out == {"id": "sub_1", "url": "https://rzp.io/i/abc"}
    method, path, body, auth = rec.calls[0]
    assert (method, path) == ("POST", "/v1/subscriptions") and auth.startswith("Basic ")
    assert body["plan_id"] == "plan_X" and body["notes"]["user_id"] == "u1" and body["notify_info"] == {"notify_email": "a@example.com"}


def test_a_subscription_counts_as_paid_only_after_a_charge(rzp):
    sub = {"id": "sub_1", "plan_id": "plan_X", "status": "created", "paid_count": 0, "notes": {"user_id": "u1"}, "customer_id": "cust_1"}
    plan = {"id": "plan_X", "item": {"amount": 199900, "currency": "INR"}}
    rec, gw = rzp({("GET", "/v1/subscriptions/sub_1"): sub, ("GET", "/v1/plans/plan_X"): plan})
    assert run(gw.retrieve("sub_1"))["payment_status"] == "unpaid"
    sub.update(status="active", paid_count=1)
    st = run(gw.retrieve("sub_1"))
    assert st["payment_status"] == "paid" and st["amount_total"] == 199900 and st["currency"] == "inr" and st["metadata"]["user_id"] == "u1"
    assert st["subscription_id"] == "sub_1"


def test_subscription_state_is_translated(rzp):
    end = int((datetime.now(timezone.utc) + timedelta(days=20)).timestamp())
    sub = {"id": "sub_1", "plan_id": "p", "status": "active", "current_end": end, "has_scheduled_changes": False}
    rec, gw = rzp({("GET", "/v1/subscriptions/sub_1"): sub})
    s = run(gw.get_subscription("sub_1"))
    assert s["status"] == "active" and not s["cancel_at_period_end"] and int(s["current_period_end"].timestamp()) == end
    sub.update(has_scheduled_changes=True)
    assert run(gw.get_subscription("sub_1"))["cancel_at_period_end"] is True
    for razor, ours in (("halted", "unpaid"), ("cancelled", "canceled"), ("pending", "past_due")):
        sub["status"] = razor
        assert run(gw.get_subscription("sub_1"))["status"] == ours


def test_cancelling_is_at_the_end_of_the_paid_month_and_cannot_be_undone(rzp):
    rec, gw = rzp({("POST", "/v1/subscriptions/sub_1/cancel"): {"id": "sub_1"}})
    run(gw.set_cancel_at_period_end("sub_1", True))
    assert rec.calls[0][2] == {"cancel_at_cycle_end": 1}
    with pytest.raises(rg.GatewayUnsupported):
        run(gw.set_cancel_at_period_end("sub_1", False))


def test_a_failing_razorpay_call_raises(rzp, monkeypatch):
    rec, gw = rzp({})
    monkeypatch.setattr(rg, "_TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(500, json={})))
    with pytest.raises(RuntimeError):
        run(gw.get_subscription("sub_1"))


# ---- through the app (the stub plays Razorpay) ----
def sign(body: bytes, secret: str = WEBHOOK_SECRET) -> dict:
    return {"X-Razorpay-Signature": hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(), "Content-Type": "application/json"}


def checkout(c, provider=None):
    set_plan(c, "FREE")
    body = {"package_id": "vidhi_pro", "origin_url": "http://localhost:3000"}
    if provider:
        body["provider"] = provider
    return c.post("/payments/checkout", json=body)


def pay_via_razorpay(c, days_left=30):
    r = checkout(c, "razorpay")
    assert r.status_code == 200, r.text
    stub_sid = r.json()["session_id"]
    sub_id = "sub_rzp_" + uuid.uuid4().hex[:10]
    sid = sub_id  # with Razorpay the checkout id IS the subscription id
    mongo().payment_transactions.update_one({"session_id": stub_sid}, {"$set": {"session_id": sid}})
    mongo().subscription_stub.insert_one({
        "id": sub_id, "status": "active", "current_period_end": datetime.now(timezone.utc) + timedelta(days=days_left),
        "cancel_at_period_end": False, "customer_id": "cust_t",
    })
    mark_stub_paid(sid, amount_total=199900, user_id=c.user["id"], subscription_id=sub_id)
    return sid, sub_id


def test_packages_list_the_available_providers(user_a):
    pk = user_a.get("/payments/packages").json()[0]
    assert set(pk["providers"]) == {"stripe", "razorpay", "paypal"}


def test_unknown_provider_is_refused(user_a):
    assert checkout(user_a, "bitcoin").status_code == 400


def test_a_razorpay_payment_unlocks_pro_and_remembers_the_provider(user_a):
    sid, sub_id = pay_via_razorpay(user_a)
    assert user_a.get(f"/payments/status/{sid}").json()["payment_status"] == "paid"
    row = mongo().users.find_one({"id": user_a.user["id"]})
    assert row["plan"] == "PRO" and row["payment_provider"] == "razorpay" and row["subscription_id"] == sub_id
    assert mongo().payment_transactions.find_one({"session_id": sid})["provider"] == "razorpay"
    assert user_a.get("/auth/entitlement").json()["plan"] == "PRO"


def test_the_amount_is_checked_for_razorpay_too(user_a):
    r = checkout(user_a, "razorpay")
    sid = r.json()["session_id"]
    mark_stub_paid(sid, amount_total=100, user_id=user_a.user["id"], subscription_id="sub_cheap")
    assert user_a.get(f"/payments/status/{sid}").json()["status"] == "needs_review"
    assert mongo().users.find_one({"id": user_a.user["id"]})["plan"] == "FREE"


def event(name: str, sub_id: str, paid_count: int, payment_id: str | None = None) -> bytes:
    payload = {"subscription": {"entity": {"id": sub_id, "paid_count": paid_count}}}
    if payment_id:
        payload["payment"] = {"entity": {"id": payment_id, "amount": 199900, "currency": "INR"}}
    return json.dumps({"event": name, "payload": payload}).encode()


def test_the_webhook_must_be_signed():
    with httpx.Client(base_url=API_URL, timeout=30.0) as anon:
        body = event("subscription.charged", "sub_x", 1)
        assert anon.post("/webhook/razorpay", content=body).status_code == 400
        assert anon.post("/webhook/razorpay", content=body, headers=sign(body, "forged-secret")).status_code == 400
        assert anon.post("/webhook/razorpay", content=body, headers={"X-Razorpay-Signature": "nothex"}).status_code == 400
        assert anon.post("/webhook/razorpay", content=body, headers=sign(body)).status_code == 200  # authentic, nothing to do for an unknown id


def test_the_webhook_settles_a_payment_the_browser_never_reported(user_a):
    sid, sub_id = pay_via_razorpay(user_a)
    body = event("subscription.activated", sub_id, 1)
    r = httpx.post(f"{API_URL}/webhook/razorpay", content=body, headers=sign(body))
    assert r.status_code == 200
    assert mongo().users.find_one({"id": user_a.user["id"]})["plan"] == "PRO"


def test_a_renewal_is_added_once_to_the_history_with_a_receipt(user_a):
    sid, sub_id = pay_via_razorpay(user_a)
    user_a.get(f"/payments/status/{sid}")
    pay = "pay_" + uuid.uuid4().hex[:10]
    body = event("subscription.charged", sub_id, 2, pay)
    for _ in range(2):  # Razorpay may deliver the same event twice
        assert httpx.post(f"{API_URL}/webhook/razorpay", content=body, headers=sign(body)).status_code == 200
    rows = list(mongo().payment_transactions.find({"session_id": pay}))
    assert len(rows) == 1 and rows[0]["renewal"] and rows[0]["provider"] == "razorpay" and rows[0]["amount"] == 1999.0


def test_the_first_charge_event_is_not_recorded_as_a_renewal(user_a):
    sid, sub_id = pay_via_razorpay(user_a)
    user_a.get(f"/payments/status/{sid}")
    pay = "pay_" + uuid.uuid4().hex[:10]
    body = event("subscription.charged", sub_id, 1, pay)
    assert httpx.post(f"{API_URL}/webhook/razorpay", content=body, headers=sign(body)).status_code == 200
    assert mongo().payment_transactions.count_documents({"session_id": pay}) == 0


def test_cancelling_a_razorpay_subscription(user_a):
    sid, sub_id = pay_via_razorpay(user_a)
    user_a.get(f"/payments/status/{sid}")
    r = user_a.post("/payments/subscription/cancel")
    assert r.status_code == 200 and r.json()["cancel_at_period_end"] is True
