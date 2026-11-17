"""Versions and approval of a demand notice.

Every change to the notice text (the AI draft, an owner's edit, an advocate's edit) is a NEW immutable version; earlier
versions are never altered or deleted (until the whole case is deleted). Approval attaches to ONE version and is
cleared the moment the text changes, so what was approved is exactly what can be sent.

States:  DRAFT -> ADVOCATE_REVIEW_REQUESTED -> CHANGES_REQUESTED / APPROVED -> SENT -> RESPONSE_RECEIVED -> CLOSED,
and ESCALATED from anywhere before CLOSED.

Honesty rules enforced here:
  * an "advocate" approval exists only if a signed-in person performed that action and ticked the declaration; it is
    recorded as THEIR declaration, any enrolment number is shown as "stated by the reviewer, not verified by VIDHI",
    and nothing is added to the notice itself (no name, signature or registration is ever inserted for them);
  * an ordinary case may go out on the owner's own approval; a case with a STOP warning (lib/route_checks.py) needs an
    advocate's approval first.
"""

import uuid

from pymongo.errors import DuplicateKeyError

from lib.auth import now
from lib.db import db
from lib.outbound import sha256

STATES = (
    "DRAFT", "ADVOCATE_REVIEW_REQUESTED", "CHANGES_REQUESTED", "APPROVED", "SENT", "RESPONSE_RECEIVED", "CLOSED", "ESCALATED",
)
LABELS = {
    "DRAFT": "Draft - awaiting approval",
    "ADVOCATE_REVIEW_REQUESTED": "Advocate review requested",
    "CHANGES_REQUESTED": "Changes requested",
    "APPROVED": "Approved for sending",
    "SENT": "Sent",
    "RESPONSE_RECEIVED": "Response received",
    "CLOSED": "Closed",
    "ESCALATED": "Escalated",
}
ADVOCATE_DECLARATION = "Declared by the reviewer: I am an advocate and I have read this notice and reviewed it."
MAX_HISTORY = 200


def who(user: dict) -> dict:
    return {"user_id": user["id"], "name": user.get("full_name", ""), "email": user["email"], "role": user.get("role", "")}


def state_of(case: dict) -> str:
    return ((case.get("workflow") or {}).get("state")) or "DRAFT"


async def _event(case_id: str, event: str, user: dict | None, note: str = "", **extra) -> None:
    entry = {"at": now(), "event": event, "note": note, **extra}
    if user:
        entry["by"] = {"name": user.get("full_name", ""), "email": user["email"]}
    await db.recovery_cases.update_one(
        {"id": case_id}, {"$push": {"workflow.history": {"$each": [entry], "$slice": -MAX_HISTORY}}}
    )


async def add_version(case: dict, body: str, origin: str, user: dict, meta: dict | None = None) -> dict:
    """Store `body` as the next version, make it current, and drop any approval (a new text is unapproved)."""
    version = None
    for _ in range(6):  # two edits at the same moment must not get the same number: the unique index refuses the second, which then takes the next one
        last = await db.notice_versions.find({"case_id": case["id"]}).sort("number", -1).limit(1).to_list(1)
        number = (last[0]["number"] if last else 0) + 1
        version = {
            "id": str(uuid.uuid4()),
            "case_id": case["id"],
            "organization_id": case["organization_id"],
            "number": number,
            "body": body,
            "sha": sha256(body),
            "origin": origin,  # AI_DRAFT | TEMPLATE | EDIT | LEGACY
            "created_by": who(user) if user else None,
            "created_at": now(),
            "meta": meta or {},
            "approvals": [],
        }
        try:
            await db.notice_versions.insert_one(dict(version))
            break
        except DuplicateKeyError:
            continue
    else:
        raise RuntimeError("could not number the new notice version")
    await db.recovery_cases.update_one(
        {"id": case["id"]},
        {"$set": {"workflow.state": "DRAFT", "workflow.current_version_id": version["id"], "workflow.approved": None}},
    )
    await _event(case["id"], f"Version {number} created ({origin.replace('_', ' ').lower()})", user, version=number)
    return version


async def current_version(case: dict) -> dict | None:
    """The version matching the case's notice text. Cases made before versions existed get a LEGACY version 1."""
    body = case.get("notice_body") or ""
    if not body:
        return None
    vid = (case.get("workflow") or {}).get("current_version_id")
    if vid:
        v = await db.notice_versions.find_one({"id": vid, "case_id": case["id"]})
        if v and v["sha"] == sha256(body):
            return v
    v = await db.notice_versions.find_one({"case_id": case["id"], "sha": sha256(body)}, sort=[("number", -1)])
    if v:
        await db.recovery_cases.update_one({"id": case["id"]}, {"$set": {"workflow.current_version_id": v["id"]}})
        return v
    return await _legacy(case, body)


async def _legacy(case: dict, body: str) -> dict:
    """A notice written before versions existed becomes version 1 (origin LEGACY); state and approval are left alone."""
    last = await db.notice_versions.find({"case_id": case["id"]}).sort("number", -1).limit(1).to_list(1)
    number = (last[0]["number"] if last else 0) + 1
    version = {
        "id": str(uuid.uuid4()), "case_id": case["id"], "organization_id": case["organization_id"], "number": number,
        "body": body, "sha": sha256(body), "origin": "LEGACY", "created_by": None, "created_at": now(), "meta": {}, "approvals": [],
    }
    await db.notice_versions.insert_one(dict(version))
    await db.recovery_cases.update_one({"id": case["id"]}, {"$set": {"workflow.current_version_id": version["id"]}})
    return version

def sendable(case: dict, notice_body: str) -> tuple[bool, str]:
    """May this exact text be emailed now? Only an approved, unchanged version, never one already sent and delivered."""
    wf = case.get("workflow") or {}
    state = wf.get("state") or "DRAFT"
    ap = wf.get("approved") or {}
    if state == "CLOSED":
        return False, "This notice process is closed."
    if case.get("status") == "RESOLVED":
        return False, "This case is marked as paid or resolved. Reopen it before sending a notice."
    resend_ok = state == "SENT" and case.get("debtor_email_status") in ("BOUNCED", "FAILED")
    if state != "APPROVED" and not resend_ok:
        if state == "SENT":
            return False, "This notice was already sent. Edit it to create a new version if you need to send a different one."
        return False, "Approve the current version of the notice first. Until then it is only a draft."
    if not ap or ap.get("sha") != sha256(notice_body):
        return False, "The approval no longer matches the notice text. Please approve the current version."
    return True, ""


async def approve(case: dict, version: dict, user: dict, kind: str, **extra) -> dict:
    record = {
        "kind": kind, "version_id": version["id"], "version": version["number"], "sha": version["sha"],
        "at": now(), **who(user), **extra,
    }
    await db.notice_versions.update_one({"id": version["id"]}, {"$push": {"approvals": record}})
    await db.recovery_cases.update_one(
        {"id": case["id"]}, {"$set": {"workflow.state": "APPROVED", "workflow.approved": record}}
    )
    label = "Approved by the owner" if kind == "OWNER" else "Approved after advocate review (declared by the reviewer)"
    await _event(case["id"], f"{label}: version {version['number']}", user, version=version["number"])
    return record


async def set_state(case_id: str, state: str, user: dict, event: str, note: str = "", **extra) -> None:
    await db.recovery_cases.update_one({"id": case_id}, {"$set": {"workflow.state": state, **{f"workflow.{k}": v for k, v in extra.items()}}})
    await _event(case_id, event, user, note)
