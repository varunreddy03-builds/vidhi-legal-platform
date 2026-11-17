"""Regression: the scripted model used by the other tests never reaches the Anthropic library, so a call the library would refuse went unnoticed until a real key was tried
(`AsyncMessages.create() got an unexpected keyword argument 'temperature'`: every Sonnet and Haiku request failed). This checks the real call's arguments against the installed library."""

import asyncio
import inspect
import types

import pytest


@pytest.mark.parametrize("provider", ["sonnet", "haiku"])
@pytest.mark.parametrize("json_mode", [True, False])
def test_a_claude_request_sends_only_what_the_installed_library_accepts(monkeypatch, provider, json_mode):
    import anthropic

    from lib import ai

    allowed = set(inspect.signature(anthropic.resources.messages.AsyncMessages.create).parameters)
    seen: dict = {}

    class Messages:
        async def create(self, **kwargs):
            seen.update(kwargs)
            unknown = set(kwargs) - allowed
            if unknown:
                raise TypeError(f"unexpected keyword argument(s) {sorted(unknown)}")
            return types.SimpleNamespace(content=[types.SimpleNamespace(text='{"ok": true}')], usage=None)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key-for-tests")
    monkeypatch.setattr(ai, "_anthropic_client", lambda: types.SimpleNamespace(messages=Messages()))
    assert asyncio.run(ai._call_text(provider, "system text", "question", json_mode=json_mode)) == '{"ok": true}'
    assert "temperature" not in seen and seen["model"] and seen["messages"]
