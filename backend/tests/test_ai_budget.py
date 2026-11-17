"""The monthly AI spending cap: atomic reservation, real-cost settlement, one alert at 80%, a hard stop at 100%, safe under concurrency."""

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

from lib import ai, aibudget
from lib.aibudget import Budget, BudgetExceeded
from tests.conftest import answer, mongo, new_matter, stub, upload
from tests.test_truth_engine import research


def with_budget(body, now=None):
    """Run `await body(budget, alerts, spend, ledger)` against throwaway collections in the test database."""

    async def main():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        tag = uuid.uuid4().hex[:8]
        spend, ledger = db[f"t_spend_{tag}"], db[f"t_ledger_{tag}"]
        alerts: list = []

        async def alert(level, used, cap):
            alerts.append((level, round(used, 2), cap))

        try:
            return await body(Budget(spend, ledger, alert=alert, now=now), alerts, spend, ledger)
        finally:
            await spend.drop()
            await ledger.drop()
            client.close()

    return asyncio.run(main())


@pytest.fixture(autouse=True)
def small_cap(monkeypatch):
    monkeypatch.setenv("AI_MONTHLY_CAP_INR", "100")
    monkeypatch.setenv("AI_ALERT_PERCENT", "80")


def test_a_reservation_is_replaced_by_the_real_cost():
    async def body(b, alerts, spend, ledger):
        mid = await b.reserve(30)
        assert (await b.status())["used_inr"] == 30
        await b.settle(mid, 30, 12.5, provider="sonnet", task="research", tokens=(1000, 500), estimated=False)
        st = await b.status()
        assert st["used_inr"] == 12.5 and st["spent_inr"] == 12.5 and st["calls"] == 1 and st["by_provider"] == {"sonnet": 12.5} and st["by_task"] == {"research": 12.5}
        row = await ledger.find_one({})
        assert row["tokens_in"] == 1000 and row["cost_inr"] == 12.5 and row["estimated"] is False

    with_budget(body)


def test_a_call_that_would_pass_the_cap_is_refused_and_changes_nothing():
    async def body(b, alerts, spend, ledger):
        await b.reserve(70)
        with pytest.raises(BudgetExceeded):
            await b.reserve(31)
        assert (await b.status())["used_inr"] == 70
        await b.reserve(30)  # exactly up to the cap is allowed
        assert (await b.status())["exhausted"] is True

    with_budget(body)


def test_concurrent_requests_can_never_overshoot_the_cap():
    async def body(b, alerts, spend, ledger):
        results = await asyncio.gather(*[b.reserve(10) for _ in range(50)], return_exceptions=True)
        ok = [r for r in results if isinstance(r, str)]
        assert len(ok) == 10 and all(isinstance(r, BudgetExceeded) for r in results if not isinstance(r, str))
        assert (await b.status())["used_inr"] == 100

    with_budget(body)


def test_a_failed_call_gives_its_reservation_back():
    async def body(b, alerts, spend, ledger):
        mid = await b.reserve(60)
        await b.release(mid, 60)
        assert (await b.status())["used_inr"] == 0
        await b.reserve(60)  # room again

    with_budget(body)


def test_the_alert_is_sent_once_at_80_percent_even_with_many_calls_at_once():
    async def body(b, alerts, spend, ledger):
        await b.reserve(79)
        assert alerts == []
        await asyncio.gather(*[b.reserve(0.5) for _ in range(10)])
        assert [a[0] for a in alerts] == ["80"]
        assert (await b.status())["alert80_sent"] is True

    with_budget(body)


def test_the_stop_alert_is_sent_once_when_the_cap_is_hit():
    async def body(b, alerts, spend, ledger):
        await b.reserve(100)
        for _ in range(5):
            with pytest.raises(BudgetExceeded):
                await b.reserve(1)
        assert [a[0] for a in alerts].count("100") == 1

    with_budget(body)


def test_an_alert_that_cannot_be_sent_never_breaks_the_call():
    async def body(b, alerts, spend, ledger):
        async def broken(*a):
            raise RuntimeError("mail is down")

        b._alert = broken
        assert await b.reserve(90)  # crosses 80% with a broken alert hook: still succeeds

    with_budget(body)


def test_the_budget_is_per_indian_calendar_month():
    ist_end = datetime(2026, 10, 31, 18, 29, tzinfo=timezone.utc)  # 23:59 on 31 Oct in India
    ist_new = datetime(2026, 10, 31, 18, 31, tzinfo=timezone.utc)  # 00:01 on 1 Nov in India
    assert aibudget.month_key(ist_end) == "2026-10" and aibudget.month_key(ist_new) == "2026-11"

    async def body(b, alerts, spend, ledger):
        await b.reserve(100)
        b._now = lambda: ist_new
        assert (await b.status())["month"] == "2026-11" and (await b.status())["used_inr"] == 0
        await b.reserve(50)  # a fresh month, a fresh budget

    with_budget(body, now=lambda: ist_end)


def test_the_owner_can_raise_the_cap_for_a_month():
    async def body(b, alerts, spend, ledger):
        await b.reserve(100)
        await spend.update_one({"_id": b._mid()}, {"$set": {"cap_override_inr": 500}})
        await b.reserve(200)
        assert (await b.status())["cap_inr"] == 500

    with_budget(body)


def test_prices_estimates_and_settings(monkeypatch):
    monkeypatch.delenv("AI_PRICES_JSON", raising=False)
    monkeypatch.delenv("AI_USD_INR", raising=False)
    rate = aibudget.usd_inr()
    assert rate == 97
    assert aibudget.cost_inr("sonnet", 1_000_000, 0) == pytest.approx(2.0 * rate)  # Claude Sonnet 5.5: $2 in, $10 out (Anthropic's price page, read 2026-10-31)
    assert aibudget.cost_inr("sonnet", 0, 1_000_000) == pytest.approx(10.0 * rate)
    assert aibudget.cost_inr("unknown-provider", 0, 1_000_000) == pytest.approx(15.0 * rate)  # not in the table: a cautious price
    monkeypatch.setenv("AI_PRICES_JSON", '{"sonnet": [1, 2]}')
    monkeypatch.setenv("AI_USD_INR", "100")
    assert aibudget.cost_inr("sonnet", 1_000_000, 1_000_000) == pytest.approx(300)
    monkeypatch.setenv("AI_PRICES_JSON", "not json")
    assert aibudget.cost_inr("sonnet", 1_000_000, 0) == pytest.approx(2.0 * 100)  # falls back to the built-in prices, does not crash
    assert aibudget.est_tokens("a" * 320) < aibudget.est_tokens("क" * 320)  # Indian scripts cost more tokens per character
    assert aibudget.file_tokens("application/pdf", 4_000_000) > aibudget.file_tokens("image/png", 4_000_000) == 1500
    assert aibudget.fixed_cost_inr("tts", 2000) > aibudget.fixed_cost_inr("tts", 1000) > 0


# ---- the real call path (ai._metered) ----
def test_a_model_call_is_charged_by_the_providers_own_token_counts(monkeypatch):
    async def body(b, alerts, spend, ledger):
        monkeypatch.setattr(aibudget, "_instance", b)

        async def fake(provider, system, prompt, *, json_mode, image=None):
            ai._USAGE.set((2000, 300))
            return '{"ok": true}'

        monkeypatch.setattr(ai, "_call_text", fake)
        monkeypatch.setattr(ai, "_usable", lambda chain: ["sonnet"])
        monkeypatch.setenv("AI_STUB", "false")
        assert await ai.ask_json("s", "hello", '{"ok": boolean}', purpose="research") == {"ok": True}
        row = await ledger.find_one({})
        assert row["tokens_in"] == 2000 and row["tokens_out"] == 300 and row["estimated"] is False and row["provider"] == "sonnet"
        assert row["cost_inr"] == pytest.approx(aibudget.cost_inr("sonnet", 2000, 300), abs=1e-3)
        assert "prompt" not in row and "answer" not in row  # no content in the ledger

    with_budget(body)


def test_when_the_cap_is_reached_no_provider_is_called_at_all(monkeypatch):
    async def body(b, alerts, spend, ledger):
        monkeypatch.setattr(aibudget, "_instance", b)
        await b.reserve(100)
        calls = []

        async def fake(*a, **k):
            calls.append(a)
            return "{}"

        monkeypatch.setattr(ai, "_call_text", fake)
        monkeypatch.setattr(ai, "_usable", lambda chain: ["gemini", "sonnet", "haiku"])  # a fall-through chain must not keep trying
        monkeypatch.setenv("AI_STUB", "false")
        with pytest.raises(BudgetExceeded):
            await ai.ask_json("s", "hello", "{}")
        assert calls == []

    with_budget(body)


def test_a_failing_provider_is_not_charged_and_falls_through(monkeypatch):
    async def body(b, alerts, spend, ledger):
        monkeypatch.setattr(aibudget, "_instance", b)
        tried = []

        async def fake(provider, system, prompt, *, json_mode, image=None):
            tried.append(provider)
            if provider == "gemini":
                raise RuntimeError("quota")
            ai._USAGE.set((100, 50))
            return '{"ok": 1}'

        monkeypatch.setattr(ai, "_call_text", fake)
        monkeypatch.setattr(ai, "_usable", lambda chain: ["gemini", "haiku"])
        monkeypatch.setenv("AI_STUB", "false")
        assert await ai.ask_json("s", "hello", "{}") == {"ok": 1}
        assert tried == ["gemini", "haiku"] and await ledger.count_documents({"ok": True}) == 1  # only the call that worked was charged
        failed = await ledger.find_one({"ok": False})
        assert failed["provider"] == "gemini" and failed["cost_inr"] == 0.0 and failed["error"] == "RuntimeError"  # the failure is logged for the failure rate, at no cost
        assert (await b.status())["used_inr"] == pytest.approx(aibudget.cost_inr("haiku", 100, 50), abs=0.01)  # status() rounds to 2 decimals

    with_budget(body)


def test_services_priced_by_characters_or_pictures_are_reserved_too(monkeypatch):
    # fixed() uses the shared budget; point it at a local one for the test
    async def local(b, alerts, spend, ledger):
        monkeypatch.setattr(aibudget, "_instance", b)
        async with aibudget.fixed("image", 1, task="image"):
            pass
        with pytest.raises(RuntimeError):
            async with aibudget.fixed("image", 1, task="image"):
                raise RuntimeError("provider failed")
        st = await b.status()
        assert st["by_task"] == {"image": pytest.approx(aibudget.fixed_cost_inr("image", 1), abs=1e-3)} and st["calls"] == 1  # the failed one was released

    with_budget(local)


def test_ensure_available_is_a_clear_503_when_the_month_is_used_up(monkeypatch):
    async def body(b, alerts, spend, ledger):
        monkeypatch.setattr(aibudget, "_instance", b)
        await aibudget.ensure_available()  # fine while there is room
        await b.reserve(100)
        with pytest.raises(HTTPException) as e:
            await aibudget.ensure_available()
        assert e.value.status_code == 503 and "next month" in e.value.detail and e.value.headers["Retry-After"] == "86400"

    with_budget(body)


# ---- through the running app ----
def test_the_scripted_model_is_charged_in_the_shared_monthly_budget(user_a):
    spend = mongo().ai_spend
    mid = aibudget.month_key()
    before = (spend.find_one({"_id": mid}) or {}).get("calls", 0)
    matter_id, title = new_matter(user_a, "Budget")
    upload(user_a, matter_id, "n.txt", "A note.")
    stub("research", answer("Fine."), contains=title)
    assert research(user_a, matter_id).status_code == 200
    doc = spend.find_one({"_id": mid})
    assert doc["calls"] > before and doc["reserved_inr"] > 0 and doc["by_provider"].get("stub", 0) > 0
    row = mongo().ai_ledger.find_one({"provider": "stub", "task": "research"}, sort=[("created_at", -1)])
    assert row and "prompt" not in row

def test_failures_and_latency_are_recorded_without_content():
    async def body(b, alerts, spend, ledger):
        mid = await b.reserve(10)
        await b.settle(mid, 10, 2.0, provider="groq", task="research", tokens=(10, 5), estimated=False, latency_ms=400)
        mid = await b.reserve(10)
        await b.settle(mid, 10, 2.0, provider="groq", task="research", tokens=(10, 5), estimated=False, latency_ms=900)
        await b.record_failure(provider="groq", task="research", latency_ms=1500, error="TimeoutError")
        rel = (await b.reliability())["groq"]
        assert rel["calls"] == 3 and rel["failures"] == 1 and rel["failure_rate_pct"] == 33.3
        assert rel["latency_samples"] == 3 and rel["latency_ms_p95"] == 1500
        assert (await b.status())["spent_inr"] == 4.0  # a failure costs nothing
        assert set((await ledger.find_one({"ok": False})).keys()) <= {"_id", "created_at", "month", "provider", "task", "cost_inr", "ok", "latency_ms", "error"}

    with_budget(body)


def test_each_model_has_its_own_price_and_the_price_changes_on_the_day_google_says(monkeypatch):
    """The numbers are the providers' own (read 2026-10-31): Anthropic, Google and Groq price pages."""
    monkeypatch.delenv("AI_PRICES_JSON", raising=False)
    assert aibudget.price_for("claude-sonnet-5-5") == (2.0, 10.0)
    assert aibudget.price_for("anthropic/claude-sonnet-5.5") == (2.0, 10.0)  # the OpenRouter spelling of the same model
    assert aibudget.price_for("claude-haiku-4-5-20251001") == (1.0, 5.0)
    assert aibudget.price_for("claude-haiku-5-5", 50_000) == (0.10, 0.50)
    assert aibudget.price_for("claude-haiku-5-5", 150_000) == (0.50, 2.50)  # prompts over 100,000 tokens cost more
    assert aibudget.price_for("gpt-oss-120b") == (0.15, 0.60) and aibudget.price_for("openai/gpt-oss-20b") == (0.075, 0.30)
    assert aibudget.price_for("gemini-3.5-flash-lite") == (0.30, 2.50)
    assert aibudget.price_for("gemini-2.5-flash-lite") == (0.10, 0.40) and aibudget.price_for("gemini-2.5-flash") == (0.30, 2.50)  # the longer name wins
    assert aibudget.price_for("gemini-3.8-flash", today="2026-12-31") == (0.75, 3.75)
    assert aibudget.price_for("gemini-3.8-flash", today="2027-01-01") == (1.50, 7.50)  # Google's announced doubling
    assert aibudget.price_for("some-model-nobody-listed") is None
    monkeypatch.setenv("AI_USD_INR", "100")
    assert aibudget.cost_inr("gemini", 1_000_000, 0, "gemini-3.8-flash", today="2027-02-01") == pytest.approx(150)
    assert aibudget.cost_inr("anthropic", 1_000_000, 0, "claude-haiku-4-5-20251001") == pytest.approx(100)
    assert aibudget.cost_inr("ollama", 5_000_000, 5_000_000, "anything") == 0.0
