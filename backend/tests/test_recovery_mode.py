"""The Legal Recovery switch (lib/recovery_mode.py). Off, the default: the email send routes answer 'not available'. On (the test server): everything works as before.
Also the three follow-up dates the person types in the guide."""

import pytest
from fastapi import HTTPException

from lib import recovery_mode
from tests.conftest import verify_email


@pytest.fixture
def verified_a(user_a):
    verify_email(user_a)
    return user_a


def new_case(c) -> str:
    r = c.post("/recovery/cases", json={"creditor_name": "Invented Traders", "debtor_name": "Invented Buyer Ltd", "amount": 52000, "currency": "INR"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.mark.parametrize("raw,on", [(None, False), ("", False), ("false", False), ("0", False), ("no", False), ("true", True), ("TRUE", True), ("1", True), ("on", True)])
def test_the_switch_is_off_unless_it_is_clearly_turned_on(monkeypatch, raw, on):
    if raw is None:
        monkeypatch.delenv("RECOVERY_FULL_FLOW", raising=False)
    else:
        monkeypatch.setenv("RECOVERY_FULL_FLOW", raw)
    assert recovery_mode.full_flow() is on


def test_with_the_switch_off_the_send_routes_say_not_available(monkeypatch):
    monkeypatch.delenv("RECOVERY_FULL_FLOW", raising=False)
    with pytest.raises(HTTPException) as e:
        recovery_mode.require_full_flow()
    assert e.value.status_code == 404 and "not available" in e.value.detail
    monkeypatch.setenv("RECOVERY_FULL_FLOW", "true")
    assert recovery_mode.require_full_flow() is None


def test_both_email_send_routes_carry_the_switch_and_nothing_else_does():
    import importlib
    import pkgutil

    import routers

    gated = set()
    for mod in pkgutil.iter_modules(routers.__path__):
        router = getattr(importlib.import_module(f"routers.{mod.name}"), "router", None)
        for route in getattr(router, "routes", []):
            deps = getattr(getattr(route, "dependant", None), "dependencies", [])
            if any(d.call is recovery_mode.require_full_flow for d in deps):
                gated.add(route.path)
    assert gated == {"/recovery/cases/{case_id}/email/prepare", "/recovery/cases/{case_id}/email"}


def test_the_server_reports_the_switch_and_with_it_on_the_send_route_works_as_before(verified_a):
    assert verified_a.get("/recovery/options").json() == {"full_flow": True}  # the test server runs with the switch on
    cid = new_case(verified_a)
    r = verified_a.post(f"/recovery/cases/{cid}/email/prepare", json={"to": "buyer@example.com"})
    assert r.status_code != 404  # reached the real route (which refuses for its own reasons: there is no notice yet)


def test_the_three_dates_are_saved_cleared_and_checked(verified_a, user_b):
    cid = new_case(verified_a)
    r = verified_a.patch(f"/recovery/cases/{cid}/guide", json={"tracker": {"notice_date": "2026-11-01", "due_date": "2026-11-16"}})
    assert r.status_code == 200 and r.json()["guide"]["tracker"] == {"notice_date": "2026-11-01", "due_date": "2026-11-16"}
    r = verified_a.patch(f"/recovery/cases/{cid}/guide", json={"tracker": {"next_date": "2026-12-01", "due_date": ""}})
    assert r.json()["guide"]["tracker"] == {"notice_date": "2026-11-01", "next_date": "2026-12-01"}  # an empty value clears that date, the others stay
    assert verified_a.patch(f"/recovery/cases/{cid}/guide", json={"tracker": {"next_date": "tomorrow"}}).status_code == 422
    assert verified_a.patch(f"/recovery/cases/{cid}/guide", json={"tracker": {"next_date": "2026-02-31"}}).status_code == 422
    verify_email(user_b)
    assert user_b.patch(f"/recovery/cases/{cid}/guide", json={"tracker": {"next_date": "2026-12-01"}}).status_code == 404  # another business cannot touch it
