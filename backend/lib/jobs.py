"""A small job queue in MongoDB for long work (OCR of a scanned law PDF, ingestion). No separate queue service.

* A job is claimed with one atomic update that sets a LEASE. A worker that dies mid-job simply stops renewing it: when the lease runs out the job can be claimed
  again, so nothing is lost and nothing runs twice at the same time.
* A failed job goes back to the queue after a growing delay (bounded attempts, no infinite retries) and is finally marked `failed` with the last error kept for the operator.
* Handlers must be safe to run again (they are: registering the same file twice returns the same record).
* Payloads hold ids and settings, never secrets. Errors stored are short and are never document text."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from lib.db import db

logger = logging.getLogger(__name__)
LEASE_SECONDS = 600
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (30, 300, 1800)


class Permanent(Exception):
    """Raise from a handler when trying again cannot help (for example the file is too long). The job is marked failed at once."""


def now() -> datetime:
    return datetime.now(timezone.utc)


async def enqueue(kind: str, payload: dict, *, max_attempts: int = MAX_ATTEMPTS) -> str:
    jid = str(uuid.uuid4())
    await db.jobs.insert_one({"id": jid, "kind": kind, "payload": payload, "state": "queued", "attempts": 0, "max_attempts": max_attempts, "available_at": now(), "lease_until": None, "last_error": None,
                              "result": None, "created_at": now(), "updated_at": now()})
    return jid


async def claim(kinds: list[str] | None = None, lease_seconds: int = LEASE_SECONDS) -> dict | None:
    """Take the oldest job that is due, or whose lease expired. Atomic: two workers never get the same job."""
    t = now()
    query: dict = {"$or": [{"state": "queued", "available_at": {"$lte": t}}, {"state": "running", "lease_until": {"$lt": t}}]}
    if kinds:
        query["kind"] = {"$in": kinds}
    job = await db.jobs.find_one_and_update(query, {"$set": {"state": "running", "lease_until": t + timedelta(seconds=lease_seconds), "updated_at": t}, "$inc": {"attempts": 1}},
                                            sort=[("created_at", 1)], return_document=ReturnDocument.AFTER)
    if job and job["attempts"] > job["max_attempts"]:  # a job that keeps dying mid-run must not loop forever
        await db.jobs.update_one({"id": job["id"]}, {"$set": {"state": "failed", "last_error": "gave up: it did not finish within the allowed attempts", "updated_at": now()}})
        return await claim(kinds, lease_seconds)
    return job


async def complete(job_id: str, result: dict | None = None) -> None:
    await db.jobs.update_one({"id": job_id}, {"$set": {"state": "done", "result": result or {}, "lease_until": None, "last_error": None, "updated_at": now()}})


async def fail(job_id: str, error: str) -> str:
    """Back to the queue with a delay, or finally failed. Returns the new state."""
    job = await db.jobs.find_one({"id": job_id})
    if not job:
        return "missing"
    msg = (error or "error")[:300]
    if job["attempts"] >= job["max_attempts"]:
        await db.jobs.update_one({"id": job_id}, {"$set": {"state": "failed", "last_error": msg, "lease_until": None, "updated_at": now()}})
        return "failed"
    delay = BACKOFF_SECONDS[min(job["attempts"] - 1, len(BACKOFF_SECONDS) - 1)]
    await db.jobs.update_one({"id": job_id}, {"$set": {"state": "queued", "last_error": msg, "lease_until": None, "available_at": now() + timedelta(seconds=delay), "updated_at": now()}})
    return "queued"


async def run_batch(handlers: dict, limit: int = 5) -> dict:
    """Run up to `limit` due jobs of the kinds we have handlers for. Returns counts."""
    done = failed = 0
    for _ in range(limit):
        job = await claim(list(handlers))
        if not job:
            break
        try:
            result = await handlers[job["kind"]](job["payload"])
            await complete(job["id"], result)
            done += 1
        except Permanent as exc:
            await db.jobs.update_one({"id": job["id"]}, {"$set": {"state": "failed", "last_error": f"not retried: {str(exc)[:200]}", "lease_until": None, "updated_at": now()}})
            failed += 1
        except Exception as exc:  # noqa: BLE001 - one bad job must not stop the others; the reason is kept short and without document text
            logger.warning("job %s (%s) failed: %s", job["id"], job["kind"], type(exc).__name__)
            await fail(job["id"], f"{type(exc).__name__}: {str(exc)[:200]}")
            failed += 1
    return {"done": done, "failed": failed}


def view(job: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in job.items() if k not in ("_id", "payload")}
