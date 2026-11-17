"""Recovery stage 1: intake, transparent balance, evidence checklist, route warnings, notice drafting rules.

Calculation and warning logic is tested directly (pure functions); the API tests drive the real routes with the
scripted model, so what the model "says" is under the test's control."""

import uuid
from datetime import date, timedelta

import pytest

from lib.balance import compute_balance, owed_amount
from lib.evidence_check import check_evidence
from lib.route_checks import check_routes
from tests.conftest import mongo, stub, verify_email

TODAY = date(2026, 10, 19)


def case(**kw):
    base = {"amount": 50000, "currency": "INR", "payments": [], "charges": [], "credits": [], "intake": {}}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------------------------
def test_full_invoice_unpaid():
    b = compute_balance(case())
    assert b["balance"] == 50000 and b["payments_total"] == 0 and not b["overpaid"]


def test_partial_payment():
    assert compute_balance(case(payments=[{"amount": 12000.5, "date": "2026-08-01"}]))["balance"] == 37999.5


def test_multiple_payments_credits_and_a_documented_charge():
    b = compute_balance(case(
        payments=[{"amount": 10000, "date": "2026-08-01"}, {"amount": 5000, "date": "2026-09-01"}],
        credits=[{"label": "Return of 2 units", "amount": 2500, "reason": "credit note 14"}],
        charges=[{"label": "Delivery", "amount": 800, "basis": "clause 3 of the agreement"}],
    ))
    assert b["balance"] == 50000 + 800 - 2500 - 15000
    assert [l["kind"] for l in b["lines"]] == ["INVOICE", "CHARGE", "CREDIT", "PAYMENT", "PAYMENT"]
    assert owed_amount(case(credits=[{"amount": 2500}], charges=[{"amount": 800, "basis": "x"}])) == 48300


def test_a_charge_without_a_written_basis_is_not_counted_and_is_listed_as_ignored():
    b = compute_balance(case(charges=[{"label": "Late fee", "amount": 1000, "basis": "  "}]))
    assert b["balance"] == 50000 and b["ignored_charges"][0]["label"] == "Late fee"


def test_no_interest_or_penalty_is_ever_added():
    b = compute_balance(case(due_date="2020-01-01", interest_rate_pct=24))
    assert b["balance"] == 50000 and "Interest" in b["formula"]


def test_money_is_exact_not_floating_point():
    assert compute_balance(case(amount=0.3, payments=[{"amount": 0.1, "date": "2026-01-01"}, {"amount": 0.1, "date": "2026-01-02"}]))["balance"] == 0.1


def test_overpayment_gives_zero_balance_and_a_warning():
    b = compute_balance(case(payments=[{"amount": 60000, "date": "2026-01-01"}]))
    assert b["balance"] == 0 and b["overpaid"] and b["warnings"]


def test_the_amount_an_ai_found_never_replaces_the_amount_the_owner_entered():
    b = compute_balance(case(amount=50000, detected_amount=55000))
    assert b["invoice_amount"] == 50000 and "different" in b["warnings"][0]
    nothing = compute_balance(case(amount=0, detected_amount=55000))
    assert nothing["invoice_amount"] == 0 and nothing["suggested_amount"] == 55000


# ---------------------------------------------------------------------------------------------
# Evidence checklist
# ---------------------------------------------------------------------------------------------
def test_missing_invoice_and_delivery_evidence_is_named():
    out = check_evidence(case(), [])
    assert set(out["required_missing"]) == {"The invoice or bill", "Proof the goods were delivered or the work was done"}
    assert not out["complete"] and any(f["key"] == "invoice_number" for f in out["facts_missing"])


def test_labelled_uploads_satisfy_the_checklist_and_a_promise_needs_its_message():
    proofs = [{"kind": "INVOICE", "filename": "inv.pdf"}, {"kind": "DELIVERY_PROOF", "filename": "challan.jpg"}]
    out = check_evidence(case(intake={"promise_to_pay": {"text": "I will pay on 5th"}}), proofs)
    assert out["required_missing"] == []
    assert any(i["key"] == "promise" and i["status"] == "MISSING" for i in out["items"])


# ---------------------------------------------------------------------------------------------
# Route warnings
# ---------------------------------------------------------------------------------------------
def routes(**kw):
    return check_routes(case(due_date="2026-09-01", **kw), TODAY)


def test_ordinary_unpaid_invoice_is_just_information():
    r = routes(intake={"route": {"cheque_bounced": "no", "existing_proceedings": "no", "insolvency": "no"}})  # unanswered questions are NOT called ordinary (see the next test)
    assert [f["key"] for f in r["flags"]] == ["ordinary"] and not r["blocks_notice"] and not r["advocate_recommended"]


def test_dispute_warns_and_recommends_an_advocate_without_blocking():
    r = routes(intake={"disputes": {"delivery": True, "note": "says it never came"}})
    assert any(f["key"] == "dispute" for f in r["flags"]) and r["advocate_recommended"] and not r["blocks_notice"]


def test_bounced_cheque_stops_an_ordinary_letter_without_stating_a_deadline():
    r = routes(intake={"route": {"cheque_bounced": "yes"}})
    f = next(f for f in r["flags"] if f["key"] == "cheque")
    assert f["level"] == "STOP" and r["blocks_notice"]
    assert "VIDHI cannot tell you the deadline" in f["text"] and not any(ch.isdigit() for ch in f["text"])


@pytest.mark.parametrize("key", ["existing_proceedings", "insolvency"])
def test_existing_proceedings_and_insolvency_stop_the_letter(key):
    assert routes(intake={"route": {key: "yes"}})["blocks_notice"]


def test_msme_gets_information_and_questions_but_no_eligibility_verdict():
    f = next(f for f in routes(intake={"route": {"msme": "yes"}})["flags"] if f["key"] == "msme")
    assert f["level"] == "INFO" and len(f["questions"]) >= 3
    assert "has not checked your eligibility" in f["text"] and "MSME Samadhaan" in f["text"]


def test_an_old_claim_warns_by_age_only_and_never_names_a_period():
    old = (TODAY - timedelta(days=900)).isoformat()
    f = next(f for f in check_routes(case(due_date=old), TODAY)["flags"] if f["key"] == "limitation")
    assert f["level"] == "WARN" and "VIDHI does not know your deadline" in f["text"]
    assert not any(w in f["text"].lower() for w in ("three years", "3 years", "article", "section"))


def test_missing_due_date_is_flagged():
    assert any(f["key"] == "due_date" for f in check_routes(case(), TODAY)["flags"])


def test_a_verified_rule_that_has_passed_stops_the_letter(monkeypatch):
    import lib.limitation as lim

    rule = {"id": "r1", "applies_to": "Test claim", "period_years": 1, "citation": "Fictional Act s.1", "source_text": "x",
            "source_url": "https://example.com", "verified_by": "Test Lawyer", "verified_on": "2026-01-01", "verified": True}
    monkeypatch.setattr(lim, "load_verified_rules", lambda path=None: [rule])
    r = check_routes(case(due_date="2024-01-01"), TODAY)
    assert r["blocks_notice"] and any(f["key"] == "limitation" and f["level"] == "STOP" for f in r["flags"])


# ---------------------------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------------------------
def new_case(c, debtor=None, amount=40000):
    debtor = debtor or f"Debtor {uuid.uuid4().hex[:8]}"
    cid = c.post("/recovery/cases", json={"creditor_name": "A Traders", "debtor_name": debtor, "amount": amount}).json()["id"]
    r = c.patch(f"/recovery/cases/{cid}/details", json={"creditor_address": "1 Market Road, Pune", "debtor_address": "9 Lake View, Mumbai", "due_date": "2026-08-01"})
    assert r.status_code == 200, r.text
    return cid, debtor


def draft_reply(body_extra=""):
    return {"notice": "Date: 19 Oct 2026\nTo: customer\n\nSubject: Unpaid invoice\n\n1. The invoice remains unpaid.\n\n{{STATEMENT}}\n\n"
            "Please pay the balance due within 15 days or reply saying what is disputed.\n\n{{ENCLOSURES}}\n\nYours faithfully, A Traders\n"
            "This is a draft to be reviewed before sending." + body_extra}


def upload_proof(c, cid, name, data, kind="OTHER"):
    return c.post(f"/recovery/cases/{cid}/proofs", files={"file": (name, data)}, data={"kind": kind})


def test_intake_is_saved_validated_and_charges_need_a_basis(user_a):
    cid, _ = new_case(user_a)
    ok = user_a.patch(f"/recovery/cases/{cid}/intake", json={
        "invoice_number": "INV-17", "invoice_date": "2026-07-01", "supply_description": "50 chairs",
        "payment_terms": "30 days", "disputes": {"quality": True, "note": "says 3 are damaged"},
        "route": {"msme": "yes"}, "credits": [{"label": "Damaged chairs", "amount": 3000, "reason": "credit note 4"}],
        "charges": [{"label": "Freight", "amount": 500, "basis": "quotation dated 1 June"}]})
    assert ok.status_code == 200, ok.text
    saved = ok.json()
    assert saved["intake"]["invoice_number"] == "INV-17" and saved["intake"]["disputes"]["quality"] is True
    assert saved["credits"][0]["amount"] == 3000 and saved["charges"][0]["basis"] == "quotation dated 1 June"
    bad = user_a.patch(f"/recovery/cases/{cid}/intake", json={"charges": [{"label": "Late fee", "amount": 900, "basis": ""}]})
    assert bad.status_code == 422 and "written basis" in bad.json()["detail"]
    assert user_a.patch(f"/recovery/cases/{cid}/intake", json={"invoice_date": "2999-01-01"}).status_code == 422
    assert user_a.patch(f"/recovery/cases/{cid}/intake", json={"invoice_date": "not a date"}).status_code == 422
    assert user_a.patch(f"/recovery/cases/{cid}/intake", json={"response_days": 3}).status_code == 422
    assert user_a.get(f"/recovery/cases/{cid}").json()["intake"]["invoice_number"] == "INV-17"  # earlier answers survive later patches


def test_readiness_reports_balance_evidence_warnings_and_provenance(user_a):
    cid, _ = new_case(user_a)
    user_a.patch(f"/recovery/cases/{cid}/intake", json={"invoice_number": "INV-9", "route": {"cheque_bounced": "yes"}})
    user_a.post(f"/recovery/cases/{cid}/payment", json={"amount": 10000})
    r = user_a.get(f"/recovery/cases/{cid}/readiness").json()
    assert r["balance"]["balance"] == 30000 and r["can_draft"] and r["route_acknowledgement_needed"]
    assert "Proof the goods were delivered or the work was done" in r["evidence"]["required_missing"]
    sources = {p["label"]: p["source"] for p in r["provenance"]}
    assert sources["Balance due"] == "CALCULATED" and sources["Invoice number"] == "YOU_ENTERED"


def test_notice_numbers_come_from_code_and_a_model_cannot_change_them(user_a):
    cid, debtor = new_case(user_a, amount=50000)
    user_a.patch(f"/recovery/cases/{cid}/intake", json={"credits": [{"label": "Return", "amount": 2000, "reason": "credit note"}]})
    user_a.post(f"/recovery/cases/{cid}/payment", json={"amount": 8000})
    upload_proof(user_a, cid, "invoice.txt", b"Invoice 17 for Rs 50,000", "INVOICE")
    wrong = draft_reply().copy()
    wrong["notice"] = wrong["notice"].replace("The invoice remains unpaid.", "The invoice remains unpaid: you owe Rs 99,999.")
    stub("generic", wrong, contains=debtor)
    r = user_a.post(f"/recovery/cases/{cid}/notice")
    assert r.status_code == 200, r.text
    body = r.json()["notice_body"]
    assert "= Balance due: 40,000.00 INR" in body and "- Return: 2,000.00 INR" in body and "- Payment received" in body
    assert "Enclosures\n  1. Invoice or bill: invoice.txt" in body
    assert "{{" not in body
    assert r.json()["notice_meta"]["balance"] == 40000 and r.json()["notice_meta"]["enclosures"] == ["Invoice or bill: invoice.txt"]


def test_blocks_are_inserted_before_the_closing_even_if_the_model_forgets_the_markers(user_a):
    cid, debtor = new_case(user_a)
    stub("generic", {"notice": "To: customer\n\nPlease pay.\n\nYours faithfully, A Traders"}, contains=debtor)
    body = user_a.post(f"/recovery/cases/{cid}/notice").json()["notice_body"]
    assert body.index("Statement of account") < body.index("Enclosures") < body.index("Yours faithfully")
    assert "No documents are enclosed" in body


def test_the_prompt_carries_the_owners_facts_and_forbids_threats(user_a):
    from tests.conftest import ai_prompts

    cid, debtor = new_case(user_a)
    user_a.patch(f"/recovery/cases/{cid}/intake", json={
        "invoice_number": "INV-55", "supply_description": "sofa set", "payment_terms": "net 15", "response_days": 21,
        "promise_to_pay": {"text": "I will pay by Friday", "date": "2026-09-10"}, "disputes": {"delivery": True, "note": "says late"}})
    stub("generic", draft_reply(), contains=debtor)
    assert user_a.post(f"/recovery/cases/{cid}/notice").status_code == 200
    prompt = ai_prompts(debtor)[-1]
    for needle in ("INV-55", "sofa set", "net 15", "21 days", "I will pay by Friday", "dispute", "Never mention arrest, police"):
        assert needle in prompt, needle


def test_a_cheque_matter_needs_an_explicit_acknowledgement_before_drafting(user_a):
    cid, debtor = new_case(user_a)
    user_a.patch(f"/recovery/cases/{cid}/intake", json={"route": {"cheque_bounced": "yes"}})
    r = user_a.post(f"/recovery/cases/{cid}/notice")
    assert r.status_code == 409 and "cheque" in r.json()["detail"].lower()
    stub("generic", draft_reply(), contains=debtor)
    ok = user_a.post(f"/recovery/cases/{cid}/notice", json={"acknowledge_route": True})
    assert ok.status_code == 200 and ok.json()["notice_meta"]["route_acknowledged"] is True


def test_nothing_is_drafted_without_an_owner_entered_amount_or_when_nothing_is_owed(user_a):
    cid, _ = new_case(user_a, amount=0)
    mongo().recovery_cases.update_one({"id": cid}, {"$set": {"detected_amount": 70000}})
    r = user_a.post(f"/recovery/cases/{cid}/notice")
    assert r.status_code == 422 and "invoice amount" in r.json()["detail"]
    user_a.patch(f"/recovery/cases/{cid}/intake", json={"amount": 5000})
    user_a.post(f"/recovery/cases/{cid}/payment", json={"amount": 5000})
    assert "Nothing is outstanding" in user_a.post(f"/recovery/cases/{cid}/notice").json()["detail"]


def test_a_model_that_cites_law_or_accuses_produces_a_blocked_draft(verified_a):
    for line, key in (("Under Section 138 you must pay.", "legal_references"), ("This is fraud and we will call the police.", "risky_language")):
        cid, debtor = new_case(verified_a)
        stub("generic", draft_reply("\n" + line), contains=debtor)
        assert verified_a.post(f"/recovery/cases/{cid}/notice").status_code == 200
        prev = verified_a.get(f"/recovery/cases/{cid}/notice-preview").json()
        assert prev["blockers"]["blocked"] and prev["blockers"][key]
        assert verified_a.get(f"/recovery/cases/{cid}/notice.pdf").status_code == 409
        prep = verified_a.post(f"/recovery/cases/{cid}/email/prepare", json={"debtor_email": "customer@example.com"})
        assert prep.status_code == 409  # cannot even be previewed for sending


def test_preview_lists_what_it_rests_on(user_a):
    cid, debtor = new_case(user_a)
    stub("generic", draft_reply(), contains=debtor)
    user_a.post(f"/recovery/cases/{cid}/notice")
    prev = user_a.get(f"/recovery/cases/{cid}/notice-preview").json()
    assert prev["ai_drafted"] and prev["balance"]["balance"] == 40000 and not prev["blockers"]["blocked"]
    assert any("not by itself create or prove any legal right" in n for n in prev["notes"])


# ---- evidence files ----
def test_proofs_keep_the_original_and_can_be_labelled_and_downloaded(user_a):
    cid, _ = new_case(user_a)
    r = upload_proof(user_a, cid, "challan.txt", b"Delivered 5 chairs. Signed: R. Kumar", "DELIVERY_PROOF")
    assert r.status_code == 200 and r.json()["kind"] == "DELIVERY_PROOF" and r.json()["has_file"]
    pid = r.json()["id"]
    d = user_a.get(f"/recovery/cases/{cid}/proofs/{pid}/file")
    assert d.status_code == 200 and d.content == b"Delivered 5 chairs. Signed: R. Kumar"
    assert user_a.patch(f"/recovery/cases/{cid}/proofs/{pid}", json={"kind": "INVOICE"}).json()["kind"] == "INVOICE"
    assert user_a.patch(f"/recovery/cases/{cid}/proofs/{pid}", json={"kind": "NONSENSE"}).status_code == 422
    assert upload_proof(user_a, cid, "other.txt", b"x y z", "BOGUS").status_code == 422
    dup = upload_proof(user_a, cid, "copy-of-challan.txt", b"Delivered 5 chairs. Signed: R. Kumar")
    assert dup.status_code == 409 and "already" in dup.json()["detail"]


def test_deleting_a_case_deletes_the_stored_evidence_files(user_a):
    cid, _ = new_case(user_a)
    pid = upload_proof(user_a, cid, "a.txt", b"evidence one", "INVOICE").json()["id"]
    db = mongo()
    gid = db.recovery_proofs.find_one({"id": pid})["gridfs_id"]
    assert db.fs.files.find_one({"_id": gid})
    assert user_a.delete(f"/recovery/cases/{cid}").status_code == 200
    assert db.fs.files.find_one({"_id": gid}) is None and db.recovery_proofs.count_documents({"case_id": cid}) == 0


# ---- privacy between businesses ----
def test_another_business_cannot_read_or_change_any_of_it(user_a, user_b):
    cid, _ = new_case(user_a)
    pid = upload_proof(user_a, cid, "secret.txt", b"private invoice", "INVOICE").json()["id"]
    for method, path, kw in (
        ("get", f"/recovery/cases/{cid}/readiness", {}),
        ("get", f"/recovery/cases/{cid}/notice-preview", {}),
        ("patch", f"/recovery/cases/{cid}/intake", {"json": {"amount": 1}}),
        ("post", f"/recovery/cases/{cid}/notice", {}),
        ("get", f"/recovery/cases/{cid}/proofs/{pid}/file", {}),
        ("patch", f"/recovery/cases/{cid}/proofs/{pid}", {"json": {"kind": "OTHER"}}),
    ):
        assert getattr(user_b, method)(path, **kw).status_code == 404, path
    assert user_a.get(f"/recovery/cases/{cid}").json()["amount"] == 40000


def test_a_member_cannot_draft_but_can_read_the_readiness(user_a):
    from tests.conftest import new_member

    verify_email(user_a)
    cid, _ = new_case(user_a)
    member = new_member(user_a, "MEMBER")
    assert member.get(f"/recovery/cases/{cid}/readiness").status_code == 200
    assert member.post(f"/recovery/cases/{cid}/notice").status_code == 403
