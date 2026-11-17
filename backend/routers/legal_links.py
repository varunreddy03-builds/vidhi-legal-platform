"""How legal text connects: amendment history by date, cross-references, forums and remedies, and how later decisions treated earlier ones.

Reading is open to any signed-in user; loading and reviewing is for the platform operator only (admin_router, mounted under /api/admin/legal by routers/admin.py).
Every answer says what it rests on and what it does not: nothing here is verified law until a named lawyer has reviewed the underlying record."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib import verified_store as vstore
from lib import case_law, forums, legal_graph, legal_history
from lib.auth import audit, current_user
from lib.db import db
from lib.platform import require_platform_admin
from lib.ratelimit import user_limit

router = APIRouter(tags=["legal"])
admin_router = APIRouter(prefix="/admin/legal", tags=["admin", "legal"], dependencies=[Depends(require_platform_admin)])


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _day(value: str | None, name: str) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must be a date like 2026-11-05.") from exc


# ------------------------------------------------------------------ reading
@router.get("/legal/history", dependencies=[Depends(user_limit("legal-history", 300, 3600))])
async def history(number: str = Query(min_length=1, max_length=12), instrument: str | None = Query(None, max_length=80), on: str | None = None, user: dict = Depends(current_user)):
    return {"results": await legal_history.history(number.strip().upper(), instrument, _day(on, "on")), "note": legal_history.NOTE}


@router.get("/legal/provisions/{provision_id}/references")
async def references(provision_id: str, user: dict = Depends(current_user)):
    out = await legal_graph.references(provision_id)
    if not out:
        raise HTTPException(status_code=404, detail="Provision not found")
    return out


@router.get("/legal/forums")
async def list_forums(remedy: str | None = Query(None, max_length=100), subject: str | None = Query(None, max_length=100), kind: str | None = None, reviewed_only: bool = False,
                      user: dict = Depends(current_user)):
    rows = await forums.find_forums(remedy, subject, kind, reviewed_only)
    return {"forums": rows, "count": len(rows), "note": forums.LIMIT + (" None of these have been reviewed." if rows and not any(r["review_status"] == "reviewed" for r in rows) else "")}


@router.get("/legal/forums/{forum_id}/chain")
async def forum_chain(forum_id: str, user: dict = Depends(current_user)):
    out = await forums.appeal_chain(forum_id)
    if not out:
        raise HTTPException(status_code=404, detail="Forum not found")
    return out


@router.get("/legal/decisions")
async def find_decision(citation: str = Query(min_length=3, max_length=200), user: dict = Depends(current_user)):
    d = await case_law.find_decision(citation)
    if not d:
        raise HTTPException(status_code=404, detail="That decision is not loaded. That does not mean it does not exist.")
    return d


@router.get("/legal/decisions/{decision_id}/standing")
async def decision_standing(decision_id: str, user: dict = Depends(current_user)):
    out = await case_law.standing(decision_id)
    if not out:
        raise HTTPException(status_code=404, detail="Decision not found")
    return out


@router.get("/legal/forums/{citing_id}/relation/{cited_id}")
async def forum_relation(citing_id: str, cited_id: str, user: dict = Depends(current_user)):
    return await forums.relation(citing_id, cited_id)


# ------------------------------------------------------------------ the operator's routes
class RemedyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    provision_ref: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=500)


class ForumIn(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    kind: str
    level: str = "other"
    territorial: str = Field(default="", max_length=500)
    subject: str = Field(default="", max_length=500)
    pecuniary: str = Field(default="", max_length=500)
    remedies: list[RemedyIn] = Field(default_factory=list, max_length=40)
    source_note: str = Field(min_length=10, max_length=1000)
    parent_id: str | None = None


class ForumPatch(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=200)
    kind: str | None = None
    level: str | None = None
    territorial: str | None = Field(default=None, max_length=500)
    subject: str | None = Field(default=None, max_length=500)
    pecuniary: str | None = Field(default=None, max_length=500)
    remedies: list[RemedyIn] | None = Field(default=None, max_length=40)
    source_note: str | None = Field(default=None, min_length=10, max_length=1000)
    parent_id: str | None = None


class ReviewIn(BaseModel):
    reviewer: str = Field(min_length=5, max_length=120)
    reviewed_on: str


class DecisionIn(BaseModel):
    citation: str = Field(min_length=3, max_length=200)
    title: str = Field(default="", max_length=300)
    forum_id: str | None = None
    decided_on: str | None = None
    source_note: str = Field(min_length=10, max_length=1000)
    pages: list[str] = Field(default_factory=list, max_length=3000)


class TreatmentIn(BaseModel):
    from_decision_id: str
    to_decision_id: str
    treatment: str
    passage: str = Field(min_length=12, max_length=2000)


@admin_router.post("/forums", status_code=201)
async def add_forum(body: ForumIn, admin: dict = Depends(require_platform_admin)):
    try:
        out = await forums.add_forum(body.model_dump())
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_FORUM_ADDED", detail=out["name"][:120])
    return out


@admin_router.patch("/forums/{forum_id}")
async def edit_forum(forum_id: str, body: ForumPatch, admin: dict = Depends(require_platform_admin)):
    try:
        out = await forums.update_forum(forum_id, body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_FORUM_EDITED", detail=forum_id)
    return out


@admin_router.post("/forums/{forum_id}/review")
async def review_forum(forum_id: str, body: ReviewIn, admin: dict = Depends(require_platform_admin)):
    try:
        out = await forums.review_forum(forum_id, body.reviewer, body.reviewed_on)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_FORUM_REVIEWED", detail=forum_id)
    return out


@admin_router.post("/decisions", status_code=201)
async def add_decision(body: DecisionIn, admin: dict = Depends(require_platform_admin)):
    try:
        out = await case_law.add_decision(body.model_dump())
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_DECISION_ADDED", detail=out["citation"][:120])
    return out


@admin_router.post("/treatments", status_code=201)
async def add_treatment(body: TreatmentIn, admin: dict = Depends(require_platform_admin)):
    try:
        out = await case_law.add_treatment(body.from_decision_id, body.to_decision_id, body.treatment, body.passage)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_TREATMENT_ADDED", detail=out["treatment"])
    return out


@admin_router.post("/treatments/{treatment_id}/review")
async def review_treatment(treatment_id: str, body: ReviewIn, admin: dict = Depends(require_platform_admin)):
    try:
        out = await case_law.review_treatment(treatment_id, body.reviewer, body.reviewed_on)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_TREATMENT_REVIEWED", detail=treatment_id)
    return out


@admin_router.post("/graph/rebuild/{version_id}")
async def rebuild_graph(version_id: str, admin: dict = Depends(require_platform_admin)):
    try:
        out = await legal_graph.build_edges(version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await audit(admin, "LEGAL_GRAPH_REBUILT", detail=version_id)
    return out


@admin_router.get("/graph/summary")
async def graph_summary():
    return {"edges": await vstore.count("provision_refs"), "unresolved": await vstore.count("provision_refs", {"resolved": False, "structural": False}),
            "forums": await vstore.count("forums"), "forums_reviewed": await vstore.count("forums", {"review_status": "reviewed"}),
            "decisions": await vstore.count("decisions"), "treatments": await vstore.count("treatments"), "treatments_reviewed": await vstore.count("treatments", {"review_status": "reviewed"})}
