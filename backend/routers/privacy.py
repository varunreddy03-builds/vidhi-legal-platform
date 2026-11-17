"""Privacy: the operator's configured details, and data-rights requests (access, correction, erasure, nomination, withdrawing consent, grievance).

The process is described to people as aligned with the rights in India's Digital Personal Data Protection Act, 2023, as a summary to be confirmed by a lawyer;
nothing here is a statement that any law has been complied with. A request is recorded, acknowledged by email, and routed to the grievance contact; the
owner handles it in the admin console. People can also download their own data at once."""

import logging
import uuid
from datetime import timedelta
from html import escape
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from lib import business
from lib.auth import audit, current_user, now
from lib.db import db
from lib.email import send_email
from lib.ratelimit import user_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["privacy"])

KINDS = {
    "ACCESS": "A copy of the personal data we hold about me",
    "CORRECTION": "Correct something that is wrong or out of date",
    "ERASURE": "Erase my personal data",
    "WITHDRAW_CONSENT": "Withdraw a consent I gave",
    "NOMINATION": "Nominate someone to exercise my rights on my behalf",
    "GRIEVANCE": "A complaint or grievance about how my data is handled",
}


@router.get("/public/legal-config")
async def legal_config():
    """What the operator has configured for the legal pages. Anything not configured is null: the pages show a visible placeholder."""
    return {"config": business.public_config(), "missing": business.missing(), "response_days": business.response_days()}


class RequestIn(BaseModel):
    kind: Literal["ACCESS", "CORRECTION", "ERASURE", "WITHDRAW_CONSENT", "NOMINATION", "GRIEVANCE"]
    details: str = Field(default="", max_length=2000)


def _row(r: dict) -> dict:
    return {k: r.get(k) for k in ("id", "kind", "details", "status", "created_at", "due_by", "closed_at", "outcome")}


@router.post("/privacy/requests", dependencies=[Depends(user_limit("privacy-request", 5, 86400))])
async def create_request(body: RequestIn, user: dict = Depends(current_user)):
    rid, created = str(uuid.uuid4()), now()
    doc = {
        "id": rid, "user_id": user["id"], "organization_id": user["organization_id"], "email": user["email"], "kind": body.kind, "details": body.details.strip(),
        "status": "RECEIVED", "created_at": created, "due_by": created + timedelta(days=business.response_days()), "events": [{"at": created, "what": "Received"}],
    }
    await db.data_requests.insert_one(dict(doc))
    await audit(user, "PRIVACY_REQUEST", detail=f"{body.kind} {rid}")
    routed_to = business.get("privacy_email") or business.get("grievance_email")
    label = KINDS[body.kind]
    try:  # an acknowledgement to the person who asked (best effort: the request is saved either way)
        await send_email(to=user["email"], subject="We received your data request", html=(
            f'<p style="font-family:Arial,sans-serif">We received your request: <strong>{escape(label)}</strong> (reference {rid[:8]}). '
            f"Our target is to reply within {business.response_days()} days. This is a service target and not a statement of any legal deadline.</p>"))
    except Exception:  # noqa: BLE001
        logger.info("data request acknowledgement not sent", exc_info=True)
    if routed_to:
        try:  # and to the operator's privacy / grievance contact
            await send_email(to=routed_to, subject=f"Data request {rid[:8]}: {body.kind}", html=(
                f'<p style="font-family:Arial,sans-serif">A data request was made in VIDHI. Reference {rid}. Type: {escape(label)}. '
                f"Handle it in the admin console. The person's details are in the request record.</p>"))
        except Exception:  # noqa: BLE001
            logger.exception("data request could not be forwarded to the privacy contact")
    else:
        logger.error("data request %s saved but no PRIVACY_CONTACT_EMAIL / GRIEVANCE_OFFICER_EMAIL is configured", rid)
    return {**_row(doc), "routed": bool(routed_to),
            "note": "" if routed_to else "Your request is saved. The operator's privacy contact has not been set up yet, so it will be picked up from the admin console."}


@router.get("/privacy/requests")
async def my_requests(user: dict = Depends(current_user)):
    rows = await db.data_requests.find({"user_id": user["id"]}).sort("created_at", -1).to_list(100)
    return [_row(r) for r in rows]


class EraseMeIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    confirm_email: str = Field(min_length=3, max_length=320)


@router.post("/privacy/erase-me", dependencies=[Depends(user_limit("erase-me", 5, 3600))])
async def erase_me(body: EraseMeIn, response: Response, user: dict = Depends(current_user)):
    """The person erases their own account now: needs their password and their email typed out. The firm's records stay with the firm, without the person (lib.purge.purge_user).
    The only owner of an organisation cannot do this; they make someone else an owner or erase the organisation."""
    from fastapi import HTTPException

    from lib.auth import COOKIE_NAME, verify_password
    from lib.purge import CannotErase, purge_user

    stored = (await db.users.find_one({"id": user["id"]})) or {}
    if not verify_password(body.password, stored.get("password_hash") or ""):
        raise HTTPException(status_code=403, detail="Your password is not correct.")
    if body.confirm_email.strip().lower() != user["email"].strip().lower():
        raise HTTPException(status_code=422, detail="Type your email exactly to confirm.")
    try:
        await purge_user(user["id"])
    except CannotErase as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"erased": True}


_SECRET_USER_FIELDS = {"_id", "password_hash", "two_factor", "two_factor_pending", "phone_pending", "email_verification", "google_sub"}


@router.get("/privacy/my-data")
async def my_data(user: dict = Depends(current_user)):
    """The person's own data, at once: their profile, preferences, activity, feedback and data requests. Secrets (password hash, two-step secret, stored phone number) are left out."""
    row = await db.users.find_one({"id": user["id"]}) or {}
    profile = {k: v for k, v in row.items() if k not in _SECRET_USER_FIELDS}
    if isinstance(profile.get("phone"), dict):
        profile["phone"] = {k: v for k, v in profile["phone"].items() if k in ("verified", "last4", "channel", "alerts")}
    activity = await db.audit_events.find({"user_id": user["id"]}, {"_id": 0, "organization_id": 0}).sort("created_at", -1).to_list(5000)
    feedback = await db.answer_feedback.find({"user_id": user["id"]}, {"_id": 0}).to_list(5000)
    requests = await db.data_requests.find({"user_id": user["id"]}, {"_id": 0}).to_list(500)
    import json

    body = json.dumps({"exported_at": now(), "profile": profile, "activity": activity, "answer_feedback": feedback, "data_requests": requests}, default=str, indent=1, ensure_ascii=False)
    await audit(user, "PRIVACY_MY_DATA_DOWNLOAD")
    return Response(content=body, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="my-vidhi-data.json"', "Cache-Control": "no-store"})