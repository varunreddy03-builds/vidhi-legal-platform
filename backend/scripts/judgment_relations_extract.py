"""Reads the judgments VIDHI holds the text of and records the clear statements they make about appeals and about other judgments (lib/judgment_relations.py rules, no AI).

Default is a DRY RUN: it counts what it would record and shows a few sentences, and stores nothing. Add --store to record them (all UNVERIFIED until a named reviewer approves each one).
Resumable: a judgment whose text has not changed since it was last read is skipped (collection judgment_scan).

    python scripts/judgment_relations_extract.py                # dry run over every judgment with text
    python scripts/judgment_relations_extract.py --court SC     # only courts whose name contains this text
    python scripts/judgment_relations_extract.py --limit 2000   # only the first N judgments with text
    python scripts/judgment_relations_extract.py --store        # record them (database: the DB_NAME in the environment; the dev app uses vidhi_dev)
"""

import argparse
import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import judgment_relations as jr  # noqa: E402
from lib.db import db  # noqa: E402


async def main(args) -> None:
    print("database:", os.environ["DB_NAME"], "| mode:", "STORE" if args.store else "dry run (nothing is stored)")
    flt: dict = {"text_chars": {"$gt": 300}}
    if args.court:
        flt["court_name"] = {"$regex": args.court, "$options": "i"}
    scanned = found = new = skipped = 0
    by_rel: Counter = Counter()
    examples: list[dict] = []
    cursor = db.hc_judgments.find(flt, {"id": 1, "text": 1, "text_sha256": 1, "case_title": 1}).batch_size(200)
    if args.limit:
        cursor = cursor.limit(args.limit)
    async for j in cursor:
        if args.store:
            done = await db.judgment_scan.find_one({"_id": j["id"]}, {"sha": 1})
            if done and done.get("sha") == j.get("text_sha256"):
                skipped += 1
                continue
        scanned += 1
        items = jr.extract(j.get("text", ""))
        found += len(items)
        for it in items:
            by_rel[it["relation"]] += 1
            if sum(1 for e in examples if e["relation"] == it["relation"]) < 2:
                examples.append({**it, "case": (j.get("case_title") or "")[:60]})
        if args.store:
            new += await jr.store(j["id"], items, j.get("text_sha256", ""))
            await db.judgment_scan.update_one({"_id": j["id"]}, {"$set": {"sha": j.get("text_sha256", "")}}, upsert=True)
        if scanned % 2000 == 0:
            print(f"  ... {scanned} judgments read, {found} statements found", flush=True)
    print(f"judgments read: {scanned} (skipped as already read: {skipped}) | statements found: {found} | by kind: {dict(by_rel)}" + (f" | newly recorded: {new}" if args.store else ""))
    for e in examples:
        print(f"  [{e['relation']}] target as written: {e['target_ref'] or '(not named)'} | {e['case']}\n      \"{e['quote'][:220]}\"")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", action="store_true")
    ap.add_argument("--court")
    ap.add_argument("--limit", type=int)
    asyncio.run(main(ap.parse_args()))
