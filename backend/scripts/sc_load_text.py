"""Read the full text of Supreme Court judgments from the LOCAL copy of the public dataset into the judgment collection. No download: the PDFs are already on this PC (SC_DATA_DIR).

    python scripts/sc_load_text.py [--from-year 1999] [--to-year 2026] [--root C:\vidhi-tools\data\sc] [--mongo-url mongodb://127.0.0.1:27017] [--db vidhi_dev] [--limit N]

For each Supreme Court record already loaded by scripts/sc_load_index.py whose text is still NOT_LOADED, the judgment's PDF is read from the local archive. A file whose text does not look like
English prose (a table, a scan, another language) is marked NO_TEXT_LAYER and keeps no text. Resumable: records that already hold text are skipped. Text is never edited; every record stays "not reviewed"."""

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo import MongoClient  # noqa: E402

from lib import verified_store as vstore  # noqa: E402
from lib.refcheck import scdata  # noqa: E402
from lib.refcheck.scsource import SupremeCourtData, judgment_blocks, readable  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-year", type=int, default=1999)
    ap.add_argument("--to-year", type=int, default=2026)
    ap.add_argument("--root", default=r"C:\vidhi-tools\data\sc")
    ap.add_argument("--mongo-url", default="mongodb://127.0.0.1:27017")
    ap.add_argument("--db", default="vidhi_dev")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    recs = []
    for y in range(a.from_year, a.to_year + 1):
        recs += scdata.read_year(Path(a.root), y)
    src = SupremeCourtData(a.root, records=scdata.merge_duplicates(recs))
    col = vstore.sync_collection(MongoClient(a.mongo_url)[a.db], "hc_judgments")
    todo = {d["id"] for d in col.find({"court_code": "SC", "text_kind": "NOT_LOADED"}, {"id": 1})}
    ops, done, scans, failed = [], 0, 0, 0
    for r in src.records.values():
        rid = f"sc-{r.stem}"
        if rid not in todo:
            continue
        if a.limit and done + scans + failed >= a.limit:
            break
        try:
            blocks = judgment_blocks(src._pdf_bytes(r))
        except Exception:  # noqa: BLE001 - a missing or broken file is left as it was (still fetchable on demand)
            failed += 1
            continue
        if readable(blocks):
            text = "\n\n".join(blocks)
            ops.append(col.update_op({"id": rid}, {"text": text, "text_chars": len(text), "text_kind": "TEXT", "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}))
            done += 1
        else:
            ops.append(col.update_op({"id": rid}, {"text_kind": "NO_TEXT_LAYER"}))
            scans += 1
        if len(ops) >= 200:
            col.bulk_write(ops, ordered=False)
            ops = []
            print(f"{done} with text, {scans} without readable text, {failed} unreadable files", flush=True)
    if ops:
        col.bulk_write(ops, ordered=False)
    print(f"finished: {done} judgments with text, {scans} without readable text, {failed} files that could not be read")
    return 0


if __name__ == "__main__":
    sys.exit(main())
