"""Load the text files made by scripts/hc_text_export.py into the judgment collection.

    python scripts/hc_import_text.py /path/to/hc_text [--mongo-url mongodb://127.0.0.1:27017] [--db vidhi_dev]

Only updates records that are already in the case list (scripts/hc_load_metadata.py); an id that is not there is skipped. Resumable and safe to run twice."""

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import verified_store as vstore  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--mongo-url", default="mongodb://127.0.0.1:27017")
    ap.add_argument("--db", default="vidhi_dev")
    a = ap.parse_args()
    col = vstore.sync_collection(MongoClient(a.mongo_url)[a.db], "hc_judgments")
    state = {"read": 0, "matched": 0}
    ops: list = []

    def flush() -> None:
        nonlocal ops
        if ops:
            state["matched"] += col.bulk_write(ops, ordered=False).matched_count
            ops = []

    for f in sorted(Path(a.folder).rglob("*.jsonl.gz")):
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    state["read"] += 1
                    if r["kind"] == "TEXT":
                        s = {"text": r["text"], "text_chars": len(r["text"]), "text_kind": "TEXT", "text_sha256": hashlib.sha256(r["text"].encode("utf-8")).hexdigest(), "pdf_exists": True, "pdf_bytes": r.get("bytes")}
                    else:
                        s = {"text_kind": "NO_TEXT_LAYER", "pdf_exists": True, "pdf_bytes": r.get("bytes")}
                    ops.append(col.update_op({"id": r["id"], "text_kind": "NOT_LOADED"}, s))
                    if len(ops) >= 500:
                        flush()
        except (OSError, EOFError):
            print(f"{f.name}: stopped early (a part-written file); what was readable was loaded")
        print(f"{f.relative_to(a.folder)}: {state['read']} read, {state['matched']} matched so far", flush=True)
    flush()
    print(f"finished: {state['read']} judgments read, {state['matched']} matched a record in the case list; the rest were not in the case list or already had text")
    return 0


if __name__ == "__main__":
    sys.exit(main())
