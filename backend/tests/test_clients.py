"""Client records: a firm's own list of who it acts for, linked to matters; own organisation only; closed to portal clients; erased and exported with the organisation."""
from tests.conftest import new_matter  # noqa: F401
from tests.test_admin import admin  # noqa: F401
from tests.conftest import user_a  # noqa: F401


def mk(c, name="Ramesh Kumar", **extra):
    r = c.post("/clients", json={"name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_read_update_and_list(admin):  # noqa: F811
    c = mk(admin, "Acme Traders Pvt Ltd", kind="COMPANY", email="legal@acme.example", phone="+91 98000 00000", notes="Prefers calls after 5 pm.")
    assert c["kind"] == "COMPANY" and "organization_id" not in c and "name_key" not in c
    got = admin.get(f"/clients/{c['id']}").json()
    assert got["name"] == "Acme Traders Pvt Ltd" and got["matters"] == []
    up = admin.patch(f"/clients/{c['id']}", json={"phone": "+91 99999 99999", "name": "  Acme Traders LLP  "})
    assert up.status_code == 200 and up.json()["name"] == "Acme Traders LLP" and up.json()["phone"] == "+91 99999 99999" and up.json()["email"] == "legal@acme.example"
    names = [x["name"] for x in admin.get("/clients").json()]
    assert "Acme Traders LLP" in names
    assert [x["name"] for x in admin.get("/clients?q=acme.example").json()] == ["Acme Traders LLP"] or "Acme Traders LLP" in [x["name"] for x in admin.get("/clients?q=acme.example").json()]


def test_a_blank_name_and_oversized_notes_are_refused(admin):  # noqa: F811
    assert admin.post("/clients", json={"name": "   "}).status_code == 422
    assert admin.post("/clients", json={"name": ""}).status_code == 422
    assert admin.post("/clients", json={"name": "X", "notes": "n" * 5001}).status_code == 422
    assert admin.post("/clients", json={"name": "X", "kind": "ROBOT"}).status_code == 422
    c = mk(admin, "Real")
    assert admin.patch(f"/clients/{c['id']}", json={"name": "   "}).status_code == 422


def test_a_matter_can_be_linked_to_a_client_and_unlinked(admin):  # noqa: F811
    c = mk(admin, "Linked Client")
    mid, _ = new_matter(admin, "Linked")
    r = admin.patch(f"/matters/{mid}", json={"client_id": c["id"]})
    assert r.status_code == 200 and r.json()["client_id"] == c["id"]
    got = admin.get(f"/clients/{c['id']}").json()
    assert [m["id"] for m in got["matters"]] == [mid]
    assert [x["matter_count"] for x in admin.get("/clients").json() if x["id"] == c["id"]] == [1]
    assert admin.delete(f"/clients/{c['id']}").status_code == 409  # still linked
    assert admin.patch(f"/matters/{mid}", json={"client_id": ""}).json()["client_id"] is None
    assert admin.delete(f"/clients/{c['id']}").status_code == 200
    assert admin.get(f"/clients/{c['id']}").status_code == 404


def test_a_matter_cannot_point_at_a_client_that_does_not_exist_or_belongs_to_another_firm(admin, user_a):  # noqa: F811
    mine = mk(admin, "Mine")
    mid, _ = new_matter(user_a, "Theirs")
    assert user_a.patch(f"/matters/{mid}", json={"client_id": "nope"}).status_code == 422
    assert user_a.patch(f"/matters/{mid}", json={"client_id": mine["id"]}).status_code == 422


def test_another_organisation_cannot_see_change_or_delete_my_clients(admin, user_a):  # noqa: F811
    c = mk(admin, "Private Person", notes="secret note")
    assert user_a.get(f"/clients/{c['id']}").status_code == 404
    assert user_a.patch(f"/clients/{c['id']}", json={"name": "Hijacked"}).status_code == 404
    assert user_a.delete(f"/clients/{c['id']}").status_code == 404
    assert c["id"] not in [x["id"] for x in user_a.get("/clients").json()]
    assert admin.get(f"/clients/{c['id']}").json()["name"] == "Private Person"
