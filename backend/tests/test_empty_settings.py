"""A setting that is present but EMPTY must mean "not set": the code's default applies. A deployment file can hold `NAME=` lines, and a number read straight from an empty value raises.
(Found on the first live deployment: AI_USD_INR= made the cost estimate raise, so every AI call was refused before it began.)"""

import pytest

from lib import ai, aibudget


def test_an_empty_exchange_rate_means_the_default(monkeypatch):
    monkeypatch.setenv("AI_USD_INR", "")
    assert aibudget.usd_inr() == 97.0
    monkeypatch.setenv("AI_USD_INR", "88.5")
    assert aibudget.usd_inr() == 88.5  # a real value still wins
    monkeypatch.delenv("AI_USD_INR")
    assert aibudget.usd_inr() == 97.0


def test_a_call_can_be_priced_when_the_price_settings_are_empty(monkeypatch):
    for name in ("AI_USD_INR", "AI_PRICE_TTS_PER_1K_CHARS_USD", "AI_PRICE_STT_PER_MIN_USD", "AI_PRICE_IMAGE_USD"):
        monkeypatch.setenv(name, "")
    assert aibudget.fixed_cost_inr("tts", 1000) == pytest.approx(0.30 * 97)
    assert aibudget.fixed_cost_inr("stt", 1_000_000) == pytest.approx(0.40 * 97)
    assert aibudget.fixed_cost_inr("image", 1) == pytest.approx(0.08 * 97)
    assert aibudget.cost_inr("gemini", 1000, 1000, "gemini-3.5-flash-lite") > 0  # the estimate the spending cap needs before every call


def test_an_empty_long_prompt_limit_does_not_break_the_choice_of_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    for name in ("AI_ROUTE", "AI_ROUTE_RESEARCH", "AI_LONG_PROMPT_CHARS"):
        monkeypatch.setenv(name, "")
    assert "gemini" in ai.route_for("research", 10, tier="pro")  # a short prompt
    assert ai.route_for("research", 10_000_000, tier="pro")[0] == "gemini"  # a very long one: the long-context model first, from the default limit


@pytest.mark.parametrize("name", ["OCR_MAX_PAGES", "CLAMD_PORT"])
def test_the_other_numeric_settings_already_fall_back_when_empty(monkeypatch, name):
    from lib import malware_scan, ocr_engine

    monkeypatch.setenv(name, "")
    assert ocr_engine.max_pages() == 60
    assert malware_scan._address()[1] == 3310
