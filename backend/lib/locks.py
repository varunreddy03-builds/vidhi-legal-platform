"""Tiny Mongo-backed lock so a scheduled job can never run twice at once (several workers, retried triggers).

The lock expires on its own (TTL), so a crashed run cannot block the schedule forever."""

from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from lib.db import db


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def acquire(name: str, ttl_seconds: int) -> bool:
    expires = _now() + timedelta(seconds=ttl_seconds)
    try:
        await db.cron_locks.insert_one({"_id": name, "expires_at": expires, "acquired_at": _now()})
        return True
    except DuplicateKeyError:
        # The TTL sweeper runs about once a minute; take over a lock that has already expired.
        res = await db.cron_locks.update_one({"_id": name, "expires_at": {"$lt": _now()}}, {"$set": {"expires_at": expires, "acquired_at": _now()}})
        return bool(res.modified_count)


async def release(name: str) -> None:
    await db.cron_locks.delete_one({"_id": name})
