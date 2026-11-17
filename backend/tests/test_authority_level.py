"""A verified library entry's authority comes from what it is. Before, every entry (a case included) was labelled PRIMARY, which would have read as binding law."""

import pytest

from lib.library import CASE_NOTE, authority_for


@pytest.mark.parametrize("kind", ["STATUTE_SECTION", "RULE"])
def test_legislation_is_primary_and_needs_no_note(kind):
    assert authority_for(kind) == ("PRIMARY", "")


def test_a_decision_is_not_called_primary_and_says_why():
    level, note = authority_for("CASE")
    assert level == "UNKNOWN" and note == CASE_NOTE
    assert "which court decided it" in note and "good law" in note and "A lawyer must check" in note


@pytest.mark.parametrize("kind", ["OTHER", "", "something-new"])
def test_anything_unclassified_is_not_given_authority(kind):
    level, note = authority_for(kind)
    assert level == "UNKNOWN" and "not classified" in note
