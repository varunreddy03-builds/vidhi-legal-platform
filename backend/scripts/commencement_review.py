"""A named person records that they compared a start date with the Gazette notification it comes from. The commit of the changed file is the audit trail (the same way as the law library).

    python scripts/commencement_review.py list
    python scripts/commencement_review.py approve --id so-848e-2024-02-23 --reviewer "Full Name" --on 2026-11-05
Computed dates (marked "computed": true, worked out from a stated interval) are approved by the same command: the reviewer is confirming the arithmetic too."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "data" / "legal_library" / "_commencement_notifications.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("approve")
    a.add_argument("--id", required=True)
    a.add_argument("--reviewer", required=True)
    a.add_argument("--on", required=True, help="review date YYYY-MM-DD")
    args = ap.parse_args()
    data = json.loads(FILE.read_text(encoding="utf-8"))
    rows = data["notifications"]
    if args.cmd == "list":
        for n in rows:
            print(f"{n['id']}\t{n['number']} ({n['notified_on']})\t{n['act_title']}\t{'reviewed by ' + n['reviewed_by'] + ' on ' + n['reviewed_on'] if n.get('reviewed_by') else 'UNVERIFIED - not reviewed'}")
        return 0
    if len(args.reviewer.strip()) < 5:
        print("Give the reviewer's full name.")
        return 1
    try:
        day = date.fromisoformat(args.on).isoformat()
    except ValueError:
        print("Give the date as YYYY-MM-DD.")
        return 1
    hit = [n for n in rows if n["id"] == args.id]
    if not hit:
        print("No notification with that id.")
        return 1
    hit[0].update(status="REVIEWED", reviewed_by=args.reviewer.strip(), reviewed_on=day)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded: {args.id} reviewed by {args.reviewer.strip()} on {day}. Commit the file, then run scripts/apply_commencement_notifications.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
