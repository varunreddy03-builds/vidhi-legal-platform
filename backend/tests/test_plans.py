"""Free vs Pro for Legal Intelligence, and the monthly subscription that moves an organisation between them.
Legal Recovery is free for everyone and must never be limited by a plan."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import answer, mark_stub_paid, mongo, new_matter, new_member, stripe_headers, stub, upload, verify_email, set_plan
from tests.test_recovery_stage1 import draft_reply, new_case

SUB = "sub_test_"


def utc(days: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def ent(c) -> dict:
    return c.get("/auth/entitlement").json()


def subscribe(c, days_left: float = 30, sub_id: str | None = None) -> str:
    """Run a real checkout through the stub gateway and settle it, as Stripe would."""
    set_plan(c, "FREE")
    r = c.post("/payments/checkout", json={"package_id": "vidhi_pro", "origin_url": "http://localhost:3000"})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    sub_id = sub_id or SUB + uuid.uuid4().hex[:10]
    mongo().subscription_stub.insert_one({"id": sub_id, "status": "active", "current_period_end": utc(days_left), "cancel_at_period_end": False, "customer_id": "cus_t"})
    mark_stub_paid(sid, amount_total=199900, user_id=c.user["id"], subscription_id=sub_id)
    assert c.get(f"/payments/status/{sid}").json()["payment_status"] == "paid"
    return sub_id


def event(kind: str, obj: dict):
    import httpx
    from tests.conftest import API_URL

    body = json.dumps({"id": "evt_" + uuid.uuid4().hex[:8], "object": "event", "type": kind, "data": {"object": obj}}).encode()
    with httpx.Client(base_url=API_URL, timeout=30.0) as c:
        return c.post("/webhook/stripe", content=body, headers=stripe_headers(body))


@pytest.fixture
def free_user(user_a):
    set_plan(user_a, "FREE")
    return user_a


# ---------------------------------------------------------------------------------------------
# The free plan: real, but limited and light
# ---------------------------------------------------------------------------------------------
def test_new_accounts_start_free_with_the_comparison_attached():
    import httpx
    from tests.conftest import API_URL

    with httpx.Client(base_url=API_URL, timeout=30.0) as c:
        r = c.post("/auth/signup", json={"email": f"free-{uuid.uuid4().hex[:8]}@example.com", "password": f"Pw-{uuid.uuid4().hex}", "full_name": "F", "organization_name": "F Org", "accept_privacy": True})
        assert r.status_code == 200
        e = c.get("/auth/entitlement").json()
    assert e["plan"] == "FREE" and e["tier"] == "free" and e["intelligence_access"] is True and e["recovery_access"] is True
    assert e["limits"]["price"] == {"amount": 1999.0, "currency": "inr", "interval": "month"}
    assert e["limits"]["free"]["ai_per_day"] == 5 and len(e["limits"]["free"]["locked"]) == 2 and e["limits"]["pro"]["locked"] == []


def test_free_research_uses_only_the_light_models_and_a_small_reading_budget(free_user):
    mid, title = new_matter(free_user, "FreeResearch")
    upload(free_user, mid, "big.txt", ("The agreement was signed on 3 March. " * 700))
    stub("research", answer("A short answer."), contains=title)
    assert free_user.post("/research", json={"question": "when was it signed?", "matter_id": mid}).status_code == 200
    call = mongo().ai_calls.find_one({"purpose": "research", "prompt": {"$regex": title}})
    assert call["tier"] == "free"
    assert "WHAT YOU ARE SHOWN" in call["prompt"]
    passages = call["prompt"].split("PASSAGES FROM THE DOCUMENTS:")[1]
    assert len(passages) < 14000  # the free reading budget, not the full one


def test_pro_research_gets_the_full_tier_and_reading_budget(user_a):
    mid, title = new_matter(user_a, "ProResearch")
    upload(user_a, mid, "big.txt", ("The agreement was signed on 3 March. " * 700))
    stub("research", answer("A fuller answer."), contains=title)
    assert user_a.post("/research", json={"question": "when was it signed?", "matter_id": mid}).status_code == 200
    call = mongo().ai_calls.find_one({"purpose": "research", "prompt": {"$regex": title}})
    assert call["tier"] == "full"
    assert len(call["prompt"].split("PASSAGES FROM THE DOCUMENTS:")[1]) > 20000


def test_complex_work_is_a_pro_feature(free_user):
    mid, title = new_matter(free_user, "Locked")
    doc = upload(free_user, mid, "services-agreement.txt", "SERVICES AGREEMENT between A and B. Indemnity: A shall indemnify B. Termination: 30 days.")
    mongo().documents.update_one({"id": doc["id"]}, {"$set": {"doc_class": "CONTRACT"}})
    r = free_user.post(f"/matters/{mid}/synthesize")
    assert r.status_code == 402 and "Pro feature" in r.json()["detail"] and "upgrade" in r.json()["detail"].lower()
    r = free_user.post(f"/documents/{doc['id']}/analyze")
    assert r.status_code == 402 and "contract" in r.json()["detail"].lower()
    assert mongo().ai_calls.count_documents({"prompt": {"$regex": title}}) == 0  # nothing reached a model
    # the same user on Pro is not refused
    set_plan(free_user, "PRO")
    stub("synthesize", {"people": [], "inconsistencies": [], "unclear": []}, contains=title)
    assert free_user.post(f"/matters/{mid}/synthesize").status_code == 200


def test_the_free_plan_has_a_small_daily_allowance_shared_by_the_organisation(free_user):
    verify_email(free_user)
    other = new_member(free_user, "LAWYER")
    for i in range(5):
        stub("research", answer(f"Answer {i}."), contains=f"allowance-{i}")
    sent = [free_user.post("/research", json={"question": f"allowance-{i}"}).status_code for i in range(3)]
    sent += [other.post("/research", json={"question": f"allowance-{i}"}).status_code for i in (3, 4)]
    assert sent == [200] * 5
    r = free_user.post("/research", json={"question": "one more"})
    assert r.status_code == 402 and "free AI requests" in r.json()["detail"] and "Pro" in r.json()["detail"]


def test_recovery_is_never_limited_by_the_plan(free_user):
    cid, debtor = new_case(free_user)
    for _ in range(7):  # more than the free daily allowance
        stub("generic", draft_reply(), contains=debtor)
        assert free_user.post(f"/recovery/cases/{cid}/notice").status_code == 200
    assert ent(free_user)["recovery_access"] is True
    call = mongo().ai_calls.find_one({"session_id": {"$regex": f"recovery-notice-{cid}"}})
    assert call["tier"] == "full"  # Recovery runs on the normal models


def test_a_citation_lookup_is_not_an_ai_request_and_stays_available_on_free(free_user):
    for _ in range(8):
        assert free_user.post("/verify-citation", json={"citation": "Nonexistent Act, 1900"}).status_code in (200, 422)


# ---------------------------------------------------------------------------------------------
# The subscription
# ---------------------------------------------------------------------------------------------
def test_a_first_payment_starts_pro_until_the_end_of_the_paid_month(free_user):
    sub = subscribe(free_user, days_left=30)
    e = ent(free_user)
    assert e["plan"] == "PRO" and e["tier"] == "pro" and e["subscription_status"] == "active" and e["cancel_at_period_end"] is False
    until = datetime.fromisoformat(e["pro_until"].replace("Z", "+00:00"))
    assert abs((until - utc(30)).total_seconds()) < 120
    row = mongo().users.find_one({"id": free_user.user["id"]})
    assert row["subscription_id"] == sub and row["stripe_customer_id"]
    assert free_user.post("/payments/checkout", json={"package_id": "vidhi_pro", "origin_url": "http://localhost:3000"}).status_code == 409  # no double subscription


def test_pro_ends_by_itself_when_the_paid_period_runs_out(free_user):
    subscribe(free_user, days_left=30)
    mongo().users.update_one({"id": free_user.user["id"]}, {"$set": {"pro_until": utc(-3)}})  # lapsed beyond the grace period
    assert ent(free_user)["plan"] == "FREE"
    mid, _ = new_matter(free_user, "Lapsed")
    assert free_user.post(f"/matters/{mid}/synthesize").status_code == 402
    mongo().users.update_one({"id": free_user.user["id"]}, {"$set": {"pro_until": utc(-1)}})  # a day late: still inside the grace period
    assert ent(free_user)["plan"] == "PRO"


def test_a_renewal_extends_pro_and_adds_a_receipt_once(free_user):
    sub = subscribe(free_user, days_left=1)
    mongo().subscription_stub.update_one({"id": sub}, {"$set": {"current_period_end": utc(31)}})
    inv = {"id": "in_" + uuid.uuid4().hex[:10], "subscription": sub, "billing_reason": "subscription_cycle", "amount_paid": 199900, "currency": "inr"}
    for _ in range(2):  # Stripe may deliver an event twice
        assert event("invoice.paid", inv).status_code == 200
    until = datetime.fromisoformat(ent(free_user)["pro_until"].replace("Z", "+00:00"))
    assert abs((until - utc(31)).total_seconds()) < 120
    history = [h for h in free_user.get("/payments/history").json() if h["session_id"] == inv["id"]]
    assert len(history) == 1 and history[0]["amount"] == 1999.0 and history[0]["payment_status"] == "paid"
    from tests.conftest import outbox

    assert outbox(to=free_user.user["email"], subject_has="renewal receipt")


def test_a_failed_renewal_keeps_pro_only_to_the_end_of_the_paid_period(free_user):
    sub = subscribe(free_user, days_left=10)
    mongo().subscription_stub.update_one({"id": sub}, {"$set": {"status": "past_due"}})
    assert event("invoice.payment_failed", {"id": "in_x", "subscription": sub}).status_code == 200
    e = ent(free_user)
    assert e["subscription_status"] == "past_due" and e["plan"] == "PRO"  # paid-for days are still paid for
    mongo().users.update_one({"id": free_user.user["id"]}, {"$set": {"pro_until": utc(-5)}})
    assert ent(free_user)["plan"] == "FREE"


def test_cancelling_stops_renewal_but_keeps_pro_until_the_period_ends(free_user):
    subscribe(free_user, days_left=20)
    r = free_user.post("/payments/subscription/cancel")
    assert r.status_code == 200 and r.json()["cancel_at_period_end"] is True
    e = ent(free_user)
    assert e["cancel_at_period_end"] is True and e["plan"] == "PRO"
    assert free_user.post("/payments/subscription/resume").json()["cancel_at_period_end"] is False
    assert ent(free_user)["cancel_at_period_end"] is False


def test_the_subscription_ended_event_is_applied_and_resubscribing_is_possible(free_user):
    sub = subscribe(free_user, days_left=5)
    mongo().subscription_stub.update_one({"id": sub}, {"$set": {"status": "canceled", "current_period_end": utc(-4)}})
    assert event("customer.subscription.deleted", {"id": sub}).status_code == 200
    e = ent(free_user)
    assert e["plan"] == "FREE" and e["subscription_status"] == "canceled"
    again = free_user.post("/payments/checkout", json={"package_id": "vidhi_pro", "origin_url": "http://localhost:3000"})
    assert again.status_code == 200


def test_subscription_events_for_unknown_subscriptions_change_nothing(free_user):
    assert event("customer.subscription.updated", {"id": "sub_unknown"}).status_code == 200
    assert event("invoice.paid", {"id": "in_1", "subscription": "sub_unknown", "billing_reason": "subscription_cycle"}).status_code == 200
    assert ent(free_user)["plan"] == "FREE"


def test_the_team_shares_the_subscription_and_only_the_owner_manages_it(free_user):
    verify_email(free_user)
    lawyer, admin = new_member(free_user, "LAWYER"), new_member(free_user, "ADMIN")
    subscribe(free_user, days_left=30)
    for c in (lawyer, admin):
        assert ent(c)["plan"] == "PRO"
        assert c.post("/payments/checkout", json={"package_id": "vidhi_pro", "origin_url": "http://localhost:3000"}).status_code == 403
        assert c.post("/payments/subscription/cancel").status_code == 403
    set_plan(free_user, "PRO", pro_until=utc(-10), subscription_id="sub_old")  # lapsed
    assert ent(lawyer)["plan"] == "FREE"


def test_cancel_without_a_subscription_is_a_clear_refusal(free_user):
    r = free_user.post("/payments/subscription/cancel")
    assert r.status_code == 409 and "no active subscription" in r.json()["detail"]


def test_an_account_upgraded_before_subscriptions_existed_stays_pro(free_user):
    set_plan(free_user, "PRO")  # no paid-until date: a legacy one-time upgrade
    assert ent(free_user)["plan"] == "PRO"


def test_the_free_plan_shows_how_much_of_todays_allowance_is_used(free_user):
    e = ent(free_user)
    assert (e["ai_used_today"], e["ai_limit_today"]) == (0, 5)
    stub("research", answer("An answer."), contains="usage-count")
    assert free_user.post("/research", json={"question": "usage-count"}).status_code == 200
    assert ent(free_user)["ai_used_today"] == 1
    set_plan(free_user, "PRO")
    assert (ent(free_user)["ai_used_today"], ent(free_user)["ai_limit_today"]) == (0, None)


def test_refused_attempts_do_not_inflate_the_daily_counter(free_user):
    """Found by the code review: every refused request used to be counted, so a free account could read '8 of 5 used'."""
    for i in range(5):
        stub("research", answer("An answer."), contains=f"count-cap-{i}")
        assert free_user.post("/research", json={"question": f"count-cap-{i}"}).status_code == 200
    for _ in range(3):
        assert free_user.post("/research", json={"question": "count-cap-over"}).status_code == 402
    e = ent(free_user)
    assert (e["ai_used_today"], e["ai_limit_today"]) == (5, 5)


def test_a_failed_ai_call_gives_the_request_back_exactly_once(free_user):
    stub("research", "__FAIL__", contains="refund-once")
    assert free_user.post("/research", json={"question": "refund-once"}).status_code == 502
    assert ent(free_user)["ai_used_today"] == 0
    stub("research", answer("Fine."), contains="refund-ok")
    assert free_user.post("/research", json={"question": "refund-ok"}).status_code == 200
    assert ent(free_user)["ai_used_today"] == 1  # the earlier failure did not take a second refund away from this one


def test_a_reply_of_an_unexpected_shape_is_a_502_and_is_refunded_not_a_crash(free_user):
    """Found by the code review: sources as a number or a list of objects crashed the analysis with a 500 after the request was charged."""
    for i, bad in enumerate(({"summary": "Fine.", "options": [{"idea": "x", "sources": 5, "risks": 5}], "confidence": "low"},
                             {"summary": "Fine.", "options": [{"idea": "x", "sources": [{"a": 1}], "risks": [{"b": 2}]}], "assumptions": 7, "confidence": "low"})):
        stub("research", bad, contains=f"shape-{i}")
        r = free_user.post("/analysis/strategy", json={"question": f"A question about a dispute shape-{i}"})
        assert r.status_code == 200, r.text  # coerced: wrong-typed fields are dropped, the rest is shown
        assert r.json()["options"][0]["sources"] == [] and r.json()["options"][0]["risks"] == []
    assert ent(free_user)["ai_used_today"] == 2

