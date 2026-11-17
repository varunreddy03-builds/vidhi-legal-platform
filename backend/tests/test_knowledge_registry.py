"""The knowledge registry is a catalogue: it must list all 50 works, resolve repeats without double records, and never claim progress (located, rights checked, ingested) without evidence."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REG = json.loads((ROOT / "backend" / "data" / "knowledge" / "registry.json").read_text(encoding="utf-8"))
ENTRIES = REG["entries"]


def test_all_fifty_numbered_entries_are_present_once():
    assert [e["number"] for e in ENTRIES] == list(range(1, 51))
    assert len({e["id"] for e in ENTRIES}) == 50 and all(e["title"].strip() and e["authors"].strip() for e in ENTRIES)


def test_repeats_point_to_one_canonical_record():
    by = {e["number"]: e for e in ENTRIES}
    assert by[26]["canonical_of"] == 3 and by[35]["canonical_of"] == 2
    assert by[26]["collections"] == ["machiavelli"] and "dark_triad" in by[35]["collections"]
    assert sum(1 for e in ENTRIES if e["canonical_of"] is None) == 48
    assert by[10]["canonical_of"] is None and by[28]["canonical_of"] is None and by[10]["title"] == by[28]["title"]  # same title, different works: never merged


def test_collections_hold_the_listed_works():
    ids = lambda name: [e["number"] for e in ENTRIES if name in e["collections"]]  # noqa: E731
    assert ids("machiavelli") == [26, 27, 28, 29, 30] and ids("dark_triad") == [31, 32, 33, 34, 35]


@pytest.mark.parametrize("e", ENTRIES, ids=lambda e: str(e["number"]))
def test_no_entry_claims_progress_without_evidence(e):
    assert e["status"] in REG["statuses"] and e["rights_hint"] in REG["rights_hints"]
    if e["status"] != "Registered" or e["source_status"] != "not_located" or e["rights_status"] != "not_verified":
        assert e["evidence"].strip(), f"#{e['number']} claims progress with no evidence"
    for field in ("edition", "translator", "year"):
        assert e[field] is None or e["evidence"].strip(), f"#{e['number']} has a {field} nobody checked"



