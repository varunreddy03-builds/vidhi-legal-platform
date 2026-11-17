"""Fixes from the backend code review of 2026-10-23 (docs/reviews/code-review-backend-2026-10-23.md). Everything here is invented text and pure functions (no server needed)."""

import pytest

from lib import analysis, legal_reasoning
from lib.analysis_guard import clean_text

HIT = {"work": "Meditations", "authors": "Marcus Aurelius", "kind": "book", "excerpt": "You have power over your mind, not outside events. Realise this, and you will find strength.", "work_coverage": "full"}


def phil(view, hits=(HIT,)):
    return analysis.finish({"question": "q", "viewpoints": [view], "confidence": "high"}, list(hits), "", "philosophy")


def test_a_quotation_with_no_cited_source_is_never_direct_text():
    out = phil({"author": "Marcus Aurelius", "work": "Meditations", "position": "p", "basis": "direct_text", "quote": "You have power over your mind, not outside events", "sources": []})
    v = out["viewpoints"][0]
    assert v["basis"] == "interpretation" and v["quote"] == "" and out["quotes_removed"] == 1 and "not checked" in v["attribution"]


def test_a_real_quotation_credited_to_the_wrong_author_is_not_shown():
    out = phil({"author": "Nietzsche", "work": "Zarathustra", "position": "p", "basis": "direct_text", "quote": "You have power over your mind, not outside events", "sources": ["S1"]})
    v = out["viewpoints"][0]
    assert v["basis"] == "interpretation" and v["quote"] == "" and "does not match" in v["attribution"]


def test_a_correctly_attributed_quotation_with_its_source_is_direct_text():
    out = phil({"author": "Marcus Aurelius", "work": "Meditations", "position": "p", "basis": "direct_text", "quote": "You have power over your mind, not outside events", "sources": ["S1"]})
    v = out["viewpoints"][0]
    assert v["basis"] == "direct_text" and v["quote"].startswith("You have power") and out["quotes_removed"] == 0


def test_a_quotation_that_the_wording_rules_would_rewrite_is_not_shown_as_verbatim():
    hit = {**HIT, "excerpt": "The witness lied about the contract and nobody should trust him at all."}
    out = phil({"author": "Marcus Aurelius", "work": "Meditations", "position": "p", "basis": "direct_text", "quote": "The witness lied about the contract and nobody should trust him", "sources": ["S1"]}, (hit,))
    v = out["viewpoints"][0]
    assert v["basis"] == "interpretation" and v["quote"] == "" and "changed by VIDHI" in v["attribution"]


def test_every_analysis_kind_removes_an_unverified_legal_time_limit_and_says_so():
    for kind in ("strategy", "reasoning", "behaviour"):
        out = analysis.finish({"summary": "Settle first. File the notice within 30 days.", "options": [{"idea": "Appeal within 90 days.", "sources": [], "risks": []}]}, [], "", kind)
        assert "within 30 days" not in out["summary"] and "within 90 days" not in out["options"][0]["idea"], kind
        assert out["deadline_note"] and any(f["rule"] == "legal_deadline" for f in out["removed_by_vidhi"]) and out["confidence"] == "low"
    out = phil({"author": "Plato", "work": "Republic", "position": "A suit must be filed within three years.", "basis": "interpretation", "sources": []}, ())
    assert "three years" not in out["viewpoints"][0]["position"] and out["deadline_note"]


def test_legal_reasoning_without_a_library_entry_removes_a_time_limit_but_with_one_leaves_it_to_the_cited_text():
    reply = {"issue": "Notice.", "arguments": [{"side": "for", "point": "The complaint must be filed within 30 days.", "library_ids": []}], "uncertainty": ["Appeal within 90 days."], "confidence": "high"}
    out = legal_reasoning.finish(reply, [], "IN")
    assert "within 30 days" not in out["arguments"][0]["point"] and out["deadline_note"]


@pytest.mark.parametrize("reply", [
    {"issue": "x", "arguments": [{"side": "for", "point": 5, "library_ids": 1}], "uncertainty": 7, "confidence": "low"},
    {"issue": "x", "arguments": [{"side": "for", "point": "p", "library_ids": [{"a": 1}, 2, "L9"]}], "facts_given": [{"b": 2}], "confidence": "low"},
    {"issue": 5, "arguments": "none", "confidence": "low"},
])
def test_legal_reasoning_survives_a_reply_of_an_unexpected_shape(reply):
    out = legal_reasoning.finish(reply, [], "IN")
    assert isinstance(out["arguments"], list) and out["verification"]["status"] == "UNSUPPORTED"


@pytest.mark.parametrize("sentence", [
    "Priya's husband is a psychopath.", "The respondent is a narcissist.", "My boss seems narcissistic.", "She is clearly trying to cheat you.", "He plans to deceive you.",
    "There is a 3-in-4 chance they will settle.", "There is a seventy percent chance they will settle.", "Nobody doubts that this approach always works.", "No one can deny it never fails.", "This guarantees success.",
])
def test_phrasings_the_review_showed_the_guard_missing_are_now_removed(sentence):
    assert clean_text(sentence)[1], sentence


@pytest.mark.parametrize("sentence", [
    "Interest is 12% per annum.", "Courts guarantee a fair hearing.", "No method can guarantee a result.", "It does not always work.", "Under the contract the fee is 5% of the invoice.",
])
def test_ordinary_sentences_the_review_showed_the_guard_removing_are_now_kept(sentence):
    assert clean_text(sentence) == (sentence, [])
