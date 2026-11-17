"""No client text in logs, stored errors or error reports. A marker sentence stands in for a client's words (a name, an address, a sentence from a document); each test makes a
failure whose message contains it and checks that the marker never reaches a log line, a stored job error or an outgoing error report, while the kind of error and where it
happened still do. Invented text only."""

import json
import logging

import httpx
import pytest

from lib import email as mail
from lib import monitoring

MARKER = "Ramesh Kumar Gupta of 14 Lake View Road owes Rs 4,50,000"
ADDRESS = "ramesh.gupta.private@example.test"


def test_an_error_label_has_the_class_and_the_status_but_never_the_message():
    resp = httpx.Response(422, text=f"invalid: {MARKER}", request=httpx.Request("POST", "https://example.test"))
    exc = httpx.HTTPStatusError(f"Client error for {MARKER}", request=resp.request, response=resp)
    label = monitoring.error_label(exc)
    assert label == "HTTPStatusError (HTTP 422)" and MARKER not in label
    assert monitoring.error_label(ValueError(MARKER)) == "ValueError"


def test_where_names_our_code_not_the_message():
    def inner():
        raise ValueError(MARKER)

    try:
        inner()
    except ValueError as exc:
        spot = monitoring.where(exc)
    assert "test_log_leaks.py" in spot and "inner" in spot and MARKER not in spot


def test_the_error_report_sends_no_message_text_at_all():
    event = {
        "message": f"failed for {MARKER}",
        "request": {"url": f"https://x.test/?q={MARKER}", "data": MARKER},
        "user": {"email": ADDRESS},
        "extra": {"text": MARKER},
        "tags": {"who": MARKER},
        "breadcrumbs": {"values": [{"message": MARKER}]},
        "logentry": {"message": "Email send failed: %s", "params": [MARKER], "formatted": f"Email send failed: {MARKER}"},
        "exception": {"values": [{"type": "ValueError", "value": f"{MARKER} {ADDRESS}", "stacktrace": {"frames": [
            {"filename": "email.py", "abs_path": "C:/srv/vidhi/lib/email.py", "lineno": 7, "function": "send", "vars": {"body": MARKER}, "context_line": f"x = '{MARKER}'", "pre_context": [MARKER], "post_context": [MARKER]}]}}]},
    }
    out = monitoring.scrub(event)
    text = json.dumps(out)
    assert MARKER not in text and ADDRESS not in text and "Ramesh" not in text and "Gupta" not in text
    value = out["exception"]["values"][0]
    assert value["type"] == "ValueError" and value["value"] == ""  # the kind of error is kept, its message is not
    frame = value["stacktrace"]["frames"][0]
    assert frame["function"] == "send" and frame["lineno"] == 7 and "vars" not in frame and "abs_path" not in frame
    assert out["logentry"] == {"message": "Email send failed: %s"}  # fixed wording only


def test_a_failed_email_logs_the_class_and_status_but_not_the_providers_message(monkeypatch, caplog):
    def refuse(request):
        return httpx.Response(422, json={"message": f"The to field {ADDRESS} is invalid. Subject was: {MARKER}"})

    monkeypatch.setattr(mail, "_TRANSPORT", httpx.MockTransport(refuse))
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key_not_real")
    monkeypatch.setenv("EMAIL_FROM", "VIDHI <noreply@example.test>")
    monkeypatch.delenv("EMAIL_DRY_RUN", raising=False)
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    import asyncio

    with caplog.at_level(logging.DEBUG), pytest.raises(httpx.HTTPStatusError):
        asyncio.run(mail.send_email(to=ADDRESS, subject="Hello", html="<p>Hello</p>"))
    assert "HTTPStatusError (HTTP 422)" in caplog.text
    assert MARKER not in caplog.text and ADDRESS not in caplog.text and "Ramesh" not in caplog.text


def test_an_unhandled_error_logs_the_class_and_where_but_not_its_message(caplog):
    import server
    from starlette.testclient import TestClient

    @server.app.get("/__log_leak_probe")
    async def probe():  # a route that fails with client text in the message, like a database or validation error can
        raise ValueError(MARKER)

    client = TestClient(server.app, raise_server_exceptions=False)  # no lifespan: no database is needed
    try:
        with caplog.at_level(logging.DEBUG):
            r = client.get("/__log_leak_probe")
    finally:  # take the probe route out again: other tests in this process walk every route of the app (and the app's schema is rebuilt without it)
        server.app.router.routes[:] = [rt for rt in server.app.router.routes if getattr(rt, "path", "") != "/__log_leak_probe"]
        server.app.openapi_schema = None
    assert r.status_code == 500 and MARKER not in r.text and "reference" in r.json()
    assert "unhandled error" in caplog.text and "ValueError" in caplog.text and "probe" in caplog.text
    assert MARKER not in caplog.text and "Ramesh" not in caplog.text and "Gupta" not in caplog.text
    assert "Traceback" not in caplog.text


def test_a_failed_scheduled_job_stores_the_error_class_only(monkeypatch, caplog):
    import asyncio

    from routers import cron

    saved = {}

    class Jobs:
        async def update_one(self, flt, update, upsert=False):
            saved.update(update["$set"])

    class FakeDb:
        job_runs = Jobs()

    async def released(name):
        return None

    async def job():
        raise ValueError(MARKER)

    monkeypatch.setattr(cron, "db", FakeDb())
    monkeypatch.setattr(cron, "release", released)
    with caplog.at_level(logging.DEBUG):
        asyncio.run(cron._run_locked("retention", job))
    assert saved["last_error"] == "ValueError" and MARKER not in json.dumps(saved, default=str)
    assert "scheduled job retention failed: ValueError" in caplog.text and MARKER not in caplog.text


def test_the_stored_reason_for_a_failed_email_hides_addresses_and_numbers():
    text = monitoring.redact(f"The to field {ADDRESS} is invalid, phone 98765 43210")
    assert ADDRESS not in text and "98765" not in text and "[email]" in text


def test_the_uptime_page_holds_only_status_words_and_job_names(anon):
    """/api/health/ready is what an outside uptime monitor reads: it must carry no client text, only status and job names."""
    r = anon.get("/health/ready")
    assert r.status_code in (200, 503)
    body = r.json()
    assert set(body) <= {"status", "database", "jobs"} and body["status"] in ("ok", "degraded", "unavailable")
    assert all(set(j) == {"job", "problem"} and j["problem"] in ("overdue", "last run failed") for j in body.get("jobs", []))
