"""Harvest High Court judgment TEXT into compressed files, with no database: meant to run on a machine INSIDE AWS (region ap-south-1, Mumbai), where the public bucket is read fast.

    python scripts/hc_text_export.py --out /data/hc_text --from-year 1999 --to-year 2026 [--court 36_29] [--min-kb 20] [--workers 16]

Needs only Python 3.10+ and `pip install pypdf`. For each year, court and bench it lists the PDFs with their sizes, skips PDFs smaller than --min-kb (adjournments and other one-page interim orders),
reads the text layer of the rest, and writes one file per bench: <out>/<year>/<court>__<bench>.jsonl.gz, one JSON line per judgment: {"id", "text", "kind", "bytes"}. The PDFs are never kept.
Resumable: stop it any time and run it again; judgments already in a file are not fetched again. Bring the files to the VIDHI machine and load them with scripts/hc_import_text.py.
Every judgment stays "UNVERIFIED - not reviewed". Data: Indian High Court Judgments, Dattam Labs, CC-BY-4.0."""

import argparse
import gzip
import json
import re
import sys
import urllib.parse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hc_text_harvest import BUCKET, get, sizes, work  # noqa: E402


def children(prefix: str) -> list[str]:
    xml = get(f"{BUCKET}/?list-type=2&delimiter=/&max-keys=1000&prefix={urllib.parse.quote(prefix)}").decode("utf-8")
    return [m for m in re.findall(r"<Prefix>([^<]+)</Prefix>", xml) if m != prefix]


def done_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    if path.exists():
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for line in f:
                    try:
                        ids.add(json.loads(line)["id"])
                    except (ValueError, KeyError):
                        pass
        except (OSError, EOFError):
            pass  # a part-written last member from a stopped run: what was read so far counts
    return ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--from-year", type=int, default=1999)
    ap.add_argument("--to-year", type=int, default=2026)
    ap.add_argument("--court", default="")
    ap.add_argument("--min-kb", type=int, default=20)
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()
    out = Path(a.out)
    cut = a.min_kb * 1024
    total = 0
    with ProcessPoolExecutor(a.workers) as pool:
        for year in range(a.from_year, a.to_year + 1):
            for cp in children(f"data/pdf/year={year}/"):
                court = cp.rstrip("/").rsplit("court=", 1)[1]
                if a.court and court != a.court:
                    continue
                for bp in children(cp):
                    bench = bp.rstrip("/").rsplit("bench=", 1)[1]
                    target = out / str(year) / f"{court}__{bench}.jsonl.gz"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    have = done_ids(target)
                    listing = sizes(f"data/pdf/year={year}/court={court}/bench={bench}/")
                    jobs, short = [], 0
                    for name, size in listing.items():
                        rid = f"hc-{court}-{bench}-{name[:-4]}"
                        if not name.endswith(".pdf") or rid in have:
                            continue
                        if size < cut:
                            short += 1
                            continue
                        jobs.append((rid, f"{BUCKET}/data/pdf/year={year}/court={court}/bench={bench}/{name}", size))
                    print(f"{year} {court} {bench}: {len(jobs)} to fetch, {short} skipped as short, {len(have)} already done", flush=True)
                    with gzip.open(target, "at", encoding="utf-8") as f:  # appending makes a new gzip member: the file stays readable after any stop
                        for (rid, text, kind), job in zip(pool.map(work, [(j[0], j[1]) for j in jobs], chunksize=8), jobs):
                            if kind == "FAILED":
                                continue  # not written, so the next run tries it again
                            f.write(json.dumps({"id": rid, "text": text, "kind": kind, "bytes": job[2]}, ensure_ascii=False) + "\n")
                            total += 1
    print(f"finished: {total} judgments written this run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
