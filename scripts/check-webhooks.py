"""Checks that a running server's payment webhooks reject forged calls and accept genuinely signed ones.

  STRIPE_WEBHOOK_SECRET=... RAZORPAY_WEBHOOK_SECRET=... python scripts/check-webhooks.py https://staging.example.com

Use the TEST-MODE secrets of a staging server. It sends a harmless event of a type the server ignores, so no account changes. Secrets are
read from the environment and never printed. For an end-to-end check with the providers themselves, use their own tools as well:
  Stripe:   `stripe listen --forward-to <url>/api/webhook/stripe` then `stripe trigger invoice.paid`
  Razorpay: Dashboard > Webhooks > the test webhook button (test mode)
  PayPal:   Developer dashboard > Webhooks simulator (sandbox)   (PayPal verifies through its own service, so it cannot be signed locally)"""

import hashlib
import hmac
import json
import os
import sys
import time

import httpx

BODY = json.dumps({"id": "evt_vidhi_check", "type": "vidhi.check.ignored", "event": "vidhi.check.ignored", "data": {"object": {}}}).encode()


def stripe_headers(secret: str) -> dict:
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + BODY, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"}


def razorpay_headers(secret: str) -> dict:
    return {"X-Razorpay-Signature": hmac.new(secret.encode(), BODY, hashlib.sha256).hexdigest(), "Content-Type": "application/json"}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    base = sys.argv[1].rstrip("/")
    checks = [("stripe", "STRIPE_WEBHOOK_SECRET", stripe_headers, {"Stripe-Signature": "t=1,v1=forged"}),
              ("razorpay", "RAZORPAY_WEBHOOK_SECRET", razorpay_headers, {"X-Razorpay-Signature": "forged"})]
    bad = 0
    for name, env, signer, forged in checks:
        url = f"{base}/api/webhook/{name}"
        secret = os.environ.get(env)
        r = httpx.post(url, content=BODY, headers={**forged, "Content-Type": "application/json"}, timeout=30)
        ok = r.status_code == 400
        print(f"{name}: forged signature -> {r.status_code}  {'OK (rejected)' if ok else 'PROBLEM: a forged call was not rejected'}")
        bad += not ok
        if not secret:
            print(f"{name}: {env} not set here - skipped the genuinely-signed check")
            continue
        r = httpx.post(url, content=BODY, headers=signer(secret), timeout=30)
        ok = 200 <= r.status_code < 300
        print(f"{name}: correctly signed -> {r.status_code}  {'OK (accepted)' if ok else 'PROBLEM: check the secret on the server matches the provider'}")
        bad += not ok
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())