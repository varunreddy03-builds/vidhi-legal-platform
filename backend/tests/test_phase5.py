"""Phase 5: the app runs on its own - Gemini, Stripe and Resend directly, no Emergent code or dependency.

Third-party services are never contacted: Gemini and Resend are replaced by fakes that RECORD what would be sent
(so request shapes are asserted), Stripe's webhook signature is verified for real with a test secret, and the
checkout gateway is the PAYMENTS_STUB. Everything between those edges is the real code.
"""

import base64
import hashlib
import hmac
import io
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from lib import ai, email as mail, payments_gateway as pg, svix
from tests.conftest import (
    mark_stub_paid,
    mongo,
    set_plan,
    outbox,
    post_stripe_event,
    stripe_headers,
)

SECRET = "whsec_" + base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()


# =============================================================================================
# Gemini (lib/ai.py) with a recording fake client
# =============================================================================================
class _Reply:
    def __init__(self, text):
        self._t = text

    @property
    def text(self):
        if self._t is None:
            raise ValueError("blocked by the safety filter")  # what the real SDK does for blocked content
        return self._t


class _FakeModels:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return _Reply(r)


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv("AI_STUB", "false")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    def install(*replies):
        fake = SimpleNamespace(aio=SimpleNamespace(models=_FakeModels(replies)))
        monkeypatch.setattr(ai, "_client", lambda: fake)
        return fake.aio.models

    return install


async def test_gemini_reply_is_parsed_even_inside_code_fences(gemini):
    models = gemini('```json\n{"answer": "ok", "n": 3}\n```')
    assert await ai.ask_json("s", "question", '{"answer": string}') == {"answer": "ok", "n": 3}
    assert len(models.calls) == 1


async def test_gemini_request_carries_the_schema_json_mode_and_default_model(gemini):
    models = gemini('{"a": 1}')
    await ai.ask_json("s", "the prompt", '{"a": number}', purpose="x")
    call = models.calls[0]
    assert call["model"] == "gemini-3.8-flash" and call["contents"] == "the prompt"
    cfg = call["config"]
    assert cfg.response_mime_type == "application/json"
    assert '{"a": number}' in cfg.system_instruction and "never say or imply that a person lied" in cfg.system_instruction
    assert cfg.temperature == 0.2


async def test_gemini_model_is_configurable_without_code_changes(gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    models = gemini('{"a": 1}')
    await ai.ask_json("s", "p", "{}")
    assert models.calls[0]["model"] == "gemini-2.5-flash"


async def test_one_unusable_reply_is_retried_then_succeeds(gemini):
    models = gemini("sorry, here you go: not json", '{"ok": true}')
    assert await ai.ask_json("s", "p", "{}") == {"ok": True}
    assert len(models.calls) == 2 and "not valid JSON" in models.calls[1]["contents"]


@pytest.mark.parametrize("bad", ["still not json", None, "[1, 2, 3]", ""], ids=["text", "blocked", "array", "empty"])
async def test_two_unusable_replies_raise_instead_of_returning_an_empty_answer(gemini, bad):
    models = gemini(bad, bad)
    with pytest.raises(ai.AIError):
        await ai.ask_json("s", "p", "{}")
    assert len(models.calls) == 2


async def test_provider_errors_are_not_swallowed(gemini):
    gemini(RuntimeError("503 overloaded"))
    with pytest.raises(ai.AIError):  # with no other model configured the failure surfaces; never an empty answer
        await ai.ask_json("s", "p", "{}")


async def test_image_text_is_read_with_the_right_mime_type(gemini):
    models = gemini("  Receipt for Rs 500  ")
    out = await ai.read_image_text("s", base64.b64encode(b"\xff\xd8\xffJPEGBYTES").decode(), "read it", "image/jpeg")
    assert out == "Receipt for Rs 500"
    part, prompt = models.calls[0]["contents"]
    assert part.inline_data.mime_type == "image/jpeg" and part.inline_data.data == b"\xff\xd8\xffJPEGBYTES" and prompt == "read it"


def test_missing_key_is_a_clear_configuration_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        ai._client()


# =============================================================================================
# Resend (lib/email.py)
# =============================================================================================
@pytest.fixture
def resend(monkeypatch):
    monkeypatch.setenv("EMAIL_DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("EMAIL_FROM", "VIDHI <notices@example.com>")
    monkeypatch.setenv("EMAIL_REPLY_TO", "help@example.com")
    sent = []

    def install(status=200, body=None):
        def handler(request):
            sent.append(request)
            return httpx.Response(status, json=body if body is not None else {"id": "re_msg_123"})

        monkeypatch.setattr(mail, "_TRANSPORT", httpx.MockTransport(handler))
        return sent

    return install


async def test_resend_request_shape(resend):
    import json

    sent = resend()
    mid = await mail.send_email(
        to="a@example.com", subject="Hello", html="<p>hi</p>", cc=["c@example.com"],
        attachments=[{"filename": "n.pdf", "content": "QUJD"}], idempotency_key="key-1",
    )
    assert mid == "re_msg_123" and len(sent) == 1
    req = sent[0]
    assert req.method == "POST" and str(req.url) == "https://api.resend.com/emails"
    assert req.headers["authorization"] == "Bearer re_test_key" and req.headers["idempotency-key"] == "key-1"
    body = json.loads(req.content)
    assert body == {
        "from": "VIDHI <notices@example.com>", "to": ["a@example.com"], "subject": "Hello", "html": "<p>hi</p>",
        "cc": ["c@example.com"], "reply_to": "help@example.com", "attachments": [{"filename": "n.pdf", "content": "QUJD"}],
    }


async def test_resend_failure_raises_and_is_not_retried(resend):
    sent = resend(status=422, body={"message": "invalid from"})
    with pytest.raises(httpx.HTTPStatusError):
        await mail.send_email(to="a@example.com", subject="s", html="<p>x</p>")
    assert len(sent) == 1  # a retry could duplicate a message that actually went out


async def test_resend_needs_configuration_and_unsafe_mail_never_leaves(resend, monkeypatch):
    sent = resend()
    with pytest.raises(ValueError):  # the safety guard still runs first
        await mail.send_email(to="a@example.com", subject="s", html='<form action="https://x.example.com"></form>')
    assert sent == []
    monkeypatch.delenv("RESEND_API_KEY")
    with pytest.raises(RuntimeError, match="RESEND_API_KEY"):
        await mail.send_email(to="a@example.com", subject="s", html="<p>x</p>")
    assert sent == []


# =============================================================================================
# Svix signatures (how Resend authenticates its webhooks)
# =============================================================================================
def _independent_signature(msg_id, ts, body):
    key = base64.b64decode(SECRET.removeprefix("whsec_"))
    return base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()


def test_svix_signature_matches_an_independent_computation_of_the_spec():
    assert svix.sign(SECRET, "msg_1", "1700000000", b'{"a":1}') == _independent_signature("msg_1", "1700000000", b'{"a":1}')


def _hdrs(body, ts=None, sigs=None):
    ts = str(ts if ts is not None else int(time.time()))
    sigs = sigs or [f"v1,{_independent_signature('msg_1', ts, body)}"]
    return {"svix-id": "msg_1", "svix-timestamp": ts, "svix-signature": " ".join(sigs)}


def test_svix_accepts_only_authentic_recent_messages():
    body = b'{"type":"email.delivered"}'
    assert svix.verify(SECRET, _hdrs(body), body)
    assert not svix.verify(SECRET, _hdrs(body), body + b"x")  # tampered body
    assert not svix.verify("whsec_" + base64.b64encode(b"another-secret-of-32-bytes-long!!").decode(), _hdrs(body), body)
    assert not svix.verify(SECRET, _hdrs(body, ts=int(time.time()) - 3600), body)  # replay of an old message
    assert not svix.verify(SECRET, _hdrs(body, ts=int(time.time()) + 3600), body)  # timestamp from the future
    assert not svix.verify(SECRET, {}, body) and not svix.verify(SECRET, {"svix-id": "x"}, body)
    assert not svix.verify(SECRET, _hdrs(body, sigs=["v1,not-base64!!"]), body)
    assert not svix.verify(SECRET, {**_hdrs(body), "svix-timestamp": "yesterday"}, body)


def test_svix_supports_rotated_secrets_with_several_signatures():
    body = b"{}"
    ts = int(time.time())
    good = f"v1,{_independent_signature('msg_1', ts, body)}"
    assert svix.verify(SECRET, _hdrs(body, ts, ["v1,AAAA", good, "v2,whatever"]), body)
    assert not svix.verify(SECRET, _hdrs(body, ts, ["v1,AAAA", "v2," + good[3:]]), body)  # only v1 counts


# =============================================================================================
# Stripe: gateway shape, price config, and a webhook that is really verified
# =============================================================================================
@pytest.mark.parametrize(
    "amount,currency,expected",
    [(49, "usd", 4900), (49.5, "INR", 4950), (4999, "inr", 499900), (500, "jpy", 500), (19.995, "usd", 2000), ("0.10", "usd", 10)],
)
def test_minor_units(amount, currency, expected):
    assert pg.minor_units(amount, currency) == expected


def test_the_installed_stripe_sdk_has_the_calls_we_use():
    import stripe

    c = stripe.StripeClient("sk_test_x")
    assert callable(c.v1.checkout.sessions.create_async) and callable(c.v1.checkout.sessions.retrieve_async)
    assert callable(c.v1.payment_intents.retrieve_async) and callable(stripe.Webhook.construct_event)


async def test_stripe_checkout_request_is_built_from_server_side_values(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    seen = {}

    class Sessions:
        async def create_async(self, params):
            seen.update(params)
            return {"id": "cs_1", "url": "https://checkout.stripe.com/c/pay/cs_1"}

    gw = pg.StripeGateway()
    gw.client = SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=Sessions())))
    out = await gw.create_checkout(
        amount=49, currency="USD", name="VIDHI Pro", success_url="https://app.example.in/payment/success?session_id={CHECKOUT_SESSION_ID}",
        cancel_url="https://app.example.in/payment/cancel", metadata={"user_id": "u1"}, client_reference_id="u1",
    )
    assert out == {"id": "cs_1", "url": "https://checkout.stripe.com/c/pay/cs_1"}
    item = seen["line_items"][0]
    assert seen["mode"] == "payment" and item["price_data"]["unit_amount"] == 4900 and item["price_data"]["currency"] == "usd"
    assert seen["metadata"] == {"user_id": "u1"} and seen["client_reference_id"] == "u1"
    assert seen["payment_intent_data"]["metadata"] == {"user_id": "u1"}


async def test_a_subscription_checkout_is_monthly_in_rupees_with_the_server_side_price(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    seen = {}

    class Sessions:
        async def create_async(self, params):
            seen.update(params)
            return {"id": "cs_2", "url": "https://checkout.stripe.com/c/pay/cs_2"}

    gw = pg.StripeGateway()
    gw.client = SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=Sessions())))
    await gw.create_checkout(
        amount=1999, currency="INR", name="VIDHI Pro", success_url="https://app.example.in/ok", cancel_url="https://app.example.in/no",
        metadata={"user_id": "u1"}, client_reference_id="u1", recurring_interval="month", customer_email="a@example.com",
    )
    item = seen["line_items"][0]["price_data"]
    assert seen["mode"] == "subscription" and item["unit_amount"] == 199900 and item["currency"] == "inr" and item["recurring"] == {"interval": "month"}
    assert seen["subscription_data"]["metadata"] == {"user_id": "u1"} and "payment_intent_data" not in seen and seen["customer_email"] == "a@example.com"


def test_stripe_key_must_be_configured_and_the_old_shared_key_is_refused(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_" + "em" + "ergent_shared")
    with pytest.raises(RuntimeError, match="STRIPE_SECRET_KEY"):
        pg.StripeGateway()


def test_webhook_construct_event_verifies_signature_and_age(monkeypatch):
    import json

    body = json.dumps({"id": "evt_1", "object": "event", "type": "checkout.session.completed", "data": {"object": {"id": "cs_1"}}}).encode()
    assert pg.construct_event(body, stripe_headers(body)["Stripe-Signature"])["type"] == "checkout.session.completed"
    for bad in (None, "", "garbage", stripe_headers(body, secret="whsec_wrong")["Stripe-Signature"], stripe_headers(body, ts=int(time.time()) - 7200)["Stripe-Signature"]):
        with pytest.raises(ValueError):
            pg.construct_event(body, bad)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET")
    with pytest.raises(ValueError):  # no configured secret -> nothing is accepted, even a "valid-looking" request
        pg.construct_event(body, stripe_headers(body, secret="whsec_anything")["Stripe-Signature"])


def _checkout(c):
    set_plan(c, "FREE")  # these tests are about becoming Pro, so they start from the free plan
    r = c.post("/payments/checkout", json={"package_id": "vidhi_pro", "origin_url": "http://localhost:3000"})
    assert r.status_code == 200, r.text
    return r.json()["session_id"], r.json()["checkout_url"]


def _plan(c):
    return c.get("/auth/entitlement").json()["plan"]


def test_price_comes_from_server_configuration(user_a):
    pro = next(p for p in user_a.get("/payments/packages").json() if p["id"] == "vidhi_pro")
    assert pro == {"id": "vidhi_pro", "amount": 1999.0, "currency": "inr", "interval": "month", "providers": ["stripe", "razorpay", "paypal"], "prices": {"stripe": {"amount": 1999.0, "currency": "inr"}, "razorpay": {"amount": 1999.0, "currency": "inr"}, "paypal": {"amount": 24.0, "currency": "usd"}}}  # PRO_PRICE_AMOUNT / PRO_PRICE_CURRENCY defaults


def test_checkout_poll_and_upgrade_only_after_a_verified_payment(user_a):
    sid, url = _checkout(user_a)
    assert url.startswith("http://localhost:3000/payment/success?session_id=cs_stub_")
    assert user_a.get(f"/payments/status/{sid}").json()["payment_status"] == "pending"
    assert _plan(user_a) != "PRO"

    mark_stub_paid(sid, amount_total=199900, user_id=user_a.user["id"])
    s = user_a.get(f"/payments/status/{sid}").json()
    assert s["payment_status"] == "paid" and s["status"] == "completed" and _plan(user_a) == "PRO"
    assert user_a.get(f"/payments/status/{sid}").json()["payment_status"] == "paid"  # idempotent

    receipt = user_a.get(f"/payments/receipt/{sid}.pdf")
    assert receipt.status_code == 200 and receipt.content[:4] == b"%PDF"
    from pypdf import PdfReader

    text = PdfReader(io.BytesIO(receipt.content)).pages[0].extract_text()
    assert "Rs 1,999.00" in text and "Test-mode" in text
    mail_row = [m for m in outbox(to=user_a.user["email"], subject_has="VIDHI Pro receipt")]
    assert mail_row and any(a and a.startswith("vidhi-receipt-") for a in mail_row[-1]["attachments"])


@pytest.mark.parametrize(
    "paid_kwargs,reason",
    [
        ({"amount_total": 100}, "amount"),  # paid far less than the price
        ({"amount_total": 199900, "currency": "usd"}, "currency"),  # right number, wrong currency
        ({"amount_total": 199900, "user_id": "someone-else"}, "buyer"),  # a session that belongs to another user
        ({"amount_total": 199900, "payment_status": "unpaid"}, None),  # complete-looking but not paid
    ],
    ids=["amount", "currency", "buyer", "unpaid"],
)
def test_a_payment_that_does_not_match_never_upgrades(user_a, paid_kwargs, reason):
    sid, _ = _checkout(user_a)
    kwargs = {"user_id": user_a.user["id"], **paid_kwargs}
    mark_stub_paid(sid, **kwargs)
    s = user_a.get(f"/payments/status/{sid}").json()
    assert s["payment_status"] == "pending" and _plan(user_a) != "PRO"
    if reason:
        assert s["status"] == "needs_review"
        assert reason in mongo().payment_transactions.find_one({"session_id": sid})["review_reason"]


def test_stripe_webhook_settles_a_payment_and_rejects_forgeries(user_a, anon):
    sid, _ = _checkout(user_a)
    body = b'{"id":"evt_x","object":"event","type":"checkout.session.completed","data":{"object":{"id":"%s"}}}' % sid.encode()
    assert anon.post("/webhook/stripe", content=body).status_code == 400  # unsigned
    assert anon.post("/webhook/stripe", content=body, headers=stripe_headers(body, secret="whsec_forged")).status_code == 400
    assert anon.post("/webhook/stripe", content=body, headers=stripe_headers(body, ts=int(time.time()) - 7200)).status_code == 400
    assert _plan(user_a) != "PRO"

    # A properly signed 'completed' event is not enough on its own: we re-ask the gateway.
    assert post_stripe_event("checkout.session.completed", sid).status_code == 200
    assert _plan(user_a) != "PRO"
    mark_stub_paid(sid, amount_total=199900, user_id=user_a.user["id"])
    assert post_stripe_event("checkout.session.completed", sid).status_code == 200
    assert _plan(user_a) == "PRO"


def test_stripe_webhook_ignores_other_event_types_and_unknown_sessions(user_a):
    set_plan(user_a, "FREE")
    assert post_stripe_event("charge.refunded", "cs_whatever").status_code == 200
    assert post_stripe_event("checkout.session.completed", "cs_not_ours").status_code == 200
    assert _plan(user_a) != "PRO"


# =============================================================================================
# Scheduled jobs, PDFs, and independence from Emergent
# =============================================================================================
def test_a_scheduled_job_cannot_start_while_the_same_job_is_running(anon):
    h = {"Authorization": "Bearer test-cron-secret-not-real"}
    from datetime import datetime, timedelta, timezone

    mongo().cron_locks.replace_one(
        {"_id": "recovery-reminders"}, {"_id": "recovery-reminders", "expires_at": datetime.now(timezone.utc) + timedelta(minutes=30)}, upsert=True
    )
    assert anon.post("/cron/recovery-reminders", headers=h).json() == {"status": "already_running"}
    mongo().cron_locks.delete_one({"_id": "recovery-reminders"})
    assert anon.post("/cron/recovery-reminders", headers=h).json() == {"status": "accepted"}


def test_expired_locks_do_not_block_the_schedule(anon):
    h = {"Authorization": "Bearer test-cron-secret-not-real"}
    from datetime import datetime, timedelta, timezone

    time.sleep(1)  # let any job started by an earlier test release its own lock
    mongo().cron_locks.replace_one(
        {"_id": "recovery-reminders"}, {"_id": "recovery-reminders", "expires_at": datetime.now(timezone.utc) - timedelta(minutes=5)}, upsert=True
    )
    assert anon.post("/cron/recovery-reminders", headers=h).json() == {"status": "accepted"}


def test_statement_pdf_spells_the_rupee_instead_of_printing_a_black_square():
    from pypdf import PdfReader

    from routers.recovery import _build_statement_pdf

    case = {
        "creditor_name": "A Traders", "debtor_name": "Debtor X", "currency": "INR", "amount": 50000,
        "detected_amount": 50000, "paid_amount": 10000,
        "payments": [{"date": "2026-10-19T10:00:00", "amount": 10000}],
    }
    text = PdfReader(io.BytesIO(_build_statement_pdf(case, None))).pages[0].extract_text()
    assert "Rs 40,000" in text and "Rs 50,000" in text
    assert "■" not in text and "₹" not in text


def test_no_emergent_code_or_dependency_remains():
    import os

    root = Path(os.path.abspath(__file__)).parents[2]  # abspath, not resolve(): keeps a short Windows junction path short
    targets = [p for p in (root / "backend").rglob("*") if p.suffix in (".py", ".txt", ".lock") and "tests" not in p.parts and "__pycache__" not in p.parts]
    targets += [p for p in (root / "frontend" / "src").rglob("*") if p.suffix in (".ts", ".tsx")]
    targets += [root / "frontend" / "vite.config.ts", root / "frontend" / "package.json"]
    forbidden = ("emergentintegrations", "emergentagent", "@emergentbase", "EMERGENT_LLM_KEY", "EMERGENT_EMAIL_KEY", "sk_test_emergent")
    offenders = {f"{p.relative_to(root)}: {w}" for p in targets if p.exists() for w in forbidden if w in p.read_text(encoding="utf-8", errors="ignore")}
    assert not offenders, sorted(offenders)


def test_a_random_token_in_a_link_never_trips_the_credential_guard():
    from lib.email import _assert_safe_email

    _assert_safe_email("Reset your password", '<p>Click <a href="https://app.example.in/reset-password?token=aXcvvBzq-cvv-9">here</a>: https://app.example.in/x?t=cvv</p>')
    with pytest.raises(ValueError, match="credentials"):
        _assert_safe_email("Hello", "<p>Please reply with your CVV to confirm.</p>")
    with pytest.raises(ValueError, match="credentials"):
        _assert_safe_email("Hello", "<p>Please reply with your password.</p>")


async def test_the_real_stripe_sdk_objects_are_not_dicts_and_the_gateway_copes(monkeypatch):
    """Found by a live test: stripe-python returns objects without .get(); a fake that returns plain dicts hid it."""
    import stripe

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    session = stripe.checkout.Session.construct_from(
        {"id": "cs_1", "payment_status": "paid", "status": "complete", "amount_total": 199900, "currency": "inr",
         "metadata": {"user_id": "u1"}, "subscription": "sub_1", "customer": "cus_1", "payment_intent": None}, "k")
    sub = stripe.Subscription.construct_from(
        {"id": "sub_1", "status": "active", "customer": "cus_1", "cancel_at_period_end": False,
         "items": {"data": [{"current_period_end": 1893456000}]}}, "k")
    with pytest.raises(AttributeError):
        session.get("id")  # the trap: this is what made the real call fail

    class Sessions:
        async def retrieve_async(self, sid):
            return session

    class Subs:
        async def retrieve_async(self, sid):
            return sub

    gw = pg.StripeGateway()
    gw.client = SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=Sessions()), subscriptions=Subs()))
    st = await gw.retrieve("cs_1")
    assert st["payment_status"] == "paid" and st["subscription_id"] == "sub_1" and st["customer_id"] == "cus_1" and st["amount_total"] == 199900
    got = await gw.get_subscription("sub_1")
    assert got["status"] == "active" and got["current_period_end"].year == 2030 and got["customer_id"] == "cus_1"
