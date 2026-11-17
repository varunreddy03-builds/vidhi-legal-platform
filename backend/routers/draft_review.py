"""A small firm's loop on a draft: the author sends it for review, a lawyer, admin or owner approves it or asks for changes, and everyone writes comments on it.

Status: DRAFT -> WITH_REVIEWER -> APPROVED or CHANGES_REQUESTED. Any change to the text or title of a draft that is with a reviewer or approved returns it to DRAFT (done in routers/research.py update_draft),
so "Approved" always means "this exact text was approved". Approval is a record of who decided and when; it blocks nothing (export is not gated).
The author cannot approve their own draft, except in an organisation with one member. Comments are plain text kept with the draft: nobody can edit or delete one, they can only be marked resolved,
and they are never put in an AI prompt. Every route writes an audit line and filters by organisation."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.auth import audit, current_user, now
from lib.db import db
from lib.rbac import ROLES, can
from lib.ratelimit import user_limit
from typing import Literal

router = APIRouter(tags=["draft-review"])
MAX_COMMENTS = 200


def name_of(user: dict) -> str:
    return user.get("full_name") or user.get("email") or "Someone"


class ReviewIn(BaseModel):
    decision: Literal["approve", "changes"]
    reason: str = Field(default="", max_length=300)


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


async def _draft(draft_id: str, user: dict) -> dict:
    doc = await db.drafts.find_one({"id": draft_id, "organization_id": user["organization_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Draft not found")
    return doc


def _out(doc: dict) -> dict:
    return {"id": doc["id"], "status": doc.get("status", "DRAFT"), "review": doc.get("review"), "version": doc.get("version", 1)}


@router.get("/drafts/{draft_id}/review")
async def read_review(draft_id: str, user: dict = Depends(current_user)):
    doc = await _draft(draft_id, user)
    return {**_out(doc), "may_review": can(user, "approve_draft") and doc.get("status") == "WITH_REVIEWER" and await _may_decide(doc, user)}


async def _may_decide(doc: dict, user: dict) -> bool:
    if doc.get("created_by") != user["id"]:
        return True
    return await db.users.count_documents({"organization_id": user["organization_id"], "role": {"$in": list(ROLES)}}) == 1  # a one-person firm has nobody else to ask


@router.post("/drafts/{draft_id}/send-for-review")
async def send_for_review(draft_id: str, user: dict = Depends(current_user)):
    doc = await _draft(draft_id, user)
    if doc.get("created_by") != user["id"] and not can(user, "admin"):
        raise HTTPException(status_code=403, detail="Only the person who wrote this draft, or an admin, can send it for review.")
    if doc.get("status", "DRAFT") not in ("DRAFT", "CHANGES_REQUESTED"):
        raise HTTPException(status_code=409, detail="This draft is already with a reviewer or approved.")
    review = {"requested_by": user["id"], "requested_by_name": name_of(user), "requested_at": now(), "version": doc.get("version", 1)}
    await db.drafts.update_one({"id": draft_id, "organization_id": user["organization_id"]}, {"$set": {"status": "WITH_REVIEWER", "review": review}})
    await audit(user, "DRAFT_SENT_FOR_REVIEW", matter_id=doc.get("matter_id"), detail=doc["title"])
    return _out(await _draft(draft_id, user))


@router.post("/drafts/{draft_id}/review")
async def decide_review(draft_id: str, body: ReviewIn, user: dict = Depends(current_user)):
    doc = await _draft(draft_id, user)
    if doc.get("status") != "WITH_REVIEWER":
        raise HTTPException(status_code=409, detail="This draft has not been sent for review, or it was changed after it was sent. Ask the author to send it again.")
    if not await _may_decide(doc, user):
        raise HTTPException(status_code=403, detail="You wrote this draft, so someone else must review it.")
    reason = body.reason.strip()
    if body.decision == "changes" and not reason:
        raise HTTPException(status_code=422, detail="Say in a line what needs to change.")
    review = {**(doc.get("review") or {}), "decision": body.decision, "decided_by": user["id"], "decided_by_name": name_of(user), "decided_at": now(), "reason": reason, "version": doc.get("version", 1)}
    status = "APPROVED" if body.decision == "approve" else "CHANGES_REQUESTED"
    await db.drafts.update_one({"id": draft_id, "organization_id": user["organization_id"], "status": "WITH_REVIEWER"}, {"$set": {"status": status, "review": review}})
    await audit(user, "DRAFT_APPROVED" if status == "APPROVED" else "DRAFT_CHANGES_REQUESTED", matter_id=doc.get("matter_id"), detail=doc["title"])
    return _out(await _draft(draft_id, user))


@router.get("/drafts/{draft_id}/comments")
async def list_comments(draft_id: str, user: dict = Depends(current_user)):
    await _draft(draft_id, user)
    rows = await db.draft_comments.find({"draft_id": draft_id, "organization_id": user["organization_id"]}, {"_id": 0}).sort("created_at", 1).to_list(MAX_COMMENTS + 1)
    return rows


@router.post("/drafts/{draft_id}/comments", dependencies=[Depends(user_limit("draft-comment", 60, 3600))])
async def add_comment(draft_id: str, body: CommentIn, user: dict = Depends(current_user)):
    doc = await _draft(draft_id, user)
    if await db.draft_comments.count_documents({"draft_id": draft_id, "organization_id": user["organization_id"]}) >= MAX_COMMENTS:
        raise HTTPException(status_code=409, detail=f"A draft can hold {MAX_COMMENTS} comments. Resolve the old ones in a copy of the draft.")
    row = {"id": str(uuid.uuid4()), "organization_id": user["organization_id"], "draft_id": draft_id, "author_id": user["id"], "author_name": name_of(user), "text": body.text.strip(),
           "created_at": now(), "resolved_at": None, "resolved_by_name": None}
    await db.draft_comments.insert_one(dict(row))
    await audit(user, "DRAFT_COMMENT", matter_id=doc.get("matter_id"), detail=doc["title"])
    return row


@router.post("/drafts/{draft_id}/comments/{comment_id}/resolve")
async def resolve_comment(draft_id: str, comment_id: str, user: dict = Depends(current_user)):
    doc = await _draft(draft_id, user)
    row = await db.draft_comments.find_one({"id": comment_id, "draft_id": draft_id, "organization_id": user["organization_id"]}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Comment not found")
    if user["id"] not in (row["author_id"], doc.get("created_by")) and not can(user, "approve_draft"):
        raise HTTPException(status_code=403, detail="Only the person who wrote the comment, the author of the draft or a reviewer can mark it resolved.")
    if row.get("resolved_at"):
        return row
    await db.draft_comments.update_one({"id": comment_id, "organization_id": user["organization_id"]}, {"$set": {"resolved_at": now(), "resolved_by_name": name_of(user)}})
    await audit(user, "DRAFT_COMMENT_RESOLVED", matter_id=doc.get("matter_id"), detail=doc["title"])
    return await db.draft_comments.find_one({"id": comment_id, "organization_id": user["organization_id"]}, {"_id": 0})
