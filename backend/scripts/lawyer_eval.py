"""Run the lawyer-checked set (backend/evals/lawyer_set.jsonl) through VIDHI and write a dated, scored report under docs/evals/ (an old report is never overwritten).

  python scripts/lawyer_eval.py --check                       only read and check the file: how many cases, what is wrong with it
  python scripts/lawyer_eval.py --offline --standin echo      run it offline with the scripted stand-in (no AI, no cost, nothing leaves this computer)
  python scripts/lawyer_eval.py --live --db vidhi_live_eval --label gemini            PLAN ONLY: how many AI calls, the estimated cost, the cap. Nothing is run or spent.
  python scripts/lawyer_eval.py --live --db vidhi_live_eval --label gemini --yes-spend   make the real, paid calls (only after the owner has said "run")

OFFLINE uses an in-process copy of the server on a throwaway database with the scripted stand-in model (AI_STUB), so no port and no key are needed. The stand-in, chosen with --standin, is
  echo     answers with the lawyer's own answer and names the lawyer's source (a model that is right and cites the right source)
  wrong    answers with the figures changed and the wording turned round, in a confident voice (a model that is wrong)
  abstain  says it cannot verify (a model that refuses)
It tests the loader, the scoring and the product's labels, not how good any real model is.

LIVE needs a server that is already running with the real AI keys in its own environment (never in a file) and AI_STUB unset, started against a THROWAWAY database; pass that database
name with --db. It signs up its own throwaway account, makes it Pro in that database and asks each question once. Each case is one model call (one more for a question not in English)."""

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from evals import lawyer_set as ls  # noqa: E402


def commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=str(REPO), timeout=10).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def standin_reply(mode: str, case: dict) -> dict:
    """The scripted model's JSON answer for one case."""
    src = case["sources"][0] if case["sources"] else "no source"
    if mode == "abstain" or case["expect"] == "could_not_check" and mode == "echo":
        return {"answer": "I cannot verify this from the materials provided.", "claims": [], "missing_information": ["a verified source"], "contrary_authority": [], "uncertainty": "No verified source was available."}
    text = case["correct_answer"] if mode == "echo" else _twist(case["correct_answer"])
    return {"answer": text, "claims": [{"text": text[:600], "claim_kind": "LEGAL", "supports": "YES", "citations": [{"source": "LIBRARY", "ref": src, "quote": ""}]}],
            "missing_information": [], "contrary_authority": [], "uncertainty": ""}


SWAP = {"one": "nine", "two": "eight", "three": "seven", "four": "six", "five": "four", "six": "two", "seven": "three", "ten": "twenty", "fifteen": "sixty", "twenty": "seventy",
        "thirty": "ninety", "forty": "eighty", "fifty": "ninety", "sixty": "fifteen", "ninety": "thirty", "hundred": "thousand", "lakh": "crore"}


def _twist(text: str) -> str:
    """The same words with the figures changed and the sense turned round: a confident wrong answer. Digits go up by 7, a number word becomes another one (thirty to ninety), and 'not' is
    taken out or put in after the first 'must', 'may', 'shall', 'can' or 'will'."""
    import re

    out = re.sub(r"\d+", lambda m: str(int(m.group(0)) + 7), text)
    out = re.sub(r"\b(" + "|".join(SWAP) + r")\b", lambda m: SWAP[m.group(1).lower()], out, flags=re.I)
    if " not " in out:
        out = out.replace(" not ", " ", 1)
    else:
        flipped = re.sub(r"\b(must|may|shall|can|will)\b", lambda m: m.group(1) + " not", out, count=1, flags=re.I)
        out = flipped if flipped != out else out + " Not so."
    return out


def run_case(client, case: dict, queue=None) -> tuple[dict, bool]:
    """(the /research result, whether the verified library holds every source of this case)."""
    if queue:
        queue(case)
    body = {"question": case["question"], "mode": "STANDARD", "language": case["language"]}
    r = client.post("/research", json=body)
    if r.status_code != 200:
        raise RuntimeError(f"{case['id']}: /research answered {r.status_code}: {r.text[:200]}")
    held = bool(case["sources"])
    for src in case["sources"]:
        found = client.get("/library/search", params={"q": src, "limit": 10})
        items = found.json().get("results", []) if found.status_code == 200 else []
        held = held and any(i.get("status") == "VERIFIED" and ls.source_matches(src, i.get("citation", "")) for i in items)
    return r.json(), held


def require_mongo(url: str) -> None:
    """A plain message instead of a long error when MongoDB is not running."""
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError

    try:
        MongoClient(url, serverSelectionTimeoutMS=3000).admin.command("ping")
    except PyMongoError as exc:
        raise RuntimeError("MongoDB is not running at the address given (MONGO_URL, default mongodb://127.0.0.1:27017). Start it first: scripts/dev-backend.ps1 starts it, or run mongod yourself.") from exc


def signup(client, tag: str) -> None:
    r = client.post("/auth/signup", json={"email": f"lawyer-eval-{tag}@example.com", "password": f"Pw-{uuid.uuid4().hex}", "full_name": "Lawyer Eval", "organization_name": f"Lawyer Eval {tag}",
                                          "accept_privacy": True, "elapsed_ms": 5000})
    if r.status_code != 200:
        raise RuntimeError(f"could not create the throwaway account: {r.status_code} {r.text[:200]}")


def finish(scored: list[dict], args, answers_from: str, mode: str, library_entries) -> int:
    meta = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "mode": mode, "answers_from": answers_from, "file": str(Path(args.set).name), "sha256": ls.file_sha256(args.set),
            "commit": commit(), "library_entries": library_entries}
    text = ls.render_report(scored, meta)
    path = ls.save_report(text, {"meta": meta, "summary": ls.summarise(scored), "cases": scored}, args.out_dir, mode)
    s = ls.summarise(scored)
    print(f"Report saved: {path}")
    print(f"  answer right {s['answer']['right']}/{s['cases']} (partly {s['answer']['partly']}, wrong {s['answer']['wrong']}); right source named {s['citation']['right']}/{s['citation']['scored']}; "
          f"claim labels right {s['claims']['right']}/{s['claims']['scored']}; could-not-check used {s['could_not_check']['did']}/{s['could_not_check']['should']}; "
          f"WRONG BUT CONFIDENT {s['wrong_but_confident']['count']}")
    return 0


def offline(cases: list[dict], args) -> int:
    scratch = f"vidhi_lawyer_eval_{uuid.uuid4().hex[:8]}"
    env = {"DB_NAME": scratch, "AI_STUB": "true", "PAYMENTS_STUB": "true", "EMAIL_DRY_RUN": "true", "VOICE_STUB": "true", "TWILIO_STUB": "true", "WEBPUSH_STUB": "true", "GOOGLE_STUB": "true",
           "IMAGEGEN_STUB": "true", "DATA_ENCRYPTION_KEY": "ChEYHyYtNDtCSVBXXmVsc3qBiI-WnaSrsrnAx87V3OM=", "LINK_SECRET": "offline-eval-link-secret-not-real", "BCRYPT_COST": "4",  # secret-scan: ok (fake test values)
           "WEBHOOK_CRON_SECRET": "offline-eval-cron-secret-not-real", "RATE_LIMIT_SIGNUP": "1000", "APP_URL": "http://localhost:3000", "COOKIE_SECURE": "false",
           **{k: "100000" for k in ("AI_DAILY_CAP_INR", "AI_FREE_DAILY_CAP_INR", "AI_USER_DAILY_CAP_INR", "AI_FREE_USER_DAILY_CAP_INR", "AI_USER_WINDOW_CAP_INR", "AI_USER_WEEKLY_CAP_INR", "AI_USER_MONTHLY_CAP_INR", "AI_MONTHLY_CAP_INR")}}
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
    require_mongo(os.environ["MONGO_URL"])
    os.environ.update(env)
    os.environ.update({"RATE_LIMIT_AI": "100000", "FREE_AI_PER_DAY": "100000", "PRO_AI_PER_DAY": "100000"})
    if args.fixture_library:
        os.environ["LIBRARY_DIR"] = str(BACKEND / "tests" / "fixtures" / "legal_library")
    from datetime import datetime as _dt

    from pymongo import MongoClient
    from starlette.testclient import TestClient

    import server  # noqa: E402  (after the environment is set: lib.db reads it at import)

    mongo = MongoClient(os.environ["MONGO_URL"])
    try:
        with TestClient(server.app, base_url="http://localhost") as client:
            api = client
            api.base_url = "http://localhost/api"
            signup(api, uuid.uuid4().hex[:8])
            mongo[scratch].users.update_many({}, {"$set": {"plan": "PRO"}})

            def queue(case):
                mongo[scratch].ai_stub.insert_one({"purpose": "research", "contains": None, "response": standin_reply(args.standin, case), "used": False, "created_at": _dt.now(timezone.utc)})

            scored = []
            for case in cases:
                result, held = run_case(api, case, queue)
                scored.append(ls.score_case(case, result, held))
            entries = mongo[scratch].library_entries.count_documents({"status": "VERIFIED"})
    finally:
        mongo.drop_database(scratch)
        mongo.close()
    return finish(scored, args, f"the scripted stand-in ({args.standin}), no AI", f"offline-{args.standin}", entries)


def live(cases: list[dict], args) -> int:
    os.environ.setdefault("MONGO_URL", args.mongo_url)  # lib.aibudget needs these two settings to be importable; the plan itself touches no database
    os.environ.setdefault("DB_NAME", args.db)
    import httpx
    from pymongo import MongoClient

    from lib import aibudget

    est_in, est_out = 3000, 1000  # a cautious guess per answer, as scripts/live_eval.py uses
    models = ("claude-haiku-4-5", "claude-sonnet-5-5")
    per_call = {m: aibudget.cost_inr("anthropic", est_in, est_out, m) for m in models}
    calls = len(cases) + sum(1 for c in cases if c["language"] != "en")
    print(f"PLAN: {len(cases)} cases, about {calls} model calls; estimated {calls * per_call[models[0]]:.1f} rupees on Claude Haiku 4.5, {calls * per_call[models[1]]:.1f} on Sonnet 5.5 "
          f"(prices from the table in lib/aibudget.py, the rupee rate is {aibudget.usd_inr():g}; the real cost depends on the provider the server uses and is UNVERIFIED); cap {args.cap_inr:g} rupees")
    if not args.yes_spend:
        print("Nothing was run and nothing was spent. Say \"run\" and add --yes-spend to make these real, paid calls.")
        return 0
    if max(calls * v for v in per_call.values()) > args.cap_inr:
        print("The worst-case estimate is above the cap; lower the number of cases (--limit) or raise --cap-inr on purpose.")
        return 2
    require_mongo(args.mongo_url)
    client = httpx.Client(base_url=args.base_url.rstrip("/") + "/api", timeout=300.0)
    tag = uuid.uuid4().hex[:8]
    signup(client, tag)
    mongo = MongoClient(args.mongo_url)
    mongo[args.db].users.update_one({"email": f"lawyer-eval-{tag}@example.com"}, {"$set": {"plan": "PRO"}})
    import time

    scored = []
    for n, case in enumerate(cases):
        time.sleep(args.pause if n else 0)
        result, held = run_case(client, case)
        scored.append(ls.score_case(case, result, held))
    entries = mongo[args.db].library_entries.count_documents({"status": "VERIFIED"})
    return finish(scored, args, f"a real model through the server at {args.base_url} (label {args.label})", f"live-{args.label}", entries)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--set", default=str(ls.DEFAULT_PATH))
    p.add_argument("--out-dir", default=str(REPO / "docs" / "evals"))
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--live", action="store_true")
    p.add_argument("--standin", choices=("echo", "wrong", "abstain"), default="echo")
    p.add_argument("--fixture-library", action="store_true", help="offline: load the invented test library (backend/tests/fixtures/legal_library) so a source can be found")
    p.add_argument("--limit", type=int, default=0, help="only the first N cases")
    p.add_argument("--base-url", default="http://127.0.0.1:8011")
    p.add_argument("--mongo-url", default="mongodb://127.0.0.1:27017")
    p.add_argument("--db", help="live: the throwaway database the server uses")
    p.add_argument("--label", default="model")
    p.add_argument("--cap-inr", type=float, default=100.0)
    p.add_argument("--pause", type=float, default=4.0)
    p.add_argument("--yes-spend", action="store_true")
    a = p.parse_args()
    cases, problems, warnings = ls.load(a.set)
    for w in warnings:
        print("WARNING:", w)
    if problems:
        print("The set cannot be used yet:")
        for x in problems:
            print("  -", x)
        return 2
    if a.limit:
        cases = cases[: a.limit]
    print(f"Loaded {len(cases)} cases from {a.set} (sha256 {ls.file_sha256(a.set)[:16]}).")
    if a.check:
        return 0
    if a.live and not a.db:
        print("--db is required with --live (the throwaway database the server uses).")
        return 2
    try:
        return offline(cases, a) if a.offline else live(cases, a)
    except RuntimeError as exc:
        print("Stopped:", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
