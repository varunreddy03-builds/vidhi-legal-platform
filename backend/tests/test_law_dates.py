"""Date-aware law: a date is read only from the manifest's own words, and an unknown date stays unknown."""

from datetime import date

from lib import law_dates as D
from lib import library


def test_the_manifests_own_wording_is_read_into_start_and_end_dates():
    bns = D.validity("In force from 01-07-2024 (S.O. 850(E), 23-02-2024), except s.106(2)")
    assert bns["from"] == date(2024, 7, 1) and bns["to"] is None
    ipc = D.validity("REPEALED by BNS (Act 45 of 2023) w.e.f. 01-07-2024")
    assert ipc["to"] == date(2024, 7, 1) and ipc["from"] is None  # "45 of 2023" is an Act number, not a date
    assert D.validity("2016-10-08")["from"] == date(2016, 10, 8)
    assert D.validity("In force from 1 January 1909")["from"] == date(1909, 1, 1)


def test_an_unstated_date_is_unknown_and_is_never_guessed():
    for text in ("not stated in the manifest", "", "In force, see Gazette"):
        v = D.validity(text)
        assert v["from"] is None and v["to"] is None and D.status_on(v, date(2020, 1, 1)) == "UNKNOWN"
    assert D.status_on(D.validity("REPEALED by BNS w.e.f. 01-07-2024"), date(2020, 1, 1)) == "UNKNOWN"  # repeal date known, start not: not claimed as in force


def test_the_same_law_is_checked_against_the_date_asked_about():
    bns, ipc = D.validity("In force from 01-07-2024"), D.validity("REPEALED by BNS w.e.f. 01-07-2024")
    assert D.status_on(bns, date(2023, 3, 12)) == "NOT_YET_IN_FORCE" and D.status_on(bns, date(2025, 1, 1)) == "IN_FORCE"
    assert D.status_on(ipc, date(2025, 1, 1)) == "REPEALED"


def test_dates_are_found_in_a_question_in_common_forms():
    got = D.question_dates("The cheque bounced on 12 March 2023 and notice was sent 15/03/2023; hearing 2024-02-01.")
    assert date(2023, 3, 12) in got and date(2023, 3, 15) in got and date(2024, 2, 1) in got


def test_draft_views_carry_only_stated_dates_and_the_date_check_never_verifies():
    d = {"id": "x", "citation": "c", "commencement": "In force from 01-07-2024", "legal_currency": "Current law"}
    v = library.draft_view(d)
    assert v["in_force_from"] == "2024-07-01" and v["in_force_until"] is None and v["status"] == library.PENDING_STATUS
    out = library.with_date_check([v], date(2023, 3, 12))[0]
    assert out["in_force_on_date"] == "NOT_YET_IN_FORCE" and out["status"] == library.PENDING_STATUS and "official manifest" in out["date_note"]
    unknown = library.with_date_check([library.draft_view({"id": "y", "citation": "c", "commencement": "not stated in the manifest"})], date(2023, 3, 12))[0]
    assert unknown["in_force_on_date"] == "UNKNOWN"


def test_research_adds_the_date_check_to_draft_law_when_the_question_names_a_date(user_a):
    from tests.conftest import answer, new_matter, stub, upload

    mid, title = new_matter(user_a)
    upload(user_a, mid, "01-note.txt", "A note about the flat lease.")
    stub("research", answer("Not enough information.", []), contains=title)
    q = "What does the gadget labelled provision say for something that happened on 12 March 2023?"
    got = user_a.post("/research", json={"question": q, "matter_id": mid, "mode": "MATTER"}).json()
    hit = [d for d in got["draft_law"] if d["id"] == "test-pending-act"]
    assert hit and hit[0]["checked_on"] == "2023-03-12" and hit[0]["in_force_on_date"] == "UNKNOWN" and hit[0]["status"] == library.PENDING_STATUS  # the test Act states no dates
    stub("research", answer("Not enough information.", []), contains=title)
    plain = user_a.post("/research", json={"question": "What does the gadget labelled provision say?", "matter_id": mid, "mode": "MATTER"}).json()
    assert all("checked_on" not in d for d in plain["draft_law"])


# ---- Acts whose manifest row gives no date: what the Act's own section 1 says -------------------------------------------------------------------------
def _entries(text, year="1959", heading="Short title, extent and commencement."):
    return [{"act_id": "x", "act_title": f"The Fictional Act, {year}", "citation": f"Section 1, The Fictional Act, {year}", "heading": heading, "text": text}]


def test_the_acts_own_commencement_sentence_is_classified_and_never_guessed():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import law_commencement as C

    assert C.classify(_entries("1. (1) This Act may be called the Fictional Act, 1959. (3) It shall come into force at once."))["basis"] == "AT_ONCE"
    assert C.classify(_entries("1. (3) It shall come into force on such date as the Government may, by notification, appoint."))["basis"] == "NOTIFICATION"
    assert C.classify(_entries("1. (3) It shall come into force on such dates as the Government may appoint."))["basis"] == "NOTIFICATION"
    explicit = C.classify(_entries("1. (3) All the provisions of this Act shall be deemed to have come into force on the 14th January, 1984."))
    assert explicit["basis"] == "EXPLICIT_DATE" and explicit["date"] == "1984-01-14"
    assert C.classify(_entries("1. (3) Section 12 shall come into force at once and the remaining sections shall be deemed to have come into force on the 28th April, 1997."))["basis"] == "PARTIAL"
    assert C.classify(_entries("2. The Nodal Department shall scrutinize the schemes.", heading="Scrutiny"))["basis"] == "NO_CLAUSE"
    # a date that is not the start date is not taken as one
    odd = C.classify(_entries("1. (3) It shall be deemed to have come into force on the third November, 1958 in areas which, immediately before the 1st November, 1956, were part of the State."))
    assert odd["basis"] != "EXPLICIT_DATE" or odd["date"] != "1956-11-01"


def test_an_act_that_started_at_once_is_in_force_after_its_year_and_the_rest_stay_unknown(monkeypatch):
    monkeypatch.setattr(D, "_sidecar", lambda: {"a-1959": {"basis": "AT_ONCE", "year": 1959}, "n-1998": {"basis": "NOTIFICATION", "year": 1998}, "e": {"basis": "EXPLICIT_DATE", "date": "1984-01-14", "year": 1984}})
    at_once = D.validity("not stated in the manifest", "", "a-1959")
    assert D.status_on(at_once, date(2020, 5, 1)) == "IN_FORCE" and D.status_on(at_once, date(1950, 5, 1)) == "NOT_YET_IN_FORCE" and D.status_on(at_once, date(1959, 6, 1)) == "UNKNOWN"
    notified = D.validity("not stated in the manifest", "", "n-1998")
    assert D.status_on(notified, date(2020, 5, 1)) == "UNKNOWN" and notified["basis"] == "NOTIFICATION"
    assert D.status_on(D.validity("not stated in the manifest", "", "e"), date(1990, 1, 1)) == "IN_FORCE"
    assert D.validity("not stated in the manifest", "", "not-listed")["basis"] is None  # no information: still unknown


def test_the_date_note_says_why_the_date_is_unknown(monkeypatch):
    monkeypatch.setattr(D, "_sidecar", lambda: {"n-1998": {"basis": "NOTIFICATION", "year": 1998}})
    view = library.draft_view({"id": "i", "citation": "c", "act_id": "n-1998", "commencement": "not stated in the manifest", "legal_currency": "Current"})
    out = library.with_date_check([view], date(2020, 5, 1))[0]
    assert out["in_force_on_date"] == "UNKNOWN" and "notification" in out["date_note"] and out["status"] == library.PENDING_STATUS
