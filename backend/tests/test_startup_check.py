"""The startup check names missing settings (never their values) and stops a live site, but not a laptop."""

import pytest

from lib import startup_check as sc

ALL = {"MONGO_URL": "m", "DB_NAME": "d", "APP_URL": "https://x.example.in", "CORS_ORIGINS": "https://x.example.in", "LINK_SECRET": "l", "WEBHOOK_CRON_SECRET": "w", "DATA_ENCRYPTION_KEY": "k", "GEMINI_API_KEY": "g"}
GROUP = ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "NVIDIA_API_KEY", "MISTRAL_API_KEY", "ZAI_API_KEY")


def setenv(monkeypatch, **kw):
    for n in list(ALL) + list(GROUP) + ["COOKIE_SECURE", "ENABLE_DOCS"]:  # the test runner sets some of these for its own server: start from a clean slate
        monkeypatch.delenv(n, raising=False)
    for k, v in {**ALL, **kw}.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


def test_nothing_missing_is_fine(monkeypatch):
    setenv(monkeypatch)
    assert sc.missing() == []
    sc.enforce()


def test_a_live_site_will_not_start_and_the_message_has_names_not_values(monkeypatch):
    setenv(monkeypatch, DATA_ENCRYPTION_KEY=None, LINK_SECRET="", GEMINI_API_KEY=None, MONGO_URL="mongodb://u:supersecretpw@h/db")  # secret-scan: ok (fake test value)
    with pytest.raises(RuntimeError) as e:
        sc.enforce()
    msg = str(e.value)
    assert "DATA_ENCRYPTION_KEY" in msg and "LINK_SECRET" in msg and "GEMINI_API_KEY or GROQ_API_KEY" in msg
    assert "supersecretpw" not in msg


def test_a_laptop_only_warns(monkeypatch, caplog):
    setenv(monkeypatch, APP_URL="http://localhost:3000", DATA_ENCRYPTION_KEY=None)
    sc.enforce()  # does not raise
    assert "DATA_ENCRYPTION_KEY" in caplog.text


def test_a_live_site_refuses_a_wildcard_origin_insecure_cookies_and_open_api_docs(monkeypatch):
    setenv(monkeypatch, CORS_ORIGINS="https://x.example.in, *")
    assert any(m.startswith("CORS_ORIGINS") for m in sc.missing())
    setenv(monkeypatch, COOKIE_SECURE="false")
    assert any(m.startswith("COOKIE_SECURE") for m in sc.missing())
    setenv(monkeypatch, ENABLE_DOCS="true")
    assert any(m.startswith("ENABLE_DOCS") for m in sc.missing())
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    monkeypatch.delenv("ENABLE_DOCS", raising=False)
    setenv(monkeypatch, APP_URL="http://localhost:3000", CORS_ORIGINS="*", COOKIE_SECURE="false")
    assert not any(m.startswith(("CORS_ORIGINS", "COOKIE_SECURE")) for m in sc.missing())  # a laptop may do all three


def test_one_model_provider_is_enough(monkeypatch):
    setenv(monkeypatch, GEMINI_API_KEY=None, GROQ_API_KEY="x")
    assert sc.missing() == []
