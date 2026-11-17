"""Saved dates (hearings, filing dates, meetings): list, add, change, calendar files, and browser-notification devices.

Every date is entered by a person; VIDHI does not look up courts or calculate legal deadlines (see lib/deadlines.py).
Dates belong to the organisation (the team sees the same calendar); reminders go to the person who saved the date."""

import hashlib
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from lib import deadlines as dl
from lib import webpush
from lib.auth import audit, current_user, now
from lib.db import db
from lib.ratelimit import user_limit

router = APIRouter(tags=["deadlines"])
MAX_OPEN = 500


class Channels(BaseModel):
    email: bool = True
    push: bool = True
    sms: bool = False  # text messages also need a verified phone with alerts switched on (Settings)


class DeadlineIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: str = "deadline"
    starts_local: str = Field(min_length=10, max_length=40, description="local date and time, e.g. 2026-11-05T10:30")
    tz: str = Field(default=dl.DEFAULT_TZ, max_length=64)
    matter_id: str | None = Field(default=None, max_length=64)
    notes: str = Field(default="", max_length=1000)
    duration_minutes: int = Field(default=60, ge=5, le=1440)
    reminders: list[int] = Field(default_factory=lambda: list(dl.DEFAULT_OFFSETS), max_length=6)
    channels: Channels = Field(default_factory=Channels)


class DeadlinePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = None
    starts_local: str | None = Field(default=None, min_length=10, max_length=40)
    tz: str | None = Field(default=None, max_length=64)
    matter_id: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=1000)
    duration_minutes: int | None = Field(default=None, ge=5, le=1440)
    reminders: list[int] | None = Field(default=None, max_length=6)
    channels: Channels | None = None
    status: str | None = None


async def _check_matter(user: dict, matter_id: str | None) -> None:
    if matter_id and not await db.matters.find_one({"id": matter_id, "organization_id": user["organization_id"]}, {"id": 1}):
        raise HTTPException(status_code=404, detail="Matter not found")


def _need(ok_condition: bool, message: str) -> None:
    if not ok_condition:
        raise HTTPException(status_code=422, detail=message)


def _view(d: dict, titles: dict | None = None) -> dict:
    tz = d.get("tz") or dl.DEFAULT_TZ
    return {
        "id": d["id"], "title": d["title"], "kind": d["kind"], "notes": d.get("notes", ""), "status": d["status"],
        "starts_at": d["starts_at"].isoformat() if d["starts_at"].tzinfo else d["starts_at"].isoformat() + "+00:00",
        "starts_local": dl.local_text(d["starts_at"], tz), "tz": tz, "duration_minutes": d.get("duration_minutes", 60),
        "matter_id": d.get("matter_id"), "matter_title": (titles or {}).get(d.get("matter_id")),
        "reminders": d.get("reminders", []), "channels": d.get("channels") or {"email": True, "push": True, "sms": False},
        "reminders_sent": sorted(int(k) for k, v in (d.get("sent") or {}).items() if v != "skipped"),
        "entered_by_a_person": True,
    }


async def _titles(org: str, docs: list[dict]) -> dict:
    ids = list({d["matter_id"] for d in docs if d.get("matter_id")})
    if not ids:
        return {}
    return {m["id"]: m["title"] async for m in db.matters.find({"organization_id": org, "id": {"$in": ids}}, {"id": 1, "title": 1})}


async def _get(user: dict, deadline_id: str) -> dict:
    d = await db.deadlines.find_one({"id": deadline_id, "organization_id": user["organization_id"]})
    if not d:
        raise HTTPException(status_code=404, detail="Date not found")
    return d


@router.get("/deadlines")
async def list_deadlines(include_past: bool = False, user: dict = Depends(current_user)):
    query: dict = {"organization_id": user["organization_id"]}
    if not include_past:
        query["$or"] = [{"starts_at": {"$gte": now() - timedelta(hours=6)}}, {"status": "OPEN", "starts_at": {"$gte": now() - timedelta(days=1)}}]
    docs = await db.deadlines.find(query).sort("starts_at", 1).to_list(500)
    titles = await _titles(user["organization_id"], docs)
    return {"items": [_view(d, titles) for d in docs], "time_zone_default": dl.DEFAULT_TZ, "reminder_choices": list(dl.ALLOWED_OFFSETS), "kinds": list(dl.KINDS), "notice": dl.DISCLAIMER}


@router.post("/deadlines", status_code=201, dependencies=[Depends(user_limit("deadline-write", 120, 3600))])
async def add_deadline(body: DeadlineIn, user: dict = Depends(current_user)):
    _need(body.kind in dl.KINDS, "Choose a kind from the list.")
    await _check_matter(user, body.matter_id)
    try:
        starts, offsets = dl.to_utc(body.starts_local, body.tz), dl.clean_offsets(body.reminders)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _need(starts > now() - timedelta(days=1), "That date is in the past.")
    if await db.deadlines.count_documents({"organization_id": user["organization_id"], "status": "OPEN"}) >= MAX_OPEN:
        raise HTTPException(status_code=409, detail="You have a lot of open dates. Mark some as done first.")
    doc = {
        "id": str(uuid.uuid4()), "organization_id": user["organization_id"], "created_by": user["id"], "matter_id": body.matter_id,
        "title": body.title.strip(), "kind": body.kind, "notes": body.notes.strip(), "starts_at": starts, "tz": body.tz,
        "duration_minutes": body.duration_minutes, "reminders": offsets, "channels": body.channels.model_dump(),
        "sent": dl.initial_sent(starts, offsets, now()), "status": "OPEN", "created_at": now(), "updated_at": now(),
    }
    await db.deadlines.insert_one(doc)
    await audit(user, "DEADLINE_ADDED", matter_id=body.matter_id, detail=doc["id"])
    return _view(doc, await _titles(user["organization_id"], [doc]))


@router.patch("/deadlines/{deadline_id}")
async def change_deadline(deadline_id: str, body: DeadlinePatch, user: dict = Depends(current_user)):
    d = await _get(user, deadline_id)
    changes = body.model_dump(exclude_unset=True)
    update: dict = {}
    if "kind" in changes:
        _need(changes["kind"] in dl.KINDS, "Choose a kind from the list.")
    if "status" in changes:
        _need(changes["status"] in ("OPEN", "DONE"), "Status must be OPEN or DONE.")
    if changes.get("matter_id"):
        await _check_matter(user, changes["matter_id"])
    for k in ("title", "kind", "notes", "duration_minutes", "status", "matter_id"):
        if k in changes and changes[k] is not None or (k == "matter_id" and k in changes):
            update[k] = changes[k].strip() if isinstance(changes[k], str) else changes[k]
    if "channels" in changes and changes["channels"] is not None:
        update["channels"] = body.channels.model_dump()
    when_changed = any(k in changes and changes[k] is not None for k in ("starts_local", "tz", "reminders"))
    if when_changed:
        try:
            tz = changes.get("tz") or d.get("tz") or dl.DEFAULT_TZ
            starts = dl.to_utc(changes["starts_local"], tz) if changes.get("starts_local") else d["starts_at"]
            offsets = dl.clean_offsets(changes["reminders"]) if changes.get("reminders") is not None else d.get("reminders", [])
            dl.zone(tz)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _need(starts > now() - timedelta(days=1) or d["status"] == "DONE", "That date is in the past.")
        update.update({"starts_at": starts, "tz": tz, "reminders": offsets, "sent": dl.initial_sent(starts, offsets, now())})  # new time: reminders start afresh
        update["sent_via"] = {}
    if update.get("status") == "OPEN" and d["status"] == "DONE" and not when_changed:
        update["sent"] = dl.initial_sent(d["starts_at"], d.get("reminders", []), now())
    update["updated_at"] = now()
    await db.deadlines.update_one({"id": deadline_id, "organization_id": user["organization_id"]}, {"$set": update})
    await audit(user, "DEADLINE_CHANGED", matter_id=d.get("matter_id"), detail=deadline_id)
    fresh = await _get(user, deadline_id)
    return _view(fresh, await _titles(user["organization_id"], [fresh]))


@router.delete("/deadlines/{deadline_id}", status_code=204)
async def delete_deadline(deadline_id: str, user: dict = Depends(current_user)):
    d = await _get(user, deadline_id)
    await db.deadlines.delete_one({"id": deadline_id, "organization_id": user["organization_id"]})
    await audit(user, "DEADLINE_DELETED", matter_id=d.get("matter_id"), detail=deadline_id)
    return Response(status_code=204)


def _ics_response(docs: list[dict], name: str) -> Response:
    return Response(content=dl.ics(docs, now()), media_type="text/calendar; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/deadlines/calendar.ics")
async def calendar_all(user: dict = Depends(current_user)):
    """All open dates still ahead, as one calendar file to import into Google Calendar, Outlook or Apple Calendar."""
    docs = await db.deadlines.find({"organization_id": user["organization_id"], "status": "OPEN", "starts_at": {"$gte": now()}}).sort("starts_at", 1).to_list(500)
    return _ics_response(docs, "vidhi-dates.ics")


@router.get("/deadlines/{deadline_id}/calendar.ics")
async def calendar_one(deadline_id: str, user: dict = Depends(current_user)):
    return _ics_response([await _get(user, deadline_id)], "vidhi-date.ics")


# ---- browser notifications: which devices to notify ----

class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class SubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1000)
    keys: SubscriptionKeys


class EndpointIn(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1000)


@router.get("/push/config")
async def push_config(user: dict = Depends(current_user)):
    n = await db.push_subscriptions.count_documents({"user_id": user["id"]})
    return {"available": webpush.configured(), "public_key": webpush.public_key() if webpush.configured() else None, "devices": n}


@router.post("/push/subscribe", dependencies=[Depends(user_limit("push-subscribe", 20, 3600))])
async def push_subscribe(body: SubscriptionIn, user: dict = Depends(current_user)):
    if not webpush.configured():
        raise HTTPException(status_code=503, detail="Browser notifications are not available right now.")
    if not webpush.endpoint_allowed(body.endpoint):
        raise HTTPException(status_code=422, detail="That notification address is not from a supported browser.")
    key = hashlib.sha256(body.endpoint.encode()).hexdigest()
    mine = await db.push_subscriptions.count_documents({"user_id": user["id"], "_id": {"$ne": key}})
    if mine >= webpush.MAX_PER_USER:
        raise HTTPException(status_code=409, detail="You already have notifications on several devices. Turn one off first.")
    await db.push_subscriptions.replace_one(
        {"_id": key}, {"_id": key, "user_id": user["id"], "organization_id": user["organization_id"], "endpoint": body.endpoint, "keys": body.keys.model_dump(), "created_at": now()}, upsert=True
    )
    await audit(user, "PUSH_DEVICE_ADDED")
    return {"subscribed": True}


@router.post("/push/unsubscribe")
async def push_unsubscribe(body: EndpointIn, user: dict = Depends(current_user)):
    await db.push_subscriptions.delete_one({"user_id": user["id"], "endpoint": body.endpoint})
    await audit(user, "PUSH_DEVICE_REMOVED")
    return {"subscribed": False}


@router.post("/push/test", dependencies=[Depends(user_limit("push-test", 5, 3600))])
async def push_test(user: dict = Depends(current_user)):
    sent = await webpush.notify_user(user["id"], "VIDHI", "Notifications are on for this device.")
    return {"delivered": sent}