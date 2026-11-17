"""Fixed-window rate limiting backed by Mongo (so it holds across workers/restarts).

Each hit increments one counter document keyed by scope + subject + time bucket; a TTL index on
`expires_at` (see lib/db.py) purges old buckets. Limits can be overridden per scope with the env var
RATE_LIMIT_<SCOPE>=<max hits per window> (e.g. RATE_LIMIT_SIGNUP=1000 in tests).
"""

import os
import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from lib.auth import current_user
from lib.db import db


def client_ip(request: Request) -> str:
    """Caller IP. X-Forwarded-For is trusted only when TRUST_PROXY=true (i.e. behind our own proxy)."""
    if os.environ.get("TRUST_PROXY", "false").lower() == "true":
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[-1].strip()  # the address OUR proxy saw (the last entry), never one the client wrote itself
    return request.client.host if request.client else "unknown"


def _limit(scope: str, default: int) -> int:
    raw = os.environ.get(f"RATE_LIMIT_{scope.upper().replace('-', '_')}")
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


async def hit(scope: str, subject: str, limit: int, window_s: int) -> str:
    """Count one event and return the key of the bucket it was counted in (so it can be given back exactly); raise 429 once `limit` is exceeded inside the current window.
    A refused attempt is not kept in the count, so the counter never reads higher than the limit."""
    limit = _limit(scope, limit)
    now = time.time()
    bucket = int(now // window_s)
    key = f"{scope}:{subject}:{bucket}"
    expires = datetime.now(timezone.utc) + timedelta(seconds=window_s * 2)
    doc = None
    for _ in range(2):  # a concurrent first-insert can race on _id; retry once
        try:
            doc = await db.rate_limits.find_one_and_update(
                {"_id": key},
                {"$inc": {"n": 1}, "$setOnInsert": {"expires_at": expires}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            break
        except DuplicateKeyError:
            continue
    if doc and doc["n"] > limit:
        await db.rate_limits.update_one({"_id": key}, {"$inc": {"n": -1}})  # the refused attempt does not stay counted
        retry = max(1, int((bucket + 1) * window_s - now))
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a little and try again.",
            headers={"Retry-After": str(retry)},
        )
    return key


async def refund_key(key: str) -> None:
    """Give one counted event back to the exact bucket it was counted in (never below zero). Used when the work the event paid for was never done."""
    await db.rate_limits.update_one({"_id": key, "n": {"$gt": 0}}, {"$inc": {"n": -1}})


async def peek(scope: str, subject: str, window_s: int) -> int:
    """How many events are already counted in the current window (does not count one)."""
    key = f"{scope}:{subject}:{int(time.time() // window_s)}"
    doc = await db.rate_limits.find_one({"_id": key})
    return int(doc["n"]) if doc else 0


def ip_limit(scope: str, limit: int, window_s: int):
    """Dependency: limit by caller IP (for unauthenticated routes)."""

    async def dep(request: Request) -> None:
        await hit(scope, client_ip(request), limit, window_s)

    return dep


def user_limit(scope: str, limit: int, window_s: int):
    """Dependency: limit by authenticated user (401 first if not signed in)."""

    async def dep(user: dict = Depends(current_user)) -> None:
        await hit(scope, user["id"], limit, window_s)

    return dep


# Shared presets so limits are tuned in one place.
_ai_per_user = user_limit("ai", 40, 3600)  # LLM calls cost money


async def AI_LIMIT(user: dict = Depends(current_user)) -> None:
    """Every AI route: the per-person hourly limit, then an early look at the monthly spending cap (so people get a clear message)."""
    await _ai_per_user(user)
    from lib.aibudget import ensure_available

    await ensure_available(user)



UPLOAD_LIMIT = user_limit("upload", 60, 3600)
EMAIL_LIMIT = user_limit("email", 20, 86400)  # outbound mail to third parties
CHECKOUT_LIMIT = user_limit("checkout", 10, 3600)
SEARCH_LIMIT = user_limit("search", 120, 60)
