"""The drafting-slip checker reads a draft; it knows no court rules, never corrects anything, and says why each finding may not be a slip (pure code, no database, no AI)."""

from lib.defects.check import check


def kinds(pages):
    return [(f.kind, f.raw) for f in check(pages)]


def test_blanks_and_placeholders_are_found_with_a_note_that_some_are_meant_to_be_filled_by_hand():
    text = "The petitioner, _______, resides at [insert address]. Dated [ ]. Amount: Rs. XXXX. Signed ................... and [●] and <<client name>> and TBD."
    found = check([text])
    assert [f.kind for f in found] == ["blank"] * 8  # ____, [insert address], [ ], XXXX, dotted line, [●], <<client name>>, TBD
    assert all("meant to be filled by hand" in f.note for f in found)
    assert [f.raw for f in found][:3] == ["_______", "[insert address]", "[ ]"]


def test_each_blank_is_reported_once_even_when_two_patterns_match_it():
    assert len(check(["Name: [_____]."])) == 1


def test_paragraph_numbers_that_skip_or_repeat_are_pointed_out_and_restarts_are_not():
    text = "1. First point.\n2. Second point.\n4. Fourth point.\n4. Again four.\n5. Fifth.\n1. A new section starts again.\n2. Its second."
    assert kinds([text]) == [("numbering_gap", "2 → 4"), ("numbering_repeat", "4")]
    gap = check([text])[0]
    assert "3 may be missing" in gap.note and "different list on purpose" in gap.note


def test_a_longer_jump_names_the_range():
    [f] = check(["1. One.\n2. Two.\n7. Seven."])
    assert "3 to 6 may be missing" in f.note


def test_an_annexure_series_with_a_label_missing_is_pointed_out():
    text = "See Annexure P-1 and Annexure P-2. Later, Annexure P-4 is relied on. Also Annexure R-1."
    found = [(f.kind, f.raw) for f in check([text])]
    assert found == [("annexure_gap", "Annexure P-3")]
    assert "may be mentioned in another document" in check([text])[0].note


def test_a_reference_to_a_paragraph_that_is_not_there_is_pointed_out_but_not_when_it_is_about_another_document():
    text = "1. First.\n2. Second.\n3. Third.\nAs stated in paragraph 2 and paragraph 9, the facts are clear. See also paragraph 24 of the judgment."
    assert kinds([text]) == [("dangling_reference", "paragraph 9")]
    assert "highest numbered paragraph found is 3" in check([text])[0].note


def test_paragraph_references_are_not_judged_when_the_draft_does_not_number_its_paragraphs():
    assert check(["As stated in paragraph 40, the facts are clear."]) == []


def test_a_word_typed_twice_is_pointed_out_but_correct_repeats_are_not():
    found = kinds(["The the petitioner states that that was so. He had had enough."])
    assert found == [("repeated_word", "The the")]


def test_each_finding_keeps_its_page_and_sentence_and_nothing_is_corrected():
    pages = ["Nothing wrong here.", "The sum of Rs. _____ was paid on the date mentioned."]
    [f] = check(pages)
    assert f.page == 2 and "sum of Rs." in f.sentence and f.raw == "_____"


def test_an_ordinary_clean_draft_has_no_findings():
    clean = "1. The petitioner filed the suit on 12 March 2021.\n2. The respondent replied.\n3. The matter was heard. See Annexure P-1 and Annexure P-2 and paragraph 2."
    assert check([clean]) == []


def test_hostile_text_cannot_tie_up_the_server():
    import time

    for text in ("the " * 75_000, "Annexure " * 30_000, "_" * 300_000, "[insert " * 30_000):
        t0 = time.perf_counter()
        check([text])
        assert time.perf_counter() - t0 < 8, text[:20]  # was minutes: every finding re-scanned the whole page for its sentence
