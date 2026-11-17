"""Pilot feedback: a short form a pilot lawyer fills in, and (in routers/authority.py) a button that marks one Authority Check result as wrong. The operator reads both in the admin
console (routers/admin.py, "Pilot feedback").

Pilot accounts are for sample and public drafts only, never client papers. What is stored here is what the lawyer chose or typed in these forms, plus the reference text the tool found
in the draft (a citation such as a case name or a section number). The sentence around the reference, the draft and any document are NOT copied here."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from lib.auth import audit, current_user, now
from lib.db import db
from lib.ratelimit import user_limit

router = APIRouter(tags=["pilot"])


class FormIn(BaseModel):
    did_task: Literal["yes", "partly", "no"]  # could you paste a draft and read the report?
    understood_report: Literal["yes", "mostly", "no"]
    trust: int = Field(ge=1, le=5)  # how much would you rely on it, 1 (not at all) to 5 (completely)
    would_use: Literal["yes", "maybe", "no"]
    wrong_or_confusing: str = Field(default="", max_length=1000)
    missing: str = Field(default="", max_length=1000)
    other: str = Field(default="", max_length=1000)
    can_contact: bool = False  # the operator may contact me about this feedback


@router.post("/pilot/feedback", dependencies=[Depends(user_limit("pilot-feedback", 20, 86400))])
async def send_feedback(body: FormIn, user: dict = Depends(current_user)):
    row = {
        "id": str(uuid.uuid4()),
        "kind": "form",
        "organization_id": user["organization_id"],
        "user_id": user["id"],
        "user_email": user["email"],
        "answers": {k: (v.strip() if isinstance(v, str) else v) for k, v in body.model_dump().items()},
        "created_at": now(),
    }
    await db.pilot_feedback.insert_one(dict(row))
    await audit(user, "PILOT_FEEDBACK", detail=row["id"][:8])
    return {"ok": True, "id": row["id"]}
