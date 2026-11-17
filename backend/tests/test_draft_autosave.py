"""A background save keeps what the person is typing without filling the version history or the audit log; a manual save still records both; nobody else can autosave into a draft."""
from tests.conftest import mongo, new_matter


def _draft(c):
    mid, _ = new_matter(c, "Autosave")
    return c.post("/drafts", json={"matter_id": mid, "title": "Letter", "body": "first"}).json()


def test_autosave_updates_the_text_but_makes_no_version_and_no_audit_entry(user_a):
    d = _draft(user_a)
    db = mongo()
    audits = db.audit_events.count_documents({"operation": "DRAFT_UPDATE", "organization_id": user_a.user["organization_id"]})
    for text in ("first, then more", "first, then more and more"):
        r = user_a.patch(f"/drafts/{d['id']}", json={"body": text, "autosave": True})
        assert r.status_code == 200 and r.json()["body"] == text and r.json()["version"] == d["version"]
    assert user_a.get(f"/drafts/{d['id']}").json()["body"] == "first, then more and more"
    assert db.draft_versions.count_documents({"draft_id": d["id"]}) == 0
    assert db.audit_events.count_documents({"operation": "DRAFT_UPDATE", "organization_id": user_a.user["organization_id"]}) == audits


def test_a_manual_save_still_makes_a_version_and_an_audit_entry(user_a):
    d = _draft(user_a)
    db = mongo()
    r = user_a.patch(f"/drafts/{d['id']}", json={"body": "saved by the person"})
    assert r.json()["version"] == d["version"] + 1
    assert db.draft_versions.count_documents({"draft_id": d["id"]}) == 1
    assert db.audit_events.count_documents({"operation": "DRAFT_UPDATE", "organization_id": user_a.user["organization_id"]}) >= 1


def test_another_organisation_cannot_autosave_into_the_draft(user_a, user_b):
    d = _draft(user_a)
    assert user_b.patch(f"/drafts/{d['id']}", json={"body": "intruder", "autosave": True}).status_code == 404
    assert user_a.get(f"/drafts/{d['id']}").json()["body"] == "first"


def test_the_autosave_flag_itself_is_not_stored_on_the_draft(user_a):
    d = _draft(user_a)
    user_a.patch(f"/drafts/{d['id']}", json={"body": "x", "autosave": True})
    assert "autosave" not in mongo().drafts.find_one({"id": d["id"]})
