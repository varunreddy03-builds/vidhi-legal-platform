"""The law extractor cuts official PDF text into DRAFT entries. It must never produce a verified entry and must not lose or reorder text."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import law_extract as L  # noqa: E402
from lib import library  # noqa: E402

SAMPLE = """CONTENTS
1. Short title
2. Definitions
1. Short title.—This Act may be cited as the Sample Act, 2000.
2. Definitions.—In this Act, unless the context otherwise requires,—
(a) "thing" means a thing;
1. Subs. by Act 3 of 2001, s. 2.
2A. Extra rule.—Another rule applies here.
4. Penalty.—Whoever offends shall be fined.
CHAPTER III
Procedure
"""


def test_split_keeps_each_section_whole_and_in_order():
    secs = L.split(SAMPLE)
    assert [s[0] for s in secs] == ["1", "2", "2A", "4"]  # the contents list and the footnote are not sections
    assert secs[1][2].endswith('(a) "thing" means a thing;\n1. Subs. by Act 3 of 2001, s. 2.')  # text is never edited, only cut
    assert secs[3][2].endswith("fined.")  # the next chapter heading is not part of the last section


def test_footnote_numbers_do_not_start_a_section():
    assert L.split("5. Subs. by Act 2 of 1999, s. 1.—for the words.\n")  == []


def test_extracted_entries_are_drafts_and_the_library_never_treats_them_as_verified():
    e = {"id": "x-1", "citation": "Section 1, X", "kind": "STATUTE_SECTION", "text": "t", "text_sha256": library.sha256_text("t"),
         "source_name": "s", "source_url": "u", "version": "v", "status": "UNVERIFIED - pending lawyer review"}
    assert library.validate_entry(e)  # no reviewer, and marked unverified: rejected as a verified entry
    assert library.validate_pending(e) == []  # accepted only as a draft
