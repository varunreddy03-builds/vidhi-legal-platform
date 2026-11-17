"""Instant decisions (lib/decide.py): which case to look at first, and what kind of help a question looks like. No AI, no cost."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from lib import decide
from lib.auth import current_user
from lib.db import db
from lib.ratelimit import user_limit

router = APIRouter(prefix="/decide", tags=["decide"])


@router.get("/cases")
async def case_priorities(user: dict = Depends(current_user)):
    """Your organisation's open recovery cases, most pressing first, each with the reasons in plain words."""
    rows = await db.recovery_cases.find({"organization_id": user["organization_id"], "status": {"$ne": "RESOLVED"}}).to_list(500)
    out = [{"case_id": r["id"], **decide.case_priority(r)} for r in rows]
    return sorted(out, key=lambda x: -x["score"])


class QuestionIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/question", dependencies=[Depends(user_limit("decide-question", 240, 60))])
async def question_kind(body: QuestionIn, user: dict = Depends(current_user)):
    """What kind of help does this question look like? Words are matched in code; nothing is sent to an AI or stored."""
    return decide.categorise(body.text)