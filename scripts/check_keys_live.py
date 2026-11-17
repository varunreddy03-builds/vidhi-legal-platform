"""Live key check for every provider key in backend/.env (106 numbered checks).

Run:  C:\\vidhi-tools\\venv2\\Scripts\\python.exe scripts\\check_keys_live.py
Writes docs/evals/live-keys-2026-10-23.json and docs/VIDHI_LIVE_KEY_CHECKS.md.

Safety: keys are read at run time from backend/.env, sent only to their own provider, and never printed, logged or
written. Every string that is stored or printed goes through clean(), which replaces any key value with ***.
No email, SMS or call is ever sent. Stripe is TEST mode only: the whole Stripe section aborts if any livemode true appears.
Sequential, 30 s timeout, short pause between calls. A 429 is recorded as 'rate limited' (expected), never as an invalid key.
"""
import json
import re
import sys
import time
from collections import OrderedDict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / "backend" / ".env"
OUT_JSON = ROOT / "docs" / "evals" / "live-keys-2026-10-23.json"
OUT_MD = ROOT / "docs" / "VIDHI_LIVE_KEY_CHECKS.md"
PAUSE = 0.7
TIMEOUT = 30.0
GEMINI_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
GROQ_FULL, GROQ_FREE = "openai/gpt-oss-120b", "openai/gpt-oss-20b"
PROMPT = "Reply with the single word: ok"


def load_env(path):
    env = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        env[k.strip()] = v
    return env


ENVV = load_env(ENV)
SECRETS = [v for v in ENVV.values() if len(v) >= 6]


def clean(s, n=170):
    s = str(s)
    for sec in sorted(SECRETS, key=len, reverse=True):
        s = s.replace(sec, "***")
    s = re.sub(r"(sk|rk|pk)_(test|live)_[A-Za-z0-9]+", "***", s)
    s = re.sub(r"AIza[0-9A-Za-z_\-]{10,}", "***", s)
    s = re.sub(r"gsk_[0-9A-Za-z]{10,}", "***", s)
    s = re.sub(r"sk-or-[0-9A-Za-z\-_]{10,}", "***", s)
    s = re.sub(r"re_[0-9A-Za-z_]{10,}", "***", s)
    s = re.sub(r"\s+", " ", s)
    return s[:n]


ROWS = []
CLIENT = httpx.Client(timeout=TIMEOUT)


class Abort(Exception):
    pass


def jbody(r):
    try:
        return r.json()
    except Exception:
        return None


def errmsg(r):
    b = jbody(r)
    if isinstance(b, dict):
        e = b.get("error", b.get("detail", b.get("message", b)))
        if isinstance(e, dict):
            e = e.get("message") or e.get("code") or e
        return clean(e)
    return clean(r.text[:150])


def default_judge(r):
    c = r.status_code
    if 200 <= c < 300:
        return "pass", "accepted"
    if c == 429:
        return "expected", "rate limited (429); not an invalid key"
    if c in (401, 403):
        return "fail", "key rejected: " + errmsg(r)
    return "fail", f"unexpected status: {errmsg(r)}"


def check(provider, what, fn, judge=default_judge, prereq=None):
    """fn() -> httpx.Response. judge(resp) -> (state, reason). Each call = one numbered row."""
    n = len(ROWS) + 1
    row = OrderedDict(n=n, provider=provider, test=what, http=None, ms=None, state="skipped", reason="")
    if prereq:
        row["reason"] = prereq
        ROWS.append(row)
        print(f"{n:3d} {provider:10s} SKIP  {what}")
        return None
    t = time.perf_counter()
    resp = None
    try:
        resp = fn()
        row["ms"] = round((time.perf_counter() - t) * 1000)
        row["http"] = resp.status_code
        row["state"], row["reason"] = judge(resp)
    except Abort:
        raise
    except Exception as e:  # network error, timeout, judge bug
        row["ms"] = round((time.perf_counter() - t) * 1000)
        row["state"], row["reason"] = "fail", f"{type(e).__name__}: {clean(e, 100)}"
    row["reason"] = clean(row["reason"])
    ROWS.append(row)
    print(f"{n:3d} {provider:10s} {row['state'].upper():8s} {str(row['http']):4s} {str(row['ms']):>6s}ms  {what}")
    time.sleep(PAUSE)
    return resp


def need(name):
    return None if ENVV.get(name) else f"{name} not set in backend/.env"


# ---------------------------------------------------------------- Gemini (25)
def gemini():
    key = ENVV.get("GEMINI_API_KEY")
    pre = need("GEMINI_API_KEY")
    base = "https://generativelanguage.googleapis.com/v1beta"
    H = {"x-goog-api-key": key or ""}

    def gen(model, body):
        return lambda: CLIENT.post(f"{base}/models/{model}:generateContent", headers=H, json=body)

    def okjudge(r):
        s, why = default_judge(r)
        if s != "pass":
            return s, why
        try:
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return "fail", "200 but no text in reply"
        return ("pass", "replied: " + clean(txt.strip(), 20)) if "ok" in txt.lower() else ("fail", "reply was not 'ok'")

    def listjudge(r):
        s, why = default_judge(r)
        if s == "pass":
            names = [m.get("name", "") for m in (jbody(r) or {}).get("models", [])]
            have = [m for m in GEMINI_MODELS if f"models/{m}" in names]
            return "pass", f"{len(names)} models; app defaults present: {have or 'none'}"
        return s, why

    check("gemini", "list models (auth)", lambda: CLIENT.get(f"{base}/models?pageSize=200", headers=H), listjudge, pre)
    for m in GEMINI_MODELS:
        check("gemini", f"get model {m}", lambda m=m: CLIENT.get(f"{base}/models/{m}", headers=H), prereq=pre)
    body = {"contents": [{"parts": [{"text": PROMPT}]}], "generationConfig": {"maxOutputTokens": 256}}
    for m in GEMINI_MODELS:
        for i in range(1, 11):
            check("gemini", f"tiny call {m} #{i}", gen(m, body), okjudge, pre)

    jb = {"contents": [{"parts": [{"text": 'Return JSON {"ok": true}'}]}],
          "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 256}}

    def jsonjudge(r):
        s, why = default_judge(r)
        if s != "pass":
            return s, why
        try:
            json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            return "pass", "valid JSON returned in JSON mode"
        except Exception:
            return "fail", "JSON mode reply was not valid JSON"

    check("gemini", "JSON-mode call", gen(GEMINI_MODELS[0], jb), jsonjudge, pre)

    huge = {"contents": [{"parts": [{"text": "a " * 3_000_000}]}], "generationConfig": {"maxOutputTokens": 1}}

    def bigjudge(r):
        if 400 <= r.status_code < 500 and r.status_code not in (401, 403, 429):
            return "pass", f"refused cleanly: {errmsg(r)}"
        if r.status_code == 429:
            return "expected", "rate limited (429)"
        if r.status_code in (401, 403):
            return "fail", "key rejected: " + errmsg(r)
        return "fail", f"not refused cleanly (status {r.status_code})"

    check("gemini", "over-long input (~3M tokens) must be refused", gen(GEMINI_MODELS[0], huge), bigjudge, pre)


# ---------------------------------------------------------------- Groq (20)
def groq():
    key = ENVV.get("GROQ_API_KEY")
    pre = need("GROQ_API_KEY")
    base = "https://api.groq.com/openai/v1"
    H = {"Authorization": f"Bearer {key}"}

    def chat(model, extra=None):
        body = {"model": model, "messages": [{"role": "user", "content": PROMPT}], "max_tokens": 200,
                "reasoning_effort": "low"}
        body.update(extra or {})
        return lambda: CLIENT.post(f"{base}/chat/completions", headers=H, json=body)

    def okjudge(r):
        s, why = default_judge(r)
        if s != "pass":
            return s, why
        try:
            txt = r.json()["choices"][0]["message"]["content"] or ""
        except Exception:
            return "fail", "200 but no content"
        return ("pass", "replied: " + clean(txt.strip(), 20)) if "ok" in txt.lower() else ("fail", "reply was not 'ok'")

    def listjudge(r):
        s, why = default_judge(r)
        if s == "pass":
            ids = [m.get("id") for m in (jbody(r) or {}).get("data", [])]
            return "pass", f"{len(ids)} models; defaults present: {[m for m in (GROQ_FULL, GROQ_FREE) if m in ids]}"
        return s, why

    def bad4xx(r):
        if r.status_code in (400, 404):
            return "pass", f"clean {r.status_code}: {errmsg(r)}"
        if r.status_code == 429:
            return "expected", "rate limited (429)"
        return "fail", f"expected a clean 4xx, got {r.status_code}"

    check("groq", "list models (auth)", lambda: CLIENT.get(f"{base}/models", headers=H), listjudge, pre)
    check("groq", f"get model {GROQ_FULL}", lambda: CLIENT.get(f"{base}/models/{GROQ_FULL}", headers=H), prereq=pre)
    for i in range(1, 9):
        check("groq", f"tiny chat {GROQ_FULL} #{i}", chat(GROQ_FULL), okjudge, pre)
    for i in range(1, 8):
        check("groq", f"tiny chat {GROQ_FREE} #{i}", chat(GROQ_FREE), okjudge, pre)
    check("groq", "bad model name must return clean 4xx", chat("no-such-model-xyz"), bad4xx, pre)
    check("groq", "unknown model lookup must return clean 4xx",
          lambda: CLIENT.get(f"{base}/models/no-such-model-xyz", headers=H), bad4xx, pre)

    def jsonjudge(r):
        s, why = default_judge(r)
        if s != "pass":
            return s, why
        try:
            json.loads(r.json()["choices"][0]["message"]["content"])
            return "pass", "valid JSON in JSON mode"
        except Exception:
            return "fail", "JSON mode reply was not valid JSON"

    check("groq", "JSON-mode chat", chat(GROQ_FULL, {"messages": [{"role": "user", "content": 'Return JSON {"ok": true}'}],
                                                     "response_format": {"type": "json_object"}}), jsonjudge, pre)
    check("groq", "list models again (latency repeat)", lambda: CLIENT.get(f"{base}/models", headers=H), listjudge, pre)


# ---------------------------------------------------------------- OpenRouter (10)
def openrouter():
    key = ENVV.get("OPENROUTER_API_KEY")
    pre = need("OPENROUTER_API_KEY")
    base = "https://openrouter.ai/api/v1"
    H = {"Authorization": f"Bearer {key}"}
    state = {"free": None}

    def keyjudge(r):
        s, why = default_judge(r)
        if s == "pass":
            d = (jbody(r) or {}).get("data", {})
            return "pass", f"key valid; is_free_tier={d.get('is_free_tier')}; limit={'set' if d.get('limit') is not None else 'none'}"
        return s, why

    def modjudge(r):
        s, why = default_judge(r)
        if s == "pass":
            data = (jbody(r) or {}).get("data", [])
            free = [m["id"] for m in data if str(m.get("id", "")).endswith(":free")]
            state["free"] = free[0] if free else None
            return "pass", f"{len(data)} models, {len(free)} free; picked free model: {state['free']}"
        return s, why

    def credjudge(r):
        if r.status_code in (401, 403):
            return "expected", "key valid but /credits needs a management key: " + errmsg(r)
        s, why = default_judge(r)
        if s == "pass":
            d = (jbody(r) or {}).get("data", {})
            rem = (d.get("total_credits") or 0) - (d.get("total_usage") or 0)
            return "pass", f"credits fetched; remaining > 0: {rem > 0}"
        return s, why

    check("openrouter", "auth: key info", lambda: CLIENT.get(f"{base}/auth/key", headers=H), keyjudge, pre)
    check("openrouter", "credit info", lambda: CLIENT.get(f"{base}/credits", headers=H), credjudge, pre)
    check("openrouter", "list models", lambda: CLIENT.get(f"{base}/models", headers=H), modjudge, pre)

    def chat(model):
        return lambda: CLIENT.post(f"{base}/chat/completions", headers=H, json={
            "model": model, "max_tokens": 50, "messages": [{"role": "user", "content": PROMPT}]})

    def freejudge(r):
        if r.status_code in (404, 502, 503):
            return "expected", f"free model unavailable upstream ({r.status_code}): {errmsg(r)}"
        s, why = default_judge(r)
        if s != "pass":
            return s, why
        try:
            msg = r.json()["choices"][0]["message"]
            txt = (msg.get("content") or "") + (msg.get("reasoning") or "")
        except Exception:
            return "fail", "200 but no content"
        return ("pass", "free model replied") if txt.strip() else ("fail", "empty reply")

    for i in range(1, 4):
        check("openrouter", f"tiny call, FREE model #{i}", lambda: chat(state["free"] or "none")(),
              freejudge, pre or (None if state["free"] else "no free model found in list"))

    def paidjudge(r):
        if r.status_code == 402:
            return "expected", "no credit (402), as allowed: " + errmsg(r)
        return default_judge(r)

    check("openrouter", "paid model call (402 no-credit is expected)", chat("openai/gpt-4o-mini"), paidjudge, pre)
    check("openrouter", "bad model must return clean 4xx", chat("no/such-model-xyz"),
          lambda r: ("pass", f"clean {r.status_code}: {errmsg(r)}") if r.status_code in (400, 404)
          else ("expected", "rate limited (429)") if r.status_code == 429 else ("fail", f"got {r.status_code}"), pre)
    check("openrouter", "list models for this user", lambda: CLIENT.get(f"{base}/models/user", headers=H),
          lambda r: ("expected", f"endpoint not available ({r.status_code})") if r.status_code == 404 else default_judge(r), pre)
    check("openrouter", "key info again (latency repeat)", lambda: CLIENT.get(f"{base}/auth/key", headers=H), keyjudge, pre)


# ---------------------------------------------------------------- Stripe TEST (20)
def stripe():
    key = ENVV.get("STRIPE_SECRET_KEY")
    pre = need("STRIPE_SECRET_KEY")
    base = "https://api.stripe.com/v1"
    H = {"Authorization": f"Bearer {key}"}
    created_customers, created_sessions = [], []

    def lv(obj):
        """Abort on any livemode true anywhere in the object (one level of list items too)."""
        if isinstance(obj, dict):
            if obj.get("livemode") is True:
                raise Abort("livemode true seen")
            for it in obj.get("data", []) if isinstance(obj.get("data"), list) else []:
                lv(it)

    def wrap(judge_ok):
        def j(r):
            b = jbody(r)
            lv(b)
            s, why = default_judge(r)
            if s == "pass":
                return judge_ok(b)
            return s, why
        return j

    kind = "missing"
    if key:
        kind = key[:8] if key.startswith(("sk_test_", "rk_test_")) else ("LIVE" if key.startswith(("sk_live_", "rk_live_", "pk_live")) else "unknown")
    if kind in ("LIVE", "unknown"):
        pre = f"ABORTED: key is not a test key (kind={kind}); no Stripe call was made"
    st = {"aborted": pre}
    try:
        check("stripe", "key kind is TEST (prefix check, no call)", lambda: type("R", (), {"status_code": 200})(),
              lambda r: ("pass", f"key prefix {kind}") if kind.endswith("test_") else ("fail", f"key kind {kind}"), None if key else pre)
        # fix the status/ms for the local check
        ROWS[-1]["http"], ROWS[-1]["ms"] = None, 0
        if kind.endswith("test_") is False:
            raise Abort("not a test key")
        check("stripe", "retrieve balance (auth, livemode false)", lambda: CLIENT.get(f"{base}/balance", headers=H),
              wrap(lambda b: ("pass", f"livemode={b.get('livemode')}") if b.get("livemode") is False else ("fail", "livemode missing")))
        check("stripe", "retrieve account", lambda: CLIENT.get(f"{base}/account", headers=H),
              lambda r: ("expected", "restricted key cannot read /account") if r.status_code in (401, 403) and "permission" in r.text.lower() else wrap(lambda b: ("pass", "account readable"))(r))
        for what in ("products", "prices", "customers", "charges"):
            check("stripe", f"list {what} (read-only)", lambda w=what: CLIENT.get(f"{base}/{w}?limit=3", headers=H),
                  wrap(lambda b, w=what: ("pass", f"{len(b.get('data', []))} item(s), all livemode false")))
        # 3 customers: create, retrieve, delete
        for i in range(1, 4):
            r = check("stripe", f"create test customer #{i}",
                      lambda i=i: CLIENT.post(f"{base}/customers", headers=H, data={"name": f"VIDHI key check {i}", "metadata[purpose]": "vidhi_key_check"}),
                      wrap(lambda b: ("pass", "created, livemode false") if b.get("livemode") is False else ("fail", "livemode not false")))
            cid = (jbody(r) or {}).get("id") if r is not None and r.status_code == 200 else None
            if cid:
                created_customers.append(cid)
            check("stripe", f"retrieve test customer #{i}", lambda c=cid: CLIENT.get(f"{base}/customers/{c}", headers=H),
                  wrap(lambda b: ("pass", "retrieved, livemode false")), None if cid else "create failed")
            check("stripe", f"delete test customer #{i}", lambda c=cid: CLIENT.delete(f"{base}/customers/{c}", headers=H),
                  wrap(lambda b: ("pass", "deleted") if b.get("deleted") else ("fail", "not deleted")), None if cid else "create failed")
            if cid and ROWS[-1]["state"] == "pass":
                created_customers.remove(cid)
        # 3 checkout sessions: create, expire
        for i in range(1, 4):
            r = check("stripe", f"create Checkout session #{i} (INR 50 test)",
                      lambda: CLIENT.post(f"{base}/checkout/sessions", headers=H, data={
                          "mode": "payment", "success_url": "https://example.com/ok", "cancel_url": "https://example.com/cancel",
                          "line_items[0][quantity]": "1", "line_items[0][price_data][currency]": "inr",
                          "line_items[0][price_data][unit_amount]": "5000",
                          "line_items[0][price_data][product_data][name]": "VIDHI key check"}),
                      wrap(lambda b: ("pass", "created, livemode false") if b.get("livemode") is False else ("fail", "livemode not false")))
            sid = (jbody(r) or {}).get("id") if r is not None and r.status_code == 200 else None
            if sid:
                created_sessions.append(sid)
            check("stripe", f"expire Checkout session #{i}", lambda s=sid: CLIENT.post(f"{base}/checkout/sessions/{s}/expire", headers=H),
                  wrap(lambda b: ("pass", f"status={b.get('status')}") if b.get("status") == "expired" else ("fail", f"status={b.get('status')}")),
                  None if sid else "create failed")
            if sid and ROWS[-1]["state"] == "pass":
                created_sessions.remove(sid)
        check("stripe", "retrieve balance again (latency repeat)", lambda: CLIENT.get(f"{base}/balance", headers=H),
              wrap(lambda b: ("pass", "livemode false")))
    except Abort as a:
        st["aborted"] = str(a)
        print("STRIPE ABORTED:", a)
    finally:
        # clean up anything left behind (test mode only)
        for c in created_customers:
            try:
                CLIENT.delete(f"{base}/customers/{c}", headers=H)
            except Exception:
                pass
        for s in created_sessions:
            try:
                CLIENT.post(f"{base}/checkout/sessions/{s}/expire", headers=H)
            except Exception:
                pass
    if st["aborted"]:
        skipped_reason = "SECTION ABORTED: " + clean(st["aborted"])
        have = sum(1 for r in ROWS if r["provider"] == "stripe")
        while have < 20:
            check("stripe", f"(not run) check {have + 1}", lambda: None, prereq=skipped_reason)
            have += 1
        if have and ROWS and ROWS[-1]["provider"] == "stripe":
            pass
    return st


# ---------------------------------------------------------------- Resend (8, never sends mail)
def resend():
    key = ENVV.get("RESEND_API_KEY")
    pre = need("RESEND_API_KEY")
    base = "https://api.resend.com"
    H = {"Authorization": f"Bearer {key}"}

    def j(r):
        if r.status_code == 401 and "restricted" in r.text.lower():
            return "pass", "valid send-only key (401 restricted_api_key on a read endpoint)"
        if r.status_code in (400, 401, 403) and "invalid" in r.text.lower():
            return "fail", "key invalid: " + errmsg(r)
        s, why = default_judge(r)
        if s == "pass":
            d = jbody(r) or {}
            return "pass", f"readable; {len(d.get('data', [])) if isinstance(d.get('data'), list) else 'ok'} item(s) (full-access key)"
        return s, why

    for p in ("domains", "api-keys", "audiences", "broadcasts", "emails", "domains", "api-keys", "audiences"):
        check("resend", f"GET /{p} (read-only; no email is sent)", lambda p=p: CLIENT.get(f"{base}/{p}", headers=H), j, pre)


# ---------------------------------------------------------------- Twilio (10, read-only)
def twilio():
    sid, tok = ENVV.get("TWILIO_ACCOUNT_SID"), ENVV.get("TWILIO_AUTH_TOKEN")
    pre = need("TWILIO_ACCOUNT_SID") or need("TWILIO_AUTH_TOKEN")
    base = f"https://api.twilio.com/2010-04-01/Accounts/{sid}"
    auth = (sid or "", tok or "")

    def get(path):
        return lambda: CLIENT.get(f"{base}{path}", auth=auth)

    def acc(r):
        s, why = default_judge(r)
        if s == "pass":
            d = jbody(r) or {}
            return "pass", f"account status={d.get('status')}, type={d.get('type')}"
        return s, why

    def lst(key):
        def j(r):
            s, why = default_judge(r)
            if s == "pass":
                d = jbody(r) or {}
                return "pass", f"{len(d.get(key, []))} item(s) on page"
            return s, why
        return j

    def bal(r):
        s, why = default_judge(r)
        if s == "pass":
            return "pass", "balance returned, currency " + str((jbody(r) or {}).get("currency"))
        return s, why

    check("twilio", "fetch account (auth)", get(".json"), acc, pre)
    check("twilio", "balance", get("/Balance.json"), bal, pre)
    check("twilio", "incoming phone numbers", get("/IncomingPhoneNumbers.json?PageSize=5"), lst("incoming_phone_numbers"), pre)
    check("twilio", "usage records", get("/Usage/Records.json?PageSize=5"), lst("usage_records"), pre)
    check("twilio", "usage records today", get("/Usage/Records/Today.json?PageSize=5"), lst("usage_records"), pre)
    check("twilio", "outgoing caller ids", get("/OutgoingCallerIds.json?PageSize=5"), lst("outgoing_caller_ids"), pre)
    check("twilio", "applications", get("/Applications.json?PageSize=5"), lst("applications"), pre)
    check("twilio", "list messages (read-only, none sent)", get("/Messages.json?PageSize=1"), lst("messages"), pre)
    check("twilio", "list calls (read-only, none made)", get("/Calls.json?PageSize=1"), lst("calls"), pre)
    check("twilio", "fetch account again (latency repeat)", get(".json"), acc, pre)


# ---------------------------------------------------------------- ElevenLabs (8)
def eleven():
    key = ENVV.get("ELEVENLABS_API_KEY")
    pre = need("ELEVENLABS_API_KEY")
    base = "https://api.elevenlabs.io"
    H = {"xi-api-key": key or ""}

    def j(r):
        if r.status_code == 401:
            b = jbody(r) or {}
            d = b.get("detail") if isinstance(b, dict) else None
            status = d.get("status") if isinstance(d, dict) else None
            if status == "missing_permissions":
                return "expected", "key is valid but restricted (missing permission): " + errmsg(r)
            if status in ("detected_unusual_activity",):
                return "fail", "account blocked: " + errmsg(r)
            return "fail", f"key rejected ({status or 'invalid'}): {errmsg(r)}"
        s, why = default_judge(r)
        if s == "pass":
            b = jbody(r)
            n = len(b) if isinstance(b, list) else len(b.get("voices", b.get("history", []))) if isinstance(b, dict) and ("voices" in b or "history" in b) else None
            return "pass", f"accepted{'; ' + str(n) + ' item(s)' if n is not None else ''}"
        return s, why

    for what, path in (("user info", "/v1/user"), ("subscription", "/v1/user/subscription"), ("models", "/v1/models"),
                       ("voices", "/v1/voices"), ("voices v2", "/v2/voices?page_size=5"), ("history", "/v1/history?page_size=1"),
                       ("default voice settings", "/v1/voices/settings/default"), ("user info again (latency repeat)", "/v1/user")):
        check("elevenlabs", what, lambda p=path: CLIENT.get(base + p, headers=H), j, pre)


# ---------------------------------------------------------------- Ollama cloud (5, tags only)
def ollama():
    key = ENVV.get("OLLAMA_API_KEY")
    pre = need("OLLAMA_API_KEY")
    H = {"Authorization": f"Bearer {key}"}

    def tags(r):
        s, why = default_judge(r)
        if s == "pass":
            return "pass", f"{len((jbody(r) or {}).get('models', []))} model(s) listed"
        return s, why

    for i in range(1, 4):
        check("ollama", f"GET /api/tags with key #{i}", lambda: CLIENT.get("https://ollama.com/api/tags", headers=H), tags, pre)
    check("ollama", "GET /api/tags without key (public listing control)", lambda: CLIENT.get("https://ollama.com/api/tags"),
          lambda r: ("pass", "public listing works without a key") if r.status_code == 200 else ("expected", f"needs auth ({r.status_code})"))
    check("ollama", "GET /api/version", lambda: CLIENT.get("https://ollama.com/api/version", headers=H),
          lambda r: ("expected", f"endpoint not offered on cloud ({r.status_code})") if r.status_code in (404, 405) else default_judge(r), pre)


def summarize():
    prov = OrderedDict()
    for r in ROWS:
        p = prov.setdefault(r["provider"], dict(total=0, passed=0, failed=0, expected=0, skipped=0))
        p["total"] += 1
        p[{"pass": "passed", "fail": "failed", "expected": "expected", "skipped": "skipped"}[r["state"]]] += 1
    tot = dict(total=0, passed=0, failed=0, expected=0, skipped=0)
    for p in prov.values():
        for k in tot:
            tot[k] += p[k]
    return prov, tot


def lat(provider):
    ms = sorted(r["ms"] for r in ROWS if r["provider"] == provider and r["ms"] and r["http"])
    if not ms:
        return "n/a"
    return f"median {ms[len(ms) // 2]} ms, max {ms[-1]} ms"


def main():
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    stripe_state = {}
    for fn in (gemini, groq, openrouter, stripe, resend, twilio, eleven, ollama):
        try:
            r = fn()
            if fn is stripe:
                stripe_state = r
        except Exception as e:
            print(f"section {fn.__name__} crashed: {type(e).__name__}: {clean(e)}")
            ROWS.append(OrderedDict(n=len(ROWS) + 1, provider=fn.__name__, test="section crashed", http=None, ms=None,
                                    state="fail", reason=f"{type(e).__name__}: {clean(e, 100)}"))
    prov, tot = summarize()
    rl = [r["n"] for r in ROWS if r["http"] == 429]
    out = OrderedDict(date="2026-10-23", started=started, secrets_printed="never; all values masked as ***",
                      summary=tot, per_provider=prov, rate_limited_check_numbers=rl,
                      stripe_aborted=bool(stripe_state.get("aborted")) if stripe_state else None, checks=ROWS)
    text = clean(json.dumps(out, indent=1, ensure_ascii=False), 10**7)
    OUT_JSON.write_text(text, encoding="utf-8")

    md = ["# VIDHI live key checks - 2026-10-23", "",
          "Generated by `scripts/check_keys_live.py`. No key value appears anywhere; no email, SMS or call was sent; Stripe used TEST mode only.", "",
          "| Provider | Checks | Passed | Failed | Expected-fail | Skipped | Latency |", "|---|---|---|---|---|---|---|"]
    for p, c in prov.items():
        md.append(f"| {p} | {c['total']} | {c['passed']} | {c['failed']} | {c['expected']} | {c['skipped']} | {lat(p)} |")
    md.append(f"| **TOTAL** | **{tot['total']}** | **{tot['passed']}** | **{tot['failed']}** | **{tot['expected']}** | **{tot['skipped']}** | |")
    md += ["", "## Failures and expected failures", ""]
    for r in ROWS:
        if r["state"] in ("fail", "expected"):
            md.append(f"- #{r['n']} {r['provider']} - {r['test']}: {r['state']} (HTTP {r['http']}) - {r['reason']}")
    if not any(r["state"] in ("fail", "expected") for r in ROWS):
        md.append("- none")
    md += ["", f"Rate-limited (429) checks: {rl or 'none'}.", "", "Full per-check rows: `docs/evals/live-keys-2026-10-23.json`."]
    OUT_MD.write_text(clean("\n".join(md), 10**6).replace(" | ", " | ") if False else "\n".join(clean(l, 400) if not l.startswith("|") else l for l in md), encoding="utf-8")

    print("\n=== COUNTS ===")
    print(f"{'provider':12s}{'total':>6s}{'pass':>6s}{'fail':>6s}{'expect':>7s}{'skip':>6s}")
    for p, c in prov.items():
        print(f"{p:12s}{c['total']:6d}{c['passed']:6d}{c['failed']:6d}{c['expected']:7d}{c['skipped']:6d}")
    print(f"{'TOTAL':12s}{tot['total']:6d}{tot['passed']:6d}{tot['failed']:6d}{tot['expected']:7d}{tot['skipped']:6d}")


if __name__ == "__main__":
    main()
