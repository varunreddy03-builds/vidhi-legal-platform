"""Encrypted database backup.

    python tools/db_backup.py --out-dir /backups --passphrase-file /run/secrets/backup_passphrase [--keep-days 30] [--every-hours 24]

Uses MONGO_URL and DB_NAME from the environment. The passphrase is read from a FILE. With --every-hours it keeps running and backs up on that schedule (the backup container uses this).
Prints the file name and counts only; it never prints the database address or the passphrase. Keep a copy of the passphrase somewhere other than the server that holds the backups,
and copy the backups off the server too (see docs/hosting-runbook.md): a backup on the same disk as the database does not survive losing that disk."""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo import MongoClient  # noqa: E402

from lib import dbbackup  # noqa: E402


def once(a) -> int:
    url, name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not name:
        print("MONGO_URL and DB_NAME must be set in the environment.", file=sys.stderr)
        return 2
    client = MongoClient(url, serverSelectionTimeoutMS=15000)
    try:
        r = dbbackup.backup(client, name, a.out_dir, a.passphrase_file, a.keep_days)
    except dbbackup.BackupError as exc:
        print(f"BACKUP FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
    print(f"backup written: {r['path']} ({r['bytes']} bytes, {r['documents']} documents in {r['collections']} collections)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--passphrase-file", required=True)
    ap.add_argument("--keep-days", type=int, default=30)
    ap.add_argument("--every-hours", type=float, default=0)
    a = ap.parse_args()
    if not a.every_hours:
        return once(a)
    while True:  # a failed run is reported and tried again next time; the loop itself never stops
        code = once(a)
        if code:
            print(f"backup did not complete (code {code}); trying again in {a.every_hours} hours", file=sys.stderr, flush=True)
        time.sleep(a.every_hours * 3600)


if __name__ == "__main__":
    sys.exit(main())
