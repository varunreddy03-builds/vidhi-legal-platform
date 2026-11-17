"""The optional local model (only ever for low-risk tasks, only when switched on), the page cap on automatic reading, and failures that must not be retried."""

import asyncio

import pytest

from lib import ai, aibudget, ocr_engine
from tests.conftest import mongo, new_matter, upload
from tests.test_jobs_and_scans import job, run_jobs, upload_scan
from tests.test_legal_data import source
from tests.test_admin import admin  # noqa: F401  (fixture)
from tests.test_ocr import scanned_pdf


@pytest.fixture
def local(monkeypatch):
    for k in ("AI_ROUTE", "AI_ROUTE_FREE", "AI_ROUTE_RESEARCH", "AI_ROUTE_TRANSLATE_QUERY", "AI_LOCAL_TASKS_FIRST"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-not-real")
    monkeypatch.setenv("GROQ_API_KEY", "dummy-not-real")
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "tiny-test-model")


def test_the_local_model_is_not_in_any_chain_unless_it_is_configured_and_the_task_is_low_risk(monkeypatch, local):
    monkeypatch.delenv("OLLAMA_MODEL")
    assert not ai.provider_configured("ollama")
    monkeypatch.setenv("AI_ROUTE_TRANSLATE_QUERY", "ollama,gemini")
    assert "ollama" not in ai.route_for("translate-query")  # no model name: not configured
    monkeypatch.setenv("OLLAMA_MODEL", "tiny-test-model")
    assert ai.provider_configured("ollama") and ai.route_for("translate-query") == ["ollama", "gemini"]


def test_the_local_model_can_never_be_routed_a_high_risk_task_whatever_the_settings_say(monkeypatch, local):
    for purpose in ("research", "synthesize", "analyze-contract", "analyze-evidence", "recovery-notice", "recovery-extract", "translate", "ocr"):
        monkeypatch.setenv("AI_ROUTE_" + purpose.upper().replace("-", "_"), "ollama,gemini")
        monkeypatch.setenv("AI_LOCAL_TASKS_FIRST", "true")
        assert "ollama" not in ai.route_for(purpose), purpose
        assert "ollama" not in ai.route_for(purpose, tier="free"), purpose
    for purpose in ("research", "synthesize", "analyze-contract", "analyze-evidence", "recovery-notice", "recovery-extract", "translate", "ocr"):
        monkeypatch.delenv("AI_ROUTE_" + purpose.upper().replace("-", "_"))
    monkeypatch.setenv("AI_ROUTE", "ollama")
    with pytest.raises(ai.AIError):
        ai.route_for("research")  # a chain made only of a refused local model is "no provider", not a silent use of it


def test_local_first_is_opt_in_and_keeps_the_hosted_models_as_fallback(monkeypatch, local):
    assert ai.route_for("translate-query", tier="free")[0] == "gemini"  # default: unchanged
    monkeypatch.setenv("AI_LOCAL_TASKS_FIRST", "true")
    assert ai.route_for("translate-query", tier="free") == ["ollama", "gemini", "groq"]
    assert ai.route_for("research", tier="free") == ["gemini", "groq"]  # other tasks untouched
    assert "ollama" not in ai.route_for("research")


def test_a_local_call_sends_a_text_only_json_request_and_records_real_usage(monkeypatch, local):
    sent = {}

    async def fake(payload):
        sent.update(payload)
        return {"message": {"content": ' {"english": "hello"} '}, "prompt_eval_count": 42, "eval_count": 7}

    monkeypatch.setattr(ai, "_ollama_chat", fake)
    async def call():  # the usage record lives in the task's own context, so read it inside the same task
        ai._USAGE.set(None)
        return await ai._call_text("ollama", "SYS", "PROMPT", json_mode=True), ai._USAGE.get()

    out, usage = asyncio.run(call())
    assert out == '{"english": "hello"}' and usage == (42, 7)
    assert sent["model"] == "tiny-test-model" and sent["stream"] is False and sent["format"] == "json" and [m["role"] for m in sent["messages"]] == ["system", "user"]
    with pytest.raises(RuntimeError, match="text-only"):
        asyncio.run(ai._call_text("ollama", "s", "p", json_mode=False, image=("abc", "image/png")))


def test_the_local_server_address_must_be_http_or_https(monkeypatch, local):
    monkeypatch.setenv("OLLAMA_URL", "file:///etc/passwd")
    with pytest.raises(RuntimeError, match="http"):
        asyncio.run(ai._ollama_chat({"model": "m"}))


def test_a_local_model_costs_nothing_per_token_in_the_spend_cap_and_hosted_models_still_do():
    assert aibudget.cost_inr("ollama", 5_000_000, 5_000_000) == 0.0
    assert aibudget.cost_inr("sonnet", 1_000_000, 0) > 0 and aibudget.cost_inr("gemini", 0, 1_000_000) > 0


# ---- the page cap ----

def test_a_pdf_longer_than_the_limit_is_refused_before_any_reading(monkeypatch):
    monkeypatch.setenv("OCR_MAX_PAGES", "2")
    assert ocr_engine.max_pages() == 2
    with pytest.raises(ValueError, match="3 pages.*longer than 2 pages"):
        asyncio.run(ocr_engine.read_pdf("s", scanned_pdf(3)))
    monkeypatch.setenv("OCR_MAX_PAGES", "banana")
    assert ocr_engine.max_pages() == 60


def test_an_overlong_scan_in_a_matter_fails_with_a_clear_message_and_no_ai_call(user_a):
    mid, _ = new_matter(user_a, "Long")
    doc = upload(user_a, mid, "long.pdf", scanned_pdf(61))
    assert doc["processing_status"] == "FAILED" and "61 pages" in doc["failure_reason"] and "Split it" in doc["failure_reason"]
    assert mongo().ai_calls.count_documents({"prompt": {"$regex": f"doc-scan-{mid}"}}) == 0


def test_an_overlong_law_scan_is_failed_at_once_and_never_retried(admin):  # noqa: F811
    src = source(admin)
    jid = upload_scan(admin, src, content=scanned_pdf(61)).json()["job_id"]
    assert run_jobs(admin) == {"done": 0, "failed": 1}
    j = job(jid)
    assert j["state"] == "failed" and j["attempts"] == 1 and j["last_error"].startswith("not retried: ") and "61 pages" in j["last_error"]
    assert mongo().legal_documents.count_documents({"source_id": src["id"]}) == 0