"""Lawyer directory: opt-in listing, what the public can and cannot see, consultation requests with abuse limits, and the switch that keeps it off."""

import uuid

import httpx
import pytest
from fastapi import HTTPException

from lib import directory
from tests.conftest import API_URL, mongo, new_member, verify_email, wait_for_mail
from tests.test_deploy_config import ROOT  # noqa: F401  (keeps the import graph honest: the directory is documented in .env.example)

PROFILE = {"display_name": "Asha Rao", "city": "Hyderabad", "state": "Telangana", "practice_areas": ["Property", "Civil"], "languages": ["en", "te", "hi"],
           "bio": "Property and civil disputes.", "enrolment_claim": "TS/1234/2015", "listed": True, "accepting_requests": True}


def listed(c, **over):
    tag = uuid.uuid4().hex[:6]
    body = {**PROFILE, "display_name": f"Asha {tag}", "city": f"City{tag}", **over}
    r = c.put("/directory/profile", json=body)
    assert r.status_code == 200, r.text
    return tag, r.json()["profile"]


def request(profile_id, **over):
    body = {"name": "Ravi Kumar", "email": f"r-{uuid.uuid4().hex[:8]}@example.com", "phone": "+91 98765 43210", "message": "I need help with a dispute over a sale deed for a plot.", "consent": True, "elapsed_ms": 5000, **over}
    return httpx.post(f"{API_URL}/public/lawyers/{profile_id}/requests", json=body)


def test_the_switch_is_off_by_default_and_the_public_routes_then_answer_404(monkeypatch):
    monkeypatch.delenv("DIRECTORY_ENABLED", raising=False)
    assert directory.enabled() is False
    from routers.directory import _need_enabled

    with pytest.raises(HTTPException) as e:
        _need_enabled()
    assert e.value.status_code == 404
    assert "DIRECTORY_ENABLED=false" in (ROOT / ".env.example").read_text(encoding="utf-8")


def test_public_info_says_what_the_directory_is_and_is_not(anon):
    info = anon.get("/public/directory").json()
    assert info["enabled"] is True and "Property" in info["practice_areas"] and "te" in info["languages"]
    assert "does not check any lawyer's enrolment" in info["notice"] and "not legal advice" in info["notice"]


def test_a_listing_needs_a_city_and_a_practice_area_and_only_known_choices(user_a):
    assert user_a.put("/directory/profile", json={**PROFILE, "city": ""}).status_code == 422
    assert user_a.put("/directory/profile", json={**PROFILE, "practice_areas": []}).status_code == 422
    assert user_a.put("/directory/profile", json={**PROFILE, "practice_areas": ["Astrology"]}).status_code == 422
    assert user_a.put("/directory/profile", json={**PROFILE, "languages": ["xx"]}).status_code == 422
    assert user_a.put("/directory/profile", json={**PROFILE, "city": "", "practice_areas": [], "listed": False}).status_code == 200  # a draft profile can be saved unlisted


def test_the_public_sees_only_listed_profiles_and_never_contact_details_or_ids(user_a, user_b, anon):
    tag, mine = listed(user_a)
    user_b.put("/directory/profile", json={**PROFILE, "display_name": f"Hidden {tag}", "city": f"City{tag}", "listed": False})
    page = anon.get("/public/lawyers", params={"city": f"City{tag}"}).json()
    assert [x["display_name"] for x in page["items"]] == [f"Asha {tag}"] and page["total"] == 1
    item = page["items"][0]
    assert set(item) == {"id", "display_name", "city", "state", "practice_areas", "languages", "bio", "enrolment_claim", "verified_by_vidhi", "accepting_requests"}
    assert item["verified_by_vidhi"] is False
    raw = anon.get(f"/public/lawyers/{item['id']}").text
    assert user_a.user["email"] not in raw and user_a.user["id"] not in raw and user_a.user["organization_id"] not in raw
    hidden = mongo().directory_profiles.find_one({"user_id": user_b.user["id"]})
    assert anon.get(f"/public/lawyers/{hidden['id']}").status_code == 404


def test_filters_sorting_and_unknown_filters(user_a, user_b, anon):
    tag = uuid.uuid4().hex[:6]
    for c, name, areas, langs in ((user_a, "Zed", ["Family"], ["en"]), (user_b, "Amit", ["Family", "Tax"], ["ta"])):
        assert c.put("/directory/profile", json={**PROFILE, "display_name": f"{name} {tag}", "city": f"Town{tag}", "practice_areas": areas, "languages": langs}).status_code == 200
    names = lambda **q: [x["display_name"] for x in anon.get("/public/lawyers", params={"city": f"town{tag}", **q}).json()["items"]]  # noqa: E731 (city match ignores case)
    assert names() == [f"Amit {tag}", f"Zed {tag}"]  # alphabetical: nobody is ranked or promoted
    assert names(area="Tax") == [f"Amit {tag}"] and names(language="en") == [f"Zed {tag}"] and names(area="Family", language="ta") == [f"Amit {tag}"]
    assert anon.get("/public/lawyers", params={"area": "Astrology"}).status_code == 422 and anon.get("/public/lawyers", params={"language": "xx"}).status_code == 422


def test_only_people_who_may_email_third_parties_can_manage_a_listing(user_a):
    verify_email(user_a)
    member = new_member(user_a, "MEMBER")
    lawyer = new_member(user_a, "LAWYER")
    assert member.get("/directory/profile").status_code == 403 and member.put("/directory/profile", json=PROFILE).status_code == 403
    assert member.get("/directory/requests").status_code == 403
    assert lawyer.put("/directory/profile", json=PROFILE).status_code == 200


def test_a_request_is_stored_the_lawyer_is_told_without_the_content_and_the_requester_is_unverified(user_a, anon):
    tag, p = listed(user_a)
    r = request(p["id"], message="Confidential: my neighbour encroached on my plot " + tag)
    assert r.status_code == 200 and "Nothing has been promised" in r.json()["message"]
    mail = wait_for_mail(user_a.user["email"], "consultation request")
    assert tag not in mail["html"] and "Confidential" not in mail["html"] and "have not been verified" in mail["html"]
    rows = user_a.get("/directory/requests").json()
    assert len(rows) == 1 and rows[0]["status"] == "NEW" and rows[0]["contact_unverified"] is True and tag in rows[0]["message"] and rows[0]["phone"] == "+919876543210"
    assert user_a.patch(f"/directory/requests/{rows[0]['id']}", json={"status": "CONTACTED"}).json()["status"] == "CONTACTED"
    assert user_a.patch(f"/directory/requests/{rows[0]['id']}", json={"status": "WON"}).status_code == 422
    assert user_a.delete(f"/directory/requests/{rows[0]['id']}").status_code == 200 and user_a.get("/directory/requests").json() == []


def test_requests_are_private_to_the_lawyer_they_were_sent_to(user_a, user_b):
    _, p = listed(user_a)
    request(p["id"])
    rid = user_a.get("/directory/requests").json()[0]["id"]
    assert user_b.get("/directory/requests").json() == []
    assert user_b.patch(f"/directory/requests/{rid}", json={"status": "DECLINED"}).status_code == 404
    assert user_b.delete(f"/directory/requests/{rid}").status_code == 404


def test_bad_or_abusive_requests_are_refused(user_a):
    _, p = listed(user_a)
    assert request(p["id"], consent=False).status_code == 422
    assert request(p["id"], website="http://spam.example").status_code == 400  # hidden field filled in: a bot
    assert request(p["id"], elapsed_ms=50).status_code == 400  # sent faster than a person can type
    assert request(p["id"], message="too short").status_code == 422
    assert request("no-such-profile").status_code == 404
    assert user_a.get("/directory/requests").json() == []
    same = f"flood-{uuid.uuid4().hex[:8]}@example.com"
    codes = [request(p["id"], email=same).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]  # one address cannot flood lawyers


def test_a_lawyer_who_stops_taking_requests_or_unlists_cannot_be_written_to(user_a):
    tag, p = listed(user_a)
    assert user_a.put("/directory/profile", json={**PROFILE, "display_name": f"Asha {tag}", "city": f"City{tag}", "accepting_requests": False}).status_code == 200
    assert request(p["id"]).status_code == 404
    assert user_a.put("/directory/profile", json={**PROFILE, "display_name": f"Asha {tag}", "city": f"City{tag}", "listed": False}).status_code == 200
    assert httpx.get(f"{API_URL}/public/lawyers/{p['id']}").status_code == 404


def test_removing_a_person_removes_their_listing_and_requests(user_a):
    verify_email(user_a)
    lawyer = new_member(user_a, "LAWYER")
    tag, p = listed(lawyer)
    request(p["id"])
    assert user_a.delete(f"/org/members/{lawyer.user['id']}").status_code == 200
    assert mongo().directory_profiles.count_documents({"user_id": lawyer.user["id"]}) == 0 and mongo().booking_requests.count_documents({"user_id": lawyer.user["id"]}) == 0
    assert httpx.get(f"{API_URL}/public/lawyers/{p['id']}").status_code == 404