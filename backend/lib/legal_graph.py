"""Cross-references between provisions, found by code in the loaded text.

A provision often points elsewhere ("subject to section 12", "as defined in article 3", "the First Schedule", "section 5 of the Fictional Penal Act"). This module finds
those pointers with fixed patterns, stores each as an edge, and links it to the provision it names when that provision is loaded. Nothing here reads meaning:
an edge says "this text mentions that number", not that the two provisions are related in law. Edges the code could not resolve are kept and marked unresolved
(the target may simply not be loaded). All edges are `derived_by: code` and `unreviewed`."""

import re
import uuid
from datetime import datetime, timezone

from lib import verified_store as store
from lib.db import db
from lib.legal_search import hint_matches

NUM = r"\d{1,4}[A-Z]{0,3}(?:\([^)\s]{1,5}\))*"
LIST = rf"{NUM}(?:\s*(?:,|and|or|to)\s*{NUM})*"
PROVISION_REF = re.compile(
    rf"\b(?P<kind>sections?|articles?|rules?|regulations?)\s+(?P<nums>{LIST})"
    r"(?:\s+of\s+(?:the\s+)?(?P<hint>(?-i:(?:[A-Z][\w'’-]*\s+){0,6}(?:Act|Code|Constitution|Rules|Regulations|Sanhita|Adhiniyam)(?:,?\s*(?:of\s*)?\d{4})?)))?",
    re.I,
)
STRUCTURE_REF = re.compile(r"\b(?P<kind>Part|Chapter|Schedule)\s+(?P<label>[IVXLC]+|\d+[A-Z]?|First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|Eleventh|Twelfth)\b")
ORDINAL_SCHEDULE = re.compile(r"\b(?P<label>First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|Eleventh|Twelfth)\s+Schedule\b")
SPLIT = re.compile(r"\s*(?:,|\band\b|\bor\b|\bto\b)\s*", re.I)
BASE = re.compile(r"^(?P<n>\d{1,4}[A-Z]{0,3})(?P<sub>(?:\([^)\s]{1,5}\))*)$", re.I)


def now() -> datetime:
    return datetime.now(timezone.utc)


def extract_references(text: str, own_number: str | None = None) -> list[dict]:
    """Every pointer in the text, in order of appearance, duplicates removed. The provision's own number is skipped."""
    found, seen = [], set()
    for m in PROVISION_REF.finditer(text or ""):
        kind = m.group("kind").lower().rstrip("s")
        hint = (m.group("hint") or "").strip() or None
        if hint and hint.split()[0].lower() in ("this", "said"):  # "this Act" / "said Act" mean the same instrument
            hint = None
        for part in SPLIT.split(m.group("nums")):
            b = BASE.match(part.strip())
            if not b:
                continue
            number, sub = b.group("n").upper(), b.group("sub")
            if own_number and number == own_number.upper() and not hint:
                continue
            key = (kind, number, sub, hint)
            if key not in seen:
                seen.add(key)
                found.append({"kind": kind, "number": number, "sub": sub, "hint": hint, "raw": m.group(0).strip()})
    structural = [(m.start(), m.group("kind").lower(), m.group("label"), m.group(0).strip()) for m in STRUCTURE_REF.finditer(text or "")]
    structural += [(m.start(), "schedule", m.group("label"), m.group(0).strip()) for m in ORDINAL_SCHEDULE.finditer(text or "")]  # "the First Schedule": the ordinal comes first
    for _, kind, label, raw in sorted(structural):
        key = ("structure", kind, label, None)
        if key not in seen:
            seen.add(key)
            found.append({"kind": kind, "number": label, "sub": "", "hint": None, "raw": raw, "structural": True})
    return found


async def build_edges(version_id: str) -> dict:
    """(Re)build the edges for every provision of one loaded version. Safe to run again: the old edges of that version are replaced."""
    version = await db.instrument_versions.find_one({"id": version_id})
    if not version:
        raise ValueError("Unknown version.")
    await store.delete(db, "provision_refs", {"from_version_id": version_id})
    instruments = None
    edges = []
    async for p in db.provisions.find({"instrument_version_id": version_id}):
        for ref in extract_references(p["text_full"], p["number"]):
            to_ids: list[str] = []
            if not ref.get("structural"):
                if ref["hint"]:
                    if instruments is None:
                        instruments = await db.instruments.find({}).to_list(500)
                    for inst in instruments:
                        if hint_matches(ref["hint"], inst):
                            async for q in db.provisions.find({"instrument_id": inst["id"], "number_norm": ref["number"]}, {"id": 1}):
                                to_ids.append(q["id"])
                else:
                    async for q in db.provisions.find({"instrument_version_id": version_id, "number_norm": ref["number"]}, {"id": 1}):
                        to_ids.append(q["id"])
            edges.append({"id": str(uuid.uuid4()), "from_provision_id": p["id"], "from_version_id": version_id, "from_number": p["number"], "kind": ref["kind"], "to_number": ref["number"], "sub": ref["sub"],
                          "hint": ref["hint"], "raw": ref["raw"], "structural": bool(ref.get("structural")), "to_provision_ids": to_ids, "resolved": bool(to_ids), "derived_by": "code",
                          "review_status": "unreviewed", "created_at": now()})
    if edges:
        await store.create_many(db, "provision_refs", edges)
    return {"version_id": version_id, "edges": len(edges), "resolved": sum(1 for e in edges if e["resolved"]), "unresolved": sum(1 for e in edges if not e["resolved"] and not e["structural"])}


def _public(e: dict) -> dict:
    return {k: e[k] for k in ("id", "kind", "to_number", "sub", "hint", "raw", "structural", "resolved", "to_provision_ids", "from_provision_id", "from_number", "derived_by", "review_status")}


async def references(provision_id: str) -> dict | None:
    """What this provision points to, and which provisions point to it."""
    p = await db.provisions.find_one({"id": provision_id})
    if not p:
        return None
    out_edges = [_public(e) async for e in db.provision_refs.find({"from_provision_id": provision_id}).sort("created_at", 1)]
    in_edges = [_public(e) async for e in db.provision_refs.find({"to_provision_ids": provision_id}).sort("created_at", 1)]
    return {"provision_id": provision_id, "number": p["number"], "refers_to": out_edges, "referred_to_by": in_edges,
            "note": "Found by code from the wording. An edge means the text mentions that number; it does not say the provisions are related in law. Edges are not reviewed."}
