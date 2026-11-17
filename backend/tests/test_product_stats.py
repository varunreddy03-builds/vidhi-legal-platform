"""Anonymous product numbers: counters per tool and day, no person and no text, visible only to the operator, trimmed by the retention job."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from pymongo import MongoClient

from lib import product_stats as ps
from tests.conftest import mongo
from tests.test_admin import admin  # noqa: F401  (the operator's session)

BACKEND = Path(__file__).resolve().parent.parent
ALLOWED_KEYS = {"_id", "day", "tool", "runs", "refused", "failed", "ms_total", "b_under_1s", "b_1_to_3s", "b_3_to_10s", "b_10s_or_more"}

ROUTES = [
    ("POST", "/api/authority/checks", "authority_check"), ("POST", "/api/authority/checks/file", "authority_check"), ("POST", "/api/datelists", "date_list"), ("POST", "/api/datelists/file", "date_list"),
    ("POST", "/api/defectchecks", "defect_check"), ("POST", "/api/defectchecks/file", "defect_check"), ("POST", "/api/oldcodechecks", "old_code_check"), ("POST", "/api/oldcodechecks/file", "old_code_check"),
    ("POST", "/api/deadline-rules/calculate", "deadline_engine"), ("POST", "/api/research", "research"), ("POST", "/api/templates/{template_id}/draft", "template_draft"),
    ("POST", "/api/drafts/{draft_id}/check", "draft_check"), ("POST", "/api/drafts/{draft_id}/send-for-review", "draft_review"), ("POST", "/api/matters/{matter_id}/documents", "document_upload"),
    # not tools: reading, signing in, the admin console itself, and the same address with another method
    ("GET", "/api/datelists", None), ("GET", "/api/authority/checks", None), ("POST", "/api/auth/login", None), ("GET", "/api/admin/product", None), ("DELETE", "/api/datelists/{id}", None),
    ("POST", "/api/authority/checks/{report_id}/items/{n}/review", None), ("POST", "/api/drafts", None), ("POST", "(unmatched)", None), ("POST", "", None),
]


@pytest.mark.parametrize("method,route,tool", ROUTES)
def test_only_the_tool_routes_are_counted_and_the_tool_comes_from_the_route_template(method, route, tool):
    assert ps.tool_for(method, route) == tool


def test_run_times_fall_into_four_buckets():
    assert [ps.bucket_of(ms) for ms in (0, 999, 1000, 2999, 3000, 9999, 10000, 60000)] == ["under_1s", "under_1s", "1_to_3s", "1_to_3s", "3_to_10s", "3_to_10s", "10s_or_more", "10s_or_more"]


def product(admin_client, days=1) -> dict:
    r = admin_client.get(f"/admin/product?days={days}")
    assert r.status_code == 200, r.text
    return {t["tool"]: t for t in r.json()["tools"]}


def test_a_run_a_refusal_and_a_failure_are_counted_apart(admin, user_a):
    before = product(admin)["date_list"]
    assert user_a.post("/datelists", json={"title": "x", "text": "Hearing on 12 March 2021."}).status_code == 200
    assert user_a.post("/datelists", json={"title": "x"}).status_code == 422  # refused: no text
    after = product(admin)["date_list"]
    assert after["runs"] == before["runs"] + 1 and after["refused"] == before["refused"] + 1 and after["failed"] == before["failed"]
    assert after["avg_ms"] is not None and sum(after["buckets"].values()) >= sum(before["buckets"].values()) + 2
    assert after["share_under_3s_pct"] is not None and after["failed_pct"] is not None


def test_nothing_about_a_person_or_a_text_is_kept(admin, user_a):
    marker = "PRIVATE-MARKER-" + uuid.uuid4().hex
    me = user_a.get("/auth/me").json()
    user_a.post("/datelists", json={"title": marker, "text": f"Hearing on 12 March 2021 in the matter of {marker}."})
    user_a.post("/defectchecks", json={"title": marker, "text": f"Paragraph 1. {marker}"})
    rows = list(mongo().product_stats.find({}))
    assert rows
    for row in rows:
        assert set(row) <= ALLOWED_KEYS, set(row) - ALLOWED_KEYS
        assert all(isinstance(v, int) for k, v in row.items() if k not in ("_id", "day", "tool"))
    blob = json.dumps(rows, default=str)
    for secret in (marker, me["id"], me["email"], me["organization_id"], me["full_name"]):
        assert secret not in blob
    assert len({(r["day"], r["tool"]) for r in rows}) == len(rows)  # one row per day and tool, never one per person


def test_only_the_operator_can_read_the_numbers(user_a, anon):
    assert anon.get("/admin/product").status_code in (401, 403)
    assert user_a.get("/admin/product").status_code in (403, 404)


def test_the_wrong_result_rate_exists_only_for_the_tool_that_has_a_report_button(admin):
    tools = product(admin)
    assert tools["authority_check"]["wrong_result_reports"] is not None
    assert all(tools[k]["wrong_result_reports"] is None and tools[k]["wrong_result_rate_pct"] is None for k in tools if k != "authority_check")
    assert set(tools) == {k for k, *_ in ps.TOOLS}


def test_a_report_of_a_wrong_result_raises_the_authority_check_count_without_storing_who(admin):
    from datetime import datetime, timezone

    before = product(admin, 1)["authority_check"]["wrong_result_reports"]
    tag = "stats-test-" + uuid.uuid4().hex
    mongo().pilot_feedback.insert_one({"id": tag, "kind": "wrong_result", "organization_id": "x", "created_at": datetime.now(timezone.utc), "_t": tag})
    try:
        assert product(admin, 1)["authority_check"]["wrong_result_reports"] == before + 1
    finally:
        mongo().pilot_feedback.delete_many({"_t": tag})


def test_old_rows_are_trimmed_by_the_retention_job_and_recent_ones_kept():
    name = f"vidhi_stats_{uuid.uuid4().hex[:8]}"
    client = MongoClient(os.environ["MONGO_URL"])
    try:
        client[name].product_stats.insert_many([{"day": "2020-01-01", "tool": "date_list", "runs": 3}, {"day": ps.day_of(), "tool": "date_list", "runs": 1}])
        code = "import asyncio, sys, json; sys.path.insert(0, sys.argv[1]); from lib import product_stats; print(json.dumps(asyncio.run(product_stats.trim())))"
        r = subprocess.run([sys.executable, "-I", "-c", code, str(BACKEND)], capture_output=True, text=True, env={**os.environ, "DB_NAME": name, "EMAIL_DRY_RUN": "true"}, cwd=str(BACKEND))
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout.strip().splitlines()[-1]) == 1
        assert [x["day"] for x in client[name].product_stats.find()] == [ps.day_of()]
    finally:
        client.drop_database(name)
        client.close()


def test_counting_can_never_break_a_request(monkeypatch):
    import asyncio

    class Broken:
        async def update_one(self, *a, **k):
            raise RuntimeError("database is down")

    monkeypatch.setattr(ps, "db", type("D", (), {"product_stats": Broken()})())
    asyncio.run(ps.record("POST", "/api/datelists", 200, 12))  # returns quietly
    asyncio.run(ps.record("GET", "/api/datelists", 200, 12))


def test_two_rows_for_one_day_and_tool_cannot_exist():
    """Two first requests of the day used to be able to create the same counter row twice; a unique index now stops it and record() retries."""
    from lib.db import INDEXES
    unique = [m.document for m in INDEXES["product_stats"] if m.document.get("unique")]
    assert unique and list(unique[0]["key"].keys()) == ["day", "tool"]
