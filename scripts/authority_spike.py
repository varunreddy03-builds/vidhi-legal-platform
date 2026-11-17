"""The lookup spike: runs the real citation lookup on a list of real citations and reports how many were found, wrongly missed, ambiguous or could not be checked.

    python scripts/authority_spike.py citations.csv --sc-dir C:/vidhi-tools/data/sc    # the local Supreme Court open dataset: free, offline, no key

citations.csv has one citation per line, optionally with the truth you know:   <citation as a lawyer would write it>,<yes|no>   (commas inside the citation are fine)
  yes = the case really exists and the citation is right      no = the citation is wrong or invented      (blank = unknown)
Example line:   Alpha Traders v. Beta Stores (2020) 7 SCC 1,yes

Judgment text is read in memory for comparison and discarded; the report keeps only the citation, label, reason, source URL, queries and times."""

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from lib.refcheck import lookup  # noqa: E402
from lib.refcheck.citations import extract_page  # noqa: E402
from lib.refcheck.sources import cost_per_lookup_inr  # noqa: E402


def read_rows(path: Path) -> list[tuple[str, str]]:
    """One citation per line; a trailing `,yes` / `|no` (or a tab) states the truth if known. Commas inside the citation are fine."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(.*?)[\s]*[,|	][\s]*(yes|no)\s*$", line, re.I)
        rows.append((m.group(1).strip(), m.group(2).lower()) if m else (line, ""))
    return rows


async def run(rows, dry: bool, sc_dir: str | None = None) -> dict:
    cap = int(os.environ.get("AUTHORITY_DAILY_LOOKUP_CAP", "300"))
    used = 0

    async def reserve(n):
        nonlocal used
        if used + n > cap:
            raise lookup.LookupCapExceeded()
        used += n

    from lib.refcheck.scsource import SupremeCourtData

    src = SupremeCourtData(sc_dir)
    out = []
    for text, truth in rows:
        refs = [r for r in extract_page(text, 1) if r.kind == "case"]
        if len(refs) != 1:
            out.append({"citation": text, "truth": truth, "label": "NOT_READ", "reason": f"the reader found {len(refs)} case citations in this line", "reporter": ""})
            continue
        ref = refs[0]
        if dry:
            out.append({"citation": text, "truth": truth, "label": "PLANNED", "reporter": ref.reporter, "searches": [{"strategy": s, "query": q} for s, q in lookup.plan(ref)], "read_as": {"parties": list(ref.parties), "year": ref.year, "court": ref.court, "neutral": ref.neutral, "report": ref.report}})
            continue
        res = await lookup.check_case(ref, src, reserve=reserve)
        out.append({"citation": text, "truth": truth, "reporter": ref.reporter, "label": res.label, "reason": res.reason, "differences": res.differences, "source_url": res.source_url,
                    "attempts": [{"strategy": a.strategy, "query": a.query, "status": a.status, "n": a.n, "error": a.error, "at": a.at} for a in res.attempts], "cost_inr": res.cost_inr})
    return {"rows": out, "lookups_used": used, "estimated_cost_inr": round(used * cost_per_lookup_inr(), 2)}


def summarise(rows: list[dict]) -> dict:
    s = Counter()
    by_rep: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        lab, truth = r["label"], r["truth"]
        rep = r.get("reporter") or "unread"
        if truth == "yes":
            kind = "found_correctly" if lab == "FOUND_MATCHES" else "wrongly_missed_as_not_found" if lab == "NOT_FOUND_FULL_SEARCH" else "wrongly_flagged_as_differing" if lab == "DETAILS_DIFFER" else "existing_but_could_not_check"
        elif truth == "no":
            kind = "wrong_citation_caught" if lab in ("DETAILS_DIFFER", "NOT_FOUND_FULL_SEARCH") else "wrong_citation_passed_as_found" if lab == "FOUND_MATCHES" else "wrong_citation_could_not_check"
        else:
            kind = "unknown_truth_" + lab.lower()
        s[kind] += 1
        by_rep[rep][kind] += 1
    return {"total": len(rows), "counts": dict(s), "by_reporter": {k: dict(v) for k, v in by_rep.items()}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--sc-dir", required=True, help="folder holding the local Supreme Court open dataset (free, offline, no key)")
    a = ap.parse_args()
    rows = read_rows(Path(a.file))
    result = asyncio.run(run(rows, False, a.sc_dir))
    result["summary"] = summarise(result["rows"])
    result["source"] = "supreme-court-open-data (local)"
    out = ROOT / "docs" / "evals" / f"authority-spike-sc-{Path(a.file).stem}-{date.today().isoformat()}.json"  # one report per input file
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    for r in result["rows"]:
        print(f"{r['label']:<24} {r.get('truth') or '-':<4} {r['citation'][:70]}")
    print(json.dumps(result["summary"], indent=1))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
