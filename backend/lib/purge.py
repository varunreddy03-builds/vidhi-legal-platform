"""Deleting data for real: one place that knows every collection (and stored file) that belongs to a matter,
a recovery case or a whole organisation. Used by the delete buttons, the retention job and organisation erasure,
so a delete can never leave a forgotten copy behind.

What is kept, and why
  * audit events of a deleted matter/case stay (the firm may need the trail) but their free-text detail is blanked,
    because it can contain client or party names.
  * email_suppressions are global by address (a bounced/complained address must never be mailed again), so they stay.
  * payment records are anonymised, not deleted (accounting); they no longer point at any person.
  * a tiny erasure_log row (organisation id, date, counts - no names, no emails) proves an erasure happened.
"""

import re
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from lib import erasure_ledger
from lib.db import db

MATTER_COLLECTIONS = (
    "documents", "facts", "timeline_events", "research_results", "drafts",
    "evidence_items", "entities", "inconsistencies", "portal_access", "portal_updates", "portal_shares",
)


# Collections whose rows carry the organisation's id: erasing the organisation deletes them, and tests/test_org_export.py makes sure the export covers each of them (or says why not).
ORG_TAGGED = (
    "clients", "addin_keys", "doc_notes", "documents", "research_results", "drafts", "recovery_proofs", "email_log", "email_confirmations",
    "audit_events", "org_branding", "invites", "answer_feedback", "portal_access", "portal_updates", "portal_shares", "deadlines", "push_subscriptions", "directory_profiles", "booking_requests", "authority_reports", "date_lists", "defect_checks", "old_code_checks", "pilot_feedback", "draft_comments",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _delete_files(file_ids: list) -> int:
    bucket = AsyncIOMotorGridFSBucket(db)
    n = 0
    for fid in file_ids:
        try:
            await bucket.delete(fid)
            n += 1
        except Exception:  # noqa: BLE001 - a file that is already gone must not block the rest
            pass
    return n


async def purge_document(doc: dict) -> None:
    """Remove one uploaded document: its stored file, everything the AI pulled out of it, and every link to it. Used by the delete button and by the upload-expiry job, so both do exactly the same."""
    import logging

    document_id = doc["id"]
    erasure_ledger.record("document", document_id)
    await db.documents.delete_one({"id": document_id})
    await db.portal_shares.delete_many({"document_id": document_id})  # a deleted document is no longer shared with any client
    await db.doc_notes.delete_many({"document_id": document_id})  # and its page notes go with it
    if doc.get("gridfs_id"):
        try:
            await AsyncIOMotorGridFSBucket(db).delete(doc["gridfs_id"])
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning("could not delete stored file for %s", document_id, exc_info=True)
    # Anything the AI pulled out of this document goes with it; user-entered records just lose the link.
    await db.evidence_items.delete_many({"document_id": document_id, "source": "AI_EXTRACTED"})
    await db.inconsistencies.delete_many({"matter_id": doc["matter_id"], "$or": [{"a.document_id": document_id}, {"b.document_id": document_id}]})  # differences quoting this document
    for ent in await db.entities.find({"matter_id": doc["matter_id"], "appearances.document_id": document_id}).to_list(1000):
        left = [a for a in ent.get("appearances", []) if a.get("document_id") != document_id]
        if left:
            await db.entities.update_one({"id": ent["id"]}, {"$set": {"appearances": left}})
        else:
            await db.entities.delete_one({"id": ent["id"]})  # a person found only in this document
    for coll in ("facts", "timeline_events", "evidence_items"):
        await db[coll].update_many({"document_id": document_id}, {"$set": {"document_id": None}})


async def purge_matter(matter_id: str) -> dict:
    """Remove a matter and everything hanging off it. The caller has already checked who may do this."""
    counts: dict[str, int] = {}
    erasure_ledger.record("matter", matter_id)
    docs = await db.documents.find({"matter_id": matter_id, "gridfs_id": {"$exists": True}}, {"gridfs_id": 1}).to_list(5000)
    counts["files"] = await _delete_files([d["gridfs_id"] for d in docs])
    draft_ids = [d["id"] for d in await db.drafts.find({"matter_id": matter_id}, {"id": 1}).to_list(5000)]
    if draft_ids:
        counts["draft_versions"] = (await db.draft_versions.delete_many({"draft_id": {"$in": draft_ids}})).deleted_count
        counts["draft_comments"] = (await db.draft_comments.delete_many({"draft_id": {"$in": draft_ids}})).deleted_count
    research_ids = [r["id"] for r in await db.research_results.find({"matter_id": matter_id}, {"id": 1}).to_list(100000)]
    if research_ids:
        counts["answer_feedback"] = (await db.answer_feedback.delete_many({"research_id": {"$in": research_ids}})).deleted_count
    counts["matters"] = (await db.matters.delete_one({"id": matter_id})).deleted_count
    for coll in MATTER_COLLECTIONS:
        counts[coll] = (await db[coll].delete_many({"matter_id": matter_id})).deleted_count
    await db.audit_events.update_many({"matter_id": matter_id}, {"$set": {"detail": None, "redacted": True}})
    return counts


async def purge_case(case_id: str) -> dict:
    """Remove a recovery case, its proofs, pending confirmations and every email record about it."""
    counts: dict[str, int] = {}
    erasure_ledger.record("case", case_id)
    proofs = await db.recovery_proofs.find({"case_id": case_id, "gridfs_id": {"$exists": True}}, {"gridfs_id": 1}).to_list(5000)
    counts["files"] = await _delete_files([p["gridfs_id"] for p in proofs])
    counts["recovery_cases"] = (await db.recovery_cases.delete_one({"id": case_id})).deleted_count
    for coll in ("recovery_proofs", "email_confirmations", "email_log", "notice_versions", "case_correspondence", "notice_translations"):
        counts[coll] = (await db[coll].delete_many({"case_id": case_id})).deleted_count
    # audit lines about this case carry its id in the detail text; blank them (names may be inside)
    await db.audit_events.update_many(
        {"detail": {"$regex": "^" + re.escape(case_id)}}, {"$set": {"detail": None, "redacted": True}}
    )
    return counts


async def purge_org(org_id: str, requested_by_user_id: str) -> dict:
    """Erase an entire organisation: all matters, cases, people, sessions, branding, audit trail."""
    counts: dict[str, int] = {}
    erasure_ledger.record("org", org_id)
    for m in await db.matters.find({"organization_id": org_id}, {"id": 1}).to_list(100000):
        for k, v in (await purge_matter(m["id"])).items():
            counts[k] = counts.get(k, 0) + v
    for c in await db.recovery_cases.find({"organization_id": org_id}, {"id": 1}).to_list(100000):
        for k, v in (await purge_case(c["id"])).items():
            counts[k] = counts.get(k, 0) + v
    # matter-less drafts and their earlier versions
    stray = [d["id"] for d in await db.drafts.find({"organization_id": org_id}, {"id": 1}).to_list(100000)]
    if stray:
        counts["draft_versions"] = counts.get("draft_versions", 0) + (await db.draft_versions.delete_many({"draft_id": {"$in": stray}})).deleted_count
    members = await db.users.find({"organization_id": org_id}, {"id": 1, "email": 1}).to_list(10000)
    member_ids, member_emails = [u["id"] for u in members], [u["email"] for u in members if u.get("email")]
    mine = {"$or": [{"organization_id": org_id}, {"user_id": {"$in": member_ids}}, {"email": {"$in": member_emails}}]}
    counts["support_tickets"] = (await db.support_tickets.delete_many(mine)).deleted_count  # free text written by the people being erased
    await db.data_requests.update_many(mine, {"$set": {"email": None, "details": None, "user_id": None, "organization_id": None, "anonymised": True}})  # the fact that a request was handled stays, the person does not
    await db.refunds.update_many({"$or": [{"organization_id": org_id}, {"user_id": {"$in": member_ids}}]}, {"$set": {"user_id": None, "organization_id": None, "anonymised": True}})
    # anything still tagged with the organisation (orphans, matter-less rows)
    for coll in ORG_TAGGED:
        counts[coll] = counts.get(coll, 0) + (await db[coll].delete_many({"organization_id": org_id})).deleted_count
    imgs = await db.generated_images.find({"organization_id": org_id}, {"gridfs_id": 1}).to_list(100000)
    counts["images"] = await _delete_files([i["gridfs_id"] for i in imgs])
    await db.generated_images.delete_many({"organization_id": org_id})
    await db.image_usage.delete_many({"organization_id": org_id})
    for coll in ("knowledge_chunks", "knowledge_works"):  # private documents the organisation added to its knowledge library (the shared library has no org_id and is untouched)
        counts[coll] = (await db[coll].delete_many({"org_id": org_id})).deleted_count
    user_ids = [u["id"] for u in await db.users.find({"organization_id": org_id}, {"id": 1}).to_list(10000)]
    if user_ids:
        await db.sessions.delete_many({"user_id": {"$in": user_ids}})
        await db.password_resets.delete_many({"user_id": {"$in": user_ids}})
    counts["users"] = (await db.users.delete_many({"organization_id": org_id})).deleted_count
    # payments: keep the accounting row, drop every link to a person or organisation
    await db.payment_transactions.update_many(
        {"organization_id": org_id}, {"$set": {"user_id": None, "organization_id": None, "anonymised": True}}
    )
    await db.organizations.delete_one({"id": org_id})
    await db.erasure_log.insert_one({"organization_id": org_id, "erased_at": _now(), "counts": counts})
    return counts


class CannotErase(Exception):
    """The person cannot be erased on their own (for example the only owner of an organisation). The message says what to do instead."""


async def purge_user(user_id: str, *, force: bool = False) -> dict:
    """Erase ONE person: their sign-in, devices, requests and messages are deleted, their name and email are removed from the audit trail, and the records they made for the firm
    (matters, documents, drafts) stay with the firm but no longer lead to a person. The caller has already checked who may do this.

    Refuses (CannotErase) when the person is the only owner of their organisation, because the organisation would be left with nobody in charge: make someone else an owner, or
    erase the organisation. `force=True` is for re-applying an erasure after a restore, where the decision was already made."""
    user = await db.users.find_one({"id": user_id})
    if not user:
        return {"users": 0}
    email = (user.get("email") or "").strip()
    if not force and user.get("role") == "OWNER" and await db.users.count_documents({"organization_id": user.get("organization_id"), "role": "OWNER", "id": {"$ne": user_id}}) == 0:
        raise CannotErase("This person is the only owner of their organisation. Make someone else an owner first, or erase the whole organisation.")
    erasure_ledger.record("user", user_id)
    counts: dict[str, int] = {}
    for coll in ("sessions", "password_resets", "push_subscriptions", "portal_access", "directory_profiles", "booking_requests", "support_tickets", "answer_feedback", "usage_events", "pilot_feedback"):
        counts[coll] = (await db[coll].delete_many({"user_id": user_id})).deleted_count
    if email:
        counts["invites"] = (await db.invites.delete_many({"email": email})).deleted_count  # invitations sent to them
        counts["email_log"] = (await db.email_log.delete_many({"to": email.lower()})).deleted_count  # messages the platform sent to this address
        counts["email_confirmations"] = (await db.email_confirmations.delete_many({"email": email})).deleted_count
    # the audit trail stays for the firm, without the person: no id, no email, and no detail text that could name them
    flt = {"$or": [{"user_id": user_id}] + ([{"user_email": email}, {"detail": {"$regex": re.escape(email), "$options": "i"}}] if email else [])}
    counts["audit_events"] = (await db.audit_events.update_many(flt, {"$set": {"user_id": None, "user_email": None, "detail": None, "redacted": True}})).modified_count
    await db.data_requests.update_many({"user_id": user_id}, {"$set": {"email": None, "details": None, "user_id": None, "organization_id": None, "anonymised": True}})
    await db.ai_ledger.update_many({"user_id": user_id}, {"$set": {"user_id": None}})  # cost records stay, without the person
    counts["users"] = (await db.users.delete_one({"id": user_id})).deleted_count
    return counts
