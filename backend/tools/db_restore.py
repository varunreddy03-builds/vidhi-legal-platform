"""Restore an encrypted backup made by tools/db_backup.py.

    python tools/db_restore.py BACKUP.archive.tar.gz.gpg --passphrase-file F --verify-only            # decrypt and check every hash; touches nothing
    python tools/db_restore.py BACKUP.archive.tar.gz.gpg --passphrase-file F --target-db vidhi_check   # restore into a NEW, empty database (practice this before you need it)
    python tools/db_restore.py BACKUP.archive.tar.gz.gpg --passphrase-file F --replace --yes          # DESTRUCTIVE: replaces the database named by DB_NAME

Uses MONGO_URL and DB_NAME from the environment. Without --target-db the target is DB_NAME, and that always needs --replace and a typed confirmation (or --yes) if it holds data."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo import MongoClient  # noqa: E402

from lib import dbbackup  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--passphrase-file", required=True)
    ap.add_argument("--target-db")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    url, name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or (not name and not a.target_db):
        print("MONGO_URL (and DB_NAME, or --target-db) must be set.", file=sys.stderr)
        return 2
    target = a.target_db or name
    client = MongoClient(url, serverSelectionTimeoutMS=15000)
    try:
        if a.replace and not a.verify_only and not a.yes:
            print(f"This REPLACES everything in database '{target}' with the contents of {a.file}.")
            if input("Type the database name to continue: ").strip() != target:
                print("not confirmed - nothing changed", file=sys.stderr)
                return 1
        r = dbbackup.restore(client, a.file, a.passphrase_file, target, replace=a.replace, verify_only=a.verify_only)
    except dbbackup.BackupError as exc:
        print(f"RESTORE FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
    print(("verified (nothing was changed)" if a.verify_only else f"restored into '{target}'") + f": backup of '{r['source_db']}' made {r['created_at']}")
    for coll, n in sorted(r["collections"].items()):
        print(f"  {coll}: {n}")
    if r["restored"]:
        print("Restart the API so it re-checks its indexes.")
        print("IMPORTANT before anyone signs in: erase again what was erased after this backup was made:")
        print("  python tools/reapply_erasures.py --ledger <the backups folder>/erasures.jsonl   (add --dry-run first to see the list)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
