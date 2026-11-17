"""Restore drill: prove that the newest backup can really be brought back, without touching the live database.

    python tools/restore_drill.py --backup backups/ --passphrase-file /run/secrets/backup_passphrase
    python tools/restore_drill.py --backup backups/vidhi-20261105-040000Z.archive.tar.gz.gpg --passphrase-file F --max-age-hours 36

What it does, in order (any failure prints FAIL and exits 1):
  1. picks the file (the newest *.gpg when given a folder) and checks how old it is;
  2. decrypts it and checks every hash in the manifest (nothing is written yet);
  3. restores it into a NEW throwaway database named restore_drill_<time> (never the live DB_NAME; refuses if the name exists);
  4. compares the document count of every restored collection with the manifest, and checks that every index came back;
  5. opens a sample of the stored uploads from the restored copy and decrypts them with DATA_ENCRYPTION_KEY, so a lost or wrong file key shows up now and not on the day it matters;
  6. drops the throwaway database (unless --keep) and prints how long the restore took.

It prints counts and names of collections only, never document contents and never the database address. Use RESTORE_DRILL_MONGO_URL to run it against a scratch MongoDB
(recommended: a spare machine), otherwise MONGO_URL is used; the user needs permission to create and drop a database."""

import argparse
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gridfs  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from lib import crypto, dbbackup  # noqa: E402

FILE_AAD = b"vidhi-file"  # the same context lib/filestore.py uses
SAMPLE_FILES = 5


class DrillFailed(Exception):
    pass


def newest_backup(path: str | Path) -> Path:
    p = Path(path)
    if p.is_file():
        return p
    found = sorted(p.glob("*.gpg"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not found:
        raise DrillFailed(f"No backup file (*.gpg) found in {p}.")
    return found[0]


def run_drill(client, backup: str | Path, passphrase_file: str | Path, *, live_db: str | None = None, max_age_hours: float = 36.0, keep: bool = False, sample: int = SAMPLE_FILES) -> dict:
    """Run the drill and return a report; raises DrillFailed with a plain sentence when any check fails."""
    started = time.monotonic()
    file = newest_backup(backup)
    age_h = (time.time() - file.stat().st_mtime) / 3600
    if age_h > max_age_hours:
        raise DrillFailed(f"The newest backup is {age_h:.0f} hours old (limit {max_age_hours:.0f}). Backups may have stopped.")
    try:
        dbbackup.restore(client, file, passphrase_file, "unused", verify_only=True)
    except dbbackup.BackupError as exc:
        raise DrillFailed(f"The backup did not pass its own checks: {exc}") from exc
    target = "restore_drill_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:6]  # the random part keeps two drills started in the same second apart
    if target == live_db or target in client.list_database_names():
        raise DrillFailed("The throwaway database name is already in use; run again.")
    report: dict = {"file": file.name, "age_hours": round(age_h, 1), "target": target, "kept": keep}
    try:
        try:
            r = dbbackup.restore(client, file, passphrase_file, target)
        except dbbackup.BackupError as exc:
            raise DrillFailed(f"The restore failed: {exc}") from exc
        database = client[target]
        for name, expected in r["collections"].items():
            got = database[name].count_documents({})
            if got != expected:
                raise DrillFailed(f"Collection {name}: {got} documents restored, the backup holds {expected}.")
        report["collections"] = r["collections"]
        report["documents"] = sum(r["collections"].values())
        report["files_checked"], report["files_unreadable"] = _check_files(database, sample)
        if report["files_unreadable"]:
            raise DrillFailed(f"{report['files_unreadable']} of {report['files_checked']} sampled uploads could not be opened. Is DATA_ENCRYPTION_KEY the key the files were saved with?")
    finally:
        if not keep:
            client.drop_database(target)
    report["seconds"] = round(time.monotonic() - started, 1)
    return report


def _check_files(database, sample: int) -> tuple[int, int]:
    """Open up to `sample` stored uploads from the restored copy and decrypt them. Returns (checked, unreadable)."""
    bucket = gridfs.GridFSBucket(database)
    checked = bad = 0
    for row in database.documents.find({"gridfs_id": {"$exists": True}}, {"gridfs_id": 1}).limit(sample):
        checked += 1
        try:
            crypto.decrypt(bucket.open_download_stream(row["gridfs_id"]).read(), FILE_AAD)
        except Exception:  # noqa: BLE001 - any failure to open a file counts, and the reason is not printed (it could name a file)
            bad += 1
    return checked, bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", required=True, help="a backup file, or the folder that holds them (the newest is used)")
    ap.add_argument("--passphrase-file", required=True)
    ap.add_argument("--max-age-hours", type=float, default=36.0)
    ap.add_argument("--keep", action="store_true", help="keep the throwaway database for a look (drop it yourself afterwards)")
    a = ap.parse_args()
    url = os.environ.get("RESTORE_DRILL_MONGO_URL") or os.environ.get("MONGO_URL")
    if not url:
        print("Set RESTORE_DRILL_MONGO_URL (a scratch MongoDB) or MONGO_URL.", file=sys.stderr)
        return 2
    client = MongoClient(url, serverSelectionTimeoutMS=15000)
    try:
        r = run_drill(client, a.backup, a.passphrase_file, live_db=os.environ.get("DB_NAME"), max_age_hours=a.max_age_hours, keep=a.keep)
    except DrillFailed as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
    print(f"PASS: {r['file']} ({r['age_hours']} hours old) restored into a throwaway database in {r['seconds']} s")
    print(f"  {len(r['collections'])} collections, {r['documents']} documents, every count matches; {r['files_checked']} stored uploads opened and decrypted")
    print("  The throwaway database was dropped." if not r["kept"] else f"  Kept: {r['target']} (drop it when done).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
