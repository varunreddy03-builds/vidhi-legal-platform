"""Amendment history ("time travel"): what a provision said at each loaded version, and what the loaded versions say about a given day.

Only loaded versions with RECORDED effective dates (and the evidence for them) can answer "as on" a date. This module never infers when anything came into force, never
decides that a provision was inserted or omitted, and never fills a gap: it reports exactly what is loaded and says so when the loaded versions cannot answer.

States of `as_on` (all of them are about the loaded versions, not about the law):
  FOUND_IN_VERSION        exactly one loaded version is recorded as effective on that day, and it contains the provision
  NOT_IN_THAT_VERSION     exactly one loaded version covers the day but it has no such provision (not yet inserted, or omitted: read the amending text)
  NO_VERSION_COVERS_DATE  no loaded version has a recorded period covering the day (before the first one, after the last, or in a gap)
  AMBIGUOUS               more than one loaded version is recorded as effective on that day
  UNDATED_VERSIONS        some loaded versions have no recorded dates, so no one can be picked"""

from lib.db import db
from lib.legal_search import UNREVIEWED, hint_matches, view

NOTE = "This is what the loaded versions say, using the effective dates recorded for them. It is not a statement of what the law was on that day: read the amending text and have a lawyer check."


def _key(entry: dict):
    v = entry["version"]
    return (v.get("effective_from") is None, v.get("effective_from") or "", str(v.get("created_at") or ""))


def build_timeline(rows: list[dict]) -> dict:
    """rows: [{"version": {...}, "provision": {...}}]. Ordered by recorded effective date; undated versions follow in load order."""
    ordered = sorted(rows, key=_key)
    entries, warnings = [], []
    prev = None
    for r in ordered:
        v, p = r["version"], r["provision"]
        change = "first_recorded" if prev is None else ("unchanged" if prev["provision"].get("content_sha256") == p.get("content_sha256") else "changed")
        entries.append({"version_id": v["id"], "label": v["label"], "effective_from": v.get("effective_from"), "effective_to": v.get("effective_to"), "evidence": v.get("evidence", ""),
                        "provision_id": p["id"], "review_status": p.get("review_status", "unreviewed"), "content_sha256": p.get("content_sha256"), "change": change})
        if not v.get("effective_from"):
            warnings.append(f"Version \"{v['label']}\" has no recorded effective date, so it cannot be placed in time.")
        if prev is not None:
            pv = prev["version"]
            if pv.get("effective_to") and v.get("effective_from") and pv["effective_to"] < v["effective_from"]:
                warnings.append(f"Between {pv['effective_to']} and {v['effective_from']} no loaded version covers this provision.")
            if v.get("effective_from") and (not pv.get("effective_to") or v["effective_from"] < pv["effective_to"]) and pv.get("effective_from"):
                warnings.append(f"Versions \"{pv['label']}\" and \"{v['label']}\" are recorded as effective at the same time from {v['effective_from']}.")
        prev = r
    return {"entries": entries, "warnings": warnings}


def state_on(day: str, versions: list[dict], present: dict) -> dict:
    """versions: every loaded version of the instrument. present: {version_id: provision or None}."""
    if any(not v.get("effective_from") for v in versions):
        undated = True
    else:
        undated = False
    covering = [v for v in versions if v.get("effective_from") and v["effective_from"] <= day and (not v.get("effective_to") or day < v["effective_to"])]
    if len(covering) > 1:
        return {"state": "AMBIGUOUS", "day": day, "message": f"More than one loaded version is recorded as effective on {day}. None was chosen.", "version_ids": [v["id"] for v in covering], "note": NOTE}
    if not covering:
        why = "Some loaded versions have no recorded dates, so none can be picked. " if undated else ""
        return {"state": "UNDATED_VERSIONS" if undated else "NO_VERSION_COVERS_DATE", "day": day,
                "message": why + f"No loaded version has a recorded period covering {day}.", "version_ids": [], "note": NOTE}
    v = covering[0]
    p = present.get(v["id"])
    if p is None:
        return {"state": "NOT_IN_THAT_VERSION", "day": day, "version_id": v["id"], "version_label": v["label"],
                "message": f"The loaded version \"{v['label']}\", recorded as effective on {day}, has no such provision. It may not have been inserted yet or may have been omitted: read the amending text.", "note": NOTE}
    return {"state": "FOUND_IN_VERSION", "day": day, "version_id": v["id"], "version_label": v["label"], "provision_id": p["id"], "note": NOTE}


async def history(number: str, hint: str | None = None, on_date: str | None = None) -> list[dict]:
    """For every matching instrument that has this provision number in at least one loaded version: the timeline and, with a date, the state on that day."""
    out = []
    async for inst in db.instruments.find({}):
        if not hint_matches(hint, inst):
            continue
        versions = await db.instrument_versions.find({"instrument_id": inst["id"]}).sort("created_at", 1).to_list(200)
        present, rows = {}, []
        for v in versions:
            p = await db.provisions.find_one({"instrument_version_id": v["id"], "number_norm": number.upper()})
            present[v["id"]] = p
            if p:
                rows.append({"version": v, "provision": p})
        if not rows:
            continue
        tl = build_timeline(rows)
        item = {"instrument": inst["title"], "instrument_id": inst["id"], "number": number.upper(), "timeline": tl["entries"], "warnings": tl["warnings"], "versions_loaded": len(versions), "review_notice": UNREVIEWED}
        if on_date:
            st = state_on(on_date, versions, present)
            if st["state"] == "FOUND_IN_VERSION":
                st["provision"] = await view(present[st["version_id"]], inst, next(v for v in versions if v["id"] == st["version_id"]))
            item["as_on"] = st
        out.append(item)
    return out
