"""Legal Recovery is NOT part of the app by default (RECOVERY_ENABLED, owner 2026-11-15: "remove legal recovery from the app"). Off: every /recovery route answers 404, the two consent links answer 404,
search offers no recovery results, the two Recovery e-mail jobs send nothing and are not counted as overdue, and `/features` says so. Nothing is deleted. The test server runs with the switch ON so the
other Recovery tests keep covering the code; the OFF state is tested here in-process (the 404 comes before any sign-in or database use)."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from lib import recovery_mode


def all_api_routes():
    """Every route of the running app with its path and its merged dependencies (this FastAPI keeps included routers as one wrapper: effective_route_contexts is the flattened list)."""
    from server import app

    out = []
    for wrapper in app.routes:
        contexts = wrapper.effective_route_contexts
        out += [c for c in (contexts() if callable(contexts) else contexts) if getattr(c, "path", "").startswith("/api/")]
    return out


def is_recovery(r) -> bool:
    return r.path.startswith("/api/recovery") or r.path.startswith("/api/public/consent/")


def recovery_routes():
    return [r for r in all_api_routes() if is_recovery(r)]


def guards(route) -> set:
    return {d.call for d in route.dependant.dependencies}


def test_the_master_switch_is_off_unless_clearly_turned_on(monkeypatch):
    for value, expected in ((None, False), ("", False), ("false", False), ("0", False), ("no", False), ("true", True), ("TRUE", True), ("1", True), ("on", True)):
        if value is None:
            monkeypatch.delenv("RECOVERY_ENABLED", raising=False)
        else:
            monkeypatch.setenv("RECOVERY_ENABLED", value)
        assert recovery_mode.enabled() is expected, value
    monkeypatch.setenv("RECOVERY_ENABLED", "false")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        recovery_mode.require_enabled()
    assert e.value.status_code == 404 and "not available" in e.value.detail
    monkeypatch.setenv("RECOVERY_ENABLED", "true")
    assert recovery_mode.require_enabled() is None


def test_every_recovery_route_and_both_consent_routes_carry_the_switch():
    routes = recovery_routes()
    import re
    from pathlib import Path

    declared = sum(len(re.findall(r"^@router\.(?:get|post|put|patch|delete)\(", (Path(__file__).resolve().parent.parent / "routers" / f"{n}.py").read_text(encoding="utf-8"), re.M))
                   for n in ("recovery", "recovery_intake", "recovery_notice", "recovery_delivery", "recovery_translation", "recovery_mail"))
    assert len([r for r in routes if r.path.startswith("/api/recovery")]) == declared >= 50  # every route written in the six Recovery files is in the app, and each one is checked below
    assert any(r.path == "/api/recovery/cases" for r in routes) and {r.path for r in routes if r.path.startswith("/api/public/consent/")} == {"/api/public/consent/{token}"}
    missing = [(sorted(r.methods), r.path) for r in routes if recovery_mode.require_enabled not in guards(r)]
    assert missing == []
    consent = [r for r in routes if r.path.startswith("/api/public/consent/")]
    assert {m for r in consent for m in r.methods} == {"GET", "POST"}


def test_the_email_delivery_webhooks_and_the_rest_of_the_app_are_not_switched_off_with_it():
    others = [r for r in all_api_routes() if not is_recovery(r)]
    assert len(others) > 200
    assert [(sorted(r.methods), r.path) for r in others if recovery_mode.require_enabled in guards(r)] == []
    assert {"/api/webhooks/resend", "/api/webhooks/sendgrid"} <= {r.path for r in others}  # delivery receipts serve every kind of e-mail


@pytest.fixture
def signed_in():
    """The role check and the user lookup are stood in for, so the request reaches the Legal Recovery switch without a database (the switch sits right after the role check)."""
    from lib.auth import current_user, enforce_policy
    from server import app

    app.dependency_overrides[enforce_policy] = lambda: None
    app.dependency_overrides[current_user] = lambda: {"id": "u1", "organization_id": "o1", "role": "OWNER", "email": "u@example.test"}
    yield
    app.dependency_overrides.pop(enforce_policy, None)
    app.dependency_overrides.pop(current_user, None)


def client() -> TestClient:
    from server import app

    return TestClient(app, raise_server_exceptions=False)  # no `with`: no start-up, no database


@pytest.mark.parametrize("method,path", [("GET", "/api/recovery/cases"), ("POST", "/api/recovery/cases"), ("GET", "/api/recovery/options"), ("GET", "/api/recovery/cases/abc/notice.pdf"),
                                         ("PATCH", "/api/recovery/cases/abc/intake"), ("GET", "/api/public/consent/sometoken"), ("POST", "/api/public/consent/sometoken")])
def test_with_the_switch_off_recovery_answers_not_available_to_a_signed_in_user(monkeypatch, signed_in, method, path):
    monkeypatch.delenv("RECOVERY_ENABLED", raising=False)
    r = client().request(method, path, json={})
    assert r.status_code == 404 and r.json()["detail"] == recovery_mode.NOT_PART_OF_APP


def test_with_the_switch_off_a_stranger_is_still_told_to_sign_in_first(monkeypatch):
    monkeypatch.delenv("RECOVERY_ENABLED", raising=False)
    assert client().get("/api/recovery/cases").status_code in (401, 403)  # the role check comes first, as everywhere else


def test_with_the_switch_on_the_route_is_reached(monkeypatch, signed_in):
    monkeypatch.setenv("RECOVERY_ENABLED", "true")
    r = client().get("/api/recovery/options")
    assert r.status_code == 200 and "full_flow" in r.json()


def test_the_two_recovery_e_mail_jobs_send_nothing_while_it_is_off(monkeypatch):
    from routers import cron

    monkeypatch.setattr(cron, "CRON_SECRET", "test-secret")
    monkeypatch.delenv("RECOVERY_ENABLED", raising=False)
    for path in ("/api/cron/recovery-reminders", "/api/cron/scheduled-statements"):
        r = client().post(path, headers={"Authorization": "Bearer test-secret"})
        assert r.status_code == 200 and r.json() == {"status": "disabled"}, path
    assert client().post("/api/cron/recovery-reminders", headers={"Authorization": "Bearer wrong"}).status_code == 401  # still guarded


def test_health_does_not_call_a_recovery_job_overdue_while_recovery_is_off(monkeypatch):
    import server
    from lib.auth import now
    from datetime import timedelta

    old = now() - timedelta(hours=500)

    class Admin:
        async def command(self, *a, **k):
            return {"ok": 1}

    class Runs:
        async def find_one(self, flt):
            return {"_id": flt["_id"], "last_ok_at": old}  # every job last ran long ago

    class FakeClient:
        admin = Admin()

    class FakeDb:
        job_runs = Runs()

    monkeypatch.setattr(server, "client", FakeClient())
    monkeypatch.setattr(server, "db", FakeDb())
    monkeypatch.delenv("RECOVERY_ENABLED", raising=False)
    off = asyncio.run(server.ready())
    assert {p["job"] for p in off["jobs"]} == {"retention", "upload-expiry", "deadline-reminders", "jobs"} and off["status"] == "degraded"  # the other jobs are still checked
    monkeypatch.setenv("RECOVERY_ENABLED", "true")
    on = asyncio.run(server.ready())
    assert {p["job"] for p in on["jobs"]} == {"recovery-reminders", "scheduled-statements", "retention", "upload-expiry", "deadline-reminders", "jobs"}


def test_search_offers_no_recovery_results_while_it_is_off(monkeypatch):
    import server

    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        async def to_list(self, n):
            return self.rows

    class Coll:
        def __init__(self, name):
            self.name = name

        def find(self, *a, **k):
            if self.name.startswith("recovery"):
                raise AssertionError("Legal Recovery data was searched while it is switched off")
            return Cursor([])

    class FakeDb:
        def __getattr__(self, name):
            return Coll(name)

    monkeypatch.setattr(server, "db", FakeDb())
    monkeypatch.delenv("RECOVERY_ENABLED", raising=False)
    out = asyncio.run(server.universal_search(q="invoice", user={"organization_id": "o1"}))
    assert out["query"] == "invoice"  # no assertion error: recovery_cases and recovery_proofs were never touched
    monkeypatch.setenv("RECOVERY_ENABLED", "true")
    with pytest.raises(AssertionError):
        asyncio.run(server.universal_search(q="invoice", user={"organization_id": "o1"}))  # on: it does search them (the fake refuses), so the guard above is what kept them out


def test_the_public_sign_in_options_tell_the_page_whether_recovery_is_on(monkeypatch, client):
    assert client.get("/auth/options").json()["recovery"] is True  # the test server runs with the switch on
    from routers import auth

    monkeypatch.delenv("RECOVERY_ENABLED", raising=False)
    assert asyncio.run(auth.sign_in_options())["recovery"] is False  # off by default
    monkeypatch.setenv("RECOVERY_ENABLED", "true")
    assert asyncio.run(auth.sign_in_options())["recovery"] is True
