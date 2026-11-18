"""Review requests between colleagues of one firm: who may be asked, who may decide, one decision, and nothing crossing into another organisation."""

import uuid

from tests.conftest import mongo, new_matter, upload
from tests.test_rbac import team  # noqa: F401  (fixture)


def doc_in(c, mid):
    return upload(c, mid, f"memo-{uuid.uuid4().hex[:8]}.txt", f"A short memo. {uuid.uuid4().hex}\n")["id"]


def ask(c, mid, kind, ref, reviewer, note=""):
    return c.post(f"/matters/{mid}/reviews", json={"kind": kind, "ref_id": ref, "reviewer_id": reviewer, "note": note})


def test_a_colleague_can_be_asked_and_decides_once(team):  # noqa: F811
    owner, lawyer = team["OWNER"], team["LAWYER"]
    mid, _ = new_matter(owner, "Review matter")
    ref = doc_in(owner, mid)
    choices = owner.get(f"/matters/{mid}/reviews/reviewers").json()["reviewers"]
    ids = {c["id"] for c in choices}
    assert lawyer.user["id"] in ids and owner.user["id"] not in ids and team["MEMBER"].user["id"] not in ids  # owner, admin, lawyer only; not yourself
    made = ask(owner, mid, "document", ref, lawyer.user["id"], "Please check the dates")
    assert made.status_code == 201, made.text
    rid = made.json()["id"]
    assert "organization_id" not in made.json() and made.json()["status"] == "REQUESTED"
    assert ask(owner, mid, "document", ref, lawyer.user["id"]).status_code == 409  # not twice while one is open
    waiting = lawyer.get("/reviews/mine").json()["reviews"]
    assert [r["id"] for r in waiting] == [rid]
    assert owner.post(f"/reviews/{rid}/decision", json={"decision": "APPROVED"}).status_code == 404  # only the person asked can decide
    assert lawyer.post(f"/reviews/{rid}/decision", json={"decision": "CHANGES_REQUESTED", "comment": ""}).status_code == 422  # say what should change
    done = lawyer.post(f"/reviews/{rid}/decision", json={"decision": "CHANGES_REQUESTED", "comment": "Dates in paragraph 2 differ"})
    assert done.status_code == 200 and done.json()["status"] == "CHANGES_REQUESTED" and done.json()["decided_at"]
    assert lawyer.post(f"/reviews/{rid}/decision", json={"decision": "APPROVED"}).status_code == 404  # one decision only
    assert lawyer.get("/reviews/mine").json()["reviews"] == []
    listed = owner.get(f"/matters/{mid}/reviews").json()["reviews"]
    assert listed[0]["decision_comment"] == "Dates in paragraph 2 differ"
    ops = {a["operation"] for a in mongo().audit_events.find({"matter_id": mid})}
    assert {"REVIEW_REQUESTED", "REVIEW_DECIDED"} <= ops


def test_a_member_cannot_decide_and_the_item_and_reviewer_must_belong_to_the_firm(team, user_b):  # noqa: F811
    owner, member = team["OWNER"], team["MEMBER"]
    mid, _ = new_matter(owner, "Review matter 2")
    ref = doc_in(owner, mid)
    assert ask(owner, mid, "document", ref, member.user["id"]).status_code == 422  # a plain member is not a reviewer
    assert ask(owner, mid, "document", "no-such-item", team["LAWYER"].user["id"]).status_code == 404
    assert ask(owner, mid, "draft", ref, team["LAWYER"].user["id"]).status_code == 404  # right id, wrong kind of item
    assert ask(owner, mid, "document", ref, user_b.user["id"]).status_code == 422  # someone from another firm
    rid = ask(owner, mid, "document", ref, team["LAWYER"].user["id"]).json()["id"]
    assert member.post(f"/reviews/{rid}/decision", json={"decision": "APPROVED"}).status_code == 403


def test_another_organisation_sees_nothing_and_a_sole_practitioner_may_ask_themselves(user_a, user_b):
    mid, _ = new_matter(user_a, "Solo matter")
    ref = doc_in(user_a, mid)
    assert user_b.get(f"/matters/{mid}/reviews").status_code == 404
    assert user_b.get(f"/matters/{mid}/reviews/reviewers").status_code == 404
    assert ask(user_b, mid, "document", ref, user_b.user["id"]).status_code == 404
    own = ask(user_a, mid, "document", ref, user_a.user["id"])
    assert own.status_code == 201, own.text  # a one-person firm can ask itself, as with draft approval
    rid = own.json()["id"]
    assert user_b.post(f"/reviews/{rid}/decision", json={"decision": "APPROVED"}).status_code == 404
    assert user_a.post(f"/reviews/{rid}/decision", json={"decision": "APPROVED"}).status_code == 200


def test_reviews_are_erased_with_the_matter(user_a):
    mid, _ = new_matter(user_a, "Erase me")
    ref = doc_in(user_a, mid)
    assert ask(user_a, mid, "document", ref, user_a.user["id"]).status_code == 201
    assert mongo().reviews.count_documents({"matter_id": mid}) == 1
    assert user_a.delete(f"/matters/{mid}").status_code in (200, 204)
    assert mongo().reviews.count_documents({"matter_id": mid}) == 0
