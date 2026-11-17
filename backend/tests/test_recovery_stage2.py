"""Recovery stage 2: notice versions, owner approval, advocate review, and the states after sending."""

import uuid

import pytest

from tests.conftest import make_case, mongo, new_member, outbox, stub, verify_email
from tests.test_recovery_stage1 import draft_reply, new_case


def drafted(c):
    """A case with an AI-drafted notice (version 1)."""
    cid, debtor = new_case(c)
    stub("generic", draft_reply(), contains=debtor)
    r = c.post(f"/recovery/cases/{cid}/notice")
    assert r.status_code == 200, r.text
    return cid


def wf(c, cid):
    return c.get(f"/recovery/cases/{cid}/notice/workflow").json()


def versions(c, cid):
    return c.get(f"/recovery/cases/{cid}/notice/versions").json()


def approve(c, cid, **kw):
    return c.post(f"/recovery/cases/{cid}/notice/approve", json={"acknowledged": True, **kw})


def prepare(c, cid, to=None):
    return c.post(f"/recovery/cases/{cid}/email/prepare", json={"debtor_email": to or f"cust-{uuid.uuid4().hex[:8]}@example.com"})


@pytest.fixture
def team(user_a):
    verify_email(user_a)
    return {"OWNER": user_a, "LAWYER": new_member(user_a, "LAWYER"), "MEMBER": new_member(user_a, "MEMBER")}


# ---------------------------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------------------------
def test_every_change_is_a_new_version_and_old_ones_stay_exactly_as_they_were(user_a):
    cid = drafted(user_a)
    v1 = versions(user_a, cid)
    assert len(v1) == 1 and v1[0]["number"] == 1 and v1[0]["origin"] == "AI_DRAFT" and v1[0]["is_current"]
    original = v1[0]["body"]
    assert user_a.patch(f"/recovery/cases/{cid}/notice", json={"notice_body": original + "\nPlease also note the invoice date."}).status_code == 200
    vs = versions(user_a, cid)
    assert [v["number"] for v in vs] == [2, 1] and vs[0]["origin"] == "EDIT" and vs[0]["is_current"] and not vs[1]["is_current"]
    assert vs[1]["body"] == original  # the original draft is preserved untouched
    assert vs[0]["created_by"]["email"] == user_a.user["email"]


def test_a_notice_written_before_versions_existed_becomes_version_one(user_a):
    cid = make_case(user_a)
    vs = versions(user_a, cid)
    assert len(vs) == 1 and vs[0]["is_current"]


# ---------------------------------------------------------------------------------------------
# Owner approval
# ---------------------------------------------------------------------------------------------
def test_nothing_can_be_prepared_for_sending_until_the_current_version_is_approved(verified_a):
    cid = drafted(verified_a)
    r = prepare(verified_a, cid)
    assert r.status_code == 409 and "Approve the current version" in r.json()["detail"]
    assert verified_a.post(f"/recovery/cases/{cid}/notice/approve", json={}).status_code == 422  # must tick the box
    ok = approve(verified_a, cid)
    assert ok.status_code == 200 and ok.json()["approved"]["kind"] == "OWNER"
    w = wf(verified_a, cid)
    assert w["state"] == "APPROVED" and w["approved"]["email"] == verified_a.user["email"] and w["approved"]["version"] == 1
    assert prepare(verified_a, cid).status_code == 200


def test_editing_after_approval_removes_the_approval_but_keeps_the_record_of_it(verified_a):
    cid = drafted(verified_a)
    approve(verified_a, cid)
    verified_a.patch(f"/recovery/cases/{cid}/notice", json={"notice_body": versions(verified_a, cid)[0]["body"] + "\nExtra paragraph."})
    w = wf(verified_a, cid)
    assert w["state"] == "DRAFT" and w["approved"] is None
    assert prepare(verified_a, cid).status_code == 409
    old = [v for v in versions(verified_a, cid) if v["number"] == 1][0]
    assert old["approvals"] and old["approvals"][0]["kind"] == "OWNER"  # who approved v1, and when, is kept
    assert approve(verified_a, cid).status_code == 200 and prepare(verified_a, cid).status_code == 200


def test_approving_a_stale_version_is_refused(verified_a):
    cid = drafted(verified_a)
    stale = versions(verified_a, cid)[0]["id"]
    verified_a.patch(f"/recovery/cases/{cid}/notice", json={"notice_body": versions(verified_a, cid)[0]["body"] + "\nChanged."})
    r = approve(verified_a, cid, version_id=stale)
    assert r.status_code == 409 and "changed" in r.json()["detail"]


def test_a_notice_with_blanks_or_legal_references_or_threats_cannot_be_approved(verified_a):
    for line in ("Under Section 138 you must pay.", "We will call the police.", "Pay [amount] now."):
        cid, debtor = new_case(verified_a)
        stub("generic", draft_reply("\n" + line), contains=debtor)
        verified_a.post(f"/recovery/cases/{cid}/notice")
        r = approve(verified_a, cid)
        assert r.status_code == 409 and "Before you can" in r.json()["detail"], line
        assert wf(verified_a, cid)["state"] == "DRAFT"


def test_roles_decide_who_may_approve(team):
    owner, lawyer, member = team["OWNER"], team["LAWYER"], team["MEMBER"]
    cid = drafted(owner)
    assert approve(member, cid).status_code == 403
    assert member.post(f"/recovery/cases/{cid}/notice/review", json={"decision": "APPROVE", "declaration": True}).status_code == 403
    assert member.post(f"/recovery/cases/{cid}/notice/request-review", json={}).status_code == 200  # anyone who can edit may ask for a review
    assert "approve" in wf(lawyer, cid)["allowed"] and "approve" not in wf(member, cid)["allowed"]


# ---------------------------------------------------------------------------------------------
# Advocate review
# ---------------------------------------------------------------------------------------------
def test_a_case_with_a_stop_warning_cannot_go_out_on_the_owners_approval_alone(team):
    owner, lawyer = team["OWNER"], team["LAWYER"]
    cid, debtor = new_case(owner)
    owner.patch(f"/recovery/cases/{cid}/intake", json={"route": {"cheque_bounced": "yes"}})
    stub("generic", draft_reply(), contains=debtor)
    assert owner.post(f"/recovery/cases/{cid}/notice", json={"acknowledge_route": True}).status_code == 200
    w = wf(owner, cid)
    assert w["needs_advocate"] and "approve" not in w["allowed"]
    r = approve(owner, cid)
    assert r.status_code == 409 and "advocate" in r.json()["detail"]
    assert prepare(owner, cid).status_code == 409

    no_decl = lawyer.post(f"/recovery/cases/{cid}/notice/review", json={"decision": "APPROVE"})
    assert no_decl.status_code == 422
    ok = lawyer.post(f"/recovery/cases/{cid}/notice/review", json={"decision": "APPROVE", "declaration": True, "comments": "Fine to send.", "enrolment_no": "MH/1234/2015"})
    assert ok.status_code == 200, ok.text
    w = wf(owner, cid)
    assert w["state"] == "APPROVED" and w["approved"]["kind"] == "ADVOCATE"
    assert w["approved"]["email"] == lawyer.user["email"] and w["approved"]["enrolment_no_stated_by_reviewer"] == "MH/1234/2015"
    assert "Declared by the reviewer" in w["approved"]["declaration"]
    # nothing about the reviewer is written into the notice itself
    body = versions(owner, cid)[0]["body"]
    assert lawyer.user["full_name"] not in body and "MH/1234/2015" not in body
    assert prepare(owner, cid).status_code == 200


def test_changes_requested_needs_comments_and_sends_the_notice_back_to_draft(team):
    owner, lawyer = team["OWNER"], team["LAWYER"]
    cid = drafted(owner)
    owner.post(f"/recovery/cases/{cid}/notice/request-review", json={"note": "Customer disputes delivery"})
    w = wf(owner, cid)
    assert w["state"] == "ADVOCATE_REVIEW_REQUESTED" and w["review_request"]["note"] == "Customer disputes delivery"
    assert lawyer.post(f"/recovery/cases/{cid}/notice/review", json={"decision": "REQUEST_CHANGES", "declaration": True}).status_code == 422
    r = lawyer.post(f"/recovery/cases/{cid}/notice/review", json={"decision": "REQUEST_CHANGES", "declaration": True, "comments": "State the delivery date."})
    assert r.status_code == 200
    w = wf(owner, cid)
    assert w["state"] == "CHANGES_REQUESTED" and w["last_review"]["comments"] == "State the delivery date." and w["approved"] is None
    assert any("Changes requested" in h["event"] for h in w["history"])
    owner.patch(f"/recovery/cases/{cid}/notice", json={"notice_body": versions(owner, cid)[0]["body"] + "\nDelivered on 1 March."})
    assert wf(owner, cid)["state"] == "DRAFT"


def test_reviewing_a_stale_version_is_refused(team):
    owner, lawyer = team["OWNER"], team["LAWYER"]
    cid = drafted(owner)
    stale = versions(owner, cid)[0]["id"]
    owner.patch(f"/recovery/cases/{cid}/notice", json={"notice_body": versions(owner, cid)[0]["body"] + "\nChanged."})
    r = lawyer.post(f"/recovery/cases/{cid}/notice/review", json={"decision": "APPROVE", "declaration": True, "version_id": stale})
    assert r.status_code == 409


# ---------------------------------------------------------------------------------------------
# Sending and afterwards
# ---------------------------------------------------------------------------------------------
def send(c, cid, to):
    p = prepare(c, cid, to)
    assert p.status_code == 200, p.text
    return c.post(f"/recovery/cases/{cid}/email", json={"confirmation_id": p.json()["confirmation_id"], "acknowledged": True})


def test_sending_records_the_state_and_blocks_a_second_send_of_the_same_notice(verified_a):
    cid = drafted(verified_a)
    approve(verified_a, cid)
    to = f"cust-{uuid.uuid4().hex[:8]}@example.com"
    assert send(verified_a, cid, to).status_code == 200
    w = wf(verified_a, cid)
    assert w["state"] == "SENT" and w["sent"]["to"] == to and w["sent"]["version"] == 1
    assert any("accepted by the email provider; delivery not confirmed" in h["event"] for h in w["history"])
    again = prepare(verified_a, cid, to)
    assert again.status_code == 409 and "already sent" in again.json()["detail"]
    assert len(outbox(to=to)) == 1


def test_a_bounced_notice_may_be_sent_again_to_a_corrected_address(verified_a):
    cid = drafted(verified_a)
    approve(verified_a, cid)
    assert send(verified_a, cid, f"typo-{uuid.uuid4().hex[:8]}@example.com").status_code == 200
    mongo().recovery_cases.update_one({"id": cid}, {"$set": {"debtor_email_status": "BOUNCED"}})
    good = f"right-{uuid.uuid4().hex[:8]}@example.com"
    assert send(verified_a, cid, good).status_code == 200 and len(outbox(to=good)) == 1


def test_what_happened_next_is_recorded_in_order_and_closing_is_final(verified_a):
    cid = drafted(verified_a)
    mark = lambda s, note="": verified_a.post(f"/recovery/cases/{cid}/notice/mark", json={"state": s, "note": note})  # noqa: E731
    assert mark("RESPONSE_RECEIVED").status_code == 409  # nothing was sent yet
    approve(verified_a, cid)
    send(verified_a, cid, f"c-{uuid.uuid4().hex[:8]}@example.com")
    assert mark("RESPONSE_RECEIVED", "He replied by email promising payment").status_code == 200
    assert mark("CLOSED", "Paid in full").status_code == 200
    w = wf(verified_a, cid)
    assert w["state"] == "CLOSED" and [h["event"] for h in w["history"]][:2] == ["Closed", "Response received from the customer"]
    assert verified_a.patch(f"/recovery/cases/{cid}/notice", json={"notice_body": "x" * 40}).status_code == 409
    assert approve(verified_a, cid).status_code == 409
    assert mark("ESCALATED").status_code == 409


def test_escalating_is_possible_before_closing(verified_a):
    cid = drafted(verified_a)
    assert verified_a.post(f"/recovery/cases/{cid}/notice/mark", json={"state": "ESCALATED", "note": "Taking it to our advocate"}).status_code == 200
    assert wf(verified_a, cid)["state"] == "ESCALATED"


# ---------------------------------------------------------------------------------------------
# Privacy and deletion
# ---------------------------------------------------------------------------------------------
def test_another_business_cannot_see_or_act_on_any_of_it(user_a, user_b):
    cid = drafted(user_a)
    for method, path, kw in (
        ("get", f"/recovery/cases/{cid}/notice/workflow", {}),
        ("get", f"/recovery/cases/{cid}/notice/versions", {}),
        ("post", f"/recovery/cases/{cid}/notice/approve", {"json": {"acknowledged": True}}),
        ("post", f"/recovery/cases/{cid}/notice/request-review", {"json": {}}),
        ("post", f"/recovery/cases/{cid}/notice/review", {"json": {"decision": "APPROVE", "declaration": True}}),
        ("post", f"/recovery/cases/{cid}/notice/mark", {"json": {"state": "ESCALATED"}}),
    ):
        assert getattr(user_b, method)(path, **kw).status_code == 404, path


def test_deleting_the_case_deletes_its_versions(user_a):
    cid = drafted(user_a)
    db = mongo()
    assert db.notice_versions.count_documents({"case_id": cid}) >= 1
    assert user_a.delete(f"/recovery/cases/{cid}").status_code == 200
    assert db.notice_versions.count_documents({"case_id": cid}) == 0
