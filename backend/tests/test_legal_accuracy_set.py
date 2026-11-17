"""The legal-accuracy set is questions only, and no one can quote an accuracy figure from it until a qualified reviewer has filled in references."""

import pytest

from evals import legal_accuracy as la


def test_the_set_covers_every_required_category_with_unique_ids():
    entries = la.load()["entries"]
    assert {e["category"] for e in entries} == set(la.CATEGORIES)
    assert len({e["id"] for e in entries}) == len(entries)
    for e in entries:
        assert e["question"].strip().endswith(("?", ".")) and e["behaviour"] in la.BEHAVIOURS and e["premise"].strip(), e["id"]
    assert min(sum(1 for e in entries if e["category"] == c) for c in la.CATEGORIES) >= 2


def test_no_entry_states_a_legal_answer_before_it_has_been_reviewed():
    for e in la.load()["entries"]:
        ref = e.get("reference") or {}
        assert not ref.get("answer") or la.is_reviewed(e), f"{e['id']} has a reference answer without a named reviewer, sources and date"


def test_an_accuracy_figure_is_refused_while_nothing_is_reviewed():
    r = la.accuracy_report({"LA-01": 100.0, "LA-02": 90.0})
    assert r["status"] == "NOT MEASURABLE" and r["reviewed"] == 0 and "average" not in r


def test_only_reviewed_entries_count_and_the_report_says_how_few(monkeypatch):
    data = la.load()
    for e in data["entries"]:
        if e["id"] == "LA-01":
            e["reference"] = {"answer": "A reviewed reference answer.", "sources": ["official source page"], "reviewer": "Reviewing Advocate", "reviewed_on": "2026-11-01"}
        if e["id"] == "LA-02":
            e["reference"] = {"answer": "No reviewer yet.", "sources": [], "reviewer": "", "reviewed_on": None}
    monkeypatch.setattr(la, "load", lambda: data)
    r = la.accuracy_report({"LA-01": 80.0, "LA-02": 100.0, "LA-03": 100.0})
    assert r == {"status": "MEASURED", "reviewed": 1, "entries": 26, "average": 80.0, "note": "Covers only the reviewed entries; the rest are untested."}


@pytest.mark.parametrize("missing", ["answer", "sources", "reviewer", "reviewed_on"])
def test_a_reference_missing_any_part_is_not_reviewed(missing):
    ref = {"answer": "x", "sources": ["s"], "reviewer": "Name Surname", "reviewed_on": "2026-11-01"}
    assert la.is_reviewed({"reference": ref})
    ref[missing] = None if missing in ("reviewed_on",) else ([] if missing == "sources" else "")
    assert not la.is_reviewed({"reference": ref})
