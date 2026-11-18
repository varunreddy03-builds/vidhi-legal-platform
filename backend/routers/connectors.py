"""Connections to other systems. Microsoft 365 (Outlook mail, OneDrive and SharePoint files) is built; iManage is not (see the status text, and docs/MICROSOFT_AND_IMANAGE_SETUP.md).

What every connection promises: read-only, the person's own account, nothing leaves VIDHI because of it, and what is imported is copied into a matter once as an ordinary document (so it is read, summarised,
searched and erased like any other). The stored refresh token is encrypted, belongs to one person in one firm, goes when they disconnect, and is never exported."""

import hmac
import logging
from datetime import timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from lib import crypto, microsoft
from lib.auth import audit, cookie_kwargs, current_user, now
from lib.db import db
from lib.outbound import sha256
from lib.ratelimit import user_limit
from routers.documents import _ingest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/connectors", tags=["connectors"])
MATTER_ROUTER = APIRouter(tags=["connectors"])
COOKIE = "vidhi_conn"


def _aad(user: dict) -> bytes:
    return f"ms|{user['organization_id']}|{user['id']}".encode()


async def _row(user: dict) -> dict | None:
    return await db.connector_tokens.find_one({"organization_id": user["organization_id"], "user_id": user["id"], "provider": "microsoft"})


async def _access(user: dict) -> str:
    """A fresh access token for this person, or a plain 409 telling them to connect."""
    row = await _row(user)
    if not row:
        raise HTTPException(status_code=409, detail="Connect your Microsoft 365 account first.")
    try:
        tok = await microsoft.refresh(crypto.open_text(row["refresh_sealed"], _aad(user)))
    except (microsoft.MicrosoftError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Microsoft needs you to connect again.") from exc
    if tok.get("refresh_token"):  # Microsoft may rotate it
        await db.connector_tokens.update_one({"organization_id": user["organization_id"], "user_id": user["id"], "provider": "microsoft"},
                                             {"$set": {"refresh_sealed": crypto.seal_text(tok["refresh_token"], _aad(user)), "refreshed_at": now()}})
    return tok["access_token"]


@router.get("")
async def connections(user: dict = Depends(current_user)):
    row = await _row(user)
    ms_state = "connected" if row else ("not_connected" if microsoft.configured() else "not_configured")
    return {"connections": [
        {"id": "word", "name": "Microsoft Word", "state": "available", "does": "Review a draft inside Word: the Katalyst checks run on the open document.", "setup": ["Open the Word add-in page and follow the steps."], "page": "/addin/word"},
        {"id": "microsoft", "name": "Microsoft 365: Outlook, OneDrive and SharePoint", "state": ms_state, "account": row.get("account") if row else None,
         "does": "Bring a file or an email from your own Microsoft 365 account into a matter, to be summarised and searched like any document. Read-only: VIDHI never sends, changes or deletes anything there.",
         "setup": [] if microsoft.configured() else ["The operator registers VIDHI in Microsoft Entra ID and sets MS_CLIENT_ID and MS_CLIENT_SECRET (and MS_TENANT_ID to limit sign-in to one firm). See docs/MICROSOFT_AND_IMANAGE_SETUP.md."]},
        {"id": "imanage", "name": "iManage", "state": "not_available", "does": "Not built. It needs iManage Work API access from your iManage administrator, and the details of your iManage server.",
         "setup": ["Until then: save the file from iManage and add it to a matter or a Vault, or open it in Word and use the Word add-in."]},
    ], "note": "Every connection is read-only and uses your own account. Disconnecting removes what VIDHI keeps."}


@router.get("/microsoft/start", dependencies=[Depends(user_limit("ms-start", 30, 300))])
async def ms_start(user: dict = Depends(current_user)):
    if not microsoft.configured():
        raise HTTPException(status_code=404, detail="Microsoft 365 is not set up on this site.")
    import secrets

    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    await db.oauth_flows.insert_one({"state_hash": sha256(state), "verifier": verifier, "user_id": user["id"], "organization_id": user["organization_id"], "purpose": "microsoft", "expires_at": now() + timedelta(minutes=10)})
    r = RedirectResponse(microsoft.authorize_url(state, verifier), status_code=302)
    r.set_cookie(COOKIE, state, httponly=True, samesite="lax", secure=cookie_kwargs()["secure"], path="/", max_age=600)
    return r


@router.get("/microsoft/callback", dependencies=[Depends(user_limit("ms-callback", 30, 300))])
async def ms_callback(code: str | None = None, state: str | None = None, error: str | None = None, vidhi_conn: str | None = Cookie(default=None), user: dict = Depends(current_user)):
    def back(flag: str) -> RedirectResponse:
        r = RedirectResponse(f"/connections?{flag}", status_code=302)
        r.delete_cookie(COOKIE, path="/")
        return r

    if error or not code or not state or not vidhi_conn or not hmac.compare_digest(state, vidhi_conn):
        return back("microsoft=cancelled")
    flow = await db.oauth_flows.find_one_and_delete({"state_hash": sha256(state), "purpose": "microsoft", "user_id": user["id"], "organization_id": user["organization_id"]})  # one use, and only for this person
    if not flow or flow["expires_at"].replace(tzinfo=timezone.utc) < now():
        return back("microsoft=failed")
    try:
        tok = await microsoft.exchange_code(code, flow["verifier"])
        if not tok.get("refresh_token"):
            raise microsoft.MicrosoftError("no refresh token")
        account = await microsoft.whoami(tok["access_token"])
    except microsoft.MicrosoftError:
        logger.info("microsoft connect refused")
        return back("microsoft=failed")
    await db.connector_tokens.update_one({"organization_id": user["organization_id"], "user_id": user["id"], "provider": "microsoft"},
                                         {"$set": {"refresh_sealed": crypto.seal_text(tok["refresh_token"], _aad(user)), "account": account, "connected_at": now()}}, upsert=True)
    await audit(user, "CONNECTOR_CONNECTED", detail="microsoft")
    return back("microsoft=connected")


@router.delete("/microsoft")
async def ms_disconnect(user: dict = Depends(current_user)):
    n = (await db.connector_tokens.delete_many({"organization_id": user["organization_id"], "user_id": user["id"], "provider": "microsoft"})).deleted_count
    await audit(user, "CONNECTOR_DISCONNECTED", detail="microsoft")
    return {"disconnected": n}


def _wrap(exc: microsoft.MicrosoftError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/microsoft/files")
async def ms_files(folder: str | None = None, user: dict = Depends(current_user)):
    try:
        return {"items": await microsoft.list_files(await _access(user), folder)}
    except microsoft.MicrosoftError as exc:
        raise _wrap(exc) from exc


@router.get("/microsoft/mail")
async def ms_mail(user: dict = Depends(current_user)):
    try:
        return {"items": await microsoft.list_mail(await _access(user))}
    except microsoft.MicrosoftError as exc:
        raise _wrap(exc) from exc


class ImportIn(BaseModel):
    kind: str = Field(pattern="^(file|mail)$")
    id: str = Field(min_length=1, max_length=512)


@MATTER_ROUTER.post("/matters/{matter_id}/connectors/microsoft/import", dependencies=[Depends(user_limit("ms-import", 60, 3600))])
async def ms_import(matter_id: str, body: ImportIn, user: dict = Depends(current_user)):
    if not await db.matters.find_one({"id": matter_id, "organization_id": user["organization_id"]}, {"id": 1}):
        raise HTTPException(status_code=404, detail="Matter not found")
    access = await _access(user)
    try:
        name, data = await (microsoft.download_file(access, body.id) if body.kind == "file" else microsoft.mail_as_text(access, body.id))
    except microsoft.MicrosoftError as exc:
        raise _wrap(exc) from exc
    doc = await _ingest(user, matter_id, name, data)
    await audit(user, "CONNECTOR_IMPORT", matter_id=matter_id, detail=f"microsoft {body.kind}")  # the kind only, never the name or subject
    return doc
