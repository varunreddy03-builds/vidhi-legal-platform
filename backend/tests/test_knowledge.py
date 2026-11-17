"""The knowledge library through the real API. All texts are invented fixtures ("TEST FIXTURE"), and every test uses its OWN invented works (unique numbers), so tests running side by side
cannot disturb each other or the real catalogue. Rules under test: a catalogue entry is not content; ingestion needs recorded rights AND written approval; statuses only move forward and
never past 'Registered' without evidence; repeats share one record and the same text is never stored twice; library text is shared, private text is not; search always says where a hit
came from and says plainly when it found nothing."""

import random
import uuid

import pytest

from tests.conftest import mongo
from tests.test_admin import admin  # noqa: F401  (fixture)

BOOK = (
    "TEST FIXTURE ONLY - NOT A REAL BOOK.\n\nChapter 1\n\nThe quillfeather method says a plan should name its quillfeather assumption before it names its goal.\n\n"
    "Chapter 2\n\nA second chapter discusses moonstitch bargaining and how a moonstitch offer changes what the other side believes.\n"
)


def new_work(canonical_of=None, status="Registered", collections=None):
    number = random.randint(10_000, 9_000_000)
    tag = uuid.uuid4().hex[:8]
    mongo().knowledge_works.insert_one({
        "number": number, "id": f"fixture-{tag}", "title": f"Fixture Book {tag}", "authors": "Invented Author", "section": "E", "kind": "book", "status": status, "evidence": "",
        "source_status": "not_located", "rights_status": "not_verified", "rights_hint": "in_copyright", "edition": None, "translator": None, "year": None,
        "canonical_of": canonical_of, "collections": collections or [], "planned_for_phases": [], "rights": None, "coverage": "unknown", "chunks": 0})
    return number, tag


def rights(admin_c, number, permitted=("private_analysis", "full_text_indexing")):
    return admin_c.post(f"/admin/knowledge/works/{number}/rights", json={
        "terms_quote": "TEST FIXTURE licence: private analysis and indexing are permitted.", "permitted": list(permitted), "source_url": "https://example.invalid/licence", "edition": "Fixture edition 1"})


def status(admin_c, number, to, evidence="TEST FIXTURE evidence for this change", approval=""):
    return admin_c.post(f"/admin/knowledge/works/{number}/status", json={"status": to, "evidence": evidence, "approval": approval})


def authorise(admin_c, number):
    assert rights(admin_c, number).status_code == 200
    for step in ("Source located", "Rights not yet verified"):
        assert status(admin_c, number, step).status_code == 200
    r = status(admin_c, number, "Authorized for ingestion", approval="Owner approved in writing on 2026-10-22 (test fixture)")
    assert r.status_code == 200, r.text


def ingest(admin_c, number, text=BOOK, complete=False):
    return admin_c.post(f"/admin/knowledge/works/{number}/text", json={"text": text, "complete": complete})


# ------------------------------------------------------------------ the catalogue
def test_importing_the_registry_adds_the_fifty_once_and_never_resets_a_status(admin):  # noqa: F811
    a = admin.post("/admin/knowledge/import-registry").json()
    assert a["in_registry"] == 50 and a["added"] + a["already_there"] == 50
    assert admin.post("/admin/knowledge/import-registry").json()["added"] == 0
    db = mongo()
    db.knowledge_works.update_one({"number": 50}, {"$set": {"status": "Source located", "evidence": "TEST FIXTURE"}})
    try:
        admin.post("/admin/knowledge/import-registry")
        assert db.knowledge_works.find_one({"number": 50})["status"] == "Source located"
    finally:
        db.knowledge_works.update_one({"number": 50}, {"$set": {"status": "Registered", "evidence": ""}})
    d = admin.get("/admin/knowledge/dashboard").json()
    assert d["works"] >= 50 and d["by_status"]["Registered"] >= 1 and "Ingested" in d["by_status"]


def test_an_ordinary_user_cannot_see_the_admin_routes(user_a):
    for path in ("/admin/knowledge/dashboard", "/admin/knowledge/works"):
        assert user_a.get(path).status_code == 404
    assert user_a.post("/admin/knowledge/import-registry").status_code == 404


# ------------------------------------------------------------------ status and rights rules
def test_a_status_needs_evidence_and_only_moves_forward(admin):  # noqa: F811
    n, _ = new_work()
    assert status(admin, n, "Source located", evidence="short").status_code == 422
    assert status(admin, n, "Source located").status_code == 200
    assert status(admin, n, "Source not yet located").status_code == 422  # backwards
    assert status(admin, n, "Source located").status_code == 422          # not forward
    assert status(admin, n, "Not a status").status_code == 422
    assert status(admin, n, "Unavailable or blocked", evidence="Publisher refused a licence (fixture)").status_code == 200  # blocking is always allowed


def test_authorising_needs_rights_that_allow_indexing_and_a_written_approval(admin):  # noqa: F811
    n, _ = new_work()
    assert status(admin, n, "Authorized for ingestion", approval="Owner approved (fixture)").status_code == 422  # no rights yet
    assert rights(admin, n, permitted=("private_analysis",)).status_code == 200
    assert status(admin, n, "Authorized for ingestion", approval="Owner approved (fixture)").status_code == 422  # rights do not allow indexing
    assert rights(admin, n).status_code == 200
    assert status(admin, n, "Authorized for ingestion").status_code == 422                                      # no written approval
    assert status(admin, n, "Authorized for ingestion", approval="Owner approved in writing (fixture)").status_code == 200


def test_rights_need_the_terms_the_source_and_the_edition(admin):  # noqa: F811
    n, _ = new_work()
    bad = {"terms_quote": "x", "permitted": ["full_text_indexing"], "source_url": "https://example.invalid/a", "edition": "e"}
    assert admin.post(f"/admin/knowledge/works/{n}/rights", json=bad).status_code == 422
    assert admin.post(f"/admin/knowledge/works/{n}/rights", json={**bad, "terms_quote": "A long enough quoted licence sentence.", "permitted": ["anything"]}).status_code == 422
    assert admin.post("/admin/knowledge/works/999999999/rights", json={**bad, "terms_quote": "A long enough quoted licence sentence."}).status_code == 404


def test_ingested_and_indexed_cannot_be_set_by_hand(admin):  # noqa: F811
    n, _ = new_work()
    assert status(admin, n, "Ingested").status_code == 422 and status(admin, n, "Indexed").status_code == 422
    assert status(admin, n, "Retrieval verified").status_code == 422  # nothing was indexed to verify


# ------------------------------------------------------------------ ingestion
def test_nothing_is_stored_for_a_work_that_is_not_authorised(admin):  # noqa: F811
    n, _ = new_work()
    r = ingest(admin, n)
    assert r.status_code == 409 and "not authorised" in r.json()["detail"]
    assert mongo().knowledge_chunks.count_documents({"work_number": n}) == 0
    assert rights(admin, n, permitted=("private_analysis",)).status_code == 200
    assert ingest(admin, n).status_code == 409  # still not authorised, whatever the rights say


def test_ingesting_stores_chunks_with_provenance_and_never_twice(admin):  # noqa: F811
    n, _ = new_work()
    authorise(admin, n)
    first = ingest(admin, n).json()
    assert first["chunks_added"] >= 2 and first["coverage"] == "partial"
    work = mongo().knowledge_works.find_one({"number": n})
    assert work["status"] == "Indexed" and work["chunks"] == first["chunks_total"] and "chunks stored" in work["evidence"]
    chapters = {c["chapter"] for c in mongo().knowledge_chunks.find({"work_number": n})}
    assert {"Chapter 1", "Chapter 2"} <= chapters
    again = ingest(admin, n).json()
    assert again["chunks_added"] == 0 and again["chunks_skipped_as_duplicates"] == first["chunks_added"] and again["chunks_total"] == first["chunks_total"]
    assert ingest(admin, n, complete=True).json()["coverage"] == "full"


def test_a_repeat_entry_shares_one_source_record(admin):  # noqa: F811
    canon, _ = new_work()
    alias, _ = new_work(canonical_of=canon, collections=["machiavelli"])
    authorise(admin, canon)
    out = ingest(admin, alias).json()  # listed twice in the catalogue: the text lands once, on the canonical record
    assert out["work_number"] == canon and out["chunks_added"] >= 2
    assert mongo().knowledge_chunks.count_documents({"work_number": alias}) == 0


# ------------------------------------------------------------------ search
def test_search_returns_provenance_short_excerpts_and_says_when_nothing_matches(admin, user_a, user_b):  # noqa: F811
    n, tag = new_work()
    authorise(admin, n)
    ingest(admin, n)
    for user in (user_a, user_b):  # the library is shared by every organisation
        hits = user.get("/knowledge/search", params={"q": "quillfeather assumption"}).json()["hits"]
        mine = [h for h in hits if h["work"] == f"Fixture Book {tag}"]
        assert mine and mine[0]["chapter"] == "Chapter 1" and mine[0]["chunk_sha256"] and mine[0]["work_coverage"] == "partial" and mine[0]["edition"] == "Fixture edition 1"
        assert len(mine[0]["excerpt"]) <= 503
    nothing = user_a.get("/knowledge/search", params={"q": "zxqvwy" + uuid.uuid4().hex}).json()
    assert nothing["hits"] == [] and "not evidence that no book discusses it" in nothing["note"]
    assert "not law" in user_a.get("/knowledge/search", params={"q": "moonstitch"}).json()["limits"]
    assert user_a.get("/knowledge/search", params={"q": ""}).json()["hits"] == []
    assert user_a.get("/knowledge/search", params={"q": "x", "k": 0}).status_code == 422


def test_text_of_a_work_that_is_not_searchable_is_never_returned(admin, user_a):  # noqa: F811
    n, tag = new_work(status="Source located")
    mongo().knowledge_chunks.insert_one({"id": uuid.uuid4().hex, "work_number": n, "scope": "library", "org_id": None, "sha256": uuid.uuid4().hex, "chapter": "", "ordinal": 0,
                                         "text": f"hiddenfable{tag} appears only in a work nobody authorised"})
    mongo().knowledge_chunks.create_index([("text", "text")], default_language="none", name="knowledge_text")
    assert user_a.get("/knowledge/search", params={"q": f"hiddenfable{tag}"}).json()["hits"] == []


def test_an_excerpt_is_cut_short_and_marked(admin, user_a):  # noqa: F811
    n, tag = new_work()
    authorise(admin, n)
    ingest(admin, n, text=f"TEST FIXTURE ONLY.\n\nlongwordtoken{tag} " + ("filler " * 150))
    hit = [h for h in user_a.get("/knowledge/search", params={"q": f"longwordtoken{tag}"}).json()["hits"] if h["work"] == f"Fixture Book {tag}"][0]
    assert hit["excerpt"].endswith("...") and len(hit["excerpt"]) == 503


# ------------------------------------------------------------------ private documents
def test_private_documents_belong_to_one_organisation(user_a, user_b):
    tag = uuid.uuid4().hex[:8]
    made = user_a.post("/knowledge/private", json={"title": "Our own playbook", "text": f"TEST FIXTURE ONLY. Chapter 1\n\nprivatefable{tag} is our internal term."})
    assert made.status_code == 200, made.text
    number = made.json()["work_number"]
    assert number < 0  # can never collide with the 50 catalogue numbers
    assert [h["scope"] for h in user_a.get("/knowledge/search", params={"q": f"privatefable{tag}"}).json()["hits"]] == ["org"]
    assert user_b.get("/knowledge/search", params={"q": f"privatefable{tag}"}).json()["hits"] == []
    assert [w["title"] for w in user_a.get("/knowledge/private").json()] == ["Our own playbook"] and user_b.get("/knowledge/private").json() == []
    assert user_b.delete(f"/knowledge/private/{number}").status_code == 404  # another organisation cannot delete it
    assert user_a.delete(f"/knowledge/private/{number}").status_code == 200
    assert user_a.get("/knowledge/search", params={"q": f"privatefable{tag}"}).json()["hits"] == []
    assert mongo().knowledge_chunks.count_documents({"work_number": number}) == 0


def test_private_text_is_removed_when_the_organisation_is_erased(user_a, user_b):
    tag = uuid.uuid4().hex[:8]
    number = user_a.post("/knowledge/private", json={"title": "To be erased", "text": f"TEST FIXTURE ONLY. erasablefable{tag}"}).json()["work_number"]
    me = user_a.get("/auth/me").json()
    r = user_a.request("DELETE", "/org", json={"password": user_a.password, "organization_name": me["organization_name"]})
    assert r.status_code == 200, r.text
    assert mongo().knowledge_works.count_documents({"number": number}) == 0 and mongo().knowledge_chunks.count_documents({"work_number": number}) == 0
    assert user_b.get("/knowledge/search", params={"q": f"erasablefable{tag}"}).json()["hits"] == []


def test_a_blank_private_document_is_refused_and_leaves_no_record_behind(user_a):
    before = len(user_a.get("/knowledge/private").json())
    assert user_a.post("/knowledge/private", json={"title": "Empty", "text": "   \n  "}).status_code == 422
    assert len(user_a.get("/knowledge/private").json()) == before


def test_chunking_keeps_reading_order_around_a_long_paragraph_and_loses_no_text():
    from lib.knowledge import CHUNK, chunk_text

    a, long_para, b = "First short paragraph.", "L" * (CHUNK * 2 + 300), "Last short paragraph."
    chunks = chunk_text(f"Chapter 1\n\n{a}\n\n{long_para}\n\n{b}\n")
    joined = "".join(c["text"] for c in chunks).replace("\n\n", "")
    assert joined == (a + long_para + b)  # same text, same order, nothing dropped or repeated
    assert [c["ordinal"] for c in chunks] == list(range(len(chunks))) and chunks[0]["text"] == a


def test_the_book_library_can_be_switched_off_by_one_setting(monkeypatch):
    import asyncio

    from lib import knowledge

    monkeypatch.setenv("KNOWLEDGE_ENABLED", "false")
    out = asyncio.run(knowledge.search("justice", "any-org", k=3))
    assert out["hits"] == [] and "switched off" in out["note"]


def test_no_rung_of_the_ladder_can_skip_rights_and_approval(admin):  # noqa: F811
    """Found by the code review: Registered -> 'Ingestion pending' used to need neither recorded rights nor the owner's written approval."""
    number, _ = new_work()
    r = status(admin, number, "Ingestion pending")
    assert r.status_code == 422 and "rights" in r.text.lower()
    assert rights(admin, number).status_code == 200
    r = status(admin, number, "Ingestion pending")  # rights are now recorded, but no approval was ever given
    assert r.status_code == 422 and "approval" in r.text.lower()
    assert ingest(admin, number).status_code == 409  # and nothing can be indexed either


def test_a_mistaken_block_can_be_undone_but_only_back_to_the_early_rungs(admin):  # noqa: F811
    number, _ = new_work()
    assert status(admin, number, "Unavailable or blocked").status_code == 200
    assert status(admin, number, "Authorized for ingestion", approval="Owner approved in writing (test fixture)").status_code == 422
    assert status(admin, number, "Source located").status_code == 200


def test_a_huge_number_in_the_path_is_a_clean_422_not_a_server_error(user_a):
    assert user_a.delete("/knowledge/private/99999999999999999999").status_code == 422


def test_a_line_that_merely_starts_with_a_keyword_is_not_a_chapter_heading():
    from lib.knowledge import chunk_text

    text = """BOOK I.

Part of the reason the king failed was pride.

Article is here, said the clerk, and the room fell quiet.

Section 228. If a builder builds.

More text."""
    labels = {c["chapter"] for c in chunk_text(text)}
    assert "BOOK I." in labels and "Section 228. If a builder builds." in labels  # real headings are still recognised
    assert not any(l.startswith(("Part of", "Article is")) for l in labels)  # ordinary sentences are not


def test_a_later_partial_load_does_not_downgrade_a_full_work(admin):  # noqa: F811
    number, _ = new_work()
    authorise(admin, number)
    assert ingest(admin, number, complete=True).json()["coverage"] == "full"
    assert ingest(admin, number, text=BOOK + " extra words quillfeather2", complete=False).json()["coverage"] == "full"



import asyncio

from tests.inproc import run as run_on_client_loop  # the shared async database client belongs to one loop; every in-process test runs on it


def test_a_private_document_quota_is_enforced_per_organisation(monkeypatch):
    from lib import knowledge
    from lib.db import db

    async def run():
        a, b = f"quota-a-{uuid.uuid4().hex[:8]}", f"quota-b-{uuid.uuid4().hex[:8]}"
        out = {}
        try:
            monkeypatch.setattr(knowledge, "MAX_PRIVATE_DOCS", 1)
            await knowledge.add_private_text(a, "One", "TEST FIXTURE ONLY. quotafable one")
            with pytest.raises(ValueError, match="private documents"):
                await knowledge.add_private_text(a, "Two", "TEST FIXTURE ONLY. quotafable two")  # over the document limit
            await knowledge.add_private_text(b, "Other org", "TEST FIXTURE ONLY. quotafable three")  # another organisation is unaffected
            monkeypatch.setattr(knowledge, "MAX_PRIVATE_DOCS", 10**6)
            monkeypatch.setattr(knowledge, "MAX_PRIVATE_CHARS", 40)
            with pytest.raises(ValueError, match="storage is full"):
                await knowledge.add_private_text(a, "Big", "TEST FIXTURE ONLY. quotafable a much longer text than the rest")
            out["docs"] = await db.knowledge_works.count_documents({"org_id": a, "scope": "org"})
        finally:
            for org in (a, b):
                for w in await db.knowledge_works.find({"org_id": org}).to_list(10):
                    await db.knowledge_chunks.delete_many({"work_number": w["number"]})
                await db.knowledge_works.delete_many({"org_id": org})
        return out

    assert run_on_client_loop(run())["docs"] == 1  # the refused uploads left nothing behind


def test_two_ingests_at_once_cannot_store_the_same_chunk_twice():
    from lib import knowledge
    from lib.db import db

    async def run():
        org = f"race-{uuid.uuid4().hex[:8]}"
        text = "TEST FIXTURE ONLY. " + " ".join(f"racefable{i}" for i in range(800))
        number = -int(uuid.uuid4().int % 10**9) - 1
        await asyncio.gather(*(knowledge._store(number, "org", org, text, False, status_after=False) for _ in range(4)))
        total = await db.knowledge_chunks.count_documents({"work_number": number, "scope": "org", "org_id": org})
        hashes = await db.knowledge_chunks.distinct("sha256", {"work_number": number, "scope": "org", "org_id": org})
        await db.knowledge_chunks.delete_many({"work_number": number})
        return total, len(hashes)

    total, unique = run_on_client_loop(run())
    assert total == unique and total > 0
