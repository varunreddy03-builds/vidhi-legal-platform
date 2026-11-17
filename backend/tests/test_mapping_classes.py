"""Mapping classes (exact / partial / related / uncertain / none) and their guards, on INVENTED statutes. Regression tests for: an unsupported claim of equivalence, a claim stronger than the
structure allows, a missing supporting source, a commencement date compared with the conduct date, and the older law never being silently replaced."""

import pytest

from tests.test_admin import admin  # noqa: F401  (fixture)
from tests.test_legal_data import mapping, pair


def make(admin_c, user_c, **over):
    old, new, lp, np_ = pair(admin_c, user_c)
    return old, new, lp, np_, mapping(admin_c, lp, np_, **over)


def test_closeness_is_never_assumed(admin, user_a):  # noqa: F811
    *_, r = make(admin, user_a)
    assert r.status_code == 201 and r.json()["equivalence"] == "uncertain" and r.json()["equivalence_label"] == "Unreviewed claim: uncertain"


@pytest.mark.parametrize("relationship,equivalence,ok", [
    ("one-to-one", "exact", True), ("modified", "exact", False), ("partial", "exact", False), ("split", "exact", False),
    ("modified", "partial", True), ("one-to-one", "partial", False),
    ("modified", "related", True), ("one-to-one", "related", True),
    ("modified", "uncertain", True), ("unresolved", "uncertain", True),
    ("modified", "none", False), ("modified", "nonsense", False),
])
def test_a_claim_of_closeness_must_fit_the_structure(admin, user_a, relationship, equivalence, ok):  # noqa: F811
    old, new, lp, np_ = pair(admin, user_a)
    body = {"equivalence": equivalence}
    if relationship == "unresolved":
        body["new_provision_ids"] = []
    r = mapping(admin, lp, np_, relationship=relationship, **body) if relationship != "unresolved" else admin.post("/admin/legal/mappings", json={
        "relationship": "unresolved", "equivalence": equivalence, "legacy_provision_ids": [lp], "new_provision_ids": [], "differences_in_effect": "Not yet compared by anyone.", "authorities": []})
    assert (r.status_code == 201) is ok, r.text
    if not ok:
        assert r.status_code == 422


def test_exact_partial_and_related_need_a_supporting_source(admin, user_a):  # noqa: F811
    old, new, lp, np_ = pair(admin, user_a)
    for eq, rel in (("exact", "one-to-one"), ("partial", "modified"), ("related", "modified")):
        r = mapping(admin, lp, np_, relationship=rel, equivalence=eq, authorities=[])
        assert r.status_code == 422 and "supporting source" in r.json()["detail"], eq
    assert mapping(admin, lp, np_, relationship="modified", equivalence="uncertain", authorities=[]).status_code == 201   # saying "not sure" needs no source


def test_an_absent_provision_is_recorded_as_none_not_as_a_match(admin, user_a):  # noqa: F811
    old, new, lp, np_ = pair(admin, user_a)
    r = admin.post("/admin/legal/mappings", json={"relationship": "absent", "legacy_provision_ids": [lp], "differences_in_effect": "Nothing in the newer text corresponds, on comparison.", "authorities": ["Invented table"]})
    assert r.status_code == 201 and r.json()["equivalence"] == "none"
    assert admin.post("/admin/legal/mappings", json={"relationship": "absent", "equivalence": "exact", "legacy_provision_ids": [lp], "differences_in_effect": "Nothing corresponds, on comparison.", "authorities": ["x"]}).status_code == 422


def test_the_lookup_says_which_way_it_searched_and_how_the_dates_compare(admin, user_a):  # noqa: F811
    old, new, lp, np_ = pair(admin, user_a)
    m = mapping(admin, lp, np_, relationship="one-to-one", equivalence="exact", commencement={"date": "2030-01-01", "evidence": "Invented notification 7 of 2030"}).json()
    admin.post(f"/admin/legal/mappings/{m['id']}/review", json={"reviewed_by": "Adv Invented Reviewer", "on": "2026-10-20"})
    before = user_a.get("/legal/mappings", params={"number": "3", "instrument": old["title"], "offence_date": "2029-12-31"}).json()["mappings"][0]
    after = user_a.get("/legal/mappings", params={"number": "3", "instrument": old["title"], "offence_date": "2030-06-01"}).json()["mappings"][0]
    reverse = user_a.get("/legal/mappings", params={"number": "3", "instrument": new["title"]}).json()["mappings"][0]
    assert before["equivalence_label"] == "Reviewed: exact" and before["searched_from"] == "older text" and reverse["searched_from"] == "newer text"
    assert before["conduct_vs_commencement"] == "before" and "may not have been in force" in before["timing_note"] and "older text may govern" in before["timing_note"]
    assert after["conduct_vs_commencement"] == "on_or_after" and "does not decide which text applies" in after["timing_note"]
    assert "conduct_vs_commencement" not in reverse   # no conduct date was given


def test_no_recorded_commencement_is_reported_as_unknown_never_assumed(admin, user_a):  # noqa: F811
    old, new, lp, np_ = pair(admin, user_a)
    mapping(admin, lp, np_)
    m = user_a.get("/legal/mappings", params={"number": "3", "instrument": old["title"], "offence_date": "2026-01-01"}).json()["mappings"][0]
    assert m["conduct_vs_commencement"] == "unknown" and "cannot say whether the newer text was in force" in m["timing_note"]


def test_a_commencement_date_needs_evidence_and_a_real_date(admin, user_a):  # noqa: F811
    old, new, lp, np_ = pair(admin, user_a)
    assert mapping(admin, lp, np_, commencement={"date": "2030-01-01", "evidence": ""}).status_code == 422
    assert mapping(admin, lp, np_, commencement={"date": "1st July", "evidence": "Invented notification 7 of 2030"}).status_code == 422
