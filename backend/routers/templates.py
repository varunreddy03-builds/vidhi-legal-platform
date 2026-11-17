"""Document templates: list them, read their questions, and turn the answers into an editable draft. Filling is done by code, never by AI."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib import draft_checks, templates as tpl
from lib.auth import audit, current_user
from lib.db import db
from lib.jurisdictions import REGISTRY, is_live
from lib.ratelimit import user_limit
from models.schemas import Draft

router = APIRouter(tags=["templates"])


class DraftFromTemplate(BaseModel):
    values: dict[str, str | int | float | None] = Field(default_factory=dict, max_length=60)
    clauses: list[str] | None = Field(default=None, max_length=30)  # None = the template's own defaults
    matter_id: str | None = Field(default=None, max_length=64)


def _full(t: dict) -> dict:
    return {
        "id": t["id"], "title": t["title"], "description": t["description"], "jurisdiction": t["jurisdiction"], "kind": t["kind"], "language": t["language"], "version": t["version"],
        "review": t["review"], "fields": t["fields"], "clauses": [{"id": c["id"], "label": c["label"], "default": c.get("default", False)} for c in t.get("clauses", [])],
        "lawyer_checks": t.get("lawyer_checks", []),
        "notice": "This is a starting draft, not legal advice. " + ("A lawyer has reviewed the template wording, not your facts." if t["review"]["reviewed"] else "No lawyer has reviewed this template yet."),
    }


@router.get("/templates")
async def list_templates(jurisdiction: str | None = None, user: dict = Depends(current_user)):
    if jurisdiction and jurisdiction not in REGISTRY:
        raise HTTPException(status_code=422, detail="Unknown country code.")
    return tpl.listing(jurisdiction)


@router.get("/templates/{template_id}")
async def read_template(template_id: str, user: dict = Depends(current_user)):
    t = tpl.get(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return _full(t)


@router.post("/templates/{template_id}/draft", response_model=Draft, dependencies=[Depends(user_limit("template-draft", 60, 3600))])
async def make_draft(template_id: str, body: DraftFromTemplate, user: dict = Depends(current_user)):
    t = tpl.get(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    if not is_live(t["jurisdiction"]):
        raise HTTPException(status_code=422, detail=f"VIDHI does not cover {REGISTRY[t['jurisdiction']].name} law yet, so this template cannot be used.")
    if body.matter_id:
        matter = await db.matters.find_one({"id": body.matter_id, "organization_id": user["organization_id"]}, {"id": 1, "jurisdiction_id": 1})
        if not matter:
            raise HTTPException(status_code=404, detail="Matter not found")
        if matter.get("jurisdiction_id", "IN") != t["jurisdiction"]:
            raise HTTPException(status_code=422, detail=f"This template is for {REGISTRY[t['jurisdiction']].name}, but the matter is set to a different country.")
    try:
        out = tpl.render(t, body.values, body.clauses)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    draft = Draft(organization_id=user["organization_id"], created_by=user["id"], matter_id=body.matter_id, title=t["title"], body=out["text"], template_id=t["id"], template_review=t["review"], template_values={k: v for k, v in body.values.items() if v is not None})
    await db.drafts.insert_one(draft.model_dump())
    await audit(user, "TEMPLATE_DRAFT_CREATED", matter_id=body.matter_id, detail=f"{t['id']} v{t['version']} ({t['review']['status']})")
    return draft


class CheckBody(BaseModel):
    body: str | None = Field(default=None, max_length=draft_checks.MAX_CHARS)  # the text as it is on screen (it may not be saved yet); the saved text if left out


@router.post("/drafts/{draft_id}/check")
async def check_draft(draft_id: str, req: CheckBody, user: dict = Depends(current_user)):
    """Flags to fix before the draft is exported or sent. It reads and flags only: nothing is changed or stored, and no AI is used."""
    doc = await db.drafts.find_one({"id": draft_id, "organization_id": user["organization_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Draft not found")
    template = tpl.get(doc["template_id"]) if doc.get("template_id") else None
    flags = draft_checks.check(doc.get("body", "") if req.body is None else req.body, template, doc.get("template_values"))
    return {"flags": flags, "counts": draft_checks.summary(flags), "from_template": bool(template),
            "note": "These flags only point things out. Nothing was changed, and no flag is a legal opinion."}
