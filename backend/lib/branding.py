"""Per-organization branding (logo + firm name/address) stored in Mongo; shared helpers."""

import base64
import io
import os
from html import escape

from lib.db import db


async def _branding_doc(org_id: str) -> dict:
    return await db.org_branding.find_one({"organization_id": org_id}) or {}


async def get_logo_bytes(org_id: str) -> bytes | None:
    doc = await _branding_doc(org_id)
    if not doc.get("logo_b64"):
        return None
    try:
        return base64.b64decode(doc["logo_b64"])
    except Exception:  # noqa: BLE001
        return None


async def get_branding(org_id: str) -> dict:
    """{logo: bytes|None, firm_name: str, firm_address: str} for PDFs + emails."""
    doc = await _branding_doc(org_id)
    logo = None
    if doc.get("logo_b64"):
        try:
            logo = base64.b64decode(doc["logo_b64"])
        except Exception:  # noqa: BLE001
            logo = None
    return {
        "logo": logo,
        "firm_name": doc.get("firm_name", "") or "",
        "firm_address": doc.get("firm_address", "") or "",
    }


def logo_flowable(logo_bytes: bytes | None):
    """Return a reportlab Image sized to a letterhead box, or None."""
    if not logo_bytes:
        return None
    try:
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Image

        iw, ih = ImageReader(io.BytesIO(logo_bytes)).getSize()
        if not iw or not ih:
            return None
        h = 40.0
        w = h * iw / ih
        if w > 170:
            w = 170.0
            h = w * ih / iw
        return Image(io.BytesIO(logo_bytes), width=w, height=h, hAlign="LEFT")
    except Exception:  # noqa: BLE001
        return None


async def email_logo_header(org_id: str) -> str:
    """HTML letterhead for emails: firm logo (https img) + firm name + address, or ""."""
    doc = await _branding_doc(org_id)
    app_url = os.environ.get("APP_URL", "").rstrip("/")
    img = ""
    if doc.get("logo_b64") and app_url.startswith("https://"):
        src = f"{app_url}/api/org/logo/{org_id}"
        img = (
            f'<div style="margin-bottom:8px"><img src="{src}" alt="" '
            f'height="40" style="max-height:40px;display:block"></div>'
        )
    name = escape(doc.get("firm_name", "") or "")
    addr = (doc.get("firm_address", "") or "").strip()
    text = ""
    if name:
        text += f'<div style="font-weight:bold;font-size:14px;color:#111">{name}</div>'
    if addr:
        addr_html = "<br>".join(escape(ln) for ln in addr.split("\n") if ln.strip())
        text += f'<div style="font-size:12px;color:#555;line-height:1.5">{addr_html}</div>'
    if not img and not text:
        return ""
    return f'<div style="margin-bottom:16px">{img}{text}</div>'
