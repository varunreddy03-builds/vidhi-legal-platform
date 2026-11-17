"""Erase again what was erased, after a database was restored from an older backup.

    python tools/reapply_erasures.py --ledger /backups/erasures.jsonl --dry-run     # list what would be erased, change nothing
    python tools/reapply_erasures.py --ledger /backups/erasures.jsonl               # erase it (uses MONGO_URL and DB_NAME)

Run it right after `tools/db_restore.py` and before the API is opened to people. The ledger (lib/erasure_ledger.py) holds kinds and ids only. Anything already gone is skipped, so it
is safe to run twice. Prints counts, never names or text."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["ERASURE_LEDGER_FILE"] = ""  # re-applying must not write the ledger again

from lib import erasure_ledger, purge  # noqa: E402
from lib.db import db  # noqa: E402

COLLECTION = {"org": "organizations", "user": "users", "matter": "matters", "case": "recovery_cases", "document": "documents"}


async def run(ledger: str, dry_run: bool) -> dict:
    rows = erasure_ledger.read(ledger)
    result = {"listed": len(rows), "present": 0, "erased": 0}
    for row in rows:
        kind, item_id = row["kind"], row["id"]
        if not await db[COLLECTION[kind]].find_one({"id": item_id}, {"id": 1}):
            continue  # already gone
        result["present"] += 1
        if dry_run:
            continue
        if kind == "org":
            await purge.purge_org(item_id, "restore")
        elif kind == "user":
            await purge.purge_user(item_id, force=True)
        elif kind == "matter":
            await purge.purge_matter(item_id)
        elif kind == "case":
            await purge.purge_case(item_id)
        else:
            await purge.purge_document(await db.documents.find_one({"id": item_id}))
        result["erased"] += 1
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not os.path.exists(a.ledger):
        print("No such ledger file.", file=sys.stderr)
        return 2
    r = asyncio.run(run(a.ledger, a.dry_run))
    print(f"{r['listed']} erasures on the list; {r['present']} had come back; " + ("nothing changed (dry run)." if a.dry_run else f"{r['erased']} erased again."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
