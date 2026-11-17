"""Business details are configuration (never invented), and data-rights requests work end to end."""

from datetime import datetime, timedelta

import pytest

from lib import business
from tests.conftest import mongo, outbox

ALL = ["BUSINESS_LEGAL_NAME", "BUSINESS_REGISTERED_ADDRESS", "BUSINESS_REGISTRATION_NUMBER", "BUSINESS_GSTIN", "GRIEVANCE_OFFICER_NAME", "GRIEVANCE_OFFICER_EMAIL",
       "GRIEVANCE_OFFICER_ADDRESS", "PRIVACY_CONTACT_EMAIL", "SUPPORT_EMAIL", "SUPPORT_WHATSAPP", "DATA_REQUEST_RESPONSE_DAYS"]


@pytest.fixture
def blank(monkeypatch):
    for k in ALL:
        monkeypatch.delenv(k, raising=False)


# ---- the configuration ----
def test_nothing_is_invented_when_nothing_is_configured(blank):
    assert all(v is None for v in business.public_config().values())
    assert business.missing() == ["legal_name", "registered_address", "grievance_name", "grievance_email", "support_email"]
    assert business.problems() == [] and business.response_days() == 30


def test_gstin_and_registration_are_optional_and_not_required_for_launch(blank):
    assert "gstin" not in business.missing() and "registration_number" not in business.missing()


def test_configured_values_are_returned_as_given(blank, monkeypatch):
    monkeypatch.setenv("BUSINESS_LEGAL_NAME", "  Example Legal Tech LLP  ")
    monkeypatch.setenv("GRIEVANCE_OFFICER_EMAIL", "grievance@example.in")
    cfg = business.public_config()
    assert cfg["legal_name"] == "Example Legal Tech LLP" and cfg["grievance_email"] == "grievance@example.in"
    assert cfg["privacy_email"] == "grievance@example.in"  # defaults to the grievance contact
    monkeypatch.setenv("PRIVACY_CONTACT_EMAIL", "privacy@example.in")
    assert business.get("privacy_email") == "privacy@example.in"


def test_a_malformed_gstin_or_email_is_never_shown_and_is_reported(blank, monkeypatch):
    monkeypatch.setenv("BUSINESS_GSTIN", "not-a-gstin")
    monkeypatch.setenv("SUPPORT_EMAIL", "not an email")
    assert business.get("gstin") is None and business.get("support_email") is None
    assert len(business.problems()) == 2 and any("GST" in p for p in business.problems())
    monkeypatch.setenv("BUSINESS_GSTIN", "27aaaaa0000a1z5")
    assert business.get("gstin") == "27AAAAA0000A1Z5" and business.problems() == [p for p in business.problems() if "GST" not in p]  # format only: never claimed to be verified


def test_the_response_target_is_configurable_and_safe(blank, monkeypatch):
    monkeypatch.setenv("DATA_REQUEST_RESPONSE_DAYS", "14")
    assert business.response_days() == 14
    monkeypatch.setenv("DATA_REQUEST_RESPONSE_DAYS", "soon")
    assert business.response_days() == 30


def test_the_source_has_no_default_business_details():
    src = open(business.__file__, encoding="utf-8").read()
    assert 'os.environ.get(FIELDS[key]) or ""' in src and "Pvt" not in src and "LLP" not in src.split('"""')[2]


# ---- the API ----
def test_the_public_config_is_public_and_marks_what_is_missing(anon):
    r = anon.get("/public/legal-config")
    assert r.status_code == 200
    j = r.json()
    assert j["config"]["gstin"] is None and j["config"]["grievance_name"] is None  # not configured in the test environment
    assert "registered_address" in j["missing"] and "grievance_email" not in j["missing"] and j["response_days"] == 30


def test_a_request_is_saved_acknowledged_and_sent_to_the_privacy_contact(user_a):
    r = user_a.post("/privacy/requests", json={"kind": "ERASURE", "details": "Please erase my data."})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "RECEIVED" and j["kind"] == "ERASURE" and j["routed"] is True
    assert datetime.fromisoformat(j["due_by"]) - datetime.fromisoformat(j["created_at"]) == timedelta(days=30)
    assert mongo().data_requests.find_one({"id": j["id"]})["user_id"] == user_a.user["id"]
    ack = outbox(to=user_a.user["email"], subject_has="data request")
    assert ack and "service target" in ack[-1]["html"] and j["id"][:8] in ack[-1]["html"]
    fwd = outbox(to="grievance-test@example.com", subject_has=j["id"][:8])
    assert fwd and "ERASURE" in fwd[-1]["subject"]
    assert "Please erase" not in fwd[-1]["html"]  # the person's words stay in the record, not in an email


def test_every_kind_is_accepted_and_nothing_else(user_a):
    for kind in ("ACCESS", "CORRECTION", "ERASURE", "WITHDRAW_CONSENT", "NOMINATION", "GRIEVANCE"):
        mongo().rate_limits.delete_many({"_id": {"$regex": "^privacy-request:" + user_a.user["id"]}})
        assert user_a.post("/privacy/requests", json={"kind": kind}).status_code == 200
    assert user_a.post("/privacy/requests", json={"kind": "SELL_MY_DATA"}).status_code == 422
    assert user_a.post("/privacy/requests", json={"kind": "ACCESS", "details": "x" * 2001}).status_code == 422


def test_requests_are_rate_limited(user_a):
    codes = [user_a.post("/privacy/requests", json={"kind": "ACCESS"}).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and 429 in codes[5:]


def test_a_person_sees_only_their_own_requests(user_a, user_b):
    mine = user_a.post("/privacy/requests", json={"kind": "ACCESS", "details": "mine"}).json()["id"]
    user_b.post("/privacy/requests", json={"kind": "GRIEVANCE", "details": "theirs"})
    assert [x["id"] for x in user_a.get("/privacy/requests").json()] == [mine]
    assert [x["details"] for x in user_b.get("/privacy/requests").json()] == ["theirs"]


def test_needs_sign_in(anon):
    assert anon.post("/privacy/requests", json={"kind": "ACCESS"}).status_code in (401, 403)
    assert anon.get("/privacy/requests").status_code in (401, 403) and anon.get("/privacy/my-data").status_code in (401, 403)


def test_my_data_is_downloadable_at_once_and_leaves_secrets_out(user_a):
    mongo().users.update_one({"id": user_a.user["id"]}, {"$set": {
        "two_factor": {"enabled": True, "secret": "SEALED-SECRET-XYZ"}, "google_sub": "g-123", "phone": {"verified": True, "number": "SEALED-NUMBER-ABC", "hash": "h", "last4": "4321", "alerts": True}}})
    user_a.post("/privacy/requests", json={"kind": "ACCESS"})
    r = user_a.get("/privacy/my-data")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    body = r.text
    data = r.json()
    assert data["profile"]["email"] == user_a.user["email"] and data["profile"]["phone"] == {"verified": True, "last4": "4321", "alerts": True}
    for secret in ("password_hash", "SEALED-SECRET-XYZ", "SEALED-NUMBER-ABC", "g-123", "two_factor"):
        assert secret not in body
    assert data["data_requests"] and any(a["operation"] == "PRIVACY_REQUEST" for a in data["activity"])