"""Score a SAVED live evaluation again with the current rule, without asking any model anything (no AI call, no cost).

  python scripts/eval_rescore.py docs/evals/live-eval-2026-11-02-zai.json            prints before and after
  python scripts/eval_rescore.py docs/evals/live-eval-2026-11-02-zai.json --save     also writes docs/evals/rescored-<report>-<date>.json (never replacing an older file)

Why it exists: on 2026-11-02 a real model's answers were scored with a rule that counted EVERY verified claim as "wrongly verified" in cases whose point was "no law may be verified". A real
model quotes a document correctly and the code then rightly verifies it, so those answers failed for being right. evals/scoring.py now has a live mode that counts only claims of law and claims
that repeat an instruction from a document. This script applies that one changed check to the saved answers. Every other check keeps its saved result, because nothing else changed.
What it cannot do: it cannot show how a NEW answer would score, and it does not change what the product does."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from evals import scoring  # noqa: E402

CASES = {c["id"]: c for c in json.loads((BACKEND / "evals" / "legal_qa.json").read_text(encoding="utf-8"))["cases"]}


def rescore(report: dict) -> tuple[list[dict], list[dict]]:
    """(new results, the cases whose outcome changed). Only the 'nothing wrongly verified' check is recomputed."""
    out, changed = [], []
    for r in report["results"]:
        exp = CASES[r["id"]]["expect"]
        checks = [dict(c) for c in r["checks"]]
        if "verified_max" in exp:
            counted = [c for c in r["claims"] if c.get("status") == "VERIFIED" and scoring.must_not_be_verified({"claim_kind": c.get("kind"), "text": c.get("text")})]
            for c in checks:
                if c["check"] == "nothing wrongly verified":
                    c["ok"] = len(counted) <= exp["verified_max"]
                    c["why"] = "" if c["ok"] else f"expected at most {exp['verified_max']} verified claims, got {len(counted)} (live mode: only claims of law and claims that repeat an instruction are counted)"
        ok = sum(1 for c in checks if c["ok"])
        new = {**r, "checks": checks, "passed": ok == len(checks), "score": round(100 * ok / len(checks))}
        out.append(new)
        if new["passed"] != r["passed"] or new["score"] != r["score"]:
            changed.append({"id": r["id"], "category": r["category"], "before": {"passed": r["passed"], "score": r["score"]}, "after": {"passed": new["passed"], "score": new["score"]}})
    return out, changed


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("report")
    p.add_argument("--save", action="store_true")
    a = p.parse_args()
    path = Path(a.report)
    report = json.loads(path.read_text(encoding="utf-8"))
    after, changed = rescore(report)
    before_s, after_s = report["summary"], scoring.summarise(after)
    print(f"{path.name} ({report.get('label')}), {before_s['cases']} cases")
    print(f"  BEFORE: passed {before_s['passed']}/{before_s['cases']}, score {before_s['score']}")
    print(f"  AFTER : passed {after_s['passed']}/{after_s['cases']}, score {after_s['score']}")
    print("  by category (before -> after):")
    for cat in sorted(set(before_s["by_category"]) | set(after_s["by_category"])):
        print(f"    {cat:24} {before_s['by_category'].get(cat, '-'):>4} -> {after_s['by_category'].get(cat, '-'):>4}")
    still = [r for r in after if not r["passed"]]
    print(f"  STILL FAILING ({len(still)}): " + ", ".join(r["id"] for r in still))
    worse = [c for c in changed if c["before"]["passed"] and not c["after"]["passed"]]
    print(f"  cases that got worse: {len(worse)}")
    if a.save:
        out_dir = REPO / "docs" / "evals"
        stem = f"rescored-{path.stem}-{datetime.now(timezone.utc):%Y-%m-%d}"
        n = 1
        while True:
            target = out_dir / (stem + ("" if n == 1 else f"-{n}") + ".json")
            try:
                with open(target, "x", encoding="utf-8") as f:  # "x": an existing file is never replaced
                    json.dump({"source": path.name, "rule": "evals/scoring.py live mode", "before": before_s, "after": after_s, "changed": changed, "still_failing": [r["id"] for r in still], "results": after}, f, ensure_ascii=False, indent=1)
                print(f"  saved: {target}")
                break
            except FileExistsError:
                n += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
