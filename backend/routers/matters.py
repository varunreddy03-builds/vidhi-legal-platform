from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lib.auth import audit, current_user, now
from lib.rbac import can
from lib.db import db
from lib.purge import purge_matter
from models.schemas import (
    AuditEvent,
    DashboardStats,
    Fact,
    FactCreate,
    GraphEdge,
    GraphNode,
    GraphOut,
    Matter,
    MatterCreate,
    MatterUpdate,
    TimelineCreate,
    TimelineEvent,
)

router = APIRouter(tags=["matters"])


async def get_matter(matter_id: str, user: dict) -> dict:
    doc = await db.matters.find_one(
        {"id": matter_id, "organization_id": user["organization_id"]}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Matter not found")
    return doc


async def _check_document_link(document_id: str | None, matter_id: str) -> None:
    """A fact/event may only point at a document that belongs to THIS matter."""
    if document_id and not await db.documents.find_one({"id": document_id, "matter_id": matter_id}):
        raise HTTPException(status_code=422, detail="That document is not part of this matter.")


@router.get("/matters", response_model=list[Matter])
async def list_matters(user: dict = Depends(current_user)):
    docs = (
        await db.matters.find({"organization_id": user["organization_id"]})
        .sort("created_at", -1)
        .to_list(500)
    )
    return [Matter(**d) for d in docs]


@router.post("/matters", response_model=Matter)
async def create_matter(body: MatterCreate, user: dict = Depends(current_user)):
    matter = Matter(
        organization_id=user["organization_id"], created_by=user["id"], **body.model_dump()
    )
    await db.matters.insert_one(matter.model_dump())
    await audit(user, "MATTER_CREATE", matter_id=matter.id, detail=matter.title)
    return matter


@router.get("/matters/{matter_id}", response_model=Matter)
async def read_matter(matter_id: str, user: dict = Depends(current_user)):
    return Matter(**await get_matter(matter_id, user))


@router.patch("/matters/{matter_id}", response_model=Matter)
async def update_matter(matter_id: str, body: MatterUpdate, user: dict = Depends(current_user)):
    current = await get_matter(matter_id, user)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "client_id" in patch:
        if patch["client_id"] and not await db.clients.find_one({"id": patch["client_id"], "organization_id": user["organization_id"]}, {"_id": 1}):
            raise HTTPException(status_code=422, detail="That client record was not found.")
        patch["client_id"] = patch["client_id"] or None
    patch["updated_at"] = now()
    unset: dict = {}
    if patch.get("status") == "CLOSED" and current.get("status") != "CLOSED":
        patch["closed_at"] = now()
    elif patch.get("status") in ("OPEN", "ON_HOLD"):
        unset = {"closed_at": "", "deletion_notice_at": ""}
    await db.matters.update_one({"id": matter_id}, {"$set": patch, **({"$unset": unset} if unset else {})})
    await audit(user, "MATTER_UPDATE", matter_id=matter_id)
    return Matter(**await get_matter(matter_id, user))


@router.delete("/matters/{matter_id}")
async def delete_matter(matter_id: str, user: dict = Depends(current_user)):
    matter = await get_matter(matter_id, user)
    if matter.get("legal_hold"):
        raise HTTPException(status_code=409, detail="This matter is under a legal hold. Remove the hold before deleting it.")
    await purge_matter(matter_id)
    await audit(user, "MATTER_DELETE", matter_id=matter_id)
    return {"ok": True}


class HoldIn(BaseModel):
    on: bool


@router.patch("/matters/{matter_id}/legal-hold", response_model=Matter)
async def set_legal_hold(matter_id: str, body: HoldIn, user: dict = Depends(current_user)):
    """An owner/admin can freeze a matter: it is never deleted by retention or by hand while the hold is on."""
    await get_matter(matter_id, user)
    patch = {"legal_hold": body.on, "updated_at": now()}
    unset = {"deletion_notice_at": ""} if body.on else {}
    await db.matters.update_one({"id": matter_id}, {"$set": patch, **({"$unset": unset} if unset else {})})
    await audit(user, "MATTER_LEGAL_HOLD_ON" if body.on else "MATTER_LEGAL_HOLD_OFF", matter_id=matter_id)
    return Matter(**await get_matter(matter_id, user))


# ---------- facts ----------
@router.get("/matters/{matter_id}/facts", response_model=list[Fact])
async def list_facts(matter_id: str, user: dict = Depends(current_user)):
    await get_matter(matter_id, user)
    docs = await db.facts.find({"matter_id": matter_id}).sort("created_at", -1).to_list(500)
    return [Fact(**d) for d in docs]


@router.post("/matters/{matter_id}/facts", response_model=Fact)
async def create_fact(matter_id: str, body: FactCreate, user: dict = Depends(current_user)):
    await get_matter(matter_id, user)
    await _check_document_link(body.document_id, matter_id)
    fact = Fact(
        matter_id=matter_id,
        organization_id=user["organization_id"],
        created_by=user["id"],
        **body.model_dump(),
    )
    await db.facts.insert_one(fact.model_dump())
    await audit(user, "FACT_CREATE", matter_id=matter_id)
    return fact


@router.delete("/matters/{matter_id}/facts/{fact_id}")
async def delete_fact(matter_id: str, fact_id: str, user: dict = Depends(current_user)):
    await get_matter(matter_id, user)
    res = await db.facts.delete_one({"id": fact_id, "matter_id": matter_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Fact not found")
    await audit(user, "FACT_DELETE", matter_id=matter_id)
    return {"ok": True}


# ---------- timeline ----------
@router.get("/matters/{matter_id}/timeline", response_model=list[TimelineEvent])
async def list_timeline(matter_id: str, user: dict = Depends(current_user)):
    await get_matter(matter_id, user)
    docs = await db.timeline_events.find({"matter_id": matter_id}).sort("event_date", 1).to_list(500)
    return [TimelineEvent(**d) for d in docs]


@router.post("/matters/{matter_id}/timeline", response_model=TimelineEvent)
async def create_event(matter_id: str, body: TimelineCreate, user: dict = Depends(current_user)):
    await get_matter(matter_id, user)
    await _check_document_link(body.document_id, matter_id)
    ev = TimelineEvent(
        matter_id=matter_id, organization_id=user["organization_id"], **body.model_dump()
    )
    await db.timeline_events.insert_one(ev.model_dump())
    await audit(user, "TIMELINE_EVENT_CREATE", matter_id=matter_id)
    return ev


@router.delete("/matters/{matter_id}/timeline/{event_id}")
async def delete_event(matter_id: str, event_id: str, user: dict = Depends(current_user)):
    await get_matter(matter_id, user)
    res = await db.timeline_events.delete_one({"id": event_id, "matter_id": matter_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Event not found")
    await audit(user, "TIMELINE_EVENT_DELETED", matter_id=matter_id, detail=event_id)
    return {"ok": True}


# ---------- graph (real application data only) ----------
@router.get("/matters/{matter_id}/graph", response_model=GraphOut)
async def matter_graph(matter_id: str, user: dict = Depends(current_user)):
    """Typed relationships built only from records that exist: documents, people, evidence, facts, events,
    research claims and the differences noted between sources. No duplicate documents, no generic links."""
    matter = await get_matter(matter_id, user)
    nodes: dict[str, GraphNode] = {matter_id: GraphNode(id=matter_id, label=matter["title"], node_type="MATTER")}
    edges: dict[tuple[str, str, str], GraphEdge] = {}

    def node(n: GraphNode) -> None:
        nodes.setdefault(n.id, n)

    def edge(source: str, target: str, relation: str) -> None:
        if source != target:
            edges.setdefault((source, target, relation), GraphEdge(source=source, target=target, relation=relation))  # type: ignore[arg-type]

    # Documents: the same file uploaded twice (same checksum) is ONE node.
    first_by_checksum: dict[str, str] = {}
    doc_alias: dict[str, str] = {}
    for d in await db.documents.find({"matter_id": matter_id}).sort([("created_at", 1), ("_id", 1)]).to_list(500):
        keep = first_by_checksum.setdefault(d.get("checksum") or d["id"], d["id"])
        doc_alias[d["id"]] = keep
        if keep == d["id"]:
            node(GraphNode(id=d["id"], label=d["filename"], node_type="DOCUMENT", sublabel=d.get("doc_class", "OTHER")))
            edge(d["id"], matter_id, "PART_OF")

    def doc(ref: str | None) -> str | None:
        return doc_alias.get(ref) if ref else None

    for f in await db.facts.find({"matter_id": matter_id}).to_list(300):
        node(GraphNode(id=f["id"], label=f["value"][:70], node_type="FACT", sublabel=f.get("status")))
        edge(f["id"], matter_id, "PART_OF")
        if doc(f.get("document_id")):
            edge(doc(f["document_id"]), f["id"], "EVIDENCES")  # type: ignore[arg-type]

    for e in await db.timeline_events.find({"matter_id": matter_id}).to_list(200):
        node(GraphNode(id=e["id"], label=f"{e['event_date']} — {e['description'][:50]}", node_type="EVENT"))
        edge(e["id"], matter_id, "PART_OF")
        if doc(e.get("document_id")):
            edge(e["id"], doc(e["document_id"]), "DERIVED_FROM")  # type: ignore[arg-type]

    people_by_name: dict[str, str] = {}
    for p in await db.entities.find({"matter_id": matter_id}).to_list(200):
        node(GraphNode(id=p["id"], label=p["name"], node_type="PERSON", sublabel=p.get("role")))
        people_by_name[p["name"].strip().lower()] = p["id"]
        for a in p.get("appearances", []):
            if doc(a.get("document_id")):
                edge(doc(a["document_id"]), p["id"], "MENTIONS")  # type: ignore[arg-type]

    for ev in await db.evidence_items.find({"matter_id": matter_id}).to_list(300):
        node(GraphNode(id=ev["id"], label=ev["label"][:70], node_type="EVIDENCE", sublabel=ev.get("status")))
        if doc(ev.get("document_id")):
            edge(ev["id"], doc(ev["document_id"]), "DERIVED_FROM")  # type: ignore[arg-type]
        else:
            edge(ev["id"], matter_id, "PART_OF")
        who = (ev.get("identified_as") or "").strip().lower()
        if who in people_by_name:
            edge(ev["id"], people_by_name[who], "IDENTIFIED_AS")

    for i in await db.inconsistencies.find({"matter_id": matter_id}).to_list(200):
        a, b = doc(i["a"].get("document_id")), doc(i["b"].get("document_id"))
        if a and b:
            edge(a, b, "CONTRADICTS")

    # Research claims: from the most recent answers only, each distinct claim once.
    seen_claims: set[str] = set()
    for r in await db.research_results.find({"matter_id": matter_id}).sort("created_at", -1).to_list(5):
        for c in r.get("claims", []):
            key = " ".join(c["text"].lower().split())
            if key in seen_claims:
                continue
            seen_claims.add(key)
            node(GraphNode(id=c["id"], label=c["text"][:70], node_type="CLAIM", sublabel=c.get("verification_status")))
            edge(c["id"], matter_id, "PART_OF")
            for cit in c.get("citations", []):
                if cit.get("library_id"):
                    sid = f"src-{cit['library_id']}"
                    node(GraphNode(id=sid, label=cit["citation"][:70], node_type="SOURCE", sublabel="verified library"))
                    edge(c["id"], sid, "CITES")
                elif cit.get("quote_verified") and doc(cit.get("document_id")):
                    edge(doc(cit["document_id"]), c["id"], "SUPPORTS")  # type: ignore[arg-type]

    return GraphOut(nodes=list(nodes.values()), edges=list(edges.values()))

# ---------- audit + dashboard ----------
@router.get("/audit", response_model=list[AuditEvent])
async def audit_log(matter_id: str | None = None, user: dict = Depends(current_user)):
    # The activity of ONE matter is visible to anyone who can see it; the whole organisation's log is admin-only.
    if not matter_id and not can(user, "admin"):
        raise HTTPException(status_code=403, detail="Only an owner or admin can see the organisation-wide activity log.")
    query: dict = {"organization_id": user["organization_id"]}
    if matter_id:
        query["matter_id"] = matter_id
    docs = await db.audit_events.find(query).sort("created_at", -1).to_list(200)
    return [AuditEvent(**d) for d in docs]


@router.get("/dashboard/stats", response_model=DashboardStats)
async def dashboard_stats(user: dict = Depends(current_user)):
    org = user["organization_id"]
    unverified = 0
    for r in await db.research_results.find({"organization_id": org}).to_list(300):
        unverified += sum(
            1 for c in r.get("claims", []) if c.get("verification_status") == "UNSUPPORTED"
        )
    return DashboardStats(
        matters=await db.matters.count_documents({"organization_id": org}),
        documents=await db.documents.count_documents({"organization_id": org}),
        research_sessions=await db.research_results.count_documents({"organization_id": org}),
        drafts=await db.drafts.count_documents({"organization_id": org}),
        unverified_claims=unverified,
    )
