"""Default retention: operational records expire on fixed periods, and closed matters can expire by a platform default that each organisation can override.
The sweeps run in a child process against their own scratch database, so they can never touch other tests' rows. Invented data only."""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pymongo import MongoClient

BACKEND = Path(__file__).resolve().parent.parent
NOW = datetime.now(timezone.utc)


def ago(days):
    return NOW - timedelta(days=days)


@pytest.fixture
def scratch():
    name = f"vidhi_ret_{uuid.uuid4().hex[:8]}"
    client = MongoClient(os.environ["MONGO_URL"])
    yield client[name], name
    client.drop_database(name)
    client.close()


def sweep(db_name, expr, **env):
    """Run `expr` (a coroutine expression using `retention`) against the scratch database and return its JSON result."""
    code = f"import asyncio, json, sys; sys.path.insert(0, sys.argv[1]); from lib import retention; print(json.dumps(asyncio.run({expr}), default=str))"
    e = {**os.environ, "DB_NAME": db_name, "EMAIL_DRY_RUN": "true", "ERASURE_LEDGER_FILE": "", **env}
    r = subprocess.run([sys.executable, "-I", "-c", code, str(BACKEND)], capture_output=True, text=True, env=e, cwd=str(BACKEND))
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_operational_records_past_their_period_are_deleted_and_newer_ones_kept(scratch):
    db, name = scratch
    db.email_log.insert_many([{"id": "old", "created_at": ago(400)}, {"id": "new", "created_at": ago(10)}])
    db.support_tickets.insert_many([{"id": "old", "created_at": ago(400)}, {"id": "new", "created_at": ago(10)}])
    db.usage_events.insert_many([{"id": "old", "timestamp": ago(450)}, {"id": "new", "timestamp": ago(10)}])
    db.audit_events.insert_many([{"id": "old", "created_at": ago(800)}, {"id": "mid", "created_at": ago(500)}, {"id": "new", "created_at": ago(10)}])
    db.research_results.insert_many([
        {"id": "r-old", "matter_id": None, "created_at": ago(120)}, {"id": "r-new", "matter_id": None, "created_at": ago(5)}, {"id": "r-matter", "matter_id": "m1", "created_at": ago(300)}])
    db.answer_feedback.insert_one({"id": "f1", "research_id": "r-old"})
    out = sweep(name, "retention.purge_operational()")
    assert out == {"email_log": 1, "support_tickets": 1, "usage_events": 1, "audit_events": 1, "research_results": 1}
    assert [r["id"] for r in db.email_log.find()] == ["new"] and [r["id"] for r in db.support_tickets.find()] == ["new"]
    assert sorted(r["id"] for r in db.audit_events.find()) == ["mid", "new"]  # 800 days is past 730; 500 is not
    assert sorted(r["id"] for r in db.research_results.find()) == ["r-matter", "r-new"]  # an answer inside a matter goes with the matter, not on a timer
    assert db.answer_feedback.count_documents({}) == 0


def test_a_period_of_zero_turns_that_one_off_and_an_invalid_value_means_the_default(scratch):
    db, name = scratch
    db.email_log.insert_one({"id": "old", "created_at": ago(400)})
    db.support_tickets.insert_one({"id": "old", "created_at": ago(400)})
    out = sweep(name, "retention.purge_operational()", EMAIL_LOG_DAYS="0", SUPPORT_TICKET_DAYS="not-a-number")
    assert "email_log" not in out and db.email_log.count_documents({}) == 1  # 0 = keep
    assert out["support_tickets"] == 1  # invalid: the 365-day default applies


def make_org(db, org_id, **extra):
    db.organizations.insert_one({"id": org_id, "name": f"Org {org_id}", **extra})
    db.users.insert_one({"id": f"{org_id}-u", "email": f"{org_id}@example.test", "organization_id": org_id, "role": "OWNER", "full_name": "Invented Owner"})


def closed_matter(db, org_id, mid, closed_days_ago, notice_days_ago=None):
    row = {"id": mid, "organization_id": org_id, "title": f"Matter {mid}", "status": "CLOSED", "closed_at": ago(closed_days_ago)}
    if notice_days_ago is not None:
        row["deletion_notice_at"] = ago(notice_days_ago)
    db.matters.insert_one(row)


def test_the_platform_default_applies_to_an_organisation_that_did_not_choose_and_the_owners_are_warned_first(scratch):
    db, name = scratch
    make_org(db, "o-default")
    closed_matter(db, "o-default", "m-old", closed_days_ago=400)
    closed_matter(db, "o-default", "m-recent", closed_days_ago=100)
    first = sweep(name, "retention.run_retention()", DEFAULT_RETENTION_DAYS_AFTER_CLOSE="365")
    assert first["notified"] == 1 and first["deleted_matters"] == 0  # warned, not deleted
    assert db.matters.find_one({"id": "m-old"})["deletion_notice_at"] and db.email_outbox.count_documents({"subject": {"$regex": "deleted"}}) == 1
    db.matters.update_one({"id": "m-old"}, {"$set": {"deletion_notice_at": ago(31)}})  # the 30 days of notice have passed
    second = sweep(name, "retention.run_retention()", DEFAULT_RETENTION_DAYS_AFTER_CLOSE="365")
    assert second["deleted_matters"] == 1
    assert db.matters.find_one({"id": "m-old"}) is None and db.matters.find_one({"id": "m-recent"}) is not None


def test_an_organisations_own_choice_beats_the_default_and_zero_keeps_everything(scratch):
    db, name = scratch
    make_org(db, "o-keep", retention_days_after_close=0)  # chose: keep everything until I delete it
    make_org(db, "o-own", retention_days_after_close=500)  # chose a longer period than the default
    closed_matter(db, "o-keep", "k1", closed_days_ago=900, notice_days_ago=60)
    closed_matter(db, "o-own", "w1", closed_days_ago=400, notice_days_ago=60)
    out = sweep(name, "retention.run_retention()", DEFAULT_RETENTION_DAYS_AFTER_CLOSE="365")
    assert out["deleted_matters"] == 0 and out["notified"] == 0
    assert db.matters.count_documents({}) == 2


def test_with_no_platform_default_nothing_changes_for_an_organisation_that_never_chose(scratch):
    db, name = scratch
    make_org(db, "o-none")
    closed_matter(db, "o-none", "n1", closed_days_ago=2000, notice_days_ago=100)
    out = sweep(name, "retention.run_retention()")
    assert out["organisations"] == 0 and out["deleted_matters"] == 0 and db.matters.count_documents({}) == 1


def test_a_default_shorter_than_the_minimum_is_ignored(scratch):
    _, name = scratch
    assert sweep(name, "asyncio.sleep(0, retention.platform_default_days())", DEFAULT_RETENTION_DAYS_AFTER_CLOSE="10") == 0
    assert sweep(name, "asyncio.sleep(0, retention.platform_default_days())", DEFAULT_RETENTION_DAYS_AFTER_CLOSE="365") == 365


def test_the_retention_setting_accepts_none_zero_or_a_period_and_reports_the_platform_default(verified_a):
    assert verified_a.get("/org/retention").json()["platform_default_days"] == 0
    assert verified_a.put("/org/retention", json={"retention_days_after_close": 0}).json()["retention_days_after_close"] == 0
    assert verified_a.put("/org/retention", json={"retention_days_after_close": 5}).status_code == 422
    assert verified_a.put("/org/retention", json={"retention_days_after_close": 90}).json()["retention_days_after_close"] == 90
    assert verified_a.put("/org/retention", json={"retention_days_after_close": None}).json()["retention_days_after_close"] is None
