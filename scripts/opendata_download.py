"""Downloads the Supreme Court judgments open dataset (registry.opendata.aws/indian-supreme-court-judgments, CC-BY-4.0, Dattam Labs) from its public S3 bucket.
No AWS account or key: plain HTTPS GET requests to the public bucket.

    python scripts/opendata_download.py --out C:/vidhi-tools/data/sc [--years 1950-2026] [--with-regional]

For each year it fetches the English judgments archive (data/tar/year=YYYY/english/*.tar), its index, and the metadata archive (metadata/tar/year=YYYY/metadata.tar + index).
Resumable: a file whose size already equals the size S3 reports is skipped; a partial file is continued with an HTTP Range request. Every file is checked against the size S3 reports.
Writes a manifest (manifest.json) with each file's key, size, S3 ETag and the time it was fetched. Prints progress only."""

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import httpx

BUCKET = "https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com/"
NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


def list_keys(prefix: str) -> list[tuple[str, int, str]]:
    out, token = [], None
    while True:
        params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        r = httpx.get(BUCKET, params=params, timeout=60)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        for c in root.findall("s3:Contents", NS):
            out.append((c.find("s3:Key", NS).text, int(c.find("s3:Size", NS).text), c.find("s3:ETag", NS).text.strip('"')))
        if root.find("s3:IsTruncated", NS).text != "true":
            return out
        token = root.find("s3:NextContinuationToken", NS).text


def fetch(key: str, size: int, dest: Path, attempts: int = 6) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, attempts + 1):
        have = dest.stat().st_size if dest.exists() else 0
        if have == size:
            return
        if have > size:
            dest.unlink()
            have = 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with httpx.stream("GET", BUCKET + key, headers=headers, timeout=httpx.Timeout(60, read=300)) as r:
                if r.status_code not in (200, 206):
                    raise httpx.HTTPError(f"status {r.status_code}")
                mode = "ab" if (have and r.status_code == 206) else "wb"
                with open(dest, mode) as f:
                    for chunk in r.iter_bytes(1024 * 1024):
                        f.write(chunk)
        except (httpx.HTTPError, OSError) as exc:
            print(f"  retry {attempt}/{attempts} for {key}: {type(exc).__name__}", flush=True)
            time.sleep(min(60, 5 * attempt))
            continue
    if not dest.exists() or dest.stat().st_size != size:
        raise SystemExit(f"FAILED: {key} did not download completely after {attempts} attempts")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--years", default="1950-2026")
    ap.add_argument("--with-regional", action="store_true")
    a = ap.parse_args()
    first, last = (int(x) for x in a.years.split("-"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"source": "registry.opendata.aws/indian-supreme-court-judgments", "licence": "CC-BY-4.0", "files": {}}
    total = done = 0
    plan = []
    for y in range(first, last + 1):
        prefixes = [f"data/tar/year={y}/english/", f"metadata/tar/year={y}/"] + ([f"data/tar/year={y}/regional/"] if a.with_regional else [])
        for p in prefixes:
            plan += list_keys(p)
    total = sum(s for _, s, _ in plan)
    print(f"{len(plan)} files, {total / 1024**3:.2f} GiB to have locally", flush=True)
    started = time.time()
    for key, size, etag in plan:
        dest = out / key
        fetch(key, size, dest)
        done += size
        manifest["files"][key] = {"size": size, "etag": etag, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        rate = done / max(1, time.time() - started)
        print(f"  {done / 1024**3:6.2f}/{total / 1024**3:.2f} GiB  {key}", flush=True)
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("DOWNLOAD COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
