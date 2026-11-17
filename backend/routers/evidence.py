"""Evidence items, the people in a matter, and neutral inconsistencies.

Why this exists: free-text answers can silently leave out an unmatched fingerprint or fail to know who
"the deceased" is because every document used to be read alone. These are structured records the research
answers are required to account for, and every AI-extracted entry must carry a quote that is really in a
document.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from lib.ai import ai_failure, ask_json, log_ai_failure
from lib.auth import audit, current_user, require_intelligence
from lib.plans import gate_ai
from lib.db import db
from lib.matter_context import build_corpus, index_text, select_context
from lib.neutral import neutralize
from lib.safety import fence
from lib.ratelimit import AI_LIMIT
from lib.verify import find_quote, resolve_doc
from models.schemas import (
    Appearance,
    Entity,
    EvidenceItem,
    EvidenceItemCreate,
    EvidenceUpdate,
    Inconsistency,
)
from routers.matters import get_matter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["evidence"])


@router.get("/matters/{matter_id}/evidence", response_model=list[EvidenceItem])
async def list_evidence(matter_id: str, user: dict = Depends(current_user)):
    await get_matter(matter_id, user)
    docs = await db.evidence_items.find({"matter_id": matter_id}).sort("created_at", 1).to_list(500)
    return [EvidenceItem(**d) for d in docs]


async def _document_in_matter(document_id: str | None, matter_id: str) -> dict | None:
    if not document_id:
        return None
    doc = await db.documents.find_one({"id": document_id, "matter_id": matter_id})
    if not doc:
        raise HTTPException(status_code=422, detail="That document is not part of this matter.")
    return doc


@router.post("/matters/{matter_id}/evidence", response_model=EvidenceItem)
async def add_evidence(matter_id: str, body: EvidenceItemCreate, user: dict = Depends(current_user)):
    await get_matter(matter_id, user)
    doc = await _document_in_matter(body.document_id, matter_id)
    page, ok = body.page, False
    if doc and body.quote:
        found = find_quote(body.quote, doc.get("pages", []))
        page, ok = (found, True) if found else (body.page, False)
    item = EvidenceItem(
        matter_id=matter_id,
        organization_id=user["organization_id"],
        **{**body.model_dump(), "page": page},
        quote_verified=ok,
        source="USER",
    )
    await db.evidence_items.insert_one(item.model_dump())
    await audit(user, "EVIDENCE_CREATE", matter_id=matter_id, detail=item.label)
    return item


@router.patch("/matters/{matter_id}/evidence/{item_id}", response_model=EvidenceItem)
async def update_evidence(matter_id: str, item_id: str, body: EvidenceUpdate, user: dict = Depends(current_user)):
    await get_matter(matter_id, user)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if body.identified_as == "":
        patch["identified_as"] = None
    res = await db.evidence_items.update_one({"id": item_id, "matter_id": matter_id}, {"$set": patch})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Evidence item not found")
    await audit(user, "EVIDENCE_UPDATE", matter_id=matter_id, detail=item_id)
    return EvidenceItem(**(await db.evidence_items.find_one({"id": item_id})))


@router.delete("/matters/{matter_id}/evidence/{item_id}")
async def delete_evidence(matter_id: str, item_id: str, user: dict = Depends(current_user)):
    await get_matter(matter_id, user)
    res = await db.evidence_items.delete_one({"id": item_id, "matter_id": matter_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Evidence item not found")
    await audit(user, "EVIDENCE_DELETE", matter_id=matter_id, detail=item_id)
    return {"ok": True}


@router.get("/matters/{matter_id}/entities", response_model=list[Entity])
async def list_entities(matter_id: str, user: dict = Depends(current_user)):
    await get_matter(matter_id, user)
    return [Entity(**d) for d in await db.entities.find({"matter_id": matter_id}).sort("name", 1).to_list(200)]


@router.get("/matters/{matter_id}/inconsistencies", response_model=list[Inconsistency])
async def list_inconsistencies(matter_id: str, user: dict = Depends(current_user)):
    await get_matter(matter_id, user)
    rows = await db.inconsistencies.find({"matter_id": matter_id}).sort("created_at", 1).to_list(200)
    return [Inconsistency(**d) for d in rows]


SYNTH_SCHEMA = (
    '{"people": [{"name": string, "role": string, "aliases": [string], '
    '"appearances": [{"ref": string, "page": number, "quote": string}]}], '
    '"inconsistencies": [{"description": string, '
    '"a": {"ref": string, "page": number, "quote": string}, "b": {"ref": string, "page": number, "quote": string}}], '
    '"unclear": [string]}'
)


@router.post("/matters/{matter_id}/synthesize", dependencies=[Depends(AI_LIMIT)])
async def synthesize_matter(matter_id: str, user: dict = Depends(require_intelligence)):
    """Read ALL the documents together: who is who, and where sources differ. Documents are no longer analysed alone."""
    matter = await get_matter(matter_id, user)
    tier = await gate_ai(user, "synthesize")  # a Pro feature: the free plan is refused here with a clear message
    docs = await db.documents.find({"matter_id": matter_id}).sort([("created_at", 1), ("_id", 1)]).to_list(500)
    if not any(d.get("pages") for d in docs):
        raise HTTPException(status_code=409, detail="Add at least one document with readable text first.")
    corpus = build_corpus(docs)
    text, coverage = select_context("people identity role relationship statement date place", corpus)
    ev = await db.evidence_items.find({"matter_id": matter_id}).to_list(200)
    prompt = (
        fence(f"MATTER: {matter['title']}\nParties: {matter.get('parties', '') or '(not recorded)'}\n{matter.get('description', '')}", "MATTER RECORDS") + "\n\n"
        f"DOCUMENTS:\n{fence(index_text(corpus), 'DOCUMENT LIST')}\n\nPASSAGES:\n{fence(text, 'DOCUMENT PASSAGES')}\n\n"
        + ("EVIDENCE ITEMS ALREADY RECORDED:\n" + fence("\n".join(f"- {e['label']} [{e['status']}]" for e in ev), "EVIDENCE LIST") + "\n\n" if ev else "")
        + "Task: (1) list every person who appears, merging aliases of the same person across documents, with the role "
        "the documents state (write 'not stated' - never guess; if one document names someone as, for example, the "
        "deceased and another only gives a name, connect them ONLY if the text supports it). (2) List places where two "
        "sources differ about the same thing (date, place, amount, who was present...), described neutrally as "
        "'X states ... whereas Y states ...' - never say or imply anyone lied. Every appearance and both sides of every "
        "difference need the document reference (like DOC-03), page, and an EXACT quote copied word-for-word."
    )
    try:
        data = await ask_json(f"synth-{matter_id}", prompt, SYNTH_SCHEMA, purpose="synthesize", tier=tier)
    except Exception as exc:  # noqa: BLE001
        log_ai_failure("matter synthesis", exc)
        await audit(user, "MATTER_SYNTHESIZE", result="FAILED", matter_id=matter_id)
        raise ai_failure(exc) from exc

    adjusted = False

    def appearance(raw: object) -> Appearance | None:
        if not isinstance(raw, dict):
            return None
        d = resolve_doc(str(raw.get("ref", "")), corpus)
        quote = str(raw.get("quote", ""))[:600]
        if not d:
            return None
        page = find_quote(quote, d["pages"])
        if not page:  # the quote is not really in that document -> not evidence, drop it
            return None
        return Appearance(document_id=d["id"], doc_label=d["label"], page=page, quote=quote)

    entities, dropped = [], 0
    for p in data.get("people", []) or []:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        apps = [a for a in (appearance(x) for x in (p.get("appearances") or [])) if a]
        if not apps:
            dropped += 1
            continue
        role, ch = neutralize(str(p.get("role") or "not stated")[:120])
        adjusted = adjusted or ch
        entities.append(
            Entity(
                matter_id=matter_id,
                organization_id=user["organization_id"],
                name=str(p["name"])[:120],
                role=role,
                aliases=[str(a)[:120] for a in (p.get("aliases") or [])][:10],
                appearances=apps,
            )
        )
    incons = []
    for i in data.get("inconsistencies", []) or []:
        if not isinstance(i, dict) or not i.get("description"):
            continue
        a, b = appearance(i.get("a")), appearance(i.get("b"))
        if not (a and b):
            dropped += 1
            continue
        desc, ch = neutralize(str(i["description"])[:600])
        adjusted = adjusted or ch
        incons.append(Inconsistency(matter_id=matter_id, organization_id=user["organization_id"], description=desc, a=a, b=b))

    await db.entities.delete_many({"matter_id": matter_id})
    await db.inconsistencies.delete_many({"matter_id": matter_id})
    if entities:
        await db.entities.insert_many([e.model_dump() for e in entities])
    if incons:
        await db.inconsistencies.insert_many([i.model_dump() for i in incons])
    await audit(user, "MATTER_SYNTHESIZE", matter_id=matter_id, detail=f"people={len(entities)} differences={len(incons)}")
    return {
        "entities": [e.model_dump() for e in entities],
        "inconsistencies": [i.model_dump() for i in incons],
        "unclear": [str(x)[:300] for x in (data.get("unclear") or [])][:10],
        "dropped_unverified": dropped,
        "coverage": coverage,
        "neutral_adjusted": adjusted,
    }
