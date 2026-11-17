"""Opt-in SMS / WhatsApp alerts to the owner's own verified phone (Twilio is replaced by a capture). Never to customers."""

import base64
import hashlib
import hmac
import re
import uuid

import httpx
import pytest

from lib import twilio_sms
from tests.conftest import API_URL, mongo
from tests.test_recovery_stage1 import new_case
from tests.test_sendgrid import post as sendgrid_post, signed

TOKEN = "twilio-test-token-not-real"  # secret-scan: ok (fake test value)
URL = "http://twilio.test/api/webhooks/twilio"


@pytest.fixture(autouse=True)
def _email_confirmed(request):
    """Phone codes need a confirmed email; the tests below are about the phone flow, so confirm it up front (one test checks the refusal)."""
    for name in ("user_a", "user_b"):
        if name in request.fixturenames:
            c = request.getfixturevalue(name)
            mongo().users.update_one({"id": c.user["id"]}, {"$set": {"email_verified": True}})


def number() -> str:
    return "+9198" + str(uuid.uuid4().int)[:8]


def code_sent_to(num: str) -> str:
    row = mongo().sms_outbox.find({"to": num}).sort("created_at", -1)[0]
    return re.search(r"code: (\d{6})", row["body"]).group(1)


def verify_phone(c, num=None, channel="sms") -> str:
    num = num or number()
    assert c.post("/auth/phone/start", json={"phone": num, "channel": channel}).status_code == 200
    r = c.post("/auth/phone/verify", json={"code": code_sent_to(num)})
    assert r.status_code == 200, r.text
    return num


def test_normalising_numbers():
    assert twilio_sms.normalise("+91 98765-43210") == "+919876543210"
    for bad in ("9876543210", "+0123456789", "+91", "abc", ""):
        with pytest.raises(ValueError):
            twilio_sms.normalise(bad)


def test_a_phone_is_added_with_a_code_and_stored_encrypted(user_a):
    num = number()
    assert user_a.get("/auth/phone").json()["verified"] is False
    assert user_a.post("/auth/phone/start", json={"phone": "12345", "channel": "sms"}).status_code == 422
    assert user_a.post("/auth/phone/verify", json={"code": "123456"}).status_code == 409  # no code asked for yet
    assert user_a.post("/auth/phone/start", json={"phone": num, "channel": "sms"}).json() == {"sent": True}
    assert user_a.post("/auth/phone/verify", json={"code": "000000"}).status_code == 400
    ok = user_a.post("/auth/phone/verify", json={"code": code_sent_to(num)})
    assert ok.status_code == 200 and ok.json()["verified"] and ok.json()["alerts"] and ok.json()["last4"] == num[-4:]
    row = mongo().users.find_one({"id": user_a.user["id"]})
    assert num not in repr(row["phone"])  # the number is sealed, only its last four digits are readable
    assert "phone_pending" not in row


def test_a_code_expires_after_too_many_wrong_tries(user_a):
    num = number()
    user_a.post("/auth/phone/start", json={"phone": num, "channel": "sms"})
    codes = [user_a.post("/auth/phone/verify", json={"code": f"{i:06d}"}).status_code for i in range(7)]
    assert codes[:5] == [400] * 5 and codes[5] == 410
    assert user_a.post("/auth/phone/verify", json={"code": code_sent_to(num)}).status_code == 409  # dead: ask again


def test_a_number_belongs_to_one_account(user_a, user_b):
    num = verify_phone(user_a)
    assert user_b.post("/auth/phone/start", json={"phone": num, "channel": "sms"}).status_code == 409


def test_codes_cannot_be_used_to_spam(user_a):
    codes = [user_a.post("/auth/phone/start", json={"phone": number(), "channel": "sms"}).status_code for _ in range(7)]
    assert 429 in codes


def test_whatsapp_is_a_separate_channel(user_a):
    num = verify_phone(user_a, channel="whatsapp")
    assert mongo().sms_outbox.find_one({"to": num})["channel"] == "whatsapp"
    assert user_a.get("/auth/phone").json()["channel"] == "whatsapp"


def test_alerts_can_be_switched_off_and_the_phone_removed(user_a):
    verify_phone(user_a)
    assert user_a.patch("/auth/phone", json={"alerts": False}).json()["alerts"] is False
    assert user_a.delete("/auth/phone").status_code == 200
    v = user_a.get("/auth/phone").json()
    assert not v["verified"] and v["last4"] is None
    assert user_a.patch("/auth/phone", json={"alerts": True}).status_code == 409


def test_needs_sign_in(anon):
    assert anon.post("/auth/phone/start", json={"phone": number(), "channel": "sms"}).status_code in (401, 403)
    assert anon.get("/auth/phone").status_code in (401, 403)


# ---- STOP replies ----
def twilio_post(params: dict, sign_with: str = TOKEN):
    data = URL + "".join(k + params[k] for k in sorted(params))
    sig = base64.b64encode(hmac.new(sign_with.encode(), data.encode(), hashlib.sha1).digest()).decode()
    return httpx.post(f"{API_URL}/webhooks/twilio", data=params, headers={"X-Twilio-Signature": sig}, timeout=30)


def test_stop_switches_alerts_off_and_only_when_signed(user_a):
    num = verify_phone(user_a)
    assert twilio_post({"From": num, "Body": "STOP"}, sign_with="forged").status_code == 401
    assert user_a.get("/auth/phone").json()["alerts"] is True
    assert twilio_post({"From": num, "Body": "hello"}).status_code == 200
    assert user_a.get("/auth/phone").json()["alerts"] is True  # only a stop word counts
    assert twilio_post({"From": num, "Body": " stop "}).status_code == 200
    assert user_a.get("/auth/phone").json()["alerts"] is False


# ---- the alert itself ----
def delivery_event(owner, status="delivered") -> None:
    cid, _ = new_case(owner)
    pid = "sgtw" + uuid.uuid4().hex[:12]
    mongo().email_log.insert_one({"id": str(uuid.uuid4()), "provider_id": pid, "kind": "notice-debtor", "case_id": cid, "to": f"debtor-{uuid.uuid4().hex[:6]}@example.com", "status": "SENT"})
    body, h = signed([{"event": status, "sg_message_id": pid + ".f"}])
    assert sendgrid_post(body, h).status_code == 200


def test_a_delivery_update_sends_a_plain_alert_to_the_owner_only(user_a):
    num = verify_phone(user_a)
    before = mongo().sms_outbox.count_documents({"to": num})
    delivery_event(user_a)
    msgs = list(mongo().sms_outbox.find({"to": num}).sort("created_at", 1))[before:]
    assert len(msgs) == 1 and msgs[0]["body"].startswith("VIDHI: ") and "@" not in msgs[0]["body"] and "Rs" not in msgs[0]["body"]
    assert mongo().sms_outbox.count_documents({"to": {"$regex": "example.com"}}) == 0  # never to the customer


def test_no_alert_when_switched_off_or_not_verified(user_a, user_b):
    num = verify_phone(user_a)
    user_a.patch("/auth/phone", json={"alerts": False})
    n = mongo().sms_outbox.count_documents({"to": num})
    delivery_event(user_a)
    delivery_event(user_b)  # never added a phone
    assert mongo().sms_outbox.count_documents({"to": num}) == n

def test_members_export_never_contains_secrets_or_the_phone_number(user_a):
    import io
    import json
    import zipfile

    num = verify_phone(user_a)
    from tests.test_twofactor import _enable

    secret, codes = _enable(user_a)
    z = zipfile.ZipFile(io.BytesIO(user_a.get("/org/export").content))
    members = z.read("members.json").decode()
    assert num not in members and secret not in members and "two_factor" not in members and "password_hash" not in members
    assert json.loads(members)[0]["phone"]["last4"] == num[-4:]


def test_an_api_key_is_used_for_sending_when_set(monkeypatch):
    import asyncio

    seen = {}

    def handler(request):
        seen["auth"], seen["path"] = request.headers["authorization"], request.url.path
        return httpx.Response(201, json={"sid": "SM1"})

    monkeypatch.setattr(twilio_sms, "_TRANSPORT", httpx.MockTransport(handler))
    for k, v in {"TWILIO_STUB": "false", "TWILIO_ACCOUNT_SID": "ACacct", "TWILIO_API_KEY_SID": "SKkey", "TWILIO_API_KEY_SECRET": "secret", "TWILIO_FROM": "+15550001111"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    assert twilio_sms.configured("sms")
    assert asyncio.run(twilio_sms.send("+919876543210", "hi")) == "SM1"
    assert seen["path"] == "/2010-04-01/Accounts/ACacct/Messages.json"
    assert base64.b64decode(seen["auth"].split()[1]).decode() == "SKkey:secret"  # signed in with the key, not the account token


def test_a_phone_code_needs_a_confirmed_email(user_a):
    mongo().users.update_one({"id": user_a.user["id"]}, {"$unset": {"email_verified": ""}})
    r = user_a.post("/auth/phone/start", json={"phone": number(), "channel": "sms"})
    assert r.status_code == 403 and "confirm your email" in r.json()["detail"]
