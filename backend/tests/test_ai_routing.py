"""Model routing: Haiku for research, Gemini / Sonnet behind it, automatic fall-through, and no model switch can
change how a claim is verified. No provider is contacted: `_call_text` is replaced by a recorder."""

import pytest

from lib import ai


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("AI_STUB", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-test")
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)  # the real .env may carry the key under this name
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_MODEL", raising=False)
    for k in ("MISTRAL_API_KEY", "MISTRAL_MODEL", "ZAI_API_KEY", "ZAI_MODEL"):  # real keys in .env must not make these providers look configured
        monkeypatch.delenv(k, raising=False)
    for k in ("AI_ROUTE", "AI_ROUTE_RESEARCH", "AI_ROUTE_OCR", "AI_ROUTE_FREE", "GEMINI_MODEL", "GEMINI_FREE_MODEL", "ANTHROPIC_SONNET_MODEL", "ANTHROPIC_HAIKU_MODEL", "GROQ_API_KEY", "GROQ_MODEL", "GROQ_FREE_MODEL", "OPENROUTER_API_KEY", "OPENROUTER_SONNET_MODEL", "OPENROUTER_HAIKU_MODEL"):
        monkeypatch.delenv(k, raising=False)
    ai._health.clear()
    yield
    ai._health.clear()


def script(monkeypatch, plan: dict):
    """plan: provider -> list of replies (str, or Exception to raise). Returns the call log."""
    log: list[tuple[str, str]] = []

    async def fake(provider, system, prompt, *, json_mode, image=None):
        log.append((provider, prompt))
        r = plan[provider].pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(ai, "_call_text", fake)
    return log


async def test_each_task_goes_to_the_model_that_suits_it(monkeypatch):
    assert ai.route_for("research") == ["haiku", "gemini", "sonnet"]
    assert ai.route_for("recovery-notice") == ["sonnet", "gemini", "haiku"]
    assert ai.route_for("synthesize")[0] == "sonnet" and ai.route_for("analyze-contract")[0] == "sonnet"
    assert ai.route_for("analyze-evidence")[0] == "haiku" and ai.route_for("recovery-extract")[0] == "haiku"
    assert ai.route_for("ocr")[0] == "gemini" and ai.route_for("something-new")[0] == "gemini"
    assert ai.task_of("generic", "recovery-notice-abc") == "recovery-notice" and ai.task_of("generic", "x") == "generic"
    assert ai.task_of("research", "recovery-notice-abc") == "research"


async def test_a_very_long_input_goes_to_gemini_first(monkeypatch):
    assert ai.route_for("synthesize", prompt_chars=50_000)[0] == "sonnet"
    assert ai.route_for("synthesize", prompt_chars=500_000) == ["gemini", "sonnet", "haiku"]
    monkeypatch.setenv("AI_ROUTE_SYNTHESIZE", "sonnet,gemini")  # an explicit route is never reordered
    assert ai.route_for("synthesize", prompt_chars=500_000) == ["sonnet", "gemini"]
    monkeypatch.setenv("AI_ROUTE_ANALYZE_CONTRACT", "haiku")
    assert ai.route_for("analyze-contract") == ["haiku"]


async def test_research_goes_to_haiku_first_everything_else_to_gemini_first(monkeypatch):
    log = script(monkeypatch, {"haiku": ['{"a": 1}'], "gemini": ['{"b": 2}']})
    assert await ai.ask_json("s", "q", "{}", purpose="research") == {"a": 1}
    assert await ai.ask_json("s", "q", "{}", purpose="analyze") == {"b": 2}
    assert [p for p, _ in log] == ["haiku", "gemini"]


async def test_a_failing_model_falls_through_to_the_next_in_the_chain(monkeypatch):
    log = script(monkeypatch, {"haiku": [RuntimeError("overloaded")], "gemini": ["not json", "still not"], "sonnet": ['{"ok": true}']})
    assert await ai.ask_json("s", "q", "{}", purpose="research") == {"ok": True}
    assert [p for p, _ in log] == ["haiku", "gemini", "gemini", "sonnet"]  # haiku errored once; gemini got its two tries


async def test_all_models_failing_raises_and_names_who_was_tried(monkeypatch):
    script(monkeypatch, {"haiku": [RuntimeError("x")], "gemini": [RuntimeError("x")], "sonnet": [RuntimeError("x")]})
    with pytest.raises(ai.AIError, match="haiku, gemini, sonnet"):
        await ai.ask_json("s", "q", "{}", purpose="research")


async def test_unconfigured_providers_are_skipped(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    log = script(monkeypatch, {"gemini": ['{"a": 1}']})
    assert await ai.ask_json("s", "q", "{}", purpose="research") == {"a": 1}
    assert [p for p, _ in log] == ["gemini"]
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(ai.AIError, match="no AI provider is configured"):
        await ai.ask_json("s", "q", "{}", purpose="research")


async def test_routes_are_configurable_per_purpose_and_globally(monkeypatch):
    monkeypatch.setenv("AI_ROUTE", "sonnet,gemini")
    monkeypatch.setenv("AI_ROUTE_RESEARCH", "gemini , haiku,bogus")
    assert ai.route_for("research") == ["gemini", "haiku"]
    assert ai.route_for("analyze") == ["sonnet", "gemini"]


async def test_a_provider_that_keeps_failing_is_skipped_for_a_while_then_retried(monkeypatch):
    plan = {"haiku": [RuntimeError("x")] * 3, "gemini": ['{"n": %d}' % i for i in range(5)], "sonnet": []}
    log = script(monkeypatch, plan)
    for _ in range(3):
        await ai.ask_json("s", "q", "{}", purpose="research")
    assert [p for p, _ in log].count("haiku") == 3
    await ai.ask_json("s", "q", "{}", purpose="research")  # haiku is now cooling down: straight to gemini
    assert [p for p, _ in log][-1] == "gemini" and [p for p, _ in log].count("haiku") == 3
    ai._health["haiku"][1] = 0.0  # cooldown over
    plan["haiku"] = ['{"back": true}']
    assert await ai.ask_json("s", "q", "{}", purpose="research") == {"back": True}


async def test_default_model_ids_and_overrides(monkeypatch):
    assert ai.provider_model("sonnet") == "claude-sonnet-5-5" and ai.provider_model("haiku") == "claude-haiku-4-5-20251001"
    monkeypatch.setenv("ANTHROPIC_HAIKU_MODEL", "claude-haiku-9")
    assert ai.provider_model("haiku") == "claude-haiku-9"


async def test_image_reading_falls_through_too(monkeypatch):
    log = script(monkeypatch, {"gemini": [RuntimeError("quota")], "haiku": ["  Receipt Rs 500 "]})
    assert await ai.read_image_text("s", "QUJD", "read", "image/png") == "Receipt Rs 500"
    assert [p for p, _ in log] == ["gemini", "haiku"]


async def test_anthropic_request_shape(monkeypatch):
    seen = {}

    class Msgs:
        async def create(self, **kw):
            seen.update(kw)
            return type("R", (), {"content": [type("B", (), {"text": '{"x": 1}'})()]})()

    monkeypatch.setattr(ai, "_anthropic_client", lambda: type("C", (), {"messages": Msgs()})())
    out = await ai._call_text("haiku", "SYS", "PROMPT", json_mode=True, image=("QUJD", "image/png"))
    assert out == '{"x": 1}'
    assert seen["model"] == "claude-haiku-4-5-20251001" and seen["system"] == "SYS"
    blocks = seen["messages"][0]["content"]
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/png" and blocks[1]["text"] == "PROMPT"


# ---------------------------------------------------------------------------------------------
# Free plan, Groq and OpenRouter
# ---------------------------------------------------------------------------------------------
async def test_the_free_plan_only_ever_gets_the_light_models(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    assert ai.route_for("synthesize", tier="free") == ["gemini", "groq"]  # never Sonnet/Haiku, whatever the task
    assert ai.route_for("research")[:1] == ["haiku"]  # the paid plan still follows the task table
    monkeypatch.setenv("AI_ROUTE_FREE", "haiku,sonnet,groq")
    assert ai.route_for("research", tier="free") == ["groq"]  # even a mistaken setting cannot send free users to Claude
    assert ai.provider_model("gemini", "free") == "gemini-3.5-flash-lite" and ai.provider_model("gemini", "full") == "gemini-3.8-flash"
    assert ai.provider_model("groq", "free") == "openai/gpt-oss-20b" and ai.provider_model("groq", "full") == "openai/gpt-oss-120b"


async def test_ask_json_tier_selects_the_models_that_are_called(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    seen = []

    async def fake(provider, system, prompt, *, json_mode, image=None):
        seen.append((provider, ai.provider_model(provider)))
        return '{"ok": 1}'

    monkeypatch.setattr(ai, "_call_text", fake)
    await ai.ask_json("s", "q", "{}", purpose="synthesize", tier="free")
    await ai.ask_json("s", "q", "{}", purpose="synthesize")
    assert seen == [("gemini", "gemini-3.5-flash-lite"), ("sonnet", "claude-sonnet-5-5")]


async def test_groq_request_shape_and_text_only(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gk-test")
    sent = {}

    async def fake_post(url, key, payload, extra_headers=None):
        sent.update(url=url, key=key, payload=payload)
        return {"choices": [{"message": {"content": '{"x": 2}'}}]}

    monkeypatch.setattr(ai, "_post_chat", fake_post)
    out = await ai._call_text("groq", "SYS", "PROMPT", json_mode=True)
    assert out == '{"x": 2}' and sent["url"].startswith("https://api.groq.com/openai/v1") and sent["key"] == "gk-test"
    assert sent["payload"]["model"] == "openai/gpt-oss-120b" and sent["payload"]["response_format"] == {"type": "json_object"}
    assert sent["payload"]["messages"][0] == {"role": "system", "content": "SYS"}
    with pytest.raises(RuntimeError):
        await ai._call_text("groq", "SYS", "PROMPT", json_mode=False, image=("QUJD", "image/png"))


async def test_sonnet_and_haiku_go_through_openrouter_when_there_is_no_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    sent = []

    async def fake_post(url, key, payload, extra_headers=None):
        sent.append((url, key, payload["model"], bool(payload.get("response_format")), extra_headers))
        return {"choices": [{"message": {"content": "  Receipt Rs 5  "}}]}

    monkeypatch.setattr(ai, "_post_chat", fake_post)
    assert ai.provider_configured("sonnet") and ai.provider_configured("haiku")
    assert await ai._call_text("haiku", "S", "P", json_mode=True, image=("QUJD", "image/png")) == "Receipt Rs 5"
    assert await ai._call_text("sonnet", "S", "P", json_mode=True) == "Receipt Rs 5"
    assert [(u, k, m, rf) for u, k, m, rf, _ in sent] == [
        ("https://openrouter.ai/api/v1/chat/completions", "or-test", "anthropic/claude-haiku-5.5", False),
        ("https://openrouter.ai/api/v1/chat/completions", "or-test", "anthropic/claude-sonnet-5.5", False),
    ]
    assert sent[0][4]["X-Title"] == "VIDHI"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-test")  # with an Anthropic key the direct route is used again
    assert ai._claude_transport() == "anthropic" and ai.provider_model("sonnet") == "claude-sonnet-5-5"


async def test_groq_is_the_last_fallback_but_never_used_for_images(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    assert ai.route_for("research")[-1] == "groq" and "groq" not in ai.route_for("ocr")
    log = script(monkeypatch, {"haiku": [RuntimeError("x")], "gemini": [RuntimeError("x")], "sonnet": [RuntimeError("x")], "groq": ['{"from": "groq"}']})
    assert await ai.ask_json("s", "q", "{}", purpose="research") == {"from": "groq"}
    assert [p for p, _ in log] == ["haiku", "gemini", "sonnet", "groq"]


def test_the_claude_key_may_be_named_claude_api_key(monkeypatch):
    """The owner's .env used CLAUDE_API_KEY; the code must treat it as the Anthropic key, and ANTHROPIC_API_KEY wins if both exist."""
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert ai.claude_key() == "" and ai._claude_transport() == "openrouter"
    monkeypatch.setenv("CLAUDE_API_KEY", "alias-key")
    assert ai.claude_key() == "alias-key" and ai._claude_transport() == "anthropic"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "main-key")
    assert ai.claude_key() == "main-key"


# ---------------------------------------------------------------------------------------------
# NVIDIA's hosted models
# ---------------------------------------------------------------------------------------------
async def test_nvidia_is_used_only_with_a_key_and_comes_last_in_the_paid_chains(monkeypatch):
    assert "nvidia" not in ai.route_for("research")  # no key: never tried
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    assert ai.route_for("research") == ["haiku", "gemini", "sonnet", "groq", "nvidia"]
    assert ai.route_for("synthesize")[-1] == "nvidia" and ai.route_for("translate")[-1] == "nvidia"
    assert "nvidia" not in ai.route_for("ocr")  # it reads text only, so it is not in the picture-reading chain
    assert "nvidia" not in ai.route_for("research", tier="free")  # the free plan keeps its two light models
    monkeypatch.setenv("AI_ROUTE_RESEARCH", "nvidia,groq")
    assert ai.route_for("research") == ["nvidia", "groq"]  # the owner can put it first


async def test_nvidia_request_shape_model_setting_and_text_only(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    sent = {}

    async def fake_post(url, key, payload, extra_headers=None):
        sent.update(url=url, key=key, payload=payload)
        return {"choices": [{"message": {"content": '{"x": 3}'}}], "usage": {"prompt_tokens": 11, "completion_tokens": 4}}

    monkeypatch.setattr(ai, "_post_chat", fake_post)
    out = await ai._call_text("nvidia", "SYS", "PROMPT", json_mode=True)
    assert out == '{"x": 3}' and sent["url"] == "https://integrate.api.nvidia.com/v1/chat/completions" and sent["key"] == "nv-test"
    assert sent["payload"]["model"] == "mistralai/mistral-large-4-1t-a52b"
    assert "response_format" not in sent["payload"]  # not every hosted model accepts it; ask_json checks the reply itself
    assert sent["payload"]["messages"][0] == {"role": "system", "content": "SYS"}
    monkeypatch.setenv("NVIDIA_MODEL", "nvidia/llama-3.1-nemotron-70b-instruct")
    assert ai.provider_model("nvidia") == "nvidia/llama-3.1-nemotron-70b-instruct"
    with pytest.raises(RuntimeError):
        await ai._call_text("nvidia", "SYS", "PROMPT", json_mode=False, image=("QUJD", "image/png"))


async def test_a_failing_nvidia_does_not_stop_the_chain_and_an_unlisted_price_is_cautious(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    monkeypatch.setenv("AI_ROUTE_RESEARCH", "nvidia,gemini")
    calls = script(monkeypatch, {"nvidia": [RuntimeError("503")], "gemini": ['{"ok": 1}']})
    assert await ai.ask_json("s", "q", "{}", purpose="research") == {"ok": 1}
    assert [p for p, _ in calls] == ["nvidia", "gemini"]
    from lib import aibudget

    assert aibudget.price_for("mistralai/mistral-large-4-1t-a52b") is None  # NVIDIA's hosted price is UNVERIFIED, so the budget uses its cautious default
    assert aibudget.cost_inr("nvidia", 1_000_000, 0, "mistralai/mistral-large-4-1t-a52b") > 0


# ---------------------------------------------------------------------------------------------
# Mistral and Z.ai
# ---------------------------------------------------------------------------------------------
async def test_mistral_and_zai_are_used_only_with_a_key_and_sit_between_groq_and_nvidia(monkeypatch):
    for k in ("MISTRAL_API_KEY", "ZAI_API_KEY", "NVIDIA_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert "mistral" not in ai.route_for("research") and "zai" not in ai.route_for("research")  # no key: never tried
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("MISTRAL_API_KEY", "m-test")
    monkeypatch.setenv("ZAI_API_KEY", "z-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    assert ai.route_for("research") == ["haiku", "gemini", "sonnet", "groq", "mistral", "zai", "nvidia"]
    assert "mistral" not in ai.route_for("ocr") and "zai" not in ai.route_for("ocr")  # text only
    assert "mistral" not in ai.route_for("research", tier="free") and "zai" not in ai.route_for("research", tier="free")


@pytest.mark.parametrize("provider,url,key_env,model,model_env,default_json", [
    ("mistral", "https://api.mistral.ai/v1/chat/completions", "MISTRAL_API_KEY", "mistral-small-latest", "MISTRAL_MODEL", True),
    ("zai", "https://api.z.ai/api/paas/v4/chat/completions", "ZAI_API_KEY", "glm-4.5-flash", "ZAI_MODEL", False),
])
async def test_mistral_and_zai_request_shape_model_setting_and_text_only(monkeypatch, provider, url, key_env, model, model_env, default_json):
    monkeypatch.setenv(key_env, "k-test")
    sent = {}

    async def fake_post(u, key, payload, extra_headers=None):
        sent.update(url=u, key=key, payload=payload)
        return {"choices": [{"message": {"content": '{"x": 3}'}}], "usage": {"prompt_tokens": 11, "completion_tokens": 4}}

    monkeypatch.setattr(ai, "_post_chat", fake_post)
    assert await ai._call_text(provider, "SYS", "PROMPT", json_mode=True) == '{"x": 3}'
    assert sent["url"] == url and sent["key"] == "k-test" and sent["payload"]["model"] == model
    assert ("response_format" in sent["payload"]) is default_json
    monkeypatch.setenv(model_env, "other-model")
    assert ai.provider_model(provider) == "other-model"
    with pytest.raises(RuntimeError):
        await ai._call_text(provider, "SYS", "PROMPT", json_mode=False, image=("QUJD", "image/png"))
