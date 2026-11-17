"""The legal-data layer through the real API, on INVENTED statutes (tests/legal_fixtures.py): ingestion, structure, exact and full-text lookup, version choice by date,
review, the hand-off to the library, and code mappings that never infer equivalence."""

import os
import random
import re
import string

import pytest

from tests.conftest import mongo
from tests.legal_fixtures import FICTIONAL_PENAL_ACT, FICTIONAL_PENAL_ACT_RESTATED
from tests.test_admin import admin  # noqa: F401  (fixture)

LIBRARY_PENDING = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "legal_library", "pending")


def tag() -> str:
    return "".join(random.choices(string.ascii_uppercase, k=5))


def source(admin_c, **over):
    body = {"name": "Invented official gazette", "publisher": "Imaginary Government Press", "access_method": "manual-supplied", **over}
    r = admin_c.post("/admin/legal/sources", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def document(admin_c, src, pages, title="Invented Act text"):
    r = admin_c.post("/admin/legal/documents", json={"source_id": src["id"], "title": title, "source_page_url": "https://example.invalid/act", "pages": pages})
    assert r.status_code == 201, r.text
    return r.json()


def ingest(admin_c, doc, title, short, label="original", **dates):
    r = admin_c.post("/admin/legal/ingest", json={"document_id": doc["id"], "instrument": {"title": title, "short_names": [short], "year": 1901}, "version_label": label, **dates})
    assert r.status_code == 201, r.text
    return r.json()


def load(admin_c, pages=FICTIONAL_PENAL_ACT, name=None, **dates):
    t = tag()
    title = name or f"Fictional Penal Act {t}"
    short = f"F{t}"
    src = source(admin_c)
    doc = document(admin_c, src, pages)
    out = ingest(admin_c, doc, title, short, **dates)
    return {"title": title, "short": short, "src": src, "doc": doc, "out": out}


def find(c, number, title, **params):
    r = c.get("/legal/search", params={"q": f"Section {number} of the {title}", **params})
    assert r.status_code == 200, r.text
    return r.json()


def prov_id(c, number, title):
    return find(c, number, title)["exact"][0]["provisions"][0]["id"]


# ---- who may load and review ----

ADMIN_ROUTES = [("post", "/admin/legal/sources", {"name": "xx", "publisher": "yy", "access_method": "manual-supplied"}), ("get", "/admin/legal/sources", None),
                ("post", "/admin/legal/ingest", {}), ("post", "/admin/legal/provisions/x/review", {}), ("post", "/admin/legal/mappings", {}), ("get", "/admin/legal/provisions/x/library-entry", None)]


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_only_the_operator_can_load_or_review_legal_text(user_a, anon, method, path, body):
    # the guard answers an ordinary user exactly as it answers for any other admin page; a handler-level "not found" would look different
    expected = user_a.get("/admin/overview")
    r = getattr(user_a, method)(path, **({"json": body} if body is not None else {}))
    assert r.status_code == expected.status_code == 404 and r.json() == expected.json()
    assert getattr(anon, method)(path, **({"json": body} if body is not None else {})).status_code in (401, 403)


def test_every_legal_admin_route_the_api_exposes_is_closed_to_ordinary_users(user_a):
    """Walks the route table: any /api/admin/legal path must refuse an ordinary user the same way as /admin/overview."""
    from server import app

    expected = user_a.get("/admin/overview")
    paths = [(p, m) for p, ops in app.openapi()["paths"].items() if p.startswith("/api/admin/legal") for m in ops if m in ("get", "post", "put", "patch", "delete")]
    assert len(paths) >= 8
    for template, method in paths:
        path = re.sub(r"\{[^}]+\}", "x", template.removeprefix("/api"))  # any path parameter (changed 2026-11-03: new routes use {entry_id} and {document_id} too)
        r = user_a.request(method.upper(), path, json={} if method != "get" else None)
        assert r.status_code == 404 and r.json() == expected.json(), f"{method.upper()} {template} was reachable by an ordinary user"


# ---- sources, documents, ingestion ----

def test_a_source_records_whether_its_terms_were_read_and_rejects_unknown_access_methods(admin):  # noqa: F811
    assert source(admin)["status"] == "terms-not-read"
    assert source(admin, terms_checked_on="2026-10-20", licence_note="Reuse allowed with attribution (invented)")["status"] == "terms-recorded"
    assert admin.post("/admin/legal/sources", json={"name": "xx", "publisher": "yy", "access_method": "scrape-everything"}).status_code == 422
    assert admin.post("/admin/legal/sources", json={"name": "xx", "publisher": "yy", "access_method": "api", "terms_checked_on": "yesterday"}).status_code == 422


def test_registering_the_same_document_twice_returns_the_first_and_the_hash_is_recorded(admin):  # noqa: F811
    src = source(admin)
    first = document(admin, src, FICTIONAL_PENAL_ACT)
    again = admin.post("/admin/legal/documents", json={"source_id": src["id"], "title": "Same again", "pages": FICTIONAL_PENAL_ACT}).json()
    assert first["duplicate"] is False and again["duplicate"] is True and again["id"] == first["id"] and len(first["sha256"]) == 64
    assert admin.post("/admin/legal/documents", json={"source_id": "nope", "title": "x" * 3, "pages": ["text"]}).status_code == 422


def test_ingestion_stores_unreviewed_provisions_and_reports_what_it_found(admin):  # noqa: F811
    t = load(admin)
    assert t["out"]["created"] is True and t["out"]["provisions"] == 6 and t["out"]["warnings"] == []
    rows = list(mongo().provisions.find({"instrument_version_id": t["out"]["version_id"]}))
    assert {r["review_status"] for r in rows} == {"unreviewed"} and all(r["reviewed_by"] is None for r in rows) and all(r["content_sha256"] for r in rows)
    assert mongo().provision_chunks.count_documents({"parent_id": {"$in": [r["id"] for r in rows]}}) >= 6
    again = ingest(admin, t["doc"], t["title"], t["short"])
    assert again["created"] is False and again["version_id"] == t["out"]["version_id"] and mongo().provisions.count_documents({"instrument_version_id": t["out"]["version_id"]}) == 6


def test_a_date_of_effect_is_stored_only_with_its_evidence(admin):  # noqa: F811
    src = source(admin)
    doc = document(admin, src, FICTIONAL_PENAL_ACT)
    base = {"document_id": doc["id"], "instrument": {"title": f"Fictional Penal Act {tag()}", "short_names": []}, "version_label": "original"}
    no_evidence = admin.post("/admin/legal/ingest", json={**base, "effective_from": "1901-01-01"})
    assert no_evidence.status_code == 422 and "evidence" in no_evidence.json()["detail"]
    assert admin.post("/admin/legal/ingest", json={**base, "effective_from": "1901-13-45", "evidence": "Invented notification No 1 of 1901"}).status_code == 422
    assert admin.post("/admin/legal/ingest", json={**base, "version_label": "perhaps"}).status_code == 422
    ok = admin.post("/admin/legal/ingest", json={**base, "effective_from": "1901-01-01", "evidence": "Invented notification No 1 of 1901"})
    assert ok.status_code == 201
    row = mongo().instrument_versions.find_one({"id": ok.json()["version_id"]})
    assert row["effective_from"] == "1901-01-01" and "Invented notification" in row["evidence"]
    undated = ingest(admin, document(admin, source(admin), FICTIONAL_PENAL_ACT_RESTATED), f"Fictional Justice Code {tag()}", "FJC")
    assert mongo().instrument_versions.find_one({"id": undated["version_id"]})["effective_from"] is None  # unknown stays unknown


def test_text_with_no_sections_is_refused_not_stored_as_an_empty_act(admin):  # noqa: F811
    src = source(admin)
    doc = document(admin, src, ["This page has prose but no numbered sections at all."])
    r = admin.post("/admin/legal/ingest", json={"document_id": doc["id"], "instrument": {"title": f"Fictional Empty Act {tag()}"}, "version_label": "original"})
    assert r.status_code == 422 and "No sections" in r.json()["detail"]


def test_uploading_a_file_stores_it_encrypted_and_reads_its_text(admin):  # noqa: F811
    src = source(admin)
    text = "\f".join(FICTIONAL_PENAL_ACT).replace("\f", "\n\n").encode("utf-8")
    r = admin.post("/admin/legal/documents/upload", data={"source_id": src["id"], "title": "Uploaded invented Act"}, files={"file": ("act.txt", text)})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["duplicate"] is False and len(d["sha256"]) == 64 and d["has_stored_file"] is True and "pages" not in d and mongo().legal_documents.find_one({"id": d["id"]})["stored_file_id"] is not None
    again = admin.post("/admin/legal/documents/upload", data={"source_id": src["id"], "title": "Uploaded invented Act"}, files={"file": ("act.txt", text)}).json()
    assert again["duplicate"] is True and again["id"] == d["id"]
    assert admin.post("/admin/legal/documents/upload", data={"source_id": src["id"], "title": "Empty"}, files={"file": ("e.txt", b"   ")}).status_code in (400, 422)


# ---- finding provisions ----

def test_an_exact_citation_returns_the_whole_provision_with_every_limit_and_says_it_is_unreviewed(admin, user_a):  # noqa: F811
    t = load(admin)
    r = find(user_a, "3", t["title"])
    assert len(r["exact"]) == 1 and r["exact"][0]["instrument"] == t["title"]
    p = r["exact"][0]["provisions"][0]
    assert [c["kind"] for c in p["components"]] == ["rule", "proviso", "illustration", "exception"] and [c["kind"] for c in p["limits"]] == ["proviso", "exception"]
    assert p["complete"] is True and p["text"].startswith("3. Hoarding tokens.—Whoever hoards") and p["page_start"] == 2 and p["heading"] == "Hoarding tokens"
    assert p["review"]["status"] == "unreviewed" and "Do not rely on it as verified law" in p["review"]["statement"]
    assert p["source"]["sha256"] == t["doc"]["sha256"] and p["source"]["name"] == "Invented official gazette" and p["version"]["note"] == "effective dates not recorded"
    assert "verified" not in str(p["review"]["status"]).lower().replace("unreviewed", "")


def test_citation_styles_and_short_names_find_the_same_provision(admin, user_a):  # noqa: F811
    t = load(admin)
    want = find(user_a, "3A", t["title"])["exact"][0]["provisions"][0]["id"]
    for q in (f"s. 3A {t['short']}", f"3A {t['short']}", f"sec 3a of {t['title']}", f"What does section 3A of the {t['title']} say?"):
        got = user_a.get("/legal/search", params={"q": q}).json()["exact"]
        assert got and got[0]["provisions"][0]["id"] == want, q
    assert user_a.get("/legal/search", params={"q": f"Section 3A of the Some Other Act {tag()}"}).json()["exact"] == []
    assert user_a.get("/legal/search", params={"q": f"Section 99 of the {t['title']}"}).json()["exact"] == []


def test_full_text_search_finds_text_without_a_citation(admin, user_a):  # noqa: F811
    # The shared test database holds many copies of the same fictional text, and a text search returns only the best 10 of equal scores: give this Act's text one word of its own
    # so the search can find THIS Act. (Changed 2026-11-03: the test failed whenever enough other tests had loaded the same fictional Act.)
    word = f"zqlamps{tag().lower()}"
    t = load(admin, pages=[p.replace("festival of lamps", f"festival of lamps {word}") for p in FICTIONAL_PENAL_ACT])
    r = user_a.get("/legal/search", params={"q": f"hoards tokens festival of lamps {word}"}).json()
    assert any(p["instrument"] == t["title"] for p in r["text"] + [x for e in r["exact"] for x in e["provisions"]])
    assert user_a.get("/legal/search", params={"q": ""}).json() == {"query": "", "exact": [], "text": [], "review_notice": r["review_notice"]}


def test_the_version_is_chosen_by_date_only_from_recorded_dates_and_never_guessed(admin, user_a):  # noqa: F811
    t = tag()
    title = f"Fictional Penal Act {t}"
    src = source(admin)
    old = ingest(admin, document(admin, src, FICTIONAL_PENAL_ACT, "original"), title, f"F{t}", effective_from="1901-01-01", effective_to="2030-01-01", evidence="Invented commencement notice 1901")
    new = ingest(admin, document(admin, src, FICTIONAL_PENAL_ACT_RESTATED, "restated"), title, f"F{t}", label="amendment", effective_from="2030-01-01", evidence="Invented commencement notice 2030")
    assert old["instrument_id"] == new["instrument_id"] and old["version_id"] != new["version_id"]
    assert len(find(user_a, "3", title)["exact"][0]["provisions"]) == 2  # no date: both shown
    assert find(user_a, "3", title)["exact"][0]["version_note"] and "none was chosen" in find(user_a, "3", title)["exact"][0]["version_note"]
    early = find(user_a, "3", title, on="1950-06-01")["exact"][0]
    assert len(early["provisions"]) == 1 and "one hundred tokens" in early["provisions"][0]["text"] and early["version_note"] is None
    late = find(user_a, "3", title, on="2031-01-01")["exact"][0]
    assert len(late["provisions"]) == 1 and "two hundred tokens" in late["provisions"][0]["text"]
    outside = find(user_a, "3", title, on="1800-01-01")["exact"][0]
    assert len(outside["provisions"]) == 2 and "none was chosen" in outside["version_note"]
    assert user_a.get("/legal/search", params={"q": "x", "on": "not-a-date"}).status_code == 422


def test_a_historical_version_stays_readable_after_a_newer_one_is_loaded(admin, user_a):  # noqa: F811
    t = load(admin)
    before = find(user_a, "3", t["title"])["exact"][0]["provisions"][0]["text"]
    ingest(admin, document(admin, source(admin), FICTIONAL_PENAL_ACT_RESTATED), t["title"], t["short"], label="amendment")
    texts = [p["text"] for p in find(user_a, "3", t["title"])["exact"][0]["provisions"]]
    assert before in texts and len(texts) == 2


# ---- review and the hand-off to the library ----

def test_review_needs_a_name_and_date_and_an_unchanged_text_and_never_creates_a_verified_claim(admin, user_a):  # noqa: F811
    t = load(admin)
    pid = prov_id(user_a, "3", t["title"])
    before = sorted(os.listdir(LIBRARY_PENDING))
    assert admin.post(f"/admin/legal/provisions/{pid}/review", json={"reviewed_by": "Adv", "on": "2026-10-20"}).status_code == 422
    assert admin.post(f"/admin/legal/provisions/{pid}/review", json={"reviewed_by": "Adv Invented Reviewer", "on": "soon"}).status_code == 422
    mongo().provisions.update_one({"id": pid}, {"$set": {"text_full": "3. Tampered text."}})
    bad = admin.post(f"/admin/legal/provisions/{pid}/review", json={"reviewed_by": "Adv Invented Reviewer", "on": "2026-10-20"})
    assert bad.status_code == 422 and "no longer matches" in bad.json()["detail"]
    other = prov_id(user_a, "3A", t["title"])
    ok = admin.post(f"/admin/legal/provisions/{other}/review", json={"reviewed_by": "Adv Invented Reviewer", "on": "2026-10-20"})
    assert ok.status_code == 200 and ok.json()["review_status"] == "reviewed"
    view = user_a.get(f"/legal/provisions/{other}").json()
    assert view["review"]["status"] == "reviewed" and "Adv Invented Reviewer" in view["review"]["statement"]
    assert sorted(os.listdir(LIBRARY_PENDING)) == before  # nothing was written into the library folders


def test_the_library_draft_is_always_marked_unverified_and_carries_the_exact_text_and_source(admin, user_a):  # noqa: F811
    t = load(admin)
    pid = prov_id(user_a, "4", t["title"])
    entry = admin.get(f"/admin/legal/provisions/{pid}/library-entry").json()
    assert "UNVERIFIED - pending lawyer review" in entry["status"] and entry["reviewer"] is None and entry["reviewed_on"] is None
    assert entry["citation"] == f"Section 4, {t['title']}" and entry["kind"] == "STATUTE_SECTION" and entry["jurisdiction"] == "IN"
    assert entry["text"].startswith("4. Counterfeiting tokens.") and "verified_by" not in entry and "text_sha256" not in entry
    assert "effective date not recorded" in entry["version"] and entry["source_name"].startswith("Invented official gazette")
    from lib.library import validate_pending

    assert validate_pending(entry) == []  # it is a valid pending draft, and a pending draft can never verify a claim


# ---- mappings ----

def pair(admin_c, user_c):
    old = load(admin_c)
    new = load(admin_c, pages=FICTIONAL_PENAL_ACT_RESTATED, name=f"Fictional Justice Code {tag()}")
    return old, new, prov_id(user_c, "3", old["title"]), prov_id(user_c, "3", new["title"])


def mapping(admin_c, legacy, new, **over):
    body = {"relationship": "modified", "legacy_provision_ids": [legacy], "new_provision_ids": [new], "differences_in_effect": "The threshold rises from one hundred to two hundred tokens and the fine doubles.",
            "authorities": ["Invented comparison table"], **over}
    return admin_c.post("/admin/legal/mappings", json=body)


def test_a_mapping_is_unreviewed_until_a_named_reviewer_and_both_texts_still_match(admin, user_a):  # noqa: F811
    old, new, lp, np_ = pair(admin, user_a)
    r = mapping(admin, lp, np_, commencement={"date": "2030-01-01", "evidence": "Invented notification 7 of 2030"}, transitional_and_saving=[{"note": "Invented saving clause: pending cases continue under the older Act."}])
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["verified"] is False and m["review_status"] == "unreviewed" and m["legacy"][0]["number"] == "3" and "text" not in m["legacy"][0] and m["commencement"]["date"] == "2030-01-01"
    before = user_a.get("/legal/mappings", params={"number": "3", "instrument": old["title"]}).json()
    assert before["verified_mappings"] == [] and len(before["mappings"]) == 1 and "No verified mapping" in before["message"]
    assert admin.post(f"/admin/legal/mappings/{m['id']}/review", json={"reviewed_by": "Adv", "on": "2026-10-20"}).status_code == 422
    mongo().code_mappings.update_one({"id": m["id"]}, {"$set": {"legacy.0.text_sha256": "0" * 64}})
    assert admin.post(f"/admin/legal/mappings/{m['id']}/review", json={"reviewed_by": "Adv Invented Reviewer", "on": "2026-10-20"}).status_code == 422
    mongo().code_mappings.update_one({"id": m["id"]}, {"$set": {"legacy.0.text_sha256": mongo().provisions.find_one({"id": lp})["content_sha256"]}})
    ok = admin.post(f"/admin/legal/mappings/{m['id']}/review", json={"reviewed_by": "Adv Invented Reviewer", "on": "2026-10-20"})
    assert ok.status_code == 200 and ok.json()["verified"] is True and ok.json()["reviewed_by"] == "Adv Invented Reviewer"


def test_lookups_work_in_both_directions_and_never_substitute_one_text_for_the_other(admin, user_a):  # noqa: F811
    old, new, lp, np_ = pair(admin, user_a)
    m = mapping(admin, lp, np_).json()
    admin.post(f"/admin/legal/mappings/{m['id']}/review", json={"reviewed_by": "Adv Invented Reviewer", "on": "2026-10-20"})
    fwd = user_a.get("/legal/mappings", params={"number": "3", "instrument": old["title"], "offence_date": "2029-05-05"}).json()
    rev = user_a.get("/legal/mappings", params={"number": "3", "instrument": new["title"]}).json()
    for r in (fwd, rev):
        assert len(r["verified_mappings"]) == 1 and r["verified_mappings"][0]["id"] == m["id"] and r["auto_substitution"] is False
        assert "has not decided which text applies" in r["caveat"] and "message" not in r
        assert len(r["found"]) == 1 and len(r["found"][0]["provisions"]) == 1
    assert "2029-05-05" in fwd["offence_date_note"] and "has applied none of it" in fwd["offence_date_note"] and "offence_date_note" not in rev
    assert fwd["found"][0]["instrument"] == old["title"] and rev["found"][0]["instrument"] == new["title"]  # each side still shows its own text, not the other's


def test_matching_numbers_or_headings_never_create_a_mapping(admin, user_a):  # noqa: F811
    old, new, lp, np_ = pair(admin, user_a)
    mapping(admin, lp, np_)
    for n in ("1", "2"):  # same numbers and the same headings exist in both texts, but nobody mapped them
        r = user_a.get("/legal/mappings", params={"number": n, "instrument": old["title"]}).json()
        assert r["mappings"] == [] and r["verified_mappings"] == [] and "No verified mapping" in r["message"]
    assert user_a.get("/legal/mappings", params={"number": "77", "instrument": old["title"]}).json()["found"] == []


def test_mapping_rules_reject_impossible_combinations(admin, user_a):  # noqa: F811
    old, new, lp, np_ = pair(admin, user_a)
    lp2, np2 = prov_id(user_a, "2", old["title"]), prov_id(user_a, "2", new["title"])
    assert mapping(admin, lp, np_, relationship="mystery").status_code == 422
    assert mapping(admin, lp, np_, relationship="absent").status_code == 422  # 'absent' cannot name a newer provision
    assert mapping(admin, lp, np_, new_provision_ids=[]).status_code == 422 and mapping(admin, lp, None, new_provision_ids=[], relationship="modified").status_code == 422
    assert mapping(admin, lp, np_, relationship="merged").status_code == 422 and mapping(admin, lp, np_, relationship="split").status_code == 422
    assert mapping(admin, lp, np_, relationship="one-to-one", legacy_provision_ids=[lp, lp2]).status_code == 422
    assert mapping(admin, lp, lp2).status_code == 422  # both sides in the same instrument
    assert mapping(admin, lp, np_, differences_in_effect="short").status_code == 422
    assert mapping(admin, lp, np_, commencement={"date": "2030-01-01", "evidence": ""}).status_code == 422
    assert mapping(admin, "no-such-id", np_).status_code == 422
    assert mapping(admin, lp, None, relationship="absent", new_provision_ids=[]).status_code == 201
    assert mapping(admin, lp2, None, relationship="unresolved", new_provision_ids=[]).status_code == 201
    assert mapping(admin, lp, np2, relationship="split", new_provision_ids=[np_, np2]).status_code == 201
    assert mapping(admin, lp, np_, relationship="merged", legacy_provision_ids=[lp, lp2]).status_code == 201


# ---- coverage ----

def test_coverage_is_counted_from_the_database_and_never_claims_completeness(admin, user_a):  # noqa: F811
    t = load(admin)
    admin.post(f"/admin/legal/provisions/{prov_id(user_a, '3', t['title'])}/review", json={"reviewed_by": "Adv Invented Reviewer", "on": "2026-10-20"})
    c = user_a.get("/legal/coverage").json()
    mine = next(i for i in c["per_instrument"] if i["instrument"] == t["title"])
    assert mine == {"instrument": t["title"], "versions": 1, "provisions": 6, "reviewed": 1, "versions_with_parser_warnings": 0, "versions_without_effective_date": 1}
    assert c["provisions"] >= 6 and c["provisions_reviewed"] >= 1 and c["sources_terms_not_read"] >= 1
    assert "do not mean the platform covers every Act" in c["meaning"]
    assert user_a.get("/legal/coverage").status_code == 200


# ---- citations written in other scripts ----

def test_section_words_and_digits_in_indian_scripts_find_the_provision(admin, user_a):  # noqa: F811
    t = tag()
    title = f"Fictional Penal Act {t}"
    src = source(admin)
    r = admin.post("/admin/legal/ingest", json={"document_id": document(admin, src, FICTIONAL_PENAL_ACT)["id"], "instrument": {"title": title, "short_names": [f"F{t}", "दंड अधिनियम", "శిక్షా చట్టం"]}, "version_label": "original"})
    assert r.status_code == 201
    want = prov_id(user_a, "3A", title)
    for q in (f"धारा ३A F{t}", f"सेक्शन 3A F{t}", f"సెక్షన్ 3A F{t}", f"కలం 3A F{t}".replace("కలం", "సెక్షన్"), "धारा 3A दंड अधिनियम", "సెక్షన్ 3A శిక్షా చట్టం", f"பிரிவு 3A F{t}", f"કલમ 3A F{t}", f"कलम ३A F{t}"):
        got = user_a.get("/legal/search", params={"q": q}).json()["exact"]
        assert got and got[0]["provisions"][0]["id"] == want, q
    assert user_a.get("/legal/search", params={"q": "धारा 3A अज्ञात अधिनियम"}).json()["exact"] == []  # an unknown Act name finds nothing


# ---- drafts into the structured store (fictional text only) ----
def _drafts(act_id, rows, commencement=""):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    docs = [{"id": f"{act_id}-{i}", "act_id": act_id, "act_title": "Fictional Draft Act", "citation": f"Section {n}, Fictional Draft Act", "heading": h, "text": t, "seq": i,
             "source_url": "https://example.invalid/draft", "status": "UNVERIFIED - pending lawyer review", "synced_at": now, "commencement": commencement, "legal_currency": "Current law"} for i, (n, h, t) in enumerate(rows)]
    mongo().legal_source_candidates.insert_many(docs)


def test_draft_sections_become_structured_unreviewed_provisions_with_provisos_attached(admin):
    act = f"fdraft-{tag().lower()}"
    _drafts(act, [("1", "Short title", "This Act may be called the Fictional Draft Act."),
                  ("2", "Hoarding", "Whoever hoards tokens shall be fined.\nProvided that the fine shall not exceed two units.\nExplanation.\u2014A token is a counter."),
                  ("2A", "Extra rule", "Another rule applies here.")])
    src = source(admin)
    title = f"Fictional Draft Act {tag()}"
    r = admin.post("/admin/legal/import-drafts", json={"act_id": act, "source_id": src["id"], "instrument": {"title": title, "short_names": ["FDA"], "year": 1902}})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["provisions"] == 3 and out["drafts"] == 3 and out["warnings"] == []
    got = find(admin, "2", title)["exact"][0]["provisions"][0]
    assert got["review"]["status"] == "unreviewed" and got["complete"] is True
    kinds = [c["kind"] for c in got["components"]]
    assert "proviso" in kinds and "explanation" in kinds  # they stayed attached to the rule
    assert "hoards tokens" in got["text"]


def test_importing_drafts_is_refused_while_the_source_needs_permission_that_is_not_recorded(admin):
    act = f"fdraft-{tag().lower()}"
    _drafts(act, [("1", "Short title", "This Act may be called the Fictional Draft Act.")])
    src = source(admin, name="India Code (fictional copy)", publisher="Legislative Department")
    r = admin.post("/admin/legal/import-drafts", json={"act_id": act, "source_id": src["id"], "instrument": {"title": f"Fictional Draft Act {tag()}", "short_names": ["FDA"], "year": 1902}})
    assert r.status_code == 422 and "written permission" in r.text
    assert admin.post("/admin/legal/import-drafts", json={"act_id": "no-such-act", "source_id": src["id"], "instrument": {"title": "X Act", "short_names": ["X"], "year": 1902}}).status_code == 422


def test_research_shows_the_whole_provision_with_its_proviso_and_marks_it_not_reviewed(admin, user_a):
    from tests.conftest import answer, new_matter, stub, upload

    act = f"fdraft-{tag().lower()}"
    word = f"zqtoken{tag().lower()}"
    _drafts(act, [("7", "Hoarding", f"Whoever hoards {word} shall be fined.\nProvided that the fine shall not exceed two units.")])
    src = source(admin)
    title = f"Fictional Hoarding Act {tag()}"
    assert admin.post("/admin/legal/import-drafts", json={"act_id": act, "source_id": src["id"], "instrument": {"title": title, "short_names": ["FHA"], "year": 1903}}).status_code == 201
    mid, mtitle = new_matter(user_a)
    upload(user_a, mid, "01-note.txt", "A note about the flat lease.")
    stub("research", answer("Not enough information.", []), contains=mtitle)
    got = user_a.post("/research", json={"question": word, "matter_id": mid, "mode": "MATTER"}).json()
    hit = [d for d in got["draft_law"] if d.get("structured") and word in d["excerpt"]]
    assert hit and hit[0]["status"] == "UNVERIFIED - pending lawyer review" and "proviso" in hit[0]["components"] and hit[0]["citation"].startswith("Section 7, ")
    full = user_a.get(f"/library/drafts/{hit[0]['id']}")
    assert full.status_code == 200 and "Provided that the fine" in full.json()["text"]  # the proviso is part of what is shown
    assert user_a.get(f"/library/{hit[0]['id']}").status_code == 404  # still not served as verified law


def test_draft_rebuild_writes_a_clean_first_line_and_keeps_the_drafts_own_words():
    from lib import legal_store

    wrapped = {"citation": "Section 44, Fictional Act", "heading": "Right of defence against assault when there is risk to an innocent \nperson", "text": "44. Right of defence against assault when there is risk to an innocent \nperson .—If in the exercise of the right A fires.\nProvided that this is fictional."}
    plain = {"citation": "Section 5A, Fictional Act", "heading": "No dash heading", "text": "5A. (1) This text has no dash heading."}
    pages, left_out = legal_store.draft_pages([wrapped, plain, {"citation": "Schedule, Fictional Act", "text": "x"}])
    assert left_out == ["Schedule, Fictional Act"]
    assert pages[0].startswith("44. Right of defence against assault when there is risk to an innocent person.—If in the exercise of the right A fires.\nProvided that this is fictional.")
    assert "5A. No dash heading.—(1) This text has no dash heading." in pages[0]
    assert legal_store.draft_rest(wrapped, "44") == "If in the exercise of the right A fires.\nProvided that this is fictional."


def test_each_draft_is_parsed_on_its_own_and_no_words_are_lost():
    from lib import legal_store, textmatch

    ok = {"citation": "Section 3, Fictional Act", "heading": "Hoarding", "text": "3. Hoarding.—Whoever hoards tokens shall be fined.\nProvided that the fine shall not exceed two units.\nCHAPTER IV \nOF OTHER MATTERS"}
    footnotes = {"citation": "Section 4, Fictional Act", "heading": "Counterfeit", "text": "4. Counterfeit.—Whoever makes a false token shall be fined.\n2. Subs. by Act 3 of 2001, s. 2.\n9. Another heading.—text that belongs to a later part."}
    marginal = {"citation": "Section 5, Fictional Act", "heading": "", "text": "5.—Possession of false tokens .—Whoever possesses a false token shall be fined."}
    res = legal_store.parse_drafts([ok, footnotes, marginal, {"citation": "Schedule, Fictional Act", "text": "x"}])
    assert res["left_out"] == ["Schedule, Fictional Act"] and [p["number"] for p in res["provisions"]] == ["3", "4", "5"]
    three, four, five = res["provisions"]
    assert [c["kind"] for c in three["components"]] == ["rule", "proviso"] and "OTHER MATTERS" not in three["text_full"]  # a chapter heading left at the end is cut
    assert "Subs. by Act 3 of 2001" in four["text_full"] and "later part" in four["text_full"]  # footnotes and following text are kept, not dropped
    assert len(four["components"]) == 1 and any("kept whole" in w for w in res["warnings"])
    assert five["heading"] == "Possession of false tokens" and "possesses a false token" in five["text_full"]
    for d, p in ((footnotes, four), (marginal, five)):  # every word of the draft is in the provision
        assert textmatch.norm(legal_store.draft_rest(d, p["number"])) in textmatch.norm(p["text_full"])


def test_structured_provisions_carry_the_acts_dates_from_the_manifest_and_research_checks_them(admin, user_a):
    from tests.conftest import answer, new_matter, stub, upload

    act = f"fdraft-{tag().lower()}"
    word = f"zqdated{tag().lower()}"
    _drafts(act, [("7", "Hoarding", f"7. Hoarding.—Whoever hoards {word} shall be fined.")], commencement="In force from 01-07-2024 (S.O. 850(E))")
    src = source(admin)
    r = admin.post("/admin/legal/import-drafts", json={"act_id": act, "source_id": src["id"], "instrument": {"title": f"Fictional Dated Act {tag()}", "short_names": ["FDT"], "year": 1904}})
    assert r.status_code == 201, r.text
    inst = mongo().instruments.find_one({"id": r.json()["instrument_id"]})
    assert inst["act_in_force_from"] == "2024-07-01" and inst["act_in_force_until"] is None and "S.O. 850(E)" in inst["commencement_text"]
    mid, mtitle = new_matter(user_a)
    upload(user_a, mid, "01-note.txt", "A note about the flat lease.")
    for when, expected in (("12 March 2023", "NOT_YET_IN_FORCE"), ("5 August 2025", "IN_FORCE")):
        stub("research", answer("Not enough information.", []), contains=mtitle)
        got = user_a.post("/research", json={"question": f"{word} on {when}", "matter_id": mid, "mode": "MATTER"}).json()
        hit = [d for d in got["draft_law"] if d.get("structured") and word in d["excerpt"]]
        assert hit and hit[0]["in_force_on_date"] == expected and hit[0]["commencement"].startswith("In force from 01-07-2024") and hit[0]["status"] == "UNVERIFIED - pending lawyer review"


def test_mapping_table_rows_are_loaded_unreviewed_through_the_same_checks_and_nothing_is_guessed(admin, user_a):  # noqa: F811
    old, new, _, _ = pair(admin, user_a)
    rows = [
        {"legacy": "3", "new": "3", "relationship": "modified", "equivalence": "partial", "differences_in_effect": "The threshold rises from one hundred to two hundred tokens (invented).", "authority": "Invented comparison table, page 2"},
        {"legacy": "4", "new": "", "relationship": "absent", "differences_in_effect": "No corresponding provision in the newer code (invented)."},
        {"legacy": "99", "new": "3", "relationship": "modified", "differences_in_effect": "Names a section that is not loaded (invented).", "authority": "Invented comparison table"},
        {"legacy": "3A", "new": "3", "relationship": "modified", "equivalence": "exact", "differences_in_effect": "A modified provision cannot be called exact (invented).", "authority": "Invented comparison table"},
    ]
    r = admin.post("/admin/legal/mappings/import", json={"legacy_instrument": old["title"], "new_instrument": new["title"], "rows": rows})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["created"] == 2 and out["skipped_as_already_recorded"] == 0 and [f["row"] for f in out["failed"]] == [3, 4]
    assert "not loaded" in out["failed"][0]["error"] and "exact" in out["failed"][1]["error"]
    stored = [mongo().code_mappings.find_one({"id": i}) for i in out["ids"]]
    assert all(m["review_status"] == "unreviewed" and m["reviewed_by"] is None for m in stored)  # nothing counts as verified
    assert next(m for m in stored if m["relationship"] == "modified")["authorities"] == ["Invented comparison table, page 2"]
    again = admin.post("/admin/legal/mappings/import", json={"legacy_instrument": old["title"], "new_instrument": new["title"], "rows": rows[:2]}).json()
    assert again["created"] == 0 and again["skipped_as_already_recorded"] == 2  # loading the same table twice does not duplicate
    unknown = admin.post("/admin/legal/mappings/import", json={"legacy_instrument": "No such Act", "new_instrument": new["title"], "rows": rows[:1]}).json()
    assert unknown["created"] == 0 and "No loaded instrument" in unknown["failed"][0]["error"]  # reported per row, nothing is created or guessed
