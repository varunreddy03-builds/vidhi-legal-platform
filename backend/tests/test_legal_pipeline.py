"""The law-library pipeline rules, through the real API, on INVENTED statutes (tests/legal_fixtures.py): permission gate, DRAFT/REVIEWED/REJECTED, source address needed for review,
hash mismatch flagged, second-source comparison, review pack, and mappings (cited source needed to be reviewed, disagreements flagged, text picked by date only from a reviewed
mapping with a recorded commencement date). Nothing here is real law."""

import io

from lib import legal_compare
from tests.conftest import mongo
from tests.legal_fixtures import FICTIONAL_PENAL_ACT, FICTIONAL_PENAL_ACT_RESTATED
from tests.test_admin import admin  # noqa: F401  (fixture)
from tests.test_legal_data import document, find, ingest, load, mapping, prov_id, source, tag



# These tests load many copies of the invented Acts into the shared test database. The word "festival" is what the existing full-text test searches for, so these copies leave it out:
# otherwise they would crowd that test's own Act out of the first ten results.
QUIET = [p.replace("festival", "gathering") for p in FICTIONAL_PENAL_ACT]
QUIET_RESTATED = [p.replace("festival", "gathering") for p in FICTIONAL_PENAL_ACT_RESTATED]


def quiet_pair(admin_c, user_c):
    old = load(admin_c, pages=QUIET)
    new = load(admin_c, pages=QUIET_RESTATED, name=f"Fictional Justice Code {tag()}")
    return old, new, prov_id(user_c, "3", old["title"]), prov_id(user_c, "3", new["title"])


def review(admin_c, pid, **over):
    return admin_c.post(f"/admin/legal/provisions/{pid}/review", json={"reviewed_by": "Adv Test Reviewer", "on": "2026-10-20", **over})


# ---- the source's own terms: no written permission recorded, no text ----

def test_text_from_a_source_that_needs_written_permission_cannot_be_loaded_until_it_is_recorded(admin):  # noqa: F811
    src = source(admin, permission_required=True, licence_note="Terms of Use: personal non-commercial use only; no automated access without written permission.")
    assert src["permission_required"] is True and src["permission_reference"] == ""
    r = admin.post("/admin/legal/documents", json={"source_id": src["id"], "title": "An Act", "source_page_url": "https://example.invalid/a", "pages": QUIET})
    assert r.status_code == 422 and "written permission" in r.json()["detail"]
    assert admin.post(f"/admin/legal/sources/{src['id']}/permission", json={"reference": "short"}).status_code == 422
    ok = admin.post(f"/admin/legal/sources/{src['id']}/permission", json={"reference": "Letter of 2026-11-02 from the Legislative Department, kept in the permissions folder"})
    assert ok.status_code == 200 and ok.json()["permission_reference"].startswith("Letter of")
    r2 = admin.post("/admin/legal/documents", json={"source_id": src["id"], "title": "An Act", "source_page_url": "https://example.invalid/a", "pages": QUIET})
    assert r2.status_code == 201


def test_permission_can_also_be_withdrawn_after_loading_so_ingest_stops(admin):  # noqa: F811
    src = source(admin, permission_required=True, permission_reference="Letter of 2026-11-02, Legislative Department")
    doc = document(admin, src, QUIET)
    mongo().legal_sources.update_one({"id": src["id"]}, {"$set": {"permission_reference": ""}})  # as if the permission were withdrawn
    r = admin.post("/admin/legal/ingest", json={"document_id": doc["id"], "instrument": {"title": f"Fictional Penal Act {tag()}", "year": 1901}, "version_label": "original"})
    assert r.status_code == 422 and "written permission" in r.json()["detail"]


def test_coverage_counts_sources_still_waiting_for_permission(admin, user_a):  # noqa: F811
    source(admin, permission_required=True)
    assert user_a.get("/legal/coverage").json()["sources_needing_permission"] >= 1


# ---- DRAFT never verifies; REVIEWED needs a source address; rejected stays out ----

def test_loaded_text_is_draft_and_even_reviewed_text_never_becomes_a_verified_library_entry(admin, user_a):  # noqa: F811
    t = load(admin, pages=QUIET)
    pid = prov_id(user_a, "3", t["title"])
    shown = find(user_a, "3", t["title"])["exact"][0]["provisions"][0]
    assert shown["review"]["label"] == "DRAFT"
    assert review(admin, pid).status_code == 200
    shown = find(user_a, "3", t["title"])["exact"][0]["provisions"][0]
    assert shown["review"]["label"] == "REVIEWED" and shown["review"]["reviewed_by"] == "Adv Test Reviewer"
    # the only thing that can verify a claim is a VERIFIED entry made from the reviewed library files; loaded text, reviewed or not, is never copied there
    assert mongo().legal_sources.count_documents({"text": {"$regex": "hoards more than one hundred tokens"}}) == 0


def test_a_provision_cannot_be_marked_reviewed_when_its_document_has_no_source_address(admin, user_a):  # noqa: F811
    src = source(admin)
    r = admin.post("/admin/legal/documents", json={"source_id": src["id"], "title": "No address Act text", "pages": QUIET})
    assert r.status_code == 201
    title = f"Fictional Penal Act {tag()}"
    ingest(admin, r.json(), title, f"F{tag()}")
    pid = prov_id(user_a, "3", title)
    bad = review(admin, pid)
    assert bad.status_code == 422 and "source address" in bad.json()["detail"]
    mongo().legal_documents.update_one({"id": r.json()["id"]}, {"$set": {"source_page_url": "https://example.invalid/the-act"}})
    assert review(admin, pid).status_code == 200


def test_a_reviewed_provision_whose_source_address_is_lost_is_flagged_by_the_integrity_check(admin, user_a):  # noqa: F811
    t = load(admin, pages=QUIET)
    pid = prov_id(user_a, "3", t["title"])
    assert review(admin, pid).status_code == 200
    assert pid not in [x["provision_id"] for x in admin.get("/admin/legal/integrity").json()["reviewed_without_source_url"]]
    mongo().legal_documents.update_one({"id": t["doc"]["id"]}, {"$set": {"source_page_url": "", "file_url": ""}})
    report = admin.get("/admin/legal/integrity").json()
    assert pid in [x["provision_id"] for x in report["reviewed_without_source_url"]] and report["ok"] is False


def test_a_changed_text_is_flagged_and_cannot_be_reviewed(admin, user_a):  # noqa: F811
    t = load(admin, pages=QUIET)
    pid = prov_id(user_a, "3", t["title"])
    mongo().provisions.update_one({"id": pid}, {"$set": {"text_full": "3. Hoarding tokens.—Whoever hoards more than two hundred tokens shall be punished with a fine."}})
    assert pid in [x["provision_id"] for x in admin.get("/admin/legal/integrity").json()["hash_mismatch"]]
    bad = review(admin, pid)
    assert bad.status_code == 422 and "hash" in bad.json()["detail"]


def test_a_rejected_provision_stays_unreviewed_with_the_reason_and_can_be_approved_later(admin, user_a):  # noqa: F811
    t = load(admin, pages=QUIET)
    pid = prov_id(user_a, "3", t["title"])
    assert admin.post(f"/admin/legal/provisions/{pid}/reject", json={"reviewed_by": "Adv Test Reviewer", "on": "2026-10-20", "reason": "short"}).status_code == 422
    r = admin.post(f"/admin/legal/provisions/{pid}/reject", json={"reviewed_by": "Adv Test Reviewer", "on": "2026-10-20", "reason": "The proviso is missing from the loaded text."})
    assert r.status_code == 200 and r.json()["review_status"] == "rejected"
    shown = find(user_a, "3", t["title"])["exact"][0]["provisions"][0]
    assert shown["review"]["label"] == "REJECTED" and "Do not rely" in shown["review"]["statement"]
    assert review(admin, pid).status_code == 200


# ---- second official source ----

def test_pure_comparison_flags_a_changed_word_a_changed_figure_and_missing_sections():
    a = {"3": "Whoever hoards more than one hundred tokens shall be punished with a fine of Rs 100.", "4": "Whoever makes a false token.", "5": "Only here."}
    b = {"3": "Whoever hoards more than two hundred tokens shall be punished with a fine of Rs 1,000.", "4": "Whoever  MAKES a false token.", "6": "Only there."}
    r = legal_compare.compare_sections(a, b)
    assert r["3"]["status"] == "DIFFERENT" and {d["loaded"] for d in r["3"]["differences"]} >= {"one", "100."} and r["4"]["status"] == "SAME"
    assert r["5"]["status"] == "ONLY_IN_LOADED" and r["6"]["status"] == "ONLY_IN_SECOND"


def test_second_source_must_be_a_different_source_and_differences_are_flagged_for_the_reviewer(admin, user_a):  # noqa: F811
    t = load(admin, pages=QUIET)
    same_source_doc = document(admin, t["src"], QUIET, title="Same source, other copy of the Act")
    version_id = mongo().instrument_versions.find_one({"document_id": t["doc"]["id"]})["id"]
    bad = admin.post("/admin/legal/compare", json={"version_id": version_id, "second_document_id": same_source_doc["id"]})
    assert bad.status_code == 422 and "different source" in bad.json()["detail"]

    changed = [p.replace("one hundred tokens", "two hundred tokens") for p in QUIET]
    other = document(admin, source(admin, name="Second invented gazette"), changed, title="Second source text")
    r = admin.post("/admin/legal/compare", json={"version_id": version_id, "second_document_id": other["id"]})
    assert r.status_code == 200, r.text
    assert "3" in r.json()["different"] and r.json()["counts"]["DIFFERENT"] >= 1 and r.json()["counts"]["SAME"] >= 1

    pid = prov_id(user_a, "3", t["title"])
    shown = find(user_a, "3", t["title"])["exact"][0]["provisions"][0]
    assert shown["review"]["second_source"]["status"] == "DIFFERENT"
    blocked = review(admin, pid)
    assert blocked.status_code == 422 and "second official source" in blocked.json()["detail"]
    assert review(admin, pid, acknowledge_second_source_difference=True).status_code == 200
    same_pid = prov_id(user_a, "1", t["title"])
    assert find(user_a, "1", t["title"])["exact"][0]["provisions"][0]["review"]["second_source"]["status"] == "SAME"
    assert review(admin, same_pid).status_code == 200  # an agreeing second source needs no acknowledgement


# ---- reviewer pack and screen data ----

def test_review_pack_lists_every_section_with_source_hash_and_status_in_word_and_csv(admin, user_a):  # noqa: F811
    t = load(admin, pages=QUIET)
    version_id = mongo().instrument_versions.find_one({"document_id": t["doc"]["id"]})["id"]
    pid = prov_id(user_a, "3", t["title"])
    assert review(admin, pid).status_code == 200
    csv_r = admin.get(f"/admin/legal/review-pack/{version_id}", params={"format": "csv"})
    assert csv_r.status_code == 200 and csv_r.content.startswith(b"\xef\xbb\xbf")
    text = csv_r.content.decode("utf-8-sig")
    assert "https://example.invalid/act" in text and "REVIEWED" in text and "DRAFT" in text and "Hoarding tokens" in text
    only_draft = admin.get(f"/admin/legal/review-pack/{version_id}", params={"format": "csv", "status": "DRAFT"}).content.decode("utf-8-sig")
    assert "REVIEWED" not in only_draft.split("\n", 1)[1]
    d = admin.get(f"/admin/legal/review-pack/{version_id}", params={"format": "docx"})
    assert d.status_code == 200 and d.content[:2] == b"PK"
    from docx import Document

    body = "\n".join(p.text for p in Document(io.BytesIO(d.content)).paragraphs)
    assert "Section 3" in body and "Decision: approve / reject" in body and "Nothing here is legal advice" in body
    assert admin.get("/admin/legal/review-pack/nope").status_code == 404


def test_reviewer_screen_data_lists_versions_and_sections_with_filters(admin, user_a):  # noqa: F811
    t = load(admin, pages=QUIET)
    version_id = mongo().instrument_versions.find_one({"document_id": t["doc"]["id"]})["id"]
    versions = admin.get("/admin/legal/versions").json()
    mine = next(v for v in versions if v["version_id"] == version_id)
    assert mine["act"] == t["title"] and mine["sections"] >= 4 and mine["reviewed"] == 0
    pid = prov_id(user_a, "3", t["title"])
    review(admin, pid)
    got = admin.get(f"/admin/legal/versions/{version_id}/provisions").json()
    assert got["source_url"] == "https://example.invalid/act" and any(p["number"] == "3" and p["status"] == "REVIEWED" for p in got["provisions"])
    drafts = admin.get(f"/admin/legal/versions/{version_id}/provisions", params={"status": "DRAFT"}).json()["provisions"]
    assert drafts and all(p["status"] == "DRAFT" for p in drafts)


def test_only_the_operator_can_use_the_new_review_routes(user_a, anon):
    for method, path, body in [("post", "/admin/legal/compare", {}), ("get", "/admin/legal/integrity", None), ("get", "/admin/legal/versions", None), ("get", "/admin/legal/review-pack/x", None),
                               ("post", "/admin/legal/provisions/x/reject", {}), ("post", "/admin/legal/sources/x/permission", {}), ("get", "/admin/legal/mappings/disagreements", None)]:
        expected = user_a.get("/admin/overview")
        r = getattr(user_a, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == expected.status_code, path
        assert getattr(anon, method)(path, **({"json": body} if body is not None else {})).status_code in (401, 403), path


# ---- mappings: cited source to be reviewed; disagreements; text by date only from a reviewed mapping ----

def test_a_mapping_without_a_cited_official_source_cannot_be_marked_reviewed(admin, user_a):  # noqa: F811
    old, new, lp, np_ = quiet_pair(admin, user_a)
    m = mapping(admin, lp, np_, equivalence="uncertain", authorities=[]).json()
    r = admin.post(f"/admin/legal/mappings/{m['id']}/review", json={"reviewed_by": "Adv Test Reviewer", "on": "2026-10-20"})
    assert r.status_code == 422 and "cites an official source" in r.json()["detail"]
    ok = mapping(admin, lp, np_, authorities=["Invented official comparison table, 2030"]).json()
    assert admin.post(f"/admin/legal/mappings/{ok['id']}/review", json={"reviewed_by": "Adv Test Reviewer", "on": "2026-10-20"}).status_code == 200


def test_two_tables_that_disagree_about_the_same_older_provision_are_flagged(admin, user_a):  # noqa: F811
    old, new, lp, np_ = quiet_pair(admin, user_a)
    np2 = prov_id(user_a, "2", new["title"])
    a = mapping(admin, lp, np_, authorities=["Invented table A"]).json()
    b = mapping(admin, lp, np2, authorities=["Invented table B"]).json()
    flags = admin.get("/admin/legal/mappings/disagreements").json()
    mine = next(f for f in flags if f["legacy_provision_id"] == lp)
    assert {m["id"] for m in mine["mappings"]} == {a["id"], b["id"]} and "none was chosen" in mine["message"]
    shown = user_a.get("/legal/mappings", params={"number": "3", "instrument": old["title"]}).json()
    assert any(f["legacy_provision_id"] == lp for f in shown["disagreements"])


def test_the_text_for_an_event_date_comes_only_from_a_reviewed_mapping_with_a_recorded_commencement_date(admin, user_a):  # noqa: F811
    old, new, lp, np_ = quiet_pair(admin, user_a)
    commencement = {"date": "2030-01-01", "evidence": "Invented notification 7 of 2030"}
    m = mapping(admin, lp, np_, commencement=commencement, transitional_and_saving=[{"note": "Invented saving clause: pending cases continue under the older Act."}]).json()

    def applies(day):
        got = user_a.get("/legal/mappings", params={"number": "3", "instrument": old["title"], "offence_date": day}).json()
        return got["applies_on_event_date"][0]

    draft = applies("2029-06-01")
    assert draft["applies"] == "unknown" and draft["mapping_status"] == "DRAFT" and "DRAFT" in draft["basis"]
    assert admin.post(f"/admin/legal/mappings/{m['id']}/review", json={"reviewed_by": "Adv Test Reviewer", "on": "2026-10-20"}).status_code == 200
    before, on, after = applies("2029-12-31"), applies("2030-01-01"), applies("2031-03-04")
    assert (before["applies"], on["applies"], after["applies"]) == ("older", "newer", "newer")
    assert "2030-01-01" in before["basis"] and "Invented notification" in before["basis"]
    assert before["transitional_and_saving"] == ["Invented saving clause: pending cases continue under the older Act."] and "lawyer" in before["caveat"].lower()
    undated = mapping(admin, lp, np_, authorities=["Invented table C"]).json()
    admin.post(f"/admin/legal/mappings/{undated['id']}/review", json={"reviewed_by": "Adv Test Reviewer", "on": "2026-10-20"})
    got = user_a.get("/legal/mappings", params={"number": "3", "instrument": old["title"], "offence_date": "2030-05-05"}).json()["applies_on_event_date"]
    assert {x["applies"] for x in got if x["mapping_id"] == undated["id"]} == {"unknown"}  # no recorded date: nothing is picked


def test_india_code_always_needs_a_recorded_permission_even_if_the_form_says_otherwise(admin):  # noqa: F811
    for name, publisher in [("India Code portal", "Legislative Department, Ministry of Law and Justice"), ("Acts from indiacode.gov.in", "NIC")]:
        s = source(admin, name=name, publisher=publisher, permission_required=False)
        assert s["permission_required"] is True and s["permission_reference"] == ""
        r = admin.post("/admin/legal/documents", json={"source_id": s["id"], "title": "x act", "source_page_url": "https://example.invalid/x", "pages": QUIET})
        assert r.status_code == 422 and "written permission" in r.json()["detail"]
