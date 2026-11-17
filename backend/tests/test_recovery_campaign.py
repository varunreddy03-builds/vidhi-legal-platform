"""The 15-phase Legal Recovery campaign: 15 phases x 100 cases = 1,500 cases, plus 100 "not solved yet" cases that the product deliberately does not do.

Every case is generated (seeded) from invented parties and money, with a year from 1990 to 2026 in its dates; about one in ten is set in an invented country. No case states what any law says.
Phases 01-11 are calculations and checks compared with an independent exact-fraction oracle; phases 12-15 drive the live API.

  01 easy                 a plain unpaid invoice                         09 advanced        three-decimal amounts and sums up to hundreds of crores
  02 easy-moderate        one part-payment                               10 expert          over-payment, credit above the invoice, zero invoice, charges alone
  03 moderate-difficult   several payments and credits                   11 master          37 years of yearly payments; a verified-rule deadline (invented rule) across years
  04 difficult            charges with and without a written basis       12 grandmaster     a full case lifecycle through the API, resolve, reopen and delete
  05 very difficult       simple interest over one span                  13 insane          malformed and hostile input to the API: nothing may crash or be altered
  06 extreme              interest with payments before, inside and after 14 nightmare       notices drafted by a scripted model that writes wrong numbers, threats and law
  07 severe               every route answer combination, with debt age  15 hell            another business and anonymous visitors probing a case across the routes
  08 technical            evidence checklists over all seven document kinds
  not-solved-yet          things the product does not do (compound interest, tax, court fees, a limitation period without a reviewed rule): it must refuse, not invent"""

import random
from datetime import date, timedelta
from fractions import Fraction

import pytest

from lib.balance import compute_balance
from lib.evidence_check import PROOF_KINDS, check_evidence
from lib.interest import compute_simple_interest
from lib.limitation import assess
from lib.route_checks import check_routes
from tests.conftest import stub
from tests.test_recovery_grid import frac, oracle_interest, paise
from tests.test_recovery_stage1 import draft_reply, new_case

TODAY = date(2026, 10, 19)
PHASES = ["easy", "easy-moderate", "moderate-difficult", "difficult", "very-difficult", "extreme", "severe", "technical", "advanced", "expert", "master", "grandmaster", "insane", "nightmare", "hell"]
INVENTED_LANDS = ["Zarvia", "Quellara", "Northmark", "Vasundhar"]


def build_cases():
    out = []
    for phase in range(1, 16):
        for n in range(100):
            year = 1990 + (n * 37 + phase * 11) % 37
            fic = n % 10 == 7
            out.append({"id": f"R{phase:02d}-{PHASES[phase - 1]}-{n:03d}-y{year}" + ("-fic" if fic else ""), "phase": phase, "n": n, "year": year, "fictional": fic})
    for n in range(100):
        year = 1990 + n % 37
        out.append({"id": f"OPEN-{n:03d}-y{year}", "phase": 16, "n": n, "year": year, "fictional": False})
    return out


CASES = build_cases()


def rng_of(case):
    return random.Random(f"recovery-{case['phase']}-{case['n']}")


def day_in(rng, year):
    return date(year, rng.randint(1, 12), rng.randint(1, 28))


def money(rng, low=1000, high=9_999_999, decimals=2):
    return round(rng.uniform(low, high), decimals)


def base_case(case, rng, **kw):
    c = {"amount": money(rng), "currency": "INR", "payments": [], "charges": [], "credits": [], "intake": {}, "due_date": day_in(rng, case["year"]).isoformat()}
    c.update(kw)
    return c


def oracle_balance(c):
    amt = frac(c.get("amount") or 0)
    charges = sum((frac(x["amount"]) for x in c.get("charges", []) if frac(x["amount"]) > 0 and str(x.get("basis") or "").strip()), Fraction(0))
    credits = sum((frac(x["amount"]) for x in c.get("credits", []) if frac(x["amount"]) > 0), Fraction(0))
    paid = sum((frac(x["amount"]) for x in c.get("payments", [])), Fraction(0))
    return paise(max(Fraction(0), amt + charges - credits - paid))


def pays(rng, year, total, k, lo=0.05, hi=0.9):
    cuts = sorted(rng.uniform(lo, hi) for _ in range(k))
    return [{"amount": round(total * (b - a), 2) if i else round(total * b, 2), "date": day_in(rng, year).isoformat()} for i, (a, b) in enumerate(zip([0] + cuts[:-1], cuts))]


# ---------------------------------------------------------------------------------------------
# phases 01-11: calculations and checks against the oracle
# ---------------------------------------------------------------------------------------------
def run_pure(case):
    rng, ph = rng_of(case), case["phase"]
    if ph == 1:
        c = base_case(case, rng)
        assert compute_balance(c)["balance"] == paise(frac(c["amount"]))
    elif ph == 2:
        c = base_case(case, rng)
        c["payments"] = [{"amount": round(c["amount"] * rng.uniform(0.05, 0.95), 2), "date": day_in(rng, case["year"]).isoformat()}]
        assert compute_balance(c)["balance"] == oracle_balance(c)
    elif ph == 3:
        c = base_case(case, rng)
        c["payments"] = pays(rng, case["year"], c["amount"] * 0.6, rng.randint(2, 5))
        c["credits"] = [{"label": "credit", "amount": round(c["amount"] * rng.uniform(0.01, 0.1), 2), "reason": "credit note"} for _ in range(rng.randint(1, 2))]
        b = compute_balance(c)
        assert b["balance"] == oracle_balance(c) and len(b["lines"]) == 1 + len(c["payments"]) + len(c["credits"])
    elif ph == 4:
        c = base_case(case, rng)
        c["charges"] = [{"label": "charge", "amount": round(rng.uniform(100, 5000), 2), "basis": rng.choice(["clause 4 of the agreement", "quotation dated 1 June", "", "   "])} for _ in range(rng.randint(2, 5))]
        c["credits"] = [{"label": "credit", "amount": round(rng.uniform(50, 2000), 2), "reason": "credit note"}]
        c["payments"] = pays(rng, case["year"], c["amount"] * 0.3, 2)
        b = compute_balance(c)
        assert b["balance"] == oracle_balance(c)
        assert len(b["ignored_charges"]) == sum(1 for x in c["charges"] if not x["basis"].strip())
    elif ph == 5:
        principal, rate = money(rng, 1000, 5_000_000), rng.choice([0, 6, 9, 10.5, 12, 15, 18, 24])
        start = day_in(rng, case["year"])
        end = start + timedelta(days=rng.randint(1, 3000))
        got = compute_simple_interest(principal, [], start.isoformat(), rate, end.isoformat())
        interest, remaining = oracle_interest(principal, rate, start.isoformat(), end.isoformat(), [])
        assert (got["interest"], got["principal_remaining"], got["days"]) == (interest, remaining, (end - start).days)
    elif ph == 6:
        principal, rate = money(rng, 10_000, 5_000_000), rng.choice([6, 9, 12, 18, 24])
        start = date(case["year"] - (case["year"] % 4) if case["year"] % 4 else case["year"], rng.choice([1, 2, 3]), rng.choice([1, 28, 29] if (case["year"] - (case["year"] % 4)) % 4 == 0 else [1, 28]))
        end = start + timedelta(days=rng.randint(200, 4000))
        pl = [(start + timedelta(days=rng.randint(-60, (end - start).days + 90)), round(principal * rng.uniform(0.02, 0.2), 2)) for _ in range(rng.randint(1, 5))]
        got = compute_simple_interest(principal, pl, start.isoformat(), rate, end.isoformat())
        interest, remaining = oracle_interest(principal, rate, start.isoformat(), end.isoformat(), pl)
        assert (got["interest"], got["principal_remaining"]) == (interest, remaining)
    elif ph == 7:
        route = {"cheque_bounced": rng.choice(["no", "unsure", "yes"]), "cheque_given": rng.choice(["no", "yes"]), "existing_proceedings": rng.choice(["no", "yes"]),
                 "insolvency": rng.choice(["no", "yes"]), "msme": rng.choice(["no", "unsure", "yes"])}
        disputed = rng.random() < 0.4
        c = base_case(case, rng, intake={"route": route, "disputes": {"amount": disputed}})
        out = check_routes(c, TODAY)
        keys = {f["key"]: f for f in out["flags"]}
        age = (TODAY - date.fromisoformat(c["due_date"])).days
        stop = route["cheque_bounced"] == "yes" or route["existing_proceedings"] == "yes" or route["insolvency"] == "yes"
        warn = (route["cheque_bounced"] != "yes" and (route["cheque_bounced"] == "unsure" or route["cheque_given"] == "yes")) or disputed or age >= 730
        assert out["blocks_notice"] == stop and out["advocate_recommended"] == (stop or warn)
        assert ("limitation" in keys) == (age >= 730)
        assert ("ordinary" in keys) == (set(keys) <= {"ordinary"})
        if "limitation" in keys:
            assert not any(w in keys["limitation"]["text"].lower() for w in ("three years", "3 years", "article", "section"))
    elif ph == 8:
        kinds = [k for k in PROOF_KINDS if rng.random() < 0.5]
        proofs = [{"kind": k, "filename": f"{k.lower()}.pdf"} for k in kinds]
        has_pay, has_credit, promise = rng.random() < 0.5, rng.random() < 0.3, rng.random() < 0.4
        populated = {k: rng.random() < 0.7 for k in ("invoice_number", "invoice_date", "supply_description", "payment_terms")}
        c = base_case(case, rng, intake={k: ("x" if on else "") for k, on in populated.items()} | {"promise_to_pay": {"text": "I will pay" if promise else ""}},
                      payments=[{"amount": 10, "date": "2020-01-01"}] if has_pay else [], credits=[{"amount": 5}] if has_credit else [],
                      creditor_address="a" if rng.random() < 0.7 else "", debtor_address="b" if rng.random() < 0.7 else "")
        out = check_evidence(c, proofs)
        items = {i["key"]: i for i in out["items"]}
        assert set(out["required_missing"]) == ({"The invoice or bill"} if "INVOICE" not in kinds else set()) | ({"Proof the goods were delivered or the work was done"} if "DELIVERY_PROOF" not in kinds else set())
        assert items["order"]["status"] == ("PRESENT" if {"PURCHASE_ORDER", "AGREEMENT"} & set(kinds) else "MISSING")
        assert ("payments" in items) == (has_pay or has_credit)
        assert ("promise" in items) == (promise and "COMMUNICATION" not in kinds)
        expected_facts = {k for k, on in populated.items() if not on} | ({"creditor_address"} if not c["creditor_address"] else set()) | ({"debtor_address"} if not c["debtor_address"] else set())
        assert expected_facts <= {f["key"] for f in out["facts_missing"]}
        assert out["complete"] == (not out["required_missing"] and not out["facts_missing"])
    elif ph == 9:
        c = base_case(case, rng, amount=money(rng, 1, 5_000_000_000, 3))
        c["payments"] = [{"amount": money(rng, 0.001, c["amount"] / 5, 3), "date": "2020-01-01"} for _ in range(rng.randint(1, 4))]
        c["credits"] = [{"label": "credit", "amount": money(rng, 0.001, c["amount"] / 20, 3), "reason": "credit note"}]
        assert compute_balance(c)["balance"] == oracle_balance(c)
    elif ph == 10:
        amount = rng.choice([0, money(rng, 100, 100000), money(rng, 100, 100000)])
        c = base_case(case, rng, amount=amount)
        c["payments"] = [{"amount": money(rng, 0, max(1, amount * 1.5)), "date": "2020-01-01"} for _ in range(rng.randint(0, 3))]
        c["credits"] = [{"label": "credit", "amount": money(rng, 0, max(1, amount * 1.2)), "reason": "credit note"} for _ in range(rng.randint(0, 2))]
        c["charges"] = [{"label": "charge", "amount": money(rng, 0, 3000), "basis": rng.choice(["clause 2", ""])} for _ in range(rng.randint(0, 2))]
        b = compute_balance(c)
        assert b["balance"] == oracle_balance(c)
        raw = frac(amount) + sum((frac(x["amount"]) for x in c["charges"] if frac(x["amount"]) > 0 and x["basis"].strip()), Fraction(0)) \
            - sum((frac(x["amount"]) for x in c["credits"] if frac(x["amount"]) > 0), Fraction(0)) - sum((frac(x["amount"]) for x in c["payments"]), Fraction(0))
        assert b["overpaid"] == (raw < 0) and b["balance"] >= 0
    elif ph == 11:
        principal, rate = money(rng, 50_000, 5_000_000), rng.choice([6, 12, 18])
        start = date(1990, 1, 1)
        yearly = [(date(y, rng.randint(1, 12), rng.randint(1, 28)), round(principal * rng.uniform(0.005, 0.03), 2)) for y in range(1991, 2027)]
        end = TODAY
        got = compute_simple_interest(principal, yearly, start.isoformat(), rate, end.isoformat())
        interest, remaining = oracle_interest(principal, rate, start.isoformat(), end.isoformat(), yearly)
        assert (got["interest"], got["principal_remaining"], got["days"]) == (interest, remaining, (end - start).days)
        # an INVENTED verified rule: the deadline is the due date plus its period; status depends on days left
        due = day_in(rng, case["year"])
        period = rng.randint(1, 12)
        rule = {"id": "r", "applies_to": "Invented claim", "period_years": period, "citation": "Invented Act s.1", "source_text": "x", "source_url": "https://example.com", "verified_by": "Test Lawyer", "verified_on": "2026-01-01", "verified": True}
        a = assess(due.isoformat(), TODAY, [rule])
        deadline = date(due.year + period, due.month, due.day)
        left = (deadline - TODAY).days
        r = a["rules"][0]
        assert a["age_days"] == (TODAY - due).days and r["deadline"] == deadline.isoformat() and r["days_left"] == left
        assert r["status"] == ("PASSED" if left < 0 else "SOON" if left <= 180 else "OK")
    else:
        raise ValueError(ph)


def run_open(case):
    """Things the product deliberately does not do. A pass means it did not invent an answer."""
    rng = rng_of(case)
    kind = case["n"] % 5
    due = day_in(rng, case["year"]).isoformat()
    if kind == 0:  # limitation without a reviewed rule: only the age, never a period
        a = assess(due, TODAY, [])
        assert a["mode"] == "GENERIC" and a["rules"] == [] and "period_years" not in str(a)
    elif kind == 1:  # old debt: a warning by age only
        c = base_case(case, rng, due_date=due)
        for f in check_routes(c, TODAY)["flags"]:
            assert not any(w in f["text"].lower() for w in ("years to", "time limit is", "barred", "section", "article"))
    elif kind == 2:  # balance never includes interest, tax or fees
        b = compute_balance(base_case(case, rng, due_date=due, interest_rate_pct=24, gst_pct=18, court_fee=5000))
        assert b["balance"] == paise(frac(b["invoice_amount"])) and b["charges_total"] == 0
    elif kind == 3:  # interest is simple only; the stated method says so
        r = compute_simple_interest(100000, [], due, 12, TODAY.isoformat())
        assert any("Simple interest (not compounded)" in x for x in r["assumptions"]) and any("not a statement of what a court would award" in x for x in r["assumptions"])
    else:  # a missing due date asks for one instead of guessing
        assert assess(None, TODAY)["mode"] == "NEEDS_DUE_DATE"


# ---------------------------------------------------------------------------------------------
# phases 12-15: the live API
# ---------------------------------------------------------------------------------------------
def run_lifecycle(case, user_a):
    rng = rng_of(case)
    amount = round(rng.uniform(1000, 5_000_000), 2)
    cid, _ = new_case(user_a, amount=amount)
    due = day_in(rng, case["year"]).isoformat()
    d = user_a.patch(f"/recovery/cases/{cid}/details", json={"creditor_address": "1 Market Road", "debtor_address": "9 Lake View", "due_date": due})
    assert d.status_code == 200, d.text
    paid = 0.0
    for _ in range(rng.randint(0, 3)):
        part = round(rng.uniform(1, amount / 6), 2)
        r = user_a.post(f"/recovery/cases/{cid}/payment", json={"amount": part})
        assert r.status_code == 200, r.text
        paid += part
    ready = user_a.get(f"/recovery/cases/{cid}/readiness").json()
    assert ready["balance"]["balance"] == paise(frac(amount) - frac(round(paid, 2))) or abs(ready["balance"]["balance"] - (amount - paid)) < 0.011
    assert cid in [c["id"] for c in user_a.get("/recovery/cases").json()]
    assert user_a.post(f"/recovery/cases/{cid}/resolve").json()["status"] == "RESOLVED"
    assert user_a.post(f"/recovery/cases/{cid}/reopen").json()["status"] != "RESOLVED"
    assert user_a.delete(f"/recovery/cases/{cid}").status_code == 200
    assert user_a.get(f"/recovery/cases/{cid}").status_code == 404


HOSTILE_TEXT = ["<script>alert(1)</script>", "'; DROP TABLE cases; --", "x" * 400, "नमस्ते " * 20, "\u0000null\u0000byte", "emoji \U0001F600 name", "  ", "‮right-to-left", "../../etc/passwd", "{{STATEMENT}}"]
HOSTILE_AMOUNTS = [-5, 0, 1e30, "abc", 12.345678, None, 10**30, "1e400", True, [1], {"a": 1}, 0.001, 99999999999.99]


def run_fuzz(case, user_a):
    rng = rng_of(case)
    name = rng.choice(HOSTILE_TEXT)
    amount = rng.choice(HOSTILE_AMOUNTS)
    body = {"creditor_name": name if rng.random() < 0.5 else "A Traders", "debtor_name": name if rng.random() < 0.5 else "Debtor " + str(case["n"]), "amount": amount}
    r = user_a.post("/recovery/cases", json=body)
    assert r.status_code < 500, f"{r.status_code} for {body!r}: {r.text[:200]}"
    if r.status_code == 200:
        got = user_a.get(f"/recovery/cases/{r.json()['id']}")
        assert got.status_code == 200
        assert got.json()["creditor_name"] == body["creditor_name"].strip() or got.json()["creditor_name"] == body["creditor_name"]
        assert "application/json" in got.headers["content-type"]
        assert got.json()["amount"] >= 0
    else:
        assert r.status_code in (400, 413, 422)


def run_notice(case, verified_a):
    rng = rng_of(case)
    amount = round(rng.uniform(5000, 900000), 2)
    cid, debtor = new_case(verified_a, amount=amount)
    verified_a.patch(f"/recovery/cases/{cid}/details", json={"creditor_address": "1 Market Road", "debtor_address": "9 Lake View", "due_date": day_in(rng, case["year"]).isoformat()})
    kind = case["n"] % 5
    extra, blocked = [("", False), ("\nUnder Section 138 you must pay within 15 days.", True), ("\nPay or we will have you arrested and call the police.", True), ("\nThis is fraud and you are a cheat.", True), ("", True)][kind]  # kind 4: the model writes its own wrong figure, which must now block the notice
    reply = draft_reply(extra)
    if kind == 4:
        reply["notice"] = reply["notice"].replace("The invoice remains unpaid.", "The invoice remains unpaid: you owe Rs 99,99,999.")
    stub("generic", reply, contains=debtor)
    r = verified_a.post(f"/recovery/cases/{cid}/notice")
    assert r.status_code == 200, r.text
    body = r.json()["notice_body"]
    assert f"= Balance due: {amount:,.2f} INR" in body  # the calculated balance is always there; a model's own figure is caught by the blocker checked below
    if kind == 4:
        assert "Rs 99,99,999" in verified_a.get(f"/recovery/cases/{cid}/notice-preview").json()["blockers"]["amount_mismatches"]
    prev = verified_a.get(f"/recovery/cases/{cid}/notice-preview").json()
    assert prev["blockers"]["blocked"] == blocked
    assert (verified_a.get(f"/recovery/cases/{cid}/notice.pdf").status_code == 409) == blocked


PROBES = [("get", "readiness"), ("get", "notice-preview"), ("get", "proofs"), ("patch", "intake"), ("post", "notice"), ("get", "interest"), ("get", "limitation"), ("post", "resolve"), ("patch", "details"), ("get", "notice/delivery")]


def run_isolation(case, user_a, user_b, anon):
    rng = rng_of(case)
    cid, _ = new_case(user_a, amount=round(rng.uniform(1000, 90000), 2))
    for method, route in rng.sample(PROBES, 4):
        kw = {"json": {"amount": 1}} if method in ("patch", "post") else {}
        assert getattr(user_b, method)(f"/recovery/cases/{cid}/{route}", **kw).status_code == 404, (method, route)
        assert getattr(anon, method)(f"/recovery/cases/{cid}/{route}", **kw).status_code == 401, (method, route)
    assert cid not in [c["id"] for c in user_b.get("/recovery/cases").json()]
    assert user_b.delete(f"/recovery/cases/{cid}").status_code == 404
    assert user_a.get(f"/recovery/cases/{cid}").status_code == 200


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_recovery_campaign(request, case):
    ph = case["phase"]
    if ph <= 11:
        run_pure(case)
    elif ph == 16:
        run_open(case)
    elif ph == 12:
        run_lifecycle(case, request.getfixturevalue("user_a"))
    elif ph == 13:
        run_fuzz(case, request.getfixturevalue("user_a"))
    elif ph == 14:
        run_notice(case, request.getfixturevalue("verified_a"))
    else:
        run_isolation(case, request.getfixturevalue("user_a"), request.getfixturevalue("user_b"), request.getfixturevalue("anon"))
