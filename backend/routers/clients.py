"""Client records: who the firm acts for (name, contact details, private notes) and which matters are theirs. Own organisation only; a firm's client (portal user) never sees these.

A client record is the firm's own note-taking. It is not shared with the client, not sent to any AI, and not used as evidence. A matter may point at one client (`client_id`)."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.auth import audit, current_user, now
from lib.db import db
from lib.ratelimit import user_limit

router = APIRouter(tags=["clients"])

MAX_CLIENTS = 2000


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["INDIVIDUAL", "COMPANY", "OTHER"] = "INDIVIDUAL"
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=40)
    address: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=5000)


class ClientPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: Literal["INDIVIDUAL", "COMPANY", "OTHER"] | None = None
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=5000)


def _public(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in ("_id", "organization_id", "name_key")}


async def _mine(client_id: str, user: dict) -> dict:
    row = await db.clients.find_one({"id": client_id, "organization_id": user["organization_id"]})
    if not row:
        raise HTTPException(status_code=404, detail="Client not found")
    return row


@router.get("/clients")
async def list_clients(q: str = "", user: dict = Depends(current_user)):
    rows = await db.clients.find({"organization_id": user["organization_id"]}).sort("name_key", 1).to_list(MAX_CLIENTS)
    needle = q.strip().lower()[:100]
    if needle:
        rows = [r for r in rows if needle in r["name"].lower() or needle in (r.get("email") or "").lower() or needle in (r.get("phone") or "")]
    counts: dict[str, int] = {}
    async for m in db.matters.find({"organization_id": user["organization_id"], "client_id": {"$in": [r["id"] for r in rows]}}, {"client_id": 1}):
        counts[m["client_id"]] = counts.get(m["client_id"], 0) + 1
    return [{**_public(r), "matter_count": counts.get(r["id"], 0)} for r in rows]


@router.post("/clients", status_code=201, dependencies=[Depends(user_limit("client-write", 200, 3600))])
async def create_client(body: ClientIn, user: dict = Depends(current_user)):
    if await db.clients.count_documents({"organization_id": user["organization_id"]}) >= MAX_CLIENTS:
        raise HTTPException(status_code=409, detail=f"A firm can hold up to {MAX_CLIENTS} client records.")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="A client needs a name.")
    row = {"id": str(uuid.uuid4()), "organization_id": user["organization_id"], **body.model_dump(), "name_key": name.lower(), "created_by": user["id"], "created_at": now(), "updated_at": now()}
    row["name"] = name
    await db.clients.insert_one(dict(row))
    await audit(user, "CLIENT_CREATE", detail=name[:80])
    return _public(row)


@router.get("/clients/{client_id}")
async def read_client(client_id: str, user: dict = Depends(current_user)):
    row = await _mine(client_id, user)
    matters = await db.matters.find({"organization_id": user["organization_id"], "client_id": client_id}, {"id": 1, "title": 1, "status": 1, "_id": 0}).sort("created_at", -1).to_list(200)
    return {**_public(row), "matters": matters}


@router.patch("/clients/{client_id}", dependencies=[Depends(user_limit("client-write", 200, 3600))])
async def update_client(client_id: str, body: ClientPatch, user: dict = Depends(current_user)):
    await _mine(client_id, user)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "name" in patch:
        patch["name"] = patch["name"].strip()
        if not patch["name"]:
            raise HTTPException(status_code=422, detail="A client needs a name.")
        patch["name_key"] = patch["name"].lower()
    patch["updated_at"] = now()
    await db.clients.update_one({"id": client_id, "organization_id": user["organization_id"]}, {"$set": patch})
    await audit(user, "CLIENT_UPDATE", detail=client_id)
    return _public(await _mine(client_id, user))


@router.delete("/clients/{client_id}")
async def delete_client(client_id: str, user: dict = Depends(current_user)):
    row = await _mine(client_id, user)
    linked = await db.matters.count_documents({"organization_id": user["organization_id"], "client_id": client_id})
    if linked:
        raise HTTPException(status_code=409, detail=f"{linked} matter(s) are linked to this client. Open each matter and choose another client (or none) first.")
    await db.clients.delete_one({"id": client_id, "organization_id": user["organization_id"]})
    await audit(user, "CLIENT_DELETE", detail=row["name"][:80])
    return {"ok": True}
