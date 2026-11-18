"""Sharing a matter's graph with its client, as a filtered snapshot (lib/graph_share.py has the rules)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from lib.auth import audit, current_user, now
from lib.db import db
from lib.graph_share import filter_graph
from routers.matters import matter_graph
from routers.portal import client_matter

router = APIRouter(tags=["portal"])


async def _matter(matter_id: str, user: dict) -> dict:
    m = await db.matters.find_one({"id": matter_id, "organization_id": user["organization_id"]})
    if not m:
        raise HTTPException(status_code=404, detail="Matter not found")
    return m


async def _live(matter_id: str, user: dict) -> dict:
    full = await matter_graph(matter_id, user)
    shared = {s["document_id"] async for s in db.portal_shares.find({"matter_id": matter_id, "organization_id": user["organization_id"]}, {"document_id": 1})}
    return filter_graph([n.model_dump() for n in full.nodes], [e.model_dump() for e in full.edges], matter_id, shared)


def _stamp(d) -> str:
    return d.isoformat() if getattr(d, "tzinfo", None) else d.isoformat() + "+00:00"


def _out(row: dict | None) -> dict | None:
    return {"nodes": row["nodes"], "edges": row["edges"], "shared_at": _stamp(row["shared_at"]), "shared_by": row.get("shared_by_name", "")} if row else None


@router.get("/matters/{matter_id}/portal/graph")
async def graph_for_firm(matter_id: str, user: dict = Depends(current_user)):
    """What a client would see if it were published now (preview), and what is published."""
    await _matter(matter_id, user)
    row = await db.portal_graphs.find_one({"matter_id": matter_id, "organization_id": user["organization_id"]})
    return {"preview": await _live(matter_id, user), "shared": _out(row),
            "note": "A client sees only this: the matter, the documents you have shared with them, and the people and dates found in those documents. Never claims, contradictions, evidence or facts."}


@router.put("/matters/{matter_id}/portal/graph")
async def publish_graph(matter_id: str, user: dict = Depends(current_user)):
    await _matter(matter_id, user)
    g = await _live(matter_id, user)
    row = {"id": str(uuid.uuid4()), "organization_id": user["organization_id"], "matter_id": matter_id, "nodes": g["nodes"], "edges": g["edges"], "shared_by": user["id"], "shared_by_name": user.get("full_name", ""), "shared_at": now()}
    await db.portal_graphs.replace_one({"matter_id": matter_id, "organization_id": user["organization_id"]}, row, upsert=True)
    await audit(user, "PORTAL_GRAPH_SHARED", matter_id=matter_id, detail=f"{len(g['nodes'])} items")
    return _out(row)


@router.delete("/matters/{matter_id}/portal/graph")
async def withdraw_graph(matter_id: str, user: dict = Depends(current_user)):
    await _matter(matter_id, user)
    n = (await db.portal_graphs.delete_many({"matter_id": matter_id, "organization_id": user["organization_id"]})).deleted_count
    await audit(user, "PORTAL_GRAPH_WITHDRAWN", matter_id=matter_id)
    return {"withdrawn": n}


@router.get("/portal/matters/{matter_id}/graph")
async def graph_for_client(matter_id: str, user: dict = Depends(current_user)):
    await client_matter(user, matter_id)
    row = await db.portal_graphs.find_one({"matter_id": matter_id, "organization_id": user["organization_id"]})
    if row:
        await audit(user, "PORTAL_GRAPH_VIEWED", matter_id=matter_id)
    return {"graph": _out(row)}
