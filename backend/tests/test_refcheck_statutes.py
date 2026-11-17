"""Statute checks against the reviewed library (Stage 2c). Offline: a fake library, invented provisions."""

import asyncio

import pytest

from lib.refcheck import statutes
from lib.refcheck.citations import extract_page


def ref(text):
    refs = [r for r in extract_page(text, 1) if r.kind == "statute"]
    assert len(refs) == 1, refs
    return refs[0]


def prov(reviewed=True, number="138"):
    return {"id": "p1", "number": number, "heading": "Dishonour of cheque", "instrument": "Negotiable Instruments Act, 1881", "version": {"note": "effective dates not recorded"},
            "review": {"status": "reviewed" if reviewed else "unreviewed", "statement": "Compared by A. Reviewer." if reviewed else "Unreviewed."}, "source": {"url": "https://example.test/act.pdf"}}


def library(table):
    async def look(number, hint=None, on_date=None):
        if table is Exception:
            raise RuntimeError("down")
        return table.get(number, [])
    return look


def run(r, table):
    return asyncio.run(statutes.check_statute(r, lookup=library(table)))


def test_a_reviewed_provision_is_found_but_never_called_current():
    res = run(ref("The complaint was filed under Section 138 of the Negotiable Instruments Act, 1881."), {"138": [{"provisions": [prov()]}]})
    assert res.label == statutes.FOUND_REVIEWED and res.current_status == "current status: not checked"
    assert "in force" in res.reason  # the reason says it is NOT checked for being in force


def test_an_unreviewed_provision_is_not_presented_as_verified():
    res = run(ref("See Section 138 of the Negotiable Instruments Act, 1881."), {"138": [{"provisions": [prov(reviewed=False)]}]})
    assert res.label == statutes.FOUND_NOT_REVIEWED


def test_a_provision_we_do_not_hold_is_not_in_reviewed_library_never_wrong():
    res = run(ref("Section 999 of the Negotiable Instruments Act, 1881 applies."), {})
    assert res.label == statutes.NOT_IN_LIBRARY and "says nothing about whether it exists" in res.reason


def test_an_unreadable_library_is_could_not_check_not_missing():
    res = run(ref("Section 138 of the Negotiable Instruments Act, 1881."), Exception)
    assert res.label == statutes.COULD_NOT_CHECK


def test_several_sections_one_missing_makes_the_whole_reference_not_in_library():
    res = run(ref("Sections 138 and 141 of the Negotiable Instruments Act, 1881."), {"138": [{"provisions": [prov()]}]})
    assert res.label == statutes.NOT_IN_LIBRARY
    assert [x["label"] for x in res.per_provision] == [statutes.FOUND_REVIEWED, statutes.NOT_IN_LIBRARY]


@pytest.mark.parametrize("text", ["Section 420 of the Indian Penal Code was invoked.", "Section 154 of the Code of Criminal Procedure was cited.", "Section 65B of the Indian Evidence Act was relied on."])
def test_old_codes_get_a_note_that_never_converts_section_numbers(text):
    res = run(ref(text), {})
    assert res.old_code_note and "does not convert section numbers" in res.old_code_note
    assert not any(ch.isdigit() for ch in res.old_code_note)  # no section number is mapped from memory


def test_new_codes_get_no_old_code_note():
    res = run(ref("Section 318 of the Bharatiya Nyaya Sanhita was invoked."), {})
    assert res.old_code_note == ""


def test_numbers_are_read_without_subsections_or_duplicates():
    assert statutes.numbers("138 and 141") == ["138", "141"]
    assert statutes.numbers("34(1)") == ["34"]
    assert statutes.numbers("302, 304B, 302") == ["302", "304B"]
    assert statutes.numbers("") == []
