"""Limitation (time-limit) warning for money claims.

Project rule 1: never invent law. So this module contains NO time periods of its own. Periods come only
from entries in data/limitation_rules.json that are marked verified AND carry the exact source text,
citation, source URL and who verified them. With no verified entries (the state today) the warning is
generic: it shows how old the debt is and tells the user that time limits exist and to see a lawyer.
"""

import json
from datetime import date
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "limitation_rules.json"
REQUIRED = ("id", "applies_to", "period_years", "citation", "source_text", "source_url", "verified_by", "verified_on")

GENERIC_MESSAGE = (
    "Courts apply time limits to money claims, and a claim can be lost if it is brought too late. "
    "How long you have depends on the kind of claim and on what has happened since the debt fell due. "
    "We cannot tell you your deadline - please speak to a lawyer soon, and sooner for an older debt."
)
LAWYER_NOTE = "Confirm with a lawyer: the right rule depends on the facts of your claim."


def load_verified_rules(path: Path | None = None) -> list[dict]:
    """Only entries that are verified and fully sourced are ever used."""
    try:
        data = json.loads((path or RULES_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rules = []
    for r in data.get("rules", []) if isinstance(data, dict) else []:
        if not isinstance(r, dict) or r.get("verified") is not True:
            continue
        if any(not r.get(k) for k in REQUIRED) or not isinstance(r["period_years"], int) or r["period_years"] <= 0:
            continue
        rules.append(r)
    return rules


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def age_text(start: date, today: date) -> str:
    months = (today.year - start.year) * 12 + (today.month - start.month) - (1 if today.day < start.day else 0)
    months = max(0, months)
    y, m = divmod(months, 12)
    parts = []
    if y:
        parts.append(f"{y} year{'s' if y != 1 else ''}")
    if m:
        parts.append(f"{m} month{'s' if m != 1 else ''}")
    return " and ".join(parts) if parts else ("less than a month" if today >= start else "not yet due")


def assess(due_date: str | None, today: date, rules: list[dict] | None = None) -> dict:
    if not due_date:
        return {
            "mode": "NEEDS_DUE_DATE",
            "message": "Add the date the money was due to see how old this debt is.",
            "age_days": None,
            "age_text": None,
            "rules": [],
        }
    try:
        due = date.fromisoformat(due_date[:10])
    except ValueError:
        return {"mode": "NEEDS_DUE_DATE", "message": "That due date is not valid.", "age_days": None, "age_text": None, "rules": []}
    rules = load_verified_rules() if rules is None else rules
    out = {
        "mode": "VERIFIED_RULES" if rules else "GENERIC",
        "due_date": due.isoformat(),
        "age_days": (today - due).days,
        "age_text": age_text(due, today),
        "message": GENERIC_MESSAGE if not rules else LAWYER_NOTE,
        "rules": [],
    }
    for r in rules:
        deadline = _add_years(due, r["period_years"])
        days_left = (deadline - today).days
        out["rules"].append(
            {
                "id": r["id"],
                "applies_to": r["applies_to"],
                "period_years": r["period_years"],
                "citation": r["citation"],
                "source_text": r["source_text"],
                "source_url": r["source_url"],
                "verified_by": r["verified_by"],
                "verified_on": r["verified_on"],
                "deadline": deadline.isoformat(),
                "days_left": days_left,
                "status": "PASSED" if days_left < 0 else ("SOON" if days_left <= 180 else "OK"),
            }
        )
    return out
