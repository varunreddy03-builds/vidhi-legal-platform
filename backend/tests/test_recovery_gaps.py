"""Gaps found by the independent review of Legal Recovery: the email says when listed enclosures are not attached, and deleting a case says that the lawyer-handoff matter is kept."""

import uuid

from routers.recovery_mail import _enclosure_note
from tests.conftest import CLEAN_NOTICE, make_case, outbox
from tests.test_recovery_stage2 import prepare, send

LISTED = CLEAN_NOTICE + "\n\nEnclosures\n  1. Invoice 118 dated 2 August 2026\n  2. Delivery challan 77"
NONE = CLEAN_NOTICE + "\n\nEnclosures\n  No documents are enclosed with this notice."


def test_the_note_appears_only_when_documents_are_listed_as_enclosed():
    assert "not attached" in _enclosure_note(LISTED)
    assert _enclosure_note(NONE) == "" and _enclosure_note(CLEAN_NOTICE) == ""
    assert _enclosure_note("The Enclosures of the contract were signed.\n  1. a") == ""  # the word alone, not the list heading, is not enough


def test_an_email_that_lists_enclosures_says_they_are_not_attached(verified_a):
    cid = make_case(verified_a, LISTED)
    to = f"cust-{uuid.uuid4().hex[:8]}@example.com"
    assert send(verified_a, cid, to).status_code == 200
    mails = outbox(to)
    assert mails and "not attached" in mails[0]["html"]
    own = outbox(verified_a.user["email"], subject_has="Copy:")
    assert own and "not attached to the email sent to them" in own[-1]["html"] and "send them separately" in own[-1]["html"]


def test_an_email_with_no_enclosures_adds_nothing(verified_a):
    cid = make_case(verified_a, NONE)
    to = f"cust-{uuid.uuid4().hex[:8]}@example.com"
    assert send(verified_a, cid, to).status_code == 200
    assert "not attached" not in outbox(to)[0]["html"]


def test_deleting_a_case_keeps_the_handoff_matter_and_says_so(user_a):
    cid = make_case(user_a)
    matter = user_a.post(f"/recovery/cases/{cid}/handoff").json()
    r = user_a.delete(f"/recovery/cases/{cid}")
    assert r.status_code == 200 and r.json() == {"ok": True, "linked_matter_kept": matter["id"]}
    assert user_a.get(f"/matters/{matter['id']}").status_code == 200  # a lawyer may already have worked in it: never deleted behind their back


def test_deleting_a_case_that_was_never_handed_over_reports_nothing_kept(user_a):
    cid = make_case(user_a)
    assert user_a.delete(f"/recovery/cases/{cid}").json() == {"ok": True, "linked_matter_kept": None}
