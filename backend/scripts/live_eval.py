"""Score a REAL model on the legal Q&A set (evals/legal_qa.json) with the account switched to Pro, so the request can reach a Claude model.

  python scripts/live_eval.py --base-url http://127.0.0.1:8011 --mongo-url mongodb://127.0.0.1:27017 --db vidhi_live_eval --label sonnet [--only ID] [--out report.json]

Run it against a THROWAWAY database and a test server started with AI_STUB unset and ANTHROPIC_API_KEY in the environment (never in a file). Like eval_answers.py it signs up
its own account, but it then marks that account Pro in the throwaway database, because the free plan never reaches a Claude model. It makes real calls that cost money."""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals import scoring  # noqa: E402

DATA = json.loads((Path(__file__).resolve().parent.parent / "evals" / "legal_qa.json").read_text(encoding="utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", default="http://127.0.0.1:8011")
    p.add_argument("--mongo-url", default="mongodb://127.0.0.1:27017")
    p.add_argument("--db", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--only")
    p.add_argument("--out")
    p.add_argument("--per-category", type=int, default=0, help="run only this many cases from each category, spread evenly (0 = every case, which is over a thousand and costly)")
    p.add_argument("--cap-inr", type=float, default=100.0, help="stop before the estimated spend passes this many rupees")
    p.add_argument("--pause", type=float, default=4.0, help="seconds to wait between cases (a free model provider limits how many words it takes a minute)")
    p.add_argument("--yes-spend", action="store_true", help="without this the script only prints how many calls it would make and what they would cost")
    a = p.parse_args()

    chosen = [x for x in DATA["cases"] if not x["needs_fixture_library"] and (not a.only or x["id"].startswith(a.only))]
    if a.per_category:
        by_cat: dict[str, list] = {}
        for x in chosen:
            by_cat.setdefault(x["category"], []).append(x)
        chosen = []
        for cat in sorted(by_cat):
            rows = sorted(by_cat[cat], key=lambda x: x["id"])
            step = max(1, len(rows) / a.per_category)
            chosen += [rows[int(i * step)] for i in range(min(a.per_category, len(rows)))]
    from lib import aibudget  # noqa: E402

    est_in, est_out = 3000, 1000  # a cautious guess per answer: the matter text, the instructions and the passages in; the JSON answer out
    per_call = {m: aibudget.cost_inr("anthropic", est_in, est_out, m) for m in ("claude-haiku-4-5", "claude-sonnet-5-5")}
    non_en = sum(1 for x in chosen if x["language"] != "en")
    calls = len(chosen) + non_en  # a question in another language also needs one small call that turns it into an English search query
    print(f"PLAN: {len(chosen)} cases, about {calls} model calls; estimated {calls * per_call['claude-haiku-4-5']:.0f} rupees on Claude Haiku 4.5, "
          f"{calls * per_call['claude-sonnet-5-5']:.0f} on Sonnet 5.5 (prices read from the providers' pages on 2026-10-31; the rupee rate is {aibudget.usd_inr():g}); cap {a.cap_inr:g}")
    if not a.yes_spend:
        print("Nothing was run. Add --yes-spend to make these real, paid calls.")
        return 0
    if max(calls * v for v in per_call.values()) > a.cap_inr:
        print("The worst-case estimate is above the cap; lower --per-category or raise --cap-inr on purpose.")
        return 2

    c = httpx.Client(base_url=a.base_url.rstrip("/") + "/api", timeout=300.0)
    tag = uuid.uuid4().hex[:10]
    email = f"live-{tag}@example.com"
    r = c.post("/auth/signup", json={"email": email, "password": f"Pw-{uuid.uuid4().hex}", "full_name": "Live Eval", "organization_name": f"Live {tag}", "accept_privacy": True, "elapsed_ms": 5000})
    if r.status_code != 200:
        print("Could not create the throwaway account:", r.status_code, r.text[:200])
        return 2
    MongoClient(a.mongo_url)[a.db].users.update_one({"email": email}, {"$set": {"plan": "PRO"}})
    results = []
    for n, case in enumerate(chosen, start=1):
        time.sleep(a.pause if n > 1 else 0)
        # the matter title must not carry the case id: its words ("cheque-notice-time") would count as recorded text and contradict an absence claim
        mid = c.post("/matters", json={"title": f"Eval matter {n} {tag}", "parties": "", "description": ""}).json()["id"]
        for i, d in enumerate(case["documents"], start=1):
            c.post(f"/matters/{mid}/documents", files={"file": (f"doc{i}.txt", DATA["documents"][d].encode())})
        t0 = time.time()
        resp = c.post("/research", json={"question": case["question"], "matter_id": mid, "mode": "MATTER", "language": case["language"]})
        if resp.status_code in (429, 502):  # a rate limit somewhere: wait and try once more, and say so in the report
            time.sleep(25)
            resp = c.post("/research", json={"question": case["question"], "matter_id": mid, "mode": "MATTER", "language": case["language"]})
        secs = round(time.time() - t0, 1)
        if resp.status_code != 200:
            res = {"id": case["id"], "category": case["category"], "passed": False, "score": 0, "checks": [{"check": "answered", "ok": False, "why": f"HTTP {resp.status_code}: {resp.text[:160]}"}]}
        else:
            res = scoring.score_case(case, resp.json(), live=True)  # a real model: see evals/scoring.py
            res["answer_excerpt"] = (resp.json().get("answer") or "")[:300]
            res["claims"] = [{"kind": x.get("claim_kind"), "status": x.get("verification_status"), "text": (x.get("text") or "")[:140]} for x in resp.json().get("claims", [])]
        res["seconds"] = secs
        results.append(res)
        print(f"{'PASS' if res['passed'] else 'FAIL'} {res['score']:>3} {secs:>5}s  {case['id']}" + ("" if res["passed"] else "  <- " + "; ".join(x["why"] for x in res["checks"] if not x["ok"])[:220]))
    summary = scoring.summarise(results)
    # The case scores mix two different things, so say them apart: how many cases got an answer at all, and whether any ANSWER broke a rule that holds for every
    # answer (disclaimer, neutral wording, a verified claim without a checked quote, law verified without the library). Some cases' own `expect` blocks were written
    # for the scripted wrong replies used in CI (for example "nothing may be verified" on an invented-quote case), so a good live answer can fail them.
    universal = {"disclaimer", "neutral wording", "verified claims have checked evidence", "law is verified only from the library"}
    answered = [r for r in results if not any(x["check"] == "answered" and not x["ok"] for x in r["checks"])]
    broke = [r["id"] for r in answered if any(x["check"] in universal and not x["ok"] for x in r["checks"])]
    summary["answered"] = f"{len(answered)} of {len(results)}"
    summary["universal_rules_broken_in"] = broke
    print("\nSUMMARY", a.label, json.dumps(summary, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps({"label": a.label, "summary": summary, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
