"""Organization branding — firm logo upload for receipts, notices and statements."""

import base64

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from lib.auth import audit, current_user, now
from lib.db import db
from lib.ratelimit import UPLOAD_LIMIT
from lib.uploads import read_limited, safe_filename, validate_content

router = APIRouter(prefix="/org", tags=["org"])

MAX_BYTES = 1024 * 1024
MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


@router.post("/logo", dependencies=[Depends(UPLOAD_LIMIT)])
async def upload_logo(file: UploadFile = File(...), user: dict = Depends(current_user)):
    filename = safe_filename(file.filename, "logo").lower()
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in MIME:
        raise HTTPException(status_code=415, detail="Upload a PNG, JPG or WEBP image.")
    data = await read_limited(file, MAX_BYTES, "Keep the logo under 1 MB.")
    if not data:
        raise HTTPException(status_code=400, detail="That file was empty.")
    validate_content(filename, data, tuple("." + e for e in MIME), "Upload a PNG, JPG or WEBP image.")
    await db.org_branding.update_one(
        {"organization_id": user["organization_id"]},
        {
            "$set": {
                "organization_id": user["organization_id"],
                "logo_b64": base64.b64encode(data).decode(),
                "logo_mime": MIME[ext],
                "updated_at": now(),
            }
        },
        upsert=True,
    )
    await audit(user, "ORG_LOGO_UPLOAD", detail=filename)
    return {"has_logo": True}


@router.get("/logo")
async def get_logo(user: dict = Depends(current_user)):
    doc = await db.org_branding.find_one({"organization_id": user["organization_id"]})
    if not doc or not doc.get("logo_b64"):
        return {"has_logo": False, "data_url": None}
    return {"has_logo": True, "data_url": f"data:{doc['logo_mime']};base64,{doc['logo_b64']}"}


@router.get("/logo/{org_id}")
async def get_logo_image(org_id: str):
    """Public raw logo image so it can be embedded in outgoing emails over https (no auth)."""
    doc = await db.org_branding.find_one({"organization_id": org_id})
    if not doc or not doc.get("logo_b64"):
        raise HTTPException(status_code=404, detail="No logo")

    return Response(
        content=base64.b64decode(doc["logo_b64"]),
        media_type=doc.get("logo_mime", "image/png"),
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.delete("/logo")
async def delete_logo(user: dict = Depends(current_user)):
    await db.org_branding.update_one(
        {"organization_id": user["organization_id"]},
        {"$unset": {"logo_b64": "", "logo_mime": ""}},
    )
    await audit(user, "ORG_LOGO_DELETE")
    return {"has_logo": False}


class BrandingIn(BaseModel):
    firm_name: str | None = None
    firm_address: str | None = None


async def _branding_out(org_id: str) -> dict:
    doc = await db.org_branding.find_one({"organization_id": org_id}) or {}
    data_url = None
    if doc.get("logo_b64"):
        data_url = f"data:{doc.get('logo_mime', 'image/png')};base64,{doc['logo_b64']}"
    return {
        "firm_name": doc.get("firm_name", "") or "",
        "firm_address": doc.get("firm_address", "") or "",
        "has_logo": bool(doc.get("logo_b64")),
        "data_url": data_url,
    }


@router.get("/branding")
async def get_branding_ep(user: dict = Depends(current_user)):
    return await _branding_out(user["organization_id"])


@router.patch("/branding")
async def set_branding(body: BrandingIn, user: dict = Depends(current_user)):
    patch = {"organization_id": user["organization_id"], "updated_at": now()}
    if body.firm_name is not None:
        patch["firm_name"] = body.firm_name.strip()[:200]
    if body.firm_address is not None:
        patch["firm_address"] = body.firm_address.strip()[:500]
    await db.org_branding.update_one(
        {"organization_id": user["organization_id"]}, {"$set": patch}, upsert=True
    )
    await audit(user, "ORG_BRANDING")
    return await _branding_out(user["organization_id"])
