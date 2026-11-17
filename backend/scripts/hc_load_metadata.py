"""Load the CASE LIST (not the judgments' text) of every High Court in the public AWS dataset into MongoDB, for a date range.

    C:\\vidhi-tools\\venv-ocr\\Scripts\\python.exe -I -X utf8 scripts/hc_load_metadata.py --from 1999-01-01 --to 2026-07-30 [--mongo-url mongodb://127.0.0.1:27017] [--db vidhi_dev]

Runs in the tools environment (needs pyarrow and pymongo). For each court-and-year file in the bucket's metadata/parquet it downloads the file, keeps one compact record per case
(title, court, bench, judge, CNR, dates, outcome, the opening of the order, the PDF address), inserts it and deletes the download. It remembers finished files in a state file, so it
can be stopped and started again. The judgments' text is NOT loaded here: the app fetches a judgment's PDF from the archive when someone opens it.
Every record is "UNVERIFIED - not reviewed". Data: Indian High Court Judgments, Dattam Labs, CC-BY-4.0."""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

import pyarrow.parquet as pq
from pymongo import ASCENDING, MongoClient
from pymongo.errors import BulkWriteError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import verified_store as vstore  # noqa: E402
from lib.script_detect import stored_script  # noqa: E402

BUCKET = "https://indian-high-court-judgments.s3.ap-south-1.amazonaws.com"
STATUS = "UNVERIFIED - not reviewed"
ATTRIBUTION = "Indian High Court Judgments, Dattam Labs, from the eCourts website, licence CC-BY-4.0: https://registry.opendata.aws/indian-high-court-judgments"
EMPTY_SHA = hashlib.sha256(b"").hexdigest()
COLUMNS = ["court_code", "title", "description", "judge", "pdf_link", "cnr", "date_of_registration", "decision_date", "disposal_nature", "court", "pdf_exists"]


def get(url: str, dest: Path | None = None) -> bytes | None:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 - fixed https host
                if dest is None:
                    return r.read()
                with open(dest, "wb") as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
                return None
        except Exception:  # noqa: BLE001 - retry, then give up loudly
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def list_keys(prefix: str) -> list[str]:
    out, tok = [], ""
    while True:
        xml = get(f"{BUCKET}/?list-type=2&max-keys=1000&prefix={urllib.parse.quote(prefix)}" + (f"&continuation-token={urllib.parse.quote(tok)}" if tok else "")).decode("utf-8")
        out += re.findall(r"<Key>([^<]+)</Key>", xml)
        n = re.search(r"<NextContinuationToken>([^<]+)", xml)
        if not n:
            return out
        tok = n.group(1)


def clean(s) -> str | None:
    s = " ".join(str(s or "").split())
    return s or None


def iso(d) -> str | None:
    if d is None:
        return None
    if isinstance(d, (datetime, date)):
        return d.date().isoformat() if isinstance(d, datetime) else d.isoformat()
    m = re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})", str(d))
    if not m:
        return None
    try:
        return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
    except ValueError:
        return None


def records(path: Path, key: str, lo: str, hi: str):
    m = re.search(r"year=(\d+)/court=([^/]+)/bench=([^/]+)/", key)
    year, court, bench = m[1], m[2], m[3]
    t = pq.read_table(path, columns=COLUMNS)
    for r in t.to_pylist():
        decided = iso(r.get("decision_date"))
        if decided and not (lo <= decided <= hi):
            continue
        link = r.get("pdf_link") or ""
        name = link.rsplit("/", 1)[-1].removesuffix(".pdf")
        if not name:
            continue
        title, snippet = clean(r.get("title")), (clean(r.get("description")) or "")[:400]
        extra = {"script": s} if (s := stored_script(snippet, title)) else {}  # only a non-Latin record gets the field
        yield {
            **extra,
            "id": f"hc-{court}-{bench}-{name}", "court_code": court, "bench": bench, "year": int(year), "court_name": clean(r.get("court")) or court,
            "case_title": clean(r.get("title")), "judge": clean(r.get("judge")), "cnr": clean(r.get("cnr")), "registration_date": iso(r.get("date_of_registration")),
            "decision_date": decided, "disposal": clean(r.get("disposal_nature")), "snippet": (clean(r.get("description")) or "")[:400], "pdf_exists": bool(r.get("pdf_exists")),
            "source_url": f"{BUCKET}/data/pdf/year={year}/court={court}/bench={bench}/{name}.pdf",
            "text": "", "text_chars": 0, "text_kind": "NOT_LOADED", "text_sha256": EMPTY_SHA, "licence": "CC-BY-4.0", "attribution": ATTRIBUTION, "status": STATUS, "origin": "bulk",
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="lo", default="1999-01-01")
    ap.add_argument("--to", dest="hi", default="2026-07-30")
    ap.add_argument("--mongo-url", default="mongodb://127.0.0.1:27017")
    ap.add_argument("--db", default="vidhi_dev")
    ap.add_argument("--work", default=r"C:\vidhi-tools\hc-meta")
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    state_file = work / "done.json"
    done = set(json.loads(state_file.read_text()) if state_file.exists() else [])
    col = vstore.sync_collection(MongoClient(a.mongo_url)[a.db], "hc_judgments")
    col.create_index([("id", ASCENDING)], name="id", unique=True)
    col.create_index([("court_code", ASCENDING), ("decision_date", ASCENDING)], name="court_date")
    y_lo, y_hi = int(a.lo[:4]), int(a.hi[:4])
    keys = [k for y in range(y_lo, y_hi + 1) for k in list_keys(f"metadata/parquet/year={y}/") if k.endswith("metadata.parquet")]
    print(f"{len(keys)} files, {len(done)} already done", flush=True)
    total = 0
    for i, key in enumerate(keys, 1):
        if key in done:
            continue
        tmp = work / "current.parquet"
        get(f"{BUCKET}/{urllib.parse.quote(key)}", tmp)
        batch, n = [], 0
        for rec in records(tmp, key, a.lo, a.hi):
            batch.append(rec)
            if len(batch) >= 5000:
                n += len(batch)
                try:
                    col.insert_many(batch, ordered=False)
                except BulkWriteError:  # duplicates from an earlier, interrupted run
                    pass
                batch = []
        if batch:
            n += len(batch)
            try:
                col.insert_many(batch, ordered=False)
            except BulkWriteError:
                pass
        tmp.unlink(missing_ok=True)
        done.add(key)
        state_file.write_text(json.dumps(sorted(done)))
        total += n
        print(f"[{i}/{len(keys)}] {key.split('metadata/parquet/')[1]}: {n} cases (running total {total})", flush=True)
    print(f"finished: {total} cases this run; database now holds {col.estimated_document_count()} judgment records", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
