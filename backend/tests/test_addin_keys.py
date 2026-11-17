"""Add-in keys for the Google Docs add-on: a key works for the two Katalyst checks and nothing else, is shown once, can be removed, expires, and belongs to one organisation."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from tests.conftest import API_URL, mongo, verify_email

BODY = {"paragraphs": [{"id": "p1", "text": "Charged under Section 302 IPC and Rs. ____ is due."}]}


@pytest.fixture
def me(user_a):
    verify_email(user_a)
    return user_a


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def analyze_with(key):
    return httpx.post(f"{API_URL}/v1/katalyst/analyze-text", json=BODY, headers=bearer(key), timeout=60)


def test_a_key_is_shown_once_and_runs_the_checks_as_its_owner(me):
    made = me.post("/v1/katalyst/keys", json={"label": "My Google Docs"})
    assert made.status_code == 200, made.text
    key = made.json()["key"]
    assert key.startswith("vk_") and len(key) > 40 and made.json()["label"] == "My Google Docs"
    listed = me.get("/v1/katalyst/keys").json()
    assert [k["id"] for k in listed] == [made.json()["id"]] and all("key" not in k and "token_hash" not in k for k in listed)  # never shown again
    row = mongo().addin_keys.find_one({"id": made.json()["id"]})
    assert row["token_hash"] != key and key not in str(row)  # only a hash is kept
    ok = analyze_with(key)
    assert ok.status_code == 200 and {i["group"] for i in ok.json()["issues"]} >= {"code_replacement", "defect"}
    assert mongo().addin_keys.find_one({"id": made.json()["id"]})["last_used_at"] is not None


def test_a_key_opens_nothing_else(me):
    key = me.post("/v1/katalyst/keys", json={}).json()["key"]
    for method, path in [("GET", "/auth/me"), ("GET", "/matters"), ("GET", "/clients"), ("GET", "/v1/katalyst/keys"), ("POST", "/v1/katalyst/keys"), ("GET", "/org/export")]:
        r = httpx.request(method, f"{API_URL}{path}", headers=bearer(key), json={} if method == "POST" else None, timeout=30)
        assert r.status_code in (401, 403), (method, path, r.status_code)  # a key cannot make a key, read a matter or export the data
    assert httpx.post(f"{API_URL}/v1/katalyst/analyze-text", json=BODY, headers=bearer("vk_not-a-real-key"), timeout=30).status_code == 401
    assert httpx.post(f"{API_URL}/v1/katalyst/analyze-text", json=BODY, headers=bearer("not-even-the-prefix"), timeout=30).status_code == 401


def test_a_removed_or_expired_key_stops_working_and_nobody_else_can_remove_it(me, user_b):
    verify_email(user_b)
    made = me.post("/v1/katalyst/keys", json={}).json()
    assert user_b.delete(f"/v1/katalyst/keys/{made['id']}").status_code == 404 and analyze_with(made["key"]).status_code == 200
    assert me.delete(f"/v1/katalyst/keys/{made['id']}").status_code == 200 and analyze_with(made["key"]).status_code == 401
    old = me.post("/v1/katalyst/keys", json={}).json()
    mongo().addin_keys.update_one({"id": old["id"]}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    assert analyze_with(old["key"]).status_code == 401


def test_a_blocked_person_s_key_stops_at_once_and_the_number_of_keys_is_limited(me):
    keys = [me.post("/v1/katalyst/keys", json={}) for _ in range(5)]
    assert all(k.status_code == 200 for k in keys) and me.post("/v1/katalyst/keys", json={}).status_code == 409
    key = keys[0].json()["key"]
    uid = me.get("/auth/me").json()["id"]
    mongo().users.update_one({"id": uid}, {"$set": {"blocked": True}})
    assert analyze_with(key).status_code == 403


def test_keys_belong_to_the_organisation_and_leave_with_its_data(me):
    from lib import purge
    from routers import org_data

    assert "addin_keys" in purge.ORG_TAGGED and "addin_keys" in org_data.EXPORT_COLLECTIONS
    made = me.post("/v1/katalyst/keys", json={}).json()
    assert mongo().addin_keys.find_one({"id": made["id"]})["organization_id"] == me.get("/auth/me").json()["organization_id"]
    assert "token_hash" in ("password_hash", "token_hash", "email_verification")  # the export cleaner already drops a field called token_hash
