"""Deadline rules and calendars of non-working days: entered by a person, shown only after a named reviewer has marked them reviewed.

Nothing here is law. A rule is DATA (a period, how to count it, the sources it comes from); the arithmetic is in compute.py and has no defaults. Like the old-to-new section mappings, a record starts
`unreviewed`, can be reviewed only if it cites a source, and a rule that moves a date off a non-working day can be reviewed only if its calendar is reviewed."""

import uuid

from lib import verified_store as store
from lib.db import db
from lib.deadlinerules import compute
from lib.legal_store import now

NOTICE = ("VIDHI applied only the rule shown below, as a person recorded it and a named reviewer checked it. It has not checked that the rule applies to your matter, whether time can be extended or excluded, "
          "or whether another period also runs. Check the date by hand and against the official source. A lawyer decides.")
NONE_LOADED = "No reviewed rule is loaded yet, so nothing can be calculated."
MAX_HOLIDAYS = 400


def _text(value, field: str, low: int, high: int) -> str:
    s = " ".join(str(value or "").split())
    if not low <= len(s) <= high:
        raise ValueError(f"{field} must be {low} to {high} characters.")
    return s


def _sources(values) -> list[str]:
    out = [" ".join(str(a).split())[:300] for a in (values or []) if str(a).strip()]
    if len(out) > 10:
        raise ValueError("Give at most 10 sources.")
    return out


def _view(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "_id"}


async def create_calendar(d: dict, recorded_by: str) -> dict:
    weekend = d.get("weekend_days", [])
    if not isinstance(weekend, list) or any(isinstance(x, bool) or not isinstance(x, int) or not 0 <= x <= 6 for x in weekend) or len(set(weekend)) != len(weekend):
        raise ValueError("weekend_days must be a list of different numbers from 0 (Monday) to 6 (Sunday), or empty.")
    holidays, seen = [], set()
    for h in d.get("holidays", []):
        day = compute.parse_day(h.get("date", ""), "holiday date").isoformat()
        if day in seen:
            raise ValueError(f"{day} is listed twice.")
        seen.add(day)
        holidays.append({"date": day, "name": _text(h.get("name"), "A holiday name", 1, 120)})
    if len(holidays) > MAX_HOLIDAYS:
        raise ValueError(f"Give at most {MAX_HOLIDAYS} holidays in one calendar.")
    doc = {"id": str(uuid.uuid4()), "title": _text(d.get("title"), "The title", 3, 200), "weekend_days": sorted(weekend), "holidays": sorted(holidays, key=lambda h: h["date"]),
           "authorities": _sources(d.get("authorities")), "review_status": "unreviewed", "reviewed_by": None, "verified_on": None, "recorded_by": recorded_by, "created_at": now()}
    await store.create(db, "deadline_calendars", doc)
    return _view(doc)


async def create_rule(d: dict, recorded_by: str) -> dict:
    rule = {"period": {"amount": (d.get("period") or {}).get("amount"), "unit": (d.get("period") or {}).get("unit")}, "count_from": d.get("count_from"), "when_not_working": d.get("when_not_working")}
    if d.get("month_end"):
        rule["month_end"] = d["month_end"]
    try:
        compute.check_rule(rule)
    except compute.RuleError as exc:
        raise ValueError(str(exc)) from exc
    cal_id = d.get("calendar_id") or None
    if rule["when_not_working"] == "move_to_next_working_day" and not cal_id:
        raise ValueError("A rule that moves a date off a non-working day must name its calendar.")
    if cal_id and not await db.deadline_calendars.find_one({"id": cal_id}):
        raise ValueError("Unknown calendar.")
    doc = {"id": str(uuid.uuid4()), "title": _text(d.get("title"), "The title", 3, 200), "starts_from": _text(d.get("starts_from"), "What the period starts from", 3, 200), **rule,
           "calendar_id": cal_id, "not_applied": [_text(x, "A condition", 3, 300) for x in (d.get("not_applied") or [])][:10], "authorities": _sources(d.get("authorities")),
           "review_status": "unreviewed", "reviewed_by": None, "verified_on": None, "recorded_by": recorded_by, "created_at": now()}
    await store.create(db, "deadline_rules", doc)
    return _view(doc)


def _reviewer(reviewer: str, on: str) -> tuple[str, str]:
    if len((reviewer or "").strip()) < 5:
        raise ValueError("Give the reviewer's full name.")
    try:
        day = compute.parse_day(on, "review date").isoformat()
    except compute.RuleError as exc:
        raise ValueError(str(exc)) from exc
    return reviewer.strip()[:120], day


async def review_calendar(cal_id: str, reviewer: str, on: str) -> dict:
    c = await db.deadline_calendars.find_one({"id": cal_id})
    if not c:
        raise ValueError("Unknown calendar.")
    name, day = _reviewer(reviewer, on)
    if not c["authorities"]:
        raise ValueError("A calendar can be marked reviewed only if it cites an official source. Add the source first.")
    await store.record_review(db, "deadline_calendars", cal_id, "reviewed", name, day, "; ".join(c["authorities"]))
    return _view(await db.deadline_calendars.find_one({"id": cal_id}))


async def review_rule(rule_id: str, reviewer: str, on: str) -> dict:
    r = await db.deadline_rules.find_one({"id": rule_id})
    if not r:
        raise ValueError("Unknown rule.")
    name, day = _reviewer(reviewer, on)
    if not r["authorities"]:
        raise ValueError("A rule can be marked reviewed only if it cites an official source. Add the source first.")
    if r["when_not_working"] == "move_to_next_working_day":
        c = await db.deadline_calendars.find_one({"id": r.get("calendar_id")})
        if not c or c["review_status"] != "reviewed":
            raise ValueError("This rule moves dates off non-working days, so its calendar must be reviewed first.")
    await store.record_review(db, "deadline_rules", rule_id, "reviewed", name, day, "; ".join(r["authorities"]))
    return _view(await db.deadline_rules.find_one({"id": rule_id}))


def calendar_usable(cal: dict | None) -> bool:
    """A calendar is used only if it is reviewed and not switched off (a calendar without the switch, from before it existed, counts as on)."""
    return bool(cal) and cal.get("review_status") == "reviewed" and cal.get("enabled") is not False


async def list_rules(reviewed_only: bool) -> list[dict]:
    q = {"review_status": "reviewed"} if reviewed_only else {}
    rows = await db.deadline_rules.find(q).sort("created_at", 1).to_list(500)
    if reviewed_only:  # a rule that needs a calendar is offered only while that calendar is usable, so nothing is listed that cannot be calculated
        cals = {c["id"]: c for c in await db.deadline_calendars.find({}).to_list(2000)}
        rows = [r for r in rows if r["when_not_working"] != "move_to_next_working_day" or calendar_usable(cals.get(r.get("calendar_id")))]
    return [_view({k: v for k, v in r.items() if not (reviewed_only and k in ("recorded_by", "created_at"))}) for r in rows]


async def list_calendars() -> list[dict]:
    return [_view(c) for c in await db.deadline_calendars.find({}).sort("created_at", 1).to_list(200)]


async def calculate(rule_id: str, start: str) -> dict:
    """Only a REVIEWED rule can be used. The result carries the rule, its sources, its reviewer, the conditions it does not apply, and the full working."""
    r = await db.deadline_rules.find_one({"id": rule_id})
    if not r or r["review_status"] != "reviewed":
        raise LookupError("That rule is not available.")
    cal = None
    if r["when_not_working"] == "move_to_next_working_day":
        cal = await db.deadline_calendars.find_one({"id": r.get("calendar_id")})
        if not calendar_usable(cal):
            raise LookupError("That rule is not available.")
    got = compute.calculate(r, start, cal)
    rule = {k: r[k] for k in ("id", "title", "starts_from", "period", "count_from", "when_not_working", "not_applied", "authorities", "reviewed_by", "verified_on")}
    if "month_end" in r:
        rule["month_end"] = r["month_end"]
    calendar = {k: cal[k] for k in ("title", "authorities", "reviewed_by", "verified_on")} if cal else None
    return {**got, "start": start.strip(), "rule": rule, "calendar": calendar, "notice": NOTICE}
