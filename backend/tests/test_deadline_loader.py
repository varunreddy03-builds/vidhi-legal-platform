"""Loading holiday calendars and deadline rules from files: refused as a whole when anything is wrong, stored unreviewed with the file's source and date checked, used only after a named reviewer
and (for a calendar) a switch-on, reported as 'X of Y courts', and rolled back. Every court, holiday, rule and source here is INVENTED; the loader has no rules of its own."""
import json
from pathlib import Path
import uuid
from datetime import date, timedelta

import pytest

from tests.conftest import mongo
from tests.test_admin import admin  # noqa: F401  (the operator's session)

REVIEW = {"reviewed_by": "Adv Invented Reviewer", "on": "2026-10-20"}
BASE = "/admin/legal"


@pytest.fixture
def court():
    """A court VIDHI lists (one judgment row in the test database), removed afterwards."""
    tag = uuid.uuid4().hex[:8]
    name = f"Invented High Court of Testland {tag}"
    mongo().hc_judgments.insert_one({"id": f"loader-test-{tag}", "court_code": f"TL{tag}", "court_name": name, "_t": tag})
    yield name
    mongo().hc_judgments.delete_many({"_t": tag})
    for coll in ("deadline_calendars", "deadline_rules"):
        mongo()[coll].delete_many({"batch_id": {"$regex": ".*"}, "file_name": {"$regex": f"^{tag}"}})
    yield_tag.append(tag)


yield_tag: list = []


def calendar_file(court_name, year=2031, **over):
    d = {"kind": "court_calendar", "court": court_name, "year": year, "source_url": "https://example.invalid/official/holidays", "source_checked_on": "2026-11-01", "weekend_days": [5, 6],
         "holidays": [{"date": f"{year}-01-14", "name": "Invented Day"}, {"date": f"{year}-03-03", "name": "Invented Festival"}]}
    d.update(over)
    return d


def rules_file(court_name=None, year=2031, **over):
    rule = {"title": "Invented rule: two days", "starts_from": "the invented order date", "period": {"amount": 2, "unit": "days"}, "count_from": "day_after_start",
            "when_not_working": "move_to_next_working_day", "not_applied": ["Invented condition"]}
    if court_name:
        rule.update(calendar_court=court_name, calendar_year=year)
    d = {"kind": "deadline_rules", "source_url": "https://example.invalid/official/rules", "source_checked_on": "2026-11-01", "rules": [rule]}
    d.update(over)
    return d


def post(admin_c, path, data, name=None):
    raw = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
    return admin_c.post(path, files={"file": (name or f"{uuid.uuid4().hex[:8]}.json", raw, "application/json")})


def load(admin_c, data, name=None):
    return post(admin_c, f"{BASE}/deadline-data/load", data, name)


def coverage(admin_c) -> dict:
    r = admin_c.get(f"{BASE}/deadline-data/coverage")
    assert r.status_code == 200, r.text
    return r.json()


def test_a_preview_stores_nothing_and_a_load_stores_unreviewed_records_with_their_source(admin, court):
    before = mongo().deadline_calendars.count_documents({})
    pre = post(admin, f"{BASE}/deadline-data/preview", calendar_file(court))
    assert pre.status_code == 200 and pre.json()["ok"] and pre.json()["dry_run"] and pre.json()["created"][0]["holidays"] == 2
    assert mongo().deadline_calendars.count_documents({}) == before
    r = load(admin, calendar_file(court))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] and out["batch_id"] and out["warnings"] == [] and "UNREVIEWED" in out["note"]
    row = mongo().deadline_calendars.find_one({"id": out["created"][0]["id"]})
    assert row["review_status"] == "unreviewed" and row["enabled"] is False and row["court"] == court and row["year"] == 2031
    assert row["source_url"] == "https://example.invalid/official/holidays" and row["source_checked_on"] == "2026-11-01" and row["authorities"] == [row["source_url"]]
    assert row["batch_id"] == out["batch_id"] and len(row["file_sha256"]) == 64 and row["loaded_by"]
    assert mongo().audit_events.count_documents({"operation": "DEADLINE_DATA_LOADED"}) >= 1


def test_the_whole_path_load_review_switch_on_then_the_rule_can_be_used(admin, user_a, court):
    cal = load(admin, calendar_file(court)).json()["created"][0]["id"]
    rule_load = load(admin, rules_file(court))
    assert rule_load.status_code == 200, rule_load.text
    rule = rule_load.json()["created"][0]["id"]
    assert user_a.post("/deadline-rules/calculate", json={"rule_id": rule, "start": "2031-01-12"}).status_code == 404  # nothing is reviewed
    assert admin.post(f"{BASE}/deadline-calendars/{cal}/enable").status_code == 422  # cannot be switched on before it is reviewed
    assert admin.post(f"{BASE}/deadline-calendars/{cal}/review", json=REVIEW).status_code == 200
    assert admin.post(f"{BASE}/deadline-rules/{rule}/review", json=REVIEW).status_code == 200
    assert rule not in [x["id"] for x in user_a.get("/deadline-rules").json()["rules"]]  # reviewed, but the calendar is not switched on: not offered
    assert user_a.post("/deadline-rules/calculate", json={"rule_id": rule, "start": "2031-01-12"}).status_code == 404
    assert admin.post(f"{BASE}/deadline-calendars/{cal}/enable").status_code == 200
    got = user_a.post("/deadline-rules/calculate", json={"rule_id": rule, "start": "2031-01-12"})
    assert got.status_code == 200, got.text
    assert got.json()["due"] == "2031-01-15" and got.json()["moved"] is True and "Invented Day" in " ".join(got.json()["steps"])  # the 14th is a listed holiday
    assert rule in [x["id"] for x in user_a.get("/deadline-rules").json()["rules"]]
    assert admin.post(f"{BASE}/deadline-calendars/{cal}/disable").status_code == 200  # switching it off takes the rule out of use again
    assert user_a.post("/deadline-rules/calculate", json={"rule_id": rule, "start": "2031-01-12"}).status_code == 404


def test_reviewed_x_of_y_courts_counts_only_reviewed_and_switched_on_calendars(admin, court):
    start = coverage(admin)
    mine = next(c for c in start["courts"] if c["court"] == court)
    assert mine["live"] is False and start["courts_total"] >= 1
    cal = load(admin, calendar_file(court)).json()["created"][0]["id"]
    assert coverage(admin)["courts_live"] == start["courts_live"]  # loaded, not reviewed
    admin.post(f"{BASE}/deadline-calendars/{cal}/review", json=REVIEW)
    assert coverage(admin)["courts_live"] == start["courts_live"]  # reviewed, not switched on
    admin.post(f"{BASE}/deadline-calendars/{cal}/enable")
    now = coverage(admin)
    assert now["courts_live"] == start["courts_live"] + 1 and now["summary"] == f"Reviewed and switched on for {now['courts_live']} of {now['courts_total']} courts."
    row = next(c for c in now["courts"] if c["court"] == court)["calendars"][0]
    assert row["reviewed_by"] == "Adv Invented Reviewer" and row["verified_on"] == "2026-10-20" and row["enabled"] and row["source_checked_on"] == "2026-11-01" and row["source_url"].startswith("https://")


def test_a_court_vidhi_does_not_list_is_warned_about_and_does_not_count(admin):
    r = load(admin, calendar_file(f"Invented Unknown Tribunal {uuid.uuid4().hex[:6]}"))
    assert r.status_code == 200 and "not one of the courts VIDHI lists" in r.json()["warnings"][0]
    cov = coverage(admin)
    assert r.json()["created"][0]["id"] in [c["id"] for c in cov["unmatched_calendars"]]
    mongo().deadline_calendars.delete_one({"id": r.json()["created"][0]["id"]})


BAD = {
    "not json": b"{ nope",
    "not utf-8": b"\xff\xfe\x00bad",
    "a list": b"[]",
    "unknown kind": {"kind": "something"},
    "no source": lambda d: d.pop("source_url"),
    "source not https": lambda d: d.update(source_url="http://example.invalid/x"),
    "source with spaces": lambda d: d.update(source_url="https://example.invalid/a b"),
    "not checked on": lambda d: d.pop("source_checked_on"),
    "checked on a bad date": lambda d: d.update(source_checked_on="01/11/2026"),
    "checked in the future": lambda d: d.update(source_checked_on=(date.today() + timedelta(days=3)).isoformat()),
    "no court": lambda d: d.pop("court"),
    "year text": lambda d: d.update(year="2031"),
    "year out of range": lambda d: d.update(year=1999),
    "no holidays": lambda d: d.update(holidays=[]),
    "holiday date wrong": lambda d: d["holidays"].append({"date": "2031-02-30", "name": "Impossible"}),
    "holiday listed twice": lambda d: d["holidays"].append({"date": "2031-01-14", "name": "Again"}),
    "holiday without a name": lambda d: d["holidays"].append({"date": "2031-05-05", "name": ""}),
    "weekend missing": lambda d: d.pop("weekend_days"),
    "weekend out of range": lambda d: d.update(weekend_days=[7]),
}


@pytest.mark.parametrize("name", list(BAD))
def test_a_calendar_file_with_any_problem_is_refused_as_a_whole(admin, court, name):
    change = BAD[name]
    data = calendar_file(court)
    if callable(change):
        change(data)
    elif isinstance(change, dict):
        data = change
    else:
        data = change
    before = mongo().deadline_calendars.count_documents({})
    r = load(admin, data)
    assert r.status_code == 422 and r.json()["detail"], name
    assert mongo().deadline_calendars.count_documents({}) == before
    assert mongo().audit_events.count_documents({"operation": "DEADLINE_DATA_REFUSED"}) >= 1


def test_a_rules_file_with_one_bad_rule_stores_none_of_them(admin, court):
    good = rules_file(court)["rules"][0]
    bad = {**good, "title": "Invented bad rule", "count_from": None}
    data = rules_file(court)
    load(admin, calendar_file(court))
    data["rules"] = [good, {**good, "title": "Invented second rule"}, bad]
    before = mongo().deadline_rules.count_documents({})
    r = load(admin, data)
    assert r.status_code == 422
    assert mongo().deadline_rules.count_documents({}) == before  # the two good rules were not left behind


def test_a_rule_naming_a_calendar_that_is_not_loaded_is_refused_and_the_same_file_twice_is_refused(admin, court):
    r = load(admin, rules_file("Invented Court With No Calendar"))
    assert r.status_code == 422 and "none is loaded" in r.json()["detail"]
    data = calendar_file(court, year=2032)
    assert load(admin, data).status_code == 200
    again = load(admin, data)
    assert again.status_code == 422 and "already been loaded" in again.json()["detail"]


def test_a_file_over_one_megabyte_is_refused(admin):
    r = post(admin, f"{BASE}/deadline-data/load", b'{"kind": "court_calendar", "pad": "' + b"x" * 1_100_000 + b'"}')
    assert r.status_code == 413


def test_rolling_back_deletes_what_is_unreviewed_and_withdraws_what_was_reviewed(admin, user_a, court):
    first = load(admin, calendar_file(court, year=2033)).json()
    assert admin.post(f"{BASE}/deadline-data/batches/{first['batch_id']}/rollback", json={"reason": "short"}).status_code == 422  # a reason is needed
    out = admin.post(f"{BASE}/deadline-data/batches/{first['batch_id']}/rollback", json={"reason": "Loaded the wrong year by mistake."}).json()
    assert out == {"batch_id": first["batch_id"], "deleted": 1, "withdrawn": 0}
    assert mongo().deadline_calendars.count_documents({"batch_id": first["batch_id"]}) == 0

    cal_load = load(admin, calendar_file(court)).json()
    cal = cal_load["created"][0]["id"]
    rule_load = load(admin, rules_file(court)).json()
    rule = rule_load["created"][0]["id"]
    admin.post(f"{BASE}/deadline-calendars/{cal}/review", json=REVIEW)
    admin.post(f"{BASE}/deadline-rules/{rule}/review", json=REVIEW)
    admin.post(f"{BASE}/deadline-calendars/{cal}/enable")
    assert user_a.post("/deadline-rules/calculate", json={"rule_id": rule, "start": "2031-01-12"}).status_code == 200
    back = admin.post(f"{BASE}/deadline-data/batches/{cal_load['batch_id']}/rollback", json={"reason": "The court corrected its list."}).json()
    assert back["withdrawn"] == 1 and back["deleted"] == 0
    row = mongo().deadline_calendars.find_one({"id": cal})
    assert row["review_status"] == "unreviewed" and row["enabled"] is False and row["reviewed_by"] is None
    assert row["previously_reviewed"] == {"reviewed_by": "Adv Invented Reviewer", "verified_on": "2026-10-20"} and row["withdrawn"]["reason"] == "The court corrected its list."
    assert user_a.post("/deadline-rules/calculate", json={"rule_id": rule, "start": "2031-01-12"}).status_code == 404  # the rule has nothing reviewed to stand on
    assert coverage(admin)["courts_live"] == coverage(admin)["courts_live"]
    assert mongo().audit_events.count_documents({"operation": "DEADLINE_DATA_ROLLED_BACK"}) >= 2
    rl = admin.post(f"{BASE}/deadline-data/batches/{rule_load['batch_id']}/rollback", json={"reason": "Remove the rule as well."}).json()
    assert rl["withdrawn"] == 1


def test_only_the_operator_can_load_review_switch_on_or_roll_back(user_a, anon, court):
    raw = json.dumps(calendar_file(court)).encode()
    for c in (user_a, anon):
        assert c.post(f"{BASE}/deadline-data/load", files={"file": ("x.json", raw)}).status_code in (401, 403, 404)
        assert c.post(f"{BASE}/deadline-data/preview", files={"file": ("x.json", raw)}).status_code in (401, 403, 404)
        assert c.get(f"{BASE}/deadline-data/coverage").status_code in (401, 403, 404)
        assert c.post(f"{BASE}/deadline-calendars/x/enable").status_code in (401, 403, 404)
        assert c.post(f"{BASE}/deadline-data/batches/x/rollback", json={"reason": "a reason to roll back"}).status_code in (401, 403, 404, 422)


def test_the_loader_brings_no_rule_or_date_of_its_own(admin):
    cal_before = mongo().deadline_calendars.count_documents({})
    rules_before = mongo().deadline_rules.count_documents({})
    assert post(admin, f"{BASE}/deadline-data/preview", rules_file()).status_code == 200
    assert (mongo().deadline_calendars.count_documents({}), mongo().deadline_rules.count_documents({})) == (cal_before, rules_before)


def test_the_blank_templates_are_refused_if_loaded_by_mistake(admin):
    folder = Path(__file__).resolve().parent.parent.parent / "docs" / "deadline-data" / "templates"
    for name in ("court-calendar.template.json", "deadline-rules.template.json"):
        r = post(admin, f"{BASE}/deadline-data/load", (folder / name).read_bytes(), name)
        assert r.status_code == 422, name
        r = post(admin, f"{BASE}/deadline-data/preview", (folder / name).read_bytes(), name)
        assert r.json()["ok"] is False
