"""Filters on the knowledge search (script, kind) and the last-line guard that keeps one organisation's private chunks away from another. The filters narrow inside the database query,
before the result limit. A chunk stored before the new fields existed has neither, so a filter leaves it out and no filter leaves it in. All texts are invented fixtures."""

import uuid

import pytest

from lib import knowledge
from tests.conftest import mongo, verify_email


@pytest.fixture
def me(user_a):
    verify_email(user_a)
    return user_a


def add_private(c, title, text):
    r = c.post("/knowledge/private", json={"title": title, "text": text})
    assert r.status_code == 200, r.text
    return r.json()["work_number"]


def found(c, q, **params):
    r = c.get("/knowledge/search", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()["hits"]


def test_script_and_kind_narrow_the_search_and_old_chunks_are_left_out_only_by_a_filter(me):
    word = "zorbufilter" + uuid.uuid4().hex[:6]
    english = add_private(me, "English fixture", f"TEST FIXTURE ONLY. The {word} method is written in plain English letters for this fixture.")
    hindi_body = "यह एक परीक्षण दस्तावेज़ है जो केवल हिंदी लिपि में लिखा गया है और इसमें कोई असली जानकारी नहीं है " * 3
    add_private(me, "Hindi fixture", f"{hindi_body} {word}")
    org = me.get("/auth/me").json()["organization_id"]
    mongo().knowledge_chunks.insert_one({"id": uuid.uuid4().hex, "work_number": english, "scope": "org", "org_id": org, "sha256": "legacy" + uuid.uuid4().hex, "chapter": "", "ordinal": 99,
                                         "text": f"TEST FIXTURE ONLY. {word} legacy chunk stored before the new fields."})

    everything = found(me, word)  # no filter: everything, the old chunk included
    assert len(everything) == 3 and {h["work"] for h in everything} == {"English fixture", "Hindi fixture"}
    assert sorted(str(h["script"]) for h in everything) == ["None", "devanagari", "latin"]  # the old chunk shows its script as unknown
    assert {h["work"] for h in found(me, word, script="latin")} == {"English fixture"} and len(found(me, word, script="latin")) == 1  # the legacy chunk has no script: left out
    assert {h["work"] for h in found(me, word, script="devanagari")} == {"Hindi fixture"}
    assert found(me, word, script="telugu") == []
    assert len(found(me, word, kind="firm_knowledge")) == 2  # the two new chunks; the legacy one has no kind
    assert found(me, word, kind="reference_work") == []  # private chunks are never reference works
    both = found(me, word, script="latin", kind="firm_knowledge")
    assert len(both) == 1 and both[0]["script"] == "latin" and both[0]["work"] == "English fixture"


def test_unknown_filter_values_are_refused(me):
    for params in ({"script": "klingon"}, {"kind": "banana"}, {"script": "BAD!"}, {"kind": "x" * 40}):
        assert me.get("/knowledge/search", params={"q": "anything", **params}).status_code == 422, params


def test_another_organisation_never_sees_private_chunks_with_or_without_filters(me, user_b):
    verify_email(user_b)
    word = "zorbuprivate" + uuid.uuid4().hex[:6]
    add_private(me, "Private fixture", f"TEST FIXTURE ONLY. {word} belongs to the first organisation only.")
    assert len(found(me, word)) == 1
    for params in ({}, {"script": "latin"}, {"kind": "firm_knowledge"}, {"script": "latin", "kind": "firm_knowledge"}):
        assert found(user_b, word, **params) == [], params


def test_the_guard_keeps_library_and_own_rows_and_drops_every_foreign_one():
    rows = [
        {"scope": "library", "org_id": None, "text": "shared"},
        {"scope": "org", "org_id": "org-me", "text": "mine"},
        {"scope": "org", "org_id": "org-other", "text": "theirs"},
        {"scope": "org", "org_id": None, "text": "private chunk with no owner"},
        {"scope": "something-new", "org_id": "org-me", "text": "unknown scope"},
        {"org_id": "org-me", "text": "no scope"},
    ]
    assert [r["text"] for r in knowledge.own_or_shared(rows, "org-me")] == ["shared", "mine"]  # anything not clearly shared or clearly mine is dropped
    assert knowledge.own_or_shared([], "org-me") == []


def test_the_search_really_runs_the_guard():
    import inspect

    src = inspect.getsource(knowledge.search)
    assert "rows = own_or_shared(rows, org_id)" in src and src.index("own_or_shared(rows, org_id)") < src.index("works = {")  # applied before any row is turned into a hit
