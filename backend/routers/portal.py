"""Client portal: a client of the firm signs in and sees ONLY what a lawyer chose to share, read-only.

Who sees what
  * A CLIENT user (lib/rbac.py) holds no "read" or "write", so every ordinary route refuses them; only /api/portal/* and their own account settings are open.
  * Access is per matter: one row in portal_access (client, matter, organisation) per matter shared with that client. Every portal route looks the row up
    for the signed-in client and the matter in the URL; no row (or a revoked one) answers 404, the same as a matter that does not exist.
  * A client sees: the matter's title and status, the updates a lawyer wrote for clients, and the documents a lawyer shared. Never: the matter's description,
    parties, facts, research, drafts, notes, other documents, other clients, or other matters.
  * Lawyers (send_mail capability) manage all of it from the matter: invite a client, post updates, share or stop sharing documents, remove access.
Nothing a client does changes any record except their own sign-in settings. Viewing a shared document is written to the audit log."""

import logging
import os
import uuid
from datetime import timedelta
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field

from lib import filestore
from lib.auth import audit, current_user, now, require_verified_sender
from lib.db import db
from lib.outbound import EmailSuppressed, link_html, new_token, send_logged, simple_email
from lib.ratelimit import EMAIL_LIMIT, user_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["portal"])
INVITE_DAYS = 7
MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".txt": "text/plain", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


async def client_matter(user: dict, matter_id: str) -> dict:
    """The matter, if THIS client has live access to it; otherwise 404 (never reveal whether it exists)."""
    row = await db.portal_access.find_one({"user_id": user["id"], "matter_id": matter_id, "organization_id": user["organization_id"], "revoked_at": None})
    matter = row and await db.matters.find_one({"id": matter_id, "organization_id": user["organization_id"]})
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    return matter


async def _matter(user: dict, matter_id: str) -> dict:
    m = await db.matters.find_one({"id": matter_id, "organization_id": user["organization_id"]})
    if not m:
        raise HTTPException(status_code=404, detail="Matter not found")
    return m


def _stamp(d) -> str:
    return d.isoformat() if getattr(d, "tzinfo", None) else d.isoformat() + "+00:00"


# ------------------------------------------------------------------ the client's side

@router.get("/portal/matters")
async def portal_matters(user: dict = Depends(current_user)):
    rows = await db.portal_access.find({"user_id": user["id"], "organization_id": user["organization_id"], "revoked_at": None}).to_list(200)
    ids = [r["matter_id"] for r in rows]
    matters = await db.matters.find({"id": {"$in": ids}, "organization_id": user["organization_id"]}, {"id": 1, "title": 1, "status": 1, "updated_at": 1}).to_list(200) if ids else []
    out = []
    for m in matters:
        out.append({"id": m["id"], "title": m["title"], "status": m.get("status", "OPEN"), "updates": await db.portal_updates.count_documents({"matter_id": m["id"]}),
                    "documents": await db.portal_shares.count_documents({"matter_id": m["id"]})})
    return {"firm": user["organization_name"], "matters": out}


@router.get("/portal/matters/{matter_id}")
async def portal_matter(matter_id: str, user: dict = Depends(current_user)):
    m = await client_matter(user, matter_id)
    updates = await db.portal_updates.find({"matter_id": matter_id}).sort("created_at", -1).to_list(200)
    shares = await db.portal_shares.find({"matter_id": matter_id}).sort("created_at", -1).to_list(200)
    docs = {d["id"]: d async for d in db.documents.find({"id": {"$in": [s["document_id"] for s in shares]}, "matter_id": matter_id, "organization_id": user["organization_id"]}, {"id": 1, "filename": 1})}
    return {
        "firm": user["organization_name"], "id": m["id"], "title": m["title"], "status": m.get("status", "OPEN"),
        "updates": [{"id": u["id"], "text": u["text"], "by": u.get("by_name", ""), "at": _stamp(u["created_at"])} for u in updates],
        "documents": [{"id": s["document_id"], "filename": docs[s["document_id"]]["filename"], "shared_at": _stamp(s["created_at"])} for s in shares if s["document_id"] in docs],
        "notice": "This page shows only what your lawyer chose to share with you. It is read-only and is not legal advice.",
    }


@router.get("/portal/matters/{matter_id}/documents/{document_id}/file")
async def portal_document(matter_id: str, document_id: str, user: dict = Depends(current_user)):
    await client_matter(user, matter_id)
    shared = await db.portal_shares.find_one({"matter_id": matter_id, "document_id": document_id})
    doc = shared and await db.documents.find_one({"id": document_id, "matter_id": matter_id, "organization_id": user["organization_id"]})
    if not doc or not doc.get("gridfs_id"):
        raise HTTPException(status_code=404, detail="File not found")
    data = await filestore.read(doc["gridfs_id"])
    await audit(user, "PORTAL_DOCUMENT_VIEWED", matter_id=matter_id, detail=doc["filename"])
    ext = os.path.splitext(doc["filename"].lower())[1]
    return Response(content=data, media_type=MIME.get(ext, "application/octet-stream"), headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(doc['filename'])}"})


# ------------------------------------------------------------------ the firm's side (lawyers: send_mail capability)

class ClientIn(BaseModel):
    email: EmailStr


class UpdateIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ShareIn(BaseModel):
    document_id: str = Field(min_length=1, max_length=64)


@router.get("/matters/{matter_id}/portal")
async def portal_state(matter_id: str, user: dict = Depends(current_user)):
    await _matter(user, matter_id)
    org = user["organization_id"]
    access = await db.portal_access.find({"matter_id": matter_id, "organization_id": org, "revoked_at": None}).to_list(100)
    users = {u["id"]: u async for u in db.users.find({"id": {"$in": [a["user_id"] for a in access]}}, {"id": 1, "full_name": 1, "email": 1})}
    invites = await db.invites.find({"organization_id": org, "role": "CLIENT", "portal_matter_ids": matter_id, "accepted_at": None, "expires_at": {"$gt": now()}}).to_list(100)
    updates = await db.portal_updates.find({"matter_id": matter_id}).sort("created_at", -1).to_list(200)
    shares = await db.portal_shares.find({"matter_id": matter_id}).to_list(500)
    return {
        "clients": [{"id": a["id"], "email": a["email"], "name": users.get(a["user_id"], {}).get("full_name", ""), "since": _stamp(a["created_at"]), "pending": False} for a in access]
        + [{"id": i["id"], "email": i["email"], "name": "", "since": _stamp(i["created_at"]), "pending": True} for i in invites],
        "updates": [{"id": u["id"], "text": u["text"], "by": u.get("by_name", ""), "at": _stamp(u["created_at"])} for u in updates],
        "shared_document_ids": [s["document_id"] for s in shares],
        "notice": "Clients see only the updates and documents listed here, read-only. Check each one before you share it: a client can download a shared document.",
    }


async def _notify(email: str, subject: str, paragraphs: list[str], user: dict) -> bool:
    try:
        await send_logged(to=email, subject=subject, html=simple_email(paragraphs), kind="portal", user=user)
        return True
    except (EmailSuppressed, Exception):  # noqa: BLE001 - a notice that cannot be sent must not undo the share
        logger.info("portal email not sent", exc_info=True)
        return False


@router.post("/matters/{matter_id}/portal/clients", dependencies=[Depends(EMAIL_LIMIT)])
async def add_client(matter_id: str, body: ClientIn, user: dict = Depends(require_verified_sender)):
    await _matter(user, matter_id)
    org, email = user["organization_id"], body.email.lower().strip()
    existing = await db.users.find_one({"email": email})
    app = os.environ.get("APP_URL", "").rstrip("/")
    if existing:
        if existing.get("organization_id") != org or existing.get("role") != "CLIENT":
            raise HTTPException(status_code=409, detail="That email already has a VIDHI account that cannot be used as a client of this firm.")
        if await db.portal_access.find_one({"user_id": existing["id"], "matter_id": matter_id, "revoked_at": None}):
            raise HTTPException(status_code=409, detail="That client already has access to this matter.")
        row = {"id": str(uuid.uuid4()), "organization_id": org, "matter_id": matter_id, "user_id": existing["id"], "email": email, "granted_by": user["id"], "created_at": now(), "revoked_at": None}
        await db.portal_access.insert_one(row)
        await _notify(email, f"{user['organization_name']} shared a matter with you", [f"{escape(user['organization_name'])} has given you access to another matter in your VIDHI client portal.", link_html(f"{app}/portal", "Open your portal")], user)
        await audit(user, "PORTAL_CLIENT_ADDED", matter_id=matter_id, detail=email)
        return {"ok": True, "id": row["id"], "email": email, "pending": False}
    await db.invites.delete_many({"organization_id": org, "email": email, "accepted_at": None})
    raw, digest = new_token()
    invite = {"id": str(uuid.uuid4()), "organization_id": org, "organization_name": user["organization_name"], "email": email, "role": "CLIENT", "portal_matter_ids": [matter_id],
              "token_hash": digest, "invited_by": user["id"], "invited_by_name": user.get("full_name", ""), "created_at": now(), "expires_at": now() + timedelta(days=INVITE_DAYS), "accepted_at": None}
    await db.invites.insert_one(invite)
    link = f"{app}/accept-invite?token={raw}"
    html = simple_email([
        f"{escape(user.get('full_name') or 'Your lawyer')} at <strong>{escape(user['organization_name'])}</strong> invited you to a private client portal on VIDHI, where they can share updates and documents with you.",
        link_html(link, "Set up your portal access"),
        f"The link works once and expires in {INVITE_DAYS} days. If you were not expecting this, ignore it - nothing happens unless you accept. You will only ever see what your lawyer shares with you.",
    ])
    try:
        await send_logged(to=email, subject=f"{user['organization_name']} invited you to a client portal", html=html, kind="invite", user=user)
    except EmailSuppressed as exc:
        await db.invites.delete_one({"id": invite["id"]})
        raise HTTPException(status_code=409, detail="That address cannot receive email from VIDHI.") from exc
    except Exception as exc:  # noqa: BLE001
        await db.invites.delete_one({"id": invite["id"]})
        logger.exception("client invite email failed")
        raise HTTPException(status_code=502, detail="We could not send the invitation. Please try again in a minute.") from exc
    await audit(user, "PORTAL_CLIENT_INVITED", matter_id=matter_id, detail=email)
    return {"ok": True, "id": invite["id"], "email": email, "pending": True}


@router.delete("/matters/{matter_id}/portal/clients/{ref}")
async def remove_client(matter_id: str, ref: str, user: dict = Depends(current_user)):
    """Stop this client seeing the matter (ref is the access id, or the id of an invitation not yet accepted). The client's account stays."""
    await _matter(user, matter_id)
    org = user["organization_id"]
    got = await db.portal_access.find_one_and_update({"id": ref, "matter_id": matter_id, "organization_id": org, "revoked_at": None}, {"$set": {"revoked_at": now()}})
    email = got["email"] if got else None
    if not got:
        inv = await db.invites.find_one_and_delete({"id": ref, "organization_id": org, "role": "CLIENT", "portal_matter_ids": matter_id, "accepted_at": None})
        if not inv:
            raise HTTPException(status_code=404, detail="Client not found")
        email = inv["email"]
    await audit(user, "PORTAL_CLIENT_REMOVED", matter_id=matter_id, detail=email)
    return {"ok": True}


@router.post("/matters/{matter_id}/portal/updates", dependencies=[Depends(user_limit("portal-update", 60, 3600))])
async def post_update(matter_id: str, body: UpdateIn, user: dict = Depends(current_user)):
    await _matter(user, matter_id)
    row = {"id": str(uuid.uuid4()), "matter_id": matter_id, "organization_id": user["organization_id"], "text": body.text.strip(), "by": user["id"], "by_name": user.get("full_name", ""), "created_at": now()}
    await db.portal_updates.insert_one(row)
    app = os.environ.get("APP_URL", "").rstrip("/")
    for a in await db.portal_access.find({"matter_id": matter_id, "organization_id": user["organization_id"], "revoked_at": None}).to_list(100):
        # the email says only that there is something new: no matter title, no content
        await _notify(a["email"], "There is a new update in your client portal", [f"{escape(user['organization_name'])} added an update for you in your VIDHI client portal.", link_html(f"{app}/portal", "Open your portal")], user)
    await audit(user, "PORTAL_UPDATE_POSTED", matter_id=matter_id)
    return {"id": row["id"], "text": row["text"], "by": row["by_name"], "at": _stamp(row["created_at"])}


@router.delete("/matters/{matter_id}/portal/updates/{update_id}")
async def delete_update(matter_id: str, update_id: str, user: dict = Depends(current_user)):
    await _matter(user, matter_id)
    res = await db.portal_updates.delete_one({"id": update_id, "matter_id": matter_id, "organization_id": user["organization_id"]})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Update not found")
    await audit(user, "PORTAL_UPDATE_DELETED", matter_id=matter_id)
    return {"ok": True}


@router.post("/matters/{matter_id}/portal/documents")
async def share_document(matter_id: str, body: ShareIn, user: dict = Depends(current_user)):
    await _matter(user, matter_id)
    doc = await db.documents.find_one({"id": body.document_id, "matter_id": matter_id, "organization_id": user["organization_id"]}, {"id": 1, "filename": 1, "gridfs_id": 1})
    if not doc or not doc.get("gridfs_id"):
        raise HTTPException(status_code=404, detail="Document not found in this matter")
    await db.portal_shares.update_one({"matter_id": matter_id, "document_id": doc["id"]}, {"$setOnInsert": {"id": str(uuid.uuid4()), "organization_id": user["organization_id"], "created_at": now(), "shared_by": user["id"]}}, upsert=True)
    await audit(user, "PORTAL_DOCUMENT_SHARED", matter_id=matter_id, detail=doc["filename"])
    return {"ok": True}


@router.delete("/matters/{matter_id}/portal/documents/{document_id}")
async def unshare_document(matter_id: str, document_id: str, user: dict = Depends(current_user)):
    await _matter(user, matter_id)
    res = await db.portal_shares.delete_one({"matter_id": matter_id, "document_id": document_id, "organization_id": user["organization_id"]})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="That document is not shared")
    await audit(user, "PORTAL_DOCUMENT_UNSHARED", matter_id=matter_id, detail=document_id)
    return {"ok": True}