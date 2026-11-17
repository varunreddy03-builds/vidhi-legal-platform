"""Recovery stage 3: honest delivery tracking, replies, postal dispatch, evidence pack."""

import io
import time
import uuid
import zipfile
from datetime import date, timedelta

import httpx
import pytest

from lib.delivery import display_status, evidence_summary
from tests.conftest import API_URL, mongo, new_member, outbox, post_resend_event, verify_email
from tests.test_recovery_stage2 import approve, drafted, send, wf


def delivery(c, cid):
    return c.get(f"/recovery/cases/{cid}/notice/delivery").json()


def provider_id(cid):
    return mongo().email_log.find_one({"case_id": cid, "kind": "notice-debtor"})["provider_id"]


def sent_case(c):
    cid = drafted(c)
    assert approve(c, cid).status_code == 200
    to = f"cust-{uuid.uuid4().hex[:8]}@example.com"
    assert send(c, cid, to).status_code == 200
    return cid, to


# ---------------------------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------------------------
def test_status_vocabulary_follows_the_state_and_the_latest_event():
    assert display_status("DRAFT", [], [], []) == "Draft"
    assert display_status("ADVOCATE_REVIEW_REQUESTED", [], [], []) == "Awaiting Approval"
    assert display_status("APPROVED", [], [], []) == "Approved"
    assert display_status("SENT", [{"status": "ACCEPTED", "created_at": date(2026, 1, 1)}] and [{"status": "ACCEPTED"}], [], []) == "Sent"
    assert display_status("SENT", [{"status": "DELIVERED"}], [], []) == "Delivery Confirmed by Provider"
    assert display_status("SENT", [{"status": "BOUNCED"}], [], []) == "Bounced"
    assert display_status("SENT", [{"status": "DELIVERED"}], [], [{"is_response": True}]) == "Response Received"


def test_a_sent_notice_never_claims_receipt_or_service():
    out = evidence_summary([{"status": "ACCEPTED", "to": "a@example.com", "created_at": date(2026, 1, 1)}], [], [])
    assert "No delivery confirmation has been received" in out["what_we_have"][0]
    text = " ".join(out["not_confirmed"])
    assert "no confirmation that the customer received" in text and "no proof that the customer read" in text and "legally served" in text


# ---------------------------------------------------------------------------------------------
# Provider delivery events
# ---------------------------------------------------------------------------------------------
def test_sent_is_not_delivered_until_the_provider_says_so(verified_a):
    cid, to = sent_case(verified_a)
    d = delivery(verified_a, cid)
    assert d["display_status"] == "Sent" and d["emails"][0]["status"] == "ACCEPTED" and d["emails"][0]["version"] == 1
    assert "No delivery confirmation has been received" in d["evidence"]["what_we_have"][0]
    assert post_resend_event("email.delivered", provider_id(cid)).status_code == 200
    d = delivery(verified_a, cid)
    assert d["display_status"] == "Delivery Confirmed by Provider" and d["emails"][0]["events"][-1]["type"] == "DELIVERED"
    assert "does not show the customer opened or read it" in d["evidence"]["what_we_have"][0]
    assert any("does not show it was read" in h["event"] for h in wf(verified_a, cid)["history"])
    assert any("no proof that the customer read" in x for x in d["evidence"]["not_confirmed"])


def test_a_bounce_shows_as_bounced_and_is_written_into_the_history(verified_a):
    cid, to = sent_case(verified_a)
    post_resend_event("email.bounced", provider_id(cid), bounce={"type": "Permanent", "message": "no such mailbox"})
    d = delivery(verified_a, cid)
    assert d["display_status"] == "Bounced" and "did not reach the customer by email" in d["evidence"]["what_we_have"][0]
    assert any("bounced" in h["event"] for h in wf(verified_a, cid)["history"])


# ---------------------------------------------------------------------------------------------
# Replies and correspondence
# ---------------------------------------------------------------------------------------------
def corr(c, cid, **kw):
    body = {"direction": "IN", "channel": "WHATSAPP", "occurred_on": date.today().isoformat(), "summary": "He says he will pay next week."} | kw
    return c.post(f"/recovery/cases/{cid}/correspondence", json=body)


def test_a_logged_reply_moves_a_sent_notice_to_response_received(verified_a):
    cid, _ = sent_case(verified_a)
    r = corr(verified_a, cid, is_response=True)
    assert r.status_code == 200 and r.json()["is_response"]
    assert wf(verified_a, cid)["state"] == "RESPONSE_RECEIVED"
    d = delivery(verified_a, cid)
    assert d["display_status"] == "Response Received" and d["correspondence"][0]["logged_by"]["email"] == verified_a.user["email"]
    assert any("Keep the original message" in x for x in d["evidence"]["what_we_have"])


def test_correspondence_is_validated_and_only_incoming_messages_count_as_a_response(verified_a):
    cid, _ = sent_case(verified_a)
    assert corr(verified_a, cid, occurred_on=(date.today() + timedelta(days=3)).isoformat()).status_code == 422
    assert corr(verified_a, cid, occurred_on="nonsense").status_code == 422
    assert corr(verified_a, cid, summary="x").status_code == 422
    assert corr(verified_a, cid, proof_id="nope").status_code == 422
    out = corr(verified_a, cid, direction="OUT", is_response=True)
    assert out.status_code == 200 and out.json()["is_response"] is False and wf(verified_a, cid)["state"] == "SENT"
    proof = verified_a.post(f"/recovery/cases/{cid}/proofs", files={"file": ("reply.txt", b"I will pay on 10th")}, data={"kind": "COMMUNICATION"}).json()
    assert corr(verified_a, cid, proof_id=proof["id"]).json()["proof_id"] == proof["id"]


# ---------------------------------------------------------------------------------------------
# Postal dispatch
# ---------------------------------------------------------------------------------------------
def postal(c, cid, **kw):
    body = {"service": "Speed Post", "tracking_no": "EE123456789IN", "sent_on": date.today().isoformat()} | kw
    return c.post(f"/recovery/cases/{cid}/notice/postal", json=body)


def test_posting_can_only_be_recorded_for_an_approved_notice(verified_a):
    cid = drafted(verified_a)
    r = postal(verified_a, cid)
    assert r.status_code == 409 and "Approve" in r.json()["detail"]
    approve(verified_a, cid)
    ok = postal(verified_a, cid)
    assert ok.status_code == 200 and ok.json()["version"] == 1
    w = wf(verified_a, cid)
    assert w["state"] == "SENT" and w["sent"]["via"] == "POST" and any("Posted by Speed Post" in h["event"] for h in w["history"])


def test_postal_tracking_updates_are_recorded_in_the_owners_words(verified_a):
    cid = drafted(verified_a)
    approve(verified_a, cid)
    p = postal(verified_a, cid).json()
    assert delivery(verified_a, cid)["display_status"] == "Sent"
    up = verified_a.post(f"/recovery/cases/{cid}/notice/postal/{p['id']}/update", json={"status": "Out for delivery", "date": date.today().isoformat()})
    assert up.status_code == 200
    d = delivery(verified_a, cid)
    assert d["display_status"] == "Postal Tracking Updated" and d["postal"][0]["updates"][0]["status"] == "Out for delivery"
    assert "Latest update: Out for delivery" in " ".join(d["evidence"]["what_we_have"])
    assert any("not confirmed" in x.lower() or "no confirmation" in x.lower() for x in d["evidence"]["not_confirmed"])
    assert verified_a.post(f"/recovery/cases/{cid}/notice/postal/nope/update", json={"status": "x1", "date": date.today().isoformat()}).status_code == 404
    assert postal(verified_a, cid, sent_on="2999-01-01").status_code == 422


def test_a_delivery_update_from_the_owner_counts_as_receipt_evidence(verified_a):
    cid = drafted(verified_a)
    approve(verified_a, cid)
    p = postal(verified_a, cid).json()
    verified_a.post(f"/recovery/cases/{cid}/notice/postal/{p['id']}/update", json={"status": "Delivered, signed by R. Kumar", "date": date.today().isoformat()})
    assert not any("no confirmation that the customer received" in x for x in delivery(verified_a, cid)["evidence"]["not_confirmed"])


# ---------------------------------------------------------------------------------------------
# Roles, privacy, evidence pack, deletion
# ---------------------------------------------------------------------------------------------
def test_a_member_can_log_messages_but_not_record_that_a_notice_was_posted(user_a):
    verify_email(user_a)
    cid = drafted(user_a)
    approve(user_a, cid)
    member = new_member(user_a, "MEMBER")
    assert corr(member, cid).status_code == 200
    assert postal(member, cid).status_code == 403
    assert member.get(f"/recovery/cases/{cid}/notice/delivery").status_code == 200


def test_another_business_sees_none_of_it(user_a, user_b):
    cid = drafted(user_a)
    for method, path, kw in (
        ("get", f"/recovery/cases/{cid}/notice/delivery", {}),
        ("post", f"/recovery/cases/{cid}/correspondence", {"json": {"direction": "IN", "channel": "EMAIL", "occurred_on": "2026-01-01", "summary": "hello"}}),
        ("post", f"/recovery/cases/{cid}/notice/postal", {"json": {"service": "Speed Post", "sent_on": "2026-01-01"}}),
        ("get", f"/recovery/cases/{cid}/evidence-pack.zip", {}),
    ):
        assert getattr(user_b, method)(path, **kw).status_code == 404, path


def test_the_evidence_pack_holds_versions_delivery_replies_and_the_original_files(verified_a):
    cid, to = sent_case(verified_a)
    verified_a.post(f"/recovery/cases/{cid}/proofs", files={"file": ("challan.txt", b"Delivered 5 chairs")}, data={"kind": "DELIVERY_PROOF"})
    corr(verified_a, cid)
    verified_a.patch(f"/recovery/cases/{cid}/notice", json={"notice_body": verified_a.get(f"/recovery/cases/{cid}").json()["notice_body"] + "\nRevised."})
    r = verified_a.get(f"/recovery/cases/{cid}/evidence-pack.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert {"README.txt", "workflow-history.json", "email-delivery.json", "correspondence.json", "delivery-summary.json"} <= set(names)
    assert "notice-versions/version-01.txt" in names and "notice-versions/version-02.txt" in names
    assert any(n.startswith("documents/") and n.endswith("challan.txt") for n in names)
    blob = b"".join(z.read(n) for n in names)
    assert b"Delivered 5 chairs" in blob and to.encode() in blob and b"does not prove" in blob and b"gridfs_id" not in blob


def test_deleting_the_case_deletes_the_correspondence(user_a):
    cid = drafted(user_a)
    corr(user_a, cid)
    db = mongo()
    assert db.case_correspondence.count_documents({"case_id": cid}) == 1
    user_a.delete(f"/recovery/cases/{cid}")
    assert db.case_correspondence.count_documents({"case_id": cid}) == 0


def test_scheduled_jobs_never_email_the_customer(verified_a):
    cid, to = sent_case(verified_a)
    mongo().recovery_cases.update_one({"id": cid}, {"$set": {"updated_at": mongo().recovery_cases.find_one({"id": cid})["updated_at"] - timedelta(days=10)}})
    before = len(outbox(to=to))
    for job in ("recovery-reminders", "scheduled-statements"):
        r = httpx.post(f"{API_URL}/cron/{job}", headers={"Authorization": "Bearer test-cron-secret-not-real"}, timeout=30)
        assert r.status_code == 200
    time.sleep(2.5)
    assert len(outbox(to=to)) == before  # the customer is only ever emailed when the owner approves and sends


@pytest.mark.parametrize("text,counts", [
    ("Delivered, signed by R. Kumar", True), ("Out for delivery", False), ("Delivery attempted, not delivered", False),
    ("Returned to sender: refused", False), ("Item delivered", True),
])
def test_only_a_genuine_delivered_update_counts_as_receipt_evidence(text, counts):
    from lib.delivery import _says_delivered

    assert _says_delivered(text) is counts


def test_postal_dates_typed_by_the_owner_are_shown_correctly():
    out = evidence_summary([], [{"service": "Speed Post", "tracking_no": "X1", "sent_on": "2026-10-19", "updates": [{"status": "Out for delivery", "at": "2026-10-20"}]}], [])
    line = out["what_we_have"][0]
    assert "19 Oct 2026" in line and "20 Oct 2026" in line and "0001" not in line
