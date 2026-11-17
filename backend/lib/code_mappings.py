"""Mappings between an older legal text and the text that replaced or restated it (IPC to BNS, CrPC to BNSS, Evidence Act to BSA, or any other pair).

What this module will NOT do: infer that two provisions correspond because their numbers match or their headings look alike, create a mapping on its own, or
substitute a newer provision into a historical case. Every mapping is entered by a person, linked to provisions that exist in the store (so the exact texts are
attached), starts `unreviewed`, and counts as a verified cross-reference only after a named reviewer is recorded and the linked texts still match their hashes.

Relationships: one-to-one, partial, split (one old provision, several new), merged (several old, one new), modified, absent (nothing corresponds), unresolved.
A lookup in either direction returns the mappings, the fixed transitional caveat, and the recorded commencement information; it never says which text applies."""

import uuid

from lib import legal_search
from lib import verified_store as store
from lib.db import db
from lib.legal_store import clean, iso, now
from lib.library import sha256_text

RELATIONSHIPS = ("one-to-one", "partial", "split", "merged", "modified", "absent", "unresolved")
# How close the correspondence is, as judged by the person who entered it (and, once reviewed, by the reviewer). Never inferred; the default is "uncertain".
EQUIVALENCES = ("exact", "partial", "related", "uncertain", "none")
EQUIVALENCE_NEEDS = {  # which structural relationships each claim of closeness is allowed with
    "exact": {"one-to-one"},
    "partial": {"partial", "split", "merged", "modified"},
    "related": {"partial", "split", "merged", "modified", "one-to-one"},
    "uncertain": set(RELATIONSHIPS) - {"absent"},
    "none": {"absent"},
}
CAVEAT = (
    "Which text applies to a particular matter depends on its facts, the dates involved (of the conduct, of any investigation, proceeding or trial), when each text came into force, "
    "and any transitional and saving provisions. VIDHI shows recorded cross-references only; it has not decided which text applies and does not replace the older provision with the newer one."
)
NO_MAPPING = "No verified mapping is recorded for this provision. That does not mean none exists; it means none has been entered and reviewed here."


async def _refs(ids: list[str]) -> list[dict]:
    refs = []
    for pid in ids:
        p = await db.provisions.find_one({"id": pid})
        if not p:
            raise ValueError(f"Unknown provision {pid}.")
        inst = await db.instruments.find_one({"id": p["instrument_id"]})
        refs.append({"provision_id": pid, "instrument": inst["title"], "instrument_id": inst["id"], "number": p["number"], "citation": f"{p['number']}, {inst['title']}", "text_sha256": p["content_sha256"], "text": p["text_full"]})
    return refs


async def create(d: dict, recorded_by: str) -> dict:
    rel = d["relationship"]
    if rel not in RELATIONSHIPS:
        raise ValueError(f"relationship must be one of {', '.join(RELATIONSHIPS)}.")
    eq = d.get("equivalence") or ("none" if rel == "absent" else "uncertain")
    if eq not in EQUIVALENCES:
        raise ValueError(f"equivalence must be one of {', '.join(EQUIVALENCES)}.")
    if rel not in EQUIVALENCE_NEEDS[eq]:
        raise ValueError(f"A mapping whose relationship is '{rel}' cannot be recorded as '{eq}': {eq} is only allowed with {', '.join(sorted(EQUIVALENCE_NEEDS[eq]))}.")
    if eq in ("exact", "partial", "related") and not [a for a in d.get("authorities", []) if a.strip()]:
        raise ValueError(f"A claim that two provisions are {eq} needs a supporting source (for example the official comparison table or a notification). Record it as 'uncertain' if there is none.")
    legacy_ids, new_ids = list(dict.fromkeys(d.get("legacy_provision_ids", []))), list(dict.fromkeys(d.get("new_provision_ids", [])))
    if not legacy_ids:
        raise ValueError("Name at least one older provision.")
    if rel == "absent" and new_ids:
        raise ValueError("A mapping marked 'absent' cannot name a newer provision.")
    if rel not in ("absent", "unresolved") and not new_ids:
        raise ValueError("Name the newer provision(s), or mark the relationship 'absent' or 'unresolved'.")
    if rel == "merged" and len(legacy_ids) < 2 or rel == "split" and len(new_ids) < 2:
        raise ValueError("'merged' needs two or more older provisions; 'split' needs two or more newer ones.")
    if rel == "one-to-one" and (len(legacy_ids) != 1 or len(new_ids) != 1):
        raise ValueError("'one-to-one' needs exactly one older and one newer provision.")
    legacy, new = await _refs(legacy_ids), await _refs(new_ids)
    if {r["instrument_id"] for r in legacy} & {r["instrument_id"] for r in new}:
        raise ValueError("The older and newer provisions must belong to different instruments.")
    diff = (d.get("differences_in_effect") or "").strip()
    if len(diff) < 10:
        raise ValueError("Describe the differences in legal effect (write 'none found on comparison' only if that is what the reviewer found).")
    commencement = d.get("commencement") or {}
    cdate = iso(commencement.get("date"), "commencement date")
    if cdate and len((commencement.get("evidence") or "").strip()) < 10:
        raise ValueError("A commencement date needs its evidence (for example the notification).")
    row = {
        "id": str(uuid.uuid4()), "relationship": rel, "equivalence": eq, "legacy": legacy, "new": new, "differences_in_effect": diff,
        "commencement": {"date": cdate, "evidence": (commencement.get("evidence") or "").strip() if cdate else ""},
        "transitional_and_saving": [{"note": n["note"].strip(), "provision_id": n.get("provision_id")} for n in d.get("transitional_and_saving", []) if n.get("note", "").strip()],
        "authorities": [a.strip() for a in d.get("authorities", []) if a.strip()], "verified_on": None, "reviewed_by": None, "review_status": "unreviewed", "recorded_by": recorded_by, "created_at": now(),
    }
    await store.create(db, "code_mappings", row)
    return clean(row)


def _numbers(value) -> list[str]:
    """"3, 4A" or ["3", "4A"] -> ["3", "4A"] (upper case, no repeats)."""
    items = value if isinstance(value, list) else str(value or "").replace(";", ",").split(",")
    return list(dict.fromkeys(str(i).strip().upper() for i in items if str(i).strip()))


async def _provision_ids(instrument_title: str, numbers: list[str]) -> tuple[list[str], list[str]]:
    """(ids, numbers that are not loaded). Where an instrument has several loaded versions, the newest one is used."""
    from lib.legal_store import norm

    inst = await db.instruments.find_one({"title_norm": norm(instrument_title)})
    if not inst:
        raise ValueError(f"No loaded instrument is titled \"{instrument_title}\".")
    ids, missing = [], []
    for n in numbers:
        p = await db.provisions.find({"instrument_id": inst["id"], "number_norm": n}).sort("created_at", -1).to_list(1)
        (ids if p else missing).append(p[0]["id"] if p else n)
    return ids, missing


async def import_rows(legacy_title: str, new_title: str, rows: list[dict], recorded_by: str) -> dict:
    """Load rows of an official comparison table as UNREVIEWED mappings, each through the same checks as a mapping entered by hand (create). Provisions are found by number in the two
    loaded instruments; a row naming a number that is not loaded fails and is reported, nothing is guessed. A row that repeats an existing mapping is skipped.
    Row fields: legacy (number or list), new (number or list, empty for absent), relationship, equivalence (optional), differences_in_effect, authority (the table and page it comes from),
    commencement_date and commencement_evidence (optional), transitional (optional note)."""
    created, skipped, failed = [], 0, []
    for i, r in enumerate(rows, 1):
        try:
            legacy_ids, miss_l = await _provision_ids(legacy_title, _numbers(r.get("legacy")))
            new_ids, miss_n = await _provision_ids(new_title, _numbers(r.get("new")))
            if miss_l or miss_n:
                raise ValueError("not loaded: " + ", ".join([f"{legacy_title} {m}" for m in miss_l] + [f"{new_title} {m}" for m in miss_n]))
            same = {"relationship": r.get("relationship"), "$expr": {"$and": [{"$eq": [{"$size": "$legacy"}, len(legacy_ids)]}, {"$eq": [{"$size": "$new"}, len(new_ids)]}]}}
            if legacy_ids:
                same["legacy.provision_id"] = {"$all": legacy_ids}
            if new_ids:  # ($all with an empty list matches nothing, so an "absent" row has no newer ids to compare)
                same["new.provision_id"] = {"$all": new_ids}
            if await db.code_mappings.find_one(same):
                skipped += 1
                continue
            m = await create({
                "relationship": r.get("relationship"), "equivalence": r.get("equivalence") or None, "legacy_provision_ids": legacy_ids, "new_provision_ids": new_ids,
                "differences_in_effect": r.get("differences_in_effect", ""), "authorities": [r["authority"]] if r.get("authority") else [],
                "commencement": {"date": r.get("commencement_date") or None, "evidence": r.get("commencement_evidence", "")},
                "transitional_and_saving": [{"note": r["transitional"]}] if r.get("transitional") else [],
            }, recorded_by)
            created.append(m["id"])
        except ValueError as exc:
            failed.append({"row": i, "error": str(exc)[:300]})
    return {"created": len(created), "skipped_as_already_recorded": skipped, "failed": failed, "ids": created, "status": "All created mappings are unreviewed: none counts as verified until a named reviewer is recorded."}


async def review(mapping_id: str, reviewer: str, on: str) -> dict:
    m = await db.code_mappings.find_one({"id": mapping_id})
    if not m:
        raise ValueError("Unknown mapping.")
    if len(reviewer.strip()) < 5:
        raise ValueError("Give the reviewer's full name.")
    day = iso(on, "verified_on")
    if not day:
        raise ValueError("Give the date of the review.")
    if m["relationship"] != "unresolved" and not [a for a in m.get("authorities", []) if a.strip()]:
        raise ValueError("A mapping can be marked reviewed only if it cites an official source (for example the official comparison table or a notification). Add the source first.")
    for ref in m["legacy"] + m["new"]:
        p = await db.provisions.find_one({"id": ref["provision_id"]})
        if not p or p["content_sha256"] != ref["text_sha256"] or sha256_text(p["text_full"]) != ref["text_sha256"]:
            raise ValueError("A linked provision has changed or is missing since this mapping was entered. Re-enter the mapping.")
    source = "; ".join(a.strip() for a in m.get("authorities", []) if a.strip()) or "none: recorded as unresolved because no official table gives a match"
    await store.record_review(db, "code_mappings", mapping_id, "reviewed", reviewer, day, source)
    return clean(await db.code_mappings.find_one({"id": mapping_id}))


def which_text(m: dict, event_day: str) -> dict:
    """Which of the two texts a mapping points to for an event on `event_day`, using ONLY the commencement date recorded on a REVIEWED mapping (with its evidence).
    Before that date: the older text. On or after it: the newer text. Anything else (draft mapping, no recorded date) is 'unknown': nothing is guessed. Transitional and saving notes are
    always returned with the answer, because they can change it, and a lawyer decides."""
    base = {"mapping_id": m["id"], "mapping_status": "REVIEWED" if m.get("review_status") == "reviewed" else "DRAFT", "event_day": event_day,
            "transitional_and_saving": [n["note"] for n in m.get("transitional_and_saving", [])], "caveat": CAVEAT + " A lawyer decides which text applies."}
    c = (m.get("commencement") or {}).get("date")
    if m.get("review_status") != "reviewed":
        return {**base, "applies": "unknown", "basis": "This mapping is a DRAFT: no named reviewer has compared it with its source, so it is not used to pick a text."}
    if not c:
        return {**base, "applies": "unknown", "basis": "No commencement date is recorded for this mapping, so the older or newer text cannot be picked by date."}
    side = "older" if event_day < c else "newer"
    return {**base, "applies": side, "basis": f"Recorded commencement date {c} (evidence: {m['commencement']['evidence']}). The event date {event_day} is {'before' if side == 'older' else 'on or after'} it.",
            "legacy": [r["citation"] for r in m["legacy"]], "new": [r["citation"] for r in m["new"]]}


async def disagreements() -> list[dict]:
    """Every older provision that two or more entered mappings treat differently (a different set of newer provisions, or a different relationship). Published tables are known to
    disagree, so this is shown to the reviewer instead of one being chosen."""
    rows = await db.code_mappings.find({}).sort("created_at", 1).to_list(5000)
    by_legacy: dict[str, list[dict]] = {}
    for m in rows:
        for r in m["legacy"]:
            by_legacy.setdefault(r["provision_id"], []).append(m)
    out = []
    for pid, ms in by_legacy.items():
        shapes = {(m["relationship"], tuple(sorted(r["provision_id"] for r in m["new"]))) for m in ms}
        if len(ms) > 1 and len(shapes) > 1:
            first = next(r for r in ms[0]["legacy"] if r["provision_id"] == pid)
            out.append({"legacy_provision_id": pid, "legacy": first["citation"], "message": "Entered mappings disagree about this provision. Read each source and decide which is right; none was chosen.",
                        "mappings": [{"id": m["id"], "relationship": m["relationship"], "new": [r["citation"] for r in m["new"]], "authorities": m["authorities"],
                                      "status": "REVIEWED" if m["review_status"] == "reviewed" else "DRAFT"} for m in ms]})
    return out


def present(m: dict) -> dict:
    out = {k: v for k, v in clean(m).items() if k not in ("legacy", "new")}
    out["legacy"] = [{k: v for k, v in r.items() if k != "text"} for r in m["legacy"]]
    out["new"] = [{k: v for k, v in r.items() if k != "text"} for r in m["new"]]
    out["verified"] = m["review_status"] == "reviewed"
    eq = m.get("equivalence", "uncertain")
    out["equivalence"] = eq
    out["equivalence_label"] = f"{'Reviewed' if out['verified'] else 'Unreviewed claim'}: {eq}"
    return out


def timing(m: dict, conduct_day: str) -> dict:
    """How the RECORDED commencement date of this mapping compares with the conduct date the person gave. Nothing is decided: a recorded date may be missing, wrong or subject to savings."""
    c = (m.get("commencement") or {}).get("date")
    if not c:
        return {"conduct_vs_commencement": "unknown", "timing_note": "No commencement date is recorded for this mapping, so VIDHI cannot say whether the newer text was in force on that date."}
    if conduct_day < c:
        return {"conduct_vs_commencement": "before", "timing_note": f"The date you gave ({conduct_day}) is BEFORE the recorded commencement ({c}). The newer text may not have been in force then; the older text may govern. A lawyer decides, including the effect of any savings provision."}
    return {"conduct_vs_commencement": "on_or_after", "timing_note": f"The date you gave ({conduct_day}) is on or after the recorded commencement ({c}). That alone does not decide which text applies: transitional and saving provisions may keep the older text in force. A lawyer decides."}


async def lookup(number: str, hint: str | None = None, offence_date: str | None = None) -> dict:
    """Mappings that involve the named provision, on either side, plus the caveat. Never picks a text for the user."""
    entries = await legal_search.lookup(number, hint)
    ids = [p["id"] for e in entries for p in e["provisions"]]
    rows = await db.code_mappings.find({"$or": [{"legacy.provision_id": {"$in": ids}}, {"new.provision_id": {"$in": ids}}]}).sort("created_at", 1).to_list(200) if ids else []
    maps = [present(m) for m in rows]
    for shown, raw in zip(maps, rows):
        in_old, in_new = any(r["provision_id"] in ids for r in raw["legacy"]), any(r["provision_id"] in ids for r in raw["new"])
        shown["searched_from"] = "older text" if in_old and not in_new else "newer text" if in_new and not in_old else "either"
    out = {
        "found": [{"instrument": e["instrument"], "provisions": e["provisions"], "version_note": e["version_note"]} for e in entries],
        "mappings": maps, "verified_mappings": [m for m in maps if m["verified"]], "caveat": CAVEAT, "auto_substitution": False,
        "disagreements": [d for d in await disagreements() if d["legacy_provision_id"] in ids or any(x["id"] in {m["id"] for m in maps} for x in d["mappings"])],
    }
    if not any(m["verified"] for m in maps):
        out["message"] = NO_MAPPING
    if offence_date:
        day = iso(offence_date, "offence_date")
        out["offence_date_note"] = (f"You gave {day} as the date of the conduct. Recorded commencement information is shown with each mapping; VIDHI has applied none of it. "
                                     "Which text applies is for a lawyer to decide.")
        for shown, raw in zip(maps, rows):
            shown.update(timing(raw, day))
        out["applies_on_event_date"] = [which_text(raw, day) for raw in rows]
    return out
