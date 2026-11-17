"""Upload expiry (decision D5): uploads are kept at most UPLOAD_MAX_DAYS (the test server runs with 30). Owners are told first, a matter under legal hold is never touched,
and a person can always delete a document at once. Documents are backdated straight in the database; the job runs through the real cron route."""

import os
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from lib import upload_expiry
from tests.conftest import API_URL, mongo, new_matter, outbox, upload, verify_email
from tests.inproc import run

CRON = {"Authorization": f"Bearer {os.environ.get('WEBHOOK_CRON_SECRET', 'test-cron-secret-not-real')}"}


def ago(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def run_expiry() -> dict:
    """Trigger the job and wait for it to finish (it runs in the background under a lock)."""
    db = mongo()
    for _ in range(40):
        asked_at = datetime.now(timezone.utc).replace(tzinfo=None)  # stored times are naive UTC
        r = httpx.post(f"{API_URL}/cron/upload-expiry", headers=CRON, timeout=30)
        assert r.status_code == 200, r.text
        if r.json()["status"] == "accepted":
            break
        time.sleep(0.5)
    for _ in range(80):
        row = db.job_runs.find_one({"_id": "upload-expiry"}) or {}
        # OUR run is one that STARTED after we asked (parallel workers share one server: a run another test started earlier, even one that finishes between our read and our request, must not be taken for ours)
        started, ok = row.get("last_started_at"), row.get("last_ok_at")
        if started and ok and started >= asked_at and ok >= started:
            return row
        time.sleep(0.25)
    raise AssertionError("upload-expiry job did not finish")


def backdate(doc_id: str, days: float) -> None:
    mongo().documents.update_one({"id": doc_id}, {"$set": {"created_at": ago(days)}})


@pytest.fixture
def owner(user_a):
    verify_email(user_a)
    return user_a


def exists(doc_id: str) -> bool:
    return mongo().documents.count_documents({"id": doc_id}) == 1


def test_a_file_near_the_ceiling_is_announced_to_the_owners_and_kept(owner):
    mid, _ = new_matter(owner, "Expiry notice")
    d = upload(owner, mid, "soon-gone.txt", "A short note about the dispute.")
    backdate(d["id"], 25)
    run_expiry()
    row = mongo().documents.find_one({"id": d["id"]})
    assert row is not None and row.get("expiry_notice_at") is not None
    mail = outbox(owner.get("/auth/me").json()["email"], "Uploaded files will be deleted")
    assert mail and "soon-gone.txt" in mail[-1]["html"] and (datetime.now(timezone.utc) + timedelta(days=5)).date().isoformat() in mail[-1]["html"]


def test_a_noticed_file_past_the_ceiling_is_deleted_for_real_and_the_rest_stay(owner):
    mid, _ = new_matter(owner, "Expiry delete")
    old, fresh = upload(owner, mid, "old.txt", "Old note about rent."), upload(owner, mid, "fresh.txt", "Fresh note about rent.")
    db = mongo()
    gid = db.documents.find_one({"id": old["id"]})["gridfs_id"]
    owner.post(f"/matters/{mid}/facts", json={"value": "Rent was due on 1 March.", "document_id": old["id"]})
    backdate(old["id"], 31)
    db.documents.update_one({"id": old["id"]}, {"$set": {"expiry_notice_at": ago(7)}})
    run_expiry()
    assert not exists(old["id"]) and db.fs.files.find_one({"_id": gid}) is None and db.fs.chunks.count_documents({"files_id": gid}) == 0
    assert exists(fresh["id"])
    assert db.facts.find_one({"matter_id": mid})["document_id"] is None  # the person's own record stays, only the link goes
    ev = db.audit_events.find_one({"matter_id": mid, "operation": "UPLOAD_EXPIRED"})
    assert ev and ev["detail"] == old["id"] and "old.txt" not in str(ev)  # the trail names no file


def in_process(coro):
    """Run the job's code in this process, limited to one organisation, so that other tests running the same job at the same time cannot change the outcome."""
    return run(coro)


def test_a_file_just_past_the_ceiling_without_a_notice_is_announced_first_then_deleted_next_run(owner):
    mid, _ = new_matter(owner, "Expiry grace")
    org = owner.get("/auth/me").json()["organization_id"]
    d = upload(owner, mid, "late.txt", "Late note about a cheque.")
    backdate(d["id"], 31)
    first = in_process(upload_expiry.run_upload_expiry(days=30, only_org=org))
    assert first["notified"] == 1 and first["deleted"] == 0
    assert exists(d["id"]) and mongo().documents.find_one({"id": d["id"]}).get("expiry_notice_at") is not None
    second = in_process(upload_expiry.run_upload_expiry(days=30, only_org=org))
    assert second["deleted"] == 1 and not exists(d["id"])


def test_a_file_is_not_announced_before_the_notice_window_and_an_off_setting_does_nothing(owner):
    mid, _ = new_matter(owner, "Expiry window")
    org = owner.get("/auth/me").json()["organization_id"]
    d = upload(owner, mid, "early.txt", "Early note about a cheque.")
    backdate(d["id"], 22)  # 8 days left of 30: outside the 7-day notice window
    assert in_process(upload_expiry.run_upload_expiry(days=30, only_org=org)) == {"enabled": True, "notified": 0, "deleted": 0, "notice_failed": 0}
    backdate(d["id"], 400)
    assert in_process(upload_expiry.run_upload_expiry(days=0, only_org=org)) == {"enabled": False, "notified": 0, "deleted": 0, "notice_failed": 0}
    assert exists(d["id"])  # switched off: nothing is deleted, however old


def test_a_file_far_past_the_ceiling_is_deleted_even_if_no_notice_could_be_sent(owner):
    mid, _ = new_matter(owner, "Expiry hard ceiling")
    d = upload(owner, mid, "very-old.txt", "Very old note.")
    backdate(d["id"], 40)
    run_expiry()
    assert not exists(d["id"])


def test_a_matter_under_legal_hold_is_never_touched(owner):
    mid, _ = new_matter(owner, "Held")
    d = upload(owner, mid, "held.txt", "Held note about a notice.")
    assert owner.patch(f"/matters/{mid}/legal-hold", json={"on": True}).json()["legal_hold"] is True
    backdate(d["id"], 90)
    mongo().documents.update_one({"id": d["id"]}, {"$set": {"expiry_notice_at": ago(60)}})
    run_expiry()
    assert exists(d["id"])
    assert owner.patch(f"/matters/{mid}/legal-hold", json={"on": False}).status_code == 200
    run_expiry()
    assert not exists(d["id"])


def test_other_organisations_files_are_judged_only_by_their_own_age(owner, user_b):
    verify_email(user_b)
    ma, _ = new_matter(owner, "A")
    mb, _ = new_matter(user_b, "B")
    da, db_ = upload(owner, ma, "a.txt", "Note A about delivery."), upload(user_b, mb, "b.txt", "Note B about delivery.")
    backdate(da["id"], 45)
    run_expiry()
    assert not exists(da["id"]) and exists(db_["id"])


def test_deleting_a_document_at_once_removes_the_stored_file_and_clears_links(owner):
    mid, _ = new_matter(owner, "Delete now")
    d = upload(owner, mid, "now.txt", "A note to delete now.")
    db = mongo()
    gid = db.documents.find_one({"id": d["id"]})["gridfs_id"]
    owner.post(f"/matters/{mid}/facts", json={"value": "A fact from the note.", "document_id": d["id"]})
    assert owner.delete(f"/documents/{d['id']}").status_code == 200
    assert not exists(d["id"]) and db.fs.files.find_one({"_id": gid}) is None
    assert db.facts.find_one({"matter_id": mid})["document_id"] is None


@pytest.mark.parametrize("raw,expected", [("", 0), ("0", 0), ("abc", 0), ("7", 0), ("8", 8), ("30", 30), ("365", 365), ("366", 0), ("-5", 0)])
def test_the_ceiling_setting_is_read_safely(monkeypatch, raw, expected):
    monkeypatch.setenv("UPLOAD_MAX_DAYS", raw)
    assert upload_expiry.max_days() == expected  # anything outside 8-365 days, or not a number, leaves expiry off rather than guessing
