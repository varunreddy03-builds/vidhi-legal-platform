"""Deadline engine: rules and calendars are entered by the operator and shown only after a named reviewer marks them reviewed. INVENTED rules only; the engine has no legal defaults."""

import os
from pathlib import Path

from lib.deadlinerules import store
from routers import deadlinerules as dr
from tests.test_admin import admin  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent.parent
REVIEW = {"reviewed_by": "Adv Invented Reviewer", "on": "2026-10-20"}


def rule_body(**over):
    body = {"title": "Invented rule: thirty days", "starts_from": "the invented order date", "period": {"amount": 30, "unit": "days"}, "count_from": "day_after_start",
            "when_not_working": "leave_as_is", "not_applied": ["Invented: time spent obtaining a copy"], "authorities": ["Invented source 1"]}
    body.update(over)
    return body


def make_rule(admin_c, **over):
    r = admin_c.post("/admin/legal/deadline-rules", json=rule_body(**over))
    assert r.status_code == 201, r.text
    return r.json()


def test_the_feature_is_off_by_default_and_documented_off():
    saved = os.environ.pop("DEADLINE_ENGINE_ENABLED", None)
    try:
        assert dr.enabled() is False
    finally:
        if saved is not None:
            os.environ["DEADLINE_ENGINE_ENABLED"] = saved
    assert "DEADLINE_ENGINE_ENABLED=false" in (ROOT / ".env.example").read_text(encoding="utf-8")
    assert (ROOT / "deploy" / "profiles" / "production.env").read_text(encoding="utf-8").count("DEADLINE_ENGINE_ENABLED=false") == 1


def test_with_no_reviewed_rule_nothing_can_be_calculated_and_it_says_so(user_a):
    r = user_a.get("/deadline-rules").json()
    assert r["rules"] == [] and r["message"] == store.NONE_LOADED
    assert user_a.post("/deadline-rules/calculate", json={"rule_id": "nothing", "start": "2030-01-10"}).status_code == 404


def test_an_unreviewed_rule_is_not_shown_or_usable_until_a_named_reviewer_marks_it_reviewed(admin, user_a):  # noqa: F811
    rule = make_rule(admin)
    assert rule["review_status"] == "unreviewed" and rule["reviewed_by"] is None
    assert rule["id"] not in [x["id"] for x in user_a.get("/deadline-rules").json()["rules"]]
    assert user_a.post("/deadline-rules/calculate", json={"rule_id": rule["id"], "start": "2030-01-10"}).status_code == 404
    assert admin.post(f"/admin/legal/deadline-rules/{rule['id']}/review", json={"reviewed_by": "Ad", "on": "2026-10-20"}).status_code == 422  # a full name is needed
    assert admin.post(f"/admin/legal/deadline-rules/{rule['id']}/review", json={"reviewed_by": "Adv Invented Reviewer", "on": "20/10/2026"}).status_code == 422
    assert admin.post(f"/admin/legal/deadline-rules/{rule['id']}/review", json=REVIEW).status_code == 200
    shown = user_a.get("/deadline-rules").json()["rules"]
    assert rule["id"] in [x["id"] for x in shown] and "recorded_by" not in shown[0]
    got = user_a.post("/deadline-rules/calculate", json={"rule_id": rule["id"], "start": "2030-01-10"})
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["due"] == "2030-02-09" and body["rule"]["reviewed_by"] == "Adv Invented Reviewer" and body["rule"]["authorities"] == ["Invented source 1"]
    assert body["rule"]["not_applied"] == ["Invented: time spent obtaining a copy"] and body["steps"][-1].startswith("Due date: 2030-02-09")
    assert "has not checked that the rule applies to your matter" in body["notice"]


def test_a_rule_cannot_be_reviewed_without_a_source_and_cannot_leave_a_choice_out(admin):  # noqa: F811
    bare = make_rule(admin, authorities=[])
    r = admin.post(f"/admin/legal/deadline-rules/{bare['id']}/review", json=REVIEW)
    assert r.status_code == 422 and "official source" in r.json()["detail"]
    for over in ({"count_from": None}, {"when_not_working": None}, {"period": {"amount": 1, "unit": "months"}}, {"period": {"amount": 0, "unit": "days"}}, {"title": "x"}):
        assert admin.post("/admin/legal/deadline-rules", json=rule_body(**over)).status_code == 422, over
    assert admin.post("/admin/legal/deadline-rules", json=rule_body(when_not_working="move_to_next_working_day")).status_code == 422  # a moving rule must name its calendar
    assert admin.post("/admin/legal/deadline-rules", json=rule_body(when_not_working="move_to_next_working_day", calendar_id="nope")).status_code == 422


def test_a_rule_that_moves_dates_needs_a_reviewed_calendar_and_the_move_is_shown_step_by_step(admin, user_a):  # noqa: F811
    cal = admin.post("/admin/legal/deadline-calendars", json={"title": "Invented calendar", "weekend_days": [5, 6], "holidays": [{"date": "2030-01-14", "name": "Invented Day"}], "authorities": []})
    assert cal.status_code == 201, cal.text
    cal_id = cal.json()["id"]
    rule = make_rule(admin, period={"amount": 2, "unit": "days"}, when_not_working="move_to_next_working_day", calendar_id=cal_id)
    r = admin.post(f"/admin/legal/deadline-rules/{rule['id']}/review", json=REVIEW)
    assert r.status_code == 422 and "calendar must be reviewed" in r.json()["detail"]
    assert admin.post(f"/admin/legal/deadline-calendars/{cal_id}/review", json=REVIEW).status_code == 422  # a calendar with no source cannot be reviewed either
    cal2 = admin.post("/admin/legal/deadline-calendars", json={"title": "Invented calendar two", "weekend_days": [5, 6], "holidays": [{"date": "2030-01-14", "name": "Invented Day"}], "authorities": ["Invented notice 9"]}).json()
    rule2 = make_rule(admin, period={"amount": 2, "unit": "days"}, when_not_working="move_to_next_working_day", calendar_id=cal2["id"])
    assert admin.post(f"/admin/legal/deadline-calendars/{cal2['id']}/review", json=REVIEW).status_code == 200
    assert admin.post(f"/admin/legal/deadline-rules/{rule2['id']}/review", json=REVIEW).status_code == 200
    got = user_a.post("/deadline-rules/calculate", json={"rule_id": rule2["id"], "start": "2030-01-10"}).json()
    assert got["due"] == "2030-01-15" and got["moved"] is True and got["calendar"]["reviewed_by"] == "Adv Invented Reviewer"
    assert "Invented Day" in " ".join(got["steps"]) and "as the rule says" in " ".join(got["steps"])


def test_bad_dates_are_refused_plainly_and_a_calendar_must_be_well_formed(admin, user_a):  # noqa: F811
    rule = make_rule(admin)
    admin.post(f"/admin/legal/deadline-rules/{rule['id']}/review", json=REVIEW)
    for start in ("2030-02-30", "10/01/2030", "", "1800-01-01"):
        r = user_a.post("/deadline-rules/calculate", json={"rule_id": rule["id"], "start": start})
        assert r.status_code in (422,) and "start date" in r.json()["detail"], start
    bad = [{"title": "Invented", "weekend_days": [7]}, {"title": "Invented", "weekend_days": [1, 1]}, {"title": "Invented", "holidays": [{"date": "2030-13-01", "name": "x"}]},
           {"title": "Invented", "holidays": [{"date": "2030-01-01", "name": "x"}, {"date": "2030-01-01", "name": "y"}]}, {"title": "Invented", "holidays": [{"date": "2030-01-01"}]}]
    for body in bad:
        assert admin.post("/admin/legal/deadline-calendars", json=body).status_code == 422, body


def test_only_the_platform_admin_can_enter_or_review_and_nothing_is_stored_from_a_calculation(admin, user_a):  # noqa: F811
    assert user_a.post("/admin/legal/deadline-rules", json=rule_body()).status_code in (401, 403, 404)
    assert user_a.get("/admin/legal/deadline-rules").status_code in (401, 403, 404)
    assert user_a.post("/admin/legal/deadline-calendars", json={"title": "Invented"}).status_code in (401, 403, 404)
    rule = make_rule(admin)
    assert user_a.post(f"/admin/legal/deadline-rules/{rule['id']}/review", json=REVIEW).status_code in (401, 403, 404)
    assert [x for x in admin.get("/admin/legal/deadline-rules").json() if x["id"] == rule["id"]][0]["review_status"] == "unreviewed"


def test_no_ai_no_outside_call_and_no_law_in_the_code():
    source = "".join((ROOT / "backend" / p).read_text(encoding="utf-8") for p in ("routers/deadlinerules.py", "lib/deadlinerules/store.py", "lib/deadlinerules/compute.py"))
    assert "lib.ai" not in source and "ask_json" not in source and "import httpx" not in source
    for word in ("limitation act", "civil procedure", "high court", "supreme court"):
        assert word not in source.lower(), word
