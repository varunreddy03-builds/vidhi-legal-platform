"""One search across everything VIDHI holds about the law, with every result labelled by where it comes from and whether anyone has reviewed it.

Three stores, never mixed up:
  verified_library  library_entries: text a named person compared with the official source. The ONLY store whose results say VERIFIED.
  structured        instruments, versions and provisions (whole provisions: rule, provisos, explanations). Always "UNVERIFIED - not reviewed" until a named reviewer signs a provision.
  draft             law text cut from official PDFs by a program (legal_source_candidates). Always "UNVERIFIED - not reviewed". Returns nothing for a source whose terms need a permission that
                    is not recorded (lib/library.py decides that when the drafts are loaded).
Mapping cards (old code to new code) are a fourth kind of result, labelled the same way.

A date check comes only from dates recorded in the Act's own text (lib/law_dates.py); when none is recorded the answer is "unknown", and nothing is guessed.
This module never calls an AI model and never changes what a result says about review."""

import re
from datetime import date

from lib import code_mappings, law_dates, legal_search, library
from lib.db import db

VERIFIED = "VERIFIED"
UNVERIFIED = "UNVERIFIED - not reviewed"
STORES = ("verified_library", "structured", "draft", "mapping")
EXCERPT = 600


def _short(act_id: str) -> str:
    """"ncrb-bns" -> "bns", "crpc" -> "crpc": the short name a draft's Act is known by."""
    return re.sub(r"^ncrb-", "", str(act_id or "")).lower()


def _question_day(q: str, on_date: str | None) -> tuple[date | None, str]:
    """The date to check against: the one given, or the single date the question names. Several dates: none is chosen."""
    if on_date:
        try:
            return date.fromisoformat(on_date), ""
        except ValueError:
            return None, "The date was not understood (use YYYY-MM-DD), so no date check was made."
    days = law_dates.question_dates(q)
    if len(days) == 1:
        return days[0], ""
    if len(days) > 1:
        return None, "The question names more than one date, so no date check was made. Give one date to check."
    return None, ""


def _verified_item(e: dict) -> dict:
    return {
        "store": "verified_library", "id": e["id"], "citation": e["citation"], "heading": e.get("title", ""), "excerpt": (e.get("text") or "")[:EXCERPT], "text_length": len(e.get("text") or ""),
        "status": VERIFIED, "verified": True, "note": f"Compared with the official source by {e.get('verified_by')} on {e.get('verified_on')}.",
        "source_name": e.get("source_name", ""), "source_url": e.get("source_url", ""), "version": e.get("version", ""), "commencement": "", "legal_currency": "", "historical": False,
        "verified_by": e.get("verified_by"), "verified_on": e.get("verified_on"), "date_check": None, "also_in_drafts": False, "open": {"kind": "verified", "id": e["id"]},
    }


def _unverified_item(store: str, d: dict) -> dict:
    """A structured provision (legal_search.panel_item) or a draft (library.draft_view), in one shape. Never verified."""
    return {
        "store": store, "id": d["id"], "citation": d["citation"], "heading": d.get("heading", ""), "excerpt": d.get("excerpt", ""), "text_length": d.get("text_length", 0),
        "status": UNVERIFIED, "verified": False, "note": d.get("note", ""), "source_name": d.get("source_name", ""), "source_url": d.get("source_url", ""), "version": d.get("version", ""),
        "commencement": d.get("commencement", ""), "legal_currency": d.get("legal_currency", ""), "historical": bool(d.get("historical")),
        "reading": "machine-read" if (d.get("text_source") == "OCR" or d.get("machine_read")) else "",
        "coverage_note": d.get("coverage_note", ""), "in_force_from": d.get("in_force_from"), "in_force_until": d.get("in_force_until"), "in_force_after_year": d.get("in_force_after_year"),
        "commencement_basis": d.get("commencement_basis"), "commencement_source": d.get("commencement_source", ""), "in_force_stages": d.get("in_force_stages"), "commencement_except": d.get("commencement_except", ""),
        "date_check": None, "also_in_drafts": False, "open": {"kind": "draft", "id": d["id"]},
    }


def _with_date(items: list[dict], day: date) -> None:
    for it, checked in zip(items, library.with_date_check([dict(i) for i in items], day)):
        if it["store"] != "verified_library":
            it["date_check"] = {"on": checked["checked_on"], "state": checked["in_force_on_date"], "note": checked["date_note"]}


async def _structured_twin(d: dict) -> dict | None:
    """The structured provision that holds the same section as a draft (the drafts of an Act that was imported), or None."""
    m = re.match(r"\s*Section\s+(\S+?),", d.get("citation", ""))
    if not m:
        return None
    short = _short(d.get("act_id", ""))
    async for inst in db.instruments.find({}, {"_id": 0}):
        if short in [str(s).lower() for s in inst.get("short_names", [])]:
            p = await db.provisions.find_one({"instrument_id": inst["id"], "number_norm": m.group(1).upper()})
            if p:
                return await legal_search.view(p, inst)
    return None


async def _mapping_cards(q: str, limit: int) -> list[dict]:
    out: list[dict] = []
    for c in legal_search.parse_citations(q)[:3]:
        res = await code_mappings.lookup(c["number"], c["hint"])
        for m in res["mappings"][:limit]:
            side = {"older text": "the older provision", "newer text": "the newer provision"}.get(m.get("searched_from", ""), "this provision")
            legacy, new = ", ".join(r["citation"] for r in m["legacy"]), ", ".join(r["citation"] for r in m["new"]) or "no newer provision"
            out.append({
                "store": "mapping", "id": m["id"], "citation": f"{legacy} -> {new}", "heading": f"Old code to new code ({m['relationship']}; {m['equivalence_label']})", "excerpt": "",
                "text_length": 0, "status": VERIFIED if m["verified"] else UNVERIFIED, "verified": bool(m["verified"]),
                "note": (f"Mapping reviewed by {m.get('reviewed_by')}." if m["verified"] else "Unreviewed: taken from a published comparison table and not compared with its source by a named reviewer. It does not say which code applies.") + f" Found from {side}.",
                "source_name": "; ".join(m.get("authorities", [])), "source_url": "", "version": "", "commencement": "", "legal_currency": "", "historical": False, "date_check": None,
                "also_in_drafts": False, "open": None, "relationship": m["relationship"],
            })
    return out[:limit]


async def search(q: str, limit: int = 10, on_date: str | None = None, territory: str | None = None) -> dict:
    q = (q or "").strip()[:300]
    limit = max(1, min(int(limit), 25))
    day, date_problem = _question_day(q, on_date)
    notices = [date_problem] if date_problem else []
    out: dict = {"query": q, "checked_on": day.isoformat() if day else None, "results": [], "counts": dict.fromkeys(STORES, 0), "notices": notices, "legend": {
        VERIFIED: "A named person compared this text with the official source.", UNVERIFIED: "Not compared with the official source by any person. Use it to find the provision, then read the official text."}}
    if not q:
        return out
    seen: set[tuple[str, str]] = set()
    items: list[dict] = []

    def add(it: dict) -> None:
        key = (it["store"], it["id"])
        if key not in seen:
            seen.add(key)
            items.append(it)

    # 1. verified library: first, because it is the only store that can verify anything
    for e in await library.find_relevant(q, k=limit):
        add(_verified_item(e))
    # 2. structured store: exact citations, then full text; a provision whose source needs a permission that is not recorded is left out
    structured_ids: set[str] = set()
    for p in await legal_search.panel_items(q, limit=limit, on_date=day.isoformat() if day else None, territory=territory):
        if p.get("blocked"):
            continue
        structured_ids.add(p["id"])
        add(_unverified_item("structured", p))
    # 3. drafts: the same section already in the structured store is shown once, as the structured provision (and says it is also in the drafts)
    drafts = await library.search_drafts(q, k=limit)
    for d in drafts:
        twin = await _structured_twin(d)
        if twin and twin["review"]["status"] == "unreviewed":
            if twin["id"] in structured_ids:
                for it in items:
                    if it["id"] == twin["id"]:
                        it["also_in_drafts"] = True
                continue
            instrument = await db.instruments.find_one({"id": twin["instrument_id"]}, {"_id": 0}) or {}
            item = _unverified_item("structured", legal_search.panel_item(twin, instrument=instrument))
            item["also_in_drafts"] = True
            structured_ids.add(twin["id"])
            add(item)
        else:
            add(_unverified_item("draft", d))
    # 4. mapping cards for a section named in the question
    for card in await _mapping_cards(q, 5):
        add(card)
    if day:
        _with_date([i for i in items if i["store"] in ("structured", "draft")], day)
    rank = {"verified_library": 0, "structured": 1, "draft": 2, "mapping": 3}
    items.sort(key=lambda i: rank[i["store"]])  # stable: inside a store the store's own order (exact citation first, then best text match) is kept
    out["results"] = items[: limit * 2]
    for it in out["results"]:
        out["counts"][it["store"]] += 1
    if not await db.legal_source_candidates.estimated_document_count():
        out["notices"].append("Law drafts are switched off or not loaded, so none are searched. They return only when the source's permission is recorded.")
    if not out["counts"]["verified_library"]:
        out["notices"].append("Nothing in the verified library matches. Every result below is unreviewed.")
    return out
