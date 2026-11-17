"""The writing-system (script) filter on judgments, and the common descriptive fields every judgment and matter page carries (lib/chunk_contract.py)."""

import os

import pytest

from lib import chunk_contract, court_hierarchy, hc_judgments as H
from lib.script_detect import NAMES, judgment_script, stored_script

HINDI = "उच्च न्यायालय जयपुर पीठ आदेश एकलपीठ सिविल रिट याचिका संख्या"
MIXED = "ORDER पीठ आदेश"


def test_a_judgments_script_comes_from_the_opening_of_the_order_and_only_a_non_latin_one_is_stored():
    assert judgment_script("Order of the Court.", "A Vs B") == "latin" and stored_script("Order of the Court.", "A Vs B") is None
    assert judgment_script(HINDI, "GAURI SHANKAR Vs STATE") == "devanagari" and stored_script(HINDI, "GAURI SHANKAR Vs STATE") == "devanagari"  # an English title does not hide a Hindi order
    assert judgment_script("", HINDI) == "devanagari" and judgment_script(None, "A Vs B") == "latin"  # no opening: the title decides
    assert stored_script(MIXED) == "mixed" and stored_script("", "") == "none" and judgment_script("1234 / 56", None) == "none"  # no letters: unknown, not Latin
    assert {judgment_script(HINDI), judgment_script("x")} <= NAMES


def test_the_file_and_the_bulk_loaders_store_the_script_the_same_way():
    meta = {"court_name": "X", "raw_html": "<button><font size='3'>A Vs B</button></font>"}
    hindi = H.build_record(meta, "n1", "2023", "9_9", "b", HINDI * 3, "TEXT")
    latin = H.build_record(meta, "n2", "2023", "9_9", "b", "Judgment text of the court.", "TEXT")
    assert hindi["script"] == "devanagari" and "script" not in latin
    assert H.view(hindi)["script"] == "devanagari" and H.view(latin)["script"] == "latin"  # a record without the field is shown as Latin


def test_every_judgment_view_carries_the_common_fields_and_is_never_above_tier_two():
    meta = {"court_name": "High Court of Fictionland", "raw_html": "<button><font size='3'>A Vs B</button></font><br>"}
    r = H.build_record(meta, "n3", "2001", "99_1", "b", "Some text.", "TEXT")
    c = H.view({**r, "citation": "2001 SCC 1"})["contract"]
    assert c == {"kind": "judgment", "trust_tier": "T2", "source_id": r["id"], "citation_title": "2001 SCC 1", "page_or_para": None, "script": "latin", "reviewer": None, "review_date": None,
                 "court_code": "99_1", "court_name": "High Court of Fictionland", "year": 2001, "decision_date": None, "court_level": None, "states": []}  # a code the table does not know: nothing guessed
    assert chunk_contract.judgment_fields({**r, "citation": None})["citation_title"] == "A Vs B"  # the title when there is no citation; never a made-up one


def test_a_matter_page_carries_its_organisation_matter_and_printed_page_number_and_is_tier_three():
    doc = {"id": "d1", "filename": "notice.pdf", "organization_id": "org-1", "matter_id": "m-1", "pages": ["First page text.", "   ", HINDI, ""]}
    got = chunk_contract.matter_page_fields(doc)
    assert [g["page_or_para"] for g in got] == ["1", "3"]  # blank pages are skipped and the numbers stay the printed ones
    assert all(g["kind"] == "matter_page" and g["trust_tier"] == "T3" and g["organization_id"] == "org-1" and g["matter_id"] == "m-1" and g["source_id"] == "d1"
               and g["reviewer"] is None and g["review_date"] is None and g["citation_title"] == "notice.pdf" for g in got)
    assert [g["script"] for g in got] == ["latin", "devanagari"] and got[1]["exact_text"] == HINDI
    assert chunk_contract.matter_page_fields({"id": "d2", "organization_id": "o"}) == []
    with pytest.raises(KeyError):
        chunk_contract.matter_page_fields({"id": "d3", "pages": ["x"]})  # a page without its organisation is refused, never stored unowned


@pytest.fixture
def three():
    from tests.conftest import mongo

    db = mongo()
    meta = {"court_name": "High Court of Fictionland", "raw_html": "<button><font size='3'>zzscriptword Vs State</button></font>"}
    recs = []
    for rid, text, extra in (("hc-script-latin", "", {}), ("hc-script-hindi", "", {"script": "devanagari"}), ("hc-script-mixed", "", {"script": "mixed"})):
        r = H.build_record(meta, rid, "2001", "98_7", "b", text, "NOT_LOADED")
        recs.append({**r, "id": rid, "origin": "bulk", **extra, "decision_date": "2001-05-05"})
    db.hc_judgments.insert_many(recs)
    yield
    db.hc_judgments.delete_many({"id": {"$in": [r["id"] for r in recs]}})


def ids(client, **params):
    got = client.get("/judgments", params={"court": "98_7", **params})
    assert got.status_code == 200, got.text
    return {i["id"] for i in got.json()["items"]}


def test_the_script_filter_separates_latin_hindi_and_mixed_records_with_and_without_words(user_a, three):
    assert ids(user_a) == {"hc-script-latin", "hc-script-hindi", "hc-script-mixed"}
    for words in ({}, {"q": "zzscriptword"}):
        assert ids(user_a, script="latin", **words) == {"hc-script-latin"}
        assert ids(user_a, script="devanagari", **words) == {"hc-script-hindi"}
        assert ids(user_a, script="mixed", **words) == {"hc-script-mixed"}
        assert ids(user_a, script="tamil", **words) == set()
    hit = next(i for i in user_a.get("/judgments", params={"court": "98_7", "script": "devanagari"}).json()["items"])
    assert hit["script"] == "devanagari" and hit["contract"]["script"] == "devanagari" and hit["status"] == H.STATUS


def test_an_unknown_script_is_refused_not_ignored(user_a):
    r = user_a.get("/judgments", params={"script": "klingon"})
    assert r.status_code == 422 and "devanagari" in r.json()["detail"]
    assert user_a.get("/judgments", params={"script": "latin", "court": "1_1"}).status_code == 200


def test_the_loaders_and_the_backfill_use_the_same_rule():
    root = os.path.join(os.path.dirname(__file__), "..", "scripts")
    for name in ("hc_load_metadata.py", "sc_load_index.py", "judgment_script_backfill.py"):
        assert "stored_script(" in open(os.path.join(root, name), encoding="utf-8").read(), name


def test_every_court_in_the_data_is_in_the_hierarchy_table_and_each_state_has_a_court():
    seen = {"10_8", "11_24", "14_25", "16_20", "17_21", "18_6", "19_16", "1_12", "20_7", "21_11", "22_18", "23_23", "24_17", "27_1", "28_2", "29_3", "2_5", "32_4", "33_10", "36_29", "3_22", "5_15", "7_26", "8_9", "9_13"}
    assert seen == set(court_hierarchy.HIGH_COURTS)  # the 25 High Court codes in the public dataset
    assert court_hierarchy.level_of("SC") == "supreme" and court_hierarchy.level_of("27_1") == "high" and court_hierarchy.level_of("99_1") is None and court_hierarchy.level_of(None) is None
    assert court_hierarchy.courts_for_state("goa") == ["27_1"] and court_hierarchy.courts_for_state("Chandigarh") == ["3_22"] and court_hierarchy.courts_for_state("Ladakh") == ["1_12"]
    assert court_hierarchy.courts_for_state("Atlantis") == [] and court_hierarchy.courts_for_state("") == []
    assert len(court_hierarchy.STATES) == len(set(court_hierarchy.STATES)) and all(court_hierarchy.courts_for_state(st) for st in court_hierarchy.STATES)
    assert court_hierarchy.courts_for_level("supreme") == ["SC"] and court_hierarchy.courts_for_level("district_sessions") == [] and set(court_hierarchy.LOADED_LEVELS) <= set(court_hierarchy.LEVELS)


@pytest.fixture
def two_states():
    from tests.conftest import mongo

    db = mongo()
    meta = {"court_name": "Bombay High Court", "raw_html": "<button><font size='3'>zzstateword Vs State</button></font>"}
    recs = []
    for rid, code, name in (("hc-hier-bom", "27_1", "Bombay High Court"), ("hc-hier-pat", "10_8", "Patna High Court"), ("hc-hier-sc", "SC", "Supreme Court of India")):
        r = H.build_record({**meta, "court_name": name}, rid, "2001", code, "b", "", "NOT_LOADED")
        recs.append({**r, "id": rid, "court_name": name, "origin": "bulk", "decision_date": "2001-05-05"})
    db.hc_judgments.insert_many(recs)
    yield
    db.hc_judgments.delete_many({"id": {"$in": [r["id"] for r in recs]}})


def test_the_state_and_court_level_filters_pick_courts_and_never_widen_to_everything(user_a, two_states):
    def got(**p):
        r = user_a.get("/judgments", params={"year_from": 2001, "year_to": 2001, **p})
        assert r.status_code == 200, r.text
        return {i["id"] for i in r.json()["items"]} & {"hc-hier-bom", "hc-hier-pat", "hc-hier-sc"}

    for words in ({}, {"q": "zzstateword"}):
        assert got(state="Goa", **words) == {"hc-hier-bom"} and got(state="bihar", **words) == {"hc-hier-pat"}  # Goa is served by the Bombay High Court
        assert got(court_level="supreme", **words) == {"hc-hier-sc"} and got(court_level="high", **words) == {"hc-hier-bom", "hc-hier-pat"}
        assert got(state="Maharashtra", court_level="supreme", **words) == set()  # both filters must hold
        assert got(state="Maharashtra", court="10_8", **words) == set() and got(state="Maharashtra", court="27_1", **words) == {"hc-hier-bom"}
        assert got(court_level="district_sessions", **words) == set()  # a level with no records: nothing, not everything
    item = next(i for i in user_a.get("/judgments", params={"court": "27_1", "year_from": 2001, "year_to": 2001}).json()["items"] if i["id"] == "hc-hier-bom")
    assert item["contract"]["court_level"] == "high" and "Goa" in item["contract"]["states"]


def test_an_unknown_state_or_level_is_refused_and_the_state_list_is_available(user_a):
    assert user_a.get("/judgments", params={"state": "Atlantis"}).status_code == 422
    assert user_a.get("/judgments", params={"court_level": "galactic"}).status_code == 422
    body = user_a.get("/judgments/states").json()
    assert {x["state"] for x in body["states"]} == set(court_hierarchy.STATES) and body["levels_with_records"] == ["supreme", "high"] and "no data" in body["note"]
