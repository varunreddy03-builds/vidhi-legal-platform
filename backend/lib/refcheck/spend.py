"""A daily limit on source lookups per organisation, so one organisation (or a bug) cannot run up the lookup bill.

The limit is a setting (AUTHORITY_DAILY_LOOKUP_CAP, default 300 lookups per organisation per Indian calendar day). Each request to a source reserves one lookup with ONE atomic
database update that refuses when the limit would be passed, so concurrent checks cannot overshoot it. A refused lookup never reaches the source."""

import os
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from lib.refcheck.lookup import LookupCapExceeded

IST = timezone(timedelta(hours=5, minutes=30))


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get("AUTHORITY_DAILY_LOOKUP_CAP", "300")))
    except ValueError:
        return 300


async def reserve(collection, org_id: str, n: int = 1, *, now: datetime | None = None) -> int:
    """Count n more lookups for this organisation today, or raise LookupCapExceeded. Returns the new count."""
    day = (now or datetime.now(IST)).astimezone(IST).strftime("%Y-%m-%d")
    cap = daily_cap()
    if n > cap:
        raise LookupCapExceeded()
    try:
        doc = await collection.find_one_and_update(
            {"_id": f"{org_id}:{day}", "lookups": {"$lte": cap - n}}, {"$inc": {"lookups": n}, "$setOnInsert": {"org": org_id, "day": day}}, upsert=True, return_document=True
        )
    except DuplicateKeyError as exc:  # the day's record exists and is at the limit, so the filter did not match and the upsert collided
        raise LookupCapExceeded() from exc
    return int(doc["lookups"])


async def used_today(collection, org_id: str, *, now: datetime | None = None) -> int:
    day = (now or datetime.now(IST)).astimezone(IST).strftime("%Y-%m-%d")
    doc = await collection.find_one({"_id": f"{org_id}:{day}"})
    return int(doc["lookups"]) if doc else 0
