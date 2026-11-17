"""Regression gate for the evaluation results: compares a result file with the floors in baseline.json.

    python -m evals.gate [docs/evals/knowledge-eval-<date>.json]     # default: the newest one

Exit code 1 when any metric is worse than its floor OR missing (a metric that was not measured can never pass). It reads results; it never runs a model."""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVALS = HERE.parent.parent / "docs" / "evals"


def latest() -> Path:
    return sorted(EVALS.glob("knowledge-eval-*.json"))[-1]


def check(results: dict, baseline: dict) -> list[str]:
    problems = []
    for kind, rules in (("min", baseline.get("min", {})), ("max", baseline.get("max", {}))):
        for path, bound in rules.items():
            section, field = path.split(".", 1)
            val = (results.get(section) or {}).get(field)
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                problems.append(f"{path}: not measured (needs a number)")
            elif kind == "min" and val < bound:
                problems.append(f"{path}: {val} is below the floor {bound}")
            elif kind == "max" and val > bound:
                problems.append(f"{path}: {val} is above the ceiling {bound}")
    return problems


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else latest()
    problems = check(json.loads(path.read_text(encoding="utf-8"))["results"], json.loads((HERE / "baseline.json").read_text(encoding="utf-8")))
    print(f"{path.name}: " + ("PASS (all floors held)" if not problems else "FAIL"))
    for p in problems:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
