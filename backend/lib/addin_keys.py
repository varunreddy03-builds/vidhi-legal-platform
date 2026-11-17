"""Add-in keys: a way for the Google Docs add-on (which cannot use the browser's sign-in cookie) to call the two Katalyst checks as the person who made the key.

Narrow on purpose:
- a key works ONLY for the two routes in ADDIN_KEY_ROUTES; it can never open the app, read a matter, make another key or change anything;
- only a person signed in with the browser session can make, list or revoke keys (a leaked key cannot make more keys);
- the key is shown once, kept only as a SHA-256 hash, expires (30 days by default, set ADDIN_KEY_DAYS between 1 and 90), and belongs to the person's organisation;
- a blocked person's keys stop working at once; at most five live keys per person."""

import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from lib.db import db

PREFIX = "vk_"
MAX_LIVE_KEYS = 5
ADDIN_KEY_ROUTES = frozenset({"/api/v1/katalyst/analyze-text", "/api/v1/katalyst/redline-docx"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def days() -> int:
    try:
        n = int(os.environ.get("ADDIN_KEY_DAYS", "30"))
    except ValueError:
        return 30
    return n if 1 <= n <= 90 else 30


def _digest(raw: str) -> str:
    from lib.auth import token_digest

    return token_digest(raw)


def _aware(d):
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


async def create(user: dict, label: str) -> dict:
    live = await db.addin_keys.count_documents({"user_id": user["id"], "expires_at": {"$gt": _now()}})
    if live >= MAX_LIVE_KEYS:
        raise HTTPException(status_code=409, detail=f"You already have {MAX_LIVE_KEYS} live keys. Remove one first.")
    raw = PREFIX + secrets.token_urlsafe(32)
    row = {"id": str(uuid.uuid4()), "organization_id": user["organization_id"], "user_id": user["id"], "label": label.strip()[:60] or "Google Docs", "token_hash": _digest(raw),
           "created_at": _now(), "expires_at": _now() + timedelta(days=days()), "last_used_at": None}
    await db.addin_keys.insert_one(dict(row))
    return {**public(row), "key": raw}


def public(row: dict) -> dict:
    return {k: row.get(k) for k in ("id", "label", "created_at", "expires_at", "last_used_at")}


async def user_for(raw: str) -> dict:
    """The person a key belongs to, or 401. The caller must already have checked that the route is one of ADDIN_KEY_ROUTES."""
    from lib.auth import BLOCKED_MESSAGE, _with_org_plan

    row = await db.addin_keys.find_one({"token_hash": _digest(raw)}) if raw.startswith(PREFIX) else None
    if not row or _aware(row["expires_at"]) < _now():
        raise HTTPException(status_code=401, detail="This key is not valid. Make a new key in VIDHI.")
    user = await db.users.find_one({"id": row["user_id"], "organization_id": row["organization_id"]})
    if not user:
        raise HTTPException(status_code=401, detail="This key is not valid. Make a new key in VIDHI.")
    if user.get("blocked"):
        raise HTTPException(status_code=403, detail=BLOCKED_MESSAGE)
    if user.get("role") != "OWNER":
        user = await _with_org_plan(user)
    await db.addin_keys.update_one({"id": row["id"]}, {"$set": {"last_used_at": _now()}})
    return user
