"""Fetch a SAMPLE of High Court judgments from the public AWS open-data bucket "indian-high-court-judgments" (CC-BY-4.0, Dattam Labs; sourced from eCourts).

    python scripts/hc_fetch.py --year 2023 --court 36_29 --bench taphc --count 25

Writes data/hc_raw/<year>/<court>/<bench>/<name>.pdf and <name>.json (the bucket's own metadata file), unchanged. Nothing here edits a judgment.
Only single-case files are fetched. The yearly tar archives are tens of GB and are never downloaded by this script.
Attribution to show wherever these are used: "Indian High Court Judgments was accessed on <date> from https://registry.opendata.aws/indian-high-court-judgments."""

import argparse
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BUCKET = "https://indian-high-court-judgments.s3.ap-south-1.amazonaws.com"
ROOT = Path(__file__).resolve().parent.parent / "data" / "hc_raw"
MAX_PDF = 5 * 1024 * 1024  # a sample: skip very large files


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 - fixed https host
        return r.read()


def list_keys(prefix: str, limit: int) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    token = ""
    while len(out) < limit:
        url = f"{BUCKET}/?list-type=2&prefix={urllib.parse.quote(prefix)}&max-keys=200" + (f"&continuation-token={urllib.parse.quote(token)}" if token else "")
        xml = get(url).decode("utf-8")
        out += [(m[0], int(m[1])) for m in re.findall(r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", xml, re.S)]
        nxt = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", xml)
        if not nxt:
            break
        token = nxt.group(1)
    return out


def children(prefix: str) -> list[str]:
    """The folders directly under a prefix, for example every court under a year."""
    xml = get(f"{BUCKET}/?list-type=2&delimiter=/&max-keys=1000&prefix={urllib.parse.quote(prefix)}").decode("utf-8")
    return [m for m in re.findall(r"<Prefix>([^<]+)</Prefix>", xml) if m != prefix]


def fetch(year: str, court: str, bench: str, count: int) -> int:
    base = f"year={year}/court={court}/bench={bench}/"
    pdfs = [(k, s) for k, s in list_keys(f"data/pdf/{base}", count * 3) if k.endswith(".pdf") and s <= MAX_PDF][:count]
    dest = ROOT / year / court / bench
    dest.mkdir(parents=True, exist_ok=True)
    got = 0
    for key, size in pdfs:
        name = key.rsplit("/", 1)[1][:-4]
        meta_key = f"metadata/json/{base}{name}.json"
        try:
            (dest / f"{name}.pdf").write_bytes(get(f"{BUCKET}/{urllib.parse.quote(key)}"))
            (dest / f"{name}.json").write_bytes(get(f"{BUCKET}/{urllib.parse.quote(meta_key)}"))
            got += 1
        except Exception as exc:  # noqa: BLE001 - report and move on
            print(f"skipped {name}: {exc}", file=sys.stderr)
    print(f"fetched {got} judgment(s) into {dest}")
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", required=True)
    ap.add_argument("--court", help="for example 36_29 (Telangana). Leave out with --all-courts")
    ap.add_argument("--bench", help="for example taphc")
    ap.add_argument("--all-courts", action="store_true", help="every High Court and bench in the bucket for that year, --count each")
    ap.add_argument("--count", type=int, default=20)
    a = ap.parse_args()
    if not a.all_courts:
        if not a.court or not a.bench:
            ap.error("give --court and --bench, or use --all-courts")
        return 0 if fetch(a.year, a.court, a.bench, a.count) else 1
    total = 0
    for cp in children(f"data/pdf/year={a.year}/"):
        court = cp.rstrip("/").rsplit("court=", 1)[1]
        for bp in children(cp):
            total += fetch(a.year, court, bp.rstrip("/").rsplit("bench=", 1)[1], a.count)
    print(f"total fetched: {total}")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
