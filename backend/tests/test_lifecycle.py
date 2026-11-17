"""Phase 6: deleting means deleting; retention only ever acts after notice; export; organisation erasure; monitoring."""

import io
import json
import os
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from tests.conftest import API_URL, make_case, mongo, new_matter, new_member, outbox, upload, verify_email

CRON = {"Authorization": f"Bearer {os.environ.get('WEBHOOK_CRON_SECRET', 'test-cron-secret-not-real')}"}


def ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def run_retention() -> None:
    """Trigger the job and wait for it to finish (it runs in the background under a lock)."""
    db = mongo()
    before = db.job_runs.find_one({"_id": "retention"}) or {}
    for _ in range(40):
        r = httpx.post(f"{API_URL}/cron/retention", headers=CRON, timeout=30)
        assert r.status_code == 200, r.text
        if r.json()["status"] == "accepted":
            break
        time.sleep(0.5)
    for _ in range(80):
        row = db.job_runs.find_one({"_id": "retention"}) or {}
        if row.get("last_ok_at") and row.get("last_ok_at") != before.get("last_ok_at"):
            return
        time.sleep(0.25)
    raise AssertionError("retention job did not finish")


@pytest.fixture
def team(user_a):
    verify_email(user_a)
    return {"OWNER": user_a, "ADMIN": new_member(user_a, "ADMIN"), "LAWYER": new_member(user_a, "LAWYER"), "MEMBER": new_member(user_a, "MEMBER")}


# ---------------------------------------------------------------------------------------------
# Deleting a matter / a case leaves nothing behind
# ---------------------------------------------------------------------------------------------
def test_deleting_a_matter_removes_its_files_records_and_audit_text(team):
    owner = team["OWNER"]
    mid, title = new_matter(owner, "Purge")
    doc = upload(owner, mid, "note.txt", "A short note about the dispute.")
    owner.post(f"/matters/{mid}/facts", json={"text": "Goods were delivered on 1 March.", "document_id": doc["id"]})
    db = mongo()
    gid = db.documents.find_one({"id": doc["id"]})["gridfs_id"]
    assert db.fs.files.find_one({"_id": gid})
    assert db.audit_events.count_documents({"matter_id": mid, "detail": {"$ne": None}}) >= 1
    assert owner.delete(f"/matters/{mid}").status_code == 200
    assert db.fs.files.find_one({"_id": gid}) is None
    assert db.fs.chunks.count_documents({"files_id": gid}) == 0
    for coll in ("documents", "facts", "timeline_events", "evidence_items", "drafts", "research_results"):
        assert db[coll].count_documents({"matter_id": mid}) == 0, coll
    assert db.audit_events.count_documents({"matter_id": mid, "detail": {"$ne": None}}) == 0
    assert db.audit_events.count_documents({"matter_id": mid, "operation": "MATTER_DELETE"}) == 1  # the trail stays, the text goes


def test_deleting_a_case_removes_proofs_confirmations_email_records_and_names_in_audit(user_a):
    cid = make_case(user_a)
    db = mongo()
    org = user_a.get("/auth/me").json()["organization_id"]
    db.recovery_proofs.insert_one({"id": str(uuid.uuid4()), "case_id": cid, "organization_id": org, "filename": "p.pdf", "created_at": ago(1)})
    db.email_confirmations.insert_one({"id": str(uuid.uuid4()), "case_id": cid, "expires_at": ago(-1)})
    db.email_log.insert_one({"id": str(uuid.uuid4()), "case_id": cid, "organization_id": org, "to": "debtor@example.com", "created_at": ago(1)})
    assert db.audit_events.count_documents({"organization_id": org, "detail": {"$regex": "Debtor X"}}) >= 1
    assert user_a.delete(f"/recovery/cases/{cid}").status_code == 200
    for coll in ("recovery_cases", "recovery_proofs", "email_confirmations", "email_log"):
        assert db[coll].count_documents({"case_id": cid} if coll != "recovery_cases" else {"id": cid}) == 0, coll
    assert db.audit_events.count_documents({"organization_id": org, "detail": {"$regex": "Debtor X"}}) == 0


# ---------------------------------------------------------------------------------------------
# Legal hold
# ---------------------------------------------------------------------------------------------
def test_legal_hold_is_admin_only_and_blocks_deletion(team):
    owner, admin, lawyer = team["OWNER"], team["ADMIN"], team["LAWYER"]
    mid, _ = new_matter(owner, "Hold")
    assert lawyer.patch(f"/matters/{mid}/legal-hold", json={"on": True}).status_code == 403
    assert admin.patch(f"/matters/{mid}/legal-hold", json={"on": True}).json()["legal_hold"] is True
    r = owner.delete(f"/matters/{mid}")
    assert r.status_code == 409 and "legal hold" in r.json()["detail"].lower()
    assert owner.patch(f"/matters/{mid}/legal-hold", json={"on": False}).status_code == 200
    assert owner.delete(f"/matters/{mid}").status_code == 200


# ---------------------------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------------------------
def test_retention_setting_rules(team):
    owner, admin, lawyer = team["OWNER"], team["ADMIN"], team["LAWYER"]
    assert owner.get("/org/retention").json()["retention_days_after_close"] is None  # no default deletion
    assert lawyer.put("/org/retention", json={"retention_days_after_close": 90}).status_code == 403
    assert admin.put("/org/retention", json={"retention_days_after_close": 5}).status_code == 422
    assert admin.put("/org/retention", json={"retention_days_after_close": 90}).json()["retention_days_after_close"] == 90
    assert admin.put("/org/retention", json={"retention_days_after_close": None}).json()["retention_days_after_close"] is None


def test_retention_notifies_first_then_deletes_and_respects_hold_reopen_and_other_orgs(team, user_b):
    owner, admin = team["OWNER"], team["ADMIN"]
    db = mongo()
    keep_open, _ = new_matter(owner, "StillOpen")
    old, old_title = new_matter(owner, "OldClosed")
    held, _ = new_matter(owner, "OldHeld")
    revived, _ = new_matter(owner, "OldRevived")
    other_org, _ = new_matter(user_b, "OtherOrgOld")  # org B never set a retention period
    for m in (old, held, revived, other_org):
        db.matters.update_one({"id": m}, {"$set": {"status": "CLOSED", "closed_at": ago(200)}})
    owner.patch(f"/matters/{held}/legal-hold", json={"on": True})
    admin.put("/org/retention", json={"retention_days_after_close": 90})

    run_retention()  # step 1: owners are told, nothing is deleted yet
    assert all(db.matters.find_one({"id": m}) for m in (keep_open, old, held, revived, other_org))
    assert db.matters.find_one({"id": old}).get("deletion_notice_at")
    assert not db.matters.find_one({"id": held}).get("deletion_notice_at")
    mail = [m for m in outbox(to=owner.user["email"], subject_has="deleted in 30 days")]
    assert mail and old_title in mail[-1]["html"]

    # the owner re-opens one matter: its notice is cancelled
    assert owner.patch(f"/matters/{revived}", json={"status": "OPEN"}).status_code == 200
    assert not db.matters.find_one({"id": revived}).get("deletion_notice_at")

    # 31 days after the notice: now it is deleted, and only what qualifies
    db.matters.update_one({"id": old}, {"$set": {"deletion_notice_at": ago(31)}})
    run_retention()
    assert db.matters.find_one({"id": old}) is None
    assert all(db.matters.find_one({"id": m}) for m in (keep_open, held, revived, other_org))


def test_retention_does_nothing_unless_an_organisation_set_a_period(user_a):
    db = mongo()
    mid, _ = new_matter(user_a, "NoPolicy")
    db.matters.update_one({"id": mid}, {"$set": {"status": "CLOSED", "closed_at": ago(3000), "deletion_notice_at": ago(400)}})
    run_retention()
    assert db.matters.find_one({"id": mid})


def test_cron_retention_needs_the_secret(anon):
    assert anon.post("/cron/retention").status_code == 401
    assert anon.post("/cron/retention", headers={"Authorization": "Bearer nope"}).status_code == 401


# ---------------------------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------------------------
def test_export_contains_the_organisations_data_and_files_only(team, user_b):
    owner, admin, lawyer = team["OWNER"], team["ADMIN"], team["LAWYER"]
    mid, title = new_matter(owner, "Export")
    upload(owner, mid, "agreement.txt", "ORIGINAL-FILE-CONTENT-12345")
    other, other_title = new_matter(user_b, "Foreign")
    assert lawyer.get("/org/export").status_code == 403
    r = admin.get("/org/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "matters.json" in names and "members.json" in names
    assert any(n.startswith("files/") and n.endswith("agreement.txt") for n in names)
    blob = b"".join(z.read(n) for n in names)
    assert title.encode() in blob and b"ORIGINAL-FILE-CONTENT-12345" in blob
    assert other_title.encode() not in blob
    assert b"password_hash" not in blob and b"$2b$" not in blob
    assert [m["role"] for m in json.loads(z.read("members.json"))].count("OWNER") == 1
    assert mongo().audit_events.count_documents({"organization_id": owner.get("/auth/me").json()["organization_id"], "operation": "ORG_EXPORT"}) == 1


# ---------------------------------------------------------------------------------------------
# Erasing the organisation
# ---------------------------------------------------------------------------------------------
def test_erasure_needs_owner_password_and_typed_name_then_removes_everything(team, user_b):
    owner, admin = team["OWNER"], team["ADMIN"]
    me = owner.get("/auth/me").json()
    org, name = me["organization_id"], me["organization_name"]
    pw = owner.password
    mid, _ = new_matter(owner, "Erase")
    doc = upload(owner, mid, "x.txt", "to be erased")
    make_case(owner)
    db = mongo()
    gid = db.documents.find_one({"id": doc["id"]})["gridfs_id"]
    db.payment_transactions.insert_one({"session_id": f"s-{uuid.uuid4().hex}", "user_id": me["id"], "organization_id": org, "amount": 4900, "currency": "usd", "status": "complete"})
    keep, _ = new_matter(user_b, "Survivor")

    body = {"password": "wrong-password-xyz", "organization_name": name}
    assert admin.request("DELETE", "/org", json={**body, "password": "whatever"}).status_code == 403   # not an owner
    assert owner.request("DELETE", "/org", json=body).status_code == 403                                  # wrong password
    assert owner.request("DELETE", "/org", json={"password": pw, "organization_name": "Not the name"}).status_code == 422
    assert db.matters.find_one({"id": mid})  # still there after every refusal

    r = owner.request("DELETE", "/org", json={"password": pw, "organization_name": name})
    assert r.status_code == 200, r.text
    assert db.matters.count_documents({"organization_id": org}) == 0
    assert db.recovery_cases.count_documents({"organization_id": org}) == 0
    assert db.users.count_documents({"organization_id": org}) == 0
    assert db.sessions.count_documents({"user_id": {"$in": [me["id"]]}}) == 0
    assert db.organizations.find_one({"id": org}) is None
    assert db.audit_events.count_documents({"organization_id": org}) == 0
    assert db.fs.files.find_one({"_id": gid}) is None
    pay = db.payment_transactions.find_one({"session_id": {"$regex": "^s-"}, "anonymised": True})
    assert pay and pay["user_id"] is None and pay["organization_id"] is None and pay["amount"] == 4900
    log = db.erasure_log.find_one({"organization_id": org})
    assert log and "@" not in json.dumps(log, default=str)  # counts only: no names, no addresses
    assert owner.get("/auth/me").status_code == 401
    assert db.matters.find_one({"id": keep})  # nobody else's data was touched


# ---------------------------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------------------------
def test_readiness_reports_database_and_jobs(anon):
    r = anon.get("/health/ready")
    assert r.status_code == 200 and r.json()["database"] == "up" and r.json()["status"] in ("ok", "degraded")


def test_overdue_or_failed_jobs_show_as_degraded(anon):
    db = mongo()
    saved = db.job_runs.find_one({"_id": "recovery-reminders"})
    try:
        db.job_runs.update_one({"_id": "recovery-reminders"}, {"$set": {"last_ok_at": ago(5)}}, upsert=True)
        body = anon.get("/health/ready").json()
        assert body["status"] == "degraded" and {"job": "recovery-reminders", "problem": "overdue"} in body["jobs"]
        db.job_runs.update_one({"_id": "recovery-reminders"}, {"$set": {"last_ok_at": ago(1), "last_failed_at": datetime.now(timezone.utc)}})
        assert {"job": "recovery-reminders", "problem": "last run failed"} in anon.get("/health/ready").json()["jobs"]
    finally:
        if saved:
            db.job_runs.replace_one({"_id": "recovery-reminders"}, saved)
        else:
            db.job_runs.delete_one({"_id": "recovery-reminders"})


def test_every_response_carries_a_request_id_and_hostile_ids_are_replaced(anon):
    r = anon.get("/health")
    assert len(r.headers["x-request-id"]) >= 8
    good = "abc12345-trace"
    assert anon.get("/health", headers={"X-Request-ID": good}).headers["x-request-id"] == good
    bad = anon.get("/health", headers={"X-Request-ID": "bad id with <script>"})
    assert bad.headers["x-request-id"] != "bad id with <script>" and "<" not in bad.headers["x-request-id"]
