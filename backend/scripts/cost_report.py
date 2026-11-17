"""What the AI actually cost, from the spend ledger (real calls only). Run against any database that has seen real traffic:

  cd backend && MONGO_URL=... DB_NAME=... python scripts/cost_report.py [YYYY-MM]

The ledger stores provider, task, token counts and cost in rupees, never prompts or answers. `estimated` rows are ones where the provider reported no token counts
and the cap used a cautious estimate instead. Prices come from the price table (AI_PRICES_JSON or the placeholder defaults), so the rupee figures are only as true
as that table: compare with your provider invoices. With no real traffic this prints nothing but zeros, and that is the honest answer."""

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

IST = timezone(timedelta(hours=5, minutes=30))


def main() -> int:
    month = sys.argv[1] if len(sys.argv) > 1 else datetime.now(IST).strftime("%Y-%m")
    db = MongoClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))[os.environ.get("DB_NAME", "vidhi")]
    rows = list(db.ai_ledger.find({"month": month}))
    if not rows:
        print(f"{month}: no AI calls recorded in this database (nothing has been measured).")
        return 0
    by_task: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_task[r.get("task", "?")].append(r)
    total = sum(r["cost_inr"] for r in rows)
    print(f"{month}: {len(rows)} calls, Rs {total:,.2f} in total ({sum(1 for r in rows if r.get('estimated'))} with estimated, not reported, token counts)")
    print(f"{'task':22} {'provider(s)':22} {'calls':>6} {'Rs total':>10} {'Rs/call':>9} {'avg tokens in/out':>18}")
    for task, rs in sorted(by_task.items(), key=lambda kv: -sum(x["cost_inr"] for x in kv[1])):
        t_in = [x["tokens_in"] for x in rs if x.get("tokens_in") is not None]
        t_out = [x["tokens_out"] for x in rs if x.get("tokens_out") is not None]
        providers = ",".join(sorted({x["provider"] for x in rs}))
        cost = sum(x["cost_inr"] for x in rs)
        print(f"{task:22} {providers:22} {len(rs):6} {cost:10.2f} {cost / len(rs):9.3f} {(sum(t_in) // max(len(t_in), 1)):>8}/{(sum(t_out) // max(len(t_out), 1)):<9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())