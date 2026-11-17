"""Fetch the TEXT of High Court judgments from the public AWS bucket, keep the text only (not the PDFs), and skip the ones that are not worth keeping.

    C:\\vidhi-tools\\venv-ocr\\Scripts\\python.exe -I -X utf8 scripts/hc_text_harvest.py --year 2024 [--court 36_29] [--min-kb 20] [--limit N] [--workers 6] [--db vidhi_dev]

Works on the case list already loaded by scripts/hc_load_metadata.py. For a year (and optionally one court) it lists the PDFs in the bucket WITH their sizes, then:
  * a case with no PDF in the bucket is marked pdf_exists=false and skipped (the case list's own pdf_exists column is wrong for every row, so the bucket listing decides);
  * a PDF smaller than --min-kb (default 20 KB: adjournments, listing and other one-page interim orders) is skipped, and its size recorded in pdf_bytes;
  * every other PDF is downloaded, its text layer read (pypdf), and the text stored. A PDF with almost no text layer is marked NO_TEXT_LAYER (a scan; it can be OCR'd later).
Resumable: a record that already holds text, or whose size is already below the cut-off, is not fetched again. The PDFs are never kept: only the text.
SPEED: measured on this PC the bucket gives about 0.8 MB/s in total, so a whole year of a big court takes days here. On a machine inside AWS (ap-south-1) the same script is fast.
Every record stays "UNVERIFIED - not reviewed". Data: Indian High Court Judgments, Dattam Labs, CC-BY-4.0."""

import argparse
import hashlib
import io
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed

BUCKET = "https://indian-high-court-judgments.s3.ap-south-1.amazonaws.com"
MAX_PDF = 20 * 1024 * 1024
MAX_TEXT = 2_000_000
MIN_TEXT = 200


def get(url: str) -> bytes:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 - fixed https host
                return r.read(MAX_PDF + 1)
        except Exception:  # noqa: BLE001
            if attempt == 2:
                raise


def sizes(prefix: str) -> dict[str, int]:
    """{file name: size in bytes} for every PDF under a bucket prefix."""
    out: dict[str, int] = {}
    tok = ""
    while True:
        xml = get(f"{BUCKET}/?list-type=2&max-keys=1000&prefix={urllib.parse.quote(prefix)}" + (f"&continuation-token={urllib.parse.quote(tok)}" if tok else "")).decode("utf-8")
        for k, s in re.findall(r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", xml, re.S):
            out[k.rsplit("/", 1)[1]] = int(s)
        n = re.search(r"<NextContinuationToken>([^<]+)", xml)
        if not n:
            return out
        tok = n.group(1)


def work(job: tuple[str, str]) -> tuple[str, str, str]:
    """(record id, text, kind) for one PDF. Runs in a worker process."""
    rid, url = job
    try:
        data = get(url)
        if len(data) > MAX_PDF:
            return rid, "", "FAILED"
        from pypdf import PdfReader

        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages).strip()[:MAX_TEXT]
    except Exception:  # noqa: BLE001 - a broken file or a network error leaves the record as it was
        return rid, "", "FAILED"
    return (rid, text, "TEXT") if len(text) >= MIN_TEXT else (rid, "", "NO_TEXT_LAYER")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--court", default="")
    ap.add_argument("--min-kb", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--mongo-url", default="mongodb://127.0.0.1:27017")
    ap.add_argument("--db", default="vidhi_dev")
    a = ap.parse_args()
    from pathlib import Path

    from pymongo import MongoClient  # only this mode needs a database; scripts/hc_text_export.py (for a machine in AWS) does not

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lib import verified_store as vstore

    col = vstore.sync_collection(MongoClient(a.mongo_url)[a.db], "hc_judgments")
    flt: dict = {"year": a.year, "origin": "bulk", "text_kind": "NOT_LOADED", "court_code": {"$ne": "SC"}}  # the dataset's own pdf_exists column is False for everything, even cases whose PDF is there: the bucket listing decides
    if a.court:
        flt["court_code"] = a.court
    groups: dict[tuple[str, str], list[dict]] = {}
    for d in col.find(flt, {"id": 1, "court_code": 1, "bench": 1, "source_url": 1, "pdf_bytes": 1}):
        groups.setdefault((d["court_code"], d["bench"]), []).append(d)
    cut = a.min_kb * 1024
    jobs: list[tuple[str, str]] = []
    ops: list = []
    skipped_short = missing = 0
    for (court, bench), docs in groups.items():
        listing = sizes(f"data/pdf/year={a.year}/court={court}/bench={bench}/")
        for d in docs:
            name = d["source_url"].rsplit("/", 1)[1]
            size = listing.get(name)
            if size is None:
                missing += 1
                ops.append(col.update_op({"id": d["id"]}, {"pdf_exists": False}))
            elif size < cut:
                skipped_short += 1
                ops.append(col.update_op({"id": d["id"]}, {"pdf_bytes": size}))
            else:
                jobs.append((d["id"], d["source_url"]))
                ops.append(col.update_op({"id": d["id"]}, {"pdf_exists": True, "pdf_bytes": size}))
        if len(ops) >= 1000:
            col.bulk_write(ops, ordered=False)
            ops = []
    if ops:
        col.bulk_write(ops, ordered=False)
    if a.limit:
        jobs = jobs[: a.limit]
    print(f"year {a.year}: {len(jobs)} to fetch, {skipped_short} skipped as shorter than {a.min_kb} KB, {missing} with no PDF in the bucket", flush=True)
    done = nodata = failed = 0
    batch: list = []
    with ProcessPoolExecutor(a.workers) as pool:
        for fut in as_completed([pool.submit(work, j) for j in jobs]):
            rid, text, kind = fut.result()
            if kind == "FAILED":
                failed += 1
                continue
            if kind == "TEXT":
                done += 1
                batch.append(col.update_op({"id": rid}, {"text": text, "text_chars": len(text), "text_kind": "TEXT", "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}))
            else:
                nodata += 1
                batch.append(col.update_op({"id": rid}, {"text_kind": "NO_TEXT_LAYER"}))
            if len(batch) >= 100:
                col.bulk_write(batch, ordered=False)
                batch = []
                print(f"  {done} with text, {nodata} scans, {failed} failed", flush=True)
    if batch:
        col.bulk_write(batch, ordered=False)
    print(f"finished year {a.year}: {done} with text, {nodata} scans (no text layer), {failed} failed (will be retried on the next run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
