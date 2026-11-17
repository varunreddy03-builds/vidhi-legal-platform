"""Notice versions, owner approval, advocate review, and what happened after sending. See lib/notice_workflow.py."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.auth import audit, current_user, now
from lib.db import db
from lib.notice_checks import blockers_for
from lib.notice_workflow import ADVOCATE_DECLARATION, LABELS, approve, current_version, set_state, state_of, who
from lib.rbac import can
from lib.route_checks import check_routes
from routers.recovery import _get_case, _today, blocker_message

router = APIRouter(prefix="/recovery", tags=["recovery-notice"])


def _version_out(v: dict, current_id: str | None) -> dict:
    return {
        "id": v["id"], "number": v["number"], "origin": v["origin"], "sha": v["sha"], "body": v["body"],
        "created_at": v["created_at"], "created_by": v.get("created_by"), "approvals": v.get("approvals", []),
        "is_current": v["id"] == current_id,
    }


def _allowed(case: dict, user: dict, state: str, blocked: bool, needs_advocate: bool) -> list[str]:
    acts: list[str] = []
    if state == "CLOSED" or not case.get("notice_body"):
        return acts
    if can(user, "send_mail") and state in ("DRAFT", "CHANGES_REQUESTED", "ADVOCATE_REVIEW_REQUESTED") and not blocked and not needs_advocate:
        acts.append("approve")
    if can(user, "write") and state in ("DRAFT", "CHANGES_REQUESTED", "APPROVED"):
        acts.append("request_review")
    if can(user, "advocate_review") and state in ("DRAFT", "ADVOCATE_REVIEW_REQUESTED", "CHANGES_REQUESTED", "APPROVED"):
        acts.append("review")
    if can(user, "send_mail"):
        if state == "SENT":
            acts += ["mark_response", "mark_closed"]
        if state == "RESPONSE_RECEIVED":
            acts.append("mark_closed")
        if state in ("SENT", "RESPONSE_RECEIVED", "APPROVED", "DRAFT", "CHANGES_REQUESTED", "ADVOCATE_REVIEW_REQUESTED"):
            acts.append("escalate")
    return acts


@router.get("/cases/{case_id}/notice/workflow")
async def workflow(case_id: str, user: dict = Depends(current_user)):
    case = await _get_case(case_id, user)
    version = await current_version(case)
    if version:
        case = await _get_case(case_id, user)
    wf = case.get("workflow") or {}
    state = state_of(case)
    check = blockers_for(case)
    routes = check_routes(case, _today())
    has_advocate = bool(wf.get("approved") and wf["approved"].get("kind") == "ADVOCATE")
    needs_advocate = routes["blocks_notice"] and not has_advocate
    return {
        "state": state,
        "label": LABELS[state],
        "current_version": ({"id": version["id"], "number": version["number"], "origin": version["origin"], "sha": version["sha"]} if version else None),
        "approved": wf.get("approved"),
        "review_request": wf.get("review"),
        "last_review": wf.get("last_review"),
        "sent": wf.get("sent"),
        "history": list(reversed(wf.get("history", []))),
        "needs_advocate": needs_advocate,
        "needs_advocate_reason": ("A bounced cheque, an existing case or insolvency is involved: an ordinary letter should be reviewed by an advocate before it is approved." if needs_advocate else None),
        "blockers": check,
        "allowed": _allowed(case, user, state, check["blocked"], needs_advocate),
        "advocate_declaration": ADVOCATE_DECLARATION,
        "notes": [
            "Approving a notice means YOU have read it and stand behind its facts. It does not make the notice legally valid.",
            "Only a person who actually reviewed the notice can record an advocate review, and it shows as their own declaration. "
            "VIDHI does not check anyone's qualifications and adds no advocate's name or signature to a notice.",
        ],
    }


@router.get("/cases/{case_id}/notice/versions")
async def versions(case_id: str, user: dict = Depends(current_user)):
    case = await _get_case(case_id, user)
    await current_version(case)
    case = await _get_case(case_id, user)
    cur = (case.get("workflow") or {}).get("current_version_id")
    rows = await db.notice_versions.find({"case_id": case_id, "organization_id": user["organization_id"]}).sort("number", -1).to_list(200)
    return [_version_out(v, cur) for v in rows]


async def _need_current(case_id: str, user: dict) -> tuple[dict, dict]:
    case = await _get_case(case_id, user)
    if not case.get("notice_body"):
        raise HTTPException(status_code=409, detail="Create the demand notice first.")
    state = state_of(case)
    if state == "CLOSED":
        raise HTTPException(status_code=409, detail="This notice process is closed.")
    if state in ("SENT", "ESCALATED", "RESPONSE_RECEIVED"):  # an approval after sending would let the same notice go out again unseen
        raise HTTPException(status_code=409, detail="This notice has already been sent. Edit it to make a new version first if you need to send a different one.")
    version = await current_version(case)
    return await _get_case(case_id, user), version


def _clear_or_409(case: dict) -> None:
    check = blockers_for(case)
    if check["blocked"]:
        raise HTTPException(status_code=409, detail=blocker_message(check))


class ApproveIn(BaseModel):
    version_id: str | None = None  # the version the owner was looking at; refused if it is no longer the current one
    acknowledged: bool = False


@router.post("/cases/{case_id}/notice/approve")
async def approve_notice(case_id: str, body: ApproveIn, user: dict = Depends(current_user)):
    """The owner says: I have read this exact version and I approve sending it."""
    if not body.acknowledged:
        raise HTTPException(status_code=422, detail="Please tick the box to confirm you have read the notice and that its facts are correct.")
    case, version = await _need_current(case_id, user)
    if body.version_id and body.version_id != version["id"]:
        raise HTTPException(status_code=409, detail="The notice has changed since you opened it. Please read the latest version and approve that.")
    _clear_or_409(case)
    wf = case.get("workflow") or {}
    if check_routes(case, _today())["blocks_notice"] and not (wf.get("approved") or {}).get("kind") == "ADVOCATE":
        raise HTTPException(status_code=409, detail="This case needs an advocate's review before the notice can be approved (see the warnings).")
    record = await approve(case, version, user, "OWNER")
    await audit(user, "NOTICE_APPROVE", detail=f"{case_id}: version {version['number']} by owner")
    return {"ok": True, "approved": record}


class ReviewRequestIn(BaseModel):
    note: str = Field(default="", max_length=1000)


@router.post("/cases/{case_id}/notice/request-review")
async def request_review(case_id: str, body: ReviewRequestIn, user: dict = Depends(current_user)):
    """Ask an advocate to look at this version. Nothing is sent to anyone: the request is a flag the team sees."""
    case, version = await _need_current(case_id, user)
    await set_state(
        case_id, "ADVOCATE_REVIEW_REQUESTED", user, f"Advocate review requested for version {version['number']}", body.note.strip(),
        review={"at": now(), "version": version["number"], "note": body.note.strip(), **who(user)}, approved=None,
    )
    await audit(user, "NOTICE_REVIEW_REQUEST", detail=f"{case_id}: version {version['number']}")
    return {"ok": True}


class ReviewIn(BaseModel):
    decision: Literal["APPROVE", "REQUEST_CHANGES"]
    comments: str = Field(default="", max_length=2000)
    declaration: bool = False
    enrolment_no: str = Field(default="", max_length=60)  # typed by the reviewer; never verified or inserted into the notice
    version_id: str | None = None


@router.post("/cases/{case_id}/notice/review")
async def review_notice(case_id: str, body: ReviewIn, user: dict = Depends(current_user)):
    """A reviewing advocate records THEIR decision on the current version, as their own declaration."""
    if not body.declaration:
        raise HTTPException(status_code=422, detail="Tick the declaration to record a review: only an advocate who has read the notice should do this.")
    if body.decision == "REQUEST_CHANGES" and not body.comments.strip():
        raise HTTPException(status_code=422, detail="Say what should change.")
    case, version = await _need_current(case_id, user)
    if body.version_id and body.version_id != version["id"]:
        raise HTTPException(status_code=409, detail="The notice has changed since you opened it. Please read the latest version.")
    if body.decision == "APPROVE":
        _clear_or_409(case)
        record = await approve(
            case, version, user, "ADVOCATE", comments=body.comments.strip(),
            enrolment_no_stated_by_reviewer=body.enrolment_no.strip(), declaration=ADVOCATE_DECLARATION,
        )
        await db.recovery_cases.update_one({"id": case_id}, {"$set": {"workflow.last_review": {**record, "decision": "APPROVE"}}})
    else:
        entry = {
            "decision": "REQUEST_CHANGES", "at": now(), "version": version["number"], "comments": body.comments.strip(),
            "enrolment_no_stated_by_reviewer": body.enrolment_no.strip(), "declaration": ADVOCATE_DECLARATION, **who(user),
        }
        await db.notice_versions.update_one({"id": version["id"]}, {"$push": {"approvals": {**entry, "kind": "ADVOCATE_CHANGES_REQUESTED"}}})
        await set_state(case_id, "CHANGES_REQUESTED", user, f"Changes requested on version {version['number']} (declared advocate review)", body.comments.strip(), last_review=entry, approved=None)
    await audit(user, "NOTICE_ADVOCATE_REVIEW", detail=f"{case_id}: version {version['number']} {body.decision}")
    return {"ok": True}


class MarkIn(BaseModel):
    state: Literal["RESPONSE_RECEIVED", "CLOSED", "ESCALATED"]
    note: str = Field(default="", max_length=1000)


_ALLOWED_FROM = {
    "RESPONSE_RECEIVED": ("SENT",),
    "CLOSED": ("SENT", "RESPONSE_RECEIVED", "ESCALATED"),
    "ESCALATED": ("DRAFT", "ADVOCATE_REVIEW_REQUESTED", "CHANGES_REQUESTED", "APPROVED", "SENT", "RESPONSE_RECEIVED"),
}


@router.post("/cases/{case_id}/notice/mark")
async def mark(case_id: str, body: MarkIn, user: dict = Depends(current_user)):
    """Record what happened next, in the owner's words: a reply came in, the matter is closed, or it was escalated."""
    case = await _get_case(case_id, user)
    state = state_of(case)
    if state not in _ALLOWED_FROM[body.state]:
        raise HTTPException(status_code=409, detail=f"That cannot be recorded while the notice is: {LABELS[state].lower()}.")
    text = {"RESPONSE_RECEIVED": "Response received from the customer", "CLOSED": "Closed", "ESCALATED": "Escalated for further advice or action"}[body.state]
    await set_state(case_id, body.state, user, text, body.note.strip())
    await audit(user, "NOTICE_MARK", detail=f"{case_id}: {body.state}")
    return {"ok": True}
