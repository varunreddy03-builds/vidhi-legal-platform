"""One search across the verified library, the structured legal store and the law drafts. Fictional Acts only. Whatever the store, only the verified library may say VERIFIED."""

from datetime import datetime, timezone

import pytest

from tests.conftest import mongo
from tests.test_admin import admin  # noqa: F401  (fixture)
from tests.test_legal_data import _drafts, load, mapping, pair, source, tag


MINE: dict = {"drafts": [], "verified": []}  # what THIS worker's current test inserted straight into the database (workers run in parallel: a test must never delete another test's rows)


@pytest.fixture(autouse=True)
def _clean_up_direct_rows():
    MINE["drafts"].clear()
    MINE["verified"].clear()
    yield
    for act in MINE["drafts"]:
        mongo().legal_source_candidates.delete_many({"id": {"$regex": f"^{act}-"}})
    for eid in MINE["verified"]:
        mongo().library_entries.delete_one({"id": eid})


def drafts(act, rows, **kw):
    MINE["drafts"].append(act)
    _drafts(act, rows, **kw)


def search(c, q, **params):
    r = c.get("/library/search", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _verified(title, extra=""):
    eid = f"verified-ufs-{tag().lower()}"
    mongo().library_entries.insert_one({
        "id": eid, "citation": f"Section 3, {title}", "aliases": [], "kind": "STATUTE_SECTION", "title": f"{title} section 3", "text": f"3. Whoever hoards tokens commits an offence under {title}. {extra}",
        "source_name": "Invented official gazette", "source_url": "https://example.invalid/verified", "version": "invented 1901 text", "verified_by": "Adv Invented Reviewer", "verified_on": "2026-10-20",
        "status": "VERIFIED", "text_sha256": "0" * 64, "created_at": datetime.now(timezone.utc)})
    MINE["verified"].append(eid)
    return eid


def test_a_result_from_each_store_appears_the_verified_one_ranks_first_and_only_it_is_verified(admin, user_a):  # noqa: F811
    old = load(admin)  # the structured store
    title = old["title"]
    vid = _verified(title)
    act = f"ufs-{tag().lower()}"
    drafts(act, [("9", "Hoarding", f"9. Hoarding.—Whoever hoards tokens under the {title} shall be fined.")])
    mongo().legal_source_candidates.update_one({"id": f"{act}-0"}, {"$set": {"status": "VERIFIED"}})  # a draft that CLAIMS to be verified
    got = search(user_a, f"Section 3 of the {title} hoards tokens fined")
    stores = {r["store"] for r in got["results"]}
    assert {"verified_library", "structured", "draft"} <= stores
    assert got["results"][0]["store"] == "verified_library" and got["results"][0]["id"] == vid
    assert got["results"][0]["status"] == "VERIFIED" and got["results"][0]["verified"] is True and got["results"][0]["verified_by"] == "Adv Invented Reviewer"
    for r in got["results"]:
        if r["store"] != "verified_library":
            assert r["status"] == "UNVERIFIED - not reviewed" and r["verified"] is False, r
    draft = [r for r in got["results"] if r["store"] == "draft" and r["id"] == f"{act}-0"]
    assert draft and draft[0]["status"] == "UNVERIFIED - not reviewed"  # claiming to be verified changes nothing
    assert all(r["source_name"] is not None and "version" in r for r in got["results"])
    assert got["counts"]["verified_library"] >= 1 and got["counts"]["structured"] >= 1 and got["counts"]["draft"] >= 1


def test_without_a_verified_match_every_result_is_unreviewed_and_the_notice_says_so(admin, user_a):  # noqa: F811
    act = f"ufs-{tag().lower()}"
    word = f"zqnone{tag().lower()}"  # a word no verified entry contains
    drafts(act, [("4", "Lone rule", f"4. Lone rule.—Whoever carries {word} shall be fined.")])
    got = search(user_a, word)
    assert got["counts"]["verified_library"] == 0 and got["results"]
    assert all(r["verified"] is False and r["status"] == "UNVERIFIED - not reviewed" for r in got["results"])
    assert any("Every result below is unreviewed" in n for n in got["notices"])


def test_a_question_that_names_a_date_gets_the_date_note_from_the_acts_own_text(admin, user_a):  # noqa: F811
    act = f"ufs-{tag().lower()}"
    word = f"zqdate{tag().lower()}"
    drafts(act, [("7", "Hoarding", f"7. Hoarding.—Whoever hoards {word} shall be fined.")], commencement="In force from 01-07-2024 (S.O. 850(E))")
    r = admin.post("/admin/legal/import-drafts", json={"act_id": act, "source_id": source(admin)["id"], "instrument": {"title": f"Fictional Dated Act {tag()}", "short_names": ["FDT"], "year": 1904}})
    assert r.status_code == 201, r.text
    before = search(user_a, f"{word} on 12 March 2023")
    hit = [x for x in before["results"] if word in x["excerpt"]]
    assert hit and all(x["date_check"]["state"] == "NOT_YET_IN_FORCE" and x["date_check"]["note"] for x in hit) and before["checked_on"] == "2023-03-12"
    assert all(x["verified"] is False for x in hit)
    after = search(user_a, word, on_date="2025-08-05")
    assert [x["date_check"]["state"] for x in after["results"] if word in x["excerpt"]][0] == "IN_FORCE"
    none = search(user_a, word)
    assert none["checked_on"] is None and all(x["date_check"] is None for x in none["results"])  # no date named: nothing is checked
    two = search(user_a, f"{word} between 12 March 2023 and 5 August 2025")
    assert two["checked_on"] is None and any("more than one date" in n for n in two["notices"])  # several dates: none is chosen


def test_a_structured_provision_whose_source_needs_a_permission_that_is_not_recorded_is_left_out(admin, user_a):  # noqa: F811
    old = load(admin)
    q = f"Section 3 of the {old['title']}"

    def mine():
        return [r for r in search(user_a, q)["results"] if r["store"] == "structured" and old["title"] in r["citation"]]

    assert mine()
    mongo().legal_sources.update_one({"id": old["src"]["id"]}, {"$set": {"permission_required": True, "permission_reference": ""}})
    assert not mine()
    mongo().legal_sources.update_one({"id": old["src"]["id"]}, {"$set": {"permission_reference": "Written permission from the publisher dated 2026-11-03, kept in the legal folder"}})
    assert mine()


def test_a_draft_already_in_the_structured_store_is_shown_once_and_says_it_is_also_a_draft(admin, user_a):  # noqa: F811
    act = f"ufs-{tag().lower()}"
    word = f"zqtwin{tag().lower()}"
    short = act.replace("ufs-", "ufst")
    drafts(act, [("5", "Twin rule", f"5. Twin rule.—Whoever carries {word} shall be fined.")])
    r = admin.post("/admin/legal/import-drafts", json={"act_id": act, "source_id": source(admin)["id"], "instrument": {"title": f"Fictional Twin Act {tag()}", "short_names": [short], "year": 1905}})
    assert r.status_code == 201, r.text
    mongo().legal_source_candidates.update_many({"act_id": act}, {"$set": {"act_id": short}})  # the draft's Act is known by the instrument's short name
    got = search(user_a, f"{word} fined")
    mine = [x for x in got["results"] if word in x["excerpt"]]
    assert len(mine) == 1 and mine[0]["store"] == "structured" and mine[0]["also_in_drafts"] is True and mine[0]["verified"] is False


def test_a_section_named_in_the_question_brings_its_mapping_labelled_unreviewed(admin, user_a):  # noqa: F811
    old, new, lp, np_ = pair(admin, user_a)
    assert mapping(admin, lp, np_).status_code == 201
    got = search(user_a, f"Section 3 of the {old['title']}")
    cards = [r for r in got["results"] if r["store"] == "mapping"]
    assert cards and new["title"] in cards[0]["citation"] and cards[0]["status"] == "UNVERIFIED - not reviewed" and cards[0]["verified"] is False
    assert "does not say which code applies" in cards[0]["note"]


def test_the_search_needs_a_login_and_an_empty_question_returns_nothing(anon, user_a):
    assert anon.get("/library/search", params={"q": "anything"}).status_code in (401, 403)
    got = search(user_a, "   ")
    assert got["results"] == [] and got["counts"] == {"verified_library": 0, "structured": 0, "draft": 0, "mapping": 0}
