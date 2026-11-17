"""The operator's weekly view: AI cost by day, AI errors, wrong-result reports, library review progress and pilot accounts. Each block is tested on its own; none returns text anyone wrote.

The database is shared by every test, so each row added here carries a tag and is removed afterwards (an untidy row once broke the pilot-kit test)."""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from routers import admin_weekly as w
from tests.conftest import mongo
from tests.test_admin import admin  # noqa: F401  (the operator's session fixture)

IST = timezone(timedelta(hours=5, minutes=30))
TAG = "weekly-test-" + uuid.uuid4().hex
COLLECTIONS = ("ai_ledger", "answer_feedback", "pilot_feedback", "organizations", "users", "matters", "audit_events")


@pytest.fixture(autouse=True)
def _tidy():
    yield
    db = mongo()
    for coll in COLLECTIONS:
        db[coll].delete_many({"_t": TAG})


def put(coll, *docs):
    """Insert separate, tagged copies (insert_many adds an _id to each dict, so one dict repeated would collide)."""
    mongo()[coll].insert_many([{**d, "_t": TAG} for d in docs])


def _weekly(admin_client, days=14):
    r = admin_client.get(f"/admin/weekly?days={days}")
    assert r.status_code == 200, r.text
    return r.json()


def _today():
    return datetime.now(timezone.utc).astimezone(IST).strftime("%Y-%m-%d")


def test_only_the_operator_can_read_it(user_a, anon):
    assert anon.get("/admin/weekly").status_code in (401, 403)
    assert user_a.get("/admin/weekly").status_code in (403, 404)  # the console hides itself from everyone else, as every admin route does


def test_ai_cost_by_day_adds_up_today_and_lists_quiet_days(admin):
    prov = "prov-" + uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    before = next(r for r in _weekly(admin)["ai_cost_by_day"] if r["day"] == _today())
    put("ai_ledger",
        {"created_at": now, "provider": prov, "task": "research", "cost_inr": 1.5, "ok": True},
        {"created_at": now, "provider": prov, "task": "research", "cost_inr": 2.5, "ok": True},
        {"created_at": now, "provider": prov, "task": "research", "cost_inr": 0.0, "ok": False, "error": "TimeoutError"})
    data = _weekly(admin, days=3)["ai_cost_by_day"]
    assert len(data) == 3 and data[0]["day"] == _today()  # one row per day, newest first, even a day with no calls
    today = data[0]
    assert today["by_provider"][prov] == 4.0
    assert today["calls"] >= before["calls"] + 3 and today["failed"] >= before["failed"] + 1
    assert today["cost_inr"] >= before["cost_inr"] + 4.0 - 0.01


def test_ai_errors_name_provider_task_and_error_class_only(admin):
    err = "ErrClass" + uuid.uuid4().hex[:6]
    row = {"created_at": datetime.now(timezone.utc), "provider": "p-err", "task": "synthesize", "cost_inr": 0.0, "ok": False, "error": err}
    put("ai_ledger", row, row)
    block = _weekly(admin)["ai_errors_7d"]
    assert {"provider": "p-err", "task": "synthesize", "error": err, "count": 2} in block["top"]
    assert block["failed"] >= 2 and 0 <= block["failure_rate_pct"] <= 100
    assert "message" not in json.dumps(block).lower()


def test_wrong_result_reports_count_but_never_show_the_comment(admin):
    secret = "COMMENT-" + uuid.uuid4().hex
    kind = "kind-" + uuid.uuid4().hex[:6]
    org = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    before = _weekly(admin)["wrong_results_7d"]
    fb = {"user_id": str(uuid.uuid4()), "organization_id": org, "rating": "down", "comment": secret, "created_at": now}
    put("answer_feedback", {**fb, "research_id": str(uuid.uuid4())}, {**fb, "research_id": str(uuid.uuid4())})
    put("pilot_feedback", {"id": str(uuid.uuid4()), "kind": "wrong_result", "organization_id": org, "user_id": fb["user_id"], "report_id": str(uuid.uuid4()), "n": 1, "ref": "Section 999",
                           "ref_kind": kind, "tool_label": "x", "note": secret, "created_at": now})
    after = _weekly(admin)["wrong_results_7d"]
    assert after["answers_marked_down"] == before["answers_marked_down"] + 2 and after["results_marked_wrong"] == before["results_marked_wrong"] + 1
    assert {"kind": kind, "count": 1} in after["wrong_by_kind"]
    assert secret not in json.dumps(after) and "Section 999" not in json.dumps(after)


def test_library_review_progress_is_counted_from_the_sections(monkeypatch):
    counts = {("provisions", None): 200, ("provisions", "reviewed"): 50, ("provisions", "rejected"): 10, ("library_entries", None): 40, ("legal_source_candidates", None): 7}

    async def fake_count(collection, flt=None, **_):
        if flt and "review_status" in flt and isinstance(flt["review_status"], dict):
            return 12  # reviewed or rejected within the last 7 days
        return counts[(collection, (flt or {}).get("review_status"))]

    monkeypatch.setattr(w.vstore, "count", fake_count)
    out = asyncio.run(w.library_review(datetime.now(timezone.utc) - timedelta(days=7)))
    assert out == {"sections_total": 200, "reviewed": 50, "rejected": 10, "waiting": 140, "reviewed_percent": 25.0, "reviewed_or_rejected_last_7_days": 12, "library_entries_verified": 40, "candidates_waiting": 7}


def test_library_review_progress_never_divides_by_zero(monkeypatch):
    async def none(*a, **k):
        return 0

    monkeypatch.setattr(w.vstore, "count", none)
    out = asyncio.run(w.library_review(datetime.now(timezone.utc)))
    assert out["reviewed_percent"] == 0.0 and out["waiting"] == 0


def test_library_review_block_is_in_the_response(admin):
    block = _weekly(admin)["library_review"]
    assert all(isinstance(block[k], (int, float)) for k in ("sections_total", "reviewed", "rejected", "waiting", "reviewed_percent", "library_entries_verified", "candidates_waiting"))


def test_pilot_accounts_show_use_and_last_seen_but_nothing_from_the_matters(admin):
    oid, name = str(uuid.uuid4()), "Pilot Chambers " + uuid.uuid4().hex[:6]
    now = datetime.now(timezone.utc)
    put("organizations", {"id": oid, "name": name, "created_at": now, "pilot": True})
    put("users", {"id": str(uuid.uuid4()), "email": f"p-{uuid.uuid4().hex[:8]}@example.com", "organization_id": oid, "created_at": now})
    put("matters", *[{"id": str(uuid.uuid4()), "organization_id": oid, "title": "SECRET-TITLE-" + oid[:6], "created_at": now} for _ in range(2)])
    put("audit_events", {"id": str(uuid.uuid4()), "organization_id": oid, "operation": "LOGIN", "created_at": now})
    ai = {"created_at": now, "provider": "x", "task": "research", "organization_id": oid, "cost_inr": 3.25, "ok": True}
    put("ai_ledger", ai, ai)
    put("answer_feedback", {"research_id": str(uuid.uuid4()), "user_id": "u", "organization_id": oid, "rating": "down", "comment": "x", "created_at": now})
    rows = _weekly(admin)["pilot_accounts"]
    mine = next(r for r in rows if r["organisation"] == name)
    assert (mine["members"], mine["matters"], mine["ai_calls_7d"], mine["ai_cost_7d_inr"], mine["marked_down_7d"]) == (1, 2, 2, 6.5, 1)
    assert mine["last_seen"] is not None
    assert "SECRET-TITLE" not in json.dumps(rows)


def test_a_non_pilot_organisation_is_not_listed(admin):
    name = "Ordinary Chambers " + uuid.uuid4().hex[:6]
    put("organizations", {"id": str(uuid.uuid4()), "name": name, "created_at": datetime.now(timezone.utc)})
    assert all(r["organisation"] != name for r in _weekly(admin)["pilot_accounts"])
