"""AI-generated illustrations: rare, Pro only, capped, labelled, and never evidence. See lib/imagegen.py."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from lib import aibudget, filestore, imagegen
from lib.ai import ai_failure, failure_label
from lib.auth import audit, current_user, entitlement_for, now
from lib.db import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/images", tags=["images"])


def _month() -> str:
    return now().strftime("%Y-%m")


async def _used(org_id: str) -> int:
    row = await db.image_usage.find_one({"_id": f"{org_id}:{_month()}"})
    return int(row["n"]) if row else 0


@router.get("/status")
async def status(user: dict = Depends(current_user)):
    pro = entitlement_for(user)["tier"] in ("pro", "firm")
    cap = imagegen.monthly_cap()
    return {"enabled": imagegen.enabled() and pro, "pro_only": True, "cap": cap, "remaining": max(0, cap - await _used(user["organization_id"])) if pro else 0}


class GenerateIn(BaseModel):
    prompt: str = Field(min_length=5, max_length=imagegen.MAX_PROMPT)


@router.post("/generate")
async def generate(body: GenerateIn, user: dict = Depends(current_user)):
    if not imagegen.enabled():
        raise HTTPException(status_code=404, detail="Illustrations are not switched on.")
    if entitlement_for(user)["tier"] not in ("pro", "firm"):
        raise HTTPException(status_code=402, detail="Illustrations are part of the Pro plan.")
    await aibudget.ensure_available(user)
    why = imagegen.refusal(body.prompt)
    if why:
        raise HTTPException(status_code=422, detail=why)
    org, cap = user["organization_id"], imagegen.monthly_cap()
    # reserve one of this month's pictures first (atomic), so two requests at once cannot both slip under the cap
    row = await db.image_usage.find_one_and_update({"_id": f"{org}:{_month()}"}, {"$inc": {"n": 1}, "$setOnInsert": {"organization_id": org}}, upsert=True, return_document=True)
    if row["n"] > cap:
        await db.image_usage.update_one({"_id": row["_id"]}, {"$inc": {"n": -1}})
        raise HTTPException(status_code=429, detail=f"Your organisation has used its {cap} illustrations for this month.")
    try:
        png = await imagegen.generate(body.prompt)
    except Exception as exc:  # noqa: BLE001 - a failed attempt does not use up an illustration
        await db.image_usage.update_one({"_id": row["_id"]}, {"$inc": {"n": -1}})
        if isinstance(exc, aibudget.BudgetExceeded):
            raise ai_failure(exc) from exc  # a reached spending cap says so
        logger.warning("illustration failed: %s", failure_label(exc))  # the class and status only: the provider's message can repeat the prompt
        raise HTTPException(status_code=502, detail="We could not make that illustration just now. It was not counted. Please try again later.") from exc
    image_id = str(uuid.uuid4())
    file_id = await filestore.put(f"{image_id}.png", png, {"organization_id": org, "kind": "illustration"})
    await db.generated_images.insert_one({"id": image_id, "organization_id": org, "created_by": user["id"], "prompt": body.prompt.strip(), "gridfs_id": file_id, "model": "image", "created_at": now()})
    await audit(user, "IMAGE_GENERATED", detail=image_id)
    return {"id": image_id, "label": "AI-generated illustration. It is not evidence.", "remaining": max(0, cap - row["n"])}


@router.get("/{image_id}")
async def get_image(image_id: str, user: dict = Depends(current_user)):
    row = await db.generated_images.find_one({"id": image_id, "organization_id": user["organization_id"]})
    if not row:
        raise HTTPException(status_code=404, detail="Picture not found")
    return Response(content=await filestore.read(row["gridfs_id"]), media_type="image/png", headers={"X-AI-Generated": "true", "Cache-Control": "private, no-store", "Content-Disposition": f'inline; filename="ai-illustration-{image_id[:8]}.png"'})