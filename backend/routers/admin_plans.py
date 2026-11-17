"""The operator's view of the plans (Admin console) and the one way an organisation is put on the Firm plan: by hand, by the operator. No payment is taken and none is recorded here.

  GET  /admin/plans                         the plans now in force (from backend/data/plans.json), whether the file is being used or ignored and why, and which older settings override it
  POST /admin/organisations/{org_id}/plan   put an organisation's owner account(s) on FREE, PRO or FIRM (for a number of months, or until changed)

The same guard as every admin route is declared here too: routes added to another router do not inherit it."""

import os
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib import plan_config, plans
from lib.auth import audit, now
from lib.db import db
from lib.platform import require_platform_admin

admin_router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_platform_admin)])
OVERRIDES = ("FREE_AI_PER_DAY", "PRO_AI_PER_DAY", "FREE_CONTEXT_CHARS", "FREE_AI_PLATFORM_PER_DAY")


class PlanIn(BaseModel):
    plan: Literal["FREE", "PRO", "FIRM"]
    months: int | None = Field(default=None, ge=1, le=60)  # None = until the operator changes it


@admin_router.get("/plans")
async def read_plans(user: dict = Depends(require_platform_admin)):
    return {"file": plan_config.status(), "plans": plans.summary(), "overridden_by_settings": [n for n in OVERRIDES if (os.environ.get(n) or "").strip()],
            "note": "Prices of null are not set: nothing can be bought for them. No payment is taken for the Firm plan."}


@admin_router.post("/organisations/{org_id}/plan")
async def set_plan(org_id: str, body: PlanIn, user: dict = Depends(require_platform_admin)):
    owners = await db.users.find({"organization_id": org_id, "role": "OWNER"}, {"id": 1, "email": 1}).to_list(20)
    if not owners:
        raise HTTPException(status_code=404, detail="No organisation with that id.")
    fields: dict = {"plan": body.plan}
    unset = {"pro_until": ""}
    if body.plan != "FREE" and body.months:
        fields["pro_until"] = now() + timedelta(days=30 * body.months)
        unset = {}
    await db.users.update_many({"organization_id": org_id, "role": "OWNER"}, {"$set": fields, **({"$unset": unset} if unset else {})})
    await audit(user, "ADMIN_ORG_PLAN_SET", detail=f"{org_id} -> {body.plan}" + (f" for {body.months} month(s)" if body.months else ""))
    return {"organization_id": org_id, "plan": body.plan, "owners": len(owners), "until": fields.get("pro_until")}
