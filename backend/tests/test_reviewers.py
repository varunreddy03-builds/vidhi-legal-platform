"""Advocate sign-off, on an INVENTED statute: anonymous reviewers are shown only by code, the real names stay in the operator's list, a confirmation goes through the one review gate, the
acknowledgement-needing provisions are skipped, and only an account linked to a registered reviewer can confirm for itself."""

from tests.conftest import mongo
from tests.test_admin import admin  # noqa: F401  (fixture)
from tests.test_legal_data import load


def instrument_of(t) -> str:
    return mongo().provisions.find_one({"instrument_version_id": t["out"]["version_id"]})["instrument_id"]


def register(admin_c, **over):
    body = {"private_name": "Invented Advocate Name", "enrolment_no": "X/1234/1999", "bar_council": "Invented Bar Council", **over}
    r = admin_c.post("/admin/legal/reviewers", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_anonymous_reviewers_get_codes_and_their_real_names_never_leave_the_operator_list(admin, user_a):  # noqa: F811
    first = register(admin)
    second = register(admin, private_name="Another Invented Name", enrolment_no="Y/9/2001")
    assert first["label"].startswith("Advocate R-") and second["label"] != first["label"]
    listing = admin.get("/admin/legal/reviewers").json()["reviewers"]
    assert any(r["private_name"] == "Invented Advocate Name" for r in listing)
    pub = user_a.get("/reviewers")
    assert pub.status_code == 200
    text = pub.text
    assert "Invented Advocate Name" not in text and "X/1234/1999" not in text and "Invented Bar Council" not in text and first["label"] in text
    assert user_a.get("/admin/legal/reviewers").status_code in (403, 404)


def test_a_confirmation_marks_provisions_reviewed_under_the_code_and_logs_it(admin, user_a):  # noqa: F811
    t = load(admin)
    iid = instrument_of(t)
    rev = register(admin)
    body = {"instrument_id": iid, "on": "2026-11-18", "compared_with_official_text": True, "reference": "Written confirmation, folder R-test"}
    refused = admin.post(f"/admin/legal/reviewers/{rev['id']}/record-confirmation", json={**body, "compared_with_official_text": False})
    assert refused.status_code == 422
    assert mongo().provisions.count_documents({"instrument_id": iid, "review_status": "reviewed"}) == 0  # nothing happens without the statement
    ok = admin.post(f"/admin/legal/reviewers/{rev['id']}/record-confirmation", json=body)
    assert ok.status_code == 200, ok.text
    assert ok.json()["confirmed"] == 6 and ok.json()["skipped"] == []
    rows = list(mongo().provisions.find({"instrument_id": iid}))
    assert {r["review_status"] for r in rows} == {"reviewed"} and {r["reviewed_by"] for r in rows} == {rev["label"]}
    assert "Invented Advocate Name" not in str(rows)
    pub = {r["label"]: r for r in user_a.get("/reviewers").json()["reviewers"]}
    assert pub[rev["label"]]["provisions_confirmed"] == 6 and pub[rev["label"]]["acts_confirmed"] == 1
    again = admin.post(f"/admin/legal/reviewers/{rev['id']}/record-confirmation", json=body).json()
    assert again["confirmed"] == 0  # already reviewed: nothing is reviewed twice


def test_provisions_needing_a_person_to_compare_them_are_skipped_not_confirmed(admin):  # noqa: F811
    t = load(admin)
    iid = instrument_of(t)
    one = mongo().provisions.find_one({"instrument_id": iid})
    mongo().provisions.update_one({"id": one["id"]}, {"$set": {"machine_read": True}})
    rev = register(admin)
    out = admin.post(f"/admin/legal/reviewers/{rev['id']}/record-confirmation", json={"instrument_id": iid, "on": "2026-11-18", "compared_with_official_text": True, "reference": "Written confirmation"}).json()
    assert out["confirmed"] == 5 and len(out["skipped"]) == 1 and out["skipped"][0]["provision_id"] == one["id"]
    assert mongo().provisions.find_one({"id": one["id"]})["review_status"] != "reviewed"


def test_a_reviewer_with_an_account_confirms_for_themselves_and_nobody_else_can(admin, user_a, user_b):  # noqa: F811
    t = load(admin)
    iid = instrument_of(t)
    body = {"instrument_id": iid, "on": "2026-11-18", "compared_with_official_text": True}
    assert user_a.post("/reviewer/confirm-act", json=body).status_code == 404  # not a reviewer
    rev = register(admin, private_name="Invented Reviewer Name", enrolment_no="Z/1/2000", account_email=user_a.user["email"])
    assert rev["label"].startswith("Advocate R-")
    assert "Invented Reviewer Name" not in user_a.get("/reviewers").text
    assert user_b.post("/reviewer/confirm-act", json=body).status_code == 404
    ok = user_a.post("/reviewer/confirm-act", json=body)
    assert ok.status_code == 200 and ok.json()["confirmed"] == 6
    assert {r["reviewed_by"] for r in mongo().provisions.find({"instrument_id": iid})} == {rev["label"]}
    assert mongo().legal_review_log.find_one({"reviewer_id": rev["id"]})["mode"] == "SELF"


def test_the_acts_list_and_who_am_i_work_only_for_the_right_people(admin, user_a, user_b):  # noqa: F811
    t = load(admin)
    iid = instrument_of(t)
    acts = admin.get("/admin/legal/reviewers/acts").json()["acts"]
    mine = next(a for a in acts if a["id"] == iid)
    assert mine["provisions"] == 6 and mine["reviewed"] == 0 and mine["waiting"] == 6
    assert user_a.get("/admin/legal/reviewers/acts").status_code in (403, 404)
    assert user_a.get("/reviewer/me").status_code == 404 and user_a.get("/reviewer/acts").status_code == 404  # not a reviewer
    rev = register(admin, private_name="Invented Reviewer Two", enrolment_no="Q/2/2002", account_email=user_a.user["email"])
    me = user_a.get("/reviewer/me")
    assert me.status_code == 200 and me.json() == {"label": rev["label"], "named": False}
    assert any(a["id"] == iid for a in user_a.get("/reviewer/acts").json()["acts"])
    assert user_b.get("/reviewer/me").status_code == 404
    assert "Invented Reviewer Two" not in me.text
