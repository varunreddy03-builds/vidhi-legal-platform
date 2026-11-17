"""Instant decisions in code: filtering, scoring and categorising text and data with plain rules. No AI, no cost, no waiting,
and the same input always gives the same answer. Every result carries its REASONS in plain words, so a person can see why.

  evaluate(ctx, RULES)      -> total points + the rules that fired      (scoring)
  band(score, BANDS)        -> a level such as "urgent" / "soon" / "ok" (filtering / triage)
  categorise(text, CATS)    -> the best category with the words that matched (categorising)

This module never states law and never decides a legal question: it only helps sort what to look at first. Lawyers decide."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable


@dataclass(frozen=True)
class Rule:
    id: str
    label: str  # shown to the person, plain words
    points: int
    test: Callable[[dict], bool]


def evaluate(ctx: dict, rules: list[Rule]) -> tuple[int, list[dict]]:
    fired = [{"id": r.id, "label": r.label, "points": r.points} for r in rules if r.test(ctx)]
    return sum(f["points"] for f in fired), fired


def band(score: int, bands: list[tuple[int, str]], default: str) -> str:
    """bands = [(minimum score, level), ...] from highest to lowest."""
    return next((level for floor, level in bands if score >= floor), default)


# --------------------------------------------------------------------------------------------------------------------
# Recovery cases: which one needs attention first
# --------------------------------------------------------------------------------------------------------------------
def _as_dt(v) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def case_context(case: dict, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    now = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    due = None
    try:
        due = date.fromisoformat(case["due_date"]) if case.get("due_date") else None
    except ValueError:
        pass
    updated = _as_dt(case.get("updated_at")) or now
    snooze = _as_dt(case.get("snooze_until"))
    check = case.get("notice_check") or {}
    return {
        "status": case.get("status", "DRAFT"),
        "outstanding": max(0.0, float(case.get("amount") or 0) - float(case.get("paid_amount") or 0)),
        "days_overdue": (today - due).days if due and today > due else 0,
        "days_idle": max(0, (now - updated).days),
        "email_bounced": case.get("debtor_email_status") in ("BOUNCED", "COMPLAINED"),
        "blanks": bool(check.get("placeholders") or check.get("blanks")),
        "snoozed": bool(snooze and snooze > now),
    }


CASE_RULES = [
    Rule("bounced", "The notice email did not reach the customer. Try another way to deliver it.", 30, lambda c: c["email_bounced"]),
    Rule("ready", "Your notice is ready. Check it and send it.", 18, lambda c: c["status"] == "NOTICE_READY"),
    Rule("waiting", "It has been two weeks or more since you sent it and nothing is recorded. Record any reply, or decide the next step.", 18, lambda c: c["status"] == "SENT_FOR_REVIEW" and c["days_idle"] >= 14),
    Rule("blanks", "The notice still has blanks to fill in.", 10, lambda c: c["blanks"] and c["status"] in ("TIMELINE_READY", "NOTICE_READY")),
    Rule("stalled_draft", "You started this but have not added your papers yet.", 10, lambda c: c["status"] == "DRAFT" and c["days_idle"] >= 7),
    Rule("idle_month", "Nothing has happened here for a month.", 10, lambda c: c["days_idle"] >= 30),
    Rule("overdue_year", "The money has been due for over a year. Old dues can be harder to recover, so ask a lawyer whether any time limit applies.", 22, lambda c: c["days_overdue"] >= 365),
    Rule("overdue_quarter", "The money has been due for over three months.", 12, lambda c: 90 <= c["days_overdue"] < 365),
    Rule("overdue_month", "The money has been due for over a month.", 6, lambda c: 30 <= c["days_overdue"] < 90),
    Rule("large", "A large amount is still owed.", 14, lambda c: c["outstanding"] >= 100000),
    Rule("sizeable", "A sizeable amount is still owed.", 7, lambda c: 25000 <= c["outstanding"] < 100000),
    Rule("snoozed", "You paused reminders for this case.", -25, lambda c: c["snoozed"]),
]
CASE_BANDS = [(40, "urgent"), (20, "soon")]


def case_priority(case: dict, today: date | None = None) -> dict:
    """{score 0-100, level urgent|soon|ok|done, reasons[]} - how soon this case deserves a look, and why."""
    if case.get("status") == "RESOLVED":
        return {"score": 0, "level": "done", "reasons": []}
    total, fired = evaluate(case_context(case, today), CASE_RULES)
    score = max(0, min(100, total))
    return {"score": score, "level": band(score, CASE_BANDS, "ok"), "reasons": [f["label"] for f in sorted(fired, key=lambda f: -f["points"]) if f["points"] > 0]}


# --------------------------------------------------------------------------------------------------------------------
# Questions: what kind of help does this look like
# --------------------------------------------------------------------------------------------------------------------
def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "").casefold()).strip()


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    route: str  # where to send the person: "recovery" (Legal Recovery), "lawyer" (speak to one soon) or "ask" (stay and ask)
    words: tuple[tuple[str, int], ...]  # (phrase, weight). Latin phrases match whole words; other scripts match as written.


CATEGORIES = [
    Category("money_recovery", "Money someone owes you", "recovery", (
        ("not paid", 3), ("has not paid", 3), ("hasn't paid", 3), ("didn't pay", 3), ("did not pay", 3), ("unpaid", 3), ("owes me", 3), ("owe me", 3),
        ("outstanding", 2), ("invoice", 2), ("pending payment", 3), ("payment pending", 3), ("dues", 2), ("balance due", 3), ("borrowed", 2), ("loan", 1),
        ("return my money", 3), ("returned my money", 3), ("cheque bounce", 3), ("bounced cheque", 3), ("recover my money", 4), ("money back", 2),
        ("पैसे नहीं", 3), ("पैसा नहीं", 3), ("बकाया", 3), ("उधार", 3), ("भुगतान नहीं", 3), ("चेक बाउंस", 3), ("पैसे वापस", 3), ("पैसा वापस", 3), ("बिल", 1),
    )),
    Category("rent_property", "Rent or property", "ask", (
        ("rent", 2), ("tenant", 3), ("landlord", 3), ("lease", 2), ("eviction", 3), ("evict", 3), ("security deposit", 3), ("property", 1),
        ("किराया", 3), ("किरायेदार", 3), ("मकान मालिक", 3), ("जमीन", 1), ("संपत्ति", 1),
    )),
    Category("consumer", "Buying something that went wrong", "ask", (
        ("defective", 3), ("warranty", 3), ("refund", 2), ("consumer", 2), ("seller", 1), ("online order", 2), ("faulty", 3), ("damaged product", 3),
        ("खराब सामान", 3), ("वारंटी", 3), ("रिफंड", 2),
    )),
    Category("employment", "Work and salary", "ask", (
        ("salary", 3), ("wages", 3), ("employer", 3), ("terminated", 3), ("fired", 3), ("resign", 2), ("notice period", 2), ("provident fund", 2),
        ("वेतन", 3), ("तनख्वाह", 3), ("नौकरी", 2), ("नियोक्ता", 3),
    )),
    Category("family", "Family matters", "ask", (
        ("divorce", 3), ("custody", 3), ("maintenance", 1), ("alimony", 3), ("marriage", 1), ("inheritance", 3), ("will", 1), ("succession", 2),
        ("तलाक", 3), ("विरासत", 3), ("गुजारा भत्ता", 3),
    )),
    Category("contract", "Reading or making an agreement", "ask", (
        ("agreement", 2), ("contract", 2), ("clause", 3), ("terms and conditions", 3), ("before signing", 3), ("sign this", 2), ("draft an agreement", 3),
        ("अनुबंध", 3), ("समझौता", 2), ("करार", 2),
    )),
    Category("urgent_safety", "Something that may need a lawyer right away", "lawyer", (
        ("arrest", 4), ("arrested", 4), ("police", 3), ("fir", 3), ("bail", 3), ("jail", 3), ("threat", 2), ("threatened", 3), ("violence", 4),
        ("harass", 3), ("harassment", 3), ("summons", 4), ("court notice", 4),
        ("गिरफ्तार", 4), ("पुलिस", 3), ("जमानत", 3), ("धमकी", 3), ("हिंसा", 4), ("समन", 4),
    )),
]


def _matches(text: str, phrase: str) -> bool:
    p = normalise(phrase)
    if re.search(r"[a-z]", p):  # Latin words: whole words only ("will" must not match "willing")
        return re.search(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", text) is not None
    return p in text


def categorise(text: str, categories: list[Category] = CATEGORIES, min_points: int = 3) -> dict:
    """{category, label, route, confidence low|medium|high, matched[]}; category is None when nothing fits well enough."""
    t = normalise(text)
    scored = []
    for c in categories:
        hits = [(w, pts) for w, pts in c.words if _matches(t, w)]
        scored.append((sum(p for _, p in hits), c, [w for w, _ in hits]))
    scored.sort(key=lambda s: -s[0])
    top, cat, hits = scored[0]
    if top < min_points:
        return {"category": None, "label": None, "route": "ask", "confidence": "low", "matched": []}
    margin = top - scored[1][0]
    return {"category": cat.id, "label": cat.label, "route": cat.route, "confidence": "high" if top >= 6 and margin >= 3 else "medium" if margin >= 2 else "low", "matched": hits}