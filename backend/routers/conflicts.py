"""Conflict-of-interest check (lib/conflicts.py): compares names with this organisation's own records. Read-only."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from lib import conflicts
from lib.auth import audit, current_user
from lib.ratelimit import user_limit

router = APIRouter(tags=["conflicts"])


class CheckIn(BaseModel):
    names: list[str] = Field(min_length=1, max_length=10, description="the prospective client and the other parties, one name each")


@router.post("/conflicts/check", dependencies=[Depends(user_limit("conflict-check", 120, 3600))])
async def run_check(body: CheckIn, user: dict = Depends(current_user)):
    names = [n.strip() for n in body.names if 2 <= len(n.strip()) <= 200]
    if not names:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="Enter at least one name of two or more letters.")
    out = await conflicts.check(user["organization_id"], names[:10])
    # the audit line records that a check happened and how many possible matches it found, never the names searched for
    await audit(user, "CONFLICT_CHECK", detail=f"{len(names)} name(s), {sum(r['total_matches'] for r in out['results'])} possible match(es)")
    return out