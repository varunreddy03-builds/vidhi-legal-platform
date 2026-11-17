"""Read-only view of the verified law library (entries are added as reviewed files - see data/legal_library/README.md)."""

from fastapi import APIRouter, Depends, HTTPException, Query

from lib import verified_store as vstore
from lib.auth import current_user
from lib.db import db
from lib import legal_search, library, territories, unified_search
from lib.jurisdictions import REGISTRY

router = APIRouter(prefix="/library", tags=["library"])

NONE_LOADED = (
    "No verified law sources have been loaded yet. Legal claims will be shown as UNSUPPORTED until a lawyer "
    "adds verified sources to the library."
)


@router.get("/jurisdictions")
async def jurisdictions(user: dict = Depends(current_user)):
    """Which countries VIDHI covers. Only "live" ones may be described as supported; the rest are the roadmap."""
    return [{"code": j.code, "name": j.name, "status": j.status, "currency": j.currency, "note": j.note} for j in REGISTRY.values()]


@router.get("/territories")
async def territory_registry(user: dict = Depends(current_user)):
    """Every State, Union Territory and High Court VIDHI knows of, with the honest state of its sources (`not_checked` until a person verifies them)."""
    return {"territories": territories.registry(), "note": "The list is general knowledge, not yet confirmed against an official list, and no State or UT source has been verified. Missing coverage never means no law exists."}


@router.get("/search")
async def search_all(q: str = Query("", max_length=300), on_date: str | None = Query(None, max_length=10), territory: str | None = Query(None, max_length=40),
                     limit: int = Query(10, ge=1, le=25), user: dict = Depends(current_user)):
    """One search across the verified library, the structured legal store and the law drafts. Each result says where it comes from and whether anyone has reviewed it;
    only the verified library can say VERIFIED. No AI is used."""
    return await unified_search.search(q, limit=limit, on_date=on_date, territory=territory)


@router.get("/drafts/acts")
async def draft_acts(user: dict = Depends(current_user)):
    """The Acts and Rules that have draft (not reviewed) text, with how many provisions each has."""
    rows = await vstore.aggregate("legal_source_candidates", [
        {"$group": {"_id": "$act_id", "title": {"$first": "$act_title"}, "count": {"$sum": 1}, "legal_currency": {"$first": "$legal_currency"}, "source_url": {"$first": "$source_url"}}},
        {"$sort": {"title": 1}},
    ])
    return {"acts": [{"act_id": r["_id"], "title": r["title"], "count": r["count"], "legal_currency": r.get("legal_currency") or "", "source_url": r.get("source_url") or "",
                      "historical": library.draft_view({"id": "", "citation": "", "legal_currency": r.get("legal_currency") or ""})["historical"]} for r in rows],
            "status": library.PENDING_STATUS, "note": library.DRAFT_NOTE, "enabled": bool(rows),
            "switched_off_note": None if rows else "The law library is switched off until written permission to store and show the official text is recorded (docs/legal-sources-terms.md)."}


@router.get("/drafts")
async def drafts(q: str = Query("", max_length=300), act: str = Query("", max_length=80), skip: int = Query(0, ge=0, le=100000), limit: int = Query(25, ge=1, le=50),
                 user: dict = Depends(current_user)):
    """Search or page through the draft law text. Always labelled not reviewed; it can never verify a claim."""
    if q.strip():
        items = await library.search_drafts(q, k=limit, act_id=act or None, skip=skip)
        return {"items": items, "total": None, "status": library.PENDING_STATUS, "note": library.DRAFT_NOTE}
    flt = {"act_id": act} if act else {}
    rows = await vstore.find_many("legal_source_candidates", flt, {"_id": 0}, sort=[("act_id", 1), ("_id", 1)], skip=skip, limit=limit)
    return {"items": [library.draft_view(d) for d in rows], "total": await vstore.count("legal_source_candidates", flt), "status": library.PENDING_STATUS, "note": library.DRAFT_NOTE}


@router.get("/drafts/{draft_id}")
async def draft_entry(draft_id: str, user: dict = Depends(current_user)):
    d = await vstore.find_one("legal_source_candidates", {"id": draft_id}, {"_id": 0})
    if not d:
        v = await legal_search.provision_view(draft_id)  # a structured provision shown in the same panel
        if v and v["review"]["status"] == "unreviewed":
            return {**legal_search.panel_item(v, excerpt=10**9), "text": v["text"], "text_sha256": library.sha256_text(v["text"]), "oversized": False}
        raise HTTPException(status_code=404, detail="No such draft")
    return {**library.draft_view(d, excerpt=10**9), "text": d.get("text", ""), "text_sha256": d.get("text_sha256", ""), "oversized": d.get("oversized", False)}


@router.get("")
async def library_status(user: dict = Depends(current_user)):
    rows = await vstore.verified_entries(sort=[("citation", 1)], limit=1000)
    pending_count = await vstore.count("legal_source_candidates")
    pending = await vstore.find_many("legal_source_candidates", {}, {"_id": 0, "synced_at": 0, "text": 0}, sort=[("citation", 1)], limit=100)  # a first page only: use /library/drafts to search or page
    return {
        "count": len(rows),
        "pending": pending,  # drafts waiting for a lawyer: always UNVERIFIED, never used to verify a claim
        "pending_count": pending_count,
        "note": "" if rows else NONE_LOADED,
        "entries": [
            {
                "id": r["id"],
                "citation": r["citation"],
                "kind": r["kind"],
                "source_name": r["source_name"],
                "version": r["version"],
                "verified_by": r["verified_by"],
                "verified_on": r["verified_on"],
            }
            for r in rows
        ],
    }


@router.get("/{entry_id}")
async def library_entry(entry_id: str, user: dict = Depends(current_user)):
    rows = await vstore.verified_entries({"id": entry_id}, limit=1)
    r = rows[0] if rows else None
    if not r:
        raise HTTPException(status_code=404, detail="Not in the verified library")
    return {k: r[k] for k in ("id", "citation", "aliases", "kind", "title", "text", "source_name", "source_url", "version", "verified_by", "verified_on", "text_sha256")}
