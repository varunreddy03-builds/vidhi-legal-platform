"""Invite-only pilot (decision D6). With SIGNUP_MODE=invite a new organisation can be created only with an invitation the operator made for that exact email address.

An invitation is single-use, expires after INVITE_DAYS, and is stored only as a hash of its code (the code is shown once, to the operator, and in the invitation email). Signing in is
never affected, only the creation of NEW accounts: by form (email + code) or by Google (the Google-verified email must have an open invitation). People invited into an existing
organisation by its owner (the team invitation flow) are not new organisations and are not affected."""

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from lib.db import db

INVITE_DAYS = 14
REFUSAL = "VIDHI is invite-only during the pilot. Use the invitation you were sent, with the same email address it was sent to."


def invite_only() -> bool:
    return os.environ.get("SIGNUP_MODE", "open").strip().lower() == "invite"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(code: str) -> str:
    return hashlib.sha256((code or "").strip().encode("utf-8")).hexdigest()


def invite_email_html(link: str) -> str:
    """The invitation email. The link must be an https address (the email layer refuses anything else)."""
    from lib.outbound import simple_email

    return simple_email([
        f"You are invited to join the VIDHI pilot. Open this link to create your account (it works once, for this email address, for {INVITE_DAYS} days):",
        f'<a href="{link}">{link}</a>',
        "VIDHI is a research and workflow tool, not legal advice.",
    ])


async def create(email: str, created_by: str) -> tuple[dict, str]:
    """A new invitation for `email` (earlier unused ones for the same address are cancelled). Returns the record and the code, which is not stored."""
    email = email.strip().lower()
    await db.pilot_invites.update_many({"email": email, "used_at": None, "revoked_at": None}, {"$set": {"revoked_at": _now()}})
    code = secrets.token_urlsafe(12)
    row = {"id": str(uuid.uuid4()), "email": email, "code_hash": _hash(code), "created_by": created_by, "created_at": _now(), "expires_at": _now() + timedelta(days=INVITE_DAYS), "used_at": None, "revoked_at": None}
    await db.pilot_invites.insert_one(dict(row))
    return {k: v for k, v in row.items() if k not in ("_id", "code_hash")}, code


def _open(email: str) -> dict:
    return {"email": email.strip().lower(), "used_at": None, "revoked_at": None, "expires_at": {"$gt": _now()}}


async def valid(email: str, code: str | None) -> dict | None:
    """The open invitation for this email and code, or None. Compares the hash; a wrong code, another address, a used, revoked or expired invitation all give None."""
    if not code or not code.strip():
        return None
    return await db.pilot_invites.find_one({**_open(email), "code_hash": _hash(code)})


async def open_for_email(email: str) -> dict | None:
    """An open invitation for this address, whatever its code (used after Google has proved the address)."""
    return await db.pilot_invites.find_one(_open(email))


async def claim(invite_id: str) -> bool:
    """Use the invitation, once. False if someone else used it first."""
    got = await db.pilot_invites.find_one_and_update({"id": invite_id, "used_at": None, "revoked_at": None}, {"$set": {"used_at": _now()}})
    return got is not None


async def release(invite_id: str) -> None:
    """Give the invitation back when the account could not be created after all (for example a race on the email address)."""
    await db.pilot_invites.update_one({"id": invite_id}, {"$set": {"used_at": None}})


async def revoke(invite_id: str) -> bool:
    got = await db.pilot_invites.find_one_and_update({"id": invite_id, "used_at": None, "revoked_at": None}, {"$set": {"revoked_at": _now()}})
    return got is not None


async def listing() -> list[dict]:
    out = []
    async for r in db.pilot_invites.find({}, {"_id": 0, "code_hash": 0}).sort("created_at", -1).limit(500):
        state = "used" if r.get("used_at") else "revoked" if r.get("revoked_at") else "expired" if r["expires_at"].replace(tzinfo=timezone.utc) <= _now() else "open"
        out.append({**r, "state": state})
    return out
