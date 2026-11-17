"""Time every GET route that needs no id, on a throwaway database with realistic amounts of data. Makes no AI call (use a backend started with AI_STUB=true) and sends nothing outside.

  cd backend && python scripts/api_timing.py --base http://127.0.0.1:8001 [--matters 40] [--repeat 12] [--label before]

It signs up a throwaway account in whatever backend --base points to (use a throwaway database such as vidhi_perf), fills it with --matters matters (each with facts, timeline events and a
pasted-text document), then calls each route --repeat times and reports the median, the slowest, and the size of the answer in bytes after compression. The list of routes comes from the
application itself. Writes ../docs/perf/api-<label>-<date>.json (never overwrites). The numbers are for this machine and an idle server: compare before and after, not against a promise."""
import argparse
import gzip
import json
import statistics
import sys
import time
import uuid
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SKIP = ("/api/auth/google", "/api/auth/logout", "/api/payments", "/api/admin", "/api/public", "/api/cron", "/api/webhooks", "/api/native", "/api/voice", "/api/export", "/api/org/export")


def routes() -> list[str]:
    from server import app  # the application's own list: nothing is guessed

    spec = app.openapi()
    out = []
    for path, ops in spec["paths"].items():
        get = ops.get("get")
        if not get or "{" in path or any(path.startswith(s) for s in SKIP):
            continue
        if any(p.get("required") for p in get.get("parameters", []) if p.get("in") == "query"):
            continue
        out.append(path if path.startswith("/api") else "/api" + path)
    return sorted(set(out))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--matters", type=int, default=40)
    ap.add_argument("--repeat", type=int, default=12)
    ap.add_argument("--label", default="run")
    a = ap.parse_args(argv)
    c = httpx.Client(base_url=a.base.rstrip("/"), timeout=60.0, headers={"Accept-Encoding": "gzip"})
    tag = uuid.uuid4().hex[:8]
    r = c.post("/api/auth/signup", json={"email": f"timing-{tag}@example.com", "password": f"Zq9-{uuid.uuid4().hex[:10]}-Xv7", "full_name": "Timing Lawyer", "organization_name": f"Timing {tag}",
                                         "accept_privacy": True, "elapsed_ms": 5000})
    if r.status_code != 200:
        print("Could not create the throwaway account:", r.status_code, r.text[:160])
        return 2
    first = None
    for n in range(a.matters):
        m = c.post("/api/matters", json={"title": f"Timing matter {n} {tag}", "parties": "A v B", "description": "A cheque of 5,00,000 rupees was returned on 01/06/2021. " * 6})
        if m.status_code not in (200, 201):
            print("matter create failed:", m.status_code, m.text[:120])
            return 2
        mid = m.json()["id"]
        first = first or mid
        for k in range(6):
            c.post(f"/api/matters/{mid}/facts", json={"value": f"Fact {k}: the notice was sent on {k + 1}/04/2021.", "fact_type": "NOTE"})
            c.post(f"/api/matters/{mid}/timeline", json={"event_date": "2021-05-0%d" % (k + 1), "description": f"Event {k} " + "x" * 120})
        c.post(f"/api/matters/{mid}/documents", files={"file": ("note.txt", ("The cheque was returned unpaid on 01/06/2021. " * 120).encode(), "text/plain")})
    print(f"seeded {a.matters} matters; timing routes")
    rows = []
    for path in routes():
        times, size, status = [], 0, None
        for _ in range(a.repeat):
            t0 = time.perf_counter()
            resp = c.get(path)
            times.append((time.perf_counter() - t0) * 1000)
            status, size = resp.status_code, len(resp.content)
        if status and status >= 500:
            print("  5xx on", path, status)
        raw = resp.content
        rows.append({"route": path, "status": status, "p50_ms": round(statistics.median(times), 1), "max_ms": round(max(times), 1), "bytes": size, "bytes_gzip": len(gzip.compress(raw, 5))})
    rows.sort(key=lambda r: -r["p50_ms"])
    print(f"{'route':48} {'status':>6} {'p50 ms':>8} {'max ms':>8} {'KB gz':>7}")
    for r in rows[:15]:
        print(f"{r['route']:48} {r['status']:>6} {r['p50_ms']:>8} {r['max_ms']:>8} {r['bytes_gzip'] / 1024:>7.1f}")
    big = sorted(rows, key=lambda r: -r["bytes_gzip"])[:5]
    print("largest answers:", ", ".join(f"{r['route']} {r['bytes_gzip'] / 1024:.0f} KB" for r in big))
    out = ROOT.parent / "docs" / "perf"
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"api-{a.label}-{date.today().isoformat()}.json"
    n = 2
    while f.exists():
        f = out / f"api-{a.label}-{date.today().isoformat()}-{n}.json"
        n += 1
    f.write_text(json.dumps({"label": a.label, "matters": a.matters, "repeat": a.repeat, "routes": rows}, indent=1), encoding="utf-8")
    print("saved", f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
