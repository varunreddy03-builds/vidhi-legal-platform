"""A basic load test for a running VIDHI server. It measures; it does not decide what is acceptable.

  python scripts/loadtest.py https://staging.example.com --users 20 --seconds 30
  python scripts/loadtest.py http://localhost:8001 --email you@example.com --password '...'   (adds signed-in pages)

Run it against a staging copy, never against production at peak, and never with AI endpoints: those cost real money and the
spending cap would (correctly) stop them. Only cheap read-only pages are hit. Results: requests, failures, and p50/p95/p99 latency.
Rate limits are part of the product, so a few 429 answers under heavy load are expected and are counted separately from failures."""

import argparse
import asyncio
import statistics
import time

import httpx

PUBLIC = ["/api/health", "/api/health/ready", "/api/auth/options", "/api/public/legal-config"]
SIGNED_IN = ["/api/auth/me", "/api/matters", "/api/recovery/cases"]


async def worker(client: httpx.AsyncClient, paths: list[str], stop_at: float, out: list):
    i = 0
    while time.perf_counter() < stop_at:
        path = paths[i % len(paths)]
        i += 1
        started = time.perf_counter()
        try:
            r = await client.get(path)
            out.append((path, r.status_code, (time.perf_counter() - started) * 1000))
        except httpx.HTTPError:
            out.append((path, 0, (time.perf_counter() - started) * 1000))


def pct(values: list[float], p: float) -> float:
    return values[min(len(values) - 1, int(len(values) * p))] if values else 0.0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--users", type=int, default=10)
    ap.add_argument("--seconds", type=int, default=20)
    ap.add_argument("--email")
    ap.add_argument("--password")
    a = ap.parse_args()
    paths = list(PUBLIC)
    results: list = []
    async with httpx.AsyncClient(base_url=a.base_url.rstrip("/"), timeout=30) as probe:
        cookies = None
        if a.email and a.password:
            r = await probe.post("/api/auth/login", json={"email": a.email, "password": a.password})
            if r.status_code != 200:
                print(f"sign-in failed ({r.status_code}); testing public pages only")
            else:
                cookies, paths = dict(probe.cookies), paths + SIGNED_IN
        stop_at = time.perf_counter() + a.seconds
        clients = [httpx.AsyncClient(base_url=a.base_url.rstrip("/"), timeout=30, cookies=cookies) for _ in range(a.users)]
        try:
            await asyncio.gather(*(worker(c, paths, stop_at, results) for c in clients))
        finally:
            await asyncio.gather(*(c.aclose() for c in clients))
    ok = sorted(ms for _, code, ms in results if 200 <= code < 400)
    limited = sum(1 for _, code, _ in results if code == 429)
    failed = [(p, c) for p, c, _ in results if c == 0 or c >= 500]
    print(f"{len(results)} requests in {a.seconds}s from {a.users} users = {len(results) / a.seconds:.1f}/s")
    print(f"ok {len(ok)}   rate-limited (429) {limited}   failed (5xx or no answer) {len(failed)}")
    if ok:
        print(f"latency ms: p50 {pct(ok, .5):.0f}  p95 {pct(ok, .95):.0f}  p99 {pct(ok, .99):.0f}  mean {statistics.mean(ok):.0f}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
