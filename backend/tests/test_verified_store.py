"""The verified store (lib/verified_store.py): what it refuses and what it records. Invented rows only; nothing here is law.
These tests use a database of their own (the test database's name + "_vs_" + the worker's name): the store reads whole collections in places, so a bare placeholder row in the shared test database could break another
test running at the same moment on another worker."""

import asyncio
import os
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from lib import verified_store as store

DB_NAME = os.environ.get("DB_NAME", "vidhi_test") + "_vs_" + os.environ.get("PYTEST_XDIST_WORKER", "main")  # one per parallel worker: each drops only its own when it is done
NAME = "Adv Invented Reviewer"
DAY = "2026-11-05"
SOURCE = "https://example.invalid/official-text"


def mongo():
    """The synchronous handle on this file's own database."""
    return MongoClient(os.environ["MONGO_URL"])[DB_NAME]


@pytest.fixture(scope="module", autouse=True)
def _own_database():
    yield
    MongoClient(os.environ["MONGO_URL"]).drop_database(DB_NAME)


def run(scenario):
    """One async scenario on its own Motor client (a client cannot be reused across asyncio.run calls)."""

    async def go():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            return await scenario(client[DB_NAME])
        finally:
            client.close()

    return asyncio.run(go())


def fresh() -> str:
    return f"vs-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ids():
    made: dict[str, list[str]] = {}
    yield made
    for coll, rows in made.items():
        mongo()[coll].delete_many({"id": {"$in": rows}})


def entry(eid: str, text: str = "Invented text of a section.") -> dict:
    return {"id": eid, "jurisdiction": "IN", "citation": f"Section 1, Invented Act {eid}", "aliases": [], "keys": [], "kind": "statute", "title": "", "text": text, "text_norm": text.lower(),
            "text_sha256": store.sha256_text(text), "source_name": "Invented source", "source_url": SOURCE, "version": "v1", "verified_by": NAME, "verified_on": DAY}


def test_a_new_row_cannot_arrive_reviewed_or_verified(ids):
    rid = fresh()
    ids.setdefault("provisions", []).append(rid)

    async def scenario(db):
        for claim in ({"review_status": "reviewed"}, {"reviewed_by": NAME}, {"provenance": {"x": 1}}, {"verified_by": NAME}):
            with pytest.raises(store.StoreError):
                await store.create(db, "provisions", {"id": rid, **claim})
        with pytest.raises(store.StoreError):
            await store.create(db, "library_entries", {"id": rid, "status": "VERIFIED"})
        with pytest.raises(store.StoreError):
            await store.create_many(db, "provisions", [{"id": rid, "review_status": "rejected"}])
        with pytest.raises(store.StoreError):
            await store.replace_many(db, "legal_source_candidates", [{"id": rid, "reviewed_by": NAME}])
        await store.create(db, "provisions", {"id": rid, "review_status": "unreviewed", "reviewed_by": None})

    run(scenario)
    assert mongo().provisions.count_documents({"id": rid}) == 1


def test_ordinary_changes_work_but_the_review_state_cannot_be_changed_through_them(ids):
    rid = fresh()
    ids.setdefault("provisions", []).append(rid)
    ids.setdefault("library_entries", []).append(rid)
    mongo().provisions.insert_one({"id": rid, "review_status": "unreviewed", "note": "a"})

    async def scenario(db):
        await store.change(db, "provisions", {"id": rid}, {"note": "b"})
        for bad in ({"review_status": "reviewed"}, {"reviewed_by": NAME}, {"verified_on": DAY}, {"provenance": {}}, {"act_commencement_reviewed": True}):
            with pytest.raises(store.StoreError):
                await store.change(db, "provisions", {"id": rid}, bad)
        with pytest.raises(store.StoreError):
            await store.change(db, "library_entries", {"id": rid}, {"status": "VERIFIED"})  # in the library the status IS the review state
        with pytest.raises(store.StoreError):
            await store.change(db, "provisions", {"id": rid}, {"note": "c"}, unset=("reviewed_by",))
        with pytest.raises(store.StoreError):
            await store.change(db, "matters", {"id": rid}, {"note": "c"})  # not a law collection

    run(scenario)
    row = mongo().provisions.find_one({"id": rid})
    assert row["note"] == "b" and row["review_status"] == "unreviewed"


def test_a_review_needs_a_full_name_a_real_date_a_source_and_for_a_rejection_a_reason(ids):
    rid = fresh()
    ids.setdefault("provisions", []).append(rid)
    mongo().provisions.insert_one({"id": rid, "review_status": "unreviewed"})

    async def scenario(db):
        for args in (("Adv", DAY, SOURCE), (NAME, "not-a-date", SOURCE), (NAME, "", SOURCE), (NAME, DAY, ""), (NAME, DAY, "   ")):
            with pytest.raises(store.StoreError):
                await store.record_review(db, "provisions", rid, "reviewed", *args)
        with pytest.raises(store.StoreError):
            await store.record_review(db, "provisions", rid, "rejected", NAME, DAY, SOURCE, reason="short")
        with pytest.raises(store.StoreError):
            await store.record_review(db, "provisions", rid, "verified", NAME, DAY, SOURCE)  # not a review status
        with pytest.raises(store.StoreError):
            await store.record_review(db, "provisions", "no-such-row", "reviewed", NAME, DAY, SOURCE)
        with pytest.raises(store.StoreError):
            await store.record_review(db, "legal_sources", rid, "reviewed", NAME, DAY, SOURCE)  # this collection has no review state

    run(scenario)
    assert mongo().provisions.find_one({"id": rid})["review_status"] == "unreviewed"  # every refusal left the row alone


def test_a_review_records_status_reviewer_date_and_source_in_one_uniform_block(ids):
    pid, mid, rel = fresh(), fresh(), fresh()
    ids.setdefault("provisions", []).append(pid)
    ids.setdefault("code_mappings", []).append(mid)
    ids.setdefault("judgment_relations", []).append(rel)
    mongo().provisions.insert_one({"id": pid, "review_status": "unreviewed"})
    mongo().code_mappings.insert_one({"id": mid, "review_status": "unreviewed"})
    mongo().judgment_relations.insert_one({"id": rel, "status": "UNVERIFIED"})

    async def scenario(db):
        await store.record_review(db, "provisions", pid, "reviewed", NAME, DAY, SOURCE)
        await store.record_review(db, "code_mappings", mid, "reviewed", NAME, DAY, "Official comparison table")
        await store.record_review(db, "judgment_relations", rel, "rejected", NAME, DAY, SOURCE, reason="The sentence says something else.")

    run(scenario)
    p, m, r = mongo().provisions.find_one({"id": pid}), mongo().code_mappings.find_one({"id": mid}), mongo().judgment_relations.find_one({"id": rel})
    assert p["review_status"] == "reviewed" and p["reviewed_by"] == NAME and p["reviewed_on"] == DAY
    assert p["provenance"] == {"source_link": SOURCE, "checked_on": DAY, "reviewed_by": NAME, "status": "reviewed"}
    assert m["review_status"] == "reviewed" and m["verified_on"] == DAY and m["provenance"]["source_link"] == "Official comparison table"  # mappings keep their own date field name
    assert r["status"] == "REJECTED" and r["rejected_reason"] == "The sentence says something else." and r["provenance"]["status"] == "REJECTED"


def test_a_verified_entry_needs_name_date_address_and_matching_text_and_never_replaces_different_text(ids):
    eid = fresh()
    ids.setdefault("library_entries", []).append(eid)

    async def scenario(db):
        for bad in ({"verified_by": "Adv"}, {"verified_on": "soon"}, {"source_url": ""}, {"source_url": "not a url"}, {"text_sha256": "0" * 64}):
            with pytest.raises(store.StoreError):
                await store.publish_verified(db, {**entry(eid), **bad}, origin="reviewer_screen")
        saved = await store.publish_verified(db, entry(eid), origin="reviewer_screen")
        assert saved["status"] == "VERIFIED" and saved["provenance"] == {"source_link": SOURCE, "checked_on": DAY, "reviewed_by": NAME, "status": "VERIFIED"}
        with pytest.raises(store.StoreError):
            await store.publish_verified(db, entry(eid, "Different invented text."), origin="reviewer_screen")  # withdraw first
        await store.publish_verified(db, entry(eid, "Different invented text."), origin="library", replace_text_guard=False)  # a library file is the authority for its own entry

    run(scenario)
    assert mongo().library_entries.find_one({"id": eid})["text"] == "Different invented text."


def test_withdrawing_keeps_the_entry_on_record_and_needs_a_name_date_and_reason(ids):
    eid = fresh()
    ids.setdefault("library_entries", []).append(eid)

    async def scenario(db):
        await store.publish_verified(db, entry(eid), origin="reviewer_screen")
        for args in (("Adv", DAY, "A long enough reason."), (NAME, "x", "A long enough reason."), (NAME, DAY, "short")):
            with pytest.raises(store.StoreError):
                await store.withdraw_verified(db, eid, *args)
        await store.withdraw_verified(db, eid, NAME, DAY, "The source was amended.")
        assert not await store.verified_entries({"id": eid}, db=db)

    run(scenario)
    row = mongo().library_entries.find_one({"id": eid})
    assert row["status"] == "WITHDRAWN" and row["withdrawn_by"] == NAME and row["text"]  # still on record


def test_a_start_date_is_marked_reviewed_only_with_a_named_reviewer_and_a_date(ids):
    iid = fresh()
    ids.setdefault("instruments", []).append(iid)
    mongo().instruments.insert_one({"id": iid})

    async def scenario(db):
        with pytest.raises(store.StoreError):
            await store.set_commencement(db, iid, {"act_in_force_from": "2024-07-01", "act_commencement_reviewed": True})
        await store.set_commencement(db, iid, {"act_in_force_from": "2024-07-01", "act_commencement_reviewed": False})
        assert mongo().instruments.find_one({"id": iid})["act_commencement_reviewed"] is False
        await store.set_commencement(db, iid, {"act_commencement_reviewed": True}, reviewed_by=NAME, reviewed_on=DAY)

    run(scenario)
    assert mongo().instruments.find_one({"id": iid})["act_commencement_reviewed"] is True


def test_restoring_puts_back_an_earlier_state_and_drops_the_provenance_of_an_unreviewed_one(ids):
    rid = fresh()
    ids.setdefault("provisions", []).append(rid)
    mongo().provisions.insert_one({"id": rid, "review_status": "unreviewed", "reviewed_by": None, "reviewed_on": None})

    async def scenario(db):
        await store.record_review(db, "provisions", rid, "reviewed", NAME, DAY, SOURCE)
        await store.restore_review(db, "provisions", rid, {"review_status": "unreviewed", "reviewed_by": None, "reviewed_on": None})
        with pytest.raises(store.StoreError):
            await store.restore_review(db, "provisions", rid, {"review_status": "reviewed", "reviewed_by": "Adv", "reviewed_on": DAY})  # an undo cannot invent a reviewer

    run(scenario)
    row = mongo().provisions.find_one({"id": rid})
    assert row["review_status"] == "unreviewed" and row["reviewed_by"] is None and "provenance" not in row


def test_source_versions_name_every_kind_of_source_and_never_make_an_unreviewed_one_look_verified():
    library = {"id": "a", "citation": "Section 1, Invented Act", "text": "Invented text.", "version": "v1", "source_name": "Invented source", "source_url": SOURCE, "verified_by": NAME, "verified_on": DAY}
    draft = {"id": "d", "citation": "Section 2, Invented Act", "source_name": "Invented source", "source_url": SOURCE, "version": "draft v1", "text_sha256": "ab" * 32}
    judgment = {"id": "j", "title": "A v B", "court": "Invented High Court", "source_url": SOURCE, "text_kind": "TEXT", "text_sha256": "cd" * 32}
    document = {"id": "m", "filename": "notice.pdf", "label": "DOC-01", "pages": ["first page", "second page"]}
    rows = store.source_versions(library_entries=[library], drafts=[draft], judgments=[judgment], documents=[document])
    by_kind = {r["source_kind"]: r for r in rows}
    assert list(by_kind) == ["verified_library", "draft_law", "judgment", "matter_document"]
    assert by_kind["verified_library"]["status"] == "VERIFIED" and by_kind["verified_library"]["reviewed_by"] == NAME and by_kind["verified_library"]["checked_on"] == DAY
    assert by_kind["verified_library"]["text_sha256"] == store.sha256_text("Invented text.") and by_kind["verified_library"]["version"] == "v1" and by_kind["verified_library"]["source_link"] == SOURCE
    for kind in ("draft_law", "judgment", "matter_document"):
        assert by_kind[kind]["status"] == "UNVERIFIED - not reviewed" and by_kind[kind]["reviewed_by"] is None and by_kind[kind]["checked_on"] is None
    assert by_kind["matter_document"]["text_sha256"] == store.sha256_text("first page\nsecond page") and by_kind["judgment"]["version"] == "TEXT"
    assert store.source_versions() == [] and all(r["recorded_at"] for r in rows)
