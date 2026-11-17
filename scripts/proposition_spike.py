"""Real-AI check of the Authority Check proposition step ("may not support this point, please read").

    C:/vidhi-tools/venv2/Scripts/python.exe scripts/proposition_spike.py --sc-dir C:/vidhi-tools/data/sc --yes-spend

PAID. It makes at most MAX_CALLS AI calls (1 key test + 10 cases; a failed attempt counts), to Gemini (model gemini-3.5-flash unless GEMINI_MODEL is set) with OpenRouter only as the
fall-back when Gemini fails, and stops before any call that would take the running cost past CAP_INR. The report says which service answered each case.
The key is read from the environment or backend/.env and is never printed or written. For each case the report keeps: the draft sentence (written from the judgment's
own text), what the AI returned, whether the quote it gave was found word for word in the real judgment text (by code, not by the AI), and the cost.
The AI can only ever produce a caution; it cannot confirm that a case supports a point."""

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

MAX_CALLS = 11
CAP_INR = 50.0

# (neutral citation, stem in the dataset, what the paragraph says, the draft sentence, expected). Sentences are written from the paragraph's own words:
# "aligned" restates it, "contrary" says the opposite. Which is which is the spike author's reading and needs a lawyer to confirm.
CASES = [
    ("2024 INSC 944", "aligned", "Applying Section 14 of the Limitation Act, the period from 20.10.2011 to 23.02.2012 is excluded, so the appellant can use the statutory remedy under Section 34 of the Act."),
    ("2022 INSC 1266", "contrary", "In awarding compensation for permanent disability the court looks only at the medical disability and does not consider the claimant's socio-economic background."),
    ("2023 INSC 596", "contrary", "The complainants have a right of audience before the Supreme Court and the High Court in a prosecution for the offence under Section 420 of the IPC."),
    ("2024 INSC 564", "aligned", "The Tribunal committed no error in accepting the original application, and the High Court rightly refused to interfere with the Tribunal's judgment."),
    ("2024 INSC 172", "contrary", "Prosecution of the appellant for the offences under Section 306 IPC and the SC/ST Act is justified even though the investigating agency itself proposed a closure report."),
    ("2024 INSC 265", "aligned", "The respondent is not a workman, so a reference to the Labour Court under the Industrial Disputes Act against the appellant is not maintainable."),
    ("2023 INSC 430", "contrary", "Continuing the direction on eco-sensitive zones avoids man-animal conflict and does not intensify it."),
    ("2023 INSC 886", "aligned", "Special purpose vehicles which own, operate and maintain captive generating plants are an association of persons under the second proviso to Rule 3(1)(a) of the Rules."),
    ("2023 INSC 1053", "contrary", "The Tribunal wrongly computed the market value of electricity supplied by the captive power plants, and the High Court was not justified in deciding the appeal against the revenue."),
    ("2023 INSC 928", "aligned", "The reasoning and findings in the impugned orders cannot survive and are set aside, and the revenue's appeals are allowed with no order on costs."),
]


def load_key() -> None:
    """GEMINI_API_KEY and OPENROUTER_API_KEY from the environment or backend/.env. The values are never printed."""
    env = ROOT / "backend" / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    for name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        if os.environ.get(name):
            continue
        for line in lines:
            m = re.match(rf"\s*{name}\s*=\s*(.*)", line)
            if m and m.group(1).strip().strip("\"'"):
                os.environ[name] = m.group(1).strip().strip("\"'")


class Meter:
    def __init__(self, ai, aibudget):
        self.ai, self.aibudget = ai, aibudget
        self.calls = 0
        self.spent = 0.0
        self.last_cost = 0.0
        self.providers = []  # the service that answered each successful call, in order

    async def metered(self, provider, system, prompt, *, json_mode, image=None, task="generic"):
        """Stands in for ai._metered: counts every attempt, refuses past MAX_CALLS or CAP_INR, and only the providers named by --route."""
        if provider not in ALLOWED:
            raise self.aibudget.BudgetExceeded("this provider is not allowed in this spike")
        est_in = self.aibudget.est_tokens(system + prompt)
        worst = self.aibudget.cost_inr(provider, est_in, 1500)
        if self.calls >= MAX_CALLS or self.spent + worst > CAP_INR:
            raise self.aibudget.BudgetExceeded("spike limit reached")
        self.calls += 1
        token = self.ai._USAGE.set(None)
        try:
            text = await self.ai._call_text(provider, system, prompt, json_mode=json_mode, image=image)
        finally:
            usage = self.ai._USAGE.get()
            self.ai._USAGE.reset(token)
        tin, tout = usage if usage else (est_in, self.aibudget.est_tokens(text))
        self.last_cost = self.aibudget.cost_inr(provider, tin, tout)
        self.providers.append(provider)
        self.spent += self.last_cost
        self.last_tokens = (tin, tout, usage is not None)
        return text


ALLOWED = ("gemini",)


async def main(sc_dir: str, route: str, redo_failed: bool) -> int:
    global ALLOWED
    ALLOWED = tuple(route.split(","))
    load_key()
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set (environment or backend/.env). Nothing was sent.")
        return 2
    os.environ.setdefault("GEMINI_MODEL", "gemini-3.5-flash")
    os.environ["AI_ROUTE"] = route  # provider names as lib/ai.py knows them: gemini, sonnet, haiku (sonnet/haiku go through OpenRouter when there is no Anthropic key)
    os.environ["AI_ROUTE_RESEARCH"] = route
    os.environ.pop("AI_STUB", None)
    from lib import ai, aibudget
    from lib.refcheck import propositions
    from lib.refcheck.scsource import SupremeCourtData

    if ai.stub_enabled():
        print("The AI stub is switched on; refusing to report stub output as a real run.")
        return 2
    meter = Meter(ai, aibudget)
    ai._metered = meter.metered
    print(f"model: {ai.model_name()}  prices (USD per 1M tokens in/out): {aibudget.price_for(ai.model_name())}  usd_inr: {aibudget.usd_inr()}")

    # call 1: the key test, the cheapest call there is
    try:
        await ai._metered(ALLOWED[0], "Reply with a JSON object.", 'Return {"ok": true}', json_mode=True)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        for name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            msg = msg.replace(os.environ.get(name, "<unset>"), "<KEY>")
        print(f"KEY TEST FAILED ({ALLOWED[0]}): {type(exc).__name__}: {msg[:300]}. Nothing more was sent. calls={meter.calls}")
        return 3
    print(f"key test ok via {meter.providers[-1]}. calls={meter.calls} cost_inr={meter.spent:.4f}")

    src = SupremeCourtData(sc_dir)
    by_neutral = {r.neutral: r for r in src.records.values() if r.neutral}
    rows = []
    todo = CASES
    if redo_failed:  # only the cases an earlier report could not check
        prev = json.loads((ROOT / "docs" / "evals" / "proposition-spike-2026-10-27.json").read_text(encoding="utf-8"))
        missing = {r["neutral"] for r in prev["rows"] if r["result_state"] == "not_checked"}
        todo = [c for c in CASES if c[0] in missing]
    for neutral, expected, sentence in todo:
        rec = by_neutral[neutral]
        doc = await src.fetch(rec.stem)
        blocks = doc["blocks"]
        raw = {}

        async def ask(session_id, prompt, schema, **kw):
            data = await ai.ask_json(session_id, prompt, schema, **kw)
            raw.update(data if isinstance(data, dict) else {})
            return data

        before_calls, before_cost, before_ok = meter.calls, meter.spent, len(meter.providers)
        res = await propositions.check(sentence, blocks, ask=ask, session_id="spike", tier="full")
        quote = str(raw.get("quote") or "")
        rows.append({
            "case": rec.title, "neutral": neutral, "draft_sentence_kind": expected, "claim": sentence,
            "ai_assessment": raw.get("assessment"), "ai_excerpt": raw.get("excerpt"), "ai_quote": quote,
            "result_state": res.get("state"), "paragraph": res.get("paragraph"), "note": res.get("note"),
            "quote_verified_in_judgment": res.get("state") == propositions.MAY_NOT_SUPPORT.lower() or res.get("state") == "may_not_support",
            "answered_by": meter.providers[before_ok:] or None, "calls": meter.calls - before_calls, "cost_inr": round(meter.spent - before_cost, 4),
        })
        print(f"{neutral:<16} {expected:<9} -> {res.get('state'):<16} ai={raw.get('assessment')} calls={meter.calls} cost_inr={meter.spent:.4f}")

    summary = {
        "calls": meter.calls, "cost_inr": round(meter.spent, 4), "cap_inr": CAP_INR, "gemini_model": ai.model_name(), "answered_by": {p: meter.providers.count(p) for p in set(meter.providers)},
        "contrary_flagged": sum(1 for r in rows if r["draft_sentence_kind"] == "contrary" and r["result_state"] == "may_not_support"),
        "contrary_total": sum(1 for r in rows if r["draft_sentence_kind"] == "contrary"),
        "aligned_flagged": sum(1 for r in rows if r["draft_sentence_kind"] == "aligned" and r["result_state"] == "may_not_support"),
        "aligned_total": sum(1 for r in rows if r["draft_sentence_kind"] == "aligned"),
        "ai_said_may_not_support_but_quote_not_in_judgment": sum(1 for r in rows if r["ai_assessment"] == "may_not_support" and r["result_state"] != "may_not_support"),
    }
    out = ROOT / "docs" / "evals" / f"proposition-spike-{date.today().isoformat()}{'-' + route.replace(',', '-') if redo_failed else ''}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sc-dir", required=True)
    ap.add_argument("--yes-spend", action="store_true", help="really call the AI (paid)")
    ap.add_argument("--route", default="gemini", help="providers allowed, in order: gemini, sonnet, haiku")
    ap.add_argument("--redo-failed", action="store_true", help="only the cases the earlier report could not check")
    ap.add_argument("--max-calls", type=int, default=MAX_CALLS)
    a = ap.parse_args()
    MAX_CALLS = a.max_calls
    if not a.yes_spend:
        print("Refusing to make paid AI calls without --yes-spend.")
        sys.exit(2)
    sys.exit(asyncio.run(main(a.sc_dir, a.route, a.redo_failed)))
