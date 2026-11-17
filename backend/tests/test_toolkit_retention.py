"""Toolkit reports hold sentences from a client's draft and are not tied to a matter, so they expire on their own: 30 days by default, then the retention sweep deletes them."""

from datetime import datetime, timedelta, timezone

import pytest

from lib import retention
from tests.conftest import mongo
from tests.test_lifecycle import run_retention

TEXT = "The accused is charged under Section 420 IPC. The hearing was on 5th April 2021. The the draft is not final."
MADE = [("authority_reports", "/authority/checks"), ("date_lists", "/datelists"), ("defect_checks", "/defectchecks"), ("old_code_checks", "/oldcodechecks")]


def make_all(c):
    out = {}
    for coll, path in MADE:
        r = c.post(path, json={"title": f"Retention {coll}", "text": TEXT})
        assert r.status_code == 200, (path, r.text)
        out[coll] = r.json()["id"]
    return out


def ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


@pytest.mark.parametrize("value,expected", [(None, 30), ("30", 30), ("7", 7), ("3650", 3650), ("0", 30), ("-5", 30), ("99999", 30), ("abc", 30), ("", 30)])
def test_the_number_of_days_is_30_unless_a_sensible_other_number_is_set(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("TOOLKIT_REPORT_DAYS", raising=False)
    else:
        monkeypatch.setenv("TOOLKIT_REPORT_DAYS", value)
    assert retention.toolkit_report_days() == expected


def test_every_new_report_records_when_it_will_be_deleted(user_a):
    ids = make_all(user_a)
    for coll, path in MADE:
        got = user_a.get(f"{path}/{ids[coll]}").json()
        gap = datetime.fromisoformat(got["expires_at"]) - datetime.fromisoformat(got["created_at"])
        assert timedelta(days=29, hours=23) < gap < timedelta(days=30, hours=1), coll


def test_the_sweep_deletes_expired_reports_and_keeps_the_rest(user_a, user_b):
    db = mongo()
    gone, kept, legacy_old, legacy_new, other_org = make_all(user_a), make_all(user_a), make_all(user_a), make_all(user_a), make_all(user_b)
    for coll, _ in MADE:
        db[coll].update_one({"id": gone[coll]}, {"$set": {"expires_at": ago(1)}})  # expired yesterday
        db[coll].update_one({"id": other_org[coll]}, {"$set": {"expires_at": ago(1)}})  # expiry does not depend on whose report it is
        db[coll].update_one({"id": legacy_old[coll]}, {"$unset": {"expires_at": ""}, "$set": {"created_at": ago(40)}})  # made before expiry dates existed, 40 days ago
        db[coll].update_one({"id": legacy_new[coll]}, {"$unset": {"expires_at": ""}, "$set": {"created_at": ago(5)}})  # made before expiry dates existed, 5 days ago
    run_retention()
    for coll, path in MADE:
        assert user_a.get(f"{path}/{gone[coll]}").status_code == 404, coll
        assert user_a.get(f"{path}/{legacy_old[coll]}").status_code == 404, coll
        assert user_b.get(f"{path}/{other_org[coll]}").status_code == 404, coll
        assert user_a.get(f"{path}/{kept[coll]}").status_code == 200, coll  # not yet expired
        assert user_a.get(f"{path}/{legacy_new[coll]}").status_code == 200, coll
