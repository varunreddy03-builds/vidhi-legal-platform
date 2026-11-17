"""Was this law in force on that date? Only from dates written in the official manifest text; an unknown date stays unknown and nothing is guessed.

The manifest gives each Act a free-text "commencement" ("In force from 01-07-2024 (S.O. 850(E))", "REPEALED by BNS w.e.f. 01-07-2024", "2016-10-08") and a "legal currency" note.
This module reads at most two dates from them: when the Act started and when it ended. It never fills a gap: no start date means we do not know when it started.
Provisions that came into force on a different date from the rest of the Act ("except s.106(2)") are not split out; the note is carried so a person can read it."""

import json
import os
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
NUM = re.compile(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?!\d)")
ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
WORDS = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")[a-z]*\.?,?\s+(\d{4})", re.I)
END_WORDS = re.compile(r"repeal|ceased|omitted|expired|replaced", re.I)


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def dates_in(text: str) -> list[tuple[int, date]]:
    """Every date written in the text, with its position, in the order written."""
    found: list[tuple[int, date]] = []
    for m in ISO.finditer(text or ""):
        d = _mk(int(m[1]), int(m[2]), int(m[3]))
        if d:
            found.append((m.start(), d))
    for m in NUM.finditer(text or ""):
        d = _mk(int(m[3]), int(m[2]), int(m[1]))  # Indian order: day-month-year
        if d:
            found.append((m.start(), d))
    for m in WORDS.finditer(text or ""):
        d = _mk(int(m[3]), MONTHS[m[2].lower()], int(m[1]))
        if d:
            found.append((m.start(), d))
    return sorted(found)


@lru_cache(maxsize=1)
def _sidecar() -> dict:
    """How each Act says it starts, read from the Act's own section 1 by scripts/law_commencement.py (only for Acts the manifest gives no date for)."""
    folder = Path(os.environ.get("LIBRARY_DIR") or Path(__file__).resolve().parent.parent / "data" / "legal_library")
    f = folder / "pending" / "_commencement.json"  # a file whose name starts with "_" is never read as a law entry
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    except (OSError, ValueError):
        return {}


def _library_folder() -> Path:
    return Path(os.environ.get("LIBRARY_DIR") or Path(__file__).resolve().parent.parent / "data" / "legal_library")


@lru_cache(maxsize=8)
def _notifications_at(path: str, stamp: int) -> dict:
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8")).get("notifications", [])
    except (OSError, ValueError):
        return {}
    out: dict = {}
    for n in rows:
        if isinstance(n, dict) and n.get("stages") and n.get("number") and n.get("file"):
            for a in n.get("act_ids", []):
                out[str(a)] = n
    return out


def notification_for(act_id: str | None) -> dict | None:
    """The Gazette notification (supplied by the owner, `_commencement_notifications.json`) that sets this Act's start date, or None. Re-read when the file changes."""
    f = _library_folder() / "_commencement_notifications.json"
    try:
        stamp = f.stat().st_mtime_ns
    except OSError:
        return None
    return _notifications_at(str(f), stamp).get(act_id or "")


def _from_notification(n: dict, out: dict) -> dict:
    """Fill a validity() result from a notification. Never says more than the notification: the source is always named, the date is UNVERIFIED until a named person has reviewed it, a date
    that was worked out from a stated interval is marked as computed, and a provision that starts on another date is kept as a note, not split out."""
    stages = [dict(s) for s in n["stages"] if s.get("from")]
    if not stages:
        return out
    stages.sort(key=lambda s: s["from"])
    reviewed = f"reviewed by {n['reviewed_by']} on {n['reviewed_on']}" if n.get("reviewed_by") and n.get("reviewed_on") else "NOT reviewed by a named person yet (UNVERIFIED)"
    out["source"] = f"{n['issuing_body']}, {n['number']} dated {n['notified_on']} ({n['gazette']}); file {n['file']}, page {n['page']}; {reviewed}"
    out["verified"] = bool(n.get("reviewed_by") and n.get("reviewed_on"))
    if out["verified"]:
        out["reviewed_by"], out["reviewed_on"] = n["reviewed_by"], n["reviewed_on"]
    out["stages"] = stages
    out["from"] = date.fromisoformat(stages[0]["from"])
    out["note"] = n["quote"]
    if len(stages) == 1:
        out["basis"] = "NOTIFICATION_DATE"
        if stages[0]["provisions"] not in ("all provisions", "whole Act"):
            out["except_note"] = f"The notification brings in {stages[0]['provisions']}."
    else:
        out["basis"] = "STAGED"
    return out


def validity(commencement: str, legal_currency: str = "", act_id: str | None = None) -> dict:
    """{"from": date|None, "to": date|None, "note": str}. "to" is set only when the text says the law was repealed or ceased, and gives the date it took effect.
    Order of evidence: a date written in the manifest; else a Gazette notification supplied by the owner (it is the actual date the Act's own section 1 says the Government will set); else the Act's
    own section 1 (sidecar); else nothing (unknown)."""
    text = (commencement or "").strip()
    out: dict = {"from": None, "to": None, "note": text, "basis": None, "after_year": None}
    if not text or text.lower().startswith("not stated"):
        notified = notification_for(act_id)
        if notified:
            return _from_notification(notified, out)
        own = _sidecar().get(act_id or "")
        if own:  # the manifest gives no date, so look at what the Act itself says about when it starts
            out["basis"] = own["basis"]
            if own["basis"] == "EXPLICIT_DATE" and own.get("date"):
                out["from"] = date.fromisoformat(own["date"])
            elif own["basis"] == "AT_ONCE" and own.get("year"):
                out["after_year"] = own["year"]
        return out
    ds = dates_in(text)
    if not ds:
        return out
    if END_WORDS.search(text) and not text.lower().startswith("in force"):
        out["to"] = ds[0][1]  # "REPEALED by BNS (Act 45 of 2023) w.e.f. 01-07-2024": "45 of 2023" is an Act number, not a date, so the first date written is the repeal date
    else:
        out["from"] = ds[0][1]
    return out


def status_on(v: dict, on: date) -> str:
    """IN_FORCE | NOT_YET_IN_FORCE | REPEALED | UNKNOWN for a validity() result on a date."""
    if v["to"] and on >= v["to"]:
        return "REPEALED"
    if v.get("after_year") and not v["from"]:  # "comes into force at once": on enactment, in the year of the Act, so any date in a later year is after it and any earlier year is before it
        return "IN_FORCE" if on.year > v["after_year"] else ("NOT_YET_IN_FORCE" if on.year < v["after_year"] else "UNKNOWN")
    if v["from"] and len(v.get("stages") or []) > 1:  # an Act that starts in stages: before the first stage nothing, after the last everything, in between only part of it
        first, last, d = v["stages"][0]["from"], v["stages"][-1]["from"], on.isoformat()
        return "NOT_YET_IN_FORCE" if d < first else ("IN_FORCE" if d >= last else "PART_IN_FORCE")
    if v["from"]:
        return "NOT_YET_IN_FORCE" if on < v["from"] else ("IN_FORCE" if not v["to"] or on < v["to"] else "REPEALED")
    if v["to"]:
        return "UNKNOWN"  # repealed from a date, but when it started is not stated: before the repeal it was probably in force, but that is a guess, so we do not say it
    return "UNKNOWN"


BASIS_NOTES = {
    "NOTIFICATION": "The Act says it starts on a date the Government sets by notification. That notification is not in the manifest, so the start date is not known here.",
    "PARTIAL": "The Act starts different sections at different times, so there is no single start date for the whole Act.",
    "NO_CLAUSE": "No commencement clause was found in the text held here (Rules usually take effect when published in the Gazette), so the start date is not known here.",
    "AT_ONCE": "The Act says it came into force on enactment (in the year of the Act); the exact day is not in the text.",
}

NOTES = {
    "IN_FORCE": "In force on that date, according to the dates in the official manifest.",
    "NOT_YET_IN_FORCE": "Not yet in force on that date, according to the dates in the official manifest. The law that applied then may be an earlier Act.",
    "PART_IN_FORCE": "Only part of this Act was in force on that date: it starts in stages (listed with the Act). Which provisions applied depends on the stage each belongs to.",
    "REPEALED": "Already repealed on that date, according to the dates in the official manifest.",
    "UNKNOWN": "The manifest does not give the dates needed to say whether this was in force on that date. Check the official source.",
}


def question_dates(text: str) -> list[date]:
    """Dates a person wrote in a question or a matter's facts: these are the dates the law must be checked against."""
    today = date.today()
    return [d for _, d in dates_in(text or "") if 1800 <= d.year <= today.year]
