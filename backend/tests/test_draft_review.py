"""A junior writes a draft, sends it for review, a senior approves it or asks for changes, and they talk in comments. Two organisations are used throughout: the other one can never read, comment on, approve or list anything."""
import uuid
from pathlib import Path

import pytest

from tests.conftest import mongo, new_member, verify_email


@pytest.fixture
def firm(user_a):
    """The owner (user_a), a junior (MEMBER) and a senior (LAWYER) in one organisation."""
    verify_email(user_a)
    return {"owner": user_a, "junior": new_member(user_a, "MEMBER"), "senior": new_member(user_a, "LAWYER")}


def make(c, body="First version of the reply."):
    r = c.post("/drafts", json={"title": "Reply " + uuid.uuid4().hex[:6], "body": body})
    assert r.status_code == 200, r.text
    return r.json()


def status(c, d):
    return c.get(f"/drafts/{d['id']}/review").json()["status"]


def audited(c, operation):
    return mongo().audit_events.count_documents({"operation": operation, "user_id": c.user["id"]})


def test_the_full_loop_junior_sends_senior_approves_and_both_are_recorded(firm):
    junior, senior = firm["junior"], firm["senior"]
    d = make(junior)
    assert d["status"] == "DRAFT" and status(junior, d) == "DRAFT"
    assert senior.get(f"/drafts/{d['id']}/review").json()["may_review"] is False  # nothing to review yet

    sent = junior.post(f"/drafts/{d['id']}/send-for-review")
    assert sent.status_code == 200 and sent.json()["status"] == "WITH_REVIEWER" and sent.json()["review"]["requested_by"] == junior.user["id"]
    assert senior.get(f"/drafts/{d['id']}/review").json()["may_review"] is True
    assert junior.get(f"/drafts/{d['id']}/review").json()["may_review"] is False

    done = senior.post(f"/drafts/{d['id']}/review", json={"decision": "approve"})
    assert done.status_code == 200 and done.json()["status"] == "APPROVED"
    review = done.json()["review"]
    assert review["decided_by"] == senior.user["id"] and review["decided_by_name"] and review["decided_at"] and review["requested_by"] == junior.user["id"]
    assert junior.get(f"/drafts/{d['id']}").json()["status"] == "APPROVED"  # the draft itself carries it
    assert audited(junior, "DRAFT_SENT_FOR_REVIEW") == 1 and audited(senior, "DRAFT_APPROVED") == 1


def test_who_may_send_and_who_may_decide(firm):
    junior, senior, owner = firm["junior"], firm["senior"], firm["owner"]
    d = make(junior)
    assert senior.post(f"/drafts/{d['id']}/send-for-review").status_code == 403  # a lawyer who did not write it cannot send it on the author's behalf
    assert owner.post(f"/drafts/{d['id']}/send-for-review").status_code == 200  # an admin or owner can
    assert junior.post(f"/drafts/{d['id']}/review", json={"decision": "approve"}).status_code == 403  # a member cannot approve
    assert junior.post(f"/drafts/{d['id']}/send-for-review").status_code == 409  # already with a reviewer
    own = make(senior)  # a lawyer's own draft
    assert senior.post(f"/drafts/{own['id']}/send-for-review").status_code == 200
    r = senior.post(f"/drafts/{own['id']}/review", json={"decision": "approve"})
    assert r.status_code == 403 and "someone else must review" in r.json()["detail"]
    assert owner.post(f"/drafts/{own['id']}/review", json={"decision": "approve"}).status_code == 200
    assert status(senior, own) == "APPROVED"


def test_a_one_person_firm_may_approve_its_own_draft(user_b):
    d = make(user_b)
    assert user_b.post(f"/drafts/{d['id']}/send-for-review").status_code == 200
    assert user_b.post(f"/drafts/{d['id']}/review", json={"decision": "approve"}).status_code == 200


def test_asking_for_changes_needs_a_reason_and_the_author_can_send_it_again(firm):
    junior, senior = firm["junior"], firm["senior"]
    d = make(junior)
    junior.post(f"/drafts/{d['id']}/send-for-review")
    assert senior.post(f"/drafts/{d['id']}/review", json={"decision": "changes"}).status_code == 422
    assert senior.post(f"/drafts/{d['id']}/review", json={"decision": "changes", "reason": "   "}).status_code == 422
    r = senior.post(f"/drafts/{d['id']}/review", json={"decision": "changes", "reason": "Add the date of the notice."})
    assert r.status_code == 200 and r.json()["status"] == "CHANGES_REQUESTED" and r.json()["review"]["reason"] == "Add the date of the notice."
    assert audited(senior, "DRAFT_CHANGES_REQUESTED") == 1
    assert junior.patch(f"/drafts/{d['id']}", json={"body": "Second version with the date."}).status_code == 200
    assert status(junior, d) == "CHANGES_REQUESTED"  # the author is working on it; it stays so until sent again
    assert junior.post(f"/drafts/{d['id']}/send-for-review").status_code == 200
    assert senior.post(f"/drafts/{d['id']}/review", json={"decision": "approve"}).json()["status"] == "APPROVED"


def test_any_change_to_the_text_after_it_was_sent_or_approved_returns_it_to_draft(firm):
    junior, senior = firm["junior"], firm["senior"]
    d = make(junior, "Text one for the reviewer.")
    junior.post(f"/drafts/{d['id']}/send-for-review")
    assert junior.patch(f"/drafts/{d['id']}", json={"body": "Text one for the reviewer, edited."}).status_code == 200
    assert status(junior, d) == "DRAFT"  # the reviewer would be approving text that no longer exists
    assert senior.post(f"/drafts/{d['id']}/review", json={"decision": "approve"}).status_code == 409
    junior.post(f"/drafts/{d['id']}/send-for-review")
    senior.post(f"/drafts/{d['id']}/review", json={"decision": "approve"})
    assert status(junior, d) == "APPROVED"
    assert junior.patch(f"/drafts/{d['id']}", json={"body": "Text one for the reviewer, edited.", "autosave": True}).status_code == 200
    assert status(junior, d) == "APPROVED"  # saving the very same text changes nothing
    assert junior.patch(f"/drafts/{d['id']}", json={"body": "A different text altogether.", "autosave": True}).status_code == 200
    got = junior.get(f"/drafts/{d['id']}/review").json()
    assert got["status"] == "DRAFT" and got["review"]["reset_from"] == "APPROVED" and got["review"]["decided_by"] == senior.user["id"]  # the earlier decision stays on record
    assert junior.patch(f"/drafts/{d['id']}", json={"title": "Another title"}).status_code == 200  # a title change on a draft in DRAFT stays DRAFT
    assert status(junior, d) == "DRAFT"


def test_comments_are_added_listed_in_order_resolved_and_cannot_be_edited_or_deleted(firm):
    junior, senior, owner = firm["junior"], firm["senior"], firm["owner"]
    d = make(junior)
    c1 = senior.post(f"/drafts/{d['id']}/comments", json={"text": "  Please add the invoice number.  "})
    assert c1.status_code == 200 and c1.json()["text"] == "Please add the invoice number." and c1.json()["author_id"] == senior.user["id"] and c1.json()["resolved_at"] is None
    c2 = junior.post(f"/drafts/{d['id']}/comments", json={"text": "Added."}).json()
    rows = owner.get(f"/drafts/{d['id']}/comments").json()
    assert [r["text"] for r in rows] == ["Please add the invoice number.", "Added."]
    assert junior.post(f"/drafts/{d['id']}/comments", json={"text": ""}).status_code == 422
    assert junior.post(f"/drafts/{d['id']}/comments", json={"text": "x" * 1001}).status_code == 422

    bystander = new_member(owner, "MEMBER")  # neither the author of the draft, nor of the comment, nor a reviewer
    cid = c1.json()["id"]
    assert bystander.post(f"/drafts/{d['id']}/comments/{cid}/resolve").status_code == 403
    assert junior.post(f"/drafts/{d['id']}/comments/{cid}/resolve").status_code == 200  # the author of the draft
    again = senior.post(f"/drafts/{d['id']}/comments/{cid}/resolve").json()
    assert again["resolved_at"] and again["resolved_by_name"]
    assert owner.post(f"/drafts/{d['id']}/comments/{c2['id']}/resolve").status_code == 200  # a reviewer role
    for method in ("patch", "put", "delete"):
        assert getattr(senior, method)(f"/drafts/{d['id']}/comments/{cid}").status_code in (404, 405)  # there is no way to change or remove a comment
    assert mongo().draft_comments.find_one({"id": cid})["text"] == "Please add the invoice number."
    assert audited(senior, "DRAFT_COMMENT") == 1 and audited(junior, "DRAFT_COMMENT_RESOLVED") == 1


def test_the_other_organisation_can_do_nothing_with_the_draft_or_its_comments(firm, user_b):
    junior, senior = firm["junior"], firm["senior"]
    d = make(junior)
    junior.post(f"/drafts/{d['id']}/send-for-review")
    cid = senior.post(f"/drafts/{d['id']}/comments", json={"text": "Private note."}).json()["id"]
    assert user_b.get(f"/drafts/{d['id']}/review").status_code == 404
    assert user_b.post(f"/drafts/{d['id']}/send-for-review").status_code == 404
    assert user_b.post(f"/drafts/{d['id']}/review", json={"decision": "approve"}).status_code == 404
    assert user_b.get(f"/drafts/{d['id']}/comments").status_code == 404
    assert user_b.post(f"/drafts/{d['id']}/comments", json={"text": "Hello"}).status_code == 404
    assert user_b.post(f"/drafts/{d['id']}/comments/{cid}/resolve").status_code == 404
    assert status(junior, d) == "WITH_REVIEWER"
    assert mongo().draft_comments.count_documents({"draft_id": d["id"]}) == 1
    # even with the comment's own id, a draft of the caller's own does not reach it
    own = make(user_b)
    assert user_b.post(f"/drafts/{own['id']}/comments/{cid}/resolve").status_code == 404


def test_deleting_the_draft_deletes_its_comments_and_the_export_carries_them(firm):
    import io
    import json
    import zipfile

    owner, junior = firm["owner"], firm["junior"]
    d = make(junior)
    owner.post(f"/drafts/{d['id']}/comments", json={"text": "Keep a record of this."})
    z = zipfile.ZipFile(io.BytesIO(owner.get("/org/export").content))
    assert any(r["text"] == "Keep a record of this." for r in json.loads(z.read("draft_comments.json")))
    assert owner.delete(f"/drafts/{d['id']}").status_code == 200
    assert mongo().draft_comments.count_documents({"draft_id": d["id"]}) == 0


def test_comments_and_review_notes_are_never_put_in_an_ai_prompt():
    root = Path(__file__).resolve().parent.parent
    users = [p.relative_to(root).as_posix() for p in list((root / "routers").glob("*.py")) + list((root / "lib").glob("*.py")) if "draft_comments" in p.read_text(encoding="utf-8")]
    assert sorted(users) == ["lib/purge.py", "routers/draft_review.py", "routers/org_data.py", "routers/research.py"], users  # purge and research.py only delete them with their draft; org_data.py exports them
    text = (root / "routers" / "research.py").read_text(encoding="utf-8")
    assert [line for line in text.splitlines() if "draft_comments" in line] == [line for line in text.splitlines() if "draft_comments.delete_many" in line]
