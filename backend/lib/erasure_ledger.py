"""A list of what was erased, kept OUTSIDE the database so it survives a restore.

Why: a backup is a photograph of the database on one day. If something is erased after that day and the database is later restored from the photograph, the erased data comes
back. This file records every erasure as one line (what kind of thing and its id, when; never a name, an email or any text). After a restore, `tools/reapply_erasures.py` reads it
and erases those things again.

Where: ERASURE_LEDGER_FILE (the compose file points it at ./backups/erasures.jsonl, so it is copied off the server together with the backups). Empty means no ledger. Writing never
stops an erasure: if the file cannot be written the erasure still happens and the failure is logged."""

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

KINDS = ("org", "user", "matter", "case", "document")


def path() -> str:
    return os.environ.get("ERASURE_LEDGER_FILE", "").strip()


def record(kind: str, item_id: str) -> bool:
    """Append one line. True if it was written."""
    target = path()
    if not target or kind not in KINDS or not item_id:
        return False
    line = json.dumps({"kind": kind, "id": str(item_id), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, separators=(",", ":"))
    try:
        with open(target, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except OSError as exc:
        logger.error("erasure ledger not written: %s", type(exc).__name__)
        return False


def read(file: str | None = None) -> list[dict]:
    """Every valid line, oldest first, repeated entries removed. A damaged line is skipped, not fatal."""
    target = file or path()
    if not target or not os.path.exists(target):
        return []
    seen, out = set(), []
    with open(target, encoding="utf-8") as f:
        for raw in f:
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            key = (row.get("kind"), row.get("id"))
            if row.get("kind") in KINDS and row.get("id") and key not in seen:
                seen.add(key)
                out.append(row)
    return out
