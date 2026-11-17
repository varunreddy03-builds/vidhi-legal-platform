"""Database migrations: ordered, one-time changes to stored data (renaming a field, filling a new one, moving records). Indexes are NOT migrations: lib/db.ensure_indexes creates those on every start.

How it works
  * MIGRATIONS is an ordered list. Each has an id (sorted, so use 0001_..., 0002_...), a description and an async function. NEVER edit a migration that has run anywhere: add a new one.
  * `run_pending()` runs each migration that has not been applied, in order, once. Progress is recorded in the `schema_migrations` collection (one row per migration).
  * Several workers or servers may start at the same moment: a migration is claimed by inserting its row; only the one that inserts it runs it, the others skip it.
  * If a migration fails, its row says `failed` with the error, nothing after it runs, and the next start retries it (fix it first; a migration must be safe to run twice).
  * A row stuck at `running` for more than STALE_MINUTES (the server died mid-way) is claimed again, so the same rule applies: write migrations that can run twice.
  * On a live site (https APP_URL) a failed migration stops the app from starting; on a laptop it is logged.
Run by hand:  python scripts/migrate.py --status   |   python scripts/migrate.py --run"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from pymongo.errors import DuplicateKeyError

from lib.db import db

logger = logging.getLogger("vidhi.migrations")
STALE_MINUTES = 30


@dataclass(frozen=True)
class Migration:
    id: str
    description: str
    run: Callable[[], Awaitable[None]]


async def _baseline() -> None:
    """Nothing to change: this marks the schema the first migrated release started from, so every later migration has a defined starting point."""
    return None


async def _encrypt_document_pages() -> None:
    """Encrypt the extracted text (documents.pages) of every document stored before field encryption existed. Safe to run twice: pages that are already sealed are skipped. Needs the file key;
    without it the migration fails and is retried at the next start, instead of being marked done with the text still readable."""
    import re

    from lib import crypto, fieldcrypt

    if not crypto.enabled():
        raise RuntimeError("DATA_ENCRYPTION_KEY is not set, so the stored document text cannot be encrypted yet. Set it and restart; this migration is retried.")
    raw = db.documents.raw  # what is really stored, not the opened view
    unsealed = {"pages": {"$elemMatch": {"$ne": "", "$not": re.compile("^" + re.escape(fieldcrypt.PREFIX))}}}
    async for row in raw.find(unsealed, {"pages": 1}):
        await raw.update_one({"_id": row["_id"]}, {"$set": {"pages": fieldcrypt.seal_pages(row["pages"])}})


MIGRATIONS: list[Migration] = [
    Migration("0001_baseline", "Mark the starting schema (no data change)", _baseline),
    Migration("0002_encrypt_document_pages", "Encrypt the extracted text of stored documents (field encryption, lib/fieldcrypt.py)", _encrypt_document_pages),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    return dt if (dt is None or dt.tzinfo) else dt.replace(tzinfo=timezone.utc)


def _ordered(migrations: list[Migration]) -> list[Migration]:
    ids = [m.id for m in migrations]
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        raise ValueError("Migrations must have unique ids listed in order.")
    return migrations


async def status(migrations: list[Migration] | None = None, collection=None) -> list[dict]:
    coll = collection if collection is not None else db.schema_migrations
    rows = {r["_id"]: r async for r in coll.find({})}
    out = []
    for m in _ordered(migrations if migrations is not None else MIGRATIONS):
        r = rows.get(m.id)
        out.append({"id": m.id, "description": m.description, "state": r["status"] if r else "pending", "finished_at": r.get("finished_at") if r else None, "error": r.get("error") if r else None})
    return out


async def _claim(coll, mid: str) -> bool:
    """True if this caller may run the migration now."""
    now = _now()
    try:
        await coll.insert_one({"_id": mid, "status": "running", "started_at": now})
        return True
    except DuplicateKeyError:
        pass
    stale = now - timedelta(minutes=STALE_MINUTES)
    taken = await coll.find_one_and_update(
        {"_id": mid, "$or": [{"status": "failed"}, {"status": "running", "started_at": {"$lte": stale}}]},
        {"$set": {"status": "running", "started_at": now, "error": None}},
    )
    return taken is not None


async def run_pending(migrations: list[Migration] | None = None, collection=None) -> dict:
    coll = collection if collection is not None else db.schema_migrations
    applied, skipped, failed = [], [], []
    for m in _ordered(migrations if migrations is not None else MIGRATIONS):
        if not await _claim(coll, m.id):
            row = await coll.find_one({"_id": m.id})
            if row and row["status"] == "running":
                # another server is running it right now: later migrations may depend on it, so wait for the next start instead of racing ahead
                skipped.append(m.id)
                break
            skipped.append(m.id)
            continue
        try:
            await m.run()
        except Exception as exc:  # noqa: BLE001
            logger.exception("migration %s failed", m.id)
            await coll.update_one({"_id": m.id}, {"$set": {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:300]}", "finished_at": _now()}})
            failed.append(m.id)
            break
        await coll.update_one({"_id": m.id}, {"$set": {"status": "applied", "finished_at": _now()}})
        applied.append(m.id)
        logger.info("migration %s applied", m.id)
    return {"applied": applied, "skipped": skipped, "failed": failed}


async def run_on_start() -> dict:
    """Called when the API starts. A failure stops a live site (https APP_URL) from serving old data against a half-changed schema; on a laptop it is only logged."""
    result = await run_pending()
    if result["failed"]:
        message = f"Database migration {result['failed'][0]} failed; see the log and the schema_migrations collection."
        if os.environ.get("APP_URL", "").strip().lower().startswith("https://"):
            raise RuntimeError(message)
        logger.error(message)
    return result
