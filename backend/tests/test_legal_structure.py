"""Statute structure parser and chunker, on INVENTED text (tests/legal_fixtures.py). Provisos, explanations, illustrations and exceptions must stay with their rule."""

from lib import legal_structure as ls
from tests.legal_fixtures import FICTIONAL_PENAL_ACT


def parsed():
    return ls.parse_provisions(FICTIONAL_PENAL_ACT)


def by_number(result, n):
    return next(p for p in result["provisions"] if p["number"] == n)


def kinds(p):
    return [c["kind"] for c in p["components"]]


def test_every_section_is_found_in_order_with_its_heading_chapter_and_page():
    r = parsed()
    assert [p["number"] for p in r["provisions"]] == ["1", "2", "3", "3A", "4", "Schedule First"]
    assert by_number(r, "3")["heading"] == "Hoarding tokens"
    assert by_number(r, "3")["chapter"] == "CHAPTER II OFFENCES ABOUT TOKENS" and by_number(r, "1")["chapter"] == "CHAPTER I PRELIMINARY"
    assert by_number(r, "1")["page_start"] == 1 and by_number(r, "3")["page_start"] == 2 and by_number(r, "Schedule First")["page_start"] == 3
    assert r["warnings"] == []


def test_a_proviso_written_in_the_same_paragraph_becomes_its_own_component_attached_to_the_rule():
    p = by_number(parsed(), "3")
    assert kinds(p) == ["rule", "proviso", "illustration", "exception"]
    assert p["components"][0]["text"].startswith("Whoever hoards more than one hundred tokens") and "Provided" not in p["components"][0]["text"]
    assert p["components"][1]["text"].startswith("Provided that nothing in this section applies to a trader")
    assert p["components"][3]["text"].startswith("Exception")


def test_separate_provisos_explanations_subsections_and_clauses_keep_their_labels():
    r = parsed()
    assert kinds(by_number(r, "3A")) == ["rule", "proviso", "proviso"]
    two = by_number(r, "2")
    assert kinds(two) == ["rule", "clause", "clause", "explanation", "explanation"]
    assert [c["label"] for c in two["components"] if c["kind"] in ("clause", "explanation")] == ["(a)", "(b)", "Explanation 1", "Explanation 2"]
    four = by_number(r, "4")
    assert kinds(four) == ["subsection", "subsection", "clause", "clause"]  # a section written only as numbered subsections has no separate opening rule
    assert [c["label"] for c in four["components"]] == ["(1)", "(2)", "(a)", "(b)"]


def test_the_exact_original_text_is_kept_and_a_schedule_is_a_separate_record():
    r = parsed()
    s3 = by_number(r, "3")
    assert s3["text_full"].startswith("3. Hoarding tokens.—Whoever hoards") and "Provided that nothing in this section applies" in s3["text_full"]
    assert "Exception.—This section does not apply to tokens held in trust" in s3["text_full"]
    sched = by_number(r, "Schedule First")
    assert sched["kind"] == "schedule" and "Form B. A square token." in sched["text_full"]
    assert "Form A" not in by_number(r, "4")["text_full"]  # the schedule did not leak into the last section


def test_numbered_lines_inside_a_section_do_not_start_a_new_section():
    pages = ["1. Short title.—This Act applies as follows.\n2. Definitions.—In this Act the following are defined.\n1. a numbered list item that goes backwards\n3. Offence.—Whoever acts shall be fined."]
    r = ls.parse_provisions(pages)
    assert [p["number"] for p in r["provisions"]] == ["1", "2", "3"]
    assert "a numbered list item that goes backwards" in by_number(r, "2")["text_full"]


def test_trouble_is_reported_not_guessed():
    r = ls.parse_provisions(["Some preface text that is not a section.\n\n1. Title.—Text here.\n1. Title again.—Duplicate number."])
    assert any("before the first section" in w for w in r["warnings"])
    assert any("appears 2 times" in w for w in r["warnings"])


def test_chunks_cover_every_component_exactly_once_and_know_their_parent():
    p = by_number(parsed(), "4")
    chunks = ls.make_chunks(p, max_chars=60)
    covered = [i for c in chunks for i in range(c["component_range"][0], c["component_range"][1] + 1)]
    assert sorted(set(covered)) == list(range(len(p["components"]))) and len(chunks) > 1
    assert all(c["header"].startswith("CHAPTER II OFFENCES ABOUT TOKENS > 4. Counterfeiting tokens") for c in chunks)
    assert [c["ordinal"] for c in chunks] == list(range(len(chunks)))
    one = ls.make_chunks(p, max_chars=5000)
    assert len(one) == 1 and one[0]["component_range"] == [0, len(p["components"]) - 1]


def test_a_very_long_single_component_is_split_at_sentence_ends_without_losing_text():
    sentence = "The accused shall appear before the court on the day fixed."
    long_rule = " ".join([sentence] * 30)
    p = {"number": "9", "heading": "Long", "part": None, "chapter": None, "components": [{"kind": "rule", "label": "", "text": long_rule}, {"kind": "proviso", "label": "", "text": "Provided that this is short."}]}
    chunks = ls.make_chunks(p, max_chars=200)
    assert " ".join(c["text"] for c in chunks if c["component_range"] == [0, 0]).split() == long_rule.split()
    assert any(c["component_range"] == [1, 1] and c["text"].startswith("Provided") for c in chunks)


def test_the_parent_view_always_carries_every_limit_and_flags_partial_use():
    p = by_number(parsed(), "3")
    view = ls.render_parent(p)
    assert [c["kind"] for c in view["components"]] == ["rule", "proviso", "illustration", "exception"]
    assert [c["kind"] for c in view["limits"]] == ["proviso", "exception"] and view["complete"] is True
    assert ls.render_parent(p, included=[0])["complete"] is False  # a caller that used only the rule is detected
    assert ls.render_parent(p, included=[0, 1, 2, 3])["complete"] is True
