"""Put invented rows into a TEST database so the operator's weekly view has something to show (browser test and screenshots), or take them out again.

  python scripts/e2e_seed_weekly.py <tag>            adds: AI calls over the last 6 days (some failed), thumbs-down, one wrong-result report, a pilot organisation with one member and matters
  python scripts/e2e_seed_weekly.py <tag> --clean    removes exactly the rows this tag added

Reads MONGO_URL and DB_NAME (like the browser tests: vidhi_e2e). Refuses any database whose name does not contain "e2e" or "test" or "shots" or "perf". Everything is invented."""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    tag, clean = sys.argv[1], "--clean" in sys.argv
    name = os.environ.get("DB_NAME", "vidhi_e2e")
    if not any(w in name for w in ("e2e", "test", "shots", "perf")):
        print("Refusing: this is not a test database:", name)
        return 2
    db = MongoClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))[name]
    if clean:
        for coll in ("ai_ledger", "answer_feedback", "pilot_feedback", "organizations", "users", "matters", "audit_events"):
            db[coll].delete_many({"_demo_tag": tag})
        print("removed rows tagged", tag)
        return 0
    now = datetime.now(timezone.utc)
    tagged = lambda d: {**d, "_demo_tag": tag}  # noqa: E731
    rows = []
    for i in range(6):
        t = now - timedelta(days=i, hours=1)
        for provider, cost, n in (("gemini", 0.0, 3 + i), ("haiku", 1.4 + i * 0.3, 2 + i)):
            for _ in range(n):
                rows.append(tagged({"created_at": t, "provider": provider, "model": "demo", "task": "research", "cost_inr": cost, "ok": True, "organization_id": "demo-org"}))
        rows.append(tagged({"created_at": t, "provider": "gemini", "task": "synthesize", "cost_inr": 0.0, "ok": False, "error": "TimeoutError" if i % 2 else "RateLimited", "organization_id": "demo-org"}))
    db.ai_ledger.insert_many(rows)
    oid = str(uuid.uuid4())
    db.organizations.insert_one(tagged({"id": oid, "name": f"Demo Pilot Chambers {tag[:4]}", "created_at": now - timedelta(days=9), "pilot": True}))
    db.users.insert_one(tagged({"id": str(uuid.uuid4()), "email": f"demo-{tag[:6]}@example.com", "organization_id": oid, "created_at": now - timedelta(days=9)}))
    db.matters.insert_many([tagged({"id": str(uuid.uuid4()), "organization_id": oid, "title": "Demo matter", "created_at": now}) for _ in range(3)])
    db.audit_events.insert_one(tagged({"id": str(uuid.uuid4()), "organization_id": oid, "operation": "LOGIN", "created_at": now - timedelta(hours=5)}))
    db.ai_ledger.insert_many([tagged({"created_at": now - timedelta(days=1), "provider": "haiku", "task": "research", "organization_id": oid, "cost_inr": 2.1, "ok": True}) for _ in range(4)])
    db.answer_feedback.insert_many([tagged({"research_id": str(uuid.uuid4()), "user_id": "demo", "organization_id": oid, "rating": r, "comment": "", "created_at": now}) for r in ("down", "up", "up")])
    db.pilot_feedback.insert_one(tagged({"id": str(uuid.uuid4()), "kind": "wrong_result", "organization_id": oid, "ref": "Demo ref", "ref_kind": "case", "created_at": now}))
    print("added demo rows tagged", tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
