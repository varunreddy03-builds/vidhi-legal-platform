"""The Tantivy search index over the court case list: it finds the expected case, rebuilds the same way every time, updates without duplicating, and when it is missing or damaged the
search falls back to MongoDB and still answers. Invented cases only."""

import asyncio
import os
import random
import string

import pytest

from lib import hc_judgments as H
from lib import judgment_index as ji
from tests.conftest import mongo


def tag() -> str:
    return "".join(random.choices(string.ascii_lowercase, k=7))


def rec(i, title, court="10_8", year=2010, text="", **over):
    return {"_id": f"{i:024x}", "id": f"ufi-{i}", "case_title": title, "court_code": court, "court_name": "Invented Court", "year": year, "judge": None, "disposal": "ALLOWED", "cnr": None, "snippet": "", "text": text, **over}


def ids(res):
    return res["ids"] if res else None


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("JUDGMENT_INDEX_DIR", str(tmp_path / "ix"))
    ji._forget()
    yield tmp_path / "ix"
    ji._forget()


def test_a_query_returns_the_expected_case_best_first_with_filters_paging_and_a_count(folder):
    w = tag()
    rows = [rec(1, f"{w} Traders Vs State of Invented"), rec(2, "Plain Title Vs Other", text=f"the petitioner prays for bail {w} granted"), rec(3, f"{w} Mills Vs Union", court="7_26", year=2020), rec(4, "Unrelated Matter Vs Nobody")]
    ji.build(rows, folder)
    got = ji.search([w], None, None, None, 0, 10)
    assert got["total"] == 3 and set(got["ids"]) == {"ufi-1", "ufi-2", "ufi-3"}
    assert got["ids"][-1] == "ufi-2"  # a word in the title outranks the same word deep in the text
    assert ids(ji.search([w, "mills"], None, None, None, 0, 10)) == ["ufi-3"]  # every word is required
    assert ids(ji.search([w], "7_26", None, None, 0, 10)) == ["ufi-3"] and set(ids(ji.search([w], "10_8", None, None, 0, 10))) == {"ufi-1", "ufi-2"}  # the court filter
    assert ids(ji.search([w], None, 2015, None, 0, 10)) == ["ufi-3"] and set(ids(ji.search([w], None, None, 2012, 0, 10))) == {"ufi-1", "ufi-2"}
    page1, page2 = ji.search([w], None, None, None, 0, 2), ji.search([w], None, None, None, 2, 2)
    assert len(page1["ids"]) == 2 and len(page2["ids"]) == 1 and set(page1["ids"]) | set(page2["ids"]) == {"ufi-1", "ufi-2", "ufi-3"} and page1["total"] == page2["total"] == 3
    assert ji.search(["zzznosuchwordzzz"], None, None, None, 0, 10) == {"ids": [], "total": 0}


def test_a_rebuild_is_repeatable_and_an_update_adds_only_new_cases_and_replaces_refreshed_ones(folder):
    w = tag()
    first = [rec(1, f"{w} One"), rec(2, f"{w} Two")]
    a = ji.build(first, folder)
    b = ji.build(first, folder)  # a second rebuild empties the folder first
    assert a["docs"] == b["docs"] == 2 and set(ids(ji.search([w], None, None, None, 0, 10))) == {"ufi-1", "ufi-2"} and ji.read_state(folder)["docs"] == 2
    ji.build([rec(3, f"{w} Three")], folder, rebuild=False)  # an update
    assert ji.read_state(folder)["docs"] == 3 and ji.search([w], None, None, None, 0, 10)["total"] == 3
    fresh = tag()
    assert ji.refresh([rec(1, f"{w} One", text=f"the judgment text now says {fresh}")], folder) == 1
    assert ids(ji.search([fresh], None, None, None, 0, 10)) == ["ufi-1"]
    assert ji.search([w], None, None, None, 0, 10)["total"] == 3  # replaced, not duplicated


def test_a_missing_or_damaged_index_or_a_missing_tantivy_means_no_index_not_an_error(folder, monkeypatch):
    assert ji.search(["bail"], None, None, None, 0, 10) is None and ji.available() is False  # nothing built here
    ji.build([rec(1, "Bail Traders Vs State")], folder)
    assert ids(ji.search(["bail"], None, None, None, 0, 10)) == ["ufi-1"]
    (folder / ji.STATE_FILE).write_text("not json", encoding="utf-8")
    ji._forget()
    assert ji.search(["bail"], None, None, None, 0, 10) is None  # the state file is unreadable
    ji.build([rec(1, "Bail Traders Vs State")], folder)
    monkeypatch.setattr(ji, "_tv", lambda: None)
    ji._forget()
    assert ji.search(["bail"], None, None, None, 0, 10) is None  # Tantivy is not installed


@pytest.fixture
def adb(monkeypatch):
    """A database client of its own for the module under test (each asyncio.run() makes a new event loop)."""
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    monkeypatch.setattr(H, "db", client[os.environ["DB_NAME"]])
    yield
    client.close()


def mongo_case(i, w, court="96_4"):
    doc = {"id": f"ufi-{i}-{w}", "court_code": court, "court_name": "Invented Court", "bench": "b", "year": 2010, "case_title": f"{w} Traders Vs State", "judge": None, "cnr": None, "decision_date": "2010-05-01",
           "registration_date": None, "disposal": None, "source_url": "https://example.invalid/j.pdf", "text": "", "text_chars": 0, "text_kind": "NOT_LOADED", "status": H.STATUS}
    mongo().hc_judgments.insert_one(doc)
    return doc


def test_the_search_uses_the_index_when_there_is_one_and_answers_from_mongodb_when_there_is_not(folder, adb):
    w = tag()
    case = mongo_case(1, w)
    async def scenario():  # one event loop for the whole scenario: the database client belongs to the loop it first ran in
        # no index folder: the MongoDB text search answers (the safe fallback)
        items, total = await H.search(w)
        assert [i["id"] for i in items] == [case["id"]] and "ranked" not in items[0] and total >= 1
        # with an index that holds the case: ranked by the index, the case itself read from MongoDB
        ji.build([{**rec(1, case["case_title"], court="96_4", year=2010), "id": case["id"]}], folder)
        items, total = await H.search(w)
        assert [i["id"] for i in items] == [case["id"]] and items[0]["ranked"] is True and items[0]["status"] == H.STATUS and total == 1
        # the index only finds: a case that is in the index but no longer in MongoDB is simply not shown
        mongo().hc_judgments.delete_many({"id": case["id"]})
        assert await H.search(w) == ([], 1)

    try:
        asyncio.run(scenario())
    finally:
        mongo().hc_judgments.delete_many({"id": case["id"]})


def test_the_words_a_question_is_searched_by_are_the_same_as_before():
    q = "What does the law say about cheating and dishonestly inducing delivery of property"
    assert H.text_words(q) == ["cheating", "dishonestly", "inducing", "delivery", "property"]
    assert H.text_terms(q) == '"cheating" "dishonestly" "inducing" "delivery" "property"'
    assert H.text_words("bail cheque") == ["bail", "cheque"] and H.text_terms("bail cheque") == "bail cheque" and H.text_words("") == []
