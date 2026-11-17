"""After a notice goes out: what the provider says, postal dispatch and tracking, the customer's replies, and one
evidence pack to hand to an advocate. Everything here records what happened; nothing claims legal service."""

import json
import tempfile
import uuid
import zipfile
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from lib.auth import audit, current_user, now
from lib import filestore
from lib.db import db
from lib.delivery import LEGAL_NOTE, display_status, evidence_summary
from lib.notice_workflow import current_version, sendable, set_state, state_of, who
from lib.ratelimit import user_limit
from routers.recovery import _get_case, _today

router = APIRouter(prefix="/recovery", tags=["recovery-delivery"])

CHANNELS = ("EMAIL", "WHATSAPP", "SMS", "PHONE_CALL", "POST", "IN_PERSON", "OTHER")


async def _email_rows(case_id: str, org_id: str) -> list[dict]:
    return await db.email_log.find({"case_id": case_id, "organization_id": org_id, "kind": "notice-debtor"}).sort("created_at", 1).to_list(50)


async def _replies(case_id: str) -> list[dict]:
    return await db.case_correspondence.find({"case_id": case_id}).sort("occurred_on", 1).to_list(500)


def _email_out(r: dict) -> dict:
    return {
        "id": r["id"], "to": r["to"], "status": r["status"], "reason": r.get("reason"), "at": r["created_at"],
        "version": r.get("notice_version"), "events": r.get("events", []),
    }


def _corr_out(x: dict) -> dict:
    return {k: x.get(k) for k in ("id", "direction", "channel", "occurred_on", "summary", "proof_id", "is_response", "created_at")} | {
        "logged_by": x.get("logged_by")
    }


@router.get("/cases/{case_id}/notice/delivery")
async def delivery(case_id: str, user: dict = Depends(current_user)):
    case = await _get_case(case_id, user)
    rows = await _email_rows(case_id, user["organization_id"])
    replies = await _replies(case_id)
    postal = case.get("postal", [])
    return {
        "display_status": display_status(state_of(case), rows, postal, replies),
        "emails": [_email_out(r) for r in rows],
        "postal": postal,
        "correspondence": [_corr_out(x) for x in reversed(replies)],
        "evidence": evidence_summary(rows, postal, replies),
        "legal_note": LEGAL_NOTE,
    }


# ---------------------------------------------------------------------------------------------
# Correspondence log: replies and anything else relevant, in the owner's words
# ---------------------------------------------------------------------------------------------
class CorrIn(BaseModel):
    direction: Literal["IN", "OUT"]
    channel: Literal["EMAIL", "WHATSAPP", "SMS", "PHONE_CALL", "POST", "IN_PERSON", "OTHER"]
    occurred_on: str = Field(max_length=10)
    summary: str = Field(min_length=3, max_length=2000)
    proof_id: str | None = None  # an uploaded document (the message itself) this entry refers to
    is_response: bool = False  # the customer's reply to the notice


@router.post("/cases/{case_id}/correspondence")
async def add_correspondence(case_id: str, body: CorrIn, user: dict = Depends(current_user)):
    case = await _get_case(case_id, user)
    try:
        d = date.fromisoformat(body.occurred_on)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="That date is not valid.") from exc
    if d > _today() or d.year < 1990:
        raise HTTPException(status_code=422, detail="That date does not look right.")
    if body.proof_id and not await db.recovery_proofs.find_one({"id": body.proof_id, "case_id": case_id}):
        raise HTTPException(status_code=422, detail="That document is not part of this case.")
    is_response = body.is_response and body.direction == "IN"
    entry = {
        "id": str(uuid.uuid4()), "case_id": case_id, "organization_id": user["organization_id"], "direction": body.direction,
        "channel": body.channel, "occurred_on": d.isoformat(), "summary": body.summary.strip(), "proof_id": body.proof_id,
        "is_response": is_response, "logged_by": {"name": user.get("full_name", ""), "email": user["email"]}, "created_at": now(),
    }
    await db.case_correspondence.insert_one(dict(entry))
    if is_response and state_of(case) == "SENT":
        await set_state(case_id, "RESPONSE_RECEIVED", user, "Response received from the customer", body.summary.strip()[:300])
    await audit(user, "CASE_CORRESPONDENCE", detail=f"{case_id}: {body.direction} {body.channel}")
    return _corr_out(entry)


# ---------------------------------------------------------------------------------------------
# Postal dispatch and tracking, as typed in by the owner (VIDHI does not track parcels itself)
# ---------------------------------------------------------------------------------------------
class PostalIn(BaseModel):
    service: str = Field(min_length=2, max_length=80)  # e.g. Speed Post, registered post, courier name
    tracking_no: str = Field(default="", max_length=60)
    sent_on: str = Field(max_length=10)
    address: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=500)


@router.post("/cases/{case_id}/notice/postal")
async def add_postal(case_id: str, body: PostalIn, user: dict = Depends(current_user)):
    """Record that the APPROVED notice was posted. Only an approved, unchanged version can be recorded as posted."""
    case = await _get_case(case_id, user)
    ok, why = sendable(case, case.get("notice_body") or "")
    state = state_of(case)
    if not (ok or state in ("SENT", "RESPONSE_RECEIVED")):
        raise HTTPException(status_code=409, detail=why or "Approve the current version of the notice before recording that it was posted.")
    try:
        d = date.fromisoformat(body.sent_on)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="That date is not valid.") from exc
    if d > _today() or d.year < 1990:
        raise HTTPException(status_code=422, detail="That date does not look right.")
    ver = await current_version(case)
    entry = {
        "id": str(uuid.uuid4()), "service": body.service.strip(), "tracking_no": body.tracking_no.strip(), "sent_on": d.isoformat(),
        "address": (body.address or case.get("debtor_address") or "").strip(), "note": body.note.strip(),
        "version": ver["number"] if ver else None, "at": now(), "recorded_by": who(user), "updates": [],
    }
    await db.recovery_cases.update_one({"id": case_id}, {"$push": {"postal": {"$each": [entry], "$slice": -20}}})
    label = f"Posted by {entry['service']}" + (f", tracking {entry['tracking_no']}" if entry["tracking_no"] else "")
    if state == "APPROVED":
        await set_state(
            case_id, "SENT", user, label, entry["note"],
            sent={"at": now(), "to": entry["address"], "via": "POST", "version": entry["version"], "sha": (case.get("workflow") or {}).get("approved", {}).get("sha")},
        )
    else:
        from lib.notice_workflow import _event

        await _event(case_id, label, user, entry["note"])
    await audit(user, "NOTICE_POSTAL", detail=f"{case_id}: {entry['service']} {entry['tracking_no']}")
    return entry


class PostalUpdateIn(BaseModel):
    status: str = Field(min_length=2, max_length=200)  # in the owner's words, e.g. "Out for delivery", "Delivered, signed R. Kumar"
    date: str = Field(max_length=10)


@router.post("/cases/{case_id}/notice/postal/{postal_id}/update")
async def update_postal(case_id: str, postal_id: str, body: PostalUpdateIn, user: dict = Depends(current_user)):
    case = await _get_case(case_id, user)
    if not any(p.get("id") == postal_id for p in case.get("postal", [])):
        raise HTTPException(status_code=404, detail="Postal record not found")
    try:
        d = date.fromisoformat(body.date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="That date is not valid.") from exc
    if d > _today() or d.year < 1990:
        raise HTTPException(status_code=422, detail="That date does not look right.")
    upd = {"status": body.status.strip(), "date": d.isoformat(), "at": now(), "recorded_by": who(user)}
    await db.recovery_cases.update_one({"id": case_id, "postal.id": postal_id}, {"$push": {"postal.$.updates": upd}})
    from lib.notice_workflow import _event

    await _event(case_id, f"Postal tracking updated: {upd['status']}", user)
    await audit(user, "NOTICE_POSTAL_UPDATE", detail=f"{case_id}: {upd['status']}")
    return upd


# ---------------------------------------------------------------------------------------------
# Evidence pack
# ---------------------------------------------------------------------------------------------
def _clean(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in ("_id", "gridfs_id", "excerpt")}


@router.get("/cases/{case_id}/evidence-pack.zip", dependencies=[Depends(user_limit("evidence-pack", 10, 3600))])
async def evidence_pack(case_id: str, user: dict = Depends(current_user)):
    """Everything about this notice in one zip for the owner or their advocate: it records, it does not prove service."""
    case = await _get_case(case_id, user)
    await current_version(case)
    case = await _get_case(case_id, user)
    org = user["organization_id"]
    rows = await _email_rows(case_id, org)
    replies = await _replies(case_id)
    proofs = await db.recovery_proofs.find({"case_id": case_id}).sort("created_at", 1).to_list(500)
    versions = await db.notice_versions.find({"case_id": case_id}).sort("number", 1).to_list(500)
    tmp = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
    dump = lambda o: json.dumps(o, default=str, indent=1)  # noqa: E731
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", (
            "VIDHI evidence pack\n\nThis file records what the owner entered and what VIDHI observed. It is not legal advice and "
            "it does not prove that any notice was served or received.\n\n" + LEGAL_NOTE + "\n"
        ))
        z.writestr("case.json", dump(_clean({k: v for k, v in case.items() if k not in ("notice_body", "workflow", "postal")})))
        for v in versions:
            z.writestr(f"notice-versions/version-{v['number']:02d}.txt", v["body"])
        z.writestr("notice-versions/index.json", dump([{k: v for k, v in x.items() if k not in ("_id", "body")} for x in versions]))
        z.writestr("workflow-history.json", dump((case.get("workflow") or {}).get("history", [])))
        z.writestr("email-delivery.json", dump([_email_out(r) for r in rows]))
        z.writestr("postal.json", dump(case.get("postal", [])))
        z.writestr("correspondence.json", dump([_corr_out(x) for x in replies]))
        z.writestr("delivery-summary.json", dump(evidence_summary(rows, case.get("postal", []), replies)))
        z.writestr("documents/index.json", dump([_clean(p) for p in proofs]))
        for p in proofs:
            if not p.get("gridfs_id"):
                continue
            try:
                z.writestr(f"documents/{p['id']}-{p['filename']}", await filestore.read(p["gridfs_id"]))
            except Exception:  # noqa: BLE001
                z.writestr(f"documents/{p['id']}-MISSING.txt", "The stored file could not be read.")
    size = tmp.tell()
    tmp.seek(0)
    await audit(user, "EVIDENCE_PACK", detail=f"{case_id}: {size} bytes")

    def chunks():
        try:
            while True:
                b = tmp.read(1024 * 1024)
                if not b:
                    break
                yield b
        finally:
            tmp.close()

    return StreamingResponse(
        chunks(), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="evidence-pack-{case_id[:8]}.zip"', "Content-Length": str(size)},
    )
