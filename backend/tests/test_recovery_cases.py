"""Legal Recovery: 50 numbered cases (R01-R50), all invented, none stating what any law says.

R01-R15  the outstanding balance: plain arithmetic, exact to the paisa, owner-entered amounts only
R16-R25  the optional simple-interest sum: rate always from the owner, actual days over 365, part-payments reduce the base
R26-R33  the evidence checklist: names what is missing, never guesses what a file proves
R34-R42  route warnings: pointers to an advocate, never a deadline, section or verdict
R43-R50  the live API: privacy between businesses, validation, payments, drafting rules, resolve and reopen

The expected figures were worked out by hand from the rules in lib/balance.py and lib/interest.py, not copied from the code's output."""

from datetime import date

import pytest

from lib.balance import compute_balance
from lib.evidence_check import check_evidence, enclosures
from lib.interest import compute_simple_interest
from lib.route_checks import check_routes
from tests.conftest import stub
from tests.test_recovery_stage1 import draft_reply, new_case

TODAY = date(2026, 10, 19)


def case(**kw):
    base = {"amount": 50000, "currency": "INR", "payments": [], "charges": [], "credits": [], "intake": {}}
    base.update(kw)
    return base


def pay(amount, day="2026-08-01"):
    return {"amount": amount, "date": day}


# ---------------------------------------------------------------------------------------------
# R01-R15 balance
# ---------------------------------------------------------------------------------------------
BALANCES = [
    ("R01-full-invoice-unpaid", case(), 50000),
    ("R02-part-payment", case(payments=[pay(12000.5)]), 37999.5),
    ("R03-two-payments", case(payments=[pay(10000), pay(5000, "2026-09-01")]), 35000),
    ("R04-credit-note", case(credits=[{"label": "Returned goods", "amount": 2500, "reason": "credit note 14"}]), 47500),
    ("R05-documented-charge", case(charges=[{"label": "Freight", "amount": 800, "basis": "quotation dated 1 June"}]), 50800),
    ("R06-charge-without-basis-ignored", case(charges=[{"label": "Late fee", "amount": 1000, "basis": ""}]), 50000),
    ("R07-blank-basis-ignored", case(charges=[{"label": "Late fee", "amount": 1000, "basis": "   "}]), 50000),
    ("R08-charge-credit-and-payments", case(payments=[pay(10000), pay(5000)], credits=[{"amount": 2500}], charges=[{"label": "Freight", "amount": 800, "basis": "clause 3"}]), 33300),
    ("R09-one-crore-twenty-five-lakh", case(amount=12500000, payments=[pay(2500000)]), 10000000),
    ("R10-paise-are-exact", case(amount=1000.10, payments=[pay(333.33), pay(333.33)]), 333.44),
    ("R11-overpayment-gives-zero", case(payments=[pay(60000)]), 0),
    ("R12-credit-larger-than-invoice", case(credits=[{"label": "Whole order returned", "amount": 70000, "reason": "credit note 2"}]), 0),
]


@pytest.mark.parametrize("name,c,expected", BALANCES, ids=[b[0] for b in BALANCES])
def test_balance_cases(name, c, expected):
    assert compute_balance(c)["balance"] == expected


def test_R13_an_amount_found_in_a_document_never_replaces_the_one_the_owner_typed():
    b = compute_balance(case(amount=50000, detected_amount=55000))
    assert b["balance"] == 50000 and b["invoice_amount"] == 50000 and "different" in b["warnings"][0]


def test_R14_with_no_owner_amount_the_balance_is_zero_and_the_owner_is_asked_to_enter_one():
    b = compute_balance(case(amount=0, detected_amount=70000))
    assert b["balance"] == 0 and b["invoice_amount"] == 0 and "Enter the invoice amount yourself" in b["warnings"][0]


def test_R15_the_currency_is_kept_and_no_interest_is_ever_added_to_the_balance():
    b = compute_balance(case(currency="USD", due_date="2020-01-01", interest_rate_pct=24))
    assert b["currency"] == "USD" and b["balance"] == 50000


# ---------------------------------------------------------------------------------------------
# R16-R25 simple interest (rate is always the owner's)
# ---------------------------------------------------------------------------------------------
def interest(principal, rate, start, as_of, payments=()):
    return compute_simple_interest(principal, list(payments), start, rate, as_of)


def test_R16_one_full_year_at_twelve_per_cent():
    r = interest(100000, 12, "2025-01-01", "2026-01-01")
    assert r["days"] == 365 and r["interest"] == 12000.0 and r["total_due"] == 112000.0


def test_R17_seventy_three_days_is_a_fifth_of_a_year():
    assert interest(50000, 10, "2026-01-01", "2026-03-15")["interest"] == 1000.0  # 73 days: 50000 x 10% x 73/365


def test_R18_a_zero_rate_adds_nothing():
    r = interest(80000, 0, "2026-01-01", "2026-12-31")
    assert r["interest"] == 0 and r["total_due"] == 80000


def test_R19_an_as_of_date_before_the_due_date_gives_no_interest():
    r = interest(80000, 12, "2026-06-01", "2026-05-01")
    assert r["days"] == 0 and r["interest"] == 0


def test_R20_a_part_payment_lowers_the_base_from_the_day_it_was_received():
    r = interest(100000, 12, "2026-01-01", "2026-03-02", [("2026-01-31", 40000)])
    # 30 days on 100000 (986.30) + 30 days on 60000 (591.78), counted unrounded then rounded once
    assert r["interest"] == 1578.08 and r["principal_remaining"] == 60000 and r["total_due"] == 61578.08


def test_R21_a_payment_on_the_due_date_reduces_the_amount_interest_is_counted_on():
    r = interest(100000, 12, "2026-01-01", "2026-12-31", [("2026-01-01", 100000)])
    assert r["interest"] == 0 and r["principal_remaining"] == 0


def test_R22_a_leap_year_month_uses_the_actual_number_of_days():
    r = interest(36500, 10, "2024-02-01", "2024-03-01")
    assert r["days"] == 29 and r["interest"] == 290.0


def test_R23_a_payment_after_the_as_of_date_is_not_counted():
    r = interest(100000, 12, "2026-01-01", "2026-02-01", [("2026-06-01", 100000)])
    assert r["payments_counted"] == 0 and r["principal_remaining"] == 100000


@pytest.mark.parametrize("rate", [101, -1], ids=["R24-rate-above-100", "R25-negative-rate"])
def test_rates_outside_zero_to_one_hundred_are_refused(rate):
    with pytest.raises(ValueError):
        interest(1000, rate, "2026-01-01", "2026-02-01")


# ---------------------------------------------------------------------------------------------
# R26-R33 evidence checklist
# ---------------------------------------------------------------------------------------------
INVOICE = {"kind": "INVOICE", "filename": "inv.pdf"}
CHALLAN = {"kind": "DELIVERY_PROOF", "filename": "challan.jpg"}
CHAT = {"kind": "COMMUNICATION", "filename": "chat.txt"}


def test_R26_with_nothing_uploaded_invoice_and_delivery_proof_are_named_as_missing():
    assert set(check_evidence(case(), [])["required_missing"]) == {"The invoice or bill", "Proof the goods were delivered or the work was done"}


def test_R27_an_invoice_alone_still_leaves_delivery_proof_missing():
    assert check_evidence(case(), [INVOICE])["required_missing"] == ["Proof the goods were delivered or the work was done"]


def test_R28_invoice_and_delivery_proof_satisfy_the_required_items():
    assert check_evidence(case(), [INVOICE, CHALLAN])["required_missing"] == []


def test_R29_files_alone_are_not_complete_while_facts_are_missing():
    out = check_evidence(case(), [INVOICE, CHALLAN])
    assert not out["complete"] and {f["key"] for f in out["facts_missing"]} >= {"invoice_number", "due_date", "debtor_address"}


def test_R30_with_every_fact_and_document_the_checklist_is_complete():
    full = case(due_date="2026-09-01", creditor_address="1 Market Road", debtor_address="9 Lake View",
                intake={"invoice_number": "INV-1", "invoice_date": "2026-07-01", "supply_description": "50 chairs", "payment_terms": "30 days"})
    assert check_evidence(full, [INVOICE, CHALLAN])["complete"]


def test_R31_entered_payments_ask_for_a_payment_record():
    items = {i["key"]: i for i in check_evidence(case(payments=[pay(1000)]), [INVOICE, CHALLAN])["items"]}
    assert items["payments"]["status"] == "MISSING"
    items = {i["key"]: i for i in check_evidence(case(payments=[pay(1000)]), [INVOICE, CHALLAN, {"kind": "PAYMENT_RECORD", "filename": "bank.pdf"}])["items"]}
    assert items["payments"]["status"] == "PRESENT"


def test_R32_a_written_promise_to_pay_needs_the_message_that_contains_it():
    c = case(intake={"promise_to_pay": {"text": "I will pay on the 5th"}})
    assert any(i["key"] == "promise" and i["status"] == "MISSING" for i in check_evidence(c, [INVOICE, CHALLAN])["items"])
    assert not any(i["key"] == "promise" for i in check_evidence(c, [INVOICE, CHALLAN, CHAT])["items"])


def test_R33_enclosures_are_listed_in_a_fixed_order_with_plain_labels():
    proofs = [{"id": "3", "kind": "COMMUNICATION", "filename": "chat.txt"}, {"id": "1", "kind": "INVOICE", "filename": "inv.pdf"}, {"id": "2", "kind": "DELIVERY_PROOF", "filename": "c.jpg"}]
    assert enclosures(proofs) == ["Invoice or bill: inv.pdf", "Delivery or completion proof: c.jpg", "Messages or emails: chat.txt"]
    assert enclosures(proofs, picked=["2"]) == ["Delivery or completion proof: c.jpg"]


# ---------------------------------------------------------------------------------------------
# R34-R42 route warnings
# ---------------------------------------------------------------------------------------------
def routes(**kw):
    return check_routes(case(due_date="2026-09-01", **kw), TODAY)


def flag(r, key):
    return next((f for f in r["flags"] if f["key"] == key), None)


def test_R34_a_bounced_cheque_stops_the_ordinary_letter_and_names_no_deadline():
    r = routes(intake={"route": {"cheque_bounced": "yes"}})
    f = flag(r, "cheque")
    assert f["level"] == "STOP" and r["blocks_notice"] and not any(ch.isdigit() for ch in f["text"])


def test_R35_an_unsure_cheque_is_a_warning_not_a_block():
    r = routes(intake={"route": {"cheque_bounced": "unsure"}})
    assert flag(r, "cheque")["level"] == "WARN" and not r["blocks_notice"] and r["advocate_recommended"]


def test_R36_a_cheque_given_as_security_is_a_warning():
    assert flag(routes(intake={"route": {"cheque_given": "yes"}}), "cheque")["level"] == "WARN"


def test_R37_an_existing_case_stops_the_letter():
    r = routes(intake={"route": {"existing_proceedings": "yes"}})
    assert flag(r, "proceedings")["level"] == "STOP" and r["blocks_notice"]


def test_R38_insolvency_stops_the_letter():
    assert flag(routes(intake={"route": {"insolvency": "yes"}}), "insolvency")["level"] == "STOP"


def test_R39_a_dispute_names_the_disputed_parts_and_recommends_an_advocate():
    r = routes(intake={"disputes": {"quality": True, "delivery": True, "note": "says three arrived damaged"}})
    f = flag(r, "dispute")
    assert "quality" in f["text"] and "delivery" in f["text"] and r["advocate_recommended"] and not r["blocks_notice"]


@pytest.mark.parametrize("answer", ["yes", "unsure"], ids=["R40-msme-yes", "R41-msme-unsure"])
def test_msme_gets_information_and_questions_but_no_verdict_on_eligibility(answer):
    f = flag(routes(intake={"route": {"msme": answer}}), "msme")
    assert f["level"] == "INFO" and len(f["questions"]) >= 3 and "has not checked your eligibility" in f["text"]


def test_R42_an_ordinary_invoice_is_information_only_and_every_warning_stays_free_of_section_numbers():
    ordinary = routes(intake={"route": {"cheque_bounced": "no", "existing_proceedings": "no", "insolvency": "no"}})
    assert [f["key"] for f in routes()["flags"]] == ["unanswered"]   # until the questions are answered, nothing is called ordinary
    assert [f["key"] for f in ordinary["flags"]] == ["ordinary"] and not ordinary["advocate_recommended"]
    everything = routes(intake={"route": {"cheque_bounced": "yes", "existing_proceedings": "yes", "insolvency": "yes", "msme": "yes"}, "disputes": {"amount": True}})
    for f in everything["flags"]:
        assert "section" not in f["text"].lower() and "article" not in f["text"].lower(), f["key"]


# ---------------------------------------------------------------------------------------------
# R43-R50 the live API
# ---------------------------------------------------------------------------------------------
def test_R43_a_business_sees_only_its_own_cases(user_a, user_b):
    cid, _ = new_case(user_a)
    assert cid in [c["id"] for c in user_a.get("/recovery/cases").json()]
    assert cid not in [c["id"] for c in user_b.get("/recovery/cases").json()]


def test_R44_an_anonymous_visitor_cannot_list_or_open_cases(anon, user_a):
    cid, _ = new_case(user_a)
    assert anon.get("/recovery/cases").status_code == 401
    assert anon.get(f"/recovery/cases/{cid}").status_code == 401


def test_R45_invoice_dates_in_the_future_or_not_dates_are_refused(user_a):
    cid, _ = new_case(user_a)
    assert user_a.patch(f"/recovery/cases/{cid}/intake", json={"invoice_date": "2999-01-01"}).status_code == 422
    assert user_a.patch(f"/recovery/cases/{cid}/intake", json={"invoice_date": "31st of never"}).status_code == 422


def test_R46_a_charge_with_no_written_basis_is_refused_rather_than_silently_added(user_a):
    cid, _ = new_case(user_a)
    r = user_a.patch(f"/recovery/cases/{cid}/intake", json={"charges": [{"label": "Late fee", "amount": 900, "basis": ""}]})
    assert r.status_code == 422 and "written basis" in r.json()["detail"]


def test_R47_recording_and_removing_a_payment_moves_the_balance_exactly(user_a):
    cid, _ = new_case(user_a, amount=40000)
    paid = user_a.post(f"/recovery/cases/{cid}/payment", json={"amount": 15000.25})
    assert paid.status_code == 200, paid.text
    assert user_a.get(f"/recovery/cases/{cid}/readiness").json()["balance"]["balance"] == 24999.75
    pid = paid.json()["payments"][-1]["id"]
    assert user_a.delete(f"/recovery/cases/{cid}/payment/{pid}").status_code == 200
    assert user_a.get(f"/recovery/cases/{cid}/readiness").json()["balance"]["balance"] == 40000


def test_R48_a_draft_that_threatens_or_accuses_is_blocked_from_going_out(verified_a):
    cid, debtor = new_case(verified_a)
    stub("generic", draft_reply("\nPay today or we will have you arrested and call the police."), contains=debtor)
    assert verified_a.post(f"/recovery/cases/{cid}/notice").status_code == 200
    assert verified_a.get(f"/recovery/cases/{cid}/notice-preview").json()["blockers"]["blocked"]
    assert verified_a.get(f"/recovery/cases/{cid}/notice.pdf").status_code == 409


def test_R49_the_notice_carries_the_balance_the_code_worked_out_not_the_one_the_model_wrote(user_a):
    cid, debtor = new_case(user_a, amount=123456.78)
    wrong = draft_reply()
    wrong["notice"] = wrong["notice"].replace("The invoice remains unpaid.", "The invoice remains unpaid: you owe Rs 9,99,999.")
    stub("generic", wrong, contains=debtor)
    r = user_a.post(f"/recovery/cases/{cid}/notice")
    assert r.status_code == 200, r.text
    assert "= Balance due: 123,456.78 INR" in r.json()["notice_body"] and r.json()["notice_meta"]["balance"] == 123456.78


def test_R50_a_resolved_case_can_be_reopened_to_an_active_step(user_a):
    cid, _ = new_case(user_a)
    assert user_a.post(f"/recovery/cases/{cid}/resolve").json()["status"] == "RESOLVED"
    reopened = user_a.post(f"/recovery/cases/{cid}/reopen")
    assert reopened.status_code == 200 and reopened.json()["status"] != "RESOLVED"
