"""Contact support: a form that works signed in or out. Messages are stored (so none is lost) and forwarded to SUPPORT_EMAIL when it is configured.
WhatsApp is optional and only shown once a genuine business number is configured (SUPPORT_WHATSAPP)."""

import logging
import uuid
from html import escape
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, Request
from pydantic import BaseModel, EmailStr, Field

from lib import business
from lib.auth import _load_user, current_user, now
from lib.db import db
from lib.email import send_email
from lib.ratelimit import ip_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["support"])


class MessageIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    message: str = Field(min_length=10, max_length=4000)
    category: Literal["general", "bug", "billing", "privacy", "other"] = "general"
    website: str = ""  # a field real people never see: bots fill it in


@router.get("/public/support-info")
async def support_info():
    """How to reach support. Anything not configured is null and not shown."""
    return {"email": business.get("support_email"), "whatsapp": business.get("support_whatsapp")}


@router.post("/public/support", dependencies=[Depends(ip_limit("support", 5, 3600))])
async def send_message(body: MessageIn, request: Request, vidhi_session: str | None = Cookie(default=None)):
    if body.website.strip():  # a bot: pretend it worked, store nothing
        return {"ok": True, "reference": uuid.uuid4().hex[:8]}
    user = None
    if vidhi_session:
        try:
            user = await _load_user(vidhi_session)
        except Exception:  # noqa: BLE001 - not signed in (or suspended): the message is still welcome
            user = None
    tid = str(uuid.uuid4())
    await db.support_tickets.insert_one({
        "id": tid, "name": body.name.strip(), "email": body.email.lower(), "message": body.message.strip(), "category": body.category, "status": "OPEN",
        "user_id": user["id"] if user else None, "organization_id": user["organization_id"] if user else None, "created_at": now(), "updated_at": now(),
    })
    to = business.get("support_email")
    if to:
        try:
            await send_email(to=to, subject=f"[VIDHI support {tid[:8]}] {body.category}", reply_to=body.email, html=(
                f'<p style="font-family:Arial,sans-serif"><strong>{escape(body.name)}</strong> ({escape(body.email)}'
                f'{", signed in" if user else ""}) wrote about <em>{escape(body.category)}</em>:</p>'
                f'<p style="font-family:Arial,sans-serif;white-space:pre-wrap">{escape(body.message)}</p>'))
        except Exception:  # noqa: BLE001 - the ticket is saved and visible in the admin console either way
            logger.warning("support message forwarded without its text or not at all", exc_info=True)
            try:
                await send_email(to=to, subject=f"[VIDHI support {tid[:8]}] new message", html=f"<p>A new support message ({escape(body.category)}) was saved. Open it in the admin console.</p>")
            except Exception:  # noqa: BLE001
                logger.exception("support notification could not be sent")
    else:
        logger.error("support message %s saved but SUPPORT_EMAIL is not configured", tid)
    return {"ok": True, "reference": tid[:8], "emailed": bool(to)}


@router.get("/support/messages")
async def my_messages(user: dict = Depends(current_user)):
    rows = await db.support_tickets.find({"user_id": user["id"]}, {"_id": 0, "message": 1, "category": 1, "status": 1, "created_at": 1, "id": 1}).sort("created_at", -1).to_list(50)
    return [{**r, "reference": r["id"][:8]} for r in rows]