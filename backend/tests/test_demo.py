"""The sample matter: invented, labelled, ordinary, once per organisation, and not available to clients."""

from tests.conftest import mongo, new_member


def test_a_sample_matter_is_made_once_and_is_an_ordinary_matter(user_a):
    r = user_a.post("/demo/sample")
    assert r.status_code == 200 and r.json()["created"] is True
    mid = r.json()["matter_id"]
    again = user_a.post("/demo/sample").json()
    assert again == {"matter_id": mid, "created": False}
    matter = next(m for m in user_a.get("/matters").json() if m["id"] == mid)
    assert matter["title"].startswith("SAMPLE:") and "fictional" in matter["title"] and "invented" in matter["description"]
    docs = user_a.get(f"/matters/{mid}/documents").json()
    assert [d["filename"] for d in docs] == ["sample-letter-fictional.txt"] and docs[0]["processing_status"] == "READY"
    detail = user_a.get(f"/documents/{docs[0]['id']}").json()
    assert "FICTIONAL" in detail["pages"][0] and "invented" in detail["pages"][0]
    assert any(e["operation"] == "SAMPLE_MATTER_CREATED" for e in mongo().audit_events.find({"matter_id": mid}))


def test_each_organisation_gets_its_own_sample_and_it_can_be_deleted(user_a, user_b):
    a = user_a.post("/demo/sample").json()["matter_id"]
    b = user_b.post("/demo/sample").json()["matter_id"]
    assert a != b and user_b.get(f"/matters/{a}").status_code == 404
    assert user_a.delete(f"/matters/{a}").status_code == 200
    assert user_a.post("/demo/sample").json()["created"] is True  # deleted, so a new one can be made


def test_a_read_only_member_may_create_it_but_a_client_may_not(user_a):
    from tests.test_portal import make_client, matter_with_secret  # noqa: PLC0415
    from tests.conftest import verify_email  # noqa: PLC0415

    verify_email(user_a)
    mid, _ = matter_with_secret(user_a)
    client = make_client(user_a, mid)
    assert client.post("/demo/sample").status_code == 403
    member = new_member(user_a, "MEMBER")
    assert member.post("/demo/sample").status_code == 200