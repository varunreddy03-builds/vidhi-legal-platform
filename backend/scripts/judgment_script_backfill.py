"""Gives every judgment record whose title or opening is NOT in Latin script a `script` field, and builds the small index that makes the script filter quick. Run once on a database that was loaded
before the script filter existed (new loads through hc_load_metadata.py and sc_load_index.py set the field themselves).

    C:\vidhi-tools\venv-ocr\Scripts\python.exe -I -X utf8 scripts/judgment_script_backfill.py [--mongo-url mongodb://127.0.0.1:27017] [--db vidhi_dev] [--dry-run]

It finds the candidates with a MongoDB pattern for any letter outside the Latin ranges, in `case_title` and `snippet` (a scan of the whole collection: it takes some minutes on 18 million records), checks each
with lib.script_detect, and writes `script` only where the result is not "latin". Nothing else on a record changes. Safe to run again. The script says WHICH writing system, never which language."""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pymongo import ASCENDING, MongoClient  # noqa: E402

from lib import verified_store as vstore  # noqa: E402
from lib.script_detect import stored_script  # noqa: E402

NON_LATIN = r"[^\x00-\x{024F}\x{2000}-\x{206F}]"  # a character outside Latin letters and common punctuation (curly quotes and dashes are not a script)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mongo-url", default="mongodb://127.0.0.1:27017")
    ap.add_argument("--db", default="vidhi_dev")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    col = vstore.sync_collection(MongoClient(a.mongo_url)[a.db], "hc_judgments")  # law-data writes go only through the verified store
    t0, seen, changed, ops = time.time(), 0, {}, []
    cur = col.find({"$or": [{"case_title": {"$regex": NON_LATIN}}, {"snippet": {"$regex": NON_LATIN}}], "script": {"$exists": False}}, {"id": 1, "case_title": 1, "snippet": 1}, no_cursor_timeout=True)
    try:
        for r in cur:
            seen += 1
            s = stored_script(r.get("snippet"), r.get("case_title"))
            if s:
                changed[s] = changed.get(s, 0) + 1
                if not a.dry_run:
                    ops.append(col.update_op({"id": r["id"]}, {"script": s}))
                    if len(ops) >= 2000:
                        col.bulk_write(ops)
                        ops = []
    finally:
        cur.close()
    if ops:
        col.bulk_write(ops)
    if not a.dry_run:
        col.create_index([("script", ASCENDING), ("decision_date", -1)], name="script_date", partialFilterExpression={"script": {"$exists": True}})  # holds only the few non-Latin records
    print(f"checked {seen} candidates in {time.time() - t0:.0f}s; {'would set' if a.dry_run else 'set'} script on {sum(changed.values())}: {changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
