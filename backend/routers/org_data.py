"""Organisation data lifecycle: retention setting, full export, erasure. Admin/owner only (see lib/rbac.py)."""

import json
import tempfile
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from lib.auth import COOKIE_NAME, audit, current_user, verify_password
from lib import filestore
from lib.db import db
from lib.purge import purge_org
from lib.ratelimit import hit, user_limit
from lib.retention import MAX_DAYS, MIN_DAYS, NOTICE_DAYS, platform_default_days

router = APIRouter(prefix="/org", tags=["org-data"])


class RetentionIn(BaseModel):
    """None: use the platform default (if the operator set one). 0: keep everything until I delete it. Otherwise a number of days between the minimum and the maximum."""

    retention_days_after_close: int | None = Field(default=None, ge=0, le=MAX_DAYS)

    @model_validator(mode="after")
    def _not_too_short(self):
        d = self.retention_days_after_close
        if d is not None and 0 < d < MIN_DAYS:
            raise ValueError(f"At least {MIN_DAYS} days, or 0 to keep everything.")
        return self


class AiSwitchIn(BaseModel):
    enabled: bool


@router.get("/ai")
async def get_ai_switch(user: dict = Depends(current_user)):
    org = await db.organizations.find_one({"id": user["organization_id"]}, {"ai_enabled": 1}) or {}
    return {"enabled": org.get("ai_enabled") is not False}


@router.put("/ai")
async def set_ai_switch(body: AiSwitchIn, user: dict = Depends(current_user)):
    """Owner and admin only (the /api/org policy). Off means nothing from this organisation is sent to any AI, OCR, voice or picture service: every AI route is refused before it sends anything."""
    await db.organizations.update_one({"id": user["organization_id"]}, {"$set": {"ai_enabled": body.enabled}})
    await audit(user, "AI_SWITCH", detail="on" if body.enabled else "off")
    return {"enabled": body.enabled}


@router.get("/retention")
async def get_retention(user: dict = Depends(current_user)):
    org = await db.organizations.find_one({"id": user["organization_id"]}) or {}
    return {
        "retention_days_after_close": org.get("retention_days_after_close"),
        "notice_days": NOTICE_DAYS,
        "min_days": MIN_DAYS,
        "max_days": MAX_DAYS,
        "platform_default_days": platform_default_days(),
    }


@router.put("/retention")
async def set_retention(body: RetentionIn, user: dict = Depends(current_user)):
    """None switches automatic deletion off (the default). Nothing is ever deleted unless an admin sets a period."""
    if body.retention_days_after_close is None:
        await db.organizations.update_one({"id": user["organization_id"]}, {"$unset": {"retention_days_after_close": ""}})
    else:
        await db.organizations.update_one(
            {"id": user["organization_id"]}, {"$set": {"retention_days_after_close": body.retention_days_after_close}}
        )
    await audit(user, "ORG_RETENTION_SET", detail=str(body.retention_days_after_close))
    return await get_retention(user)


EXPORT_COLLECTIONS = (  # everything the organisation owns, filtered by organization_id
    "portal_graphs", "reviews", "vault_rows", "matters", "clients", "addin_keys", "doc_notes", "documents", "facts", "timeline_events", "evidence_items", "entities", "inconsistencies",
    "research_results", "drafts", "recovery_cases", "recovery_proofs", "notice_versions", "notice_translations", "case_correspondence", "audit_events", "email_log", "generated_images", "answer_feedback",
    "deadlines", "portal_access", "portal_shares", "portal_updates", "authority_reports", "date_lists", "defect_checks", "old_code_checks",
    "support_tickets", "data_requests", "invites", "directory_profiles", "booking_requests", "org_branding", "email_confirmations", "pilot_feedback", "draft_comments",
)
# Org-tagged collections that are NOT exported, each with the reason. tests/test_org_export.py fails when a collection is in neither list, so a new one cannot be forgotten.
EXPORT_EXCLUDED = {
    "push_subscriptions": "device addresses and keys for notifications: credentials of a device, not records",
    "connector_tokens": "each person's encrypted sign-in key to their own Microsoft 365 account: a credential, never exported (erased with the organisation)",
}


def _clean(doc: dict) -> dict:
    doc = {k: v for k, v in doc.items() if k != "_id"}
    for secret in ("password_hash", "token_hash", "email_verification", "logo_b64", "two_factor", "two_factor_pending", "phone_pending", "google_sub"):
        doc.pop(secret, None)
    if isinstance(doc.get("phone"), dict):  # never export the stored number itself, only whether alerts are on
        doc["phone"] = {k: v for k, v in doc["phone"].items() if k in ("verified", "last4", "channel", "alerts")}
    return doc


@router.get("/export", dependencies=[Depends(user_limit("org-export", 3, 3600))])
async def export_everything(user: dict = Depends(current_user)):
    """One zip: every record as JSON plus the original uploaded files. For the organisation to keep or move."""
    org_id = user["organization_id"]
    tmp = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        org = await db.organizations.find_one({"id": org_id}) or {}
        z.writestr("organization.json", json.dumps(_clean(org), default=str, indent=1))
        users = [_clean(u) for u in await db.users.find({"organization_id": org_id}).to_list(10000)]
        z.writestr("members.json", json.dumps(users, default=str, indent=1))
        for coll in EXPORT_COLLECTIONS:
            rows = [_clean(r) for r in await db[coll].find({"organization_id": org_id}).to_list(200000)]
            z.writestr(f"{coll}.json", json.dumps(rows, default=str, indent=1))
        works = [_clean(r) for r in await db.knowledge_works.find({"org_id": org_id}).to_list(100000)]  # private documents added to the organisation's own knowledge library
        z.writestr("knowledge_works.json", json.dumps(works, default=str, indent=1))
        draft_ids = [d["id"] for d in await db.drafts.find({"organization_id": org_id}, {"id": 1}).to_list(100000)]
        versions = [_clean(r) for r in await db.draft_versions.find({"draft_id": {"$in": draft_ids}}).to_list(200000)] if draft_ids else []
        z.writestr("draft_versions.json", json.dumps(versions, default=str, indent=1))
        for d in await db.documents.find({"organization_id": org_id, "gridfs_id": {"$exists": True}}).to_list(100000):
            name = f"files/{d['id']}-{d.get('filename', 'file')}"
            try:
                z.writestr(name, await filestore.read(d["gridfs_id"]))
            except Exception:  # noqa: BLE001 - one missing file must not spoil the export; it is listed instead
                z.writestr(f"files/{d['id']}-MISSING.txt", "The stored file could not be read.")
        for pr in await db.recovery_proofs.find({"organization_id": org_id, "gridfs_id": {"$exists": True}}).to_list(100000):
            pname = f"case-files/{pr['case_id']}/{pr['id']}-{pr.get('filename', 'file')}"
            try:
                z.writestr(pname, await filestore.read(pr["gridfs_id"]))
            except Exception:  # noqa: BLE001
                z.writestr(f"case-files/{pr['case_id']}/{pr['id']}-MISSING.txt", "The stored file could not be read.")
        z.writestr("README.txt", "VIDHI export. JSON files hold the records; files/ holds the original uploaded documents.\n")
    size = tmp.tell()
    tmp.seek(0)
    await audit(user, "ORG_EXPORT", detail=f"{size} bytes")

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
        headers={"Content-Disposition": "attachment; filename=vidhi-export.zip", "Content-Length": str(size)},
    )


class EraseIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    organization_name: str = Field(min_length=1, max_length=200)


@router.delete("")
async def erase_organization(body: EraseIn, response: Response, user: dict = Depends(current_user)):
    """Permanently delete the whole organisation. Owner only; needs the password and the organisation name typed out."""
    await hit("org-erase", user["id"], 5, 3600)
    stored = (await db.users.find_one({"id": user["id"]}))["password_hash"]
    if not verify_password(body.password, stored):
        raise HTTPException(status_code=403, detail="Your password is not correct.")
    if body.organization_name.strip() != user["organization_name"]:
        raise HTTPException(status_code=422, detail="Type the organisation name exactly as shown to confirm.")
    await purge_org(user["organization_id"], user["id"])
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}
