"""Saved dates: time zones, calendar files, reminders (email, browser notification, opt-in text) and the people who may see them."""

import os
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from lib import deadlines as dl
from lib import webpush
from tests.conftest import API_URL, mongo, new_matter, outbox
from tests.test_twilio import verify_phone

CRON = {"Authorization": f"Bearer {os.environ.get('WEBHOOK_CRON_SECRET', 'test-cron-secret-not-real')}"}
UTC = timezone.utc
FCM = "https://fcm.googleapis.com/fcm/send/abc123-test-device-endpoint"
KEYS = {"p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM", "auth": "tBHItJI5svbpez7KI4CCXg"}


def soon(minutes: int = 180, tz: str = "Asia/Kolkata") -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes)).astimezone(dl.zone(tz)).strftime("%Y-%m-%dT%H:%M")


def add(c, title="Hearing in the district court", **extra):
    body = {"title": title, "kind": "hearing", "starts_local": soon(), "tz": "Asia/Kolkata", **extra}
    return c.post("/deadlines", json=body)


def run_job() -> None:
    db = mongo()
    before = (db.job_runs.find_one({"_id": "deadline-reminders"}) or {}).get("last_ok_at")
    for _ in range(40):
        r = httpx.post(f"{API_URL}/cron/deadline-reminders", headers=CRON, timeout=30)
        assert r.status_code == 200, r.text
        if r.json()["status"] == "accepted":
            break
        time.sleep(0.25)
    for _ in range(80):
        row = db.job_runs.find_one({"_id": "deadline-reminders"}) or {}
        if row.get("last_ok_at") and row.get("last_ok_at") != before:
            return
        assert not row.get("last_error"), row.get("last_error")
        time.sleep(0.25)
    raise AssertionError("the reminder job did not finish")


def make_due(deadline_id: str, minutes_ahead: int = 50) -> None:
    """Pretend time has passed: move the date close and forget what was sent."""
    mongo().deadlines.update_one({"id": deadline_id}, {"$set": {"starts_at": datetime.now(UTC) + timedelta(minutes=minutes_ahead), "sent": {}}})


# ---- time zones ----

def test_local_times_become_utc_and_come_back_in_the_same_zone():
    assert dl.to_utc("2026-11-05T10:30", "Asia/Kolkata") == datetime(2026, 11, 5, 5, 0, tzinfo=UTC)
    assert dl.local_text(datetime(2026, 11, 5, 5, 0, tzinfo=UTC), "Asia/Kolkata") == "2026-11-05T10:30"
    assert dl.to_utc("2026-07-01T09:00", "Europe/London") == datetime(2026, 7, 1, 8, 0, tzinfo=UTC)  # summer time
    assert dl.to_utc("2026-12-01T09:00", "Europe/London") == datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
    assert dl.to_utc("2026-11-05T10:30+05:30", "Europe/London") == datetime(2026, 11, 5, 5, 0, tzinfo=UTC)  # an explicit offset is honoured


def test_a_time_the_clocks_skip_is_refused_and_a_repeated_time_means_the_first_one():
    with pytest.raises(ValueError, match="does not exist"):
        dl.to_utc("2026-03-29T01:30", "Europe/London")  # clocks go 01:00 -> 02:00
    assert dl.to_utc("2026-10-25T01:30", "Europe/London") == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)  # happens twice; the first (summer time)


@pytest.mark.parametrize("bad_tz", ["Mars/Base", "", "../etc/passwd", "IST"])
def test_unknown_time_zones_and_dates_are_refused(bad_tz):
    with pytest.raises(ValueError):
        dl.to_utc("2026-11-05T10:30", bad_tz)
    with pytest.raises(ValueError):
        dl.to_utc("next Tuesday", "Asia/Kolkata")


# ---- reminder planning ----

def test_reminders_that_are_already_past_are_skipped_not_fired():
    starts = datetime(2026, 11, 5, 5, 0, tzinfo=UTC)
    now = starts - timedelta(hours=5)
    assert dl.initial_sent(starts, [1440, 60], now) == {"1440": "skipped"}
    d = {"status": "OPEN", "starts_at": starts, "reminders": [1440, 60], "sent": {"1440": "skipped"}}
    assert dl.due_offsets(d, now) == []
    assert dl.due_offsets(d, starts - timedelta(minutes=59)) == [60]
    assert dl.due_offsets({**d, "sent": {"1440": "skipped", "60": now}}, starts - timedelta(minutes=30)) == []  # never twice
    assert dl.due_offsets(d, starts + timedelta(minutes=1)) == []  # the date has passed
    assert dl.due_offsets({**d, "status": "DONE"}, starts - timedelta(minutes=30)) == []
    with pytest.raises(ValueError):
        dl.clean_offsets([7])


# ---- calendar file ----

def test_the_calendar_file_is_valid_escaped_and_folded():
    title = "Hearing; Smith, J. \\ आदेश / విచారణ " + "x" * 90
    d = {"id": "abc", "title": title, "kind": "hearing", "notes": "line one\nline two", "starts_at": datetime(2026, 11, 5, 5, 0, tzinfo=UTC), "tz": "Asia/Kolkata", "reminders": [1440, 60]}
    raw = dl.ics([d], datetime(2026, 10, 1, tzinfo=UTC))
    text = raw.decode("utf-8")
    assert text.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert all(len(line.encode("utf-8")) <= 75 for line in text.split("\r\n"))
    unfolded = text.replace("\r\n ", "")
    assert "DTSTART:20261105T050000Z" in unfolded and "DTEND:20261105T060000Z" in unfolded and "UID:abc@vidhi" in unfolded
    assert "SUMMARY:Hearing\\; Smith\\, J. \\\\ आदेश / విచారణ " in unfolded
    assert "TRIGGER:-PT1440M" in unfolded and "TRIGGER:-PT60M" in unfolded
    assert "Local time: 05 Nov 2026\\, 10:30 (Asia/Kolkata)" in unfolded and "line one\\nline two" in unfolded
    assert "does not check it against any court record" in unfolded
    assert text.count("BEGIN:VEVENT") == text.count("END:VEVENT") == 1


# ---- the API ----

def test_dates_can_be_added_listed_changed_finished_and_deleted(user_a):
    when = soon(180)
    r = add(user_a, notes="Bring the originals", reminders=[1440, 60, 15], starts_local=when)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["starts_local"] == when and d["tz"] == "Asia/Kolkata"  # shown back exactly as it was typed, in the same zone
    assert d["reminders"] == [1440, 60, 15] and d["status"] == "OPEN" and d["entered_by_a_person"] is True
    listed = user_a.get("/deadlines").json()
    assert [x["id"] for x in listed["items"]] == [d["id"]] and "does not check it against any court record" in listed["notice"]
    p = user_a.patch(f"/deadlines/{d['id']}", json={"title": "Changed", "starts_local": soon(300, "Europe/London"), "tz": "Europe/London", "reminders": [60]})
    assert p.status_code == 200, p.text
    assert p.json()["title"] == "Changed" and p.json()["tz"] == "Europe/London" and p.json()["reminders"] == [60]
    assert user_a.patch(f"/deadlines/{d['id']}", json={"status": "DONE"}).json()["status"] == "DONE"
    assert user_a.delete(f"/deadlines/{d['id']}").status_code == 204
    assert user_a.get("/deadlines").json()["items"] == []
    ops = [e["operation"] for e in mongo().audit_events.find({"detail": d["id"]})]
    assert {"DEADLINE_ADDED", "DEADLINE_CHANGED", "DEADLINE_DELETED"} <= set(ops)


def test_bad_input_is_refused_with_plain_messages(user_a):
    assert add(user_a, starts_local="2020-01-01T10:00").status_code == 422  # in the past
    assert add(user_a, tz="Mars/Base").status_code == 422
    assert add(user_a, kind="holiday").status_code == 422
    assert add(user_a, reminders=[7]).status_code == 422
    assert add(user_a, starts_local="tomorrow").status_code == 422
    assert add(user_a, title="").status_code == 422
    assert add(user_a, matter_id="not-a-matter").status_code == 404
    assert add(user_a, starts_local="2027-03-28T01:30", tz="Europe/London").status_code == 422  # a skipped hour


def test_a_date_can_belong_to_a_matter_of_the_same_organisation_only(user_a, user_b):
    mid, _ = new_matter(user_a)
    d = add(user_a, matter_id=mid).json()
    assert d["matter_id"] == mid and d["matter_title"]
    assert add(user_b, matter_id=mid).status_code == 404


def test_other_organisations_cannot_see_change_or_export_a_date(user_a, user_b):
    d = add(user_a).json()
    assert user_b.get("/deadlines").json()["items"] == []
    assert user_b.patch(f"/deadlines/{d['id']}", json={"title": "x"}).status_code == 404
    assert user_b.delete(f"/deadlines/{d['id']}").status_code == 404
    assert user_b.get(f"/deadlines/{d['id']}/calendar.ics").status_code == 404
    assert "VEVENT" not in user_b.get("/deadlines/calendar.ics").text
    assert user_a.get("/deadlines").json()["items"][0]["title"] == "Hearing in the district court"


def test_calendar_files_download_for_one_date_and_for_all(user_a, anon):
    d = add(user_a, title="Filing day", reminders=[60]).json()
    one = user_a.get(f"/deadlines/{d['id']}/calendar.ics")
    assert one.status_code == 200 and one.headers["content-type"].startswith("text/calendar") and "attachment" in one.headers["content-disposition"]
    assert "SUMMARY:Filing day" in one.text and "TRIGGER:-PT60M" in one.text
    assert "SUMMARY:Filing day" in user_a.get("/deadlines/calendar.ics").text
    user_a.patch(f"/deadlines/{d['id']}", json={"status": "DONE"})
    assert "VEVENT" not in user_a.get("/deadlines/calendar.ics").text  # finished dates are left out of the feed
    assert anon.get(f"/deadlines/{d['id']}/calendar.ics").status_code == 401


# ---- reminders ----

def test_the_reminder_job_needs_the_secret(anon):
    assert anon.post("/cron/deadline-reminders").status_code == 401
    assert anon.post("/cron/deadline-reminders", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_a_due_reminder_is_emailed_once_with_the_title_and_the_not_checked_notice(user_a):
    d = add(user_a, title="Rejoinder due", reminders=[60], channels={"email": True, "push": False, "sms": False}).json()
    make_due(d["id"])
    run_job()
    run_job()  # a second run (or a retried trigger) must not send it again
    mails = outbox(to=user_a.user["email"], subject_has="Reminder: Rejoinder due")
    assert len(mails) == 1
    assert "in one hour" in mails[0]["html"] and "does not check it against any court record" in mails[0]["html"]
    row = mongo().deadlines.find_one({"id": d["id"]})
    assert "60" in row["sent"] and row["sent_via"]["60"] == {"email": True}
    assert [m for m in user_a.get("/deadlines").json()["items"]][0]["reminders_sent"] == [60]


def test_a_finished_or_far_off_date_sends_nothing(user_a):
    done = add(user_a, title="Already done", reminders=[60]).json()
    far = add(user_a, title="Far away", reminders=[60], starts_local=soon(60 * 24 * 20)).json()
    make_due(done["id"])
    user_a.patch(f"/deadlines/{done['id']}", json={"status": "DONE"})
    run_job()
    assert not outbox(to=user_a.user["email"], subject_has="Already done") and not outbox(to=user_a.user["email"], subject_has="Far away")
    assert mongo().deadlines.find_one({"id": far["id"]})["sent"] == {}


def test_phone_and_browser_messages_are_generic_and_text_needs_a_verified_phone_with_alerts(user_a):
    mongo().users.update_one({"id": user_a.user["id"]}, {"$set": {"email_verified": True}})
    sub = user_a.post("/push/subscribe", json={"endpoint": FCM, "keys": KEYS})
    assert sub.status_code == 200, sub.text
    d = add(user_a, title="Secret client name v State", reminders=[60], channels={"email": False, "push": True, "sms": True}).json()
    make_due(d["id"])
    run_job()
    via = mongo().deadlines.find_one({"id": d["id"]})["sent_via"]["60"]
    assert via["push"] is True and via["sms"] is False  # no verified phone yet: no text
    num = verify_phone(user_a)
    mongo().users.update_one({"id": user_a.user["id"]}, {"$set": {"phone.alerts": True}})
    make_due(d["id"])
    run_job()
    via = mongo().deadlines.find_one({"id": d["id"]})["sent_via"]["60"]
    assert via["sms"] is True
    texts = [r["body"] for r in mongo().sms_outbox.find({"to": num})] + [str(p["payload"]) for p in mongo().push_outbox.find({"user_id": user_a.user["id"]})]
    assert any("A date you saved in VIDHI is coming up in one hour" in t for t in texts)
    assert not any("Secret client" in t for t in texts)  # titles never leave in a text or a push


# ---- browser notification devices ----

def test_only_real_push_services_are_accepted_as_a_device_address(user_a):
    cfg = user_a.get("/push/config").json()
    assert cfg["available"] is True and cfg["public_key"] == webpush.STUB_KEY and cfg["devices"] == 0
    for bad in ("http://fcm.googleapis.com/x/aaaaaaaaaaaaaaaaaaaa", "https://evil.example.com/push/aaaaaaaaaaaaaaaa", "https://fcm.googleapis.com.evil.com/x/aaaaaaaa",
                "https://user:pw@fcm.googleapis.com/send/aaaaaaaaaaaa", "https://fcm.googleapis.com:8443/send/aaaaaaaaaaaa", "https://127.0.0.1/send/aaaaaaaaaaaaaaaaaaaa"):
        assert user_a.post("/push/subscribe", json={"endpoint": bad, "keys": KEYS}).status_code == 422, bad
    for good in (FCM, "https://updates.push.services.mozilla.com/wpush/v2/aaaaaaaaaa", "https://web.push.apple.com/aaaaaaaaaaaaaaaa", "https://wns2-par02p.notify.windows.com/w/?token=aaaaaaaa"):
        assert user_a.post("/push/subscribe", json={"endpoint": good, "keys": KEYS}).status_code == 200, good


def test_devices_are_limited_unsubscribed_and_private(user_a, user_b):
    for i in range(webpush.MAX_PER_USER):
        assert user_a.post("/push/subscribe", json={"endpoint": f"{FCM}{i}", "keys": KEYS}).status_code == 200
    assert user_a.post("/push/subscribe", json={"endpoint": f"{FCM}extra", "keys": KEYS}).status_code == 409
    assert user_a.post("/push/subscribe", json={"endpoint": f"{FCM}0", "keys": KEYS}).status_code == 200  # the same device again is fine
    assert user_b.post("/push/unsubscribe", json={"endpoint": f"{FCM}0"}).json() == {"subscribed": False}
    assert user_a.get("/push/config").json()["devices"] == webpush.MAX_PER_USER  # someone else's unsubscribe changed nothing
    assert user_a.post("/push/unsubscribe", json={"endpoint": f"{FCM}0"}).status_code == 200
    assert user_a.get("/push/config").json()["devices"] == webpush.MAX_PER_USER - 1
    sent = user_a.post("/push/test").json()
    assert sent["delivered"] == webpush.MAX_PER_USER - 1
    assert user_b.get("/push/config").json()["devices"] == 0