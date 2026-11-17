import pytest
"""Limitation warning (never invents a period) and demand-notice blockers: pure unit tests."""

import json
from datetime import date

from lib import limitation
from lib.limitation import assess, load_verified_rules
from lib.notice_checks import find_legal_references, find_placeholders, notice_blockers

TODAY = date(2026, 10, 19)

GOOD_RULE = {
    "id": "TEST-ONLY-1",
    "verified": True,
    "applies_to": "a made-up claim used only by this test",
    "period_years": 3,
    "citation": "Test Provision 1",
    "source_text": "Exact words would be pasted here.",
    "source_url": "https://example.com/source",
    "verified_by": "A. Lawyer",
    "verified_on": "2026-01-01",
}


# ---------- limitation ----------
def test_shipped_rules_file_has_no_entries_so_nothing_is_invented():
    assert load_verified_rules() == []  # until a lawyer adds a verified, sourced rule


def test_generic_mode_gives_age_and_a_lawyer_message_but_no_deadline():
    r = assess("2024-07-01", TODAY, rules=[])
    assert r["mode"] == "GENERIC" and r["rules"] == []
    assert r["age_text"] == "2 years and 3 months"
    assert "speak to a lawyer" in r["message"]
    assert not any(ch.isdigit() for ch in r["message"])  # no invented period in the text


def test_no_due_date_asks_for_it():
    assert assess(None, TODAY, rules=[])["mode"] == "NEEDS_DUE_DATE"
    assert assess("garbage", TODAY, rules=[])["mode"] == "NEEDS_DUE_DATE"


def test_verified_rule_computes_deadline_and_status():
    r = assess("2024-01-15", TODAY, rules=[GOOD_RULE])
    rule = r["rules"][0]
    assert r["mode"] == "VERIFIED_RULES"
    assert rule["deadline"] == "2027-01-15" and rule["days_left"] == 88 and rule["status"] == "SOON"
    assert assess("2025-10-01", TODAY, rules=[GOOD_RULE])["rules"][0]["status"] == "OK"
    assert rule["citation"] == "Test Provision 1" and rule["verified_by"] == "A. Lawyer"
    assert assess("2022-01-15", TODAY, rules=[GOOD_RULE])["rules"][0]["status"] == "PASSED"


def test_unverified_or_incomplete_rules_are_ignored(tmp_path):
    bad = [
        {**GOOD_RULE, "verified": False},
        {**GOOD_RULE, "source_text": ""},
        {**GOOD_RULE, "verified_by": ""},
        {**GOOD_RULE, "period_years": "three"},
        {**GOOD_RULE, "period_years": 0},
        "not a dict",
    ]
    p = tmp_path / "rules.json"
    p.write_text(json.dumps({"rules": bad + [GOOD_RULE]}))
    assert [r["id"] for r in load_verified_rules(p)] == ["TEST-ONLY-1"]
    p.write_text("{not json")
    assert load_verified_rules(p) == []
    assert load_verified_rules(tmp_path / "missing.json") == []


def test_leap_day_deadline_does_not_crash():
    assert limitation._add_years(date(2024, 2, 29), 3) == date(2027, 2, 28)


# ---------- notice blockers ----------
def test_placeholders_are_found():
    text = "Dear [name],\nPlease pay within 15 days.\nAddress: [ ]\nDate: [date]\nRepeat [name]"
    assert find_placeholders(text) == ["[name]", "[ ]", "[date]"]


def test_clean_notice_is_not_blocked():
    text = (
        "Date: 19 Oct 2026\nTo: Sample Debtor, 12 Main Road, Pune\nFrom: Visual Traders\n"
        "You owe Rs 40,000 for goods delivered on 1 March 2026. Please pay within 15 days."
    )
    assert notice_blockers(text) == {"placeholders": [], "legal_references": [], "risky_language": [], "amount_mismatches": [], "service_claims": [], "statement_changed": False, "figures_changed": False, "blocked": False}


def test_legal_references_are_flagged_for_removal_or_lawyer_verification():
    for bad in (
        "This is a breach under Section 73 of the Contract Act.",
        "See the Limitation Act, 1963.",
        "Under Article 113 you must pay.",
        "As held in Sharma vs Verma the debt is due.",
        "Relief under CPC Order 37 will be sought.",
    ):
        b = notice_blockers(bad)
        assert b["legal_references"] and b["blocked"], bad


def test_ordinary_words_are_not_mistaken_for_law():
    text = "Please act promptly. Our rule is simple: pay by the order date. Section of the shop is closed."
    assert find_legal_references(text) == []


@pytest.mark.parametrize(
    "line",
    [
        "Pay up or we will have you arrested.",
        "We will file a police complaint.",
        "This is cheating and fraud.",
        "You lied about the delivery.",
        "We will take criminal action.",
    ],
)
def test_threats_and_accusations_block_a_notice(line):
    check = notice_blockers("Please pay Rs 40,000 within 15 days. " + line)
    assert check["blocked"] and check["risky_language"]


def test_template_markers_left_behind_are_treated_as_blanks():
    assert notice_blockers("Total: {{STATEMENT}}")["placeholders"] == ["{{STATEMENT}}"]
