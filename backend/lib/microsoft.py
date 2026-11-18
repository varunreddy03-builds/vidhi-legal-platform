"""Microsoft 365 (Outlook mail, OneDrive and SharePoint files) through Microsoft Graph, signed in by the person themselves.

Each person connects THEIR OWN account (delegated permission, authorization-code flow with PKCE and state). VIDHI asks only to READ: sign-in details, files and mail. It never sends mail, never writes
or deletes anything in Microsoft 365, and keeps only the refresh token, encrypted, until the person disconnects. What a person imports into a matter is copied in once, as an ordinary document.

Setup (docs/MICROSOFT_AND_IMANAGE_SETUP.md): an app registration in Microsoft Entra ID gives MS_CLIENT_ID and MS_CLIENT_SECRET; MS_TENANT_ID narrows sign-in to one firm's tenant (default: any work
or school account). Until those exist the connection is simply off and says so. The Graph calls here follow Microsoft's published API; they are tested against a pretend Graph (tests inject _TRANSPORT)
and have not yet been run against a live tenant."""

import base64
import hashlib
import os
import re
from urllib.parse import urlencode

SCOPES = "openid offline_access User.Read Files.Read Mail.Read"
GRAPH = "https://graph.microsoft.com/v1.0"
MAX_FILE_BYTES = 25 * 1024 * 1024
_TRANSPORT = None  # tests inject an httpx.MockTransport here


class MicrosoftError(Exception):
    """A plain-sentence problem to show the person (never contains a token)."""


def stub_enabled() -> bool:
    """Tests and local trials only: a pretend Microsoft with a few canned files and mails. Needs BOTH flags, and AI_STUB is itself never set on a real site."""
    return os.environ.get("MS_STUB", "false").lower() == "true" and os.environ.get("AI_STUB", "false").lower() == "true"


def configured() -> bool:
    return stub_enabled() or bool(os.environ.get("MS_CLIENT_ID") and os.environ.get("MS_CLIENT_SECRET"))


def tenant() -> str:
    t = re.sub(r"[^A-Za-z0-9.\-]", "", os.environ.get("MS_TENANT_ID", ""))
    return t or "organizations"


def redirect_uri() -> str:
    return os.environ.get("MS_REDIRECT_URI") or os.environ.get("APP_URL", "http://localhost:3000").rstrip("/") + "/api/connectors/microsoft/callback"


def authorize_url(state: str, verifier: str) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    q = {"client_id": os.environ.get("MS_CLIENT_ID", ""), "response_type": "code", "redirect_uri": redirect_uri(), "response_mode": "query", "scope": SCOPES, "state": state,
         "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"}
    return f"https://login.microsoftonline.com/{tenant()}/oauth2/v2.0/authorize?" + urlencode(q)


STUB_FILE = b"Stub lease agreement. The rent is Rs 25,000 a month."
STUB_MAIL = {"id": "mail-1", "subject": "Notice of termination", "from": {"emailAddress": {"name": "Asha Rao", "address": "asha@example.test"}}, "receivedDateTime": "2026-11-01T09:30:00Z", "bodyPreview": "Please treat this as notice",
             "toRecipients": [{"emailAddress": {"name": "Ravi Kumar", "address": "ravi@example.test"}}], "ccRecipients": [], "body": {"contentType": "text", "content": "Please treat this as notice of termination. Regards"}}


def _stub_transport():
    import httpx

    def handle(req: "httpx.Request") -> "httpx.Response":
        path = req.url.path
        if path.endswith("/oauth2/v2.0/token"):
            form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            if form.get("code") not in (None, "stub-code") or form.get("refresh_token") not in (None, "stub-refresh"):
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "stub-access", "refresh_token": "stub-refresh", "expires_in": 3600})
        if req.headers.get("authorization") != "Bearer stub-access":
            return httpx.Response(401, json={})
        if path.endswith("/me"):
            return httpx.Response(200, json={"userPrincipalName": "stub.user@example.test"})
        if path.endswith("/me/drive/root/children"):
            return httpx.Response(200, json={"value": [{"id": "f1", "name": "lease.txt", "size": len(STUB_FILE), "file": {}, "lastModifiedDateTime": "2026-10-01T00:00:00Z"}, {"id": "d1", "name": "Contracts", "size": 0, "folder": {}}]})
        if path.endswith("/me/drive/items/f1/content"):
            return httpx.Response(200, content=STUB_FILE)
        if path.endswith("/me/drive/items/f1"):
            return httpx.Response(200, json={"id": "f1", "name": "lease.txt", "size": len(STUB_FILE), "file": {}})
        if path.endswith("/me/drive/items/d1"):
            return httpx.Response(200, json={"id": "d1", "name": "Contracts", "size": 0, "folder": {}})
        if path.endswith("/me/messages"):
            return httpx.Response(200, json={"value": [STUB_MAIL]})
        if path.endswith("/me/messages/mail-1"):
            return httpx.Response(200, json=STUB_MAIL)
        return httpx.Response(404, json={})

    return httpx.MockTransport(handle)


def _client():
    import httpx

    return httpx.AsyncClient(timeout=30.0, transport=_stub_transport() if stub_enabled() else _TRANSPORT, follow_redirects=True)


async def _token(data: dict) -> dict:
    async with _client() as c:
        r = await c.post(f"https://login.microsoftonline.com/{tenant()}/oauth2/v2.0/token", data={"client_id": os.environ.get("MS_CLIENT_ID", ""), "client_secret": os.environ.get("MS_CLIENT_SECRET", ""),
                                                                                               "scope": SCOPES, **data})
    if r.status_code != 200 or "access_token" not in r.json():
        raise MicrosoftError("Microsoft did not accept the sign-in. Connect again.")
    return r.json()


async def exchange_code(code: str, verifier: str) -> dict:
    return await _token({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(), "code_verifier": verifier})


async def refresh(refresh_token: str) -> dict:
    return await _token({"grant_type": "refresh_token", "refresh_token": refresh_token})


async def _get(access: str, path: str, params: dict | None = None, headers: dict | None = None):
    async with _client() as c:
        r = await c.get(GRAPH + path if path.startswith("/") else path, params=params, headers={"Authorization": f"Bearer {access}", **(headers or {})})
    if r.status_code in (401, 403):
        raise MicrosoftError("Microsoft refused access. Connect again and allow VIDHI to read your files and mail.")
    if r.status_code == 404:
        raise MicrosoftError("That item was not found in Microsoft 365.")
    if r.status_code != 200:
        raise MicrosoftError("Microsoft 365 could not be reached just now. Please try again.")
    return r


async def whoami(access: str) -> str:
    return str((await _get(access, "/me", {"$select": "userPrincipalName,mail"})).json().get("userPrincipalName") or "")


async def list_files(access: str, folder_id: str | None = None) -> list[dict]:
    path = f"/me/drive/items/{folder_id}/children" if folder_id else "/me/drive/root/children"
    data = (await _get(access, path, {"$select": "id,name,size,folder,file,lastModifiedDateTime", "$top": "100"})).json()
    return [{"id": i["id"], "name": i.get("name", ""), "size": int(i.get("size") or 0), "folder": "folder" in i, "modified": i.get("lastModifiedDateTime", "")} for i in data.get("value", [])]


async def download_file(access: str, item_id: str) -> tuple[str, bytes]:
    meta = (await _get(access, f"/me/drive/items/{item_id}", {"$select": "id,name,size,folder,file"})).json()
    if "folder" in meta:
        raise MicrosoftError("That is a folder. Choose a file.")
    if int(meta.get("size") or 0) > MAX_FILE_BYTES:
        raise MicrosoftError("That file is too large to import (over 25 MB).")
    r = await _get(access, f"/me/drive/items/{item_id}/content")
    if len(r.content) > MAX_FILE_BYTES:
        raise MicrosoftError("That file is too large to import (over 25 MB).")
    return meta.get("name") or "file", r.content


async def list_mail(access: str, top: int = 25) -> list[dict]:
    data = (await _get(access, "/me/messages", {"$top": str(min(top, 50)), "$select": "id,subject,from,receivedDateTime,bodyPreview", "$orderby": "receivedDateTime desc"})).json()
    out = []
    for m in data.get("value", []):
        sender = ((m.get("from") or {}).get("emailAddress") or {})
        out.append({"id": m["id"], "subject": m.get("subject") or "(no subject)", "from": sender.get("address", ""), "received": m.get("receivedDateTime", ""), "preview": (m.get("bodyPreview") or "")[:200]})
    return out


def _addr(x: dict) -> str:
    a = (x or {}).get("emailAddress") or {}
    return f"{a.get('name', '')} <{a.get('address', '')}>".strip()


async def mail_as_text(access: str, message_id: str) -> tuple[str, bytes]:
    """One message as plain text: who, when, subject and body. Attachments are not fetched."""
    m = (await _get(access, f"/me/messages/{message_id}", {"$select": "subject,from,toRecipients,ccRecipients,receivedDateTime,body"}, {"Prefer": 'outlook.body-content-type="text"'})).json()
    head = [f"From: {_addr(m.get('from'))}", "To: " + "; ".join(_addr(x) for x in m.get("toRecipients", [])), "Cc: " + "; ".join(_addr(x) for x in m.get("ccRecipients", [])),
            f"Date: {m.get('receivedDateTime', '')}", f"Subject: {m.get('subject') or ''}"]
    body = ((m.get("body") or {}).get("content") or "").replace("\r\n", "\n").strip()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", (m.get("subject") or "email")).strip("-")[:50] or "email"
    return f"email-{slug}.txt", ("\n".join(h for h in head if not h.endswith(": ")) + "\n\n" + body + "\n").encode("utf-8")
