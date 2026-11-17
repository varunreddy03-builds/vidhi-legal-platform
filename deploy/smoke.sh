#!/usr/bin/env bash
# Checks a running VIDHI stack from the outside.   bash deploy/smoke.sh http://127.0.0.1:8080        or        bash deploy/smoke.sh https://app.example.in
# It reads, never writes: no account is created and nothing is stored. Exit code 0 only when every check passes.
set -uo pipefail

BASE="${1:?usage: smoke.sh <base address, no trailing slash>}"
fail=0
ok()   { echo "  ok   $1"; }
bad()  { echo "  FAIL $1" >&2; fail=1; }
check() { local what="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$what"; else bad "$what"; fi; }

echo "Waiting for the site (up to 3 minutes)..."
for _ in $(seq 1 90); do
  if curl -fsS "$BASE/api/health" >/dev/null 2>&1; then break; fi
  sleep 2
done

check "the app page loads"                          curl -fsS "$BASE/"
check "the API answers /api/health"                 bash -c "curl -fsS '$BASE/api/health' | grep -q '\"ok\"'"
check "the database answers /api/health/ready"      bash -c "curl -fsS '$BASE/api/health/ready' | grep -Eq '\"status\": ?\"(ok|degraded)\"'"
check "security headers are sent with the app"      bash -c "curl -fsSI '$BASE/' | tr -d '\r' | grep -qi '^x-content-type-options: nosniff' && curl -fsSI '$BASE/' | tr -d '\r' | grep -qi '^content-security-policy:'"
check "interactive API pages are off (/api/docs)"   bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' '$BASE/api/docs')\" != 200 ]"
check "the API schema is not published"             bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' '$BASE/api/openapi.json')\" != 200 ]"
check "a private page needs a sign-in"              bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' '$BASE/api/matters')\" = 401 ]"
check "the service worker is served"                curl -fsS "$BASE/sw.js"
check "no API response is cacheable (/api/auth/options)" bash -c "curl -fsSI '$BASE/api/auth/options' | tr -d '\r' | grep -qi '^cache-control: .*no-store'"

if [ "$fail" -eq 0 ]; then echo "All checks passed."; else echo "Some checks FAILED." >&2; fi
exit "$fail"
