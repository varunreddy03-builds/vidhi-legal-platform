"""Plans as data: free, pro and firm limits and prices come from a file the operator edits, a mistake in the file can never remove a limit, and no limit can be got around.
The test server reads tests/fixtures/plans_test.json (the shipped plans, except that the firm plan allows 3 people)."""
import copy
import json
import os
import time
import uuid
from pathlib import Path

import pytest

from lib import plan_config
from tests.conftest import answer, mongo, new_member, set_plan, stub, verify_email
from tests.test_admin import admin  # noqa: F401  (the operator's session)

SHIPPED = Path(__file__).resolve().parent.parent / "data" / "plans.json"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "plans_test.json"


def shipped() -> dict:
    return json.loads(SHIPPED.read_text(encoding="utf-8"))


@pytest.fixture
def plans_file(tmp_path, monkeypatch):
    for name in ("FREE_AI_PER_DAY", "PRO_AI_PER_DAY", "FREE_CONTEXT_CHARS", "FREE_AI_PLATFORM_PER_DAY"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "plans.json"
    monkeypatch.setenv("PLANS_FILE", str(path))

    def write(data) -> Path:
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        os.utime(path, (time.time() + write.n, time.time() + write.n))  # a distinct modification time each write, as a real edit would have
        write.n += 1
        return path

    write.n = 1
    return write


# ---- the file ----

def test_the_shipped_file_is_valid_and_matches_the_built_in_defaults():
    data = shipped()
    assert plan_config.problems(data) == []
    for tier in plan_config.TIERS:
        for key in ("ai_per_day", "context_chars", "locked_tasks", "members_max"):
            assert data["plans"][tier][key] == plan_config.DEFAULTS["plans"][tier][key], (tier, key)
    assert data["free_platform_ai_per_day"] == plan_config.DEFAULTS["free_platform_ai_per_day"]
    assert all(data["plans"][t]["price"]["amount"] is None for t in ("pro", "firm"))  # prices are placeholders: nothing invented


def test_the_test_fixture_differs_from_the_shipped_plans_only_in_the_firm_member_limit():
    a, b = shipped(), json.loads(FIXTURE.read_text(encoding="utf-8"))
    a["plans"]["firm"]["members_max"] = b["plans"]["firm"]["members_max"]
    a["_about"] = b["_about"]
    assert a == b and b["plans"]["firm"]["members_max"] == 3


def test_an_edit_is_picked_up_without_a_restart(plans_file):
    data = shipped()
    plans_file(data)
    assert plan_config.plan("free")["ai_per_day"] == 5
    data["plans"]["free"]["ai_per_day"] = 9
    data["plans"]["firm"]["members_max"] = 40
    data["plans"]["firm"]["price"]["amount"] = 4999
    plans_file(data)
    assert plan_config.plan("free")["ai_per_day"] == 9 and plan_config.plan("firm")["members_max"] == 40
    assert plan_config.load()["plans"]["firm"]["price"]["amount"] == 4999
    assert plan_config.status()["problem"] is None


BAD = {
    "not json": "{ this is not json",
    "empty file": "",
    "no plans": {"x": 1},
    "firm plan missing": lambda d: d["plans"].pop("firm"),
    "ai_per_day empty": lambda d: d["plans"]["free"].update(ai_per_day=None),
    "ai_per_day text": lambda d: d["plans"]["free"].update(ai_per_day="5"),
    "ai_per_day decimal": lambda d: d["plans"]["free"].update(ai_per_day=5.5),
    "ai_per_day true": lambda d: d["plans"]["pro"].update(ai_per_day=True),
    "ai_per_day negative": lambda d: d["plans"]["pro"].update(ai_per_day=-1),
    "ai_per_day huge": lambda d: d["plans"]["firm"].update(ai_per_day=10**9),
    "ai_per_day removed": lambda d: d["plans"]["firm"].pop("ai_per_day"),
    "free above pro": lambda d: d["plans"]["free"].update(ai_per_day=900),
    "unknown task": lambda d: d["plans"]["free"].update(locked_tasks=["synthesise"]),
    "tasks not a list": lambda d: d["plans"]["free"].update(locked_tasks="synthesize"),
    "members_max zero": lambda d: d["plans"]["firm"].update(members_max=0),
    "members_max text": lambda d: d["plans"]["firm"].update(members_max="many"),
    "context tiny": lambda d: d["plans"]["free"].update(context_chars=5),
    "price negative": lambda d: d["plans"]["pro"]["price"].update(amount=-5),
    "price text": lambda d: d["plans"]["pro"]["price"].update(amount="free"),
    "price currency missing": lambda d: d["plans"]["pro"]["price"].pop("currency"),
    "label missing": lambda d: d["plans"]["pro"].pop("label"),
    "platform limit text": lambda d: d.update(free_platform_ai_per_day="all"),
}


@pytest.mark.parametrize("name", list(BAD))
def test_a_file_with_a_mistake_is_ignored_as_a_whole_and_the_limits_stay_in_force(plans_file, name):
    data = shipped()
    change = BAD[name]
    if callable(change):
        change(data)
    else:
        data = change
    plans_file(data)
    plan_config.load()
    assert plan_config.status()["problem"], name
    assert plan_config.status()["source"] == "built-in defaults"
    assert plan_config.plan("free")["ai_per_day"] == 5  # the free allowance is still in force; a typo cannot lift it
    assert plan_config.plan("free")["locked_tasks"] == ["synthesize", "analyze-contract"]
    assert plan_config.plan("firm")["members_max"] == 25


def test_a_missing_file_uses_the_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("PLANS_FILE", str(tmp_path / "nope.json"))
    assert plan_config.plan("free")["ai_per_day"] == 5 and "could not be found" in plan_config.status()["problem"]


def test_a_mistake_fixed_comes_back_into_force(plans_file):
    plans_file("{ broken")
    plan_config.load()
    assert plan_config.status()["problem"]
    data = shipped()
    data["plans"]["free"]["ai_per_day"] = 7
    plans_file(data)
    assert plan_config.plan("free")["ai_per_day"] == 7 and plan_config.status()["problem"] is None


def test_the_older_settings_still_win_over_the_file(plans_file, monkeypatch):
    plans_file(shipped())
    monkeypatch.setenv("FREE_AI_PER_DAY", "3")
    monkeypatch.setenv("PRO_AI_PER_DAY", "40")
    monkeypatch.setenv("FREE_CONTEXT_CHARS", "8000")
    monkeypatch.setenv("FREE_AI_PLATFORM_PER_DAY", "10")
    assert plan_config.plan("free")["ai_per_day"] == 3 and plan_config.plan("pro")["ai_per_day"] == 40
    assert plan_config.plan("free")["context_chars"] == 8000 and plan_config.free_platform_ai_per_day() == 10
    monkeypatch.setenv("FREE_AI_PER_DAY", "not a number")
    assert plan_config.plan("free")["ai_per_day"] == 5  # a setting that is not a number is ignored, not obeyed as zero or unlimited


def test_an_unknown_plan_name_gets_the_strictest_limits(plans_file):
    plans_file(shipped())
    assert plan_config.plan("platinum") == plan_config.plan("free") and plan_config.plan("") == plan_config.plan("free")


def test_no_code_outside_the_plan_files_holds_a_plan_number():
    root = Path(__file__).resolve().parent.parent
    names = ("FREE_AI_PER_DAY", "PRO_AI_PER_DAY", "FREE_CONTEXT_CHARS", "FREE_AI_PLATFORM_PER_DAY")
    holders = {p.name for p in list((root / "routers").glob("*.py")) + list((root / "lib").glob("*.py")) if any(n in p.read_text(encoding="utf-8") for n in names)}
    assert holders == {"plan_config.py", "admin_plans.py"}, holders  # the limits are read through lib/plan_config.py only


# ---- through the server ----

def ent(c):
    return c.get("/auth/entitlement").json()


def org_of(c):
    return c.get("/auth/me").json()["organization_id"]


def test_the_operator_sees_the_plans_and_puts_an_organisation_on_the_firm_plan_by_hand(admin, user_a):
    r = admin.get("/admin/plans")
    assert r.status_code == 200 and r.json()["file"]["problem"] is None and r.json()["plans"]["firm"]["members_max"] == 3
    assert r.json()["plans"]["firm"]["price"] is None  # no price is set: shown as such, nothing can be bought
    set_plan(user_a, "FREE")
    assert ent(user_a)["tier"] == "free"
    done = admin.post(f"/admin/organisations/{org_of(user_a)}/plan", json={"plan": "FIRM", "months": 12})
    assert done.status_code == 200 and done.json()["owners"] >= 1
    e = ent(user_a)
    assert e["plan"] == "FIRM" and e["tier"] == "firm" and e["pro_until"]
    assert e["limits"]["firm"]["ai_per_day"] == 2000 and e["limits"]["firm"]["price"] is None
    assert mongo().audit_events.count_documents({"operation": "ADMIN_ORG_PLAN_SET"}) >= 1
    assert admin.post(f"/admin/organisations/{org_of(user_a)}/plan", json={"plan": "FREE"}).status_code == 200
    assert ent(user_a)["tier"] == "free"
    assert admin.post("/admin/organisations/no-such-org/plan", json={"plan": "FIRM"}).status_code == 404
    assert admin.post(f"/admin/organisations/{org_of(user_a)}/plan", json={"plan": "GOLD"}).status_code == 422
    assert admin.post(f"/admin/organisations/{org_of(user_a)}/plan", json={"plan": "FIRM", "months": 0}).status_code == 422


def test_nobody_but_the_operator_can_read_or_change_plans(user_a, user_b, anon):
    for c in (user_a, anon):
        assert c.get("/admin/plans").status_code in (401, 403, 404)
        assert c.post(f"/admin/organisations/{org_of(user_a) if c is user_a else 'x'}/plan", json={"plan": "FIRM"}).status_code in (401, 403, 404)
    assert user_b.post(f"/admin/organisations/{org_of(user_a)}/plan", json={"plan": "FIRM"}).status_code in (403, 404)
    assert ent(user_a)["tier"] in ("pro", "free")  # nothing changed


def test_an_expired_firm_plan_is_free_again_and_a_member_inherits_the_firm_plan(admin, user_a):
    verify_email(user_a)
    member = new_member(user_a, "LAWYER")
    admin.post(f"/admin/organisations/{org_of(user_a)}/plan", json={"plan": "FIRM", "months": 1})
    assert ent(member)["tier"] == "firm"  # the subscription belongs to the organisation
    mongo().users.update_many({"organization_id": org_of(user_a), "role": "OWNER"}, {"$set": {"pro_until": time_ago(10)}})
    assert ent(member)["tier"] == "free" and ent(user_a)["tier"] == "free"  # past the paid period and the 2-day grace


def time_ago(days: float):
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) - timedelta(days=days)


def test_the_firm_plan_limits_the_number_of_people_including_invitations_not_yet_accepted(admin, user_a):
    verify_email(user_a)
    admin.post(f"/admin/organisations/{org_of(user_a)}/plan", json={"plan": "FIRM"})
    assert ent(user_a)["usage"]["members_limit"] == 3 and ent(user_a)["usage"]["members_used"] == 1
    new_member(user_a, "LAWYER")  # the 2nd person
    assert ent(user_a)["usage"]["members_used"] == 2
    ok = user_a.post("/org/invites", json={"email": f"third-{uuid.uuid4().hex[:6]}@example.com", "role": "MEMBER"})
    assert ok.status_code == 200  # the 3rd place is an open invitation
    assert ent(user_a)["usage"]["members_used"] == 3
    full = user_a.post("/org/invites", json={"email": f"fourth-{uuid.uuid4().hex[:6]}@example.com", "role": "MEMBER"})
    assert full.status_code == 402 and "allows 3 people" in full.json()["detail"]
    # a client of the portal is not one of the firm's people
    assert user_a.get("/org/invites").status_code == 200


def test_two_invitations_cannot_both_be_accepted_when_only_one_place_is_left(admin, user_a):
    from tests.conftest import outbox, token_from_mail
    import httpx
    from tests.conftest import API_URL

    verify_email(user_a)
    admin.post(f"/admin/organisations/{org_of(user_a)}/plan", json={"plan": "FIRM"})
    emails = [f"race-{i}-{uuid.uuid4().hex[:6]}@example.com" for i in range(2)]
    assert user_a.post("/org/invites", json={"email": emails[0], "role": "MEMBER"}).status_code == 200  # 2 of 3
    # the second invitation is written straight into the database, as if it had been sent while there was room
    mongo().invites.insert_one({"id": str(uuid.uuid4()), "organization_id": org_of(user_a), "organization_name": "x", "email": emails[1], "role": "MEMBER", "token_hash": __import__("hashlib").sha256(b"race-token").hexdigest(),
                                "invited_by": user_a.user["id"], "created_at": time_ago(0), "expires_at": time_ago(-1), "accepted_at": None})
    assert ent(user_a)["usage"]["members_used"] == 3
    mongo().users.insert_one({"id": str(uuid.uuid4()), "email": f"filler-{uuid.uuid4().hex[:6]}@example.com", "role": "MEMBER", "organization_id": org_of(user_a), "organization_name": "x", "plan": "FREE"})  # someone else took the place
    c = httpx.Client(base_url=API_URL, timeout=30.0)
    token = token_from_mail(outbox(to=emails[0], subject_has="invited")[-1], "token=")
    r = c.post("/auth/accept-invite", json={"token": token, "full_name": "Late Joiner", "password": f"Pw-{uuid.uuid4().hex}", "accept_privacy": True})
    assert r.status_code == 402 and "allows 3 people" in r.json()["detail"]
    assert mongo().invites.find_one({"email": emails[0]})["accepted_at"] is None  # the invitation can still be used once there is room
    assert mongo().users.count_documents({"email": emails[0]}) == 0


def test_a_plan_with_no_limit_on_people_still_invites_as_before(user_a):
    verify_email(user_a)
    set_plan(user_a, "FREE")
    for _ in range(3):
        new_member(user_a, "MEMBER")
    assert ent(user_a)["usage"]["members_limit"] is None and ent(user_a)["usage"]["members_used"] == 4


def test_usage_is_shown_for_every_plan_and_counts_what_was_used(user_a):
    set_plan(user_a, "FREE")
    stub("research", answer("A short answer."), contains="usage-shown")
    before = ent(user_a)["usage"]
    assert before["ai_limit_today"] == 5 and ent(user_a)["ai_limit_today"] == 5  # the older fields keep their meaning on the free plan
    assert user_a.post("/research", json={"question": "usage-shown please"}).status_code == 200
    assert ent(user_a)["usage"]["ai_used_today"] == before["ai_used_today"] + 1
    set_plan(user_a, "PRO")
    e = ent(user_a)
    assert e["ai_limit_today"] is None and e["usage"]["ai_limit_today"] == 500  # paid plans: the older field stays empty, the new block says 500
