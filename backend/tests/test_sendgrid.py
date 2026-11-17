"""SendGrid as the mail provider, and its signed delivery webhook (a throwaway test key signs the events)."""

import asyncio
import base64
import json
import time
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from lib import email as mail
from tests.conftest import API_URL, mongo

KEY = ec.derive_private_key(0x5E5D5C5B5A595857565554535251504F4E4D4C4B4A494847464544434241, ec.SECP256R1())  # test only; the server holds the public half


def run(c):
    return asyncio.run(c)


# ---- sending ----
@pytest.fixture
def sendgrid(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(202, headers={"X-Message-Id": "abc123msgid"})

    monkeypatch.setattr(mail, "_TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setenv("EMAIL_DRY_RUN", "false")
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.test")
    monkeypatch.setenv("EMAIL_FROM", "VIDHI <notices@mail.example.in>")
    monkeypatch.setenv("EMAIL_PROVIDER", "sendgrid")
    return calls


def test_a_mail_goes_to_sendgrid_in_its_format(sendgrid):
    mid = run(mail.send_email(
        to="a@example.com", subject="Hello", html="<p>Hi</p>", cc=["c@example.com"], reply_to="r@example.com",
        attachments=[{"filename": "notice.pdf", "content": "UERG"}],
    ))
    assert mid == "abc123msgid"
    req = sendgrid[0]
    body = json.loads(req.content)
    assert req.url.path == "/v3/mail/send" and req.headers["authorization"] == "Bearer SG.test"
    assert body["personalizations"] == [{"to": [{"email": "a@example.com"}], "cc": [{"email": "c@example.com"}]}]
    assert body["from"] == {"email": "notices@mail.example.in", "name": "VIDHI"} and body["reply_to"] == {"email": "r@example.com"}
    assert body["content"] == [{"type": "text/html", "value": "<p>Hi</p>"}]
    assert body["attachments"][0] == {"content": "UERG", "filename": "notice.pdf", "type": "application/pdf", "disposition": "attachment"}


def test_the_same_safety_checks_apply(sendgrid):
    with pytest.raises(ValueError):
        run(mail.send_email(to="a@example.com", subject="x", html='<form><input name="pw"></form>'))
    with pytest.raises(ValueError):
        run(mail.send_email(to="a@example.com", subject="x", html='<a href="http://insecure.example.com">x</a>'))
    assert not sendgrid  # nothing was sent


def test_a_provider_error_is_raised(monkeypatch):
    monkeypatch.setattr(mail, "_TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(401, json={"errors": []})))
    monkeypatch.setenv("EMAIL_DRY_RUN", "false")
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.bad")
    monkeypatch.setenv("EMAIL_FROM", "n@example.com")
    monkeypatch.setenv("EMAIL_PROVIDER", "sendgrid")
    with pytest.raises(httpx.HTTPStatusError):
        run(mail.send_email(to="a@example.com", subject="x", html="<p>x</p>"))


def test_which_provider_is_used(monkeypatch):
    for k in ("RESEND_API_KEY", "SENDGRID_API_KEY", "EMAIL_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    assert mail.provider() == "resend"
    monkeypatch.setenv("SENDGRID_API_KEY", "x")
    assert mail.provider() == "sendgrid"  # only SendGrid is configured
    monkeypatch.setenv("RESEND_API_KEY", "y")
    assert mail.provider() == "resend"  # both: Resend unless told otherwise
    monkeypatch.setenv("EMAIL_PROVIDER", "sendgrid")
    assert mail.provider() == "sendgrid"
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.delenv("RESEND_API_KEY")
    assert mail.provider() == "sendgrid"  # the chosen one is not configured: use what is


# ---- the delivery webhook ----
def signed(events: list, *, ts: int | None = None, tamper=False) -> tuple[bytes, dict]:
    body = json.dumps(events).encode()
    stamp = str(ts if ts is not None else int(time.time()))
    sig = KEY.sign(stamp.encode() + body, ec.ECDSA(hashes.SHA256()))
    if tamper:
        body += b" "
    return body, {"X-Twilio-Email-Event-Webhook-Signature": base64.b64encode(sig).decode(), "X-Twilio-Email-Event-Webhook-Timestamp": stamp, "Content-Type": "application/json"}


def logged_mail(to: str) -> str:
    pid = "sg" + uuid.uuid4().hex[:16]
    mongo().email_log.insert_one({"id": str(uuid.uuid4()), "provider_id": pid, "kind": "receipt", "to": to, "status": "SENT"})
    return pid


def post(body, headers):
    return httpx.post(f"{API_URL}/webhooks/sendgrid", content=body, headers=headers, timeout=30)


def test_unsigned_forged_tampered_and_stale_events_are_refused():
    ev = [{"event": "delivered", "sg_message_id": "x.filter0"}]
    assert post(json.dumps(ev).encode(), {}).status_code == 401
    body, h = signed(ev, tamper=True)
    assert post(body, h).status_code == 401
    body, h = signed(ev, ts=int(time.time()) - 3600)
    assert post(body, h).status_code == 401
    body, h = signed(ev)
    h["X-Twilio-Email-Event-Webhook-Signature"] = base64.b64encode(b"not a signature").decode()
    assert post(body, h).status_code == 401


def test_delivery_is_recorded_against_the_message_we_sent():
    pid = logged_mail("d@example.com")
    body, h = signed([{"event": "delivered", "sg_message_id": f"{pid}.filterdrecv-abc.1.0"}, {"event": "open", "sg_message_id": f"{pid}.x"}])
    assert post(body, h).json() == {"ok": True, "unknown_messages": 0}
    assert mongo().email_log.find_one({"provider_id": pid})["status"] == "DELIVERED"


def test_a_hard_bounce_blocks_the_address_but_a_soft_block_does_not():
    hard, soft = f"hard-{uuid.uuid4().hex[:8]}@example.com", f"soft-{uuid.uuid4().hex[:8]}@example.com"
    p1, p2 = logged_mail(hard), logged_mail(soft)
    body, h = signed([{"event": "bounce", "type": "bounce", "reason": "550 no such user", "sg_message_id": p1 + ".f"}, {"event": "bounce", "type": "blocked", "reason": "mailbox busy", "sg_message_id": p2 + ".f"}])
    assert post(body, h).status_code == 200
    assert mongo().email_suppressions.find_one({"email": hard})
    assert not mongo().email_suppressions.find_one({"email": soft})
    assert mongo().email_log.find_one({"provider_id": p2})["status"] == "BOUNCED"


def test_a_spam_complaint_blocks_the_address():
    to = f"spam-{uuid.uuid4().hex[:8]}@example.com"
    pid = logged_mail(to)
    body, h = signed([{"event": "spamreport", "sg_message_id": pid + ".f"}])
    assert post(body, h).status_code == 200 and mongo().email_suppressions.find_one({"email": to})


def test_events_for_mail_we_never_sent_are_counted_not_applied():
    body, h = signed([{"event": "delivered", "sg_message_id": "neversent.filter"}])
    assert post(body, h).json() == {"ok": True, "unknown_messages": 1}