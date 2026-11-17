"""Pre-scaffolded pytest fixtures for the FastAPI backend.

Tests hit the live uvicorn process managed by supervisor (not an in-process ASGI app), so
the app under test is the same one the frontend and Playwright see. Do NOT re-create this
file — add app-specific fixtures below the marker at the bottom.
"""

import os

import httpx
import pytest
import pytest_asyncio

# Defaults so tests that import app modules directly (unit-style) work; the live server gets its own env
# from scripts/test-backend.ps1. Never point these at a real database or real provider keys.
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "vidhi_test")
os.environ.setdefault("APP_URL", "http://localhost:3000")
os.environ.setdefault("BCRYPT_COST", "4")

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8001")
API_URL = f"{BACKEND_URL}/api"


def api_url(path: str = "") -> str:
    """Absolute URL for an /api route: api_url("/status") -> http://localhost:8001/api/status."""
    return f"{API_URL}{path}"


@pytest.fixture(scope="session")
def backend_url() -> str:
    return BACKEND_URL


@pytest.fixture
def client():
    """Sync httpx client rooted at /api — the default for endpoint tests.

    Example:
        def test_status(client):
            assert client.get("/status").status_code == 200
    """
    with httpx.Client(base_url=API_URL, timeout=30.0) as c:
        yield c


@pytest_asyncio.fixture
async def aclient():
    """Async variant, for tests that also await motor/backend helpers directly."""
    async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as c:
        yield c


# --- app-specific fixtures below this line ---
import uuid  # noqa: E402


def _new_user_client() -> httpx.Client:
    """Sign up a fresh user + organization; the returned client keeps the session cookie.

    Uses example.com (the email validator rejects reserved TLDs such as .test). Each call is a
    brand-new organization, so tests never share tenant data.
    """
    c = httpx.Client(base_url=API_URL, timeout=30.0)
    tag = uuid.uuid4().hex[:12]
    password = f"Pw-{uuid.uuid4().hex}"
    r = c.post(
        "/auth/signup",
        json={
            "email": f"qa-{tag}@example.com",
            "password": password,
            "full_name": "QA User",
            "organization_name": f"QA Org {tag}",
            "accept_privacy": True,
        },
    )
    assert r.status_code == 200, r.text
    c.user = r.json()  # type: ignore[attr-defined]
    c.password = password  # type: ignore[attr-defined]
    # Most tests are about features, not plans, so test users start on PRO (no end date = unlimited). Plan tests use set_plan().
    set_plan(c, "PRO")
    return c


def set_plan(c, plan: str, **extra) -> None:
    """Put the user (and so their organisation) on a plan directly in the database, e.g. set_plan(c, "FREE")."""
    fields = {"plan": plan, **extra}
    unset = {k: "" for k in ("pro_until", "subscription_status", "cancel_at_period_end", "subscription_id", "stripe_customer_id") if k not in fields}
    mongo().users.update_one({"id": c.user["id"]}, {"$set": fields, "$unset": unset})


@pytest.fixture
def user_a():
    c = _new_user_client()
    yield c
    c.close()


@pytest.fixture
def user_b():
    c = _new_user_client()
    yield c
    c.close()


@pytest.fixture
def anon():
    with httpx.Client(base_url=API_URL, timeout=30.0) as c:
        yield c


# ---- helpers for mail-related tests (server runs with EMAIL_DRY_RUN=true: mail lands in email_outbox) ----
import re  # noqa: E402

from pymongo import MongoClient  # noqa: E402


_MONGO: dict[str, MongoClient] = {}


def mongo():
    """The test database. One connection per process, with retryable writes off: a brand-new connection could send a write option that a plain (non-replica-set) MongoDB refuses
    ("Transaction numbers are only allowed on a replica set member or mongos"), which failed an unrelated test once under load on 2026-11-06."""
    url = os.environ["MONGO_URL"]
    if url not in _MONGO:
        _MONGO[url] = MongoClient(url, retryWrites=False)
    return _MONGO[url][os.environ["DB_NAME"]]


def outbox(to: str | None = None, subject_has: str | None = None) -> list[dict]:
    q: dict = {}
    if to:
        q["to"] = {"$regex": f"^{re.escape(to)}$", "$options": "i"}
    if subject_has:
        q["subject"] = {"$regex": re.escape(subject_has), "$options": "i"}
    return list(mongo().email_outbox.find(q).sort("created_at", 1))


def token_from_mail(mail: dict, marker: str) -> str:
    """Pull the signed/random token out of a captured mail link (…/<marker><token>)."""
    m = re.search(re.escape(marker) + r"([\w\-\.]+)", mail["html"])
    assert m, f"no {marker} link in mail to {mail['to']}"
    return m.group(1)


def verify_email(c: httpx.Client) -> None:
    """Confirm the signed-up user's address using the link from the captured verification mail."""
    mail = outbox(to=c.user["email"], subject_has="Confirm your email")[-1]
    token = token_from_mail(mail, "token=")
    r = c.post("/auth/verify-email", json={"token": token})
    assert r.status_code == 200, r.text


@pytest.fixture
def verified_a(user_a):
    verify_email(user_a)
    return user_a


@pytest.fixture
def verified_b(user_b):
    verify_email(user_b)
    return user_b


CLEAN_NOTICE = (
    "Date: 19 Oct 2026\nFrom: A Traders, 1 Market Road, Pune\nTo: Debtor X, 9 Lake View, Mumbai\n\n"
    "You owe Rs 40,000 for goods delivered on 1 March 2026. Please pay within 15 days.\n"
    "This is a draft to be reviewed by a lawyer before sending."
)


def make_case(c: httpx.Client, notice: str | None = CLEAN_NOTICE) -> str:
    case = c.post("/recovery/cases", json={"creditor_name": "A Traders", "debtor_name": "Debtor X", "amount": 50000}).json()
    if notice is not None:
        import hashlib

        sha = hashlib.sha256(notice.encode()).hexdigest()
        vid = str(uuid.uuid4())
        db = mongo()
        approver = {"kind": "OWNER", "version_id": vid, "version": 1, "sha": sha, "at": datetime.now(timezone.utc), "name": "fixture"}
        db.notice_versions.insert_one({"id": vid, "case_id": case["id"], "organization_id": c.user["organization_id"], "number": 1,
            "body": notice, "sha": sha, "origin": "LEGACY", "created_by": None, "created_at": datetime.now(timezone.utc), "meta": {}, "approvals": [approver]})
        db.recovery_cases.update_one({"id": case["id"]}, {"$set": {"notice_body": notice, "status": "NOTICE_READY",
            "workflow": {"state": "APPROVED", "current_version_id": vid, "approved": approver, "history": []}}})
    return case["id"]


# ---- helpers for AI-dependent tests (server runs with AI_STUB=true: replies are scripted per test) ----
from datetime import datetime, timezone  # noqa: E402


def stub(purpose: str, response, contains: str | None = None) -> None:
    """Queue ONE scripted model reply. `contains` (use the test's unique matter title) keeps parallel tests apart."""
    mongo().ai_stub.insert_one(
        {"purpose": purpose, "contains": contains, "response": response, "used": False, "created_at": datetime.now(timezone.utc)}
    )


def ai_prompts(contains: str, purpose: str | None = None) -> list[str]:
    """Every prompt the model was actually given that mentions `contains`."""
    q: dict = {"prompt": {"$regex": re.escape(contains)}}
    if purpose:
        q["purpose"] = purpose
    return [c["prompt"] for c in mongo().ai_calls.find(q).sort("created_at", 1)]


def new_matter(c: httpx.Client, label: str = "Matter") -> tuple[str, str]:
    """(matter id, unique title). The title is the marker used to route scripted replies and find prompts."""
    title = f"{label} {uuid.uuid4().hex[:10]}"
    return c.post("/matters", json={"title": title, "parties": "State v. Unknown"}).json()["id"], title


def upload(c: httpx.Client, matter_id: str, name: str, content: bytes | str) -> dict:
    data = content.encode() if isinstance(content, str) else content
    r = c.post(f"/matters/{matter_id}/documents", files={"file": (name, data)})
    assert r.status_code == 200, r.text
    return r.json()


def answer(text="Direct answer.", claims=None, **extra) -> dict:
    return {"answer": text, "claims": claims or [], "missing_information": [], "contrary_authority": [], "uncertainty": "", **extra}


# ---- signed webhooks (the server verifies signatures for real; only the gateways behind them are stubbed) ----
import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402


def resend_headers(body: bytes, secret: str | None = None, msg_id: str | None = None, ts: int | None = None) -> dict:
    from lib import svix

    secret = secret or os.environ["RESEND_WEBHOOK_SECRET"]
    msg_id, ts = msg_id or f"msg_{uuid.uuid4().hex[:12]}", str(ts if ts is not None else int(time.time()))
    return {"svix-id": msg_id, "svix-timestamp": ts, "svix-signature": f"v1,{svix.sign(secret, msg_id, ts, body)}", "content-type": "application/json"}


def post_resend_event(event_type: str, email_id: str, *, bounce: dict | None = None, secret: str | None = None) -> httpx.Response:
    data: dict = {"email_id": email_id, "to": ["x@example.com"]}
    if bounce:
        data["bounce"] = bounce
    body = json.dumps({"type": event_type, "created_at": "2026-10-19T10:00:00Z", "data": data}).encode()
    with httpx.Client(base_url=API_URL, timeout=30.0) as c:
        return c.post("/webhooks/resend", content=body, headers=resend_headers(body, secret))


def stripe_headers(body: bytes, secret: str | None = None, ts: int | None = None) -> dict:
    secret = secret or os.environ["STRIPE_WEBHOOK_SECRET"]
    ts = ts if ts is not None else int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={ts},v1={sig}", "content-type": "application/json"}


def post_stripe_event(event_type: str, session_id: str, *, secret: str | None = None, ts: int | None = None) -> httpx.Response:
    body = json.dumps({"id": "evt_test", "object": "event", "type": event_type, "data": {"object": {"id": session_id, "object": "checkout.session"}}}).encode()
    with httpx.Client(base_url=API_URL, timeout=30.0) as c:
        return c.post("/webhook/stripe", content=body, headers=stripe_headers(body, secret, ts))


def mark_stub_paid(
    session_id: str, *, amount_total: int, currency: str = "inr", user_id: str | None = None, payment_status: str = "paid",
    subscription_id: str | None = None,
) -> None:
    row = {"session_id": session_id, "payment_status": payment_status, "amount_total": amount_total, "currency": currency, "metadata": {"user_id": user_id}}
    if subscription_id:
        row["subscription_id"] = subscription_id
    mongo().payment_stub.insert_one(row)


# ---- team helpers ----
def new_member(owner: httpx.Client, role: str = "LAWYER") -> httpx.Client:
    """Invite someone into the owner's organisation by email and accept the invitation as them."""
    tag = uuid.uuid4().hex[:10]
    email = f"m-{role.lower()}-{tag}@example.com"
    r = owner.post("/org/invites", json={"email": email, "role": role})
    assert r.status_code == 200, r.text
    mail = outbox(to=email, subject_has="invited")[-1]
    token = token_from_mail(mail, "token=")
    pw = f"Pw-{uuid.uuid4().hex}"
    c = httpx.Client(base_url=API_URL, timeout=30.0)
    a = c.post("/auth/accept-invite", json={"token": token, "full_name": f"{role.title()} Person", "password": pw, "accept_privacy": True})
    assert a.status_code == 200, a.text
    c.user = a.json()  # type: ignore[attr-defined]
    c.password = pw  # type: ignore[attr-defined]
    return c


def login_client(email: str, password: str) -> httpx.Client:
    c = httpx.Client(base_url=API_URL, timeout=30.0)
    r = c.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


def wait_for_mail(to: str, subject_has: str, timeout: float = 5.0) -> dict:
    """Mail sent in a background task shows up shortly after the response."""
    end = time.time() + timeout
    while time.time() < end:
        found = outbox(to=to, subject_has=subject_has)
        if found:
            return found[-1]
        time.sleep(0.1)
    raise AssertionError(f"no mail to {to} with subject containing {subject_has!r}")


# ---- in-process unit tests must not touch the shared database budget (it belongs to the server's event loop) ----
class InMemoryBudget:
    """Stands in for lib.aibudget.Budget in tests that call AI code directly. The real budget is tested in tests/test_ai_budget.py."""

    def __init__(self):
        self.used = 0.0

    async def reserve(self, est):
        self.used += est
        return "test"

    async def release(self, mid, est):
        self.used -= est

    async def settle(self, mid, est, actual, **kw):
        self.used += actual - est

    async def status(self):
        return {"exhausted": False, "used_inr": self.used}


@pytest.fixture(autouse=True)
def _in_memory_ai_budget(monkeypatch):
    from lib import aibudget

    monkeypatch.setattr(aibudget, "_instance", InMemoryBudget())
