"""Conflict-of-interest check: name matching, what it searches, honest limits, and that it never looks outside the signed-in organisation."""

import uuid

import pytest

from lib import conflicts as cf
from tests.conftest import mongo
from tests.test_recovery_stage1 import new_case


def strength(a: str, b: str):
    v = cf.compare(cf.tokens(a), cf.tokens(b))
    return v[0] if v else None


def test_names_are_cleaned_of_honorifics_company_words_and_punctuation():
    assert cf.tokens("Mr. Ramesh  KUMAR") == ["ramesh", "kumar"]
    assert cf.tokens("M/s Acme Traders Pvt. Ltd.") == ["acme", "traders"]
    assert cf.tokens("Smt. Lakshmi Devi") == ["lakshmi", "devi"]
    assert cf.tokens("Dr") == ["dr"]  # a name made only of such words is kept rather than lost
    assert cf.tokens("శ్రీనివాస్ రావు") == ["శ్రీనివాస్", "రావు"] and cf.tokens("राम कुमार") == ["राम", "कुमार"]  # Indian vowel signs survive cleaning


@pytest.mark.parametrize("a,b,expected", [
    ("Ramesh Kumar", "Ramesh Kumar", "strong"),
    ("Ramesh Kumar", "Kumar, Ramesh", "strong"),
    ("Acme Traders Pvt Ltd", "M/s ACME Traders", "strong"),
    ("R. Kumar", "Ramesh Kumar", "possible"),
    ("Ramesh Kumar", "Rammesh Kumar", "possible"),
    ("Ramesh Kumar", "Ramesh Kumar Singh", "possible"),
    ("Sharma", "Ramesh Sharma", "weak"),
    ("Ramesh Kumar", "Suresh Kumar", "weak"),
    ("Ramesh Kumar", "Priya Nair", None),
    ("Ravi", "Rani", None),
    ("Kumar", "Kumaran", None),
    ("రామ్ కుమార్", "రామ్ కుమార్", "strong"),
    ("राम कुमार", "रमेश कुमार", "weak"),
])
def test_matching_strength(a, b, expected):
    assert strength(a, b) == expected


def test_a_matter_title_or_parties_text_is_split_into_names():
    assert cf.parts("Ramesh Kumar v. State of X") == ["Ramesh Kumar", "State of X"]
    assert cf.parts("A Traders vs B Stores; C Mills and D Co, Ee") == ["A Traders", "B Stores", "C Mills", "D Co", "Ee"]
    assert cf.parts("") == [] and cf.parts("a") == []


def check(c, *names):
    r = c.post("/conflicts/check", json={"names": list(names)})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_check_finds_parties_people_and_recovery_cases_in_the_firms_own_records(user_a):
    tag = uuid.uuid4().hex[:6]
    m = user_a.post("/matters", json={"title": f"Kumar v. Vegesna{tag}", "parties": f"Ramesh Kumar{tag}; Orbit Textiles Pvt Ltd"}).json()
    mongo().entities.insert_one({"id": str(uuid.uuid4()), "matter_id": m["id"], "organization_id": user_a.user["organization_id"], "name": f"Priya Nair{tag}", "role": "witness", "aliases": [f"P. Nair{tag}"]})
    cid, debtor = new_case(user_a, debtor=f"Zenith Stores {tag}")
    out = check(user_a, f"Mr. Ramesh Kumar{tag}", "Orbit Textiles", f"Priya Nair{tag}", f"Zenith Stores {tag}", "Somebody Unrelated")
    by = {r["name"]: r for r in out["results"]}
    rk = by[f"Mr. Ramesh Kumar{tag}"]["matches"]
    assert rk[0]["strength"] == "strong" and rk[0]["matter_id"] == m["id"] and rk[0]["href"] == f"/matters/{m['id']}" and rk[0]["matter_status"] == "OPEN"
    assert by["Orbit Textiles"]["matches"][0]["source"] == "Matter parties" and by["Orbit Textiles"]["matches"][0]["strength"] == "strong"
    person = by[f"Priya Nair{tag}"]["matches"]
    assert any(x["source"] == "Person in a matter (witness)" for x in person)
    case = by[f"Zenith Stores {tag}"]["matches"][0]
    assert case["source"] == "Recovery case (debtor)" and case["case_id"] == cid and case["href"] == f"/recovery/cases/{cid}"
    assert by["Somebody Unrelated"]["matches"] == [] and by["Somebody Unrelated"]["total_matches"] == 0
    assert out["searched"]["matters"] >= 1 and out["searched"]["recovery_cases"] >= 1 and out["truncated"] is False


def test_every_answer_says_no_match_is_not_a_clearance(user_a):
    out = check(user_a, "Nobody At All")
    assert "No match does NOT mean there is no conflict" in out["notice"] and "A lawyer decides" in out["notice"]
    assert out["results"][0]["matches"] == []


def test_one_organisation_never_sees_anothers_names(user_a, user_b):
    tag = uuid.uuid4().hex[:8]
    user_b.post("/matters", json={"title": f"Secret matter {tag}", "parties": f"Hidden Person{tag}"})
    new_case(user_b, debtor=f"Hidden Debtor{tag}")
    a = check(user_a, f"Hidden Person{tag}", f"Hidden Debtor{tag}")
    assert [r["matches"] for r in a["results"]] == [[], []]
    b = check(user_b, f"Hidden Person{tag}")
    assert b["results"][0]["matches"][0]["strength"] == "strong"


def test_the_audit_line_records_that_a_check_happened_but_not_the_names(user_a):
    tag = uuid.uuid4().hex[:8]
    check(user_a, f"Confidential Prospect{tag}")
    lines = [e["detail"] for e in mongo().audit_events.find({"operation": "CONFLICT_CHECK", "user_id": user_a.user["id"]})]
    assert lines and all(tag not in d and "Prospect" not in d for d in lines)


def test_bad_requests_are_refused_and_it_needs_a_signed_in_user(user_a, anon):
    assert user_a.post("/conflicts/check", json={"names": []}).status_code == 422
    assert user_a.post("/conflicts/check", json={"names": ["x"]}).status_code == 422
    assert user_a.post("/conflicts/check", json={"names": ["Valid Name"] * 11}).status_code == 422
    assert user_a.post("/conflicts/check", json={"names": ["y" * 300]}).status_code == 422
    assert anon.post("/conflicts/check", json={"names": ["Valid Name"]}).status_code == 401