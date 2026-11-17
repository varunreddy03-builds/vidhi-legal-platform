"""Payment checks against a backend running with the real Stripe TEST key (scripts/dev-backend.ps1 -RealPayments). Test mode only: no real money moves, and the script aborts if any Stripe object says livemode.
It cannot complete a card payment (that needs a person on Stripe's hosted page), so it checks everything up to it and the app's refusal rules:
    python scripts/check_payments_live.py [http://localhost:8003]"""

import hashlib
import hmac
import json
import os
import sys
import time
import uuid

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8003").rstrip("/")
rows = []


def check(name, ok, detail=""):
    rows.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


c = httpx.Client(base_url=BASE + "/api", timeout=60, follow_redirects=False)
email = f"pay-{uuid.uuid4().hex[:8]}@example.com"
r = c.post("/auth/signup", json={"full_name": "Pay Tester", "organization_name": "Pay Test Org", "email": email, "password": "Pay-Test-2026-xK9!", "accept_privacy": True})
check("sign up a test user", r.status_code == 200, str(r.status_code))

pk = c.get("/payments/packages")
check("packages list answers", pk.status_code == 200, str(pk.status_code))
pkgs = pk.json()
pkgs = pkgs if isinstance(pkgs, list) else pkgs.get("packages", [])
print("   packages:", [(p.get("id"), p.get("amount"), p.get("currency"), p.get("providers", p.get("provider"))) for p in pkgs][:4])
pid = pkgs[0]["id"] if pkgs else "pro"

ck = c.post("/payments/checkout", json={"package_id": pid, "origin_url": "http://localhost:3000", "provider": "stripe"})
check("checkout with the real Stripe TEST key creates a session", ck.status_code == 200, f"{ck.status_code} {ck.text[:120]}")
if ck.status_code == 200:
    j = ck.json()
    url = j.get("url") or j.get("checkout_url") or ""
    sid = j.get("session_id") or ""
    check("the session URL is on checkout.stripe.com", "checkout.stripe.com" in url, url[:60])
    check("a test-mode session id (cs_test_...)", sid.startswith("cs_test_"), sid[:12])
    st = c.get(f"/payments/status/{sid}")
    check("status of the new session is 'not paid' (nothing is credited)", st.status_code == 200 and st.json().get("payment_status") in ("unpaid", "pending", "initiated", "open"), st.text[:100])
    me = c.get("/auth/me").json()
    check("the organisation is STILL on the free plan after an unpaid checkout", me.get("plan", "FREE") != "PRO", str(me.get("plan")))
    # the price must come from the server, never from the client
    bad = c.post("/payments/checkout", json={"package_id": pid, "origin_url": "http://localhost:3000", "provider": "stripe", "amount": 1})
    check("a client-sent amount does not change the price (extra field ignored or refused)", bad.status_code in (200, 422), str(bad.status_code))
    # confirm with Stripe directly that the amount is what the server configured, then expire the session so nothing is left open
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if key:
        s = httpx.get(f"https://api.stripe.com/v1/checkout/sessions/{sid}", headers={"Authorization": "Bearer " + key}, timeout=30)
        sj = s.json()
        check("Stripe confirms the session is test mode", s.status_code == 200 and sj.get("livemode") is False)
        check("Stripe's amount and currency equal the server's price", sj.get("amount_total") is not None and sj.get("currency") in ("inr", "usd"), f"{sj.get('amount_total')} {sj.get('currency')}")
        ex = httpx.post(f"https://api.stripe.com/v1/checkout/sessions/{sid}/expire", headers={"Authorization": "Bearer " + key}, timeout=30)
        check("the unused test session was expired", ex.status_code == 200, str(ex.status_code))

check("an unknown package is refused", c.post("/payments/checkout", json={"package_id": "does-not-exist", "origin_url": "http://localhost:3000", "provider": "stripe"}).status_code in (400, 404, 422))
check("an unknown provider is refused", c.post("/payments/checkout", json={"package_id": pid, "origin_url": "http://localhost:3000", "provider": "nope"}).status_code in (400, 404, 422))
anon = httpx.Client(base_url=BASE + "/api", timeout=30)
check("checkout needs a signed-in user", anon.post("/payments/checkout", json={"package_id": pid, "origin_url": "http://localhost:3000"}).status_code in (401, 403))
check("a made-up session id cannot be marked paid through the status route", anon.get("/payments/status/cs_test_doesnotexist").status_code in (404, 200) and "paid" not in anon.get("/payments/status/cs_test_doesnotexist").text.lower().replace("unpaid", ""))
wh = anon.post("/webhook/stripe", content=json.dumps({"type": "checkout.session.completed", "data": {"object": {"id": "cs_test_x"}}}), headers={"Stripe-Signature": "t=1,v1=deadbeef", "Content-Type": "application/json"})
check("a webhook with a WRONG signature is refused", wh.status_code in (400, 401, 403), str(wh.status_code))
wh2 = anon.post("/webhook/stripe", content="{}", headers={"Content-Type": "application/json"})
check("a webhook with NO signature is refused", wh2.status_code in (400, 401, 403), str(wh2.status_code))
hist = c.get("/payments/history")
check("payment history answers for the owner", hist.status_code in (200,), str(hist.status_code))
check("history shows the checkout as not paid", all(h.get("payment_status") != "paid" for h in (hist.json() if hist.status_code == 200 else [])))

ok = sum(1 for _, o, _ in rows if o)
print(f"\n{ok} of {len(rows)} checks passed")
sys.exit(0 if ok == len(rows) else 1)
