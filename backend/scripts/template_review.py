"""A lawyer approves a template after reading it. Moves backend/data/templates/pending/<id>.json to <COUNTRY>/<id>.json with the reviewer's name, date
and a hash of exactly what was reviewed. Editing the wording afterwards changes the hash, and the template silently goes back to "not reviewed".

  python scripts/template_review.py status
  python scripts/template_review.py approve --id in-nda --reviewer "Full Name" --on 2026-11-20
Approving does NOT make the template legal advice for anyone's facts; it records that a named lawyer read this wording."""

import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import templates  # noqa: E402
from lib.jurisdictions import is_live  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    a = sub.add_parser("approve")
    a.add_argument("--id", required=True)
    a.add_argument("--reviewer", required=True)
    a.add_argument("--on", required=True, help="review date, YYYY-MM-DD")
    args = ap.parse_args()
    root = templates.templates_dir()
    if args.cmd == "status":
        for t in templates.load_all():
            print(f"{t['id']:40} {t['jurisdiction']}  {t['review']['status']}" + (f"  ({t['review']['reviewed_by']}, {t['review']['reviewed_on']})" if t["review"]["reviewed"] else ""))
        return 0
    path = root / "pending" / f"{args.id}.json"
    if not path.is_file():
        print(f"no pending template {args.id}", file=sys.stderr)
        return 1
    if len(args.reviewer.strip()) < 5:
        print("give the reviewer's full name", file=sys.stderr)
        return 1
    try:
        date.fromisoformat(args.on)
    except ValueError:
        print("--on must be a date like 2026-11-20", file=sys.stderr)
        return 1
    t = json.loads(path.read_text(encoding="utf-8"))
    if not is_live(t["jurisdiction"]):
        print(f"{t['jurisdiction']} is not a supported country yet (lib/jurisdictions.py)", file=sys.stderr)
        return 1
    if templates._problems(t):
        print("template is not valid:", templates._problems(t), file=sys.stderr)
        return 1
    t.update({"reviewed_by": args.reviewer.strip(), "reviewed_on": args.on, "content_sha256": templates.content_hash(t)})
    dest = root / t["jurisdiction"] / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(t, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    path.unlink()
    print(f"approved {t['id']} -> {dest}  (restart the server)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())