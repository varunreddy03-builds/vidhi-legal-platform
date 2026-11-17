"""Compare two live-eval runs (before / after a routing change): quality and rupees per answer. Makes NO AI call and sends nothing anywhere.

  python scripts/route_compare.py --before docs/evals/A.json --after docs/evals/B.json [--before-db vidhi_eval_a --after-db vidhi_eval_b] [--mongo-url mongodb://127.0.0.1:27017]

Quality comes from the two reports written by scripts/live_eval.py (the same cases, scored by evals/scoring.py). Cost comes from the spend ledger (`ai_ledger`) of the throwaway
database each run used: its rows hold provider, task, tokens and rupees, never prompts or answers. Without a database name the cost is reported as "not measured".

The verdict is only a recommendation about DEFAULTS: change the defaults only when quality is equal or better (no case that passed before fails now, no more broken universal rules,
mean score not lower). Cheaper but worse is "KEEP THE OLD DEFAULT". Different case sets are refused, because the numbers would not be comparable."""

import argparse
import json
import sys
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def quality(report: dict) -> dict:
    res = report["results"]
    scores = [r.get("score", 0) for r in res]
    universal = report.get("summary", {}).get("universal_rules_broken_in", [])
    answered = report.get("summary", {}).get("answered", "")
    return {"cases": len(res), "passed": sum(1 for r in res if r.get("passed")), "mean_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
            "broke_universal_rules": sorted(universal), "answered": answered, "by_id": {r["id"]: bool(r.get("passed")) for r in res}}


def cost_by_task(db_name: str, mongo_url: str) -> dict:
    from pymongo import MongoClient
    rows = list(MongoClient(mongo_url, serverSelectionTimeoutMS=3000)[db_name].ai_ledger.find({"ok": {"$ne": False}}))
    by: dict[str, dict] = {}
    for r in rows:
        t = by.setdefault(r.get("task", "?"), {"calls": 0, "rs": 0.0, "providers": set()})
        t["calls"] += 1
        t["rs"] += float(r.get("cost_inr", 0))
        t["providers"].add(r.get("provider", "?"))
    return {"total_rs": round(sum(t["rs"] for t in by.values()), 4), "calls": len(rows),
            "tasks": {k: {"calls": v["calls"], "rs": round(v["rs"], 4), "providers": sorted(v["providers"])} for k, v in by.items()}}


def verdict(b: dict, a: dict) -> tuple[str, list[str]]:
    why = []
    regressed = sorted(i for i, ok in b["by_id"].items() if ok and not a["by_id"].get(i, False))
    if regressed:
        why.append(f"{len(regressed)} case(s) passed before and fail now: {', '.join(regressed[:8])}")
    new_broken = sorted(set(a["broke_universal_rules"]) - set(b["broke_universal_rules"]))
    if new_broken:
        why.append(f"universal rules broken in new cases: {', '.join(new_broken[:8])}")
    if a["mean_score"] < b["mean_score"]:
        why.append(f"mean score fell {b['mean_score']} -> {a['mean_score']}")
    if why:
        return "KEEP THE OLD DEFAULT (quality is worse)", why
    return "QUALITY EQUAL OR BETTER (a default change may be considered; check cost and have an advocate read a sample)", ["no regressions found on these cases"]


def render(b: dict, a: dict, cb: dict | None, ca: dict | None) -> str:
    out = ["BEFORE vs AFTER", f"cases: {b['cases']} vs {a['cases']}",
           f"passed: {b['passed']} vs {a['passed']}", f"mean score: {b['mean_score']} vs {a['mean_score']}",
           f"answered: {b['answered']} vs {a['answered']}"]
    for label, c, q in (("before", cb, b), ("after", ca, a)):
        if c is None:
            out.append(f"cost {label}: not measured (no database given)")
            continue
        n = max(q["cases"], 1)
        out.append(f"cost {label}: Rs {c['total_rs']} over {c['calls']} calls = Rs {round(c['total_rs'] / n, 3)} per case")
        for t, v in sorted(c["tasks"].items()):
            out.append(f"   {t:18} {v['calls']:4} calls  Rs {v['rs']:8.3f}  {','.join(v['providers'])}")
    v, why = verdict(b, a)
    out += ["", "VERDICT: " + v] + ["  - " + w for w in why]
    out.append("Quality here is the scorer's checks, not a lawyer's opinion. Whether an answer is right in law is for an advocate to confirm.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    p.add_argument("--before-db")
    p.add_argument("--after-db")
    p.add_argument("--mongo-url", default="mongodb://127.0.0.1:27017")
    a = p.parse_args(argv)
    rb, ra = load(a.before), load(a.after)
    b, af = quality(rb), quality(ra)
    if set(b["by_id"]) != set(af["by_id"]):
        print("These two reports are not about the same cases, so they cannot be compared.", file=sys.stderr)
        return 2
    try:
        cb = cost_by_task(a.before_db, a.mongo_url) if a.before_db else None
        ca = cost_by_task(a.after_db, a.mongo_url) if a.after_db else None
    except Exception as exc:  # noqa: BLE001
        print(f"Could not read the ledger ({type(exc).__name__}). Is MongoDB running?", file=sys.stderr)
        return 2
    print(render(b, af, cb, ca))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
