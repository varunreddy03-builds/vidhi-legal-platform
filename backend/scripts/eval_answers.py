"""Score a REAL model on the 35-case legal Q&A set (evals/legal_qa.json) against a running VIDHI server.

  python scripts/eval_answers.py --base-url http://localhost:8001 [--fixture-library] [--min-score 80] [--out report.json]

It signs up a throwaway account on that server, creates one matter per case, uploads the case's documents, asks the question, scores the answer
with evals/scoring.py and prints a table. Cases about the fictional fixture library only run with --fixture-library (when the server was started
with LIBRARY_DIR pointing at backend/tests/fixtures/legal_library). Use a TEST server: it makes real model calls (they cost money and count towards
the monthly AI cap). Exit code 1 if the average is below --min-score."""

import argparse
import json
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals import scoring  # noqa: E402

DATA = json.loads((Path(__file__).resolve().parent.parent / "evals" / "legal_qa.json").read_text(encoding="utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", default="http://localhost:8001")
    p.add_argument("--fixture-library", action="store_true")
    p.add_argument("--min-score", type=int, default=80)
    p.add_argument("--only", help="run only cases whose id starts with this")
    p.add_argument("--out")
    a = p.parse_args()

    c = httpx.Client(base_url=a.base_url.rstrip("/") + "/api", timeout=240.0)
    tag = uuid.uuid4().hex[:10]
    r = c.post("/auth/signup", json={"email": f"eval-{tag}@example.com", "password": f"Pw-{uuid.uuid4().hex}", "full_name": "Eval Run", "organization_name": f"Eval {tag}", "accept_privacy": True})
    if r.status_code != 200:
        print("Could not create the throwaway account:", r.status_code, r.text[:200])
        return 2
    results = []
    for case in DATA["cases"]:
        if a.only and not case["id"].startswith(a.only):
            continue
        if case["needs_fixture_library"] and not a.fixture_library:
            continue
        mid = c.post("/matters", json={"title": f"Eval {case['id']} {tag}", "parties": "", "description": ""}).json()["id"]
        for i, d in enumerate(case["documents"], start=1):
            c.post(f"/matters/{mid}/documents", files={"file": (f"doc{i}.txt", DATA["documents"][d].encode())})
        resp = c.post("/research", json={"question": case["question"], "matter_id": mid, "mode": "MATTER", "language": case["language"]})
        if resp.status_code != 200:
            res = {"id": case["id"], "category": case["category"], "passed": False, "score": 0, "checks": [{"check": "answered", "ok": False, "why": f"HTTP {resp.status_code}: {resp.text[:120]}"}]}
        else:
            res = scoring.score_case(case, resp.json(), live=True)  # a real model: see evals/scoring.py
        results.append(res)
        print(f"{'PASS' if res['passed'] else 'FAIL'} {res['score']:>3}  {case['id']}" + ("" if res["passed"] else "  <- " + "; ".join(x["why"] for x in res["checks"] if not x["ok"])[:200]))
    summary = scoring.summarise(results)
    print("\nSUMMARY", json.dumps(summary, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if summary["score"] >= a.min_score else 1


if __name__ == "__main__":
    sys.exit(main())