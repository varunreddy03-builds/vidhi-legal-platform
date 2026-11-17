"""500 Legal Recovery scenarios (10 families x 50) driven through the live API and judged against independent oracles (exact fractions; rules written from the project's documented
behaviour, not by calling the app's own code). Every party and amount is invented; years run from 1990 to the present. Nothing here states what any law says.

 RS01 ledger          random sequences of adding, editing and deleting part-payments: the balance must equal the exact sum after every step
 RS02 intake          charges and credits that replace each other; a charge without a written basis must be refused and change nothing
 RS03 interest        the itemised simple-interest working against an independent calculation, with payments before, inside and after the span; bad rates and dates refused
 RS04 age of debt     the limitation endpoint reports age only and never a period (no reviewed rule is loaded)
 RS05 routes          the route warnings the readiness panel shows, and whether drafting needs an acknowledgement
 RS06 wording         notices whose wording carries figures, law, threats or blanks: exactly the ones that should be blocked are blocked
 RS07 approval        random edits / approvals / send-preparations against a model of the approval rules; old versions never change
 RS08 evidence        uploads, duplicates, labels, downloads and deletion of the stored files
 RS09 privacy         another business and anonymous visitors against 6 random routes of a case
 RS10 robustness      hostile and malformed input to every field: nothing may crash or leave the case unreadable"""

import random
import re
import uuid
from datetime import date, timedelta
from fractions import Fraction

import pytest

from lib.evidence_check import PROOF_KINDS
from tests.conftest import mongo, stub
from tests.test_recovery_grid import frac, oracle_interest, paise
from tests.test_recovery_stage1 import draft_reply, new_case

FAMILIES = ["ledger", "intake", "interest", "age", "routes", "wording", "approval", "evidence", "privacy", "robustness"]
CASES = [{"id": f"RS{f + 1:02d}-{FAMILIES[f]}-{n:03d}", "family": f, "n": n} for f in range(10) for n in range(50)]


def rng_of(c):
    return random.Random(f"scenario-{c['family']}-{c['n']}")


def past_date(rng, low_year=1990):
    start, end = date(low_year, 1, 1), date.today() - timedelta(days=3)
    return start + timedelta(days=rng.randrange((end - start).days))


def money(rng, lo=1000, hi=3_000_000):
    return round(rng.uniform(lo, hi), 2)


def balance(c, cid):
    r = c.get(f"/recovery/cases/{cid}/readiness")
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ RS01
def s_ledger(case, c):
    rng = rng_of(case)
    amount = money(rng)
    cid, _ = new_case(c, amount=amount)
    ledger: dict[str, Fraction] = {}
    for _ in range(rng.randint(2, 8)):
        op = rng.choice(["add", "add", "add", "edit", "delete"]) if ledger else "add"
        if op == "add":
            part = round(rng.uniform(0.5, amount * 0.6), rng.choice([2, 2, 2, 3]))
            r = c.post(f"/recovery/cases/{cid}/payment", json={"amount": part})
            assert r.status_code == 200, r.text
            pid = [p["id"] for p in r.json()["payments"] if p["id"] not in ledger][0]
            ledger[pid] = frac(round(part, 2))  # the app keeps every payment to whole paise
        elif op == "edit":
            pid = rng.choice(list(ledger))
            part = round(rng.uniform(0.5, amount * 0.6), 2)
            assert c.patch(f"/recovery/cases/{cid}/payment/{pid}", json={"amount": part}).status_code == 200
            ledger[pid] = frac(part)
        else:
            pid = rng.choice(list(ledger))
            assert c.delete(f"/recovery/cases/{cid}/payment/{pid}").status_code == 200
            del ledger[pid]
        b = balance(c, cid)["balance"]
        owed = frac(amount) - sum(ledger.values(), Fraction(0))
        assert b["balance"] == paise(max(Fraction(0), owed)), (op, b["balance"], float(owed))
        assert b["overpaid"] == (owed < 0)
        assert b["payments_total"] == paise(sum(ledger.values(), Fraction(0)))
    assert abs(c.get(f"/recovery/cases/{cid}").json()["paid_amount"] - float(sum(ledger.values(), Fraction(0)))) < 0.006 * max(1, len(ledger))


# ------------------------------------------------------------------ RS02
def s_intake(case, c):
    rng = rng_of(case)
    amount = money(rng)
    cid, _ = new_case(c, amount=amount)
    state = {"charges": [], "credits": []}
    for _ in range(rng.randint(1, 3)):
        charges = [{"label": f"charge {i}", "amount": round(rng.uniform(10, 4000), 2), "basis": rng.choice(["clause 4 of the agreement", "quotation dated 1 June 1999", "purchase order terms"])} for i in range(rng.randint(0, 3))]
        credits = [{"label": f"credit {i}", "amount": round(rng.uniform(10, amount / 5), 2), "reason": "credit note"} for i in range(rng.randint(0, 3))]
        bad = rng.random() < 0.35 and charges
        if bad:
            charges[rng.randrange(len(charges))]["basis"] = rng.choice(["", "   "])
        before = balance(c, cid)["balance"]["balance"]
        r = c.patch(f"/recovery/cases/{cid}/intake", json={"charges": charges, "credits": credits})
        if bad:
            assert r.status_code == 422 and "written basis" in r.json()["detail"], r.text
            assert balance(c, cid)["balance"]["balance"] == before   # a refused change changes nothing
            continue
        assert r.status_code == 200, r.text
        state = {"charges": charges, "credits": credits}
        owed = frac(amount) + sum((frac(x["amount"]) for x in charges), Fraction(0)) - sum((frac(x["amount"]) for x in credits), Fraction(0))
        assert balance(c, cid)["balance"]["balance"] == paise(max(Fraction(0), owed))
    assert len(c.get(f"/recovery/cases/{cid}").json()["credits"]) == len(state["credits"])


# ------------------------------------------------------------------ RS03
def s_interest(case, c):
    rng = rng_of(case)
    amount = money(rng, 5000, 2_000_000)
    cid, _ = new_case(c, amount=amount)
    due = past_date(rng, 1990)
    rate = rng.choice([0, 6, 9, 10.5, 12, 15, 18, 24, 100])
    assert c.patch(f"/recovery/cases/{cid}/details", json={"due_date": due.isoformat(), "interest_rate_pct": rate}).status_code == 200
    credits = [{"label": "credit", "amount": round(amount * rng.uniform(0.01, 0.1), 2), "reason": "credit note"}] if rng.random() < 0.4 else []
    if credits:
        assert c.patch(f"/recovery/cases/{cid}/intake", json={"credits": credits}).status_code == 200
    as_of = due + timedelta(days=rng.randint(0, 4000))
    pays = []
    for _ in range(rng.randint(0, 4)):
        part = round(rng.uniform(100, amount * 0.15), 2)
        r = c.post(f"/recovery/cases/{cid}/payment", json={"amount": part})
        pid = r.json()["payments"][-1]["id"]
        when = min(due + timedelta(days=rng.randint(-40, (as_of - due).days + 60)), date.today() - timedelta(days=1))  # a payment cannot be dated in the future
        assert c.patch(f"/recovery/cases/{cid}/payment/{pid}", json={"date": when.isoformat()}).status_code == 200
        pays.append((when, part))
    principal = max(0.0, float(frac(amount) - sum((frac(x["amount"]) for x in credits), Fraction(0))))
    r = c.get(f"/recovery/cases/{cid}/interest", params={"as_of": as_of.isoformat()})
    assert r.status_code == 200, r.text
    interest, remaining = oracle_interest(round(principal, 2), rate, due.isoformat(), as_of.isoformat(), pays)
    got = r.json()
    assert (got["interest"], got["principal_remaining"]) == (interest, remaining), (got["interest"], interest)
    assert got["total_due"] == paise(frac(interest) + frac(remaining)) and got["days"] == (as_of - due).days
    assert any("Simple interest (not compounded)" in a for a in got["assumptions"])
    for bad_rate in (-0.01, 100.01):
        assert c.patch(f"/recovery/cases/{cid}/details", json={"interest_rate_pct": bad_rate}).status_code == 422
    assert c.get(f"/recovery/cases/{cid}/interest", params={"as_of": "31st March"}).status_code == 422
    assert c.patch(f"/recovery/cases/{cid}/details", json={"clear_interest": True}).status_code == 200
    assert c.get(f"/recovery/cases/{cid}/interest").status_code == 422     # no rate, no interest: it is never assumed


# ------------------------------------------------------------------ RS04
def s_age(case, c):
    rng = rng_of(case)
    cid, _ = new_case(c)
    due = past_date(rng, 1990)
    assert c.patch(f"/recovery/cases/{cid}/details", json={"due_date": due.isoformat()}).status_code == 200
    out = c.get(f"/recovery/cases/{cid}/limitation").json()
    assert out["mode"] == "GENERIC" and out["rules"] == []
    assert abs(out["age_days"] - (date.today() - due).days) <= 1
    assert "period_years" not in str(out) and "section" not in str(out).lower() and "article" not in str(out).lower()
    assert c.patch(f"/recovery/cases/{cid}/details", json={"clear_due_date": True}).status_code == 200
    assert c.get(f"/recovery/cases/{cid}/limitation").json()["mode"] == "NEEDS_DUE_DATE"
    for bad in ("1989-12-31", "1900-01-01", "2026-13-01", "banana", "2026-02-30", "0000-00-00"):
        assert c.patch(f"/recovery/cases/{cid}/details", json={"due_date": bad}).status_code == 422, bad


# ------------------------------------------------------------------ RS05
def s_routes(case, c):
    rng = rng_of(case)
    cid, debtor = new_case(c)
    route = {"cheque_bounced": rng.choice(["no", "unsure", "yes"]), "cheque_given": rng.choice(["no", "yes"]), "existing_proceedings": rng.choice(["no", "yes"]),
             "insolvency": rng.choice(["no", "yes"]), "msme": rng.choice(["no", "unsure", "yes"])}
    disputed = rng.random() < 0.4
    age = rng.choice([30, 200, 600, 725, 735, 900, 4000, 9000])
    due = max(date(1990, 1, 1), date.today() - timedelta(days=age))
    age = (date.today() - due).days
    assert c.patch(f"/recovery/cases/{cid}/details", json={"due_date": due.isoformat()}).status_code == 200
    assert c.patch(f"/recovery/cases/{cid}/intake", json={"route": route, "disputes": {"quality": disputed}}).status_code == 200
    r = balance(c, cid)
    routes, keys = r["routes"], {f["key"] for f in r["routes"]["flags"]}
    stop = "yes" in (route["cheque_bounced"], route["existing_proceedings"], route["insolvency"])
    warn = (route["cheque_bounced"] == "unsure" or route["cheque_given"] == "yes") and route["cheque_bounced"] != "yes" or disputed or age >= 730
    assert routes["blocks_notice"] == stop and r["route_acknowledgement_needed"] == stop
    assert routes["advocate_recommended"] == (stop or warn)
    assert ("limitation" in keys) == (age >= 730) and ("msme" in keys) == (route["msme"] in ("yes", "unsure"))
    assert ("cheque" in keys) == (route["cheque_bounced"] in ("yes", "unsure") or route["cheque_given"] == "yes")
    for f in routes["flags"]:
        assert not re.search(r"\b(section|article)\s*\d", f["text"], re.I), f["key"]   # a warning may say how old a debt is, never which law or what deadline
    stub("generic", draft_reply(), contains=debtor)
    stub("generic", draft_reply(), contains=debtor)  # one reply for each of the two drafts below
    plain = c.post(f"/recovery/cases/{cid}/notice")
    acked = c.post(f"/recovery/cases/{cid}/notice", json={"acknowledge_route": True})
    if stop:
        assert plain.status_code == 409 and acked.status_code == 200
    else:
        assert plain.status_code == 200 and acked.status_code == 200


# ------------------------------------------------------------------ RS06
THREATS = ["We will have you arrested.", "We will call the police.", "You will go to jail.", "This is a criminal matter.", "We will file an FIR.", "This is a scam.", "You cheated us.", "This is fraud."]
LAW = ["Under Section 138 you must pay.", "Article 21 applies.", "As per the Negotiable Instruments Act you owe this.", "Order 37 rule 2 applies.", "This falls under the IPC.", "The BNS applies."]
BLANKS = ["Pay [amount] now.", "Dated [date].", "To {{name}}."]
MONEY = re.compile(r"(?:(?:Rs\.?|INR|₹)\s*(\d[\d,]*(?:\.\d+)?))|(?:(\d[\d,]*(?:\.\d+)?)\s*INR)", re.I)


def s_wording(case, c):
    rng = rng_of(case)
    amount = money(rng, 5000, 900000)
    cid, debtor = new_case(c, amount=amount)
    paid = 0.0
    if rng.random() < 0.5:
        paid = round(amount * rng.uniform(0.1, 0.5), 2)
        assert c.post(f"/recovery/cases/{cid}/payment", json={"amount": paid}).status_code == 200
    bal = round(amount - paid, 2)
    kind = rng.choice(["clean", "bal_indian", "bal_plain", "bal_inr", "paid_mention", "wrong_amount", "wrong_small", "law", "threat", "blank", "mixed"])
    indian = f"{bal:,.2f}"          # western grouping is what the statement prints; the Indian form below differs in the commas
    whole = int(bal)
    ind = re.sub(r"(\d)(?=(\d\d)+\d$)", r"\1,", str(whole)) if whole >= 1000 else str(whole)
    extra = {
        "clean": "", "bal_indian": f"\nThe balance of Rs {ind}.{int(round((bal - whole) * 100)):02d} is unpaid.", "bal_plain": f"\nThe balance of Rs {bal:.2f} is unpaid.",
        "bal_inr": f"\nPlease pay INR {indian}.", "paid_mention": f"\nYou paid Rs {paid:,.2f} earlier." if paid else "", "wrong_amount": "\nYou owe Rs 99,99,999.",
        "wrong_small": f"\nYou owe Rs {bal + 1:,.2f}.", "law": "\n" + rng.choice(LAW), "threat": "\n" + rng.choice(THREATS), "blank": "\n" + rng.choice(BLANKS),
        "mixed": "\n" + rng.choice(THREATS) + " You owe Rs 12,345.",
    }[kind]
    stub("generic", draft_reply(extra), contains=debtor)
    r = c.post(f"/recovery/cases/{cid}/notice")
    assert r.status_code == 200, r.text
    body = r.json()["notice_body"]
    # independent oracle over the notice text the app produced
    statement, prose = set(), []
    for line in body.splitlines():
        in_st = re.match(r"^\s*[+\-=]\s.*INR", line, re.I)
        for m in MONEY.finditer(line):
            v = Fraction((m.group(1) or m.group(2)).replace(",", ""))
            (statement.add(v) if in_st else prose.append(v))
    assert Fraction(f"{bal:.2f}") in statement, "the calculated balance must be printed in the statement"
    stray = [v for v in prose if v not in statement] if statement else []
    law = bool(re.search(r"\b(section|sec\.|article|art\.|order|rule)\s*\d|\b(IPC|BNS|BNSS|CrPC|CPC)\b|\bAct\b", body, re.I))
    threat = bool(re.search(r"\b(arrest\w*|jail\w*|imprison\w*|police|FIR|criminal\w*|cheat\w*|fraud\w*|scam\w*)\b", body, re.I))
    blank = bool(re.search(r"\[[^\[\]\n]{0,80}\]|\{\{[^{}\n]{0,80}\}\}", body))
    expected_blocked = bool(stray) or law or threat or blank
    prev = c.get(f"/recovery/cases/{cid}/notice-preview").json()["blockers"]
    assert prev["blocked"] == expected_blocked, (kind, prev, stray, law, threat, blank)
    assert bool(prev["amount_mismatches"]) == bool(stray) and bool(prev["risky_language"]) == threat
    assert (c.get(f"/recovery/cases/{cid}/notice.pdf").status_code == 409) == expected_blocked


# ------------------------------------------------------------------ RS07
def s_approval(case, c):
    def tag():  # random but never digits or hex letters that can look like a currency code next to a number
        return "".join("ghjkmnpqrstvwxyz"[int(ch, 16)] for ch in uuid.uuid4().hex[:6])

    rng = rng_of(case)
    cid, debtor = new_case(c)
    stub("generic", draft_reply(), contains=debtor)
    assert c.post(f"/recovery/cases/{cid}/notice").status_code == 200
    seen: dict[int, str] = {}
    current_v, approved = 1, False

    def versions():
        vs = c.get(f"/recovery/cases/{cid}/notice/versions").json()
        for v in vs:
            if v["number"] in seen:
                assert seen[v["number"]] == v["body"], "an old version changed"
            seen[v["number"]] = v["body"]
        return vs

    for step in range(rng.randint(3, 8)):
        act = rng.choice(["edit", "edit", "approve", "prepare", "prepare", "approve"])
        if act == "edit":
            body = versions()[0]["body"] + f"\nNote {step}: ref {tag()}."  # letters only: random hex such as "aed1f2" reads as an amount in dirhams ("AED 1"), which blocks approval - the old rare flake in this family
            assert c.patch(f"/recovery/cases/{cid}/notice", json={"notice_body": body}).status_code == 200
            current_v, approved = current_v + 1, False
        elif act == "approve":
            r = c.post(f"/recovery/cases/{cid}/notice/approve", json={"acknowledged": True})
            assert r.status_code == 200, r.text
            approved = True
        else:
            r = c.post(f"/recovery/cases/{cid}/email/prepare", json={"debtor_email": f"cust-{uuid.uuid4().hex[:8]}@example.com"})
            assert r.status_code == (200 if approved else 409), (act, approved, r.status_code, r.text[:120])
        vs = versions()
        assert len(vs) == current_v and vs[0]["number"] == current_v and vs[0]["is_current"] and sum(1 for v in vs if v["is_current"]) == 1
        w = c.get(f"/recovery/cases/{cid}/notice/workflow").json()
        assert (w["state"] == "APPROVED") == approved, (w["state"], approved)


# ------------------------------------------------------------------ RS08
def s_evidence(case, c):
    rng = rng_of(case)
    cid, _ = new_case(c)
    db, files = mongo(), {}
    for i in range(rng.randint(1, 5)):
        data = f"evidence {case['n']} {i} {uuid.uuid4().hex}".encode() * rng.randint(1, 30)
        kind = rng.choice(PROOF_KINDS)
        r = c.post(f"/recovery/cases/{cid}/proofs", files={"file": (f"proof{i}.txt", data)}, data={"kind": kind})
        assert r.status_code == 200, r.text
        files[r.json()["id"]] = (data, kind)
        dup = c.post(f"/recovery/cases/{cid}/proofs", files={"file": (f"again{i}.txt", data)}, data={"kind": "OTHER"})
        assert dup.status_code == 409 and "already" in dup.json()["detail"]
    listed = c.get(f"/recovery/cases/{cid}/proofs").json()
    assert {p["id"] for p in listed} == set(files)
    for pid, (data, kind) in files.items():
        assert c.get(f"/recovery/cases/{cid}/proofs/{pid}/file").content == data
        assert next(p for p in listed if p["id"] == pid)["kind"] == kind
    pid = rng.choice(list(files))
    assert c.patch(f"/recovery/cases/{cid}/proofs/{pid}", json={"kind": "NONSENSE"}).status_code == 422
    assert c.patch(f"/recovery/cases/{cid}/proofs/{pid}", json={"kind": "INVOICE"}).json()["kind"] == "INVOICE"
    gridfs_ids = [p["gridfs_id"] for p in db.recovery_proofs.find({"case_id": cid})]
    assert c.delete(f"/recovery/cases/{cid}").status_code == 200
    assert db.recovery_proofs.count_documents({"case_id": cid}) == 0
    assert all(db.fs.files.find_one({"_id": g}) is None for g in gridfs_ids)


# ------------------------------------------------------------------ RS09
ROUTES = [("get", "", None), ("get", "/readiness", None), ("get", "/proofs", None), ("post", "/payment", {"amount": 5}), ("patch", "/reminders", {"enabled": False}), ("post", "/resolve", None),
          ("post", "/reopen", None), ("post", "/handoff", None), ("get", "/interest", None), ("get", "/limitation", None), ("get", "/statement.pdf", None), ("get", "/statement-preview", None),
          ("get", "/nudge-preview", None), ("get", "/notice.pdf", None), ("get", "/notice-preview", None), ("get", "/notice/versions", None), ("get", "/notice/workflow", None),
          ("post", "/notice/approve", {"acknowledged": True}), ("post", "/email/prepare", {"debtor_email": "x@example.com"}), ("get", "/emails", None), ("get", "/evidence-pack.zip", None),
          ("patch", "/details", {"creditor_address": "x"}), ("patch", "/intake", {"amount": 5}), ("post", "/notice", None), ("get", "/notice/translations", None), ("get", "/notice/delivery", None),
          ("patch", "/statement-schedule", {"schedule": "OFF"}), ("delete", "", None)]


def s_privacy(case, c, other, anon):
    rng = rng_of(case)
    cid, _ = new_case(c)
    for method, path, body in rng.sample(ROUTES, 6):
        kw = {"json": body} if body is not None else {}
        # a second business that has not confirmed its email is refused before the case is even looked up (403); either way nothing about the case is revealed
        assert getattr(other, method)(f"/recovery/cases/{cid}{path}", **kw).status_code in ((403, 404) if path == "/email/prepare" else (404,)), (method, path)
        assert getattr(anon, method)(f"/recovery/cases/{cid}{path}", **kw).status_code == 401, (method, path)
    assert c.get(f"/recovery/cases/{cid}").status_code == 200
    assert cid not in [x["id"] for x in other.get("/recovery/cases").json()]


# ------------------------------------------------------------------ RS10
HOSTILE = ["<script>alert(1)</script>", "'; DROP TABLE cases; --", "x" * 600, "नमस्ते " * 30, "\u0000null", "\U0001F600 emoji", "‮RTL", "../../etc/passwd", "{{STATEMENT}}", " ", "", "$where", "{\"$gt\": \"\"}"]
DATES = ["banana", "2026-02-30", "0000-01-01", "9999-12-31", "2026/01/01", "1 Jan 2026", "", " ", "2026-1-1", "20260101", "٤٠٢٦-01-01"]


def s_robustness(case, c):
    rng = rng_of(case)
    cid, _ = new_case(c, amount=money(rng))
    ok_or_refused = lambda r: r.status_code < 500 and r.status_code in (200, 400, 404, 409, 413, 422)  # noqa: E731
    for _ in range(6):
        pick = rng.randrange(7)
        if pick == 0:
            r = c.patch(f"/recovery/cases/{cid}/details", json={rng.choice(["creditor_address", "debtor_address"]): rng.choice(HOSTILE)})
        elif pick == 1:
            r = c.patch(f"/recovery/cases/{cid}/details", json={"due_date": rng.choice(DATES)})
        elif pick == 2:
            r = c.post(f"/recovery/cases/{cid}/payment", json={"amount": rng.choice([0, -1, 1e-9, 0.001, 1e12, 1e13, "abc", None, 12.345678, True])})
        elif pick == 3:
            pr = c.post(f"/recovery/cases/{cid}/payment", json={"amount": 100})
            r = c.patch(f"/recovery/cases/{cid}/payment/{pr.json()['payments'][-1]['id']}", json={"date": rng.choice(DATES), "amount": rng.choice([None, 50, 0, -5])}) if pr.status_code == 200 else pr
        elif pick == 4:
            r = c.patch(f"/recovery/cases/{cid}/intake", json={rng.choice(["supply_description", "payment_terms", "invoice_number", "debtor_email"]): rng.choice(HOSTILE)})
        elif pick == 5:
            r = c.patch(f"/recovery/cases/{cid}/intake", json={"invoice_date": rng.choice(DATES)})
        else:
            r = c.patch(f"/recovery/cases/{cid}/reminders", json={rng.choice(["snooze_days", "cadence_days"]): rng.choice([-1, 0, 1, 3, 7, 365, 366, 10**9, "x", None])})
        assert ok_or_refused(r), (pick, r.status_code, r.text[:200])
    # whatever happened, the case must still be readable and its figures must still compute
    assert c.get(f"/recovery/cases/{cid}").status_code == 200
    assert c.get(f"/recovery/cases/{cid}/readiness").status_code == 200
    assert c.get(f"/recovery/cases/{cid}/limitation").status_code == 200
    assert c.get(f"/recovery/cases/{cid}/statement-preview").status_code < 500
    if c.get(f"/recovery/cases/{cid}").json().get("due_date"):
        c.patch(f"/recovery/cases/{cid}/details", json={"interest_rate_pct": 12})
        r = c.get(f"/recovery/cases/{cid}/interest")
        assert r.status_code in (200, 422), f"interest crashed: {r.status_code} {r.text[:200]}"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_recovery_scenario(request, case):
    fam = case["family"]
    if fam == 8:
        s_privacy(case, request.getfixturevalue("user_a"), request.getfixturevalue("user_b"), request.getfixturevalue("anon"))
        return
    client = request.getfixturevalue("verified_a" if fam in (5, 6) else "user_a")
    {0: s_ledger, 1: s_intake, 2: s_interest, 3: s_age, 4: s_routes, 5: s_wording, 6: s_approval, 7: s_evidence, 9: s_robustness}[fam](case, client)
