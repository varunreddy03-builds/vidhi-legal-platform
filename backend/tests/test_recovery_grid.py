"""Legal Recovery grid: 1,108 generated cases, each checked against an INDEPENDENT oracle (exact fractions, written separately from the production code).

360 balances        8 invoice amounts x 5 payment patterns x 3 credit patterns x 3 charge patterns
540 interest sums   6 principals x 6 rates x 5 date spans x 3 payment patterns
144 route answers   every combination of the cheque / given-cheque / proceedings / insolvency / MSME / dispute answers
 64 evidence sets   every subset of the four document kinds x payments entered or not x a written promise or not

Money is invented. Nothing here states what any law says: interest uses a rate the owner enters, and the route checks only turn the owner's answers into warnings."""

import itertools
from datetime import date, timedelta
from fractions import Fraction

import pytest

from lib.balance import compute_balance
from lib.evidence_check import check_evidence
from lib.interest import compute_simple_interest
from lib.route_checks import check_routes

TODAY = date(2026, 10, 19)


def frac(x):
    return Fraction(str(x))


def paise(x: Fraction) -> float:
    """Round half up to two places, independent of the production helper."""
    scaled = x * 100
    whole = scaled.numerator // scaled.denominator
    if scaled - whole >= Fraction(1, 2):
        whole += 1
    return whole / 100


# ---------------------------------------------------------------------------------------------
# balances
# ---------------------------------------------------------------------------------------------
AMOUNTS = [1000, 12345.67, 50000, 99999.99, 250000.5, 1250000, 0.99, 7777.77]
PAYMENTS = [[], [1000], [333.33, 333.33], [5000, 2500.5, 100], [999999]]
CREDITS = [[], [250.25], [100, 200]]
CHARGES = [[], [(500, "clause 2 of the agreement")], [(500, ""), (300, "clause 3 of the agreement")]]
BALANCE_GRID = list(itertools.product(range(len(AMOUNTS)), range(len(PAYMENTS)), range(len(CREDITS)), range(len(CHARGES))))


@pytest.mark.parametrize("ai,pi,ci,hi", BALANCE_GRID, ids=[f"bal-a{a}-p{p}-c{c}-h{h}" for a, p, c, h in BALANCE_GRID])
def test_balance_matches_the_oracle(ai, pi, ci, hi):
    amount, pays, creds, chs = AMOUNTS[ai], PAYMENTS[pi], CREDITS[ci], CHARGES[hi]
    got = compute_balance({
        "amount": amount, "currency": "INR",
        "payments": [{"amount": p, "date": "2026-08-01"} for p in pays],
        "credits": [{"label": "credit", "amount": c, "reason": "credit note"} for c in creds],
        "charges": [{"label": "charge", "amount": a, "basis": b} for a, b in chs], "intake": {},
    })
    counted = sum((frac(a) for a, b in chs if b.strip()), Fraction(0))
    expected = max(Fraction(0), frac(amount) + counted - sum((frac(c) for c in creds), Fraction(0)) - sum((frac(p) for p in pays), Fraction(0)))
    assert got["balance"] == paise(expected)
    assert len(got["ignored_charges"]) == sum(1 for _, b in chs if not b.strip())
    assert got["overpaid"] == (frac(amount) + counted - sum((frac(c) for c in creds), Fraction(0)) - sum((frac(p) for p in pays), Fraction(0)) < 0)


# ---------------------------------------------------------------------------------------------
# simple interest
# ---------------------------------------------------------------------------------------------
PRINCIPALS = [10000, 50000.5, 123456.78, 1000000, 999.99, 250000]
RATES = [0, 6, 9.5, 12, 18.25, 24]
SPANS = [("2026-01-01", "2026-01-02"), ("2026-01-01", "2026-04-01"), ("2025-06-15", "2026-06-15"), ("2024-02-01", "2024-03-01"), ("2023-01-01", "2026-10-19")]
PAY_PATTERNS = ["none", "middle", "start-and-after"]
INTEREST_GRID = list(itertools.product(range(len(PRINCIPALS)), range(len(RATES)), range(len(SPANS)), PAY_PATTERNS))


def oracle_interest(principal, rate, start, end, payments):
    start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
    balance = frac(principal)
    later = []
    for d, amt in sorted(payments):
        if d <= start_d:
            balance = max(Fraction(0), balance - frac(amt))
        else:
            later.append((d, amt))
    total, cursor = Fraction(0), start_d

    def accrue(upto):
        nonlocal total, cursor
        days = (upto - cursor).days
        if days > 0 and balance > 0:
            total += balance * frac(rate) / 100 * days / 365
        if upto > cursor:
            cursor = upto

    for d, amt in later:
        if d > end_d:
            break
        accrue(d)
        balance = max(Fraction(0), balance - frac(amt))
    accrue(end_d)
    return paise(total), paise(balance)


def payments_for(pattern, principal, start, end):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    if pattern == "none":
        return []
    if pattern == "middle":
        return [(s + (e - s) / 2 if (e - s).days > 1 else s, round(principal * 0.2, 2))]
    return [(s, round(principal * 0.1, 2)), (e + timedelta(days=30), round(principal * 0.5, 2))]


@pytest.mark.parametrize("pi,ri,si,pay", INTEREST_GRID, ids=[f"int-p{p}-r{r}-s{s}-{pay}" for p, r, s, pay in INTEREST_GRID])
def test_interest_matches_the_oracle(pi, ri, si, pay):
    principal, rate = PRINCIPALS[pi], RATES[ri]
    start, end = SPANS[si]
    pays = payments_for(pay, principal, start, end)
    got = compute_simple_interest(principal, [(d, a) for d, a in pays], start, rate, end)
    interest, remaining = oracle_interest(principal, rate, start, end, pays)
    assert got["interest"] == interest
    assert got["principal_remaining"] == remaining
    assert got["total_due"] == paise(frac(interest) + frac(remaining))
    assert got["days"] == (date.fromisoformat(end) - date.fromisoformat(start)).days


# ---------------------------------------------------------------------------------------------
# route answers
# ---------------------------------------------------------------------------------------------
ROUTE_GRID = list(itertools.product(["no", "unsure", "yes"], ["no", "yes"], ["no", "yes"], ["no", "yes"], ["no", "unsure", "yes"], [False, True]))


@pytest.mark.parametrize("cheque,given,proceedings,insolvency,msme,disputed", ROUTE_GRID, ids=["route-" + "-".join(map(str, r)) for r in ROUTE_GRID])
def test_route_answers_match_the_oracle(cheque, given, proceedings, insolvency, msme, disputed):
    out = check_routes({
        "amount": 50000, "due_date": "2026-09-01", "payments": [], "charges": [], "credits": [],
        "intake": {"route": {"cheque_bounced": cheque, "cheque_given": given, "existing_proceedings": proceedings, "insolvency": insolvency, "msme": msme},
                   "disputes": {"quality": disputed}},
    }, TODAY)
    keys = {f["key"]: f for f in out["flags"]}
    stop = cheque == "yes" or proceedings == "yes" or insolvency == "yes"
    warn = (cheque != "yes" and (cheque == "unsure" or given == "yes")) or disputed
    assert out["blocks_notice"] == stop
    assert out["advocate_recommended"] == (stop or warn)
    assert ("cheque" in keys) == (cheque in ("yes", "unsure") or given == "yes")
    assert ("proceedings" in keys) == (proceedings == "yes") and ("insolvency" in keys) == (insolvency == "yes")
    assert ("dispute" in keys) == disputed and ("msme" in keys) == (msme in ("yes", "unsure"))
    assert ("ordinary" in keys) == (not keys.keys() - {"ordinary"})
    for f in out["flags"]:
        assert "section" not in f["text"].lower() and "article" not in f["text"].lower()
        if f["key"] == "cheque":
            assert not any(ch.isdigit() for ch in f["text"])  # never a deadline


# ---------------------------------------------------------------------------------------------
# evidence sets
# ---------------------------------------------------------------------------------------------
KINDS = ["INVOICE", "DELIVERY_PROOF", "AGREEMENT", "COMMUNICATION"]
EVIDENCE_GRID = [(mask, pays, promise) for mask in range(16) for pays in (False, True) for promise in (False, True)]


@pytest.mark.parametrize("mask,pays,promise", EVIDENCE_GRID, ids=[f"ev-{m:04b}-p{int(p)}-w{int(w)}" for m, p, w in EVIDENCE_GRID])
def test_evidence_sets_match_the_oracle(mask, pays, promise):
    kinds = [k for i, k in enumerate(KINDS) if mask >> i & 1]
    proofs = [{"kind": k, "filename": f"{k.lower()}.pdf"} for k in kinds]
    case = {"amount": 50000, "payments": [{"amount": 100, "date": "2026-08-01"}] if pays else [], "credits": [], "intake": {"promise_to_pay": {"text": "I will pay on Friday"} if promise else {}}}
    out = check_evidence(case, proofs)
    items = {i["key"]: i for i in out["items"]}
    missing = set(out["required_missing"])
    assert ("The invoice or bill" in missing) == ("INVOICE" not in kinds)
    assert ("Proof the goods were delivered or the work was done" in missing) == ("DELIVERY_PROOF" not in kinds)
    assert items["order"]["status"] == ("PRESENT" if "AGREEMENT" in kinds else "MISSING")
    assert items["communication"]["status"] == ("PRESENT" if "COMMUNICATION" in kinds else "MISSING")
    assert ("payments" in items) == pays and (pays and items["payments"]["status"] == "MISSING" or not pays)  # no payment-record kind is ever in KINDS
    assert ("promise" in items) == (promise and "COMMUNICATION" not in kinds)
    assert out["complete"] is False  # the case never fills in every fact, so a checklist can never be called complete here
