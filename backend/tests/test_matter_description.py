"""The matter description: every path the friend's phone test could have taken. Create, edit later, long text, Telugu, special characters, list vs detail."""

import uuid

import pytest

TELUGU = "ఇది ఒక వివరణ — రూ. 5,00,000 బకాయి; “కోట్స్” & <b>tags</b> 'single' \"double\" \\ back/slash %20 ​ zero-width"
SPECIAL = "Line one\nLine two\ttabbed <script>alert(1)</script> & ampersand ' \" \\ ₹ 5,00,000 — ✓ 😀"


def make(c, **kw):
    body = {"title": f"Desc {uuid.uuid4().hex[:6]}", "description": "", "parties": "A v. B", "jurisdiction_id": "IN", **kw}
    r = c.post("/matters", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("text", [TELUGU, SPECIAL, "plain", "  padded with spaces  ", "x" * 20000])
def test_description_is_kept_exactly_on_create_and_in_every_view(user_a, text):
    m = make(user_a, description=text)
    assert m["description"] == text
    assert user_a.get(f"/matters/{m['id']}").json()["description"] == text  # detail view
    listed = [x for x in user_a.get("/matters").json() if x["id"] == m["id"]][0]  # list view
    assert listed["description"] == text


def test_description_over_the_limit_is_refused_clearly_not_silently_cut(user_a):
    r = user_a.post("/matters", json={"title": "Too long", "description": "x" * 20001})
    assert r.status_code == 422


@pytest.mark.parametrize("text", [TELUGU, SPECIAL, "x" * 20000])
def test_description_can_be_edited_after_the_matter_exists(user_a, text):
    m = make(user_a, description="first")
    r = user_a.patch(f"/matters/{m['id']}", json={"description": text})
    assert r.status_code == 200, r.text
    assert r.json()["description"] == text
    assert user_a.get(f"/matters/{m['id']}").json()["description"] == text
    assert [x for x in user_a.get("/matters").json() if x["id"] == m["id"]][0]["description"] == text


def test_description_can_be_cleared_and_other_details_are_not_touched(user_a):
    m = make(user_a, description="to clear", parties="P v. Q")
    r = user_a.patch(f"/matters/{m['id']}", json={"description": ""})
    assert r.status_code == 200
    got = user_a.get(f"/matters/{m['id']}").json()
    assert got["description"] == "" and got["parties"] == "P v. Q" and got["title"] == m["title"]


def test_changing_the_status_does_not_wipe_the_description(user_a):
    m = make(user_a, description=TELUGU)
    assert user_a.patch(f"/matters/{m['id']}", json={"status": "ON_HOLD"}).status_code == 200
    assert user_a.patch(f"/matters/{m['id']}", json={"status": "OPEN"}).status_code == 200
    assert user_a.get(f"/matters/{m['id']}").json()["description"] == TELUGU


def test_analysis_and_new_documents_do_not_change_the_description(user_a):
    from tests.conftest import upload

    m = make(user_a, description=SPECIAL)
    upload(user_a, m["id"], "note.txt", "The tenant paid rent on 5 March 2024.")
    assert user_a.get(f"/matters/{m['id']}").json()["description"] == SPECIAL


def test_a_description_edit_is_recorded_in_the_audit_trail(user_a):
    m = make(user_a, description="before")
    user_a.patch(f"/matters/{m['id']}", json={"description": "after"})
    events = user_a.get("/audit").json()
    assert any(e.get("operation") == "MATTER_UPDATE" and e.get("matter_id") == m["id"] for e in events)


def test_one_organisation_cannot_edit_anothers_description(user_a, user_b):
    m = make(user_a, description="mine")
    assert user_b.patch(f"/matters/{m['id']}", json={"description": "taken"}).status_code in (403, 404)
    assert user_a.get(f"/matters/{m['id']}").json()["description"] == "mine"
