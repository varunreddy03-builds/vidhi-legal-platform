"""Advocate sign-off (lib/reviewers.py has the rules). The operator registers reviewers and records anonymous reviewers' confirmations; a named reviewer confirms with their own account.
Real names and enrolment numbers are returned only to the operator."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib import reviewers
from lib.auth import audit, current_user
from lib.db import db
from lib.platform import require_platform_admin

admin_router = APIRouter(prefix="/admin/legal/reviewers", tags=["admin", "legal"], dependencies=[Depends(require_platform_admin)])
router = APIRouter(tags=["legal"])


class RegisterIn(BaseModel):
    private_name: str = Field(min_length=5, max_length=120)
    enrolment_no: str = Field(min_length=3, max_length=60)
    bar_council: str = Field(default="", max_length=120)
    named_publicly: bool = False
    public_label: str = Field(default="", max_length=60)
    account_email: str = Field(default="", max_length=200)


class ConfirmIn(BaseModel):
    instrument_id: str = Field(min_length=1, max_length=64)
    on: str = Field(min_length=8, max_length=10)
    compared_with_official_text: bool = False


class RecordIn(ConfirmIn):
    reference: str = Field(min_length=5, max_length=200)  # where the reviewer's written confirmation is kept


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@admin_router.post("", status_code=201)
async def register(body: RegisterIn, admin: dict = Depends(require_platform_admin)):
    uid = None
    if body.account_email.strip():
        u = await db.users.find_one({"email": body.account_email.strip().lower()})
        if not u:
            raise HTTPException(status_code=422, detail="No account has that email address. They must sign up first.")
        uid = u["id"]
    try:
        row = await reviewers.register(private_name=body.private_name, enrolment_no=body.enrolment_no, bar_council=body.bar_council, named_publicly=body.named_publicly, public_label=body.public_label, user_id=uid)
    except reviewers.ReviewerError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_REVIEWER_REGISTERED", detail=row["label"])  # the label only, never the real name
    return reviewers.operator_view(row)


@admin_router.get("")
async def operator_list():
    return {"reviewers": [reviewers.operator_view(r) async for r in db.legal_reviewers.find({}).sort("label", 1)], "note": "Real names and enrolment numbers are shown here only."}


@admin_router.post("/{reviewer_id}/record-confirmation")
async def record(reviewer_id: str, body: RecordIn, admin: dict = Depends(require_platform_admin)):
    r = await db.legal_reviewers.find_one({"id": reviewer_id})
    if not r:
        raise HTTPException(status_code=404, detail="Reviewer not found")
    try:
        out = await reviewers.confirm_act(r, body.instrument_id, body.on, compared_with_official_text=body.compared_with_official_text, mode="OPERATOR_RECORDED", recorded_by=admin["id"], reference=body.reference)
    except (reviewers.ReviewerError, ValueError) as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_ACT_CONFIRMED", detail=f"{r['label']}: {out['instrument'][:80]} {out['confirmed']} provisions")
    return out


@router.get("/reviewers")
async def public_reviewers(user: dict = Depends(current_user)):
    """Who has compared the library with the official text, and how much: labels and counts only."""
    return {"reviewers": await reviewers.public_list(), "note": "Reviewers other than those named are shown by code; their identities are kept on file by VIDHI. A confirmation means the reviewer compared the text with the official source; it is not legal advice."}


@router.post("/reviewer/confirm-act")
async def confirm_own(body: ConfirmIn, user: dict = Depends(current_user)):
    """A named reviewer, signed in with their own account, confirms an Act they compared."""
    r = await db.legal_reviewers.find_one({"user_id": user["id"], "active": True})
    if not r:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        out = await reviewers.confirm_act(r, body.instrument_id, body.on, compared_with_official_text=body.compared_with_official_text, mode="SELF", recorded_by=user["id"])
    except (reviewers.ReviewerError, ValueError) as exc:
        raise _bad(exc) from exc
    await audit(user, "LEGAL_ACT_CONFIRMED", detail=f"{r['label']}: {out['instrument'][:80]} {out['confirmed']} provisions")
    return out
