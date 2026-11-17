"""Lawyer directory (lib/directory.py): the public listing and request form, and the lawyer's own profile and inbox."""

import logging
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from lib import botcheck, directory
from lib.auth import audit, current_user, now
from lib.db import db
from lib.email import send_email
from lib.ratelimit import client_ip, hit, ip_limit, user_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["directory"])
PAGE = 30


def _need_enabled() -> None:
    if not directory.enabled():
        raise HTTPException(status_code=404, detail="The lawyer directory is not available.")


# ------------------------------------------------------------------ public

@router.get("/public/directory")
async def directory_info():
    return {"enabled": directory.enabled(), "practice_areas": list(directory.PRACTICE_AREAS), "languages": list(directory.LANGUAGES), "notice": directory.NOTICE, "turnstile_site_key": botcheck.site_key()}


@router.get("/public/lawyers", dependencies=[Depends(ip_limit("directory-list", 120, 3600))])
async def list_lawyers(area: str | None = None, city: str | None = None, language: str | None = None, page: int = 1):
    _need_enabled()
    query: dict = {"listed": True}
    if area:
        if area not in directory.PRACTICE_AREAS:
            raise HTTPException(status_code=422, detail="Unknown practice area.")
        query["practice_areas"] = area
    if language:
        if language not in directory.LANGUAGES:
            raise HTTPException(status_code=422, detail="Unknown language.")
        query["languages"] = language
    if city:
        query["city"] = {"$regex": "^" + re.escape(city.strip()[:60]) + "$", "$options": "i"}
    total = await db.directory_profiles.count_documents(query)
    rows = await db.directory_profiles.find(query).sort("display_name_sort", 1).skip((max(page, 1) - 1) * PAGE).limit(PAGE).to_list(PAGE)
    return {"items": [directory.public_view(r) for r in rows], "total": total, "page": max(page, 1), "page_size": PAGE, "notice": directory.NOTICE}


@router.get("/public/lawyers/{profile_id}", dependencies=[Depends(ip_limit("directory-one", 240, 3600))])
async def read_lawyer(profile_id: str):
    _need_enabled()
    p = await db.directory_profiles.find_one({"id": profile_id, "listed": True})
    if not p:
        raise HTTPException(status_code=404, detail="Lawyer not found")
    return {**directory.public_view(p), "notice": directory.NOTICE}


class RequestIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(default="", max_length=20)
    message: str = Field(min_length=20, max_length=1500)
    consent: bool = False  # "I understand this is not legal advice and creates no lawyer-client relationship"
    website: str = ""  # a field real people never see
    elapsed_ms: int | None = Field(default=None, ge=0, le=10**9)
    turnstile_token: str | None = Field(default=None, max_length=4096)


@router.post("/public/lawyers/{profile_id}/requests", dependencies=[Depends(ip_limit("lawyer-request-ip", 5, 3600))])
async def send_request(profile_id: str, body: RequestIn, request: Request):
    _need_enabled()
    if not body.consent:
        raise HTTPException(status_code=422, detail="Please confirm you understand this is not legal advice and does not make anyone your lawyer.")
    if not await botcheck.human(body.turnstile_token, client_ip(request), honeypot=body.website, elapsed_ms=body.elapsed_ms):
        raise HTTPException(status_code=400, detail="We could not confirm you are a person. Please try again.")
    p = await db.directory_profiles.find_one({"id": profile_id, "listed": True})
    if not p or not p.get("accepting_requests", True):
        raise HTTPException(status_code=404, detail="This lawyer is not taking requests through VIDHI.")
    phone = re.sub(r"[^\d+]", "", body.phone)
    email = body.email.lower()
    await hit("lawyer-request-email", email, 3, 86400)  # one person cannot flood many lawyers
    await hit("lawyer-request-profile", profile_id, 30, 86400)  # nor can many people flood one lawyer
    rid = str(uuid.uuid4())
    await db.booking_requests.insert_one({
        "id": rid, "profile_id": profile_id, "user_id": p["user_id"], "organization_id": p["organization_id"], "name": body.name.strip(), "email": email, "phone": phone,
        "message": body.message.strip(), "status": "NEW", "contact_unverified": True, "created_at": now(), "updated_at": now(),
    })
    lawyer = await db.users.find_one({"id": p["user_id"]}, {"email": 1})
    if lawyer and lawyer.get("email"):
        try:  # a notice only: the request itself is read inside VIDHI after signing in
            await send_email(to=lawyer["email"], subject="A new consultation request is waiting in VIDHI", html='<p style="font-family:Arial,sans-serif">You have a new consultation request. Sign in to VIDHI and open Settings to read it. The person\'s contact details have not been verified.</p>')
        except Exception:  # noqa: BLE001 - the request is saved either way
            logger.info("request notice not emailed", exc_info=True)
    return {"ok": True, "reference": rid[:8], "message": "Your request was sent. The lawyer will contact you if they can help. Nothing has been promised or agreed."}


# ------------------------------------------------------------------ the lawyer's own profile and inbox (send_mail capability)

class ProfileIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=100)
    city: str = Field(default="", max_length=60)
    state: str = Field(default="", max_length=60)
    practice_areas: list[str] = Field(default_factory=list, max_length=12)
    languages: list[str] = Field(default_factory=list, max_length=23)
    bio: str = Field(default="", max_length=800)
    enrolment_claim: str = Field(default="", max_length=40)
    listed: bool = False
    accepting_requests: bool = True


@router.get("/directory/profile")
async def my_profile(user: dict = Depends(current_user)):
    p = await db.directory_profiles.find_one({"user_id": user["id"]})
    return {
        "profile": ({**directory.public_view(p), "listed": bool(p.get("listed"))} if p else None), "directory_enabled": directory.enabled(),
        "practice_areas": list(directory.PRACTICE_AREAS), "languages": list(directory.LANGUAGES), "notice": directory.NOTICE,
    }


@router.put("/directory/profile")
async def save_profile(body: ProfileIn, user: dict = Depends(current_user)):
    bad = [a for a in body.practice_areas if a not in directory.PRACTICE_AREAS] + [x for x in body.languages if x not in directory.LANGUAGES]
    if bad:
        raise HTTPException(status_code=422, detail="Choose practice areas and languages from the lists.")
    if body.listed and not (body.practice_areas and body.city.strip()):
        raise HTTPException(status_code=422, detail="To be listed, add your city and at least one practice area.")
    doc = {
        "user_id": user["id"], "organization_id": user["organization_id"], "display_name": body.display_name.strip(), "display_name_sort": body.display_name.strip().casefold(),
        "city": body.city.strip(), "state": body.state.strip(), "practice_areas": sorted(set(body.practice_areas)), "languages": sorted(set(body.languages)),
        "bio": body.bio.strip(), "enrolment_claim": body.enrolment_claim.strip(), "listed": body.listed, "accepting_requests": body.accepting_requests, "updated_at": now(),
    }
    await db.directory_profiles.update_one({"user_id": user["id"]}, {"$set": doc, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now()}}, upsert=True)
    await audit(user, "DIRECTORY_PROFILE_SAVED", detail="listed" if body.listed else "not listed")
    return await my_profile(user)


@router.get("/directory/requests")
async def my_requests(user: dict = Depends(current_user)):
    rows = await db.booking_requests.find({"user_id": user["id"]}).sort("created_at", -1).to_list(200)
    return [{"id": r["id"], "name": r["name"], "email": r["email"], "phone": r.get("phone", ""), "message": r["message"], "status": r["status"], "at": r["created_at"].isoformat() + "+00:00" if not r["created_at"].tzinfo else r["created_at"].isoformat(),
             "contact_unverified": True} for r in rows]


class StatusIn(BaseModel):
    status: Literal["NEW", "CONTACTED", "DECLINED", "ARCHIVED"]


@router.patch("/directory/requests/{request_id}", dependencies=[Depends(user_limit("directory-request-status", 200, 3600))])
async def set_status(request_id: str, body: StatusIn, user: dict = Depends(current_user)):
    res = await db.booking_requests.update_one({"id": request_id, "user_id": user["id"]}, {"$set": {"status": body.status, "updated_at": now()}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Request not found")
    await audit(user, "DIRECTORY_REQUEST_STATUS", detail=f"{request_id} {body.status}")
    return {"ok": True, "status": body.status}


@router.delete("/directory/requests/{request_id}")
async def delete_request(request_id: str, user: dict = Depends(current_user)):
    res = await db.booking_requests.delete_one({"id": request_id, "user_id": user["id"]})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Request not found")
    await audit(user, "DIRECTORY_REQUEST_DELETED", detail=request_id)
    return {"ok": True}