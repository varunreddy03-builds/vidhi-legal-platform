"""Builds the paragraph index over the judgments whose text is stored in MongoDB. MongoDB stays the source of truth; the index can be deleted and rebuilt at any time.

    python scripts/passage_index_build.py                  # rebuild from scratch (repeatable; empties the folder first)
    python scripts/passage_index_build.py --limit 1000     # a trial build of the first N judgments that have text
    python scripts/passage_index_build.py --status         # what is built, nothing else

Environment: MONGO_URL and DB_NAME as for the app; PASSAGE_INDEX_DIR for where the index lives (default backend/data/passage_index; keep it out of a cloud-synced folder)."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo import MongoClient  # noqa: E402

from lib import passage_index as pi  # noqa: E402
from lib import verified_store as vstore  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.status:
        print({"available": pi.available(), "dir": str(pi.index_dir()), **(pi.read_state() or {})})
        return
    db = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)[os.environ["DB_NAME"]]
    coll = vstore.sync_collection(db, "hc_judgments")
    cur = coll.find({"text_kind": "TEXT"}, {"id": 1, "text": 1}, no_cursor_timeout=True, batch_size=200)
    if args.limit:
        cur = cur.limit(args.limit)
    print("database:", os.environ["DB_NAME"], "| index folder:", pi.index_dir(), flush=True)
    try:
        out = pi.build(cur)
    finally:
        cur.close()
    size = sum(f.stat().st_size for f in pi.index_dir().rglob("*") if f.is_file())
    print(f"indexed {out['passages']:,} passages from {out['judgments']:,} judgments ({out['numbered']:,} with printed paragraph numbers) in {out['seconds']}s; {size / 1e6:.1f} MB on disk")


if __name__ == "__main__":
    main()
