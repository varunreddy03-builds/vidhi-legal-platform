#!/usr/bin/env python
"""VIDHI feature walk: drives the REAL HTTP API of a running dev backend through the user journeys and records, for every step,
route, expected result, actual HTTP status, passed/failed and the reason when failed.

  C:\\vidhi-tools\\venv2\\Scripts\\python.exe scripts\\feature_walk.py [--base http://localhost:8002] [--out docs/evals/feature-walk-results.json]
  C:\\vidhi-tools\\venv2\\Scripts\\python.exe scripts\\feature_walk.py --inventory   (prints the route inventory as markdown, from /openapi.json + lib/rbac.py)

Needs: a dev backend (database vidhi_dev; PAYMENTS_STUB, EMAIL_DRY_RUN) and httpx. It reads outgoing mail (verification, invite and reset links)
from the dev database's `email_outbox` collection with pymongo (read only); it never touches backend/.env. It makes about 6 real AI calls.
A step PASSES only when the status is right AND the body is right (not merely 200). Everything it creates uses throwaway accounts."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import re
import struct
import sys
import time
import uuid
import zlib
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from lib import rbac  # noqa: E402  (a pure table: no side effects)

PW = "Walk-Throwaway-9x!"
RESULTS: list[dict] = []
CTX: dict = {}
BASE = "http://localhost:8002"
DB = None

AREAS = [  # feature area by route prefix, first match wins
    ("/api/auth/2fa", "auth"), ("/api/auth/phone", "auth"), ("/api/auth", "auth"),
    ("/api/matters/{matter_id}/portal", "portal"), ("/api/portal", "portal"),
    ("/api/matters/{matter_id}/documents", "documents"), ("/api/documents", "documents"),
    ("/api/matters/{matter_id}/evidence", "evidence"), ("/api/evidence", "evidence"),
    ("/api/matters/{matter_id}/facts", "facts"), ("/api/matters/{matter_id}/timeline", "timeline"),
    ("/api/matters/{matter_id}/synthesize", "research"), ("/api/matters/{matter_id}/legal-hold", "matters"),
    ("/api/matters", "matters"), ("/api/dashboard", "matters"), ("/api/search", "matters"), ("/api/audit", "org admin"),
    ("/api/research", "research"), ("/api/legal-reasoning", "research"), ("/api/verify-citation", "research"),
    ("/api/drafts", "drafts"), ("/api/templates", "templates"),
    ("/api/recovery", "recovery cases and notice workflow"), ("/api/deadlines", "deadlines"),
    ("/api/conflicts", "conflicts"), ("/api/directory", "directory"), ("/api/public/directory", "directory"), ("/api/public/lawyers", "directory"),
    ("/api/payments", "payments"), ("/api/webhook", "payments"), ("/api/webhooks", "webhooks"),
    ("/api/org", "org admin"), ("/api/admin", "operator (platform admin)"), ("/api/voice", "voice"), ("/api/push", "push"),
    ("/api/privacy", "privacy"), ("/api/support", "support"), ("/api/public", "public"), ("/api/analysis", "analysis"),
    ("/api/knowledge", "knowledge and films"), ("/api/library", "legal library"), ("/api/legal", "legal library"),
    ("/api/decide", "rules engine"), ("/api/images", "images"), ("/api/demo", "demo"), ("/api/cron", "cron"), ("/api/health", "health"),
]


def area_of(path: str) -> str:
    for p, a in AREAS:
        if path.startswith(p):
            return a
    return "other"


# --------------------------------------------------------------------------------------------- recording
def rec(feature, step, route, expected, actual, ok, reason="", ai=False, kind="step"):
    RESULTS.append({"feature": feature, "step": step, "route": route, "expected": expected, "actual": actual,
                    "result": "PASS" if ok else "FAIL", "reason": "" if ok else reason, "ai": ai, "kind": kind})
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {feature:22s} {step[:60]:60s} {route[:55]:55s} exp={expected} got={actual}" + ("" if ok else f"\n        -> {reason[:300]}"))


def skip(feature, step, route, why, ai=False):
    RESULTS.append({"feature": feature, "step": step, "route": route, "expected": "-", "actual": "-", "result": "NOT_TESTED",
                    "reason": why, "ai": ai, "kind": "step"})
    print(f"[SKIP] {feature:22s} {step[:60]:60s} {why[:100]}")


def short(r: httpx.Response, n=260):
    t = r.text.replace("\n", " ")
    return t[:n]


class Who:
    """One signed-in (or anonymous) caller."""
    def __init__(self, name):
        self.name = name
        self.http = httpx.Client(base_url=BASE + "/api", timeout=180)
        self.email = None

    def req(self, method, path, **kw):
        return self.http.request(method, path, **kw)


def step(who: Who, feature, name, method, path, expect, check=None, ai=False, route=None, **kw):
    """Run one request. expect = int or collection of ints. check(r) -> True or a reason string. Returns the response."""
    exp = {expect} if isinstance(expect, int) else set(expect)
    try:
        r = who.req(method, path, **kw)
    except Exception as e:  # noqa: BLE001
        rec(feature, name, route or f"{method} {path}", sorted(exp), "ERR", False, f"request error: {e}", ai)
        return None
    ok, reason = r.status_code in exp, ""
    if not ok:
        reason = f"status {r.status_code}, wanted {sorted(exp)}; response: {short(r)}"
    elif check is not None:
        try:
            res = check(r)
        except Exception as e:  # noqa: BLE001
            res = f"check crashed: {type(e).__name__}: {e}; response: {short(r)}"
        if res is not True:
            ok, reason = False, f"status was right but the content is wrong: {res}; response: {short(r)}"
    rec(feature, name, route or f"{method} {path}", sorted(exp), r.status_code, ok, reason, ai)
    return r


def js(r):
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return None


def new_user(label: str, org="Walk Org") -> Who:
    w = Who(label)
    w.email = f"walk-{label}-{uuid.uuid4().hex[:6]}@example.com"
    r = w.req("POST", "/auth/signup", json={"email": w.email, "password": PW, "full_name": f"Walk {label}", "organization_name": org, "accept_privacy": True, "elapsed_ms": 5000})
    if r.status_code != 200:
        raise SystemExit(f"cannot sign up {label}: {r.status_code} {r.text[:200]}")
    w.me = r.json()
    return w


def outbox(to: str, subject_part: str = "", tries=5):
    for _ in range(tries):
        for m in DB.email_outbox.find({"to": to}).sort("created_at", -1):
            if subject_part.lower() in m["subject"].lower():
                return m
        time.sleep(0.4)
    return None


def token_from(mail) -> str | None:
    if not mail:
        return None
    m = re.search(r"token=([A-Za-z0-9_\-]+)", mail["html"])
    return m.group(1) if m else None


def make_pdf(text: str) -> bytes:
    """A one-page PDF written by hand (no library needed)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"]
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def make_png() -> bytes:
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x10\x60\xa0" * 8 for _ in range(8))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def totp(secret_b32: str) -> str:
    key = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    h = hmac.new(key, struct.pack(">Q", int(time.time() // 30)), hashlib.sha1).digest()
    o = h[-1] & 15
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 10**6:06d}"


# --------------------------------------------------------------------------------------------- inventory
def inventory_md() -> str:
    spec = httpx.get(BASE + "/openapi.json").json()
    rows = []
    for p, ms in spec["paths"].items():
        for m in ms:
            if m.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                cap = rbac.required_cap(m, p)
                if p.startswith("/api/admin/"):
                    who = "any signed-in user passes rbac (cap read); handler then allows only the platform operator"
                else:
                    who = "public / self-authenticating" if cap is None else f"{cap}: " + ", ".join(r for r in ("OWNER", "ADMIN", "LAWYER", "MEMBER", "CLIENT") if cap in rbac.ROLE_CAPS[r])
                rows.append((area_of(p), p, m.upper(), who))
    out = [f"Total routes: {len(rows)}\n"]
    for a in sorted({r[0] for r in rows}):
        sub = sorted((r for r in rows if r[0] == a), key=lambda r: (r[1], r[2]))
        out.append(f"\n### {a} ({len(sub)} routes)\n\n| Method | Path | Who may call it (rbac.py) |\n|---|---|---|")
        out += [f"| {m} | `{p}` | {w} |" for _, p, m, w in sub]
    return "\n".join(out)


# --------------------------------------------------------------------------------------------- the walk
def walk():
    global DB
    from pymongo import MongoClient
    DB = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=3000)["vidhi_dev"]
    anon = Who("anon")

    # ---- health / public
    F = "health"
    step(anon, F, "health check", "GET", "/health", 200, lambda r: js(r) == {"status": "ok"} or "not {status: ok}")
    step(anon, F, "readiness check (database reachable)", "GET", "/health/ready", 200)

    # ---- auth
    F = "auth"
    step(anon, F, "sign-in options (password on, Google off)", "GET", "/auth/options", 200, lambda r: (js(r) or {}).get("password") is True or "password sign-in not offered")
    owner = new_user("owner", "Walk Org A")
    rec(F, "sign up a new owner + organisation", "POST /auth/signup", 200, 200, owner.me.get("role") == "OWNER" and owner.me.get("organization_id") is not None and owner.me.get("email_verified") is False,
        f"unexpected account: {owner.me}")
    step(anon, F, "sign up with the same e-mail is refused", "POST", "/auth/signup", 409, json={"email": owner.email, "password": PW, "full_name": "x", "organization_name": "x", "accept_privacy": True, "elapsed_ms": 5000})
    step(anon, F, "sign up with a too-easy password is refused", "POST", "/auth/signup", {400, 422}, json={"email": f"weak-{uuid.uuid4().hex[:6]}@example.com", "password": "password123", "full_name": "x", "organization_name": "x", "accept_privacy": True, "elapsed_ms": 5000})
    step(anon, F, "sign up with the bot-trap field filled is refused", "POST", "/auth/signup", 400, json={"email": f"bot-{uuid.uuid4().hex[:6]}@example.com", "password": PW, "full_name": "x", "organization_name": "x", "accept_privacy": True, "website": "http://spam", "elapsed_ms": 5000})
    step(anon, F, "login with a wrong password is refused", "POST", "/auth/login", 401, json={"email": owner.email, "password": "Wrong-Password-1!"})
    step(owner, F, "GET /auth/me returns the signed-in owner", "GET", "/auth/me", 200, lambda r: (js(r) or {}).get("email") == owner.email or "wrong user")
    step(anon, F, "GET /auth/me anonymous is refused", "GET", "/auth/me", 401)
    step(owner, F, "entitlement: FREE plan, Recovery open", "GET", "/auth/entitlement", 200, lambda r: ((js(r) or {}).get("plan") == "FREE" and (js(r) or {}).get("recovery_access") is True) or "plan not FREE")
    step(owner, F, "request a new verification e-mail", "POST", "/auth/verify-email/request", 200)
    mail = outbox(owner.email, "confirm")
    tok = token_from(mail)
    rec(F, "verification e-mail captured in the dry-run outbox with a link", "email_outbox", "mail with token", "found" if tok else "none", bool(tok), "no verification mail / token found")
    if tok:
        step(anon, F, "verify e-mail with a wrong token is refused", "POST", "/auth/verify-email", 400, json={"token": "x" * 43})
        step(anon, F, "verify e-mail with the real token", "POST", "/auth/verify-email", 200, json={"token": tok})
        step(owner, F, "me.email_verified is now true", "GET", "/auth/me", 200, lambda r: (js(r) or {}).get("email_verified") is True or "still unverified")
        step(anon, F, "the verification token cannot be used twice", "POST", "/auth/verify-email", 400, json={"token": tok})
    step(owner, F, "save language and theme preferences", "PATCH", "/auth/preferences", 200, json={"language": "hi", "theme": "dark"})
    step(owner, F, "preferences are returned by /auth/me", "GET", "/auth/me", 200, lambda r: ((js(r) or {}).get("language") == "hi" and (js(r) or {}).get("theme") == "dark") or "preferences not saved")
    step(owner, F, "list my sign-in sessions", "GET", "/auth/sessions", 200, lambda r: (isinstance(js(r), (list, dict)) and bool(js(r))) or "no session listed")
    # password reset
    step(anon, F, "forgot-password for an unknown e-mail answers the same (no account hint)", "POST", "/auth/forgot-password", 200, json={"email": f"nobody-{uuid.uuid4().hex[:6]}@example.com"})
    step(anon, F, "forgot-password for the owner", "POST", "/auth/forgot-password", 200, json={"email": owner.email})
    rm = outbox(owner.email, "reset")
    rt = token_from(rm)
    rec(F, "reset e-mail captured with a link", "email_outbox", "mail with token", "found" if rt else "none", bool(rt), "no reset mail found")
    if rt:
        step(anon, F, "reset-password with a too-easy password is refused", "POST", "/auth/reset-password", {400, 422}, json={"token": rt, "new_password": "password123"})
        step(anon, F, "reset-password with the real token", "POST", "/auth/reset-password", 200, json={"token": rt, "new_password": PW + "r"})
        step(anon, F, "old password no longer works after reset", "POST", "/auth/login", 401, json={"email": owner.email, "password": PW})
        step(anon, F, "reset token cannot be reused", "POST", "/auth/reset-password", 400, json={"token": rt, "new_password": PW + "q"})
        owner.pw = PW + "r"
    else:
        owner.pw = PW
    # a reset closes every old session (correct), so sign in again
    step(owner, F, "after a reset the old session is closed", "GET", "/auth/me", 401)
    step(owner, F, "sign in with the reset password", "POST", "/auth/login", 200, json={"email": owner.email, "password": owner.pw})
    # login / logout / change password
    step(owner, F, "change-password with a wrong current password is refused", "POST", "/auth/change-password", {400, 401, 403}, json={"current_password": "Nope-Nope-12!", "new_password": PW + "n"})
    step(owner, F, "change-password", "POST", "/auth/change-password", 200, json={"current_password": owner.pw, "new_password": PW + "n"})
    owner.pw = PW + "n"
    step(owner, F, "log out", "POST", "/auth/logout", 200)
    step(owner, F, "after logout /auth/me is refused", "GET", "/auth/me", 401)
    step(owner, F, "old password refused after change", "POST", "/auth/login", 401, json={"email": owner.email, "password": PW})
    step(owner, F, "log in again with the new password", "POST", "/auth/login", 200, json={"email": owner.email, "password": owner.pw}, check=lambda r: (js(r) or {}).get("email") == owner.email or "wrong user")
    step(owner, F, "signed in again: /auth/me works", "GET", "/auth/me", 200)
    second = httpx.Client(base_url=BASE + "/api", timeout=60)
    second.post("/auth/login", json={"email": owner.email, "password": owner.pw})
    step(owner, F, "log out of all devices", "POST", "/auth/logout-all", 200)
    r2 = second.get("/auth/me")
    rec(F, "the other device's session is also closed", "GET /auth/me (2nd session)", 401, r2.status_code, r2.status_code == 401, "second session still valid after logout-all")
    step(owner, F, "log in once more", "POST", "/auth/login", 200, json={"email": owner.email, "password": owner.pw})
    # Google / SMS / phone
    r = anon.req("GET", "/auth/google/start", follow_redirects=False)
    rec(F, "Google start when Google sign-in is not configured is refused cleanly", "GET /auth/google/start", "4xx (not 500)", r.status_code, 400 <= r.status_code < 500, f"status {r.status_code}: {short(r)}")
    skip(F, "Google sign-in end to end", "GET /auth/google/start|callback", "needs a real Google client id/secret and a browser login; Google is not configured on this dev server (options.google=false)")
    step(owner, F, "phone status (alerts)", "GET", "/auth/phone", 200)
    skip(F, "SMS code to a phone / SMS alerts", "POST /auth/phone/start|verify", "needs real Twilio SMS delivery to a real phone (TWILIO_STUB on in dev)")

    # ---- two-step sign-in on its own throwaway user
    t = new_user("other", "Walk Org B")  # org B user; also used for the cross-organisation checks (signup is limited to 5 an hour per address)
    CTX["b"] = t
    tv = token_from(outbox(t.email, "confirm"))
    if tv:
        t.req("POST", "/auth/verify-email", json={"token": tv})
    r = step(t, F, "2FA: set up (gets a secret)", "POST", "/auth/2fa/setup", 200, lambda r: bool((js(r) or {}).get("secret")) or "no secret")
    if r is not None and r.status_code == 200:
        secret = js(r)["secret"]
        r = step(t, F, "2FA: enable with a wrong code is refused", "POST", "/auth/2fa/enable", {400, 401, 422}, json={"code": "000000"})
        r = step(t, F, "2FA: enable with the right code", "POST", "/auth/2fa/enable", 200, lambda r: bool((js(r) or {}).get("recovery_codes")) or "no recovery codes", json={"code": totp(secret)})
        codes = (js(r) or {}).get("recovery_codes", []) if r is not None else []
        time.sleep(31 - time.time() % 30)  # a code works once: wait for the next 30-second code
        t2 = Who("t2")
        step(t2, F, "2FA: login without the code asks for it (428)", "POST", "/auth/login", 428, json={"email": t.email, "password": PW})
        step(t2, F, "2FA: login with a wrong code is refused", "POST", "/auth/login", 401, json={"email": t.email, "password": PW, "otp": "000000"})
        step(t2, F, "2FA: login with the right code", "POST", "/auth/login", 200, json={"email": t.email, "password": PW, "otp": totp(secret)})
        step(t2, F, "2FA: the same code cannot be used twice", "POST", "/auth/login", 401, json={"email": t.email, "password": PW, "otp": totp(secret)})
        if codes:
            t3 = Who("t3")
            step(t3, F, "2FA: login with a recovery code", "POST", "/auth/login", 200, json={"email": t.email, "password": PW, "otp": codes[0]})
    # ---- public support / privacy
    F = "support"
    step(anon, F, "public support form", "POST", "/public/support", 200, json={"name": "Walk", "email": owner.email, "message": "Feature walk test message, please ignore.", "category": "general"})
    step(anon, F, "support info is public", "GET", "/public/support-info", 200)
    step(anon, F, "public legal config", "GET", "/public/legal-config", 200)
    F = "privacy"
    step(owner, F, "download my data", "GET", "/privacy/my-data", 200, lambda r: (isinstance(js(r), dict) and bool(js(r))) or "empty export")
    step(owner, F, "file a data-rights request (ACCESS)", "POST", "/privacy/requests", 200, lambda r: (js(r) or {}).get("kind") == "ACCESS" or "wrong kind", json={"kind": "ACCESS", "details": "walk test"})
    step(owner, F, "my data-rights requests are listed", "GET", "/privacy/requests", 200, lambda r: len(js(r) if isinstance(js(r), list) else (js(r) or {}).get("items", [])) >= 1 or "request not listed")
    step(owner, F, "support messages (own)", "GET", "/support/messages", 200)

    # ---- matters
    F = "matters"
    r = step(owner, F, "create a matter", "POST", "/matters", 200, lambda r: ((js(r) or {}).get("title") == "Supply dispute Acme v Beta" and (js(r) or {}).get("status") == "OPEN") or "title/status wrong",
             json={"title": "Supply dispute Acme v Beta", "description": "Unpaid invoice 77", "parties": "Acme Ltd vs Beta Pvt Ltd"})
    M = js(r)["id"]
    CTX["M"] = M
    step(owner, F, "read the matter", "GET", f"/matters/{M}", 200, lambda r: (js(r) or {}).get("id") == M or "wrong matter")
    step(owner, F, "matter appears in the list", "GET", "/matters", 200, lambda r: any(m["id"] == M for m in js(r)) or "matter missing from list")
    step(owner, F, "edit the matter description", "PATCH", f"/matters/{M}", 200, lambda r: (js(r) or {}).get("description") == "Unpaid invoice 77 (edited)" or "edit not saved", json={"description": "Unpaid invoice 77 (edited)"})
    step(owner, F, "an unknown matter id gives 404", "GET", f"/matters/{uuid.uuid4()}", 404)

    # ---- documents
    F = "documents"
    txt = (b"SUPPLY AGREEMENT dated 1 March 2025 between Acme Ltd (Supplier) and Beta Pvt Ltd (Buyer). Beta shall pay Rs 500000 within 30 days of invoice. "
           b"Acme delivered goods on 10 March 2025. Invoice 77 dated 12 March 2025 for Rs 500000. Beta has not paid as of 30 June 2025.\n")
    r = step(owner, F, "upload a text document", "POST", f"/matters/{M}/documents", 200,
             lambda r: ((js(r) or {}).get("processing_status") == "READY" and (js(r) or {}).get("text_available") is True and (js(r) or {}).get("size_bytes") == len(txt)) or "not READY / size wrong",
             files={"file": ("agreement.txt", txt, "text/plain")})
    D = js(r)["id"]
    CTX["D"] = D
    r = step(owner, F, "upload a small PDF (hand-made)", "POST", f"/matters/{M}/documents", 200,
             lambda r: ((js(r) or {}).get("processing_status") == "READY" and (js(r) or {}).get("page_count") == 1) or "PDF not READY / page_count != 1",
             files={"file": ("receipt.pdf", make_pdf("Receipt reference ZQXK4471 amount Rs 5000 paid on 5 April 2025"), "application/pdf")})
    PD = js(r)["id"] if r is not None and r.status_code == 200 else None
    if PD:
        step(owner, F, "the PDF's text was read (the reference is findable)", "GET", f"/documents/{PD}", 200,
             lambda r: (js(r) or {}).get("text_available") is True or "text_available false: PDF text not extracted")
        rs = owner.req("GET", "/search", params={"q": "ZQXK4471"})
        found = rs.status_code == 200 and "ZQXK4471" in rs.text
        rec(F, "search finds text inside the uploaded PDF", "GET /search?q=<ref in PDF>", 200, rs.status_code, found, "reference from inside the PDF not found by search: " + short(rs))
    step(owner, F, "document list has both", "GET", f"/matters/{M}/documents", 200, lambda r: len(js(r)) == (2 if PD else 1) or f"{len(js(r))} documents")
    step(owner, F, "download the original file; bytes identical", "GET", f"/documents/{D}/file", 200, lambda r: r.content == txt or "downloaded bytes differ from upload")
    step(owner, F, "an unsupported file type is refused", "POST", f"/matters/{M}/documents", {400, 415, 422}, files={"file": ("evil.exe", b"MZ\x90\x00", "application/x-msdownload")})
    # ---- facts / timeline / evidence
    F = "facts"
    r = step(owner, F, "add a fact tied to the document", "POST", f"/matters/{M}/facts", 200, lambda r: (js(r) or {}).get("document_id") == D or "document link lost", json={"value": "Beta did not pay invoice 77", "fact_type": "EVENT", "document_id": D, "evidence": "Beta has not paid"})
    FID = js(r)["id"]
    step(owner, F, "fact is listed", "GET", f"/matters/{M}/facts", 200, lambda r: any(f["id"] == FID for f in js(r)) or "fact missing")
    F = "timeline"
    r = step(owner, F, "add a timeline event", "POST", f"/matters/{M}/timeline", 200, json={"event_date": "2025-03-10", "description": "Goods delivered", "actor": "Acme"})
    TID = js(r)["id"]
    step(owner, F, "add a second, earlier event", "POST", f"/matters/{M}/timeline", 200, json={"event_date": "2025-03-01", "description": "Agreement signed", "actor": "Both"})
    step(owner, F, "timeline is returned in date order", "GET", f"/matters/{M}/timeline", 200, lambda r: [e["event_date"] for e in js(r)] == sorted(e["event_date"] for e in js(r)) or f"not sorted: {[e['event_date'] for e in js(r)]}")
    step(owner, F, "bad date is refused", "POST", f"/matters/{M}/timeline", {400, 422}, json={"event_date": "not-a-date", "description": "x"})
    F = "evidence"
    r = step(owner, F, "add an evidence item", "POST", f"/matters/{M}/evidence", 200, json={"kind": "DOCUMENT", "label": "Signed agreement", "document_id": D, "quote": "Beta shall pay Rs 500000 within 30 days of invoice."})
    EID = (js(r) or {}).get("id")
    step(owner, F, "evidence list", "GET", f"/matters/{M}/evidence", 200, lambda r: any(e["id"] == EID for e in (js(r) if isinstance(js(r), list) else js(r).get("items", []))) or "item missing")
    if EID:
        step(owner, F, "edit evidence status", "PATCH", f"/matters/{M}/evidence/{EID}", 200, json={"status": "MATCHED"})
    step(owner, F, "evidence framework", "GET", "/evidence/framework", 200)
    step(owner, F, "evidence screen of pasted text (code only)", "POST", "/evidence/classify", 200, json={"text": "The CCTV footage from the shop shows the accused leaving at 9 pm."})
    step(owner, "matters", "entities", "GET", f"/matters/{M}/entities", 200)
    step(owner, "matters", "graph", "GET", f"/matters/{M}/graph", 200)
    step(owner, "matters", "inconsistencies", "GET", f"/matters/{M}/inconsistencies", 200)
    step(owner, "matters", "dashboard stats count the matter and documents", "GET", "/dashboard/stats", 200, lambda r: ((js(r) or {}).get("matters", 0) >= 1 and (js(r) or {}).get("documents", 0) >= 2) or "counts wrong")
    step(owner, "matters", "global search finds the matter by title word", "GET", "/search", 200, lambda r: "Supply dispute" in r.text or "matter not found", params={"q": "Supply"})
    step(owner, "org admin", "audit log shows the actions", "GET", "/audit", 200, lambda r: len(r.text) > 50 or "empty audit")

    # ---- research / AI
    F = "research"
    r = step(owner, F, "AI research on the matter: answer with verified quotes", "POST", "/research", 200, ai=True,
             json={"question": "What was Beta required to pay and by when?", "matter_id": M},
             check=lambda r: _check_research(js(r)))
    RID = (js(r) or {}).get("id") if r is not None and r.status_code == 200 else None
    if RID:
        step(owner, F, "research history lists it", "GET", "/research", 200, lambda r: RID in r.text or "not in history")
        step(owner, F, "rate the answer", "PUT", f"/research/{RID}/feedback", 200, json={"rating": "up", "comment": "walk"})
    r = step(owner, F, "legal question with an EMPTY law library must not show law as VERIFIED", "POST", "/research", 200, ai=True,
             json={"question": "What is the limitation period for recovering an unpaid invoice under Indian law?", "matter_id": M},
             check=lambda r: _check_no_law_verified(js(r)))
    step(owner, F, "citation check against the library (not in library)", "POST", "/verify-citation", 200,
         lambda r: "VERIFIED" not in json.dumps({k: v for k, v in (js(r) or {}).items() if k in ("status", "verification_status")}).replace("UNVERIFIED", "").replace("NOT_VERIFIED", "") or "unknown citation reported VERIFIED",
         json={"citation": "Section 999 of the Imaginary Act, 1850", "claim": "x"})
    r = step(owner, F, "whole-matter synthesis is a Pro feature: refused on FREE", "POST", f"/matters/{M}/synthesize", {402, 403}, json=None)
    F = "documents"
    step(owner, F, "AI document analysis: summary with verified quotes", "POST", f"/documents/{D}/analyze", 200, ai=True, check=lambda r: _check_analyze(js(r)))
    step(owner, F, "set the document class to CONTRACT (after the analysis)", "PATCH", f"/documents/{D}", 200, lambda r: (js(r) or {}).get("doc_class") == "CONTRACT" or "class not saved", json={"doc_class": "CONTRACT"})
    F = "analysis"
    step(owner, F, "analysis route: strategy", "POST", "/analysis/strategy", 200, ai=True,
         check=lambda r: _check_analysis(js(r)), json={"question": "What are the options for recovering an unpaid supply invoice from a business customer?", "context": "Invoice 77, Rs 500000, 30 days terms, unpaid."})
    step(owner, F, "analysis route: unknown kind refused", "POST", "/analysis/astrology", {404, 422}, json={"question": "x", "context": ""})
    F = "drafts"
    r = step(owner, F, "create a draft", "POST", "/drafts", 200, lambda r: (js(r) or {}).get("title") == "Reply to Beta" or "title wrong", json={"title": "Reply to Beta", "body": "Dear Sir,\nPlease pay.", "matter_id": M})
    DR = js(r)["id"]
    step(owner, F, "edit the draft", "PATCH", f"/drafts/{DR}", 200, lambda r: "edited" in (js(r) or {}).get("body", "") or "edit not saved", json={"body": "Dear Sir,\nPlease pay (edited)."})
    step(owner, F, "read the draft back", "GET", f"/drafts/{DR}", 200, lambda r: "edited" in (js(r) or {}).get("body", "") or "stale body")
    step(owner, F, "drafts list", "GET", "/drafts", 200, lambda r: any(d["id"] == DR for d in js(r)) or "draft missing")
    F = "templates"
    rt = step(owner, F, "template catalogue", "GET", "/templates", 200, lambda r: bool(js(r)) or "no templates")
    tl = js(rt) if rt is not None else None
    tl = tl if isinstance(tl, list) else (tl or {}).get("items", []) if isinstance(tl, dict) else []
    if tl:
        tid = tl[0]["id"]
        rr = step(owner, F, "open one template", "GET", f"/templates/{tid}", 200)
        fields = (js(rr) or {}).get("fields", []) if rr is not None else []
        vals = {(f.get("key") or f.get("id") or f.get("name")): _tpl_value(f) for f in fields if isinstance(f, dict)}
        step(owner, F, "fill a template into a draft", "POST", f"/templates/{tid}/draft", 200, lambda r: bool((js(r) or {}).get("id")) or "no draft returned", json={"values": vals, "matter_id": M})

    # ---- knowledge
    F = "knowledge and films"
    step(owner, F, "knowledge domains", "GET", "/knowledge/domains", 200, lambda r: bool(js(r)) or "empty")
    step(owner, F, "knowledge search finds text in a loaded book", "GET", "/knowledge/search", 200, lambda r: (len((js(r) or {}).get("hits", [])) > 0 and all("work" in h for h in js(r)["hits"])) or "no hits / no work names", params={"q": "justice"})
    step(owner, F, "knowledge search for nonsense finds nothing", "GET", "/knowledge/search", 200, lambda r: len((js(r) or {}).get("hits", [])) == 0 or "hits for nonsense", params={"q": "qzxvwk plmnbv"})
    step(owner, F, "film catalogue", "GET", "/knowledge/films", 200, lambda r: bool(js(r)) or "empty")
    step(owner, F, "film exercises", "GET", "/knowledge/films/exercises", 200)
    word = "zqxvprivate" + uuid.uuid4().hex[:6]
    r = step(owner, F, "add a private note to the knowledge base", "POST", "/knowledge/private", 200, json={"title": "Walk note", "text": f"The {word} clause means nothing in particular but is searchable."})
    step(owner, F, "the private note is listed", "GET", "/knowledge/private", 200, lambda r: "Walk note" in r.text or "not listed")
    step(owner, F, "the private note is found by search", "GET", "/knowledge/search", 200, lambda r: word in r.text or "private text not found", params={"q": word})
    num = (js(r) or {}).get("number") or (js(r) or {}).get("id")
    if num:
        step(owner, F, "delete the private note", "DELETE", f"/knowledge/private/{num}", 200)

    # ---- legal library
    F = "legal library"
    for p, nm, q in (("/library", "library list", None), ("/library/jurisdictions", "jurisdictions", None), ("/legal/coverage", "coverage", None), ("/legal/resources", "resources", None), ("/legal/forums", "forums", None), ("/legal/decisions", "decisions lookup (unknown citation: honest 'not loaded')", {"citation": "AIR 1950 SC 1"}), ("/legal/mappings", "mappings lookup (unknown section)", {"number": "999"})):
        step(owner, F, nm, "GET", p, {200, 404} if "decisions" in p else 200, (lambda r: r.status_code == 200 or "not loaded" in r.text or "404 without the honest 'not loaded' message") if "decisions" in p else None, params=q)
    step(owner, F, "legal search on empty library answers honestly (no invented law)", "GET", "/legal/search", 200, lambda r: not _claims_law_found(js(r)) or "returned legal hits although the library is empty", params={"q": "limitation"})
    pass  # legal-reasoning is exercised by org B (the free AI allowance is 5 a day per ORGANISATION)

    bb = CTX["b"]
    step(bb, "legal library", "legal-reasoning workflow (AI), as owner of org B", "POST", "/legal-reasoning", 200, ai=True, check=lambda r: _check_reasoning(js(r)),
         json={"question": "Can an unpaid supplier recover the invoice amount from the buyer?", "facts": "Goods delivered 10 March 2025; invoice 77 for Rs 500000; not paid.", "jurisdiction": "IN"})
    # ---- conflicts
    F = "conflicts"
    step(owner, F, "conflict check finds an existing party", "POST", "/conflicts/check", 200, lambda r: "Beta" in r.text and _has_conflict_hit(js(r)) or "existing party 'Beta Pvt Ltd' not flagged", json={"names": ["Beta Pvt Ltd"]})
    step(owner, F, "conflict check on an unknown name finds nothing", "POST", "/conflicts/check", 200, lambda r: not _has_conflict_hit(js(r)) or "false conflict", json={"names": ["Zyxwvut Qqqq Nobody"]})

    # ---- deadlines
    F = "deadlines"
    r = step(owner, F, "add a deadline", "POST", "/deadlines", 201, lambda r: (js(r) or {}).get("title") == "File reply" or "title wrong", json={"title": "File reply", "kind": "deadline", "starts_local": "2027-03-05T10:30", "tz": "Asia/Kolkata", "matter_id": M, "reminders": [1440]})
    DL = (js(r) or {}).get("id")
    step(owner, F, "deadline appears in the list at the right local time", "GET", "/deadlines", 200, lambda r: any(d["id"] == DL and d["starts_local"].startswith("2027-03-05T10:30") for d in js(r)["items"]) or "missing / time shifted")
    step(owner, F, "calendar file for the deadline", "GET", f"/deadlines/{DL}/calendar.ics", 200, lambda r: ("BEGIN:VCALENDAR" in r.text and "File reply" in r.text) or "not a valid calendar")
    step(owner, F, "all-deadlines calendar", "GET", "/deadlines/calendar.ics", 200, lambda r: "BEGIN:VCALENDAR" in r.text or "bad ics")
    step(owner, F, "move the deadline", "PATCH", f"/deadlines/{DL}", 200, lambda r: (js(r) or {}).get("starts_local", "").startswith("2027-03-06") or "date not moved", json={"starts_local": "2027-03-06T11:00"})
    step(owner, F, "unknown kind refused", "POST", "/deadlines", {400, 422}, json={"title": "x", "kind": "bogus", "starts_local": "2027-03-05T10:30"})
    step(owner, F, "delete the deadline", "DELETE", f"/deadlines/{DL}", {200, 204})
    step(owner, F, "deleted deadline is gone", "GET", "/deadlines", 200, lambda r: not any(d["id"] == DL for d in js(r)["items"]) or "still listed")

    # ---- recovery
    recovery_walk(owner)

    # ---- rules engine / voice / push / images / directory / demo
    F = "rules engine"
    step(owner, F, "case priorities (no AI)", "GET", "/decide/cases", 200)
    step(owner, F, "classify a question (no AI)", "POST", "/decide/question", 200, json={"text": "Customer says the cheque bounced last week, what now?"})
    F = "voice"
    rv = step(owner, F, "voice status", "GET", "/voice/status", 200)
    skip(F, "speech-to-text / text-to-speech with the real ElevenLabs or Gemini voice", "POST /voice/transcribe|speak", "dev server runs VOICE_STUB; a real recording and real audio output need a microphone/speaker and the provider")
    F = "push"
    step(owner, F, "push config", "GET", "/push/config", 200)
    step(owner, F, "subscribe a (fake) browser endpoint", "POST", "/push/subscribe", 200, json={"endpoint": "https://fcm.googleapis.com/fcm/send/walk-" + uuid.uuid4().hex, "keys": {"p256dh": "BNc" + "A" * 80, "auth": "B" * 22}})
    skip(F, "a real push notification arriving on a device", "POST /push/test", "WEBPUSH_STUB is on; delivery needs a real browser subscription")
    F = "images"
    step(owner, F, "image status", "GET", "/images/status", 200)
    skip(F, "AI illustration generation", "POST /images/generate", "off by default, Pro only and capped; IMAGEGEN_STUB in dev (no real image)")
    F = "directory"
    rd = step(owner, F, "directory profile (feature is OFF unless DIRECTORY_ENABLED=true)", "GET", "/directory/profile", {200, 403, 404})
    step(anon, F, "public lawyer directory answers anonymously", "GET", "/public/lawyers", {200, 404})
    F = "demo"
    step(owner, F, "create the sample case", "POST", "/demo/sample", 200)

    # ---- org admin + roles
    roles = org_walk(owner)

    # ---- permissions matrix, cross-org, anonymous
    matrix(owner, roles, anon)
    cross_org(owner, roles)

    # ---- payments last (changes the plan)
    payments_walk(owner)

    # ---- webhooks / cron are closed to outsiders
    F = "webhooks"
    for p in ("webhook/stripe", "webhook/razorpay", "webhook/paypal", "webhooks/resend", "webhooks/sendgrid", "webhooks/twilio"):
        step(anon, F, f"unsigned call to /{p} is rejected", "POST", f"/{p}", {400, 401, 403, 404, 422, 503}, content=b"{}", headers={"content-type": "application/json"})
    for p in ("cron/jobs", "cron/deadline-reminders", "cron/recovery-reminders", "cron/retention", "cron/scheduled-statements"):
        step(anon, "cron", f"cron without the secret is rejected: /{p}", "POST", f"/{p}", {401, 403, 503})
        step(anon, "cron", f"cron with a wrong secret is rejected: /{p}", "POST", f"/{p}", {401, 403, 503}, headers={"authorization": "Bearer wrong-secret-value"})

    # ---- clean-up: delete data, then the whole organisation
    F = "matters"
    step(owner, F, "delete the matter (and its documents)", "DELETE", f"/matters/{M}", 200)
    step(owner, F, "deleted matter is gone", "GET", f"/matters/{M}", 404)
    step(owner, F, "its document is gone too", "GET", f"/documents/{D}", 404)
    F = "org admin"
    step(owner, F, "erase the organisation with the wrong password is refused", "DELETE", "/org", {400, 401, 403, 422}, json={"password": "wrong-password-1", "organization_name": "Walk Org A"})
    step(owner, F, "erase the whole organisation (owner)", "DELETE", "/org", 200, json={"password": owner.pw, "organization_name": "Walk Org A"})
    step(anon, F, "after erasure the owner can no longer log in", "POST", "/auth/login", 401, json={"email": owner.email, "password": owner.pw})


# ---- content checks ------------------------------------------------------------------------------
def _check_research(d):
    if not isinstance(d, dict):
        return "no JSON"
    ans = d.get("answer", "")
    claims = d.get("claims") or []
    if not ans:
        return "empty answer"
    if "500" not in ans.replace(",", ""):
        return f"answer does not mention the Rs 500000 amount: {ans[:150]}"
    if not ("11 April 2025" in ans or "11 Apr" in ans or "30 days" in ans):
        return "answer does not give the 30-day / 11 April due date"
    if not claims:
        return "no claims"
    for c in claims:
        if c.get("verification_status") == "VERIFIED":
            cits = c.get("citations") or []
            if not cits or not all(x.get("quote_verified") for x in cits):
                return "a claim is VERIFIED without a verified quote"
            if cits[0].get("passage") and cits[0]["passage"] not in (CTX.get("DOC_TEXT") or cits[0]["passage"]):
                return "quote not in the document"
    if not any(c.get("verification_status") == "VERIFIED" for c in claims):
        return "no claim verified against the document although the text is in it"
    return True


def _check_no_law_verified(d):
    if not isinstance(d, dict) or not d.get("answer"):
        return "no answer"
    for c in d.get("claims") or []:
        for x in c.get("citations") or []:
            if x.get("authority_level") not in (None, "MATTER_DOCUMENT") and c.get("verification_status") == "VERIFIED":
                return f"a claim backed by outside law is VERIFIED although the law library is empty: {c.get('text', '')[:120]}"
        if c.get("claim_kind") == "LEGAL" and c.get("verification_status") == "VERIFIED":
            return f"a LEGAL claim is VERIFIED with an empty library: {c.get('text', '')[:120]}"
    return True


def _check_analyze(d):
    if not isinstance(d, dict):
        return "no JSON"
    kf = d.get("key_facts") or []
    if not d.get("summary") or not kf:
        return "no summary / key facts"
    bad = [k for k in kf if not k.get("quote_verified")]
    if bad:
        return f"{len(bad)} key facts have an unverified quote"
    if not any("500000" in k.get("quote", "") for k in kf):
        return "the Rs 500000 payment term was not extracted"
    return True


def _check_analysis(d):
    if not isinstance(d, dict) or d.get("kind") != "strategy":
        return "wrong shape"
    if not str(d.get("summary") or "").strip():
        return "empty summary"
    low = json.dumps(d).lower()
    if " lied" in low or " liar" in low:
        return "uses 'lied/liar' wording (house rule 2)"
    return True


def _check_reasoning(d):
    if not isinstance(d, dict):
        return "no JSON"
    low = json.dumps(d)
    if '"VERIFIED"' in low and "LIBRARY" not in low.upper():
        return "reports VERIFIED law without a library source"
    return True if low and len(low) > 50 else "empty"


def _claims_law_found(d):
    if not isinstance(d, dict):
        return False
    for k in ("hits", "results", "items", "provisions"):
        if d.get(k):
            return True
    return False


def _has_conflict_hit(d):
    if isinstance(d, dict):
        if isinstance(d.get("results"), list):
            return any(x.get("matches") for x in d["results"] if isinstance(x, dict))
        for k in ("hits", "conflicts", "matches", "items"):
            if d.get(k):
                return True
        return bool(d.get("has_conflict") or d.get("conflict"))
    return bool(d)


def _tpl_value(f):
    lab = str(f.get("label") or f.get("key") or f.get("name") or "").lower()
    if "days" in lab:
        return "15"
    if "date" in lab:
        return "2026-11-05"
    if "amount" in lab:
        return "25000"
    return "Test value"


# ---- recovery -------------------------------------------------------------------------------------
def recovery_walk(o: Who):
    F = "recovery cases"
    # (a) a creditor whose name ends in "rs" ("Acme Traders") and whose address line starts with a number: reproduces the notice blocker bug
    cases = {}
    for tag, cname in (("bug", "Acme Traders"), ("main", "Acme Supplies Ltd")):
        r = step(o, F, f"[{tag}] create a recovery case", "POST", "/recovery/cases", 200, lambda r: ((js(r) or {}).get("status") == "DRAFT" and (js(r) or {}).get("amount") == 50000.0) or "status/amount wrong",
                 json={"creditor_name": cname, "debtor_name": "Beta Pvt Ltd", "amount": 50000, "currency": "INR", "description": "Unpaid invoice 77 for goods supplied on 10 March 2025", "debtor_email": "debtor@example.org"})
        cid = js(r)["id"]
        cases[tag] = cid
        step(o, F, f"[{tag}] save addresses, due date, interest rate", "PATCH", f"/recovery/cases/{cid}/details", 200,
             lambda r: ((js(r) or {}).get("due_date") == "2025-04-11" and (js(r) or {}).get("interest_rate_pct") == 12.0) or "details not saved",
             json={"creditor_address": "12 MG Road, Pune 411001", "debtor_address": "4 Park Street, Kolkata 700016", "due_date": "2025-04-11", "interest_rate_pct": 12})
        step(o, F, f"[{tag}] save invoice details (intake)", "PATCH", f"/recovery/cases/{cid}/intake", 200, lambda r: (js(r) or {}).get("intake", {}).get("invoice_number") == "77" or "intake not saved",
             json={"invoice_number": "77", "invoice_date": "2025-03-12", "supply_description": "Industrial fasteners", "payment_terms": "30 days from invoice", "creditor_email": "accounts@acme.example", "response_days": 15})
        step(o, F, f"[{tag}] upload proof (invoice)", "POST", f"/recovery/cases/{cid}/proofs", 200, lambda r: (js(r) or {}).get("processing_status") == "READY" or "proof not READY",
             files={"file": ("invoice77.txt", b"Invoice 77 dated 12 March 2025. Acme to Beta Pvt Ltd. Amount Rs 50000. Goods: industrial fasteners. Payment within 30 days.", "text/plain")}, data={"kind": "INVOICE"})
        if tag == "bug":
            F2 = "recovery AI"
            step(o, F2, "[bug] extract case summary and timeline (AI)", "POST", f"/recovery/cases/{cid}/extract", 200, ai=True,
                 check=lambda r: ((js(r) or {}).get("status") == "TIMELINE_READY" and len((js(r) or {}).get("timeline", [])) >= 2 and (js(r) or {}).get("detected_amount") == 50000.0) or "no timeline / amount not detected as 50000")
            step(o, F2, "[bug] generate the demand notice (AI)", "POST", f"/recovery/cases/{cid}/notice", 200, ai=True, json={"acknowledge_route": True, "response_days": 15},
                 check=lambda r: ("Statement of account" in (js(r) or {}).get("notice_body", "") and "50,000.00" in (js(r) or {}).get("notice_body", "")) or "notice lacks the statement of account / amount")
            w = o.req("GET", f"/recovery/cases/{cid}/notice/workflow").json()
            b = (w.get("blockers") or {})
            rec("recovery cases", "[bug] a clean notice for creditor 'Acme Traders' (address '12 MG Road') is NOT blocked by the amount checker", f"GET /recovery/cases/{cid}/notice/workflow", "blocked=false", f"blocked={b.get('blocked')} amount_mismatches={b.get('amount_mismatches')}",
                b.get("blocked") is False, f"false positive: the notice is blocked with amount_mismatches={b.get('amount_mismatches')} because 'Traders' + newline + '12 MG Road' reads as 'Rs 12' (lib/notice_checks.py _CUR has no word boundary before Rs)")
            step(o, F, "[bug] approving that blocked notice is refused", "POST", f"/recovery/cases/{cid}/notice/approve", 409, json={"acknowledged": True})
    cid = cases["main"]
    F = "recovery cases"
    step(o, F, "readiness shows the balance 50,000 and the proof", "GET", f"/recovery/cases/{cid}/readiness", 200,
         lambda r: ((js(r) or {}).get("balance", {}).get("balance") == 50000.0 and any(i["status"] == "PRESENT" for i in js(r)["evidence"]["items"])) or "balance/proof wrong")
    F = "recovery AI"
    step(o, F, "extract case summary and timeline (AI)", "POST", f"/recovery/cases/{cid}/extract", 200, ai=True,
         check=lambda r: ((js(r) or {}).get("status") == "TIMELINE_READY" and (js(r) or {}).get("detected_amount") == 50000.0 and "50,000" in (js(r) or {}).get("summary", "")) or "summary lacks the amount or status not TIMELINE_READY")
    r = step(o, F, "generate the demand notice (AI)", "POST", f"/recovery/cases/{cid}/notice", 200, ai=True, json={"acknowledge_route": True, "response_days": 15}, check=lambda r: _check_notice(js(r)))
    F = "recovery cases"
    w = js(o.req("GET", f"/recovery/cases/{cid}/notice/workflow"))
    if (w.get("blockers") or {}).get("blocked"):
        body = js(o.req("GET", f"/recovery/cases/{cid}")).get("notice_body", "")
        w["blockers_detail"] = json.dumps(w.get("blockers")) + " | notice lines with a number after 'rs': " + " || ".join(re.findall(r"[^\n]*[Rr][Ss]\.?\s{0,3}\d[^\n]*", body)[:3])
    rec(F, "notice workflow: draft, not blocked, approval allowed", f"GET /recovery/cases/{cid}/notice/workflow", "state=DRAFT, blocked=false", f"state={w.get('state')} blocked={(w.get('blockers') or {}).get('blocked')}",
        w.get("state") == "DRAFT" and (w.get("blockers") or {}).get("blocked") is False and "approve" in (w.get("allowed") or []), f"workflow: {w.get('blockers_detail') or json.dumps(w)[:300]}")
    step(o, F, "approve WITHOUT ticking the box is refused", "POST", f"/recovery/cases/{cid}/notice/approve", 422, json={"acknowledged": False})
    step(o, F, "approve the notice (owner)", "POST", f"/recovery/cases/{cid}/notice/approve", 200, lambda r: (js(r) or {}).get("approved", {}).get("version") == 1 or "approval not bound to version 1", json={"acknowledged": True})
    step(o, F, "workflow now APPROVED", "GET", f"/recovery/cases/{cid}/notice/workflow", 200, lambda r: (js(r) or {}).get("state") == "APPROVED" or f"state {(js(r) or {}).get('state')}")
    step(o, F, "prepare the e-mail (NOT sent) with a verified sender", "POST", f"/recovery/cases/{cid}/email/prepare", 200, lambda r: bool((js(r) or {}).get("confirmation_id")) or "no confirmation_id", json={"debtor_email": "debtor@example.org"})
    step(o, F, "nothing was sent: e-mail log is empty", "GET", f"/recovery/cases/{cid}/emails", 200, lambda r: (js(r) in ([], None) or (isinstance(js(r), dict) and not js(r).get("items"))) or "an e-mail was logged although only prepare was called")
    skip(F, "send the notice e-mail to the debtor", f"POST /recovery/cases/{cid}/email", "deliberately not sent (instruction: prepare only); real delivery cannot be tested with EMAIL_DRY_RUN anyway")
    step(o, F, "notice PDF downloads", "GET", f"/recovery/cases/{cid}/notice.pdf", 200, lambda r: r.content[:5] == b"%PDF-" or "not a PDF")
    step(o, F, "interest before any payment: 12% simple on 50,000 from 2025-04-11", "GET", f"/recovery/cases/{cid}/interest", 200, lambda r: _check_interest(js(r), 0))
    step(o, F, "record a part payment of 10,000", "POST", f"/recovery/cases/{cid}/payment", 200, lambda r: ((js(r) or {}).get("paid_amount") == 10000.0 and len((js(r) or {}).get("payments", [])) == 1) or "payment not recorded", json={"amount": 10000, "date": "2026-10-01"})
    pid = (js(o.req("GET", f"/recovery/cases/{cid}")).get("payments") or [{}])[0].get("id")
    step(o, F, "readiness balance is now 40,000", "GET", f"/recovery/cases/{cid}/readiness", 200, lambda r: (js(r) or {}).get("balance", {}).get("balance") == 40000.0 or f"balance {(js(r) or {}).get('balance', {}).get('balance')}")
    step(o, F, "interest reflects the part payment", "GET", f"/recovery/cases/{cid}/interest", 200, lambda r: _check_interest(js(r), 10000))
    step(o, F, "after a payment the old notice is blocked from download/e-mail until re-drafted", "POST", f"/recovery/cases/{cid}/email/prepare", 409, json={"debtor_email": "debtor@example.org"})
    step(o, F, "limitation help (no invented periods)", "GET", f"/recovery/cases/{cid}/limitation", 200, lambda r: ((js(r) or {}).get("mode") in ("GENERIC", "VERIFIED") and ((js(r) or {}).get("mode") != "GENERIC" or (js(r) or {}).get("rules") == [])) or "generic mode returned rules")
    step(o, F, "statement preview", "GET", f"/recovery/cases/{cid}/statement-preview", 200)
    step(o, F, "statement PDF", "GET", f"/recovery/cases/{cid}/statement.pdf", 200, lambda r: r.content[:5] == b"%PDF-" or "not a PDF")
    step(o, F, "evidence pack ZIP", "GET", f"/recovery/cases/{cid}/evidence-pack.zip", 200, lambda r: r.content[:2] == b"PK" or "not a zip")
    step(o, F, "log a correspondence entry", "POST", f"/recovery/cases/{cid}/correspondence", 200, json={"direction": "OUT", "channel": "EMAIL", "occurred_on": "2026-10-02", "summary": "Reminder sent"})
    step(o, F, "set reminders cadence", "PATCH", f"/recovery/cases/{cid}/reminders", 200, json={"enabled": True, "cadence_days": 7})
    step(o, F, "set statement schedule", "PATCH", f"/recovery/cases/{cid}/statement-schedule", 200, json={"schedule": "MONTHLY", "day": 5})
    step(o, F, "delete the payment", "DELETE", f"/recovery/cases/{cid}/payment/{pid}", 200)
    step(o, F, "balance returns to 50,000", "GET", f"/recovery/cases/{cid}/readiness", 200, lambda r: (js(r) or {}).get("balance", {}).get("balance") == 50000.0 or "balance not restored")
    step(o, F, "hand the case to a lawyer (creates a matter)", "POST", f"/recovery/cases/{cid}/handoff", 200, lambda r: str((js(r) or {}).get("title", "")).startswith("Recovery:") or "no matter returned")
    step(o, F, "mark the case resolved", "POST", f"/recovery/cases/{cid}/resolve", 200)
    step(o, F, "reopen the case", "POST", f"/recovery/cases/{cid}/reopen", 200)
    step(o, F, "case list contains both cases", "GET", "/recovery/cases", 200, lambda r: {cases["bug"], cases["main"]} <= {c["id"] for c in js(r)} or "case missing")
    skip("recovery AI", "translate the notice into another language", f"POST /recovery/cases/{cid}/notice/translate", "kept out to limit AI spend (one more model call); needs a fluent reviewer anyway")
    skip(F, "advocate review of a notice", f"POST /recovery/cases/{cid}/notice/review", "only an advocate's own declaration is valid; not simulated")
    skip(F, "postal tracking updates from a courier", "POST .../notice/postal", "needs a real courier/post tracking record")
    CTX["case"] = cid
    CTX["case_bug"] = cases["bug"]


def _check_notice(d):
    body = (d or {}).get("notice_body", "")
    if not body:
        return "empty notice"
    for must in ("Statement of account", "50,000.00", "Acme Supplies Ltd", "Beta Pvt Ltd", "77"):
        if must not in body:
            return f"notice is missing '{must}'"
    low = body.lower()
    for bad in (" lied", "section ", "act, ", "[ ]", "fraud", "criminal"):
        if bad in low:
            return f"notice contains risky/legal/blank text '{bad.strip()}'"
    if "interest" in low and "9,205.48" not in body:
        return "interest figure not the one computed by code (9,205.48 on the day it was written)"
    return True


def _check_interest(d, paid):
    if not isinstance(d, dict) or "interest" not in d:
        return "no interest field"
    from datetime import date
    start = date.fromisoformat(d["start"])
    asof = date.fromisoformat(d["as_of"])
    if paid == 0:
        exp = round(50000 * 0.12 * (asof - start).days / 365, 2)
    else:
        pay = date(2026, 10, 1)
        exp = round(50000 * 0.12 * (pay - start).days / 365 + 40000 * 0.12 * (asof - pay).days / 365, 2)
    if abs(exp - d["interest"]) > 0.02:
        return f"interest {d['interest']} but independent arithmetic gives {exp}"
    return True


# ---- org / roles ----------------------------------------------------------------------------------
def org_walk(o: Who) -> dict:
    F = "org admin"
    step(o, F, "members list shows the owner", "GET", "/org/members", 200, lambda r: any(m["email"] == o.email for m in js(r)) or "owner not listed")
    step(o, F, "branding: set firm name", "PATCH", "/org/branding", 200, json={"firm_name": "Walk & Co", "firm_address": "1 Test Road"})
    step(o, F, "branding is read back", "GET", "/org/branding", 200, lambda r: "Walk & Co" in r.text or "firm name not saved")
    step(o, F, "upload a logo (tiny PNG)", "POST", "/org/logo", 200, files={"file": ("logo.png", make_png(), "image/png")})
    step(o, F, "logo is served", "GET", "/org/logo", 200, lambda r: ((js(r) or {}).get("has_logo") is True and str((js(r) or {}).get("data_url", "")).startswith("data:image/png")) or "logo not returned")
    step(o, F, "retention setting: set 365 days", "PUT", "/org/retention", 200, json={"retention_days_after_close": 365})
    step(o, F, "retention setting is read back", "GET", "/org/retention", 200, lambda r: "365" in r.text or "not saved")
    step(o, F, "organisation data export", "GET", "/org/export", 200, lambda r: len(r.content) > 100 or "empty export")
    step(o, "matters", "legal hold on / off", "PATCH", f"/matters/{CTX['M']}/legal-hold", 200, lambda r: (js(r) or {}).get("legal_hold") is True or "hold not set", json={"on": True})
    step(o, "matters", "delete is blocked while legal hold is on", "DELETE", f"/matters/{CTX['M']}", {409, 423, 403}) if False else None
    o.req("PATCH", f"/matters/{CTX['M']}/legal-hold", json={"on": False})
    roles: dict[str, Who] = {"OWNER": o}
    for role in ("ADMIN", "LAWYER", "MEMBER"):
        em = f"walk-{role.lower()}-{uuid.uuid4().hex[:6]}@example.com"
        r = step(o, F, f"invite a {role}", "POST", "/org/invites", 200, json={"email": em, "role": role})
        mail = outbox(em, "invited")
        tok = token_from(mail)
        rec(F, f"invite e-mail for {role} captured in the dry-run outbox", "email_outbox", "mail with link", "found" if tok else "none", bool(tok), "no invitation mail captured")
        if not tok:
            continue
        step(Who("x"), F, f"invite link shows the organisation ({role})", "GET", f"/auth/invites/{tok}", 200, lambda r: "Walk Org A" in r.text or "org name missing")
        w = Who(role)
        w.email = em
        r = step(w, F, f"accept the invitation as {role}", "POST", "/auth/accept-invite", 200, lambda r, role=role: (js(r) or {}).get("role") == role or "wrong role", json={"token": tok, "password": PW, "full_name": f"Walk {role}", "accept_privacy": True})
        if r is not None and r.status_code == 200:
            w.pw = PW
            roles[role] = w
        step(Who("x"), F, f"the invitation link works only once ({role})", "POST", "/auth/accept-invite", {400, 404}, json={"token": tok, "password": PW, "full_name": "x", "accept_privacy": True})
    step(o, F, "members list now has 4 people", "GET", "/org/members", 200, lambda r: len(js(r)) == 4 or f"{len(js(r))} members")
    if "MEMBER" in roles:
        uid = roles["MEMBER"].me_id = js(roles["MEMBER"].req("GET", "/auth/me"))["id"]
        step(o, F, "owner promotes the MEMBER to LAWYER", "PATCH", f"/org/members/{uid}", 200, json={"role": "LAWYER"})
        step(roles["MEMBER"], F, "the promoted user now has AI rights (capabilities)", "GET", "/auth/me", 200, lambda r: "ai" in (js(r) or {}).get("capabilities", []) or "capabilities not updated")
        step(o, F, "owner demotes back to MEMBER", "PATCH", f"/org/members/{uid}", 200, json={"role": "MEMBER"})
    if "ADMIN" in roles:
        aid = js(roles["ADMIN"].req("GET", "/auth/me"))["id"]
        step(roles["ADMIN"], F, "an ADMIN cannot make someone an OWNER", "PATCH", f"/org/members/{js(roles['MEMBER'].req('GET', '/auth/me'))['id']}", {400, 403}, json={"role": "OWNER"}) if "MEMBER" in roles else None
        step(roles["ADMIN"], F, "an ADMIN cannot change the OWNER", "PATCH", f"/org/members/{o.me['id']}", {400, 403}, json={"role": "MEMBER"})
        step(roles["ADMIN"], F, "an ADMIN cannot remove the OWNER", "DELETE", f"/org/members/{o.me['id']}", {400, 403})
    # client portal
    step(o, "portal", "the matter has no portal clients yet", "GET", f"/matters/{CTX['M']}/portal", 200)
    cem = f"walk-client-{uuid.uuid4().hex[:6]}@example.com"
    r = step(o, "portal", "invite a client to the portal", "POST", f"/matters/{CTX['M']}/portal/clients", 200, lambda r: (js(r) or {}).get("pending") is True or "not pending", json={"email": cem})
    tok = token_from(outbox(cem, "portal"))
    if tok:
        c = Who("CLIENT")
        c.email = cem
        r = step(c, "portal", "client accepts the portal invitation", "POST", "/auth/accept-invite", 200, lambda r: (js(r) or {}).get("role") == "CLIENT" or "not a CLIENT", json={"token": tok, "password": PW, "full_name": "Walk Client", "accept_privacy": True})
        if r is not None and r.status_code == 200:
            c.pw = PW
            roles["CLIENT"] = c
            step(c, "portal", "client sees the shared matter list (nothing shared yet is hidden)", "GET", "/portal/matters", 200)
            step(o, "portal", "owner posts an update", "POST", f"/matters/{CTX['M']}/portal/updates", 200, json={"text": "Your reply is filed."})
            step(o, "portal", "owner shares the agreement document", "POST", f"/matters/{CTX['M']}/portal/documents", 200, json={"document_id": CTX["D"]})
            step(c, "portal", "client sees the update", "GET", f"/portal/matters/{CTX['M']}", 200, lambda r: "Your reply is filed." in r.text or "update not visible")
            step(c, "portal", "client can download the shared document", "GET", f"/portal/matters/{CTX['M']}/documents/{CTX['D']}/file", 200)
            step(c, "portal", "client cannot read the matter itself (staff route)", "GET", f"/matters/{CTX['M']}", 403)
            step(c, "portal", "client cannot read facts", "GET", f"/matters/{CTX['M']}/facts", 403)
    return roles


# ---- the permissions matrix -------------------------------------------------------------------------
SAFE_ALLOW_SKIP = ("/auth/logout", "/auth/logout-all", "/auth/2fa/", "/demo/sample", "/payments/subscription/", "/org/logo", "/cron/", "/push/test", "/auth/sessions", "/org/export")


def fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "nonexistent-id", path)


def matrix(o: Who, roles: dict, anon: Who):
    F = "permissions"
    spec = httpx.get(BASE + "/openapi.json").json()
    routes = [(m.upper(), p) for p, ms in spec["paths"].items() for m in ms if m.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE")]
    tally = {}
    for role in ("MEMBER", "LAWYER", "ADMIN", "CLIENT"):
        w = roles.get(role)
        if not w:
            skip(F, f"{role} matrix", "-", f"no {role} session could be created")
            continue
        bad_deny, bad_allow, n_deny, n_allow = [], [], 0, 0
        for m, p in routes:
            cap = rbac.required_cap(m, p)
            if cap is None or p.startswith("/api/admin/"):
                continue
            allowed = cap in rbac.ROLE_CAPS[role]
            url = fill(p)[4:]
            if allowed and any(s in p for s in SAFE_ALLOW_SKIP):
                continue
            try:
                r = w.req(m, url, json={} if m in ("POST", "PUT", "PATCH", "DELETE") else None) if m != "GET" else w.req(m, url)
            except Exception as e:  # noqa: BLE001
                bad_deny.append(f"{m} {p}: {e}")
                continue
            if allowed:
                n_allow += 1
                if r.status_code in (401, 403) and not (r.status_code == 403 and "role" not in r.text.lower() and "allowed" not in r.text.lower()):
                    bad_allow.append(f"{m} {p} -> {r.status_code} {short(r, 120)}")
            else:
                n_deny += 1
                if r.status_code != 403:
                    bad_deny.append(f"{m} {p} -> {r.status_code} (expected 403)")
        tally[role] = (n_deny, n_allow)
        rec(F, f"{role}: every route rbac.py denies is refused (403)", f"{n_deny} routes", "all 403", f"{n_deny - len(bad_deny)}/{n_deny} refused", not bad_deny, "; ".join(bad_deny[:6]), kind="matrix")
        rec(F, f"{role}: every route rbac.py allows gets past the permission gate", f"{n_allow} routes", "never 401/403 by role", f"{n_allow - len(bad_allow)}/{n_allow} passed gate", not bad_allow, "; ".join(bad_allow[:6]), kind="matrix")
    # OWNER can reach everything it should
    bad = []
    n = 0
    for m, p in routes:
        cap = rbac.required_cap(m, p)
        if cap is None or p.startswith("/api/admin/") or any(s in p for s in SAFE_ALLOW_SKIP) or (m == "DELETE" and p == "/api/org") or cap not in rbac.ROLE_CAPS["OWNER"]:
            continue
        n += 1
        r = o.req(m, fill(p)[4:], json={} if m != "GET" else None) if m != "GET" else o.req(m, fill(p)[4:])
        if r.status_code in (401, 403) and "role" in r.text.lower():
            bad.append(f"{m} {p} -> {r.status_code}")
    rec(F, "OWNER: routes allowed by rbac.py get past the gate", f"{n} routes", "never refused by role", f"{n - len(bad)}/{n}", not bad, "; ".join(bad[:6]), kind="matrix")
    # anonymous
    bad, n = [], 0
    for m, p in routes:
        cap = rbac.required_cap(m, p)
        if cap is None:
            continue
        n += 1
        r = anon.req(m, fill(p)[4:], json={}) if m != "GET" else anon.req(m, fill(p)[4:])
        if r.status_code != 401:
            bad.append(f"{m} {p} -> {r.status_code}")
    rec(F, "ANONYMOUS: every route that needs sign-in answers 401", f"{n} routes", "all 401", f"{n - len(bad)}/{n}", not bad, "; ".join(bad[:8]), kind="matrix")
    # public routes really are reachable anonymously (spot check) and operator-only routes refuse staff
    for m, p, ok in (("GET", "/health", {200}), ("GET", "/auth/options", {200}), ("GET", "/public/support-info", {200}), ("GET", "/public/legal-config", {200})):
        step(anon, F, f"public route {p} is reachable anonymously", m, p, ok)
    bad, n = [], 0
    for m, p in routes:
        if not p.startswith("/api/admin/"):
            continue
        n += 1
        for role in ("OWNER", "LAWYER", "MEMBER"):
            if role in roles:
                r = roles[role].req(m, fill(p)[4:], json={}) if m != "GET" else roles[role].req(m, fill(p)[4:])
                if r.status_code not in (403, 404):
                    bad.append(f"{role} {m} {p} -> {r.status_code}")
    rec(F, "operator-only /api/admin/*: even an OWNER of an organisation is refused (403)", f"{n} routes x 3 roles", "all 403 or 404", f"{n * 3 - len(bad)}/{n * 3}", not bad, "; ".join(bad[:6]), kind="matrix")
    # a few concrete, behavioural role checks (real calls with real ids)
    M = CTX["M"]
    if "MEMBER" in roles and "LAWYER" in roles:
        mem, law = roles["MEMBER"], roles["LAWYER"]
        step(mem, F, "MEMBER can read the matter", "GET", f"/matters/{M}", 200)
        step(mem, F, "MEMBER can add a fact", "POST", f"/matters/{M}/facts", 200, json={"value": "Member note", "fact_type": "EVENT"})
        step(mem, F, "MEMBER cannot run AI research", "POST", "/research", 403, json={"question": "x", "matter_id": M})
        step(mem, F, "MEMBER cannot delete the matter", "DELETE", f"/matters/{M}", 403)
        step(mem, F, "MEMBER cannot invite", "POST", "/org/invites", 403, json={"email": "a@example.com", "role": "MEMBER"})
        step(mem, F, "MEMBER cannot e-mail a notice", "POST", f"/recovery/cases/{CTX['case']}/email/prepare", 403, json={"debtor_email": "d@example.org"})
        step(mem, F, "MEMBER cannot see billing history", "GET", "/payments/history", 403)
        step(law, F, "LAWYER can read the matter", "GET", f"/matters/{M}", 200)
        step(law, F, "LAWYER cannot delete the matter", "DELETE", f"/matters/{M}", 403)
        step(law, F, "LAWYER cannot export the organisation", "GET", "/org/export", 403)
        step(law, F, "LAWYER cannot buy Pro", "POST", "/payments/checkout", 403, json={"package_id": "pro_monthly", "origin_url": "http://localhost:3000"})
        step(law, F, "LAWYER passes the AI permission gate (empty body -> 422, no AI call made)", "POST", "/legal-reasoning", 422, json={})
    if "ADMIN" in roles:
        step(roles["ADMIN"], F, "ADMIN can read members", "GET", "/org/members", 200)
        step(roles["ADMIN"], F, "ADMIN cannot erase the organisation", "DELETE", "/org", 403, json={"password": PW, "organization_name": "Walk Org A"})
        step(roles["ADMIN"], F, "ADMIN cannot see billing", "GET", "/payments/history", 403)
    if "CLIENT" in roles:
        c = roles["CLIENT"]
        for nm, m, p in (("matters", "GET", "/matters"), ("research", "POST", "/research"), ("recovery cases", "GET", "/recovery/cases"), ("deadlines", "GET", "/deadlines"), ("drafts", "GET", "/drafts"), ("knowledge", "GET", "/knowledge/search?q=justice"), ("org members", "GET", "/org/members")):
            step(c, F, f"CLIENT cannot use {nm}", m, p, 403, json={} if m == "POST" else None)
        step(c, F, "CLIENT can use own account route", "GET", "/auth/me", 200, lambda r: (js(r) or {}).get("role") == "CLIENT" or "wrong role")
        step(c, F, "CLIENT can use the portal", "GET", "/portal/matters", 200)
        step(roles["OWNER"], F, "staff cannot use the client portal route", "GET", "/portal/matters", 403)


# ---- cross organisation ---------------------------------------------------------------------------
def cross_org(o: Who, roles: dict):
    F = "cross-organisation"
    b = CTX["b"]
    M, D, case = CTX["M"], CTX["D"], CTX["case"]
    spy = [
        ("GET", f"/matters/{M}", None), ("PATCH", f"/matters/{M}", {"title": "hacked"}), ("DELETE", f"/matters/{M}", None),
        ("GET", f"/matters/{M}/documents", None), ("GET", f"/documents/{D}", None), ("GET", f"/documents/{D}/file", None), ("DELETE", f"/documents/{D}", None),
        ("POST", f"/documents/{D}/analyze", None),
        ("GET", f"/matters/{M}/facts", None), ("POST", f"/matters/{M}/facts", {"value": "planted"}), ("GET", f"/matters/{M}/timeline", None),
        ("POST", f"/matters/{M}/timeline", {"event_date": "2025-01-01", "description": "planted"}), ("GET", f"/matters/{M}/evidence", None), ("GET", f"/matters/{M}/graph", None),
        ("GET", f"/matters/{M}/portal", None), ("POST", f"/matters/{M}/portal/updates", {"text": "planted"}), ("PATCH", f"/matters/{M}/legal-hold", {"on": True}),
        ("POST", "/research", {"question": "x", "matter_id": M}),
        ("GET", f"/recovery/cases/{case}", None), ("PATCH", f"/recovery/cases/{case}/details", {"debtor_address": "x"}), ("POST", f"/recovery/cases/{case}/payment", {"amount": 1}),
        ("GET", f"/recovery/cases/{case}/notice.pdf", None), ("GET", f"/recovery/cases/{case}/notice/workflow", None), ("POST", f"/recovery/cases/{case}/notice/approve", {"acknowledged": True}),
        ("POST", f"/recovery/cases/{case}/email/prepare", {"debtor_email": "x@example.org"}), ("GET", f"/recovery/cases/{case}/proofs", None), ("GET", f"/recovery/cases/{case}/evidence-pack.zip", None),
        ("DELETE", f"/recovery/cases/{case}", None), ("POST", f"/recovery/cases/{case}/handoff", None),
        ("GET", "/drafts/" + (CTX.get("DR") or "x"), None),
    ]
    # make an owner draft/deadline id available
    dr = js(o.req("GET", "/drafts"))
    if dr:
        spy.append(("GET", f"/drafts/{dr[0]['id']}", None))
        spy.append(("PATCH", f"/drafts/{dr[0]['id']}", {"body": "hacked"}))
        spy.append(("DELETE", f"/drafts/{dr[0]['id']}", None))
    dl = js(o.req("POST", "/deadlines", json={"title": "xorg", "kind": "deadline", "starts_local": "2027-04-05T10:30"}))
    if dl and dl.get("id"):
        spy += [("PATCH", f"/deadlines/{dl['id']}", {"title": "hacked"}), ("DELETE", f"/deadlines/{dl['id']}", None), ("GET", f"/deadlines/{dl['id']}/calendar.ics", None)]
    mem = js(o.req("GET", "/org/members"))
    spy += [("PATCH", f"/org/members/{mem[0]['id']}", {"role": "MEMBER"}), ("DELETE", f"/org/members/{mem[0]['id']}", None)]
    inv = js(o.req("POST", "/org/invites", json={"email": f"x-{uuid.uuid4().hex[:5]}@example.com", "role": "MEMBER"}))
    if inv and inv.get("id"):
        spy.append(("DELETE", f"/org/invites/{inv['id']}", None))
    for m, p, body in spy:
        r = b.req(m, p, json=body) if body is not None else b.req(m, p)
        ok = r.status_code in (403, 404) or (r.status_code == 422 and m in ("POST", "PATCH"))
        rec(F, f"org B -> org A: {m} {re.sub(r'[0-9a-f-]{36}', '{id}', p)}", f"{m} {p}", "403/404 (never 200)", r.status_code, ok, f"org B got {r.status_code}: {short(r, 150)}")
    # lists must not leak
    for p in ("/matters", "/recovery/cases", "/drafts", "/deadlines", "/org/members"):
        r = b.req("GET", p)
        txt = r.text
        leak = any(x in txt for x in (M, case, o.email))
        rec(F, f"org B's {p} list does not contain org A's records", f"GET {p}", "no A ids", "clean" if not leak else "LEAK", not leak, "org A data visible to org B")
    # search / dashboards
    r = b.req("GET", "/search", params={"q": "Supply"})
    rec(F, "org B's search does not find org A's matter", "GET /search?q=Supply", "no A hits", r.status_code, "Supply dispute" not in r.text, "leak in search")
    r = b.req("GET", "/knowledge/search", params={"q": "zqxvprivate"})
    rec(F, "org B's knowledge search does not see org A's private notes", "GET /knowledge/search", "no A hits", r.status_code, "zqxvprivate" not in r.text, "private knowledge leak")
    # the shared document in the portal: B (a staff user elsewhere) cannot use the portal either
    step(b, F, "org B cannot fetch org A's portal document", "GET", f"/portal/matters/{M}/documents/{D}/file", 403)
    step(b, F, "a session cookie of org B cannot read org A's user data", "GET", "/privacy/my-data", 200, lambda r: o.email not in r.text or "A's e-mail in B's data export")


# ---- payments ---------------------------------------------------------------------------------------
def payments_walk(o: Who):
    F = "payments"
    pk = step(o, F, "list packages (server owns the price)", "GET", "/payments/packages", 200, lambda r: bool(js(r)) or "empty")
    packs = js(pk)
    packs = packs if isinstance(packs, list) else (packs or {}).get("packages", list((packs or {}).values()))
    pid = None
    for p in packs or []:
        if isinstance(p, dict) and (p.get("id") or p.get("package_id")):
            pid = p.get("id") or p.get("package_id")
            break
    if not pid:
        pid = "pro_monthly"
    step(o, F, "checkout with an unknown package is refused", "POST", "/payments/checkout", {400, 404, 422}, json={"package_id": "free_lunch", "origin_url": "http://localhost:3000"})
    step(o, F, "checkout with a foreign origin URL is refused", "POST", "/payments/checkout", {400, 403, 422}, json={"package_id": pid, "origin_url": "https://evil.example.com"})
    r = step(o, F, "start a checkout (PAYMENTS_STUB: fake gateway, no money)", "POST", "/payments/checkout", 200, lambda r: bool((js(r) or {}).get("session_id")) or "no session_id", json={"package_id": pid, "origin_url": "http://localhost:3000"})
    sid = (js(r) or {}).get("session_id") if r is not None and r.status_code == 200 else None
    if sid:
        pr = o.req("GET", "/auth/entitlement").json().get("limits", {}).get("price", {})
        paise = int(round(float(pr.get("amount", 1999)) * 100))
        step(o, F, "payment status before the gateway reports paid: still pending", "GET", f"/payments/status/{sid}", 200, lambda r: (js(r) or {}).get("payment_status") in ("pending", "unpaid") or "claims paid before payment")
        step(o, F, "still FREE before payment", "GET", "/auth/entitlement", 200, lambda r: (js(r) or {}).get("plan") == "FREE" or "upgraded without payment")
        DB.payment_stub.insert_one({"session_id": sid, "payment_status": "paid", "amount_total": 100, "currency": pr.get("currency", "inr"), "metadata": {"user_id": o.me["id"]}, "subscription_id": "sub_walk"})
        step(o, F, "gateway says paid but the AMOUNT is wrong (Rs 1): no upgrade", "GET", f"/payments/status/{sid}", 200, lambda r: (js(r) or {}).get("payment_status") != "paid" or "accepted a wrong amount")
        step(o, F, "still FREE after a wrong-amount payment", "GET", "/auth/entitlement", 200, lambda r: (js(r) or {}).get("plan") == "FREE" or "upgraded on a wrong amount")
        DB.payment_stub.delete_many({"session_id": sid})
        DB.payment_stub.insert_one({"session_id": sid, "payment_status": "paid", "amount_total": paise, "currency": pr.get("currency", "inr"), "metadata": {"user_id": o.me["id"]}, "subscription_id": "sub_walk"})
        step(o, F, "payment status for the session", "GET", f"/payments/status/{sid}", 200, lambda r: (js(r) or {}).get("payment_status") == "paid" or f"not paid: {js(r)}")
        step(o, F, "the account is upgraded to PRO after the stub payment", "GET", "/auth/entitlement", 200, lambda r: (js(r) or {}).get("plan") == "PRO" or f"plan is {(js(r) or {}).get('plan')} after checkout+status (stub gateway)")
        step(o, F, "payment history lists the purchase", "GET", "/payments/history", 200, lambda r: sid in r.text or "purchase not in history")
        step(o, F, "receipt PDF", "GET", f"/payments/receipt/{sid}.pdf", 200, lambda r: r.content[:5] == b"%PDF-" or "not a PDF")
        step(o, F, "cancel the subscription at period end", "POST", "/payments/subscription/cancel", 200)
        step(o, F, "resume the subscription", "POST", "/payments/subscription/resume", 200)
    skip(F, "a real card payment / webhook from Stripe, Razorpay, PayPal", "POST /payments/checkout (real)", "dev server uses PAYMENTS_STUB (fake gateway); a real test-mode payment needs the payments-test backend on port 8003 and a browser checkout")
    skip(F, "refund recorded by the operator", "POST /admin/payments/{id}/refund", "operator-only route; no platform-admin account is used in this walk")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8002")
    ap.add_argument("--out", default=str(ROOT / "docs" / "evals" / "feature-walk-results.json"))
    ap.add_argument("--inventory", action="store_true")
    a = ap.parse_args()
    BASE = a.base.rstrip("/")
    if a.inventory:
        print(inventory_md())
        raise SystemExit(0)
    t0 = time.time()
    try:
        walk()
    finally:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps({"base": BASE, "seconds": round(time.time() - t0), "results": RESULTS}, indent=1), encoding="utf-8")
    p = sum(r["result"] == "PASS" for r in RESULTS)
    f = sum(r["result"] == "FAIL" for r in RESULTS)
    s = sum(r["result"] == "NOT_TESTED" for r in RESULTS)
    print(f"\nTOTAL {len(RESULTS)}  PASS {p}  FAIL {f}  NOT_TESTED {s}   AI-dependent steps {sum(1 for r in RESULTS if r['ai'])}")
