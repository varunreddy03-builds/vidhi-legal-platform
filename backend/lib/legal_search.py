"""Finding provisions: exact citations first, full-text second, always returning the COMPLETE provision (rule, provisos, explanations, illustrations, exceptions).

* "Section 3A of the Fictional Penal Act", "s. 3 FPA", "420 IPC" are parsed into a number and an instrument hint; the lookup is by structured fields, so an exact
  citation is found whatever any other search does.
* Full-text search uses MongoDB's text index over headings and provision text. No embeddings, no model, nothing that can change what the law says.
* A version is chosen by date ONLY from versions whose effective dates are recorded with evidence. If the date is unknown or not covered, every version is returned
  with a plain note and nothing is picked for the user.
* Every result states its review status. This module never says "verified"."""

import re
import unicodedata

from lib import embeddings, legal_structure, territories
from lib.db import db
from lib.legal_store import norm, use_blocked

# "section" in the languages people write citations in; the number may be in any script's digits (converted by ascii_digits). The Act name must still match a registered title or short name.
SECTION_WORDS = "|".join(["sections?", r"sec\.?", r"s\.", "articles?", r"art\.?", "अनुच्छेद", "ఆర్టికల్", "धारा", "सेक्शन", "సెక్షన్", "பிரிவு", "ধারা", "કલમ", "कलम", "ਧਾਰਾ", "ଧାରା", "വകുപ്പ്", "ಕಲಂ", "ಸೆಕ್ಷನ್", "دفعہ", "ধাৰা"])
CITE_LONG = re.compile(r"(?:(?<!\w)(?:" + SECTION_WORDS + r"))\s*(?P<num>\d{1,4}[A-Za-z]{0,3})(?:\s*\([^)]{1,6}\))*(?:\s+(?:of\s+)?(?:the\s+)?(?P<hint>[^;:?!\n]{2,80}?))?(?=[;:?!]|$|\n|\s+(?:and|or)\s+\d)", re.I)
CITE_SHORT = re.compile(r"\b(?P<num>\d{1,4}[A-Za-z]{0,3})\s+(?P<hint>[A-Z][A-Za-z]{1,7})\b")
STOP = {"the", "of", "and", "in", "on"}
UNREVIEWED_STATUS = "UNVERIFIED - pending lawyer review"
UNREVIEWED = "Unreviewed: loaded from an official source and not yet compared with it by a lawyer. Do not rely on it as verified law."


def ascii_digits(text: str) -> str:
    """Devanagari, Telugu, Tamil, Bengali... digits to 0-9, so "धारा ३" and "సెక్షన్ ౩" read as section 3. Everything else is left as typed."""
    return "".join(str(unicodedata.digit(ch)) if ch.isdigit() and not ch.isascii() and unicodedata.digit(ch, None) is not None else ch for ch in text)


def parse_citations(q: str) -> list[dict]:
    q = ascii_digits(q or "")
    found: list[dict] = []
    for m in CITE_LONG.finditer(q or ""):
        hint = (m.group("hint") or "").strip(" .,;")
        found.append({"number": m.group("num").upper(), "hint": hint or None})
    if not found:
        for m in CITE_SHORT.finditer(q or ""):
            found.append({"number": m.group("num").upper(), "hint": m.group("hint")})
    seen, out = set(), []
    for c in found:
        k = (c["number"], norm(c["hint"] or ""))
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def hint_matches(hint: str | None, instrument: dict) -> bool:
    if not hint:
        return True
    h = norm(hint)
    if not h:
        return True
    if any(h == norm(s) for s in instrument.get("short_names", [])):
        return True
    title_norm = norm(instrument["title"])
    if re.search(rf"(?<!\w){re.escape(title_norm)}(?!\w)", h):  # the whole title appears in what was typed ("...Fictional Penal Act 1901 say?")
        return True
    title = set(title_norm.split())
    tokens = [t for t in h.split() if t not in STOP]
    return bool(tokens) and all(t in title for t in tokens)


def _version_note(v: dict) -> str:
    if v.get("effective_from") or v.get("effective_to"):
        return f"effective {v.get('effective_from') or 'date not recorded'}" + (f" to {v['effective_to']}" if v.get("effective_to") else "") + f" (evidence: {v.get('evidence', '')})"
    return "effective dates not recorded"


async def view(p: dict, instrument: dict | None = None, version: dict | None = None) -> dict:
    instrument = instrument or await db.instruments.find_one({"id": p["instrument_id"]})
    version = version or await db.instrument_versions.find_one({"id": p["instrument_version_id"]})
    doc = await db.legal_documents.find_one({"id": version["document_id"]}, {"pages": 0}) or {}
    source = await db.legal_sources.find_one({"id": doc.get("source_id")}) or {}
    parent = legal_structure.render_parent(p)
    reviewed = p.get("review_status") == "reviewed"
    return {
        "id": p["id"], "number": p["number"], "heading": p.get("heading", ""), "kind": p["kind"], "unit": "Article" if instrument.get("kind") == "constitution" else "Section", "instrument": instrument["title"], "instrument_id": instrument["id"], "jurisdiction": instrument["jurisdiction"],
        "version": {"id": version["id"], "label": version["label"], "note": _version_note(version), "effective_from": version.get("effective_from"), "effective_to": version.get("effective_to")},
        "path": parent["path"], "page_start": p.get("page_start"), "components": parent["components"], "limits": parent["limits"], "complete": parent["complete"], "text": p["text_full"],
        "review": {"status": p.get("review_status", "unreviewed"), "label": "REVIEWED" if reviewed else ("REJECTED" if p.get("review_status") == "rejected" else "DRAFT"),
                   "reviewed_by": p.get("reviewed_by"), "reviewed_on": p.get("reviewed_on"), "second_source": p.get("second_source"),
                   "statement": (f"Compared with the official text by {p.get('reviewed_by')} on {p.get('reviewed_on')}." if reviewed else UNREVIEWED)},
        "reading": {"machine_read": bool(p.get("machine_read")), "uncertain_page": bool(p.get("page_uncertain")),
                    "warning": ("Read from a scan by a machine; wording may contain errors." + (" This page was read with low confidence or unreadable words." if p.get("page_uncertain") else "")) if p.get("machine_read") else None},
        "source": {"name": source.get("name"), "document": doc.get("title"), "url": doc.get("file_url") or doc.get("source_page_url") or None, "sha256": doc.get("sha256"), "retrieved_on": doc.get("retrieved_on")},
        "blocked": use_blocked(source) is not None,  # the source needs a permission that is not recorded: unified search leaves it out
    }


async def lookup(number: str, hint: str | None = None, on_date: str | None = None, territory: str | None = None) -> list[dict]:
    """Every instrument matching the hint that has this provision number, with its versions. One entry per instrument."""
    results = []
    async for inst in db.instruments.find({}):
        if not hint_matches(hint, inst) or not territories.applies_in(inst.get("jurisdiction"), territory):  # a law of another State is not shown as the law here
            continue
        versions = await db.instrument_versions.find({"instrument_id": inst["id"]}).sort("created_at", 1).to_list(100)
        rows = []
        for v in versions:
            p = await db.provisions.find_one({"instrument_version_id": v["id"], "number_norm": number.upper()})
            if p:
                rows.append((v, p))
        if not rows:
            continue
        selected, note = None, None
        if on_date:
            covering = [(v, p) for v, p in rows if v.get("effective_from") and v["effective_from"] <= on_date and (not v.get("effective_to") or on_date < v["effective_to"])]
            if len(covering) == 1:
                selected = covering[0]
            elif not covering:
                note = f"No loaded version has a recorded effective period covering {on_date}. All loaded versions are shown; none was chosen for you."
            else:
                note = f"More than one loaded version is recorded as effective on {on_date}. All are shown; none was chosen for you."
        elif len(rows) > 1:
            note = "More than one version is loaded. No date was given, so none was chosen; read each version's effective-date note."
        shown = [selected] if selected else rows
        results.append({"instrument": inst["title"], "instrument_id": inst["id"], "version_note": note, "provisions": [await view(p, inst, v) for v, p in shown]})
    return results


async def search(q: str, limit: int = 10, on_date: str | None = None, territory: str | None = None) -> dict:
    q = (q or "").strip()[:300]
    out: dict = {"query": q, "exact": [], "text": [], "review_notice": UNREVIEWED}
    seen: set[str] = set()
    for c in parse_citations(q):
        for entry in await lookup(c["number"], c["hint"], on_date, territory):
            out["exact"].append(entry)
            seen.update(p["id"] for p in entry["provisions"])
    if q:
        cursor = db.provisions.find({"$text": {"$search": q}}, {"score": {"$meta": "textScore"}}).sort([("score", {"$meta": "textScore"})]).limit(limit)
        async for p in cursor:
            if p["id"] not in seen:
                v = await view(p)
                if territories.applies_in(v.get("jurisdiction"), territory):
                    out["text"].append(v)
        semantic = [i for i in await embeddings.semantic_provision_ids(q) if i not in seen]  # [] unless meaning-based search is switched on, set up and current (lib/embeddings.py)
        if semantic:
            have = {v["id"]: v for v in out["text"]}
            order, found_by = embeddings.fuse(list(have), semantic, limit)
            missing = [i for i in order if i not in have]
            if missing:
                async for p in db.provisions.find({"id": {"$in": missing}}):
                    v = await view(p)
                    if territories.applies_in(v.get("jurisdiction"), territory):
                        have[p["id"]] = v
            reranked = await embeddings.rerank(q, [(i, f"{have[i]['instrument']} section {have[i]['number']}: {have[i].get('heading') or ''}. {have[i]['text']}") for i in order if i in have])
            if reranked is not None and set(reranked) == {i for i in order if i in have}:  # only a re-ordering is ever accepted
                order = reranked
                out["reranked"] = True
            out["text"] = [{**have[i], "found_by": found_by[i]} for i in order if i in have]  # how each was found: keyword, meaning or both; absent when meaning-based search is off
            out["meaning_search"] = "used"
    if territory:
        out["territory"] = territory
        out["territory_note"] = f"Only central law and law recorded for {territories.name_of(territory)} is shown. This does not mean other law is irrelevant: coverage of State and Union Territory sources is not yet verified."
    return out


def panel_item(v: dict, excerpt: int = 600, version_note: str | None = None, instrument: dict | None = None) -> dict:
    """A structured provision in the shape the "possibly relevant law" panel already shows for a draft. Unreviewed only: this never says verified."""
    text = v.get("text", "")
    ver = v.get("version", {})
    return {
        "id": v["id"], "citation": f"{v['unit']} {v['number']}, {v['instrument']}", "heading": v.get("heading", ""), "act_id": v.get("instrument_id", ""), "act_title": v["instrument"],
        "excerpt": text[:excerpt], "text_length": len(text), "source_name": (v.get("source") or {}).get("name") or "", "source_url": (v.get("source") or {}).get("url") or "",
        "version": ver.get("note", ""), "historical": False, "commencement": (instrument or {}).get("commencement_text", ""), "legal_currency": (instrument or {}).get("legal_currency_text", ""),
        "in_force_from": (instrument or {}).get("act_in_force_from"), "in_force_until": (instrument or {}).get("act_in_force_until"), "in_force_after_year": (instrument or {}).get("act_in_force_after_year"),
        "commencement_basis": (instrument or {}).get("act_commencement_basis"), "commencement_source": (instrument or {}).get("act_commencement_source", ""), "in_force_stages": (instrument or {}).get("act_in_force_stages"), "commencement_except": (instrument or {}).get("act_commencement_except", ""), "commencement_reviewed": bool((instrument or {}).get("act_commencement_reviewed")), "date_note": version_note or "", "structured": True, "complete": v.get("complete", True), "components": [c["kind"] for c in v.get("components", [])],
        "status": UNREVIEWED_STATUS, "note": v["review"]["statement"], "blocked": bool(v.get("blocked")),
    }


async def panel_items(q: str, limit: int = 5, on_date: str | None = None, territory: str | None = None) -> list[dict]:
    """The loaded provisions that look relevant to a question: exact citations first, then full text. Whole provisions (rule, provisos, explanations, exceptions), picked by date only
    from recorded effective dates. Only UNREVIEWED provisions are returned here: a reviewed one reaches an answer through the verified library, and a rejected one is never shown."""
    found = await search(q, limit=limit, on_date=on_date, territory=territory)
    out, seen, instruments = [], set(), {}

    async def inst(v: dict) -> dict:
        if v.get("instrument_id") not in instruments:
            instruments[v.get("instrument_id")] = await db.instruments.find_one({"id": v.get("instrument_id")}, {"_id": 0}) or {}
        return instruments[v.get("instrument_id")]

    for entry in found["exact"]:
        for v in entry["provisions"]:
            if v["id"] not in seen and v["review"]["status"] == "unreviewed":
                seen.add(v["id"])
                out.append(panel_item(v, version_note=entry.get("version_note"), instrument=await inst(v)))
    for v in found["text"]:
        if v["id"] not in seen and v["review"]["status"] == "unreviewed":
            seen.add(v["id"])
            out.append(panel_item(v, instrument=await inst(v)))
    return out[:limit]


async def provision_view(provision_id: str) -> dict | None:
    p = await db.provisions.find_one({"id": provision_id})
    return await view(p) if p else None
