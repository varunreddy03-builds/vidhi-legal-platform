"""The old-to-new table grouping works out a mapping's shape only from which section numbers the official table joins, and never claims more than the table says. Fictional rows."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import import_old_codes_and_mappings as imp  # noqa: E402

DATA = {
    "source": "https://example.test/table", "publisher": "A Fictional Bureau", "retrieved_on": "2026-01-01", "new_instrument": "New Code", "legacy_instrument": "Old Code",
    "legacy_to_new": [
        {"legacy": "1. Title.", "new": "1. Short title."},
        {"legacy": "2. Punishment.", "new": "7. Punishment. (Change)"},
        {"legacy": "3. Cheating.", "new": "9 (1)"},
        {"legacy": "4. Cheating more.", "new": "9 (2)"},
        {"legacy": "5. Gone.", "new": "Deleted"},
        {"legacy": "6. Split.", "new": "11."},
        {"legacy": "6. Split.", "new": "12."},
        {"legacy": "CHAPTER I", "new": "CHAPTER I"},
    ],
    "new_to_legacy": [{"new": "20. Brand new.", "legacy": "New Section"}, {"new": "1. Short title.", "legacy": "1. Title."}],
}


def shapes():
    comps, stats = imp.components(DATA)
    rows = imp.to_rows(comps, DATA)
    return {(tuple(r["legacy"]), tuple(r["new"])): r for r in rows}, stats


def test_the_shape_comes_only_from_the_numbers_the_table_joins():
    by, stats = shapes()
    assert by[(("1",), ("1",))]["relationship"] == "one-to-one"
    assert by[(("2",), ("7",))]["relationship"] == "modified"  # the table itself marked it "(Change)"
    assert by[(("3", "4"), ("9",))]["relationship"] == "merged"  # a sub-section reference (9 (1), 9 (2)) joins the whole section 9
    assert by[(("5",), ())]["relationship"] == "absent" and by[(("5",), ())]["equivalence"] == "none"
    assert by[(("6",), ("11", "12"))]["relationship"] == "split"
    assert stats["new_only_not_recordable"] == 1  # a "New Section" has no older section to attach to


def test_nothing_is_ever_called_exact_and_the_difference_is_not_claimed_to_be_analysed():
    by, _ = shapes()
    for r in by.values():
        assert r["equivalence"] in ("related", "none")
        assert r["differences_in_effect"].startswith("Not analysed here")
        assert "A Fictional Bureau" in r["authority"] and "https://example.test/table" in r["authority"]
