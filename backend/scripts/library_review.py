"""A lawyer approves (or rejects) a DRAFT library entry.  Drafts live in data/legal_library/pending/ and can never verify a claim.

  python scripts/library_review.py list
  python scripts/library_review.py approve --id <id> --reviewer "<lawyer's full name>" --on 2026-10-19 --version "as amended up to <date>"
  python scripts/library_review.py reject --id <id>

Approving checks the entry is complete (exact text, official source), computes the text hash, records the reviewer and date, and moves the
file into the library. The commit that adds the file is the audit trail. The tool never writes law itself.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.jurisdictions import REGISTRY, is_live  # noqa: E402
from lib.library import DEFAULT_DIR, sha256_text, validate_entry  # noqa: E402


def find(entry_id: str) -> Path | None:
    for f in (DEFAULT_DIR / "pending").glob("*.json"):
        if not f.name.startswith("_") and json.loads(f.read_text(encoding="utf-8")).get("id") == entry_id:
            return f
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("approve")
    a.add_argument("--id", required=True)
    a.add_argument("--reviewer", required=True)
    a.add_argument("--on", required=True, help="review date YYYY-MM-DD")
    a.add_argument("--version", default=None)
    r = sub.add_parser("reject")
    r.add_argument("--id", required=True)
    args = p.parse_args()

    if args.cmd == "list":
        for f in sorted((DEFAULT_DIR / "pending").glob("*.json")):
            if not f.name.startswith("_"):
                e = json.loads(f.read_text(encoding="utf-8"))
                print(f"{e.get('id')}\t{e.get('citation')}\tUNVERIFIED - pending lawyer review")
        return 0
    path = find(args.id)
    if not path:
        print("No pending entry with that id.")
        return 1
    if args.cmd == "reject":
        path.unlink()
        print(f"Removed {path.name}. Commit the deletion.")
        return 0
    e = json.loads(path.read_text(encoding="utf-8"))
    juris = e.get("jurisdiction", "IN")
    if juris not in REGISTRY or not is_live(juris):
        print(f"Jurisdiction {juris} is not live yet (lib/jurisdictions.py): it cannot be approved.")
        return 1
    entry = {k: e[k] for k in ("id", "citation", "kind", "text", "source_name", "source_url") if k in e}
    entry.update(jurisdiction=juris, aliases=e.get("aliases", []), title=e.get("title", ""), version=args.version or e.get("version", ""),
                 text_sha256=sha256_text(str(e.get("text", "")).strip()), verified_by=args.reviewer, verified_on=args.on)
    entry["text"] = str(entry["text"]).strip()
    errs = validate_entry(entry)
    if errs:
        print("Not approved:", "; ".join(errs))
        return 1
    out = DEFAULT_DIR / juris
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{entry['id']}.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.unlink()
    print(f"Approved: {out / (entry['id'] + '.json')}. Commit it (the commit is the audit trail), then restart the server.")
    return 0


if __name__ == "__main__":
    sys.exit(main())