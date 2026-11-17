"""The 206-case legal Q&A set (46 hand-written, 160 court-style matters from evals/court_cases.py), run through the real pipeline with scripted ("gold") model replies, and the scorer itself."""

import json
import os
from pathlib import Path

import pytest

from evals import scoring
from tests.conftest import new_matter, stub, upload

DATA = json.loads((Path(os.path.abspath(__file__)).parent.parent / "evals" / "legal_qa.json").read_text(encoding="utf-8"))
CASES = DATA["cases"]


def test_the_set_is_big_enough_and_well_formed():
    assert len(CASES) >= 30
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert {c["category"] for c in CASES} >= {"grounded", "invented-quote", "law-not-in-library", "library-law", "absence", "neutral", "injection", "language", "missing-information"}
    for c in CASES:
        assert set(c["expect"]) <= scoring.KNOWN, c["id"]
        assert c["question"].strip() and c["gold"]["answer"].strip() and all(d in DATA["documents"] for d in c["documents"]), c["id"]


def test_the_set_contains_no_statement_of_real_law_in_its_expected_answers():
    """Questions may name real statutes, but no scripted answer may assert what a real provision says."""
    for c in CASES:
        blob = json.dumps(c["gold"], ensure_ascii=False).lower()
        assert "punishable" not in blob and "imprisonment" not in blob and "fine of" not in blob, c["id"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_each_case_scores_a_pass_through_the_real_pipeline(user_a, case):
    mid, title = new_matter(user_a, "Eval")
    for i, d in enumerate(case["documents"], start=1):
        upload(user_a, mid, f"doc{i}.txt", DATA["documents"][d])
    stub("research", {**case["gold"]}, contains=title)
    r = user_a.post("/research", json={"question": f"{case['question']} {title}", "matter_id": mid, "mode": "MATTER", "language": case["language"]})
    assert r.status_code == 200, r.text
    result = scoring.score_case(case, r.json())
    assert result["passed"], [c for c in result["checks"] if not c["ok"]]


# ---- the scorer must catch bad answers, otherwise a pass means nothing ----
def good_result(**kw):
    return {"answer": "Rs 40,000.", "disclaimer": "Research tool only. Not legal advice.", "claims": [], "uncertainty": "", "missing_information": [], "unverified_references": [], **kw}


def case_with(**expect):
    return {"id": "x", "category": "t", "expect": expect}


def test_a_verified_claim_without_a_checked_quote_fails():
    bad = good_result(claims=[{"text": "t", "claim_kind": "FACTUAL", "verification_status": "VERIFIED", "citations": [{"quote_verified": False}]}])
    assert not scoring.score_case(case_with(), bad)["passed"]


def test_verified_law_without_a_library_source_fails():
    bad = good_result(claims=[{"text": "t", "claim_kind": "LEGAL", "verification_status": "VERIFIED", "citations": [{"quote_verified": True}]}])
    assert not scoring.score_case(case_with(), bad)["passed"]
    ok = good_result(claims=[{"text": "t", "claim_kind": "LEGAL", "verification_status": "VERIFIED", "citations": [{"quote_verified": True, "library_id": "x"}]}])
    assert scoring.score_case(case_with(), ok)["passed"]


def test_missing_disclaimer_dishonest_wording_and_wrong_counts_fail():
    assert not scoring.score_case(case_with(), good_result(disclaimer=""))["passed"]
    assert not scoring.score_case(case_with(), good_result(answer="He lied."))["passed"]
    assert not scoring.score_case(case_with(verified_min=1), good_result())["passed"]
    verified = {"text": "t", "claim_kind": "ABSENCE", "verification_status": "VERIFIED", "citations": []}
    assert not scoring.score_case(case_with(verified_max=0), good_result(claims=[verified]))["passed"]
    assert scoring.score_case(case_with(verified_min=1), good_result(claims=[verified]))["passed"]


def test_language_uncertainty_and_reference_checks():
    assert scoring.script_share("नमस्ते दोस्त", "hi") > 0.9 and scoring.script_share("hello", "hi") == 0
    assert not scoring.score_case(case_with(language="hi"), good_result(answer="English only"))["passed"]
    assert scoring.score_case(case_with(language="hi"), good_result(answer="रवि ने सामान लिया"))["passed"]
    assert not scoring.score_case(case_with(uncertainty_required=True), good_result())["passed"]
    assert scoring.score_case(case_with(uncertainty_required=True), good_result(uncertainty="not checked"))["passed"]
    assert not scoring.score_case(case_with(unverified_references_min=1), good_result())["passed"]


def test_banned_words_match_whole_words_only():
    banned = case_with(must_not_contain=["lied"])
    assert scoring.score_case(banned, good_result(answer="The goods were supplied and the rule was applied."))["passed"]
    assert not scoring.score_case(banned, good_result(answer="He lied about it."))["passed"]
    assert not scoring.score_case(banned, good_result(answer="Lied."))["passed"]


def test_the_summary_averages_by_category():
    s = scoring.summarise([{"passed": True, "score": 100, "category": "a"}, {"passed": False, "score": 50, "category": "a"}, {"passed": True, "score": 100, "category": "b"}])
    assert s == {"cases": 3, "passed": 2, "score": 83, "by_category": {"a": 75, "b": 100}}