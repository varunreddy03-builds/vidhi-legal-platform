"""The verified source store: the ONE module that writes law data and the status of whether anyone has verified it.

Law data here means every collection in LAW_COLLECTIONS: the sources and documents, the Acts, versions and provisions, the verified library, the drafts, the old-code to new-code mappings,
the judgment case list and the links between judgments, forums, treatments and the deadline rules. Nothing else in the application inserts, changes, replaces or deletes a row of those
collections, and nothing else sets a reviewed or verified status on any of them. tests/test_verified_store.py reads all the code and fails if any other module does.

What the store guarantees
  * A row is created unreviewed. `create`, `create_many`, `change` and `replace_many` refuse a row or a change that claims a reviewed or verified status.
  * A status of reviewed, rejected or verified is recorded only by `record_review` or `publish_verified`, and only with a reviewer's full name, a real date and the source the reviewer
    compared with (a link, or the written citation when there is no link: never an invented one). Each such row also gets one uniform `provenance` block:
    {source_link, checked_on, reviewed_by, status}.
  * `withdraw_verified` takes an entry out of the verified library and keeps it on record. `restore_review` puts back a status that was there before (the undo of a failed approval).
  * Reading goes through `find_one`, `find_many`, `count` and `aggregate`, so a route never needs to touch a law collection itself.

Each module keeps its own domain checks (is the text unchanged, is the quote in the judgment, does the rule cite a source) and then hands the write to this store. The functions take the database
handle as their first argument (callers pass their own), so a test can point one module at its own client.
This module never calls an AI model and never writes law text: it stores what a caller gives it and refuses what claims more than the caller proved."""

import hashlib
import re
from datetime import date, datetime, timezone

from pymongo import ReplaceOne, UpdateOne

LAW_COLLECTIONS = frozenset({
    "legal_sources", "legal_documents", "instruments", "instrument_versions", "provisions", "provision_chunks", "provision_refs", "library_entries", "legal_source_candidates", "code_mappings", "judgment_relations",
    "hc_judgments", "decisions", "treatments", "forums", "deadline_calendars", "deadline_rules",
})
# Fields that say "a person compared this with the source". Only record_review, publish_verified, withdraw_verified, restore_review and set_commencement may write them.
REVIEW_KEYS = frozenset({
    "review_status", "reviewed_by", "reviewed_on", "verified_by", "verified_on", "rejected_reason", "provenance", "approved_at", "withdrawn_by", "withdrawn_on", "withdrawn_reason",
    "act_commencement_reviewed",
})
STATUS_IS_REVIEW = frozenset({"library_entries", "judgment_relations"})  # in these collections the `status` field itself is the review state
# (state field, who field, date field) written by record_review for each collection that can be reviewed
REVIEW_FIELDS = {
    "provisions": ("review_status", "reviewed_by", "reviewed_on"),
    "forums": ("review_status", "reviewed_by", "reviewed_on"),
    "treatments": ("review_status", "reviewed_by", "reviewed_on"),
    "code_mappings": ("review_status", "reviewed_by", "verified_on"),
    "deadline_calendars": ("review_status", "reviewed_by", "verified_on"),
    "deadline_rules": ("review_status", "reviewed_by", "verified_on"),
    "judgment_relations": ("status", "reviewed_by", "reviewed_on"),
}
VERIFIED = "VERIFIED"
REVIEWED, REJECTED, UNREVIEWED = "reviewed", "rejected", "unreviewed"


class StoreError(ValueError):
    """A write the store refuses. A ValueError, so every existing route that turns ValueError into a plain message keeps working."""


def _collection(name: str) -> str:
    if name not in LAW_COLLECTIONS:
        raise StoreError(f"{name} is not a law-data collection.")
    return name


def _handle(db):
    if db is not None:
        return db
    from lib.db import db as default  # imported late: tests give each module its own client

    return default


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def clean_name(reviewer: str) -> str:
    name = (reviewer or "").strip()
    if len(name) < 5:
        raise StoreError("Give the reviewer's full name.")
    return name[:120]


def clean_day(on: str) -> str:
    try:
        return date.fromisoformat(str(on)).isoformat()
    except ValueError as exc:
        raise StoreError("Give the date of the review as YYYY-MM-DD.") from exc


def _claims_review(collection: str, doc: dict) -> bool:
    if str(doc.get("review_status") or "").lower() in (REVIEWED, REJECTED):
        return True
    if collection in STATUS_IS_REVIEW and str(doc.get("status") or "").upper() in (VERIFIED, "REVIEWED", "REJECTED"):
        return True
    return any(doc.get(k) for k in ("reviewed_by", "reviewed_on", "verified_by", "provenance", "act_commencement_reviewed"))


# ---------- writes that never carry a review ----------
async def create(db, collection: str, doc: dict) -> None:
    _collection(collection)
    if _claims_review(collection, doc):
        raise StoreError("A new row cannot arrive already reviewed: a named reviewer records that afterwards (record_review).")
    await _handle(db)[collection].insert_one(dict(doc))


async def create_many(db, collection: str, rows: list[dict]) -> None:
    _collection(collection)
    if any(_claims_review(collection, r) for r in rows):
        raise StoreError("A new row cannot arrive already reviewed: a named reviewer records that afterwards (record_review).")
    if rows:
        await _handle(db)[collection].insert_many([dict(r) for r in rows])


async def change(db, collection: str, flt: dict, fields: dict, *, many: bool = False, upsert: bool = False, unset: tuple[str, ...] = ()) -> None:
    """Set ordinary fields. Refuses any field that belongs to the review state."""
    _collection(collection)
    banned = [k for k in fields if k in REVIEW_KEYS or (k == "status" and collection in STATUS_IS_REVIEW)] + [k for k in unset if k in REVIEW_KEYS]
    if banned:
        raise StoreError(f"{', '.join(banned)} can only be set by the verified store's review functions.")
    update: dict = {"$set": fields}
    if unset:
        update["$unset"] = {k: "" for k in unset}
    c = _handle(db)[collection]
    await (c.update_many if many else c.update_one)(flt, update, upsert=upsert)


async def replace_many(db, collection: str, rows: list[dict], *, key: str = "id", batch: int = 500) -> None:
    """Insert or replace whole rows by `key` (the loaders for drafts and the judgment case list). Rows that claim a review are refused."""
    _collection(collection)
    if any(_claims_review(collection, r) for r in rows):
        raise StoreError("A loaded row cannot claim a review.")
    c = _handle(db)[collection]
    for i in range(0, len(rows), batch):
        await c.bulk_write([ReplaceOne({key: r[key]}, r, upsert=True) for r in rows[i : i + batch]], ordered=False)


async def delete(db, collection: str, flt: dict, *, many: bool = True) -> int:
    _collection(collection)
    c = _handle(db)[collection]
    res = await (c.delete_many if many else c.delete_one)(flt)
    return res.deleted_count


async def set_commencement(db, instrument_id: str, fields: dict, *, reviewed_by: str | None = None, reviewed_on: str | None = None) -> None:
    """Record where an Act's start date came from. `act_commencement_reviewed` becomes true only with the name and date of the person who compared the notification with the Gazette."""
    f = dict(fields)
    reviewed = bool(f.pop("act_commencement_reviewed", False))
    if reviewed:
        clean_name(reviewed_by or "")
        clean_day(reviewed_on or "")
    await change(db, "instruments", {"id": instrument_id}, f)
    await _handle(db)["instruments"].update_one({"id": instrument_id}, {"$set": {"act_commencement_reviewed": reviewed}})


# ---------- the review state ----------
def provenance(source_link: str, checked_on: str, reviewer: str, status: str) -> dict:
    return {"source_link": source_link, "checked_on": checked_on, "reviewed_by": reviewer, "status": status}


async def record_review(db, collection: str, doc_id: str, status: str, reviewer: str, on: str, source_link: str, *, reason: str | None = None) -> None:
    """A named person compared this row with its source: reviewed, or rejected with the reason. The row's own module has already made its domain checks."""
    _collection(collection)
    if collection not in REVIEW_FIELDS:
        raise StoreError(f"{collection} has no review state.")
    if status not in (REVIEWED, REJECTED):
        raise StoreError("A review is either 'reviewed' or 'rejected'.")
    name, day = clean_name(reviewer), clean_day(on)
    link = (source_link or "").strip()
    if status == REVIEWED and not link:
        raise StoreError("A row can be marked reviewed only with the source it was compared with (a link, or the written citation).")
    if status == REJECTED and len((reason or "").strip()) < 10:
        raise StoreError("Say what does not match the source.")
    state_f, who_f, date_f = REVIEW_FIELDS[collection]
    value = status.upper() if collection == "judgment_relations" else status
    fields = {state_f: value, who_f: name, date_f: day, "provenance": provenance(link, day, name, value)}
    if collection in ("provisions", "judgment_relations"):
        fields["rejected_reason"] = (reason or "").strip()[:1000] if status == REJECTED else None
    res = await _handle(db)[collection].update_one({"id": doc_id}, {"$set": fields})
    if not res.matched_count:
        raise StoreError("Unknown row.")


async def restore_review(db, collection: str, doc_id: str, before: dict) -> None:
    """Put back the review state a row had a moment ago (the undo when an approval could not be completed, or when a library entry is withdrawn). Writes nothing newer than `before`."""
    _collection(collection)
    state_f, who_f, date_f = REVIEW_FIELDS[collection]
    state = before.get(state_f) or UNREVIEWED
    if str(state).lower() == REVIEWED:
        clean_name(before.get(who_f) or "")
        clean_day(before.get(date_f) or "")
    fields = {state_f: state, who_f: before.get(who_f), date_f: before.get(date_f)}
    unset = () if str(state).lower() == REVIEWED else ("provenance",)
    update: dict = {"$set": fields}
    if unset:
        update["$unset"] = {"provenance": ""}
    await _handle(db)[collection].update_one({"id": doc_id}, update)


# ---------- the verified library ----------
async def publish_verified(db, entry: dict, *, origin: str, replace_text_guard: bool = True) -> dict:
    """Make one library entry VERIFIED. The entry must carry a named reviewer, a real date, the source address and a text whose hash matches. Never overwrites a verified entry whose
    text is different (withdraw that one first). Used for entries read from the library files and for entries approved on the reviewer screen: nothing else writes `library_entries`."""
    name, day = clean_name(entry.get("verified_by") or ""), clean_day(entry.get("verified_on") or "")
    url = str(entry.get("source_url") or "").strip()
    if not re.match(r"^https?://\S+$", url):
        raise StoreError("A verified entry needs the web address of the official source.")
    text = str(entry.get("text") or "")
    if sha256_text(text) != entry.get("text_sha256"):
        raise StoreError("The text does not match its recorded hash.")
    c = _handle(db)["library_entries"]
    old = await c.find_one({"id": entry["id"]})
    if replace_text_guard and old and old.get("status") == VERIFIED and old.get("text_sha256") != entry["text_sha256"]:
        raise StoreError("An entry with this id is already verified with different text. Withdraw that one first, or check which version you are approving.")
    now = datetime.now(timezone.utc)
    doc = {**entry, "verified_by": name, "verified_on": day, "status": VERIFIED, "origin": origin, "synced_at": now, "provenance": provenance(url, day, name, VERIFIED)}
    await c.update_one({"id": entry["id"]}, {"$set": doc, "$unset": {"withdrawn_by": "", "withdrawn_on": "", "withdrawn_reason": ""}}, upsert=True)
    return doc


async def withdraw_verified(db, entry_id: str, reviewer: str, on: str, reason: str) -> None:
    name, day = clean_name(reviewer), clean_day(on)
    if len((reason or "").strip()) < 10:
        raise StoreError("Say why the entry is being withdrawn.")
    await _handle(db)["library_entries"].update_one({"id": entry_id}, {"$set": {"status": "WITHDRAWN", "withdrawn_by": name, "withdrawn_on": day, "withdrawn_reason": reason.strip()[:1000]}})


async def withdraw_missing(db, origin: str, keep_ids: list[str]) -> None:
    """Entries that came from library files and are no longer in the files stop being verified (their file was removed)."""
    await _handle(db)["library_entries"].update_many({"origin": origin, "id": {"$nin": keep_ids}}, {"$set": {"status": "WITHDRAWN"}})


# ---------- which version of each source an answer used ----------
NOT_REVIEWED = "UNVERIFIED - not reviewed"


def source_versions(*, library_entries: list[dict] = (), drafts: list[dict] = (), judgments: list[dict] = (), documents: list[dict] = ()) -> list[dict]:
    """One record for every source an answer drew on, saved with the answer: what it was, where it can be read, which version, the hash of the exact text used, when and by whom it was checked,
    and its status. A verified library entry says VERIFIED with its reviewer; everything else says it was not reviewed. Nothing is looked up or invented here: a field the source does not carry stays empty."""
    now = datetime.now(timezone.utc).isoformat()
    out: list[dict] = []
    for e in library_entries:
        out.append({"source_kind": "verified_library", "id": e.get("id"), "citation": e.get("citation"), "source_name": e.get("source_name", ""), "source_link": e.get("source_url", ""),
                    "version": e.get("version", ""), "text_sha256": e.get("text_sha256") or sha256_text(str(e.get("text", ""))), "checked_on": e.get("verified_on"),
                    "reviewed_by": e.get("verified_by"), "status": VERIFIED, "recorded_at": now})
    for d in drafts:
        out.append({"source_kind": "draft_law", "id": d.get("id"), "citation": d.get("citation"), "source_name": d.get("source_name", ""), "source_link": d.get("source_url", ""),
                    "version": d.get("version", ""), "text_sha256": d.get("text_sha256", ""), "checked_on": None, "reviewed_by": None, "status": NOT_REVIEWED, "recorded_at": now})
    for j in judgments:
        out.append({"source_kind": "judgment", "id": j.get("id"), "citation": j.get("title") or j.get("citation"), "source_name": j.get("court", ""), "source_link": j.get("source_url", ""),
                    "version": j.get("text_kind", ""), "text_sha256": j.get("text_sha256", ""), "checked_on": None, "reviewed_by": None, "status": NOT_REVIEWED, "recorded_at": now})
    for m in documents:
        text = chr(10).join(p or "" for p in m.get("pages", []))
        out.append({"source_kind": "matter_document", "id": m.get("id"), "citation": m.get("filename"), "source_name": "uploaded to the matter", "source_link": "", "version": m.get("label", ""),
                    "text_sha256": sha256_text(text) if text.strip() else "", "checked_on": None, "reviewed_by": None, "status": NOT_REVIEWED, "recorded_at": now})
    return out


# ---------- reading: the only way a route reads law data ----------
async def find_one(collection: str, flt: dict, projection: dict | None = None, *, db=None) -> dict | None:
    return await _handle(db)[_collection(collection)].find_one(flt, projection)


async def find_many(collection: str, flt: dict | None = None, projection: dict | None = None, *, sort: list | None = None, skip: int = 0, limit: int = 0, db=None) -> list[dict]:
    cur = _handle(db)[_collection(collection)].find(flt or {}, projection)
    if sort:
        cur = cur.sort(sort)
    if skip:
        cur = cur.skip(skip)
    if limit:
        cur = cur.limit(limit)
    return await cur.to_list(limit or None)


async def count(collection: str, flt: dict | None = None, *, db=None) -> int:
    return await _handle(db)[_collection(collection)].count_documents(flt or {})


async def aggregate(collection: str, pipeline: list[dict], *, db=None) -> list[dict]:
    return await _handle(db)[_collection(collection)].aggregate(pipeline).to_list(None)


async def verified_count(*, db=None) -> int:
    return await count("library_entries", {"status": VERIFIED}, db=db)


async def verified_entries(flt: dict | None = None, projection: dict | None = None, *, sort: list | None = None, limit: int = 1000, db=None) -> list[dict]:
    """Library entries with status VERIFIED (the only status that means a named person compared the text with the source)."""
    return await find_many("library_entries", {**(flt or {}), "status": VERIFIED}, projection, sort=sort, limit=limit, db=db)


# ---------- the loader scripts (plain pymongo, millions of rows) ----------
class _CheckedUpdate(UpdateOne):
    """An update built by LawCollection.update_op: its fields were checked when it was made."""


class LawCollection:
    """A law-data collection for the loader scripts under scripts/ (they use a plain synchronous client for speed). Reads pass straight through; every write is checked like the async functions
    above: no review state in a new row or an update, and bulk writes accept only updates made by `update_op`."""

    def __init__(self, database, name: str):
        self.name = _collection(name)
        self._c = database[name]

    def find(self, *args, **kwargs):
        return self._c.find(*args, **kwargs)

    def find_one(self, *args, **kwargs):
        return self._c.find_one(*args, **kwargs)

    def count_documents(self, *args, **kwargs):
        return self._c.count_documents(*args, **kwargs)

    def estimated_document_count(self) -> int:
        return self._c.estimated_document_count()

    def create_index(self, *args, **kwargs):
        return self._c.create_index(*args, **kwargs)

    def insert_many(self, docs: list[dict], ordered: bool = False):
        if any(_claims_review(self.name, d) for d in docs):
            raise StoreError("A loaded row cannot claim a review.")
        return self._c.insert_many(docs, ordered=ordered)

    def update_op(self, flt: dict, fields: dict) -> UpdateOne:
        banned = [k for k in fields if k in REVIEW_KEYS or (k == "status" and self.name in STATUS_IS_REVIEW)]
        if banned:
            raise StoreError(f"{', '.join(banned)} can only be set by the verified store's review functions.")
        return _CheckedUpdate(flt, {"$set": fields})

    def bulk_write(self, ops: list, ordered: bool = False):
        if not all(isinstance(o, _CheckedUpdate) for o in ops):
            raise StoreError("Bulk writes accept only updates made with update_op.")
        return self._c.bulk_write(ops, ordered=ordered)


def sync_collection(database, name: str) -> LawCollection:
    return LawCollection(database, name)
