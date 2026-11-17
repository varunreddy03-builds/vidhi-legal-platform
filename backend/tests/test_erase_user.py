"""Erasing ONE person (operator route and self-service), and the list of erasures that survives a restore. Invented people only."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from lib import erasure_ledger
from tests.conftest import mongo, new_matter, new_member
from tests.test_admin import admin  # noqa: F401  (fixture)

BACKEND = Path(__file__).resolve().parent.parent


def erase(admin_c, user, email=None):
    return admin_c.post(f"/admin/users/{user.user['id']}/erase", json={"confirm_email": email or user.user["email"]})


def test_the_operator_erases_one_person_and_the_firm_keeps_its_records(verified_a, admin):
    member = new_member(verified_a, "LAWYER")
    uid, email = member.user["id"], member.user["email"]
    mid, _ = new_matter(member, "ByMember")  # a record the member made for the firm (and an audit line with their email)
    db = mongo()
    org = member.user["organization_id"]
    db.support_tickets.insert_one({"id": str(uuid.uuid4()), "user_id": uid, "organization_id": org, "message": "my words"})
    db.push_subscriptions.insert_one({"user_id": uid, "organization_id": org, "endpoint": "https://example.test/ep"})
    assert db.audit_events.count_documents({"$or": [{"user_id": uid}, {"user_email": email}]}) > 0
    assert erase(admin, member, email="someone.else@example.com").status_code == 422  # the email must be typed correctly
    r = erase(admin, member)
    assert r.status_code == 200 and r.json()["erased"] is True
    assert db.users.find_one({"id": uid}) is None
    assert member.get("/auth/me").status_code == 401  # signed out everywhere
    assert db.support_tickets.count_documents({"user_id": uid}) == 0 and db.push_subscriptions.count_documents({"user_id": uid}) == 0
    # the audit trail stays for the firm, but no longer leads to the person
    assert db.audit_events.count_documents({"$or": [{"user_id": uid}, {"user_email": email}, {"detail": {"$regex": email, "$options": "i"}}]}) == 0
    assert db.audit_events.count_documents({"redacted": True, "organization_id": org}) > 0
    assert verified_a.get(f"/matters/{mid}").status_code == 200  # the matter the member made is still the firm's


def test_the_only_owner_cannot_be_erased_alone(verified_a, admin):
    verified_a.user = verified_a.get("/auth/me").json()
    r = erase(admin, verified_a)
    assert r.status_code == 409 and "only owner" in r.json()["detail"]
    assert mongo().users.find_one({"id": verified_a.user["id"]}) is not None


def test_an_ordinary_user_cannot_use_the_operator_route(verified_a, user_b):
    member = new_member(verified_a, "MEMBER")
    assert user_b.post(f"/admin/users/{member.user['id']}/erase", json={"confirm_email": "x@example.com"}).status_code == 404
    assert mongo().users.find_one({"id": member.user["id"]}) is not None


def test_a_person_erases_their_own_account_with_their_password(verified_a):
    member = new_member(verified_a, "LAWYER")
    uid, email = member.user["id"], member.user["email"]
    assert member.post("/privacy/erase-me", json={"password": "wrong", "confirm_email": email}).status_code == 403
    assert member.post("/privacy/erase-me", json={"password": member.password, "confirm_email": "no@example.com"}).status_code == 422
    assert mongo().users.find_one({"id": uid}) is not None
    ok = member.post("/privacy/erase-me", json={"password": member.password, "confirm_email": email})
    assert ok.status_code == 200 and mongo().users.find_one({"id": uid}) is None


# ---- the list of erasures that survives a restore ----
def test_the_ledger_holds_kinds_and_ids_only_and_ignores_damage(tmp_path, monkeypatch):
    f = tmp_path / "erasures.jsonl"
    monkeypatch.setenv("ERASURE_LEDGER_FILE", str(f))
    assert erasure_ledger.record("matter", "m-1") and erasure_ledger.record("user", "u-1") and erasure_ledger.record("matter", "m-1")
    assert not erasure_ledger.record("nonsense", "x") and not erasure_ledger.record("org", "")
    f.write_text(f.read_text() + "this line is damaged\n", encoding="utf-8")
    rows = erasure_ledger.read()
    assert [(r["kind"], r["id"]) for r in rows] == [("matter", "m-1"), ("user", "u-1")]  # repeated entry removed, damaged line skipped
    assert set(json.loads(f.read_text().splitlines()[0])) == {"kind", "id", "at"}
    monkeypatch.setenv("ERASURE_LEDGER_FILE", "")
    assert erasure_ledger.record("matter", "m-2") is False  # no ledger configured: nothing written


def run_tool(*args):
    return subprocess.run([sys.executable, "-I", str(BACKEND / "tools" / "reapply_erasures.py"), *args], capture_output=True, text=True, env=dict(os.environ), cwd=str(BACKEND))


def test_a_real_erasure_writes_the_ledger_and_the_tool_erases_it_again_after_a_restore(tmp_path):
    db = mongo()
    mid, org = f"led-m-{uuid.uuid4().hex[:8]}", f"led-o-{uuid.uuid4().hex[:8]}"
    ledger = tmp_path / "erasures.jsonl"

    def put():
        db.matters.insert_one({"id": mid, "organization_id": org, "title": "Invented ledger matter"})
        db.facts.insert_one({"id": f"{mid}-f", "matter_id": mid, "organization_id": org, "text": "invented fact"})

    put()
    # 1. a real erasure through the purge code records the ledger line
    code = "import asyncio, sys; sys.path.insert(0, sys.argv[2]); from lib import purge; asyncio.run(purge.purge_matter(sys.argv[1]))"
    r = subprocess.run([sys.executable, "-I", "-c", code, mid, str(BACKEND)], capture_output=True, text=True, cwd=str(BACKEND), env={**os.environ, "ERASURE_LEDGER_FILE": str(ledger)})
    assert r.returncode == 0, r.stderr
    assert db.matters.find_one({"id": mid}) is None
    assert [(x["kind"], x["id"]) for x in erasure_ledger.read(str(ledger))] == [("matter", mid)]
    # 2. a restore from an older backup brings the matter back (simulated), and the tool erases it again
    put()
    dry = run_tool("--ledger", str(ledger), "--dry-run")
    assert dry.returncode == 0 and "1 had come back" in dry.stdout and "nothing changed" in dry.stdout
    assert db.matters.find_one({"id": mid}) is not None
    real = run_tool("--ledger", str(ledger))
    assert real.returncode == 0 and "1 erased again" in real.stdout
    assert db.matters.find_one({"id": mid}) is None and db.facts.count_documents({"matter_id": mid}) == 0
    assert "0 had come back" in run_tool("--ledger", str(ledger)).stdout  # safe to run twice
    assert len(ledger.read_text().splitlines()) == 1  # re-applying did not write the ledger again
    assert run_tool("--ledger", str(tmp_path / "missing.jsonl")).returncode == 2
