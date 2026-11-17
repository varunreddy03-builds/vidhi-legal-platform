"""Instant decisions: scoring, filtering and categorising in plain rules (no AI), with reasons a person can read."""

from datetime import date, datetime, timedelta, timezone

import pytest

from lib import decide
from tests.conftest import mongo
from tests.test_recovery_stage1 import new_case

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 9, tzinfo=timezone.utc)


def case(**kw):
    return {"status": "DRAFT", "amount": 10000, "paid_amount": 0, "updated_at": NOW, **kw}


# ---- scoring cases ----
def test_a_fresh_small_case_is_calm():
    p = decide.case_priority(case(), TODAY)
    assert p == {"score": 0, "level": "ok", "reasons": []}


def test_a_resolved_case_is_done_whatever_else_is_true():
    assert decide.case_priority(case(status="RESOLVED", debtor_email_status="BOUNCED", amount=10**7), TODAY)["level"] == "done"


def test_a_bounced_notice_is_urgent_and_says_why():
    p = decide.case_priority(case(status="SENT_FOR_REVIEW", debtor_email_status="BOUNCED"), TODAY)
    assert p["level"] == "soon" and p["reasons"][0].startswith("The notice email did not reach")
    big = decide.case_priority(case(status="SENT_FOR_REVIEW", debtor_email_status="BOUNCED", amount=500000, due_date="2025-01-01"), TODAY)
    assert big["level"] == "urgent" and len(big["reasons"]) >= 3 and big["score"] <= 100


def test_old_dues_and_large_amounts_raise_the_score_but_paid_money_does_not_count():
    old = decide.case_priority(case(due_date="2025-06-01", amount=120000), TODAY)
    assert old["score"] == 22 + 14 and any("over a year" in r for r in old["reasons"])
    paid_down = decide.case_priority(case(due_date="2025-06-01", amount=120000, paid_amount=110000), TODAY)
    assert paid_down["score"] == 22  # only 10,000 is still owed
    assert decide.case_priority(case(due_date="2026-10-25"), TODAY)["score"] == 0  # not due yet


def test_idle_cases_and_waiting_notices_are_noticed():
    assert decide.case_priority(case(status="SENT_FOR_REVIEW", updated_at=NOW - timedelta(days=20)), TODAY)["score"] == 18 + 0
    assert any("a month" in r for r in decide.case_priority(case(updated_at=NOW - timedelta(days=45)), TODAY)["reasons"])
    assert decide.case_priority(case(status="SENT_FOR_REVIEW", updated_at=NOW - timedelta(days=3)), TODAY)["score"] == 0


def test_a_snoozed_case_drops_down():
    base = case(status="NOTICE_READY", debtor_email_status="BOUNCED")
    snoozed = {**base, "snooze_until": NOW + timedelta(days=5)}
    assert decide.case_priority(snoozed, TODAY)["score"] == decide.case_priority(base, TODAY)["score"] - 25


def test_the_same_input_always_gives_the_same_answer_and_bad_dates_do_not_crash():
    c = case(due_date="not-a-date", status="NOTICE_READY")
    assert decide.case_priority(c, TODAY) == decide.case_priority(c, TODAY)


def test_bands_and_rules_are_generic():
    rules = [decide.Rule("a", "A", 5, lambda c: c["x"] > 1), decide.Rule("b", "B", 7, lambda c: c["x"] > 5)]
    assert decide.evaluate({"x": 3}, rules) == (5, [{"id": "a", "label": "A", "points": 5}])
    assert decide.evaluate({"x": 9}, rules)[0] == 12
    assert decide.band(12, [(10, "high"), (5, "mid")], "low") == "high" and decide.band(1, [(10, "high")], "low") == "low"


# ---- categorising questions ----
@pytest.mark.parametrize("text,category,route", [
    ("My customer has not paid my invoice for two months. What can I do?", "money_recovery", "recovery"),
    ("He borrowed money from me and refuses to return my money", "money_recovery", "recovery"),
    ("मेरे ग्राहक ने बिल का भुगतान नहीं किया, पैसे नहीं दिए", "money_recovery", "recovery"),
    ("मुझे उधार दिया पैसा वापस चाहिए, बकाया है", "money_recovery", "recovery"),
    ("My landlord will not return the security deposit", "rent_property", "ask"),
    ("किरायेदार ने किराया नहीं दिया", "rent_property", "ask"),
    ("The phone I bought is defective and they refuse a refund", "consumer", "ask"),
    ("My employer terminated me and has not paid my salary", "employment", "ask"),
    ("What should I check in this agreement before signing?", "contract", "ask"),
    ("We are going for a divorce, who gets custody?", "family", "ask"),
    ("The police came and arrested my brother, he needs bail", "urgent_safety", "lawyer"),
    ("पुलिस ने गिरफ्तार किया है, जमानत कैसे मिलेगी", "urgent_safety", "lawyer"),
])
def test_questions_are_sorted_by_what_they_are_about(text, category, route):
    out = decide.categorise(text)
    assert out["category"] == category and out["route"] == route and out["matched"]


def test_something_urgent_beats_money_when_both_appear():
    assert decide.categorise("The police arrested me because he says I have not paid")["category"] == "urgent_safety"


def test_vague_text_has_no_category_and_words_inside_words_do_not_count():
    assert decide.categorise("Hello, I would like some help please")["category"] is None
    assert decide.categorise("I am willing to wait")["category"] is None  # "will" must not match "willing"
    assert decide.categorise("")["category"] is None


def test_confidence_reflects_how_clear_it_is():
    assert decide.categorise("my customer has not paid the unpaid invoice, he owes me money")["confidence"] == "high"
    assert decide.categorise("loan agreement")["confidence"] in ("low", "medium")


# ---- the routes ----
def test_open_cases_come_back_most_pressing_first(user_a):
    calm, _ = new_case(user_a)
    hot, _ = new_case(user_a)
    mongo().recovery_cases.update_one({"id": hot}, {"$set": {"debtor_email_status": "BOUNCED", "due_date": "2024-01-01", "amount": 300000, "status": "SENT_FOR_REVIEW"}})
    rows = user_a.get("/decide/cases").json()
    ids = [r["case_id"] for r in rows]
    assert ids.index(hot) < ids.index(calm)
    top = rows[ids.index(hot)]
    assert top["level"] == "urgent" and top["reasons"]


def test_resolved_cases_are_left_out_and_other_organisations_are_never_shown(user_a, user_b):
    done, _ = new_case(user_a)
    mongo().recovery_cases.update_one({"id": done}, {"$set": {"status": "RESOLVED"}})
    mine, _ = new_case(user_a)
    assert {r["case_id"] for r in user_a.get("/decide/cases").json()} >= {mine} and done not in {r["case_id"] for r in user_a.get("/decide/cases").json()}
    assert mine not in {r["case_id"] for r in user_b.get("/decide/cases").json()}


def test_the_question_route(user_a, anon):
    r = user_a.post("/decide/question", json={"text": "my customer has not paid the invoice"})
    assert r.status_code == 200 and r.json()["category"] == "money_recovery" and r.json()["route"] == "recovery"
    assert user_a.post("/decide/question", json={"text": ""}).status_code == 422
    assert anon.post("/decide/question", json={"text": "hi"}).status_code in (401, 403)
    assert anon.get("/decide/cases").status_code in (401, 403)