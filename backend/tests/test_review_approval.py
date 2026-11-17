"""The reviewer's approval: a NAMED person approves a loaded section and it enters the verified library, written only by lib/library.py. Invented statutes only. Nothing is ever approved by the code."""

import pytest

from tests.conftest import mongo
from tests.test_admin import admin  # noqa: F401  (fixture)
from tests.test_legal_data import load, prov_id

NAME = "Adv Invented Reviewer"
DAY = "2026-11-03"


def approve(admin_c, pid, name=NAME, on=DAY, **extra):
    return admin_c.post(f"/admin/legal/provisions/{pid}/approve", json={"reviewed_by": name, "on": on, **extra})


def entry_of(pid):
    return mongo().library_entries.find_one({"provision_id": pid})


MINE: list = []  # provisions THIS worker's current test approved (workers run in parallel: a test must only remove its own library entries)


@pytest.fixture(autouse=True)
def _remove_my_library_entries():
    MINE.clear()
    yield
    mongo().library_entries.delete_many({"provision_id": {"$in": list(MINE)}})


def setup(admin_c, user_c):
    t = load(admin_c)
    pid = prov_id(user_c, "3", t["title"])
    MINE.append(pid)
    return t, pid


ROUTES = [("post", "/admin/legal/provisions/x/approve", {"reviewed_by": NAME, "on": DAY}), ("post", "/admin/legal/provisions/x/withdraw", {"reviewed_by": NAME, "on": DAY, "reason": "Invented reason to withdraw"}),
          ("get", "/admin/legal/library-entries/x/export", None), ("post", "/admin/legal/documents/x/source-url", {"url": "https://example.invalid/act"})]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_only_the_operator_can_approve_withdraw_export_or_set_a_source_address(user_a, user_b, anon, method, path, body):
    expected = user_a.get("/admin/overview")
    for client in (user_a, user_b):  # an ordinary user, and a user of another organisation, are both turned away exactly like any other admin page
        r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == expected.status_code == 404 and r.json() == expected.json()
    assert getattr(anon, method)(path, **({"json": body} if body is not None else {})).status_code in (401, 403)


def test_approval_needs_a_full_name_and_a_real_date_and_changes_nothing_when_refused(admin, user_a):  # noqa: F811
    _, pid = setup(admin, user_a)
    assert approve(admin, pid, name="Adv").status_code == 422
    assert approve(admin, pid, on="not-a-date").status_code == 422
    assert approve(admin, pid, on="").status_code == 422
    assert entry_of(pid) is None and mongo().provisions.find_one({"id": pid})["review_status"] == "unreviewed"


def test_an_approval_enters_the_verified_library_with_reviewer_date_and_hashes_and_is_logged(admin, user_a):  # noqa: F811
    t, pid = setup(admin, user_a)
    assert user_a.get("/library").json()["count"] >= 0 and entry_of(pid) is None  # before: not verified
    r = approve(admin, pid)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["verified"] is True and out["review_status"] == "reviewed" and out["reviewed_by"] == NAME and out["reviewed_on"] == DAY
    e = entry_of(pid)
    prov = mongo().provisions.find_one({"id": pid})
    assert e["status"] == "VERIFIED" and e["verified_by"] == NAME and e["verified_on"] == DAY and e["origin"] == "reviewer_screen"
    assert e["provision_sha256"] == prov["content_sha256"] and e["document_sha256"] and e["text_sha256"] and e["text"] == prov["text_full"].strip()
    listed = {x["id"]: x for x in user_a.get("/library").json()["entries"]}
    assert listed[e["id"]]["verified_by"] == NAME and listed[e["id"]]["verified_on"] == DAY
    logged = mongo().audit_events.find_one({"operation": "LEGAL_LIBRARY_APPROVED", "detail": {"$regex": e["id"][:40]}})
    assert logged and NAME in logged["detail"] and DAY in logged["detail"]
    found = user_a.get("/library/search", params={"q": f"Section 3 of the {t['title']}"}).json()["results"]
    assert found[0]["store"] == "verified_library" and found[0]["status"] == "VERIFIED" and found[0]["verified_by"] == NAME  # and it ranks first in the one search


def test_a_provision_whose_text_changed_since_loading_cannot_be_approved(admin, user_a):  # noqa: F811
    _, pid = setup(admin, user_a)
    mongo().provisions.update_one({"id": pid}, {"$set": {"text_full": "3. Someone edited this text after it was loaded."}})
    r = approve(admin, pid)
    assert r.status_code == 422 and "no longer matches" in r.json()["detail"]
    assert entry_of(pid) is None and mongo().provisions.find_one({"id": pid})["review_status"] == "unreviewed"


def test_a_rejected_provision_stays_unverified_and_cannot_be_approved(admin, user_a):  # noqa: F811
    _, pid = setup(admin, user_a)
    r = admin.post(f"/admin/legal/provisions/{pid}/reject", json={"reviewed_by": NAME, "on": DAY, "reason": "The fine amount differs from the official page."})
    assert r.status_code == 200 and r.json()["review_status"] == "rejected"
    again = approve(admin, pid)
    assert again.status_code == 422 and "rejected" in again.json()["detail"]
    assert entry_of(pid) is None and mongo().provisions.find_one({"id": pid})["review_status"] == "rejected"


def test_a_section_with_no_source_address_is_refused_until_the_operator_records_one(admin, user_a):  # noqa: F811
    t, pid = setup(admin, user_a)
    mongo().legal_documents.update_one({"id": t["doc"]["id"]}, {"$set": {"source_page_url": "", "file_url": ""}})
    r = approve(admin, pid)
    assert r.status_code == 422 and "source address" in r.json()["detail"] and entry_of(pid) is None
    assert admin.post(f"/admin/legal/documents/{t['doc']['id']}/source-url", json={"url": "not a web address"}).status_code == 422
    ok = admin.post(f"/admin/legal/documents/{t['doc']['id']}/source-url", json={"url": "https://example.invalid/the-official-act"})
    assert ok.status_code == 200
    assert approve(admin, pid).status_code == 200 and entry_of(pid)["source_url"] == "https://example.invalid/the-official-act"
    assert mongo().audit_events.find_one({"operation": "LEGAL_DOCUMENT_URL", "detail": {"$regex": "the-official-act"}})


def test_withdrawing_takes_it_out_of_the_verified_library_and_back_to_unreviewed(admin, user_a):  # noqa: F811
    t, pid = setup(admin, user_a)
    assert approve(admin, pid).status_code == 200
    eid = entry_of(pid)["id"]
    assert admin.post(f"/admin/legal/provisions/{pid}/withdraw", json={"reviewed_by": NAME, "on": DAY, "reason": "short"}).status_code == 422
    r = admin.post(f"/admin/legal/provisions/{pid}/withdraw", json={"reviewed_by": NAME, "on": DAY, "reason": "Found a transcription slip on re-reading."})
    assert r.status_code == 200 and r.json()["verified"] is False
    assert mongo().library_entries.find_one({"id": eid})["status"] == "WITHDRAWN" and eid not in {x["id"] for x in user_a.get("/library").json()["entries"]}
    assert mongo().provisions.find_one({"id": pid})["review_status"] == "unreviewed"
    assert not [x for x in user_a.get("/library/search", params={"q": f"Section 3 of the {t['title']}"}).json()["results"] if x["id"] == eid]  # no longer found as verified
    assert mongo().audit_events.find_one({"operation": "LEGAL_LIBRARY_WITHDRAWN", "detail": {"$regex": NAME}})
    assert admin.post(f"/admin/legal/provisions/{pid}/withdraw", json={"reviewed_by": NAME, "on": DAY, "reason": "Withdrawing a second time."}).status_code == 422


def test_an_approved_entry_exports_in_the_library_file_format_and_an_unapproved_one_does_not(admin, user_a):  # noqa: F811
    _, pid = setup(admin, user_a)
    approve(admin, pid)
    eid = entry_of(pid)["id"]
    got = admin.get(f"/admin/legal/library-entries/{eid}/export")
    assert got.status_code == 200 and "attachment" in got.headers["content-disposition"]
    body = got.json()
    from lib import library

    assert library.validate_entry(body) == [] and body["verified_by"] == NAME and body["verified_on"] == DAY and body["id"] == eid  # a committed copy would load as a library file
    assert admin.get("/admin/legal/library-entries/no-such-entry/export").status_code == 404


def test_the_version_listing_says_which_sections_are_in_the_library_and_gives_the_document(admin, user_a):  # noqa: F811
    t, pid = setup(admin, user_a)
    approve(admin, pid)
    vid = t["out"]["version_id"]
    listing = admin.get(f"/admin/legal/versions/{vid}/provisions").json()
    assert listing["document_id"] == t["doc"]["id"]
    by = {p["id"]: p for p in listing["provisions"]}
    assert by[pid]["library_entry_id"] and by[pid]["status"] == "REVIEWED"
    assert all(p["library_entry_id"] is None for p in listing["provisions"] if p["id"] != pid)


def test_an_approved_entry_reads_the_same_in_every_organisation_and_no_user_can_withdraw_it(admin, user_a, user_b):  # noqa: F811
    _, pid = setup(admin, user_a)
    assert approve(admin, pid).status_code == 200
    e = entry_of(pid)
    for client in (user_a, user_b):  # the verified library is shared law text, not one organisation's data: both see the same reviewer, date and status
        seen = {x["id"]: x for x in client.get("/library").json()["entries"]}[e["id"]]
        assert seen["verified_by"] == NAME and seen["verified_on"] == DAY
    for client in (user_a, user_b):
        assert client.post(f"/admin/legal/provisions/{pid}/withdraw", json={"reviewed_by": NAME, "on": DAY, "reason": "Invented reason to withdraw"}).status_code == 404
    assert entry_of(pid)["status"] == "VERIFIED"  # both attempts left it untouched
