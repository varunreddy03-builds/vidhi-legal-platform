"""The CrPC section finder keeps the longest in-order run of section numbers, so a stray number inside a section (a figure, a cross-reference) cannot derail it, and a section whose number cannot be
read is reported as missing, never guessed. Fictional text."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import crpc_extract as c  # noqa: E402


def test_a_stray_number_inside_a_section_does_not_derail_the_run(monkeypatch):
    monkeypatch.setattr(c, "EXPECTED_MAX", 6)
    body = "\n".join([
        "1. (1) First rule words here and more words.",
        "2. (1) Second rule words here and more words.",
        "30. (1) A stray figure at the start of a line inside the second rule.",
        "3. (1) Third rule words here and more words.",
        "4. (1) Fourth rule words here and more words.",
        "6. (1) Sixth rule words here and more words.",
    ])
    starts, missing = c.find_starts(body)
    assert sorted(starts) == [1, 2, 3, 4, 6]
    assert 30 not in starts
    assert missing == [5]  # section 5's number is not in the text: reported, not invented


def test_a_garbled_number_is_found_by_its_neighbours_only_when_it_is_still_readable(monkeypatch):
    monkeypatch.setattr(c, "EXPECTED_MAX", 4)
    body = "1. (1) First rule words here and more words.\n" + "x" * 30 + " 2; (1) Second rule words here after a page break and more words.\n3. (1) Third rule words here and more words.\n4. (1) Fourth rule."
    starts, missing = c.find_starts(body)
    assert 2 in starts and missing == []
