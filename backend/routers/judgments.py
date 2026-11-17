"""High Court judgments for looking up (public dataset, CC-BY-4.0). Every record is "not reviewed" and can never verify a claim: see lib/hc_judgments.py."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib import court_hierarchy, hc_judgments, judgment_relations
from lib.auth import audit, current_user
from lib.platform import require_platform_admin

router = APIRouter(prefix="/judgments", tags=["judgments"])
# The operator's routes are added to the admin router (routers/admin.py); they carry the same guard themselves.
admin_router = APIRouter(prefix="/admin/judgments", tags=["admin", "judgments"], dependencies=[Depends(require_platform_admin)])


@router.get("/courts")
async def judgment_courts(user: dict = Depends(current_user)):
    return {"courts": await hc_judgments.courts(), "attribution": hc_judgments.ATTRIBUTION, "note": hc_judgments.NOTE}


@router.get("/states")
async def judgment_states(user: dict = Depends(current_user)):
    """Every State and Union Territory with the High Court code(s) that serve it, and the court levels that have records."""
    return {"states": [{"state": s, "court_codes": court_hierarchy.courts_for_state(s)} for s in court_hierarchy.STATES], "levels": list(court_hierarchy.LEVELS), "levels_with_records": list(court_hierarchy.LOADED_LEVELS),
            "note": "Only the Supreme Court and the High Courts have records. District and lower courts are listed as levels but no data for them is loaded."}


@router.get("")
async def search_judgments(q: str = Query("", max_length=300), court: str = Query("", max_length=20), skip: int = Query(0, ge=0, le=100000), limit: int = Query(20, ge=1, le=50), year_from: int = Query(0, ge=0, le=2100), year_to: int = Query(0, ge=0, le=2100), script: str = Query("", max_length=20), state: str = Query("", max_length=60), court_level: str = Query("", max_length=30), user: dict = Depends(current_user)):
    if script and script not in hc_judgments.SCRIPT_NAMES:
        raise HTTPException(status_code=422, detail=f"Unknown script '{script}'. Use one of: {', '.join(sorted(hc_judgments.SCRIPT_NAMES))}.")
    if court_level and court_level not in court_hierarchy.LEVELS:
        raise HTTPException(status_code=422, detail=f"Unknown court_level '{court_level}'. Use one of: {', '.join(court_hierarchy.LEVELS)}.")
    if state and not court_hierarchy.courts_for_state(state):
        raise HTTPException(status_code=422, detail=f"Unknown State or Union Territory '{state}'. See GET /judgments/states.")
    try:
        items, total = await hc_judgments.search(q, court or None, skip, limit, year_from or None, year_to or None, script or None, state or None, court_level or None)
    except hc_judgments.SearchTooBroad:
        return {"items": [], "total": 0, "total_is_at_least": False, "too_broad": True, "status": hc_judgments.STATUS, "note": "Those words match too many judgments to rank. Add more specific words, a court or a year range.", "attribution": hc_judgments.ATTRIBUTION}
    unranked = any(i.get("ranked") is False for i in items)
    return {"items": items, "total": total, "total_is_at_least": total >= hc_judgments.COUNT_CAP or (bool(q.strip()) and len(items) == limit), "unranked": unranked, "status": hc_judgments.STATUS, "note": hc_judgments.NOTE, "attribution": hc_judgments.ATTRIBUTION}


@router.get("/{judgment_id}")
async def judgment(judgment_id: str, user: dict = Depends(current_user)):
    r = await hc_judgments.get(judgment_id)
    if not r:
        raise HTTPException(status_code=404, detail="No such judgment")
    return r


@router.get("/{judgment_id}/history")
async def judgment_history(judgment_id: str, user: dict = Depends(current_user)):
    """Appeals and how later judgments treated this one, only where a source states it. "Not known" when none does; it never says whether the judgment is still good law."""
    if not await hc_judgments.exists(judgment_id):
        raise HTTPException(status_code=404, detail="No such judgment")
    return await judgment_relations.history(judgment_id)


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


class RelationIn(BaseModel):
    from_id: str = Field(min_length=3, max_length=200)
    relation: str
    target_ref: str = Field(min_length=3, max_length=300)
    source_note: str = Field(min_length=20, max_length=600)
    source_url: str = Field(default="", max_length=500)
    entered_by: str = Field(min_length=5, max_length=120)


class RelationReviewIn(BaseModel):
    reviewed_by: str = Field(min_length=5, max_length=120)
    on: str


class RelationRejectIn(RelationReviewIn):
    reason: str = Field(min_length=10, max_length=1000)


@admin_router.get("/relations")
async def relation_queue(status: str = Query("UNVERIFIED", max_length=12), skip: int = Query(0, ge=0, le=100000), limit: int = Query(25, ge=1, le=50)):
    return await judgment_relations.queue(status, skip, limit)


@admin_router.post("/relations", status_code=201)
async def add_relation(body: RelationIn, admin: dict = Depends(require_platform_admin)):
    try:
        out = await judgment_relations.add_manual(body.from_id, body.relation, body.target_ref, body.source_note, body.source_url, body.entered_by)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "JUDGMENT_RELATION_ADDED", detail=f"{body.relation} on {body.from_id[:60]} by {body.entered_by[:60]}")
    return out


@admin_router.post("/relations/{relation_id}/approve")
async def approve_relation(relation_id: str, body: RelationReviewIn, admin: dict = Depends(require_platform_admin)):
    try:
        out = await judgment_relations.review(relation_id, body.reviewed_by, body.on)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "JUDGMENT_RELATION_REVIEWED", detail=f"{out['relation']} on {out['from_id'][:60]} by {body.reviewed_by[:60]} on {body.on}")
    return out


@admin_router.post("/relations/{relation_id}/reject")
async def reject_relation(relation_id: str, body: RelationRejectIn, admin: dict = Depends(require_platform_admin)):
    try:
        out = await judgment_relations.reject(relation_id, body.reviewed_by, body.on, body.reason)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "JUDGMENT_RELATION_REJECTED", detail=f"{out['relation']} on {out['from_id'][:60]} by {body.reviewed_by[:60]}")
    return out
