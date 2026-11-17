"""The retrieval test set (evals/retrieval_set.json) is well formed and the recall arithmetic is right. The database itself is not needed."""
import json
import re
from pathlib import Path

import scripts.rag_baseline as rb  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "evals" / "retrieval_set.json"
data = json.loads(FIXTURE.read_text(encoding="utf-8"))
QS = data["questions"]


def test_forty_questions_each_with_an_expected_source():
    assert len(QS) == 40 and len({q["id"] for q in QS}) == 40
    assert sum(q["kind"] == "statute" for q in QS) == 24 and sum(q["kind"] == "judgment" for q in QS) == 16
    assert all(q["expected"] for q in QS)


def test_every_statute_expectation_names_a_provision_and_its_heading_from_the_data():
    for q in (x for x in QS if x["kind"] == "statute"):
        for e in q["expected"]:
            assert re.fullmatch(r"[0-9a-f-]{36}", e["provision_id"]) and e["heading"] and e["act"] in ("IPC", "BNS", "CrPC", "BNSS", "IEA", "BSA")


def test_judgment_expectations_have_an_id_a_court_and_a_year_and_the_question_names_the_parties():
    for q in (x for x in QS if x["kind"] == "judgment"):
        e = q["expected"][0]
        assert e["judgment_id"] and e["court"] and 2005 <= e["year"] <= 2020 and " v " in q["question"] and str(e["year"]) in q["question"]


def test_the_question_bank_rows_that_touch_the_acts_we_hold_are_included():
    assert {q["source"] for q in QS if q["source"].startswith("BANK")} == {"BANK B2", "BANK E3", "BANK J3"}


def test_recall_counts_a_miss_as_not_found():
    ranks = [1, 3, None, 5, 10, None, 2, 1]
    assert rb.recall(ranks, 1) == 2 / 8 and rb.recall(ranks, 3) == 4 / 8 and rb.recall(ranks, 10) == 6 / 8
    assert rb.recall([], 5) == 0.0


def test_first_rank_is_the_best_position_of_any_expected_source():
    assert rb.first_rank(["a", "b", "c", "d"], {"d", "b"}) == 2
    assert rb.first_rank(["a"], {"z"}) is None and rb.first_rank([], {"z"}) is None


def test_a_party_name_is_cleaned_from_a_case_title_and_noise_is_refused():
    assert rb._clean_title("CWJC/8434/1998 of SUKHDEO SINGH and ORS Vs THE DIRECTOR OF CONSOLIDATION") == "Sukhdeo Singh v The Director Of Consolidation"
    assert rb._clean_title("WP/1/2010 of ONLYONEPARTY") is None
    assert rb._clean_title("A Vs B") is None  # a single word on a side is too weak to ask about
