"""Loads the three repealed codes (IPC 1860, CrPC 1973, Indian Evidence Act 1872) as UNREVIEWED provisions, then loads the Home Ministry's old-to-new section tables
(data/mapping_tables/ncrb_*.json, saved as published by scripts/ncrb_tables_save.py) as UNREVIEWED mappings, through the same code as the admin routes.

Needs OLD_CODES_USE_REF and NCRB_PORTAL_USE_REF in backend/.env (who decided, and when). Nothing it loads is verified: a named reviewer must sign each provision and each mapping.
The structure of a mapping is worked out only from the table's own rows (which section numbers it joins), never from the content of the sections:
  * one older section joined to one newer section: "one-to-one", or "modified" where the table itself marks the row "(Change)";
  * one older to several newer: "split"; several older to one newer: "merged"; several on both sides: "partial";
  * an older section the table says is "Deleted": "absent".
A newer section that the table says is new ("New Section") has no older section to attach to and cannot be recorded; it is counted and reported.
Equivalence is recorded as "related" (never "exact") with the table as the authority, and the differences text says only that they were not analysed.

    python scripts/import_old_codes_and_mappings.py [--dry-run]
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import code_mappings, db, legal_store, library  # noqa: E402

TABLES = Path(__file__).resolve().parent.parent / "data" / "mapping_tables"
OLD_SOURCE = {
    "name": "India Code (Legislative Department): repealed codes supplied by the owner", "publisher": "Legislative Department, Ministry of Law and Justice (India Code)", "jurisdiction": "IN", "document_types": ["act"],
    "access_method": "manual-supplied", "licence_note": "India Code's terms need written permission for commercial reuse. The owner supplied the PDFs and decided on 2026-11-03 to use them as unverified drafts (OLD_CODES_USE_REF); a lawyer's view is still advised.",
    "terms_checked_on": "2026-10-26", "known_limits": "Historical text (repealed). The CrPC file is a scan read by a machine: only part of its sections were found.", "permission_required": True,
}
OLD_ACTS = [
    ("ipc", {"title": "The Indian Penal Code, 1860", "short_names": ["IPC"], "kind": "act", "year": 1860, "jurisdiction": "IN"}),
    ("crpc", {"title": "The Code of Criminal Procedure, 1973", "short_names": ["CrPC"], "kind": "act", "year": 1973, "jurisdiction": "IN"}),
    ("iea", {"title": "The Indian Evidence Act, 1872", "short_names": ["IEA", "Evidence Act"], "kind": "act", "year": 1872, "jurisdiction": "IN"}),
]
PAIRS = [("ncrb_bns.json", "The Bharatiya Nyaya Sanhita, 2023", "The Indian Penal Code, 1860"), ("ncrb_bnss.json", "The Bharatiya Nagarik Suraksha Sanhita, 2023", "The Code of Criminal Procedure, 1973"),
         ("ncrb_bsa.json", "The Bharatiya Sakshya Adhiniyam, 2023", "The Indian Evidence Act, 1872")]
NUM = re.compile(r"^\s*(\d+[A-Za-z]{0,3})(?![\dA-Za-z])")
CHANGE = re.compile(r"\(\s*change\s*\)", re.I)


def number(cell: str) -> str | None:
    m = NUM.match(cell or "")
    return m.group(1).upper() if m else None


def components(data: dict) -> tuple[list[dict], dict]:
    """Group the table's rows into sets of older and newer section numbers that the table joins."""
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    notes: dict[str, set] = {}
    changed: set[str] = set()
    deleted_legacy: set[str] = set()
    new_only: set[str] = set()
    skipped = 0
    pairs = [(r["legacy"], r["new"]) for r in data["legacy_to_new"]] + [(r["legacy"], r["new"]) for r in ({"legacy": x["legacy"], "new": x["new"]} for x in data["new_to_legacy"])]
    for leg, new in pairs:
        ln, nn = number(leg), number(new)
        if ln is None and nn is None:
            skipped += 1
            continue
        if ln and nn:
            union("L" + ln, "N" + nn)
            root = find("L" + ln)
            notes.setdefault(root, set()).add(f"{leg} <-> {new}")
            if CHANGE.search(leg) or CHANGE.search(new):
                changed.add("L" + ln)
        elif ln and not nn:
            if re.match(r"^\s*(deleted|omitted)", new or "", re.I):
                deleted_legacy.add(ln)
            else:
                skipped += 1
        elif nn and not ln:
            new_only.add(nn)
    groups: dict[str, dict] = {}
    for key in list(parent):
        groups.setdefault(find(key), {"L": set(), "N": set()})["L" if key[0] == "L" else "N"].add(key[1:])
    out = []
    for root, g in groups.items():
        out.append({"legacy": sorted(g["L"], key=_k), "new": sorted(g["N"], key=_k), "change": any("L" + x in changed for x in g["L"]), "table_rows": sorted(notes.get(find(root), set()))[:6]})
    linked_legacy = {x for g in groups.values() for x in g["L"]}
    for ln in sorted(deleted_legacy - linked_legacy, key=_k):
        out.append({"legacy": [ln], "new": [], "change": False, "table_rows": [f"{ln} <-> Deleted"]})
    return out, {"skipped_rows": skipped, "new_only_not_recordable": len(new_only - {x for g in groups.values() for x in g["N"]})}


def _k(n: str):
    m = re.match(r"(\d+)(.*)", n)
    return (int(m.group(1)), m.group(2)) if m else (10**9, n)


def to_rows(comps: list[dict], data: dict) -> list[dict]:
    url = data["source"]
    rows = []
    for c in comps:
        L, N = c["legacy"], c["new"]
        if not N:
            rel, eq = "absent", "none"
        elif len(L) == 1 and len(N) == 1:
            rel, eq = ("modified" if c["change"] else "one-to-one"), "related"
        elif len(L) == 1:
            rel, eq = "split", "related"
        elif len(N) == 1:
            rel, eq = "merged", "related"
        else:
            rel, eq = "partial", "related"
        diff = "Not analysed here. The official table joins these sections" + (" and itself marks the row as changed ('(Change)')" if c["change"] else "") + ". Table rows as published: " + " | ".join(c["table_rows"])
        rows.append({"legacy": L, "new": N, "relationship": rel, "equivalence": eq, "differences_in_effect": diff[:900],
                     "authority": f"{data['publisher']}, comparison table of {data['new_instrument']} with {data['legacy_instrument']}: {url} (retrieved {data['retrieved_on']})"})
    return rows


async def main(dry: bool) -> None:
    rows_by_pair = {}
    for fname, new_title, old_title in PAIRS:
        data = json.loads((TABLES / fname).read_text(encoding="utf-8"))
        comps, stats = components(data)
        rows_by_pair[fname] = (new_title, old_title, to_rows(comps, data), stats)
        kinds: dict[str, int] = {}
        for r in rows_by_pair[fname][2]:
            kinds[r["relationship"]] = kinds.get(r["relationship"], 0) + 1
        print(f"{fname}: {len(comps)} groups {kinds} | {stats}")
    if dry:
        return
    for k in ("OLD_CODES_USE_REF", "NCRB_PORTAL_USE_REF"):
        if len((os.environ.get(k) or "").strip()) < 10:
            sys.exit(f"{k} is not set in backend/.env: nothing was loaded.")
    print("writing to database:", os.environ["DB_NAME"], "(the dev app uses vidhi_dev: set DB_NAME=vidhi_dev, because backend/.env names a different database)")
    sync = await library.sync_library()
    print("drafts synced:", {k: v for k, v in sync.items() if not isinstance(v, (list, dict))})
    src = await db.db.legal_sources.find_one({"name": OLD_SOURCE["name"]}, {"_id": 0}) or await legal_store.register_source(dict(OLD_SOURCE))
    if not (src.get("permission_reference") or "").strip():
        src = await legal_store.record_permission(src["id"], os.environ["OLD_CODES_USE_REF"].strip(), "owner decision (import_old_codes_and_mappings.py)")
    for act_id, instrument in OLD_ACTS:
        try:
            out = await legal_store.ingest_drafts(act_id, src["id"], instrument, "other", evidence="India Code repealed-Acts PDF supplied by the owner (file hash matches the extracted drafts); historical text")
            print(act_id, {k: v for k, v in out.items() if k != "warnings"}, "| warnings:", len(out.get("warnings", [])))
        except ValueError as exc:
            print(act_id, "REFUSED:", str(exc)[:300])
    for fname, (new_title, old_title, rows, _stats) in rows_by_pair.items():
        out = await code_mappings.import_rows(old_title, new_title, rows, "owner decision (import_old_codes_and_mappings.py)")
        why: dict[str, int] = {}
        for f in out["failed"]:
            key = "not loaded: older section missing" if "not loaded" in f["error"] else f["error"][:80]
            why[key] = why.get(key, 0) + 1
        print(fname, {"created": out["created"], "skipped_as_already_recorded": out["skipped_as_already_recorded"], "failed": len(out["failed"]), "why": why})


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
