"""The lawyer-checked evaluation set: loading, scoring (including the worst kind, wrong but confident), the dated report that is never overwritten, and an offline run with the scripted
stand-in. Invented text only (the Fictional Widget Testing Act of the test library)."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evals import lawyer_set as ls

BACKEND = Path(__file__).resolve().parent.parent
SAMPLE = BACKEND / "evals" / "lawyer_set.sample.jsonl"
S1 = "Section 1, Fictional Widget Testing Act, 2000"


def write(tmp_path, *lines):
    p = tmp_path / "set.jsonl"
    p.write_text("\n".join(json.dumps(x) if isinstance(x, dict) else x for x in lines) + "\n", encoding="utf-8")
    return p


# ---------- the loader ----------
def test_a_good_file_loads_with_aliases_default_ids_and_comments(tmp_path):
    p = write(tmp_path, "# a comment", {"question": "How many days must a borrower take to return a widget?", "answer": "Thirty days.", "citation": S1}, "",
              {"id": "X9", "question": "Another question about widgets?", "correct_answer": "No fee.", "sources": [S1, "Section 2, Fictional Widget Testing Act, 2000"], "must_contain": ["fee", 30]})
    cases, problems, warnings = ls.load(p)
    assert problems == [] and warnings == []
    assert [c["id"] for c in cases] == ["L001", "X9"] and cases[0]["correct_answer"] == "Thirty days." and cases[0]["sources"] == [S1]
    assert len(cases[1]["sources"]) == 2 and cases[1]["must_contain"] == ["fee", "30"] and cases[1]["expect"] == "answer"


def test_a_bad_file_is_refused_with_plain_reasons_and_never_raises(tmp_path):
    p = write(tmp_path, "not json", "[1, 2]", {"question": "", "correct_answer": "x", "source": "y"}, {"id": "A", "question": "A real question here?", "source": "s"},
              {"id": "A", "question": "A real question here?", "correct_answer": "Yes.", "source": "s"}, {"id": "B", "question": "Another real question?", "correct_answer": "Yes.", "source": "s", "expect": "maybe"},
              {"id": "C", "question": "Yet another real question?", "correct_answer": "Yes.", "source": "s", "must_contain": "not a list"})
    cases, problems, _ = ls.load(p)
    text = " | ".join(problems)
    for needle in ("line 1: not valid JSON", "line 2: not a JSON object", "no question", "no correct_answer", "the id is used twice", "expect must be one of", "must_contain must be a list"):
        assert needle in text, needle
    assert ls.load(tmp_path / "missing.jsonl")[1][0].startswith("The file ") and "does not exist" in ls.load(tmp_path / "missing.jsonl")[1][0]
    empty = tmp_path / "empty.jsonl"
    empty.write_text("# nothing\n", encoding="utf-8")
    assert ls.load(empty)[1] == ["The file has no cases."]
    bad = tmp_path / "bad.jsonl"
    bad.write_bytes(b"\xff\xfe\x00 not utf-8")
    assert "UTF-8" in ls.load(bad)[1][0]


def test_no_source_is_allowed_only_when_the_right_answer_is_could_not_check(tmp_path):
    ok = write(tmp_path, {"question": "What does the guidance say about widgets?", "correct_answer": "", "source": "", "expect": "could_not_check"})
    assert ls.load(ok)[1] == []
    missing = write(tmp_path, {"question": "What does the guidance say about widgets?", "correct_answer": "Thirty days.", "source": ""})
    assert "no source" in ls.load(missing)[1][0]


def test_personal_details_and_repeated_questions_are_warned_about(tmp_path):
    p = write(tmp_path, {"question": "Does ramesh.private@example.com have to pay the widget fee?", "correct_answer": "No.", "source": S1},
              {"question": "Does ramesh.private@example.com have to pay the widget fee?", "correct_answer": "No.", "source": S1, "id": "L002"})
    _, problems, warnings = ls.load(p)
    assert problems == [] and any("email address" in w for w in warnings) and any("same question" in w for w in warnings)


# ---------- the scoring ----------
CASE = {"id": "T1", "question": "Within how many days must a borrower return a widget?", "correct_answer": "A borrower must return the widget to the lender within thirty days.",
        "sources": [S1], "language": "en", "must_contain": [], "expect": "answer", "note": ""}


def result(answer, claims=None, **extra):
    return {"answer": answer, "claims": claims or [], "uncertainty": "", "missing_information": [], **extra}


def claim(text, label, kind="LEGAL", citation=S1, verified=False):
    return {"text": text, "claim_kind": kind, "verification_status": label, "citations": [{"citation": citation, "quote_verified": verified}]}


RIGHT_TEXT = "A borrower must return the widget to the lender within thirty days."
WRONG_TEXT = "A borrower must return the widget to the lender within ninety days."


def test_a_right_answer_with_the_right_verified_source_scores_right_everywhere():
    s = ls.score_case(CASE, result(RIGHT_TEXT, [claim(RIGHT_TEXT, "VERIFIED", verified=True)]), library_has_source=True)
    assert s["answer"]["state"] == "right" and s["citation"]["state"] == "right" and s["citation"]["verified"] is True
    assert [c["verdict"] for c in s["claims"]] == ["right"] and s["wrong_confident"] is False
    assert s["abstain"]["should"] is False and s["abstain"]["over_cautious"] is False


def test_a_wrong_answer_in_a_verified_claim_is_wrong_but_confident_and_counted_on_its_own():
    s = ls.score_case(CASE, result(WRONG_TEXT, [claim(WRONG_TEXT, "VERIFIED", verified=True)]), library_has_source=True)
    assert s["answer"]["state"] != "right" and [c["verdict"] for c in s["claims"]] == ["wrong_confident"] and s["wrong_confident"] is True
    summary = ls.summarise([s])
    assert summary["wrong_but_confident"] == {"cases": ["T1"], "count": 1, "unflagged": 1, "unflagged_cases": ["T1"]} and summary["claims"]["wrong_confident"] == 1


def test_a_wrong_answer_that_vidhi_marked_as_unchecked_is_counted_as_confident_but_not_as_unflagged():
    banner = "Not checked against any source: this is the AI's own recollection. Do not rely on it.\n\n" + WRONG_TEXT
    s = ls.score_case(CASE, result(banner, [claim(WRONG_TEXT, "UNSUPPORTED")]), library_has_source=False)
    assert s["answer"]["state"] != "right"
    assert s["wrong_confident"] is True and s["unflagged"] is False  # the model sounded sure, but the lawyer was told it was unchecked
    assert [c["verdict"] for c in s["claims"]] == ["right_refused"]  # refusing to verify a claim that differs is the right label
    assert s["abstain"]["should"] is True and s["abstain"]["did"] is False and s["abstain"]["ok"] is False  # the banner is VIDHI's, not the model saying it could not check


def test_a_wrong_confident_answer_with_no_hedge_and_no_verified_claim_is_still_wrong_but_confident():
    s = ls.score_case(CASE, result("The widget must be returned within ninety days of borrowing."), library_has_source=True)
    assert s["answer"]["state"] == "wrong" and s["wrong_confident"] is True and s["unflagged"] is False  # no VERIFIED claim, so the labels themselves tell the lawyer it is unchecked


def test_an_unrelated_claim_is_not_scored_and_a_too_cautious_claim_is_named():
    s = ls.score_case(CASE, result(RIGHT_TEXT, [claim("The court sits in the capital city.", "VERIFIED", kind="FACTUAL"), claim(RIGHT_TEXT, "UNSUPPORTED")]), library_has_source=False)
    assert [c["verdict"] for c in s["claims"]] == ["not_scored", "too_cautious"]
    assert ls.summarise([s])["claims"]["too_cautious"] == 1


def test_the_lawyers_must_contain_list_decides_the_answer_when_given():
    case = {**CASE, "must_contain": ["thirty", "lender"]}
    assert ls.score_case(case, result("The borrower returns it to the lender in thirty days."), True)["answer"]["state"] == "right"
    assert ls.score_case(case, result("Give it back in thirty days."), True)["answer"]["state"] == "partly"
    assert ls.score_case(case, result("It depends."), True)["answer"]["state"] == "wrong"


def test_could_not_check_cases_want_an_abstention_and_a_confident_answer_there_is_wrong_and_confident():
    case = {**CASE, "expect": "could_not_check", "sources": [], "correct_answer": ""}
    said = ls.score_case(case, result("I cannot verify this from the materials provided.", [], uncertainty="No verified source."), False)
    assert said["answer"]["state"] == "right" and said["abstain"]["ok"] is True and said["citation"]["state"] == "not_applicable" and said["wrong_confident"] is False
    guessed = ls.score_case(case, result("The penalty is a fine of five thousand rupees."), False)
    assert guessed["answer"]["state"] == "wrong" and guessed["abstain"]["ok"] is False and guessed["wrong_confident"] is True
    banner = "Not checked against any source: this is the AI's own recollection.\n\nThe penalty is a fine of five thousand rupees."
    assert ls.score_case(case, result(banner), False)["answer"]["state"] == "wrong"  # VIDHI's banner does not turn a guess into a refusal


def test_a_verified_legal_claim_where_the_source_is_not_in_the_library_means_could_not_check_was_not_used():
    s = ls.score_case(CASE, result(RIGHT_TEXT, [claim(RIGHT_TEXT, "VERIFIED", verified=True)]), library_has_source=False)
    assert s["abstain"]["should"] is True and s["abstain"]["ok"] is False


def test_too_cautious_is_counted_when_a_verified_source_existed_and_vidhi_still_abstained():
    s = ls.score_case(CASE, result("I cannot verify this.", [], uncertainty="unsure"), library_has_source=True)
    assert s["abstain"]["over_cautious"] is True and ls.summarise([s])["could_not_check"]["over_cautious"] == 1


@pytest.mark.parametrize("source,cited,expected", [
    (S1, "Section 1, Fictional Widget Testing Act, 2000", True),
    (S1, "Fictional Widget Testing Act, 2000, s. 1", True),
    (S1, "Section 2, Fictional Widget Testing Act, 2000", False),
    (S1, "Section 1, Imaginary Gadget Rules, 1990", False),
    ("Rangappa v. Sri Mohan (2010) 11 SCC 441", "Rangappa v. Sri Mohan, (2010) 11 SCC 441", True),
    ("Rangappa v. Sri Mohan (2010) 11 SCC 441", "Rangappa v. Sri Mohan (2010) 11 SCC 442", False),
])
def test_source_matching_needs_the_same_numbers_and_most_of_the_same_words(source, cited, expected):
    assert ls.source_matches(source, cited) is expected


def test_a_source_named_only_in_the_answer_text_counts_but_is_marked_as_text_only():
    s = ls.score_case(CASE, result("Under Section 1 of the Fictional Widget Testing Act, 2000, a borrower must return the widget to the lender within thirty days."), True)
    assert s["citation"]["state"] == "right" and s["citation"]["in_text_only"] == 1 and s["citation"]["verified"] is False


def test_a_different_source_cited_is_wrong_and_no_citation_is_none():
    other = ls.score_case(CASE, result(RIGHT_TEXT, [claim(RIGHT_TEXT, "UNSUPPORTED", citation="Section 9, Some Other Act, 1999")]), True)
    assert other["citation"]["state"] == "wrong"
    none = ls.score_case(CASE, result("Return it within thirty days."), True)
    assert none["citation"]["state"] == "none"


# ---------- the report ----------
def scored_sample():
    ok = ls.score_case(CASE, result(RIGHT_TEXT, [claim(RIGHT_TEXT, "VERIFIED", verified=True)]), True)
    bad = ls.score_case({**CASE, "id": "T2"}, result(WRONG_TEXT, [claim(WRONG_TEXT, "VERIFIED", verified=True)]), True)
    return [ok, bad]


def test_the_report_puts_wrong_but_confident_first_and_names_the_cases():
    text = ls.render_report(scored_sample(), {"date": "2026-11-06", "mode": "offline-echo", "answers_from": "the stand-in", "file": "set.jsonl", "sha256": "ab" * 32, "commit": "abc1234", "library_entries": 0})
    assert text.index("wrong but confident") < text.index("## Scores") < text.index("## Case by case")
    assert "**1 case(s)** where the model sounded sure and was wrong: T2" in text and "**1 of them reached the lawyer WITHOUT VIDHI's \"unchecked\" warning**" in text and "wrong and VERIFIED 1" in text
    assert "| T2 |" in text and "word and number rules" in text


def test_a_saved_report_never_replaces_an_older_one(tmp_path):
    when = datetime(2026, 11, 6, 9, 30, tzinfo=timezone.utc)
    first = ls.save_report("first\n", {"n": 1}, tmp_path, "offline-echo", now=when)
    second = ls.save_report("second\n", {"n": 2}, tmp_path, "offline-echo", now=when)
    third = ls.save_report("third\n", {"n": 3}, tmp_path, "offline-echo", now=when)
    assert first.name == "lawyer-eval-2026-11-06-0930-offline-echo.md" and second.name.endswith("-2.md") and third.name.endswith("-3.md")
    assert first.read_text() == "first\n" and second.read_text() == "second\n"  # the older text is untouched
    assert json.loads(first.with_suffix(".json").read_text()) == {"n": 1} and json.loads(third.with_suffix(".json").read_text()) == {"n": 3}


# ---------- the runner, offline with the scripted stand-in ----------
def run_script(*args, env_extra=None):
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run([sys.executable, "-I", str(BACKEND / "scripts" / "lawyer_eval.py"), *args], capture_output=True, text=True, env=env, cwd=str(BACKEND))


def test_check_mode_reads_the_sample_and_the_real_path_message_is_plain(tmp_path):
    ok = run_script("--check", "--set", str(SAMPLE))
    assert ok.returncode == 0 and "Loaded 3 cases" in ok.stdout
    gone = run_script("--check", "--set", str(tmp_path / "nope.jsonl"))
    assert gone.returncode == 2 and "does not exist" in gone.stdout


@pytest.mark.parametrize("standin,right_min,wrong_confident", [("echo", 3, 0), ("wrong", 0, 3), ("abstain", 1, 0)])
def test_the_offline_run_with_the_stand_in_scores_and_saves_a_dated_report(tmp_path, standin, right_min, wrong_confident):
    r = run_script("--offline", "--standin", standin, "--fixture-library", "--set", str(SAMPLE), "--out-dir", str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    reports = sorted(tmp_path.glob("lawyer-eval-*-offline-*.md"))
    assert len(reports) == 1 and reports[0].name.endswith(f"offline-{standin}.md")
    data = json.loads(reports[0].with_suffix(".json").read_text(encoding="utf-8"))
    s = data["summary"]
    assert s["cases"] == 3 and s["answer"]["right"] >= right_min and s["wrong_but_confident"]["count"] == wrong_confident
    assert data["meta"]["library_entries"] >= 2  # the invented test library was loaded, so its two entries are "verified" for this run
    text = reports[0].read_text(encoding="utf-8")
    assert "The worst kind: wrong but confident" in text and "scripted stand-in" in text
    again = run_script("--offline", "--standin", standin, "--fixture-library", "--set", str(SAMPLE), "--out-dir", str(tmp_path))
    assert again.returncode == 0 and len(list(tmp_path.glob("lawyer-eval-*.md"))) == 2  # a second run adds a report, it never replaces the first


def test_the_wrong_stand_in_is_caught_as_wrong_and_confident_and_the_product_marks_it_unchecked(tmp_path):
    r = run_script("--offline", "--standin", "wrong", "--fixture-library", "--set", str(SAMPLE), "--out-dir", str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    s = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))["summary"]
    assert s["answer"]["wrong"] >= 2 and s["wrong_but_confident"]["count"] == 3  # the stand-in sounded sure about all three
    assert s["wrong_but_confident"]["unflagged"] == 0  # but VIDHI showed every claim as unchecked, so none reached the lawyer looking verified


def test_live_mode_prints_the_plan_and_spends_nothing_without_the_go_ahead(tmp_path):
    r = run_script("--live", "--set", str(SAMPLE), "--db", "vidhi_never_used", "--label", "plan", "--out-dir", str(tmp_path), env_extra={"MONGO_URL": os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"), "DB_NAME": "vidhi_never_used"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PLAN: 3 cases, about 3 model calls" in r.stdout and "cap 100 rupees" in r.stdout and "Nothing was run and nothing was spent" in r.stdout
    assert list(tmp_path.iterdir()) == []  # no report: nothing ran
    no_db = run_script("--live", "--set", str(SAMPLE))
    assert no_db.returncode == 2 and "--db is required" in no_db.stdout


# ---------- found by the offline stand-in: a changed key figure, and an answer that says the opposite ----------
def test_a_number_word_and_its_digits_are_the_same_figure():
    assert ls.figures("within thirty days") == ls.figures("within 30 days") == {"30"}
    assert ls.figures("Rs 5,00,000") == {"500000"} and ls.figures("five lakh") == {"5", "100000"}


def test_a_key_figure_the_lawyer_listed_must_be_in_the_answer_or_the_answer_is_wrong():
    case = {**CASE, "must_contain": ["thirty", "lender"]}
    assert ls.score_case(case, result("The borrower returns it to the lender within 30 days."), True)["answer"]["state"] == "right"  # 30 is thirty
    wrong = ls.score_case(case, result("The borrower returns it to the lender within ninety days."), True)
    assert wrong["answer"]["state"] == "wrong" and "key figure" in wrong["answer"]["reason"]


def test_an_answer_with_the_same_words_but_a_not_added_or_removed_is_wrong():
    case = {**CASE, "correct_answer": "No. A lender shall not charge any fee for the return of a widget.", "must_contain": []}
    flipped = ls.score_case(case, result("No. A lender shall charge any fee for the return of a widget."), True)
    assert flipped["answer"]["state"] == "wrong" and "opposite" in flipped["answer"]["reason"] and flipped["wrong_confident"] is True
    assert ls.score_case(case, result("No. A lender shall not charge any fee for the return of a widget."), True)["answer"]["state"] == "right"


def test_a_right_answer_in_different_words_is_not_called_the_opposite_for_a_missing_not():
    case = {**CASE, "correct_answer": "A lender shall not charge any fee for the return of a widget."}
    s = ls.score_case(case, result("A lender must return it free of cost."), True)
    assert "opposite" not in s["answer"]["reason"]  # low word overlap: judged on the words, never as 'the opposite'
    assert s["answer"]["state"] in ("partly", "wrong") and s["wrong_confident"] is (s["answer"]["state"] == "wrong")


# ---------- each language against English ----------
def _row(i, lang, right=True):
    return {"id": i, "language": lang, "question": "q", "expect": "answer", "answer": {"state": "right" if right else "wrong", "reason": ""},
            "citation": {"state": "right" if right else "wrong", "verified": False, "reason": ""}, "claims": [{"verdict": "right_unchecked" if right else "wrong_hedged", "label": "x", "text": "t"}],
            "abstain": {"should": False, "did": False, "ok": None, "over_cautious": False}, "wrong_confident": False, "unflagged": False, "library_has_source": True}


def test_a_language_far_below_english_is_called_worse():
    from evals import lawyer_set as ls
    rows = [_row(f"e{i}", "en") for i in range(10)] + [_row(f"h{i}", "hi", right=i < 5) for i in range(10)]
    r = ls.by_language(rows)["languages"]["hi"]
    assert r["worse_than_english"] and "answer right: 50% vs 100% in English" in r["worse_than_english"]


def test_too_few_cases_are_not_compared():
    from evals import lawyer_set as ls
    rows = [_row(f"e{i}", "en") for i in range(10)] + [_row(f"t{i}", "te", right=False) for i in range(3)]
    r = ls.by_language(rows)["languages"]["te"]
    assert r["worse_than_english"] == [] and "too few" in r["note"]


def test_no_english_baseline_says_so_and_report_has_the_section():
    from evals import lawyer_set as ls
    rows = [_row(f"t{i}", "ta") for i in range(12)]
    assert "no English baseline" in ls.by_language(rows)["languages"]["ta"]["note"]
    assert "## Each language against English" in ls.render_report(rows, {"date": "d", "mode": "m"})
    assert "## Each language against English" not in ls.render_report([_row("e1", "en")], {"date": "d", "mode": "m"})
