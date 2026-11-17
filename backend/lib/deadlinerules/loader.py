"""Loading court holiday calendars and limitation/deadline rules from FILES the owner supplies, safely. This module writes no rule of its own and no date: it reads a file, checks its shape, and stores what the file says
as UNREVIEWED records that cite the file's official source. Nothing loaded can be used until a named reviewer has marked it reviewed (lib/deadlinerules/store.py) and, for a calendar, an operator has switched it on.

A file is JSON, at most 1 MB, in one of two shapes (docs/deadline-data/README.md has a blank template of each):
  {"kind": "court_calendar", "court": "<court name as VIDHI lists it>", "year": 2026, "source_url": "https://...", "source_checked_on": "YYYY-MM-DD", "weekend_days": [5, 6], "holidays": [{"date": "YYYY-MM-DD", "name": "..."}]}
  {"kind": "deadline_rules", "source_url": "https://...", "source_checked_on": "YYYY-MM-DD", "rules": [{"title", "starts_from", "period": {"amount", "unit"}, "count_from", "when_not_working", "month_end"?, "calendar_court"?, "calendar_year"?, "authorities"?, "not_applied"?}]}
Every file must name its official source (an https link) and the day that source was checked. A file with any problem is refused as a whole: nothing is half-loaded. Everything loaded together shares a batch id, so a batch can be rolled back.

Switched on per court: a calendar is used only if it is reviewed AND enabled; `coverage` reports "reviewed X of Y courts" against the courts VIDHI lists."""

import hashlib
import json
import uuid
from datetime import date

from lib import verified_store as store
from lib.db import db
from lib.deadlinerules import compute
from lib.deadlinerules import store as rules
from lib.legal_store import now

MAX_BYTES = 1_000_000
MAX_RULES = 200


def _norm(name) -> str:
    return " ".join(str(name or "").lower().split())


def parse_file(raw: bytes) -> tuple[dict | None, list[str]]:
    """(data, problems). The shape and every value are checked here; the rules and calendars are checked again by the store when they are created."""
    if len(raw) > MAX_BYTES:
        return None, [f"The file is larger than {MAX_BYTES // 1_000_000} MB."]
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return None, ["The file is not valid JSON in UTF-8."]
    if not isinstance(data, dict) or data.get("kind") not in ("court_calendar", "deadline_rules"):
        return None, ['The file must be an object whose "kind" is "court_calendar" or "deadline_rules".']
    problems: list[str] = []
    url = str(data.get("source_url") or "").strip()
    if not url.lower().startswith("https://") or len(url) > 500 or " " in url:
        problems.append('"source_url" must be the official source, an https link.')
    try:
        checked = compute.parse_day(str(data.get("source_checked_on") or ""), "source_checked_on")
        if checked > date.today():
            problems.append('"source_checked_on" cannot be in the future.')
    except compute.RuleError as exc:
        problems.append(str(exc))
    if data["kind"] == "court_calendar":
        court = " ".join(str(data.get("court") or "").split())
        if not 3 <= len(court) <= 120:
            problems.append('"court" must be the court\'s name, 3 to 120 characters.')
        if not (isinstance(data.get("year"), int) and not isinstance(data.get("year"), bool) and 2000 <= data["year"] <= 2100):
            problems.append('"year" must be a whole year from 2000 to 2100.')
        if not isinstance(data.get("holidays"), list) or not data["holidays"]:
            problems.append('"holidays" must be a list with at least one holiday.')
        if "weekend_days" not in data:
            problems.append('"weekend_days" must be given (an empty list if the court sits every day).')
    else:
        items = data.get("rules")
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_RULES:
            problems.append(f'"rules" must be a list of 1 to {MAX_RULES} rules.')
    return (None, problems) if problems else (data, [])


async def _court_names() -> dict[str, str]:
    """The courts VIDHI lists (the ones its judgment list holds), by normalised name. Not cached: counting is what is slow, naming 26 courts is not."""
    names = {}
    for code in await db.hc_judgments.distinct("court_code"):
        one = await db.hc_judgments.find_one({"court_code": code}, {"court_name": 1, "_id": 0})
        if one and one.get("court_name"):
            names[_norm(one["court_name"])] = one["court_name"]
    return names


async def _calendar_for(court: str, year) -> dict | None:
    flt = {"court_norm": _norm(court)}
    if year:
        flt["year"] = year
    rows = await db.deadline_calendars.find(flt).sort("created_at", -1).to_list(5)
    return rows[0] if rows else None


async def load(raw: bytes, filename: str, who: str, dry_run: bool = False) -> dict:
    """Parse and (unless dry_run) store a file. Returns {ok, problems, batch_id, kind, created, court_known, warnings}. Nothing is stored when there is any problem."""
    data, problems = parse_file(raw)
    if problems:
        return {"ok": False, "problems": problems, "created": []}
    sha, batch = hashlib.sha256(raw).hexdigest(), str(uuid.uuid4())
    meta = {"batch_id": batch, "file_name": (filename or "file")[:120], "file_sha256": sha, "source_url": data["source_url"].strip(), "source_checked_on": data["source_checked_on"], "loaded_by": who}
    if await db.deadline_calendars.find_one({"file_sha256": sha}) or await db.deadline_rules.find_one({"file_sha256": sha}):
        return {"ok": False, "problems": ["This exact file has already been loaded. Roll its batch back first if you want to load it again."], "created": []}
    warnings: list[str] = []
    created: list[dict] = []
    try:
        if data["kind"] == "court_calendar":
            court = " ".join(data["court"].split())
            known = (await _court_names()).get(_norm(court))
            if not known:
                warnings.append(f'"{court}" is not one of the courts VIDHI lists, so it will not count towards "reviewed X of Y courts" until the name matches.')
            title = f"{known or court} holidays {data['year']}"
            if dry_run:
                created.append({"title": title, "holidays": len(data["holidays"])})
            else:
                cal = await rules.create_calendar({"title": title, "weekend_days": data["weekend_days"], "holidays": data["holidays"], "authorities": [meta["source_url"]]}, who)
                await store.change(db, "deadline_calendars", {"id": cal["id"]}, {**meta, "court": known or court, "court_norm": _norm(known or court), "year": data["year"], "enabled": False})
                created.append({"id": cal["id"], "title": title, "holidays": len(cal["holidays"])})
        else:
            for item in data["rules"]:
                if not isinstance(item, dict):
                    raise ValueError("Each rule must be an object.")
                cal_id = None
                if item.get("calendar_court"):
                    cal = await _calendar_for(item["calendar_court"], item.get("calendar_year"))
                    if not cal:
                        raise ValueError(f'Rule "{str(item.get("title"))[:60]}" names a calendar for {item["calendar_court"]}, but none is loaded. Load the calendar file first.')
                    cal_id = cal["id"]
                body = {**{k: item.get(k) for k in ("title", "starts_from", "period", "count_from", "when_not_working", "month_end", "not_applied")}, "calendar_id": cal_id,
                        "authorities": list(item.get("authorities") or []) + [meta["source_url"]]}
                if dry_run:
                    rules_check = {"period": item.get("period"), "count_from": item.get("count_from"), "when_not_working": item.get("when_not_working")}
                    if item.get("month_end"):
                        rules_check["month_end"] = item["month_end"]
                    compute.check_rule(rules_check)
                    created.append({"title": str(item.get("title"))[:120]})
                else:
                    r = await rules.create_rule(body, who)
                    await store.change(db, "deadline_rules", {"id": r["id"]}, meta)
                    created.append({"id": r["id"], "title": r["title"]})
    except (ValueError, compute.RuleError) as exc:
        if not dry_run:
            await rollback(batch, who, "the file could not be loaded completely", quiet=True)  # nothing is half-loaded
        return {"ok": False, "problems": [str(exc)], "created": []}
    return {"ok": True, "problems": [], "dry_run": dry_run, "batch_id": None if dry_run else batch, "kind": data["kind"], "created": created, "warnings": warnings,
            "note": "Loaded as UNREVIEWED. Nothing can be used until a named reviewer marks it reviewed" + (" and an operator switches the calendar on." if data["kind"] == "court_calendar" else ".")}


async def rollback(batch_id: str, who: str, reason: str, quiet: bool = False) -> dict:
    """Undo a load. Records still unreviewed are deleted. A record that was reviewed is not deleted (the review stays on record): it goes back to unreviewed, a calendar is switched off, and the withdrawal is noted."""
    deleted = withdrawn = 0
    for coll in ("deadline_calendars", "deadline_rules"):
        for doc in await db[coll].find({"batch_id": batch_id}).to_list(1000):
            if doc.get("review_status") == "reviewed":
                await store.restore_review(db, coll, doc["id"], {"review_status": "unreviewed", "reviewed_by": None, "verified_on": None})  # back to unreviewed through the store, which owns the review state
                await store.change(db, coll, {"id": doc["id"]}, {"enabled": False, "withdrawn": {"by": who, "on": now().date().isoformat(), "reason": reason[:300]},
                                                                "previously_reviewed": {"reviewed_by": doc.get("reviewed_by"), "verified_on": doc.get("verified_on")}})
                withdrawn += 1
            else:
                await store.delete(db, coll, {"id": doc["id"]}, many=False)
                deleted += 1
    return {"batch_id": batch_id, "deleted": deleted, "withdrawn": withdrawn}


async def set_enabled(cal_id: str, on: bool) -> dict:
    cal = await db.deadline_calendars.find_one({"id": cal_id})
    if not cal:
        raise ValueError("Unknown calendar.")
    if on and cal.get("review_status") != "reviewed":
        raise ValueError("A calendar can be switched on only after a named reviewer has marked it reviewed.")
    await store.change(db, "deadline_calendars", {"id": cal_id}, {"enabled": bool(on)})
    return {"id": cal_id, "enabled": bool(on)}


async def coverage() -> dict:
    """'Reviewed X of Y courts': Y = the courts VIDHI lists; X = those with a calendar that is reviewed and switched on."""
    courts = await _court_names()
    cals = await db.deadline_calendars.find({"court_norm": {"$exists": True}}).to_list(2000)
    rows = []
    for key, name in courts.items():
        mine = [c for c in cals if c.get("court_norm") == key]
        live = [c for c in mine if c.get("review_status") == "reviewed" and c.get("enabled")]
        rows.append({"court": name, "calendars": [{"id": c["id"], "year": c.get("year"), "review_status": c.get("review_status"), "reviewed_by": c.get("reviewed_by"), "verified_on": c.get("verified_on"),
                                                   "enabled": bool(c.get("enabled")), "holidays": len(c.get("holidays", [])), "source_url": c.get("source_url"), "source_checked_on": c.get("source_checked_on"),
                                                   "batch_id": c.get("batch_id")} for c in sorted(mine, key=lambda c: c.get("year") or 0)], "live": bool(live)})
    unmatched = [c for c in cals if c.get("court_norm") not in courts]
    return {"courts_total": len(rows), "courts_live": sum(1 for r in rows if r["live"]), "courts": rows, "unmatched_calendars": [{"id": c["id"], "court": c.get("court"), "year": c.get("year")} for c in unmatched],
            "summary": f"Reviewed and switched on for {sum(1 for r in rows if r['live'])} of {len(rows)} courts."}
