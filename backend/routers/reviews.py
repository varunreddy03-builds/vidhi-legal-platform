"""Review requests: ask a colleague to review a research result, a draft, a document or its analysis, and record their decision.

It is a hand-off between people in the SAME organisation; the program decides nothing about the item. The reviewer must be an owner, admin or lawyer of the firm who is not the requester (a one-person firm can ask
itself, as with draft approval). One decision per request, recorded with who and when, and the activity log notes it. Everything is tied to the matter and the organisation."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.auth import audit, current_user, now
from lib.db import db
from lib.rbac import can

router = APIRouter(tags=["reviews"])

KINDS = {"research": "research_results", "draft": "drafts", "document": "documents", "analysis": "documents"}
MAX_OPEN_PER_MATTER = 200


class ReviewIn(BaseModel):
    kind: Literal["research", "draft", "document", "analysis"]
    ref_id: str = Field(min_length=1, max_length=64)
    reviewer_id: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", max_length=1000)


class DecisionIn(BaseModel):
    decision: Literal["APPROVED", "CHANGES_REQUESTED"]
    comment: str = Field(default="", max_length=2000)


def _public(r: dict) -> dict:
    return {k: v for k, v in r.items() if k not in ("_id", "organization_id")}


async def _matter(matter_id: str, user: dict) -> dict:
    m = await db.matters.find_one({"id": matter_id, "organization_id": user["organization_id"]})
    if not m:
        raise HTTPException(status_code=404, detail="Matter not found")
    return m


async def _reviewers(user: dict) -> list[dict]:
    rows = await db.users.find({"organization_id": user["organization_id"], "role": {"$in": ["OWNER", "ADMIN", "LAWYER"]}}, {"id": 1, "full_name": 1, "role": 1}).to_list(500)
    return [{"id": r["id"], "name": r.get("full_name", ""), "role": r["role"]} for r in rows]


@router.get("/matters/{matter_id}/reviews/reviewers")
async def reviewer_choices(matter_id: str, user: dict = Depends(current_user)):
    await _matter(matter_id, user)
    people = await _reviewers(user)
    only_me = len(people) == 1 and people[0]["id"] == user["id"]
    return {"reviewers": [p for p in people if only_me or p["id"] != user["id"]]}


@router.post("/matters/{matter_id}/reviews", status_code=201)
async def request_review(matter_id: str, body: ReviewIn, user: dict = Depends(current_user)):
    await _matter(matter_id, user)
    org = user["organization_id"]
    item = await db[KINDS[body.kind]].find_one({"id": body.ref_id, "matter_id": matter_id, "organization_id": org}, {"id": 1})
    if not item:
        raise HTTPException(status_code=404, detail="That item is not in this matter")
    choices = {p["id"]: p for p in await _reviewers(user)}
    reviewer = choices.get(body.reviewer_id)
    if not reviewer:
        raise HTTPException(status_code=422, detail="Choose an owner, admin or lawyer of your firm as the reviewer.")
    if reviewer["id"] == user["id"] and len(choices) > 1:
        raise HTTPException(status_code=422, detail="Ask a colleague, not yourself.")
    if await db.reviews.count_documents({"matter_id": matter_id, "organization_id": org, "status": "REQUESTED"}) >= MAX_OPEN_PER_MATTER:
        raise HTTPException(status_code=409, detail="Too many reviews are waiting on this matter.")
    if await db.reviews.find_one({"matter_id": matter_id, "organization_id": org, "kind": body.kind, "ref_id": body.ref_id, "reviewer_id": reviewer["id"], "status": "REQUESTED"}):
        raise HTTPException(status_code=409, detail="This reviewer already has a request for that item.")
    row = {"id": str(uuid.uuid4()), "organization_id": org, "matter_id": matter_id, "kind": body.kind, "ref_id": body.ref_id, "reviewer_id": reviewer["id"], "reviewer_name": reviewer["name"],
           "requested_by": user["id"], "requested_by_name": user.get("full_name", ""), "note": " ".join(body.note.split()), "status": "REQUESTED", "decision_comment": "", "created_at": now(), "decided_at": None}
    await db.reviews.insert_one(row)
    await audit(user, "REVIEW_REQUESTED", matter_id=matter_id, detail=body.kind)
    return _public(row)


@router.get("/matters/{matter_id}/reviews")
async def matter_reviews(matter_id: str, user: dict = Depends(current_user)):
    await _matter(matter_id, user)
    rows = await db.reviews.find({"matter_id": matter_id, "organization_id": user["organization_id"]}).sort("created_at", -1).to_list(500)
    return {"reviews": [_public(r) for r in rows]}


@router.get("/reviews/mine")
async def my_reviews(user: dict = Depends(current_user)):
    """Requests waiting for me, across the firm's matters."""
    rows = await db.reviews.find({"organization_id": user["organization_id"], "reviewer_id": user["id"], "status": "REQUESTED"}).sort("created_at", 1).to_list(200)
    return {"reviews": [_public(r) for r in rows]}


@router.post("/reviews/{review_id}/decision")
async def decide(review_id: str, body: DecisionIn, user: dict = Depends(current_user)):
    if not can(user, "approve_draft"):
        raise HTTPException(status_code=403, detail="Not allowed")
    if body.decision == "CHANGES_REQUESTED" and len(body.comment.strip()) < 3:
        raise HTTPException(status_code=422, detail="Say what should change.")
    got = await db.reviews.find_one_and_update(
        {"id": review_id, "organization_id": user["organization_id"], "reviewer_id": user["id"], "status": "REQUESTED"},
        {"$set": {"status": body.decision, "decision_comment": " ".join(body.comment.split()), "decided_at": now()}}, return_document=True)
    if not got:
        raise HTTPException(status_code=404, detail="No open review request for you with that id")
    await audit(user, "REVIEW_DECIDED", matter_id=got["matter_id"], detail=body.decision)
    return _public(got)
