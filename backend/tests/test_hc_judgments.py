"""High Court judgments: read from the public dataset's own files, always "not reviewed", never able to verify a claim."""

import os

import pytest

from lib import hc_judgments as H

META = {
    "court_code": "36~29", "court_name": "High Court for State of Telangana", "pdf_link": "court/cnrorders/taphc/orders/X.pdf",
    "raw_html": "<button><font size='3'>CRLP/1/2020 of Panduga Praveen Kumar Vs State of Telangana</button></font><br><strong>Judge : K.SURENDER</strong><br>"
                "<strong class='caseDetailsTD'><span> CNR :</span><font color='green'> HBHC010000012020</font><span> | Date of registration :</span><font color='green'> 02-01-2020</font>"
                "<span> | Decision Date :</span><font color='green'> 15-03-2023</font><span> | Disposal Nature :</span><font color='green'> PARTLY ALLOWED NO COSTS</font></strong>",
}


def test_the_datasets_metadata_is_read_into_plain_fields_and_a_missing_field_stays_empty():
    p = H.parse_metadata(META)
    assert p["case_title"] == "CRLP/1/2020 of Panduga Praveen Kumar Vs State of Telangana" and p["judge"] == "K.SURENDER" and p["cnr"] == "HBHC010000012020"
    assert p["decision_date"] == "2023-03-15" and p["registration_date"] == "2020-01-02" and p["disposal"] == "PARTLY ALLOWED NO COSTS"
    bare = H.parse_metadata({"court_name": "X", "raw_html": "<button><font size='3'>A Vs B</button></font>"})
    assert bare["judge"] is None and bare["decision_date"] is None and bare["cnr"] is None  # never filled in


def test_a_record_is_always_not_reviewed_and_a_verified_or_altered_one_is_rejected():
    r = H.build_record(META, "HBHC010000012020_1_2023-03-15", "2023", "36_29", "taphc", "Judgment text.", "TEXT")
    assert H.validate_record(r) == [] and r["status"] == H.STATUS and "year=2023/court=36_29/bench=taphc/" in r["source_url"] and r["licence"] == "CC-BY-4.0"
    assert any("verified" in e for e in H.validate_record({**r, "status": "VERIFIED"}))
    assert any("hash" in e for e in H.validate_record({**r, "text": "Changed text."}))


def test_an_unreadable_pdf_is_kept_as_a_record_with_no_text():
    r = H.build_record(META, "n", "2023", "36_29", "taphc", "", "UNREADABLE")
    assert H.validate_record(r) == [] and r["text_kind"] == "UNREADABLE" and r["text_chars"] == 0


def test_judgments_can_be_searched_and_opened_and_are_labelled_not_reviewed(user_a):
    got = user_a.get("/judgments", params={"q": "quibblefrost licence"}).json()
    assert got["status"] == H.STATUS and "Not reviewed" in got["note"] and "CC-BY-4.0" in got["attribution"]
    hit = next(x for x in got["items"] if x["case_title"].startswith("CRLP/9/2099"))
    assert hit["status"] == H.STATUS and hit["court_name"] == "High Court of Fictionland" and hit["decision_date"] == "2099-03-15" and hit["note"] == H.NOTE
    full = user_a.get(f"/judgments/{hit['id']}").json()
    assert "quibblefrost" in full["text"] and full["status"] == H.STATUS
    assert user_a.get("/judgments/no-such").status_code == 404
    assert any(c["court_code"] == "99_1" for c in user_a.get("/judgments/courts").json()["courts"])
    assert user_a.get("/judgments", params={"court": "99_1"}).json()["total"] >= 1 and user_a.get("/judgments", params={"court": "1_1"}).json()["total"] == 0


def test_the_judgment_lookup_needs_a_signed_in_user(client):
    assert client.get("/judgments").status_code in (401, 403)


def test_research_shows_possibly_relevant_judgments_but_they_verify_nothing(user_a):
    from tests.conftest import answer, new_matter, stub, upload

    mid, title = new_matter(user_a)
    upload(user_a, mid, "01-note.txt", "A note about a licence.")
    stub("research", answer("Not enough information.", []), contains=title)
    got = user_a.post("/research", json={"question": "What did the court say about the quibblefrost licence of Zorblax Traders?", "matter_id": mid, "mode": "MATTER"}).json()
    assert any(j["case_title"].startswith("CRLP/9/2099") and j["status"] == H.STATUS for j in got["judgments"])
    assert all(c["verification_status"] != "VERIFIED" for c in got["claims"])


@pytest.fixture
def adb(monkeypatch):
    """A database client of its own for the module under test: each asyncio.run() makes a new event loop, and a client belongs to the loop it first ran in."""
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    database = client[os.environ["DB_NAME"]]
    monkeypatch.setattr(H, "db", database)
    yield database
    client.close()


def _bulk_record(rid="hc-bulk-test-1", url="https://indian-high-court-judgments.s3.ap-south-1.amazonaws.com/data/pdf/year=2001/court=99_1/bench=b/x.pdf"):
    meta = {"court_name": "High Court of Fictionland", "raw_html": "<button><font size='3'>Bulk Test Vs State</button></font>"}
    r = H.build_record(meta, "x", "2001", "99_1", "b", "", "NOT_LOADED")
    return {**r, "id": rid, "source_url": url, "origin": "bulk"}


def test_bulk_loaded_case_lists_survive_the_start_up_sync(adb):
    import asyncio

    from tests.conftest import mongo

    db = mongo()
    db.hc_judgments.replace_one({"id": "hc-bulk-test-1"}, _bulk_record(), upsert=True)
    try:
        asyncio.run(H.sync_judgments())
        assert db.hc_judgments.find_one({"id": "hc-bulk-test-1"}) is not None  # only records that came from files are managed by the sync
        assert db.hc_judgments.find_one({"id": "hc-99_1-fictbench-FICT010000092099_1_2099-03-15"}) is not None
    finally:
        db.hc_judgments.delete_many({"id": "hc-bulk-test-1"})


def test_the_text_of_a_case_list_record_is_fetched_when_opened_and_kept(monkeypatch, adb):
    import asyncio

    from tests.conftest import mongo

    db = mongo()
    db.hc_judgments.replace_one({"id": "hc-bulk-test-2"}, _bulk_record("hc-bulk-test-2"), upsert=True)
    monkeypatch.setattr(H, "_download_pdf", lambda url: b"%PDF fake")
    monkeypatch.setattr(H, "_pdf_text", lambda data: "The court held that the quibblefrost licence stands. " * 10)
    async def scenario():
        got = await H.get("hc-bulk-test-2")
        kept = await adb.hc_judgments.find_one({"id": "hc-bulk-test-2"})
        monkeypatch.setattr(H, "_pdf_text", lambda data: "too short")  # a picture-only PDF has almost no text layer
        await adb.hc_judgments.replace_one({"id": "hc-bulk-test-2"}, _bulk_record("hc-bulk-test-2"), upsert=True)
        scan = await H.get("hc-bulk-test-2")
        return got, kept, scan

    try:
        got, kept, scan = asyncio.run(scenario())
        assert got["text_kind"] == "TEXT" and "quibblefrost" in got["text"] and got["status"] == H.STATUS and "text_error" not in got
        assert kept["text_kind"] == "TEXT" and kept["text_sha256"] == H.sha256_text(kept["text"])  # stored, so the next reader does not wait
        assert scan["text_kind"] == "NO_TEXT_LAYER"
    finally:
        db.hc_judgments.delete_many({"id": "hc-bulk-test-2"})


def test_a_failed_fetch_says_so_and_keeps_the_case_details(monkeypatch, adb):
    import asyncio

    from tests.conftest import mongo

    db = mongo()
    db.hc_judgments.replace_one({"id": "hc-bulk-test-3"}, _bulk_record("hc-bulk-test-3"), upsert=True)

    def boom(url):
        raise OSError("network down")

    monkeypatch.setattr(H, "_download_pdf", boom)
    try:
        got = asyncio.run(H.get("hc-bulk-test-3"))
        assert got["text"] == "" and "could not be fetched" in got["text_error"] and got["case_title"] == "Bulk Test Vs State"
        assert db.hc_judgments.find_one({"id": "hc-bulk-test-3"})["text_kind"] == "NOT_LOADED"  # nothing half-saved
    finally:
        db.hc_judgments.delete_many({"id": "hc-bulk-test-3"})


def test_only_the_two_public_archives_are_ever_fetched():
    for bad in ("http://169.254.169.254/latest/meta-data/", "https://evil.example/x.pdf", "file:///etc/passwd", "https://indian-high-court-judgments.s3.ap-south-1.amazonaws.com.evil.example/x"):
        with pytest.raises(ValueError):
            H._download_pdf(bad)


def test_the_supreme_court_judge_names_are_cut_from_the_headnote_that_follows_them():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import sc_load_index as S

    assert S.judges("P. SATHASIVAM * , B.S. CHAUHAN 12 S.C.R. 974 HAR NARAIN v. MAM CHAND") == "P. SATHASIVAM, B.S. CHAUHAN"
    assert S.judges("R.V. RAVEENDRAN * , P. SATHASIVAM, A.K. PATNAIK . A B Maharashtra Land Revenue Code") == "R.V. RAVEENDRAN, P. SATHASIVAM, A.K. PATNAIK"
    assert S.judges(None) is None and S.judges("headnote only, no names") is None


def test_judgments_can_be_limited_to_a_range_of_years(user_a):
    inside = user_a.get("/judgments", params={"court": "99_1", "year_from": 2099, "year_to": 2099}).json()
    assert inside["total"] >= 1 and all(i["year"] == 2099 for i in inside["items"])
    assert user_a.get("/judgments", params={"court": "99_1", "year_from": 2000, "year_to": 2050}).json()["total"] == 0  # the test judgment is from 2099
    assert user_a.get("/judgments", params={"court": "99_1", "year_from": 2100}).json()["total"] == 0
    assert user_a.get("/judgments", params={"year_from": 99999}).status_code == 422  # an unreasonable year is refused


def test_a_long_question_is_searched_by_its_five_longest_words_all_required():
    q = "What does the law say about cheating and dishonestly inducing delivery of property"
    assert H.text_terms(q) == '"cheating" "dishonestly" "inducing" "delivery" "property"'
    assert H.text_terms("bail cheque") == "bail cheque"  # a few words are searched as typed
    assert H.text_terms("") == ""


def test_a_search_that_takes_too_long_gives_the_too_broad_answer_not_a_hang(monkeypatch, user_a):
    from unittest.mock import AsyncMock, MagicMock

    from pymongo.errors import ExecutionTimeout

    fake = MagicMock()
    fake.hc_judgments.find.return_value.sort.return_value = MagicMock()
    fake.hc_judgments.count_documents = AsyncMock(side_effect=ExecutionTimeout("operation exceeded time limit"))
    monkeypatch.setattr(H, "db", fake)
    import asyncio

    with pytest.raises(H.SearchTooBroad):
        asyncio.run(H.search(""))  # the list with no words counts its matches; a count that runs out of time gives the too-broad answer


def test_when_ranking_is_too_slow_the_first_matches_come_back_labelled_unranked(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from pymongo.errors import ExecutionTimeout

    class Cur:
        def __init__(self, rows, slow):
            self.rows, self.slow = rows, slow

        def sort(self, *_):
            return self

        def skip(self, _):
            return self

        def limit(self, _):
            return self

        def max_time_ms(self, _):
            if self.slow:
                raise ExecutionTimeout("operation exceeded time limit")  # what ranking millions of matches runs into
            return self

        def __aiter__(self):
            async def gen():
                for r in self.rows:
                    yield r

            return gen()

    row = {"id": "hc-x", "court_code": "99_1", "court_name": "High Court of Fictionland", "case_title": "T Vs S", "year": 2099, "text_kind": "NOT_LOADED"}
    fake = MagicMock()
    fake.hc_judgments.find.side_effect = lambda flt, proj=None: Cur([row], slow=bool(proj and "score" in proj))  # only the ranked query is too slow
    fake.hc_judgments.count_documents = AsyncMock(return_value=10000)
    monkeypatch.setattr(H, "db", fake)
    items, total = asyncio.run(H.search("bail"))
    assert total == 1 and len(items) == 1 and items[0]["ranked"] is False  # a text search does not count every match: that is as slow as ranking them


def test_a_text_search_where_even_the_unranked_fetch_is_too_slow_gives_the_too_broad_answer(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    from pymongo.errors import ExecutionTimeout

    class Slow:
        def sort(self, *_):
            return self

        def skip(self, _):
            return self

        def limit(self, _):
            return self

        def max_time_ms(self, _):
            raise ExecutionTimeout("operation exceeded time limit")

    fake = MagicMock()
    fake.hc_judgments.find.side_effect = lambda *a, **k: Slow()
    monkeypatch.setattr(H, "db", fake)
    with pytest.raises(H.SearchTooBroad):
        asyncio.run(H.search("bail"))
