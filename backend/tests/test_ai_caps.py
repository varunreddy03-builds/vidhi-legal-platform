"""The AI spending caps (lib/aibudget.py): a monthly total, a daily total and each person's day; a clear error naming the limit that was reached; one cost record per call (who, which model,
how many tokens, how many rupees) with no client text anywhere in it or in the logs; and no AI call that can skip the budget. Every provider is replaced by a stand-in: no paid call is made."""

import ast
import asyncio
import logging
import pathlib
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from lib import ai, aibudget
from lib.aibudget import Budget, BudgetExceeded, DailyCapReached, UserDailyCapReached
from tests.conftest import answer, mongo, stub
from tests.test_admin import admin  # noqa: F401  (fixture)
from tests.test_ai_budget import with_budget

BACKEND = pathlib.Path(__file__).resolve().parent.parent
CLIENT_WORDS = "zq-client-words-never-logged"


@pytest.fixture(autouse=True)
def caps(monkeypatch):
    monkeypatch.setenv("AI_MONTHLY_CAP_INR", "1000")
    monkeypatch.setenv("AI_DAILY_CAP_INR", "100")
    monkeypatch.setenv("AI_USER_DAILY_CAP_INR", "40")
    monkeypatch.setenv("AI_FREE_DAILY_CAP_INR", "30")
    monkeypatch.setenv("AI_FREE_USER_DAILY_CAP_INR", "15")
    for name in ("AI_USER_WINDOW_CAP_INR", "AI_USER_WEEKLY_CAP_INR", "AI_USER_MONTHLY_CAP_INR"):  # one person's other limits are out of the way unless a test sets them
        monkeypatch.setenv(name, "100000")
    monkeypatch.setenv("AI_ALERT_PERCENT", "80")


def reserved(doc) -> float:
    return round(float((doc or {}).get("reserved_inr", 0)), 4)


# ---------- the three caps ----------
def test_the_daily_total_stops_everyone_and_gives_back_what_it_had_set_aside(monkeypatch):
    monkeypatch.setenv("AI_DAILY_CAP_INR", "50")

    async def body(b, alerts, spend, ledger):
        await b.reserve(30, user=("u1", None))
        await b.reserve(20, user=("u2", None))
        with pytest.raises(DailyCapReached) as e:
            await b.reserve(1, user=("u3", None))
        assert e.value.scope == "day" and e.value.status_code == 503
        assert reserved(await spend.find_one({"_id": b._mid()})) == 50  # the refused rupee was given back to the month
        assert await spend.find_one({"_id": f"u:u3:{aibudget.day_key(b._now())}"}) is None

    with_budget(body)


def test_one_persons_daily_cap_stops_that_person_only_and_leaves_no_residue():
    async def body(b, alerts, spend, ledger):
        await b.reserve(25, user=("a", None))
        await b.reserve(15, user=("a", None))
        with pytest.raises(UserDailyCapReached) as e:
            await b.reserve(1, user=("a", None))
        assert e.value.scope == "user" and e.value.status_code == 429
        await b.reserve(30, user=("b", None))  # someone else is not affected
        day = aibudget.day_key(b._now())
        assert reserved(await spend.find_one({"_id": f"d:{day}"})) == 70 and reserved(await spend.find_one({"_id": b._mid()})) == 70  # the refused rupee left nothing behind
        assert reserved(await spend.find_one({"_id": f"u:a:{day}"})) == 40

    with_budget(body)


def test_a_call_with_no_person_counts_against_the_totals_only():
    async def body(b, alerts, spend, ledger):
        for _ in range(8):
            await b.reserve(10)  # a background job: no person, so no per-person cap, but the daily total (100) still applies
        with pytest.raises(DailyCapReached):
            await b.reserve(30)

    with_budget(body)


def test_the_caps_are_safe_under_concurrency(monkeypatch):
    monkeypatch.setenv("AI_USER_DAILY_CAP_INR", "100")
    monkeypatch.setenv("AI_DAILY_CAP_INR", "100000")

    async def body(b, alerts, spend, ledger):
        results = await asyncio.gather(*[b.reserve(10, user=("u", None)) for _ in range(50)], return_exceptions=True)
        assert sum(1 for r in results if not isinstance(r, Exception)) == 10 and all(isinstance(r, UserDailyCapReached) for r in results if isinstance(r, Exception))

    with_budget(body)


def test_the_daily_caps_start_again_on_the_next_day_in_india():
    clock = [datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)]  # 15:30 IST

    async def body(b, alerts, spend, ledger):
        await b.reserve(40, user=("a", None))
        with pytest.raises(UserDailyCapReached):
            await b.reserve(1, user=("a", None))
        clock[0] += timedelta(days=1)
        await b.reserve(40, user=("a", None))  # a new IST day: a new allowance
        assert aibudget.day_key(clock[0]) == "2026-11-06"

    with_budget(body, now=lambda: clock[0])


def test_a_cap_of_zero_turns_that_cap_off(monkeypatch):
    monkeypatch.setenv("AI_USER_DAILY_CAP_INR", "0")
    monkeypatch.setenv("AI_DAILY_CAP_INR", "0")

    async def body(b, alerts, spend, ledger):
        await b.reserve(500, user=("a", None))  # only the monthly cap (1000) is left

    with_budget(body)


def test_settling_and_releasing_change_the_month_the_day_and_the_person_together():
    async def body(b, alerts, spend, ledger):
        day = aibudget.day_key(b._now())
        res = await b.reserve(10, user=("u1", "org1"))
        await b.settle(res, 10, 2.5, provider="gemini", model="gemini-3.8-flash", task="research", tokens=(100, 50), estimated=False)
        for doc_id in (b._mid(), f"d:{day}", f"u:u1:{day}"):
            assert reserved(await spend.find_one({"_id": doc_id})) == 2.5
        again = await b.reserve(5, user=("u1", "org1"))
        await b.release(again, 5)  # a failed call is not charged
        for doc_id in (b._mid(), f"d:{day}", f"u:u1:{day}"):
            assert reserved(await spend.find_one({"_id": doc_id})) == 2.5
        row = await ledger.find_one({})
        assert row["user_id"] == "u1" and row["organization_id"] == "org1" and row["model"] == "gemini-3.8-flash" and row["cost_inr"] == 2.5 and row["day"] == day
        assert row["provider"] == "gemini" and row["task"] == "research" and (row["tokens_in"], row["tokens_out"]) == (100, 50)

    with_budget(body)


def test_limit_reached_names_the_widest_limit_first_and_status_shows_today():
    async def body(b, alerts, spend, ledger):
        assert await b.limit_reached("a") is None
        await b.reserve(40, user=("a", None))
        assert await b.limit_reached("a") == "user" and await b.limit_reached("b") is None
        await b.reserve(40, user=("b", None))
        await b.reserve(20, user=("c", None))
        assert await b.limit_reached("d") == "day"
        await spend.update_one({"_id": b._mid()}, {"$set": {"cap_override_inr": 50}})
        assert await b.limit_reached("d") == "month"
        st = await b.status()
        assert st["daily_cap_inr"] == 100 and st["daily_used_inr"] == 100 and st["user_daily_cap_inr"] == 40 and st["day"] == aibudget.day_key(b._now())

    with_budget(body)


# ---------- the clear errors ----------
def test_ensure_available_says_which_limit_was_reached_and_when_it_renews(monkeypatch):
    async def body(b, alerts, spend, ledger):
        monkeypatch.setattr(aibudget, "_instance", b)
        me, other = {"id": "u1", "organization_id": "o1", "plan": "PRO"}, {"id": "u2", "organization_id": "o1", "plan": "PRO"}
        await aibudget.ensure_available(me)  # nothing used yet
        await b.reserve(40, user=("u1", "o1"))
        with pytest.raises(HTTPException) as e:
            await aibudget.ensure_available(me)
        assert e.value.status_code == 429 and "allowance for today" in e.value.detail and int(e.value.headers["Retry-After"]) >= 60
        await aibudget.ensure_available(other)  # another person is not refused
        await b.reserve(40, user=("u2", "o1"))
        await b.reserve(20, user=("u3", "o1"))
        with pytest.raises(HTTPException) as e:
            await aibudget.ensure_available({"id": "u4", "organization_id": "o1", "plan": "PRO"})
        assert e.value.status_code == 503 and "today's shared limit" in e.value.detail and "midnight" in e.value.detail
        await spend.update_one({"_id": b._mid()}, {"$set": {"cap_override_inr": 50}})
        with pytest.raises(HTTPException) as e:
            await aibudget.ensure_available({"id": "u5", "organization_id": "o1", "plan": "PRO"})
        assert e.value.status_code == 503 and "this month's AI budget" in e.value.detail and e.value.headers["Retry-After"] == "86400"

    with_budget(body)


def test_ai_failure_turns_a_reached_cap_into_a_clear_error_and_anything_else_into_the_busy_message():
    for exc, status, words in ((UserDailyCapReached("x"), 429, "allowance for today"), (DailyCapReached("x"), 503, "today's shared limit"), (BudgetExceeded("x"), 503, "this month's AI budget")):
        out = ai.ai_failure(exc)
        assert out.status_code == status and words in out.detail and int(out.headers["Retry-After"]) >= 60
    busy = ai.ai_failure(RuntimeError("provider said something"))
    assert busy.status_code == 502 and busy.detail == ai.AI_UNAVAILABLE and "provider" not in busy.detail


def test_the_route_level_errors_for_a_person_at_the_cap(user_a, admin):  # noqa: F811
    uid, day = user_a.get("/auth/me").json()["id"], aibudget.day_key()
    budget = admin.get("/admin/ai-spend").json()["budget"]
    cap = budget["free_user_daily_cap_inr"] if user_a.get("/auth/entitlement").json()["tier"] == "free" else budget["user_daily_cap_inr"]  # the cap of this person's plan
    doc_id = f"u:{uid}:{day}"
    word = f"capword{uuid.uuid4().hex[:10]}"
    try:
        mongo().ai_spend.insert_one({"_id": doc_id, "reserved_inr": 1e9, "spent_inr": 0.0, "calls": 0})
        refused = user_a.post("/research", json={"question": f"Must a borrowed widget be returned? {word}", "mode": "STANDARD"})  # at the door
        assert refused.status_code == 429 and "allowance for today" in refused.json()["detail"] and int(refused.headers["Retry-After"]) >= 60
        mongo().ai_spend.update_one({"_id": doc_id}, {"$set": {"reserved_inr": cap - 1e-6}})  # passes the early look, but the call itself would pass the cap
        stub("research", answer("An answer.", []), contains=word)
        mid_call = user_a.post("/research", json={"question": f"Must a borrowed widget be returned? {word}", "mode": "STANDARD"})
        assert mid_call.status_code == 429 and "allowance for today" in mid_call.json()["detail"]  # a clear message, not "AI busy"
        assert round(mongo().ai_spend.find_one({"_id": doc_id})["reserved_inr"], 5) == round(cap - 1e-6, 5)  # the refused call left nothing reserved
    finally:
        mongo().ai_spend.delete_one({"_id": doc_id})


# ---------- the cost record, and no client text ----------
def test_a_call_is_recorded_with_cost_person_and_model_but_no_client_text(monkeypatch, caplog):
    async def fake_call(provider, system, prompt, *, json_mode, image=None):
        return f"an answer that repeats {CLIENT_WORDS}"

    async def body(b, alerts, spend, ledger):
        monkeypatch.setattr(aibudget, "_instance", b)
        monkeypatch.setattr(ai, "_call_text", fake_call)
        aibudget.set_current_user({"id": "u1", "organization_id": "o1"})
        with caplog.at_level(logging.DEBUG):
            await ai._metered("gemini", "system text", f"a prompt that contains {CLIENT_WORDS}", json_mode=False, task="research")
        row = await ledger.find_one({})
        assert row["user_id"] == "u1" and row["organization_id"] == "o1" and row["task"] == "research" and row["provider"] == "gemini" and row["model"] == ai.provider_model("gemini")
        assert row["cost_inr"] > 0 and row["tokens_in"] > 0 and row["tokens_out"] > 0 and row["day"] == aibudget.day_key()
        assert CLIENT_WORDS not in str(row)  # the prompt and the answer are never kept
        assert any("ai cost" in r.getMessage() and "cost_inr=" in r.getMessage() and "user=u1" in r.getMessage() for r in caplog.records)  # one cost line per call

    with_budget(body)
    assert CLIENT_WORDS not in caplog.text


def test_a_failed_call_is_logged_by_its_error_class_never_its_message(monkeypatch, caplog):
    async def failing(provider, system, prompt, *, json_mode, image=None):
        raise RuntimeError(f"the provider repeated the prompt: {CLIENT_WORDS}")

    async def body(b, alerts, spend, ledger):
        monkeypatch.setattr(aibudget, "_instance", b)
        monkeypatch.setattr(ai, "stub_enabled", lambda: False)
        monkeypatch.setattr(ai, "route_for", lambda *a, **k: ["gemini"])
        monkeypatch.setattr(ai, "_usable", lambda chain: chain)
        monkeypatch.setattr(ai, "_call_text", failing)
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(ai.AIError) as e:
                await ai.ask_json("session-1", f"a prompt that contains {CLIENT_WORDS}", "{}", purpose="research")
        assert CLIENT_WORDS not in str(e.value)
        assert (await ledger.find_one({"ok": False}))["error"] == "RuntimeError"  # the class only, as before
        assert CLIENT_WORDS not in str(await ledger.find({}).to_list(10))

    with_budget(body)
    assert "RuntimeError" in caplog.text and CLIENT_WORDS not in caplog.text


def test_log_ai_failure_and_failure_label_never_carry_the_message(caplog):
    class Boom(Exception):
        status_code = 429

    with caplog.at_level(logging.DEBUG):
        ai.log_ai_failure("research", Boom(f"echo {CLIENT_WORDS}"))
        ai.log_ai_failure("research", UserDailyCapReached(f"echo {CLIENT_WORDS}"))
    assert CLIENT_WORDS not in caplog.text and "Boom (HTTP 429)" in caplog.text and "user cap reached" in caplog.text
    assert ai.failure_label(Boom("x")) == "Boom (HTTP 429)" and ai.failure_label(KeyError("x")) == "KeyError"


def test_a_normal_call_through_the_server_is_recorded_with_the_person_and_the_model(user_a):
    uid = user_a.get("/auth/me").json()["id"]
    word = f"ledgerword{uuid.uuid4().hex[:10]}"
    stub("research", answer("An answer.", []), contains=word)
    r = user_a.post("/research", json={"question": f"Must a borrowed widget be returned? {word}", "mode": "STANDARD"})
    assert r.status_code == 200, r.text
    row = mongo().ai_ledger.find_one({"user_id": uid, "task": {"$exists": True}})
    assert row and row["ok"] is True and row["cost_inr"] > 0 and row["model"] == "stub" and row["day"] == aibudget.day_key()
    assert word not in str(row)  # the question is never kept in the cost record


# ---------- no way around the budget ----------
PROVIDER_MARKERS = ("generativelanguage", "api.groq", "openrouter.ai", "api.openai", "api.anthropic", "api.mistral", "integrate.api.nvidia", "api.z.ai", "elevenlabs.io", "genai.Client",
                    "generate_content(", "chat.completions", "messages.create(", "AsyncAnthropic", "AsyncOpenAI")
AI_MODULES = {"lib/ai.py", "lib/voice.py", "lib/imagegen.py"}  # the only modules that talk to an AI provider; each is checked below


def _python_files():
    for d in ("lib", "routers", "scripts", "tools", "evals", "models"):
        yield from (BACKEND / d).rglob("*.py")
    yield BACKEND / "server.py"


def test_only_the_three_ai_modules_talk_to_a_provider():
    strays = []
    for path in _python_files():
        rel = path.relative_to(BACKEND).as_posix()
        text = path.read_text(encoding="utf-8")
        if rel not in AI_MODULES and any(m in text for m in PROVIDER_MARKERS):
            strays.append(rel)
    assert not strays, f"These modules reach an AI provider without going through lib/ai.py, lib/voice.py or lib/imagegen.py (and so around the budget): {strays}"


def _functions(rel):
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
    src = (BACKEND / rel).read_text(encoding="utf-8")
    return {n.name: ast.get_source_segment(src, n) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_every_provider_call_in_those_modules_runs_inside_the_budget():
    text_fns = _functions("lib/ai.py")
    calls = [name for name, src in text_fns.items() if name != "_call_text" and re.search(r"\b_call_text\(", src or "")]
    assert calls == ["_metered"]  # the text providers are only ever reached through the metered wrapper
    assert "budget.reserve(" in text_fns["_metered"] and "budget.settle(" in text_fns["_metered"] and "budget.release(" in text_fns["_metered"]
    assert "budget.reserve(" in text_fns["_stub_ask"] and "budget.settle(" in text_fns["_stub_ask"]  # even the scripted stand-in goes through the budget
    voice_fns = _functions("lib/voice.py")
    for name in ("_eleven_stt", "_gemini_stt", "speak"):
        assert "aibudget.fixed(" in voice_fns[name], name
    assert "aibudget.fixed(" in _functions("lib/imagegen.py")["generate"]


def test_every_route_that_starts_ai_work_checks_the_caps_with_the_signed_in_person():
    for rel in ("lib/plans.py", "lib/ratelimit.py", "routers/images.py", "routers/voice.py"):
        text = (BACKEND / rel).read_text(encoding="utf-8")
        assert "ensure_available(user)" in text and "ensure_available()" not in text, rel  # always with the person, never anonymously


# ---------- the free plan has its own, smaller limits ----------
def test_a_free_person_has_a_smaller_daily_cap_than_a_pro_person():
    async def body(b, alerts, spend, ledger):
        await b.reserve(10, user=("f1", None, "free"))
        await b.reserve(5, user=("f1", None, "free"))
        with pytest.raises(UserDailyCapReached):
            await b.reserve(1, user=("f1", None, "free"))  # 15 is the free cap
        await b.reserve(40, user=("p1", None, "pro"))  # a Pro person has 40 here
        with pytest.raises(UserDailyCapReached):
            await b.reserve(1, user=("p1", None, "pro"))

    with_budget(body)


def test_free_accounts_together_cannot_use_up_the_day_that_pro_customers_pay_for():
    async def body(b, alerts, spend, ledger):
        day = aibudget.day_key(b._now())
        await b.reserve(15, user=("f1", None, "free"))
        await b.reserve(15, user=("f2", None, "free"))  # the free plan's shared 30
        with pytest.raises(aibudget.FreePoolCapReached) as e:
            await b.reserve(1, user=("f3", None, "free"))
        assert e.value.scope == "free" and e.value.status_code == 503 and "Pro is not affected" in e.value.public_message
        await b.reserve(40, user=("p1", None, "pro"))  # a Pro person is still served: the day (100) has room
        assert reserved(await spend.find_one({"_id": f"d:{day}"})) == 70 and reserved(await spend.find_one({"_id": f"f:{day}"})) == 30  # the refused rupee left nothing behind
        assert await spend.find_one({"_id": f"u:f3:{day}"}) is None

    with_budget(body)


def test_ensure_available_tells_a_free_person_the_free_plan_is_full_and_a_pro_person_is_not_refused(monkeypatch):
    async def body(b, alerts, spend, ledger):
        monkeypatch.setattr(aibudget, "_instance", b)
        await b.reserve(15, user=("f1", None, "free"))
        await b.reserve(15, user=("f2", None, "free"))
        free, pro = {"id": "f3", "organization_id": "o1"}, {"id": "p9", "organization_id": "o1", "plan": "PRO"}
        with pytest.raises(HTTPException) as e:
            await aibudget.ensure_available(free)
        assert e.value.status_code == 503 and "free plan has reached today's shared AI limit" in e.value.detail and int(e.value.headers["Retry-After"]) >= 60
        await aibudget.ensure_available(pro)
        st = await b.status()
        assert st["free_daily_cap_inr"] == 30 and st["free_user_daily_cap_inr"] == 15 and st["user_daily_cap_inr"] == 40

    with_budget(body)


def test_the_documented_defaults_are_the_ones_in_force(monkeypatch):
    for name in ("AI_MONTHLY_CAP_INR", "AI_DAILY_CAP_INR", "AI_FREE_DAILY_CAP_INR", "AI_USER_WINDOW_CAP_INR", "AI_USER_DAILY_CAP_INR", "AI_USER_WEEKLY_CAP_INR", "AI_USER_MONTHLY_CAP_INR",
                 "AI_FREE_USER_DAILY_CAP_INR", "AI_WINDOW_HOURS"):
        monkeypatch.delenv(name, raising=False)
    assert (aibudget.cap_inr(), aibudget.daily_cap_inr(), aibudget.free_daily_cap_inr(), aibudget.window_hours()) == (20000, 2000, 500, 5)
    pro, free = aibudget.person_caps("pro"), aibudget.person_caps("free")
    assert pro == {"window": 40, "day": 60, "week": 200, "month": 800} and free == {"day": 15}
    assert pro["window"] <= pro["day"] <= pro["week"] <= pro["month"]  # a shorter limit is never larger than a longer one
    assert pro["month"] <= 0.5 * 1999  # the AI a Pro person can use in a month costs at most half of what Rs 1,999 brings in
    example = (BACKEND.parent / ".env.example").read_text(encoding="utf-8")
    for line in ("AI_DAILY_CAP_INR=2000", "AI_FREE_DAILY_CAP_INR=500", "AI_WINDOW_HOURS=5", "AI_USER_WINDOW_CAP_INR=40", "AI_USER_DAILY_CAP_INR=60", "AI_USER_WEEKLY_CAP_INR=200",
                 "AI_USER_MONTHLY_CAP_INR=800", "AI_FREE_USER_DAILY_CAP_INR=15"):
        assert line in example, line  # the example settings file says the same numbers
    assert "PRO_PRICE_AMOUNT=1999" in (BACKEND / ".env.example").read_text(encoding="utf-8")  # and the example price is the real one


# ---------- a Pro person's limits work like Claude's: a rolling window, a day, a week, a month ----------
def run_with_clock(body, start):
    clock = [start]
    return with_budget(lambda b, a, sp, led: body(b, sp, clock), now=lambda: clock[0])


def test_the_rolling_window_stops_a_burst_and_a_new_window_starts_when_it_ends(monkeypatch):
    monkeypatch.setenv("AI_USER_WINDOW_CAP_INR", "20")

    async def body(b, spend, clock):
        first = clock[0]
        res = await b.reserve(20, user=("a", None, "pro"))
        with pytest.raises(aibudget.WindowCapReached) as e:
            await b.reserve(1, user=("a", None, "pro"))
        assert e.value.scope == "window" and e.value.status_code == 429 and e.value.resets_at == first + timedelta(hours=5)
        assert "5-hour period" in e.value.public_message and "India time" in e.value.public_message
        info = await b.limit_info("a", "pro")
        assert info[0] == "window" and info[1] == first + timedelta(hours=5)
        await b.release(res, 20)  # a failed call gives the window its money back
        await b.reserve(20, user=("a", None, "pro"))
        clock[0] = first + timedelta(hours=5, minutes=1)  # the window has ended
        assert await b.limit_info("a", "pro") is None
        await b.reserve(20, user=("a", None, "pro"))  # a new window, a new allowance
        assert (await spend.find_one({"_id": "w:a"}))["start"] != first.replace(tzinfo=None)

    run_with_clock(body, datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc))


def test_a_window_that_rolled_over_is_not_touched_by_a_call_that_started_in_the_old_one(monkeypatch):
    monkeypatch.setenv("AI_USER_WINDOW_CAP_INR", "20")

    async def body(b, spend, clock):
        old = await b.reserve(10, user=("a", None, "pro"))
        clock[0] += timedelta(hours=6)
        await b.reserve(5, user=("a", None, "pro"))  # the new window holds 5
        await b.release(old, 10)  # the old call ends late: the new window must not lose its 5 or go negative
        assert round((await spend.find_one({"_id": "w:a"}))["reserved_inr"], 4) == 5

    run_with_clock(body, datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc))


def test_the_weekly_cap_stops_a_person_across_days_and_renews_on_monday(monkeypatch):
    monkeypatch.setenv("AI_USER_WEEKLY_CAP_INR", "50")

    async def body(b, spend, clock):
        await b.reserve(40, user=("a", None, "pro"))  # Tuesday: the day's 40
        clock[0] += timedelta(days=1)
        await b.reserve(10, user=("a", None, "pro"))  # Wednesday: the week reaches 50
        with pytest.raises(aibudget.WeekCapReached) as e:
            await b.reserve(1, user=("a", None, "pro"))
        assert e.value.scope == "week" and e.value.status_code == 429 and "Monday" in e.value.public_message
        assert e.value.resets_at == datetime(2026, 11, 8, 18, 30, tzinfo=timezone.utc)  # Monday 9 November, 00:00 India time
        assert (await b.limit_info("a", "pro"))[0] == "week"
        clock[0] = datetime(2026, 11, 9, 5, 0, tzinfo=timezone.utc)  # Monday morning
        await b.reserve(40, user=("a", None, "pro"))

    run_with_clock(body, datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc))


def test_the_personal_monthly_allowance_stops_a_person_for_the_rest_of_the_month(monkeypatch):
    monkeypatch.setenv("AI_USER_MONTHLY_CAP_INR", "60")

    async def body(b, spend, clock):
        await b.reserve(40, user=("a", None, "pro"))
        clock[0] += timedelta(days=1)
        await b.reserve(20, user=("a", None, "pro"))
        with pytest.raises(aibudget.UserMonthCapReached) as e:
            await b.reserve(1, user=("a", None, "pro"))
        assert e.value.scope == "user_month" and "1st of next month" in e.value.public_message and e.value.resets_at == datetime(2026, 11, 30, 18, 30, tzinfo=timezone.utc)
        clock[0] = datetime(2026, 12, 1, 5, 0, tzinfo=timezone.utc)
        await b.reserve(40, user=("a", None, "pro"))

    run_with_clock(body, datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc))


def test_when_several_of_a_persons_limits_are_full_the_one_that_renews_last_is_named(monkeypatch):
    monkeypatch.setenv("AI_USER_WINDOW_CAP_INR", "20")
    monkeypatch.setenv("AI_USER_WEEKLY_CAP_INR", "20")

    async def body(b, spend, clock):
        await b.reserve(20, user=("a", None, "pro"))  # fills the window AND the week
        info = await b.limit_info("a", "pro")
        assert info[0] == "week"  # the window renews in 5 hours, the week on Monday: the person can really use AI again only then

    run_with_clock(body, datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc))


def test_a_refusal_by_a_longer_limit_gives_back_the_shorter_ones(monkeypatch):
    monkeypatch.setenv("AI_USER_WEEKLY_CAP_INR", "30")

    async def body(b, spend, clock):
        await b.reserve(30, user=("a", None, "pro"))
        with pytest.raises(aibudget.WeekCapReached):
            await b.reserve(10, user=("a", None, "pro"))
        assert round((await spend.find_one({"_id": "w:a"}))["reserved_inr"], 4) == 30  # the refused 10 left nothing in the window
        assert round((await spend.find_one({"_id": f"u:a:{aibudget.day_key(clock[0])}"}))["reserved_inr"], 4) == 30
        assert round((await spend.find_one({"_id": b._mid()}))["reserved_inr"], 4) == 30

    run_with_clock(body, datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc))


def test_the_usage_meter_shows_shares_and_renewal_times_never_rupees(monkeypatch):
    for name, value in (("AI_USER_WINDOW_CAP_INR", "40"), ("AI_USER_DAILY_CAP_INR", "40"), ("AI_USER_WEEKLY_CAP_INR", "200"), ("AI_USER_MONTHLY_CAP_INR", "800")):
        monkeypatch.setenv(name, value)

    async def body(b, spend, clock):
        await b.reserve(20, user=("a", None, "pro"))
        rows = {r["name"]: r for r in await b.usage("a", "pro")}
        assert list(rows) == ["window", "day", "week", "month"]
        assert rows["window"]["percent"] == 50.0 and rows["window"]["label"] == "5-hour" and rows["day"]["percent"] == 50.0 and rows["week"]["percent"] == 10.0 and rows["month"]["percent"] == 2.5
        assert all(set(r) == {"name", "label", "percent", "resets_at"} and r["resets_at"] for r in rows.values())  # shares and times only
        free = await b.usage("f", "free")
        assert [r["name"] for r in free] == ["day"] and free[0]["percent"] == 0.0
        clock[0] += timedelta(hours=6)
        assert {r["name"]: r for r in await b.usage("a", "pro")}["window"]["percent"] == 0.0  # the window has ended

    run_with_clock(body, datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc))


def test_the_usage_route_gives_a_person_their_own_limits(user_a, anon):
    r = user_a.get("/auth/ai-usage")
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] in ("free", "pro") and body["limits"] and all(set(x) == {"name", "label", "percent", "resets_at"} for x in body["limits"])
    assert "inr" not in r.text.lower() and "rupee" not in r.text.lower()  # no money amounts are shown to a customer
    assert anon.get("/auth/ai-usage").status_code in (401, 403)  # only for a signed-in person


def test_a_window_refusal_at_the_door_tells_the_person_when_it_renews(monkeypatch):
    monkeypatch.setenv("AI_USER_WINDOW_CAP_INR", "20")

    async def body(b, alerts_spend, clock):
        monkeypatch.setattr(aibudget, "_instance", b)
        me = {"id": "w1", "organization_id": "o1", "plan": "PRO"}
        await aibudget.ensure_available(me)
        await b.reserve(20, user=("w1", "o1", "pro"))
        with pytest.raises(HTTPException) as e:
            await aibudget.ensure_available(me)
        assert e.value.status_code == 429 and "5-hour period" in e.value.detail and "India time" in e.value.detail
        assert 60 <= int(e.value.headers["Retry-After"]) <= 5 * 3600 + 60

    async def go(b, a, sp, led):
        return await body(b, sp, [datetime.now(timezone.utc)])

    with_budget(go)


# ---------- the shared totals grow with paying customers ----------
def with_seats(body, accounts):
    """Run `await body(budget, spend)` with a budget that can count Pro seats in a throwaway accounts collection."""
    import os

    from motor.motor_asyncio import AsyncIOMotorClient

    async def main():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        tag = uuid.uuid4().hex[:8]
        spend, ledger, users = db[f"t_spend_{tag}"], db[f"t_ledger_{tag}"], db[f"t_users_{tag}"]
        try:
            if accounts:
                await users.insert_many(accounts)
            b = Budget(spend, ledger, users=users)
            b._seats_ttl = 0.0
            return await body(b, spend, users)
        finally:
            for c in (spend, ledger, users):
                await c.drop()
            client.close()

    return asyncio.run(main())


def _accounts():
    now = datetime.now(timezone.utc)
    return [
        {"plan": "PRO", "pro_until": now + timedelta(days=20)},  # paid
        {"plan": "PRO", "pro_until": None},  # an older Pro account with no date
        {"plan": "PRO", "pro_until": now - timedelta(days=30)},  # lapsed beyond the grace days: not a seat
        {"plan": "FREE"},
        {},
    ]


def test_the_monthly_and_daily_totals_grow_by_one_pro_allowance_for_every_active_pro_seat(monkeypatch):
    monkeypatch.setenv("AI_USER_MONTHLY_CAP_INR", "800")  # AI_MONTHLY_CAP_INR is 1000, AI_USER_DAILY_CAP_INR 40, AI_DAILY_CAP_INR 100

    async def body(b, spend, users):
        assert await b.seats() == 2
        st = await b.status()
        assert st["pro_seats"] == 2 and st["cap_inr"] == 1000 + 2 * 800 and st["daily_cap_inr"] == 100 + 2 * 40

    with_seats(body, _accounts())


def test_a_total_above_the_base_is_allowed_up_to_the_grown_cap_and_no_further(monkeypatch):
    monkeypatch.setenv("AI_USER_MONTHLY_CAP_INR", "800")
    monkeypatch.setenv("AI_DAILY_CAP_INR", "0")  # only the monthly total is under test

    async def body(b, spend, users):
        await b.reserve(2000)  # more than the base 1000, because two Pro seats pay for more
        await b.reserve(600)
        with pytest.raises(BudgetExceeded):
            await b.reserve(1)

    with_seats(body, _accounts())


def test_without_pro_seats_or_without_an_accounts_collection_the_totals_stay_at_their_base(monkeypatch):
    monkeypatch.setenv("AI_USER_MONTHLY_CAP_INR", "800")

    async def body(b, spend, users):
        assert await b.seats() == 0 and (await b.status())["cap_inr"] == 1000

    with_seats(body, [{"plan": "FREE"}])

    async def body2(b, alerts, spend, ledger):
        assert b.users is None and await b.seats() == 0 and (await b.status())["cap_inr"] == 1000

    with_budget(body2)


def test_an_administrators_absolute_cap_for_the_month_wins_over_the_seat_growth(monkeypatch):
    monkeypatch.setenv("AI_USER_MONTHLY_CAP_INR", "800")

    async def body(b, spend, users):
        await spend.update_one({"_id": b._mid()}, {"$set": {"cap_override_inr": 50}}, upsert=True)
        assert (await b.status())["cap_inr"] == 50

    with_seats(body, _accounts())


def test_the_seat_count_is_remembered_for_a_few_minutes_so_it_is_not_asked_on_every_call(monkeypatch):
    async def body(b, spend, users):
        b._seats_ttl = 300.0
        assert await b.seats() == 2
        await users.insert_one({"plan": "PRO", "pro_until": None})
        assert await b.seats() == 2  # still the remembered count
        b._seats_ttl = 0.0
        assert await b.seats() == 3  # asked again

    with_seats(body, _accounts())
