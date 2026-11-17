"""Builds (or updates) the Tantivy search index over the court case list in MongoDB. MongoDB stays the source of truth: the index can be deleted and rebuilt at any time.

    python scripts/judgment_index_build.py                 # rebuild from scratch (repeatable; empties the index folder first)
    python scripts/judgment_index_build.py --update        # only the cases added since the last build, plus a refresh of the cases whose text has been loaded
    python scripts/judgment_index_build.py --limit 50000   # a trial build of the first N cases
    python scripts/judgment_index_build.py --status        # what is built, nothing else

Environment: MONGO_URL and DB_NAME as for the app (the dev app uses vidhi_dev); JUDGMENT_INDEX_DIR for where the index lives (default backend/data/judgment_index; keep it OUT of a
cloud-synced folder, it is several gigabytes)."""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bson import ObjectId  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from lib import judgment_index as ji  # noqa: E402
from lib import verified_store as vstore  # noqa: E402

FIELDS = {"id": 1, "case_title": 1, "court_name": 1, "court_code": 1, "year": 1, "judge": 1, "disposal": 1, "cnr": 1, "snippet": 1, "text": 1}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.status:
        print(ji.status())
        return
    db = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)[os.environ["DB_NAME"]]
    coll = vstore.sync_collection(db, "hc_judgments")
    print("database:", os.environ["DB_NAME"], "| index folder:", ji.index_dir(), "| mode:", "update" if args.update else "rebuild", flush=True)
    t0 = time.time()
    flt: dict = {}
    if args.update:
        st = ji.read_state()
        if not st or not st.get("watermark"):
            sys.exit("There is no index to update: run without --update first.")
        flt = {"_id": {"$gt": ObjectId(st["watermark"])}}
    cur = coll.find(flt, FIELDS, no_cursor_timeout=True, batch_size=5000).sort("_id", 1)
    if args.limit:
        cur = cur.limit(args.limit)
    try:
        out = ji.build(cur, rebuild=not args.update, threads=args.threads, progress=lambda n: print(f"  ... {n:,} cases indexed ({time.time() - t0:.0f}s)", flush=True))
    finally:
        cur.close()
    print(f"indexed {out['added']:,} cases in {out['seconds']}s; the index now holds {out['docs']:,}")
    if args.update:
        n = ji.refresh(coll.find({"text_chars": {"$gt": 0}}, {"_id": 1, **FIELDS}))
        print(f"refreshed {n:,} cases whose text is loaded")
    print(ji.status())
    size = sum(f.stat().st_size for f in ji.index_dir().rglob("*") if f.is_file())
    print(f"index size on disk: {size / 1e9:.2f} GB; total time {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
