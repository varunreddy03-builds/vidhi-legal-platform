"""A live site (https APP_URL) must not start with a test-only fake switched on; local and test setups (http) are unaffected."""

import pytest

from lib.stand_ins import STAND_INS, refuse_on_live_site


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in STAND_INS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("name", STAND_INS)
def test_every_stand_in_stops_a_live_site(monkeypatch, name):
    monkeypatch.setenv("APP_URL", "https://vidhi.example")
    monkeypatch.setenv(name, "true")
    with pytest.raises(RuntimeError, match=name):
        refuse_on_live_site()


def test_the_message_names_the_switch_and_never_a_value(monkeypatch):
    monkeypatch.setenv("APP_URL", "https://vidhi.example")
    monkeypatch.setenv("EMAIL_DRY_RUN", "true")
    monkeypatch.setenv("RESEND_API_KEY", "re_secret_value_not_to_be_shown")
    with pytest.raises(RuntimeError) as e:
        refuse_on_live_site()
    assert "EMAIL_DRY_RUN" in str(e.value) and "re_secret" not in str(e.value)


@pytest.mark.parametrize("app_url,flag", [("http://localhost:3000", "true"), ("", "true"), ("https://vidhi.example", "false"), ("https://vidhi.example", ""), ("HTTPS://VIDHI.EXAMPLE", "false")])
def test_local_setups_and_a_clean_live_site_start_normally(monkeypatch, app_url, flag):
    monkeypatch.setenv("APP_URL", app_url)
    if flag:
        monkeypatch.setenv("AI_STUB", flag)
    refuse_on_live_site()


def test_the_check_ignores_case_in_the_address_and_the_value(monkeypatch):
    monkeypatch.setenv("APP_URL", "HTTPS://Vidhi.Example")
    monkeypatch.setenv("PAYMENTS_STUB", "TRUE")
    with pytest.raises(RuntimeError, match="PAYMENTS_STUB"):
        refuse_on_live_site()
