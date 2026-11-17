"""Phase 16: amendment history by date, cross-references, forums and remedies, and case-law treatment, all on INVENTED material (an invented Charter, Act, courts and decisions).
Nothing here is real law, and the engine is shown to claim nothing the loaded, dated, reviewed records do not support."""

import random
import string

import pytest

from lib import legal_graph, legal_history
from tests.test_admin import admin  # noqa: F401  (fixture)
from tests.test_legal_data import document, ingest, source


def tag() -> str:
    return "".join(random.choices(string.ascii_uppercase, k=6))


def charter_v1(t):
    return [f"""THE FICTIONAL {t} CHARTER, 2000

PART I
THE REALM

1. The realm.—The realm of Examplia is a union of districts. See article 2 and the First Schedule.

2. Districts.—The districts are listed in the First Schedule, subject to article 5.""",
            f"""PART II
RIGHTS

5. Equal treatment.—(1) Every person is equal before the council.
(2) The council shall not treat a person unequally, except as provided in sub-section (1) of section 3 of the Fictional {t} Act.

6. Gathering.—All persons may gather in the market square.
Provided that the gathering is peaceful.

THE FIRST SCHEDULE
The districts of Examplia."""]


def charter_v2(t):
    return [f"""THE FICTIONAL {t} CHARTER, 2000 (as amended in 2010)

PART I
THE REALM

1. The realm.—The realm of Examplia is a union of districts. See article 2 and the First Schedule.

2. Districts.—The districts are listed in the First Schedule, subject to article 5.""",
            f"""PART II
RIGHTS

5. Equal treatment.—(1) Every person is equal before the council and the court.
(2) The council shall not treat a person unequally, except as provided in sub-section (1) of section 3 of the Fictional {t} Act.

7. Assembly of councils.—The councils may meet as provided in articles 5 and 7.

THE FIRST SCHEDULE
The districts of Examplia."""]


def target_act(t):
    return [f"""THE FICTIONAL {t} ACT, 1950

1. Short title.—This Act may be called the Fictional {t} Act, 1950.

3. Exceptions.—(1) The council may treat persons differently for the festival of lamps.
(2) Nothing in subsection (1) affects article 5 of the Charter."""]


def load_charter(admin_c, t, dated=True, second_undated=False):
    src = source(admin_c)
    title, short = f"Fictional {t} Charter", f"FC{t}"
    d1 = document(admin_c, src, charter_v1(t), title="Charter v1")
    d2 = document(admin_c, src, charter_v2(t), title="Charter v2")
    ev = "Invented notification bringing it into force"

    def put(doc, label, **dates):
        r = admin_c.post("/admin/legal/ingest", json={"document_id": doc["id"], "instrument": {"title": title, "short_names": [short], "kind": "constitution", "year": 2000}, "version_label": label, **dates})
        assert r.status_code == 201, r.text
        return r.json()

    out1 = put(d1, "original", **({"effective_from": "2000-01-01", "effective_to": "2010-06-01", "evidence": ev} if dated else {}))
    out2 = put(d2, "consolidated", **({"effective_from": "2010-06-01", "evidence": ev} if dated and not second_undated else {}))
    return title, short, out1, out2


def load_act(admin_c, t):
    src = source(admin_c)
    doc = document(admin_c, src, target_act(t), title="Act text")
    return ingest(admin_c, doc, f"Fictional {t} Act", f"FA{t}")


# ---------------------------------------------------------------------------------------------
# reference extraction (pure)
# ---------------------------------------------------------------------------------------------
def refs(text, own=None):
    return [(r["kind"], r["number"], r["sub"], r["hint"]) for r in legal_graph.extract_references(text, own)]


@pytest.mark.parametrize("text,expected", [
    ("subject to section 12", [("section", "12", "", None)]),
    ("as in article 21A", [("article", "21A", "", None)]),
    ("sub-section (2) of section 5", [("section", "5", "", None)]),
    ("sections 5, 6 and 7", [("section", "5", "", None), ("section", "6", "", None), ("section", "7", "", None)]),
    ("section 5(2)(a)", [("section", "5", "(2)(a)", None)]),
    ("section 9 of the Fictional Penal Act, 1901", [("section", "9", "", "Fictional Penal Act, 1901")]),
    ("section 9 of this Act", [("section", "9", "", None)]),
    ("section 9 of the said Act", [("section", "9", "", None)]),
    ("section 8 of the contract is an Act of kindness", [("section", "8", "", None)]),
    ("see Part III and Chapter IV", [("part", "III", "", None), ("chapter", "IV", "", None)]),
    ("the Second Schedule", [("schedule", "Second", "", None)]),
    ("part-payment was made", []),
    ("", []),
])
def test_references_are_found_by_fixed_patterns(text, expected):
    assert refs(text) == expected


def test_a_provision_does_not_refer_to_itself_and_duplicates_are_dropped():
    assert refs("this section 5 and section 6 and section 6", own="5") == [("section", "6", "", None)]


# ---------------------------------------------------------------------------------------------
# history states (pure)
# ---------------------------------------------------------------------------------------------
V1 = {"id": "v1", "label": "original", "effective_from": "2000-01-01", "effective_to": "2010-06-01", "evidence": "x", "created_at": 1}
V2 = {"id": "v2", "label": "consolidated", "effective_from": "2010-06-01", "effective_to": None, "evidence": "x", "created_at": 2}
P1, P2 = {"id": "p1", "content_sha256": "a"}, {"id": "p2", "content_sha256": "b"}


@pytest.mark.parametrize("day,present,state", [
    ("2005-03-04", {"v1": P1, "v2": P2}, "FOUND_IN_VERSION"),
    ("2015-01-01", {"v1": P1, "v2": None}, "NOT_IN_THAT_VERSION"),
    ("1999-12-31", {"v1": P1, "v2": P2}, "NO_VERSION_COVERS_DATE"),
    ("2010-06-01", {"v1": P1, "v2": P2}, "FOUND_IN_VERSION"),   # the boundary day belongs to the later version
    ("2010-05-31", {"v1": P1, "v2": P2}, "FOUND_IN_VERSION"),
])
def test_the_state_on_a_day_comes_only_from_recorded_dates(day, present, state):
    s = legal_history.state_on(day, [V1, V2], present)
    assert s["state"] == state
    if state == "FOUND_IN_VERSION":
        assert s["version_id"] == ("v2" if day >= "2010-06-01" else "v1")


def test_overlapping_versions_are_ambiguous_and_undated_ones_block_a_guess():
    overlap = {**V2, "effective_from": "2009-01-01"}
    assert legal_history.state_on("2009-06-01", [V1, overlap], {"v1": P1, "v2": P2})["state"] == "AMBIGUOUS"
    undated = {**V2, "effective_from": None}
    assert legal_history.state_on("2015-01-01", [V1, undated], {"v1": P1, "v2": P2})["state"] == "UNDATED_VERSIONS"


def test_the_timeline_marks_changes_gaps_overlaps_and_missing_dates():
    tl = legal_history.build_timeline([{"version": V2, "provision": P2}, {"version": V1, "provision": P1}])
    assert [e["version_id"] for e in tl["entries"]] == ["v1", "v2"] and [e["change"] for e in tl["entries"]] == ["first_recorded", "changed"] and tl["warnings"] == []
    same = legal_history.build_timeline([{"version": V1, "provision": P1}, {"version": V2, "provision": P1}])
    assert same["entries"][1]["change"] == "unchanged"
    gap = legal_history.build_timeline([{"version": V1, "provision": P1}, {"version": {**V2, "effective_from": "2012-01-01"}, "provision": P2}])
    assert any("no loaded version covers" in w for w in gap["warnings"])
    overlap = legal_history.build_timeline([{"version": V1, "provision": P1}, {"version": {**V2, "effective_from": "2009-01-01"}, "provision": P2}])
    assert any("at the same time" in w for w in overlap["warnings"])
    undated = legal_history.build_timeline([{"version": V1, "provision": P1}, {"version": {**V2, "effective_from": None}, "provision": P2}])
    assert any("no recorded effective date" in w for w in undated["warnings"])


# ---------------------------------------------------------------------------------------------
# history and references through the API
# ---------------------------------------------------------------------------------------------
def test_an_article_is_followed_across_amendments_and_answered_as_on_a_date(admin, user_a):  # noqa: F811
    t = tag()
    title, short, *_ = load_charter(admin, t)
    r = user_a.get("/legal/history", params={"number": "5", "instrument": title})
    assert r.status_code == 200, r.text
    item = r.json()["results"][0]
    assert [e["label"] for e in item["timeline"]] == ["original", "consolidated"] and item["timeline"][1]["change"] == "changed" and item["warnings"] == []
    assert all(e["review_status"] == "unreviewed" for e in item["timeline"])

    on = lambda number, day: user_a.get("/legal/history", params={"number": number, "instrument": title, "on": day}).json()["results"][0]["as_on"]  # noqa: E731
    old = on("5", "2005-05-05")
    assert old["state"] == "FOUND_IN_VERSION" and old["version_label"] == "original" and "equal before the council." in old["provision"]["text"] and "and the court" not in old["provision"]["text"]
    new = on("5", "2015-05-05")
    assert new["state"] == "FOUND_IN_VERSION" and "and the court" in new["provision"]["text"]
    assert on("6", "2015-05-05")["state"] == "NOT_IN_THAT_VERSION"      # article 6 is not in the later version
    assert on("7", "2005-05-05")["state"] == "NOT_IN_THAT_VERSION"      # article 7 is not yet in the earlier one
    assert on("5", "1990-01-01")["state"] == "NO_VERSION_COVERS_DATE"
    assert "not a statement of what the law was" in user_a.get("/legal/history", params={"number": "5", "instrument": title, "on": "2005-05-05"}).json()["note"]


def test_a_version_without_dates_cannot_answer_as_on_a_date(admin, user_a):  # noqa: F811
    t = tag()
    title, *_ = load_charter(admin, t, dated=False)
    r = user_a.get("/legal/history", params={"number": "5", "instrument": title, "on": "2005-05-05"}).json()["results"][0]
    assert r["as_on"]["state"] == "UNDATED_VERSIONS" and any("no recorded effective date" in w for w in r["warnings"])


def test_bad_dates_and_unknown_provisions_are_handled(admin, user_a):  # noqa: F811
    assert user_a.get("/legal/history", params={"number": "5", "on": "5th May"}).status_code == 422
    assert user_a.get("/legal/history", params={"number": "99999"}).json()["results"] == []
    assert user_a.get("/legal/history", params={"number": "5"}).status_code == 200
    assert user_a.get("/legal/provisions/not-real/references").status_code == 404


def test_cross_references_are_built_on_ingest_resolved_where_loaded_and_never_reviewed(admin, user_a):  # noqa: F811
    t = tag()
    load_act(admin, t)                    # the target of the external reference must be loaded before the charter so it resolves at ingest
    title, *_ = load_charter(admin, t)
    art5 = user_a.get("/legal/search", params={"q": f"Article 5 of the {title}", "on": "2005-05-05"}).json()["exact"][0]["provisions"][0]
    out = user_a.get(f"/legal/provisions/{art5['id']}/references").json()
    by_target = {(e["kind"], e["to_number"]): e for e in out["refers_to"]}
    ext = by_target[("section", "3")]
    assert ext["hint"] == f"Fictional {t} Act" and ext["resolved"] and len(ext["to_provision_ids"]) == 1 and ext["derived_by"] == "code" and ext["review_status"] == "unreviewed"
    assert "does not say the provisions are related in law" in out["note"]

    # article 1 points to article 2 (same version, resolved) and to the First Schedule (structural, never resolved to a provision)
    art1 = user_a.get("/legal/search", params={"q": f"Article 1 of the {title}", "on": "2005-05-05"}).json()["exact"][0]["provisions"][0]
    e1 = {(e["kind"], e["to_number"]): e for e in user_a.get(f"/legal/provisions/{art1['id']}/references").json()["refers_to"]}
    assert e1[("article", "2")]["resolved"] and e1[("schedule", "First")]["structural"] and not e1[("schedule", "First")]["resolved"]

    # article 5 is referred to by article 2 (same version), and the Act's section 3 refers back to "article 5 of the Charter" (not resolvable without a name)
    back = [e["from_number"] for e in user_a.get(f"/legal/provisions/{art5['id']}/references").json()["referred_to_by"]]
    assert "2" in back


def test_an_article_is_found_by_its_citation_and_labelled_as_an_article(admin, user_a):  # noqa: F811
    t = tag()
    title, short, *_ = load_charter(admin, t)
    for q in (f"Article 5 of the {title}", f"art. 5 of the {title}", f"अनुच्छेद 5 {title}"):
        hits = user_a.get("/legal/search", params={"q": q, "on": "2005-05-05"}).json()["exact"]
        assert hits and hits[0]["provisions"][0]["unit"] == "Article" and hits[0]["provisions"][0]["number"] == "5", q
    # an Act keeps its "Section" label
    act = load_act(admin, t)
    sec = user_a.get("/legal/search", params={"q": f"Section 3 of the Fictional {t} Act"}).json()["exact"][0]["provisions"][0]
    assert sec["unit"] == "Section" and act["created"]


def test_the_parts_and_schedule_of_a_charter_are_kept_in_the_path(admin, user_a):  # noqa: F811
    t = tag()
    title, *_ = load_charter(admin, t)
    art5 = user_a.get("/legal/search", params={"q": f"Article 5 of the {title}", "on": "2005-05-05"}).json()["exact"][0]["provisions"][0]
    assert any("PART II" in step.upper() for step in art5["path"])
    # the proviso of article 6 stays attached to its rule
    art6 = user_a.get("/legal/search", params={"q": f"Article 6 of the {title}", "on": "2005-05-05"}).json()["exact"][0]["provisions"][0]
    assert [c["kind"] for c in art6["components"]] == ["rule", "proviso"] and art6["limits"]


def test_rebuilding_edges_is_repeatable(admin):  # noqa: F811
    t = tag()
    _, _, out1, _ = load_charter(admin, t)
    a = admin.post(f"/admin/legal/graph/rebuild/{out1['version_id']}").json()
    b = admin.post(f"/admin/legal/graph/rebuild/{out1['version_id']}").json()
    assert a == b and a["edges"] >= 3
    assert admin.post("/admin/legal/graph/rebuild/not-a-version").status_code == 404
    assert admin.get("/admin/legal/graph/summary").json()["edges"] >= a["edges"]


# ---------------------------------------------------------------------------------------------
# forums and remedies
# ---------------------------------------------------------------------------------------------
def forum(admin_c, name, kind="court", level="district", parent=None, remedies=None, **over):
    body = {"name": name, "kind": kind, "level": level, "source_note": "Entered from an invented gazette for testing", "remedies": remedies or [], "parent_id": parent, **over}
    r = admin_c.post("/admin/legal/forums", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_forums_ship_unreviewed_and_say_so(admin, user_a):  # noqa: F811
    t = tag()
    f = forum(admin, f"Court of Examplia {t}", remedies=[{"name": f"order of restoration {t}", "provision_ref": "Charter article 5"}])
    assert f["review_status"] == "unreviewed" and "Not reviewed" in f["review_statement"]
    listed = user_a.get("/legal/forums", params={"remedy": f"restoration {t}"}).json()
    assert listed["count"] == 1 and "None of these have been reviewed" in listed["note"]
    assert user_a.get("/legal/forums", params={"remedy": f"restoration {t}", "reviewed_only": "true"}).json()["count"] == 0


def test_a_reviewed_forum_is_reviewed_by_a_named_person_and_any_edit_undoes_it(admin, user_a):  # noqa: F811
    f = forum(admin, f"Tribunal of Examplia {tag()}", kind="tribunal", level="tribunal")
    assert admin.post(f"/admin/legal/forums/{f['id']}/review", json={"reviewer": "Ana", "reviewed_on": "2026-10-20"}).status_code == 422
    assert admin.post(f"/admin/legal/forums/{f['id']}/review", json={"reviewer": "Reviewer Lawyer", "reviewed_on": "20 October"}).status_code == 422
    ok = admin.post(f"/admin/legal/forums/{f['id']}/review", json={"reviewer": "Reviewer Lawyer", "reviewed_on": "2026-10-20"})
    assert ok.status_code == 200 and ok.json()["review_status"] == "reviewed" and "Reviewer Lawyer" in ok.json()["review_statement"]
    edited = admin.patch(f"/admin/legal/forums/{f['id']}", json={"subject": "disputes about tokens"})
    assert edited.status_code == 200 and edited.json()["review_status"] == "unreviewed" and edited.json()["reviewed_by"] is None


def test_the_chain_of_appeal_is_verified_only_when_every_forum_on_it_is_reviewed(admin, user_a):  # noqa: F811
    t = tag()
    apex = forum(admin, f"Apex Court of Examplia {t}", level="apex")
    high = forum(admin, f"High Court of Examplia {t}", level="high", parent=apex["id"])
    low = forum(admin, f"District Court of Examplia {t}", level="district", parent=high["id"])
    chain = user_a.get(f"/legal/forums/{low['id']}/chain").json()
    assert [f["id"] for f in chain["chain"]] == [low["id"], high["id"], apex["id"]] and chain["verified"] is False
    for f in (apex, high):
        admin.post(f"/admin/legal/forums/{f['id']}/review", json={"reviewer": "Reviewer Lawyer", "reviewed_on": "2026-10-20"})
    assert user_a.get(f"/legal/forums/{low['id']}/chain").json()["verified"] is False   # the lowest forum is still unreviewed
    admin.post(f"/admin/legal/forums/{low['id']}/review", json={"reviewer": "Reviewer Lawyer", "reviewed_on": "2026-10-20"})
    assert user_a.get(f"/legal/forums/{low['id']}/chain").json()["verified"] is True
    rel = user_a.get(f"/legal/forums/{low['id']}/relation/{apex['id']}").json()
    assert rel["relation"] == "CITED_FORUM_IS_ABOVE" and rel["verified"] is True and "A lawyer must check" in rel["note"]
    assert user_a.get(f"/legal/forums/{apex['id']}/relation/{low['id']}").json()["relation"] == "UNKNOWN"   # downward: nothing is concluded
    assert user_a.get(f"/legal/forums/{low['id']}/relation/not-real").json()["relation"] == "UNKNOWN"


def test_a_loop_in_the_chain_and_bad_input_are_refused(admin):  # noqa: F811
    a = forum(admin, f"Court A {tag()}")
    b = forum(admin, f"Court B {tag()}", parent=a["id"])
    assert admin.patch(f"/admin/legal/forums/{a['id']}", json={"parent_id": b["id"]}).status_code == 422
    assert admin.patch(f"/admin/legal/forums/{a['id']}", json={"parent_id": a["id"]}).status_code == 422
    assert admin.post("/admin/legal/forums", json={"name": "Some court", "kind": "palace", "source_note": "from an invented gazette"}).status_code == 422
    assert admin.post("/admin/legal/forums", json={"name": "Some court", "kind": "court", "source_note": "short"}).status_code == 422
    assert admin.post("/admin/legal/forums", json={"name": "Some court", "kind": "court", "level": "galactic", "source_note": "from an invented gazette"}).status_code == 422
    assert admin.post("/admin/legal/forums", json={"name": "Some court", "kind": "court", "source_note": "from an invented gazette", "parent_id": "nope"}).status_code == 422


# ---------------------------------------------------------------------------------------------
# case-law interaction
# ---------------------------------------------------------------------------------------------
def decision(admin_c, citation, pages=None, **over):
    r = admin_c.post("/admin/legal/decisions", json={"citation": citation, "title": "Invented v. Imaginary", "source_note": "Invented report for testing", "pages": pages or [], **over})
    assert r.status_code == 201, r.text
    return r.json()


def treat(admin_c, a, b, kind, passage):
    return admin_c.post("/admin/legal/treatments", json={"from_decision_id": a["id"], "to_decision_id": b["id"], "treatment": kind, "passage": passage})


def test_treatments_need_a_real_passage_and_say_what_they_do_not_know(admin, user_a):  # noqa: F811
    t = tag()
    early = decision(admin, f"Invented Reports {t} 1 (1999)")
    late = decision(admin, f"Invented Reports {t} 9 (2010)", pages=["The court considered the earlier decision. We decline to follow the earlier ruling on tokens and say it was wrongly decided."])
    assert treat(admin, late, early, "overruled", "this passage is nowhere in the text").status_code == 422
    assert treat(admin, late, early, "praised", "We decline to follow the earlier ruling").status_code == 422
    assert treat(admin, late, late, "followed", "We decline to follow the earlier ruling").status_code == 422
    assert treat(admin, late, early, "overruled", "short").status_code == 422
    made = treat(admin, late, early, "overruled", "We decline to follow the earlier ruling on tokens")
    assert made.status_code == 201 and made.json()["negative"] is True and made.json()["passage_checked"] is True and made.json()["review_status"] == "unreviewed"

    s = user_a.get(f"/legal/decisions/{early['id']}/standing").json()
    assert s["status"] == "NEGATIVE_TREATMENT_REPORTED_UNREVIEWED" and s["negative_unreviewed"] == 1 and "does not say whether the decision is good law" in s["note"]
    tid = made.json()["id"]
    assert admin.post(f"/admin/legal/treatments/{tid}/review", json={"reviewer": "Reviewer Lawyer", "reviewed_on": "2026-10-20"}).status_code == 200
    assert user_a.get(f"/legal/decisions/{early['id']}/standing").json()["status"] == "NEGATIVE_TREATMENT_REVIEWED"


def test_a_decision_with_no_recorded_treatment_is_never_called_good_law(admin, user_a):  # noqa: F811
    d = decision(admin, f"Invented Reports {tag()} 3 (2001)")
    s = user_a.get(f"/legal/decisions/{d['id']}/standing").json()
    assert s["status"] == "NO_TREATMENT_RECORDED" and "good law" in s["note"] and "is good law" not in s["note"].replace("does not say whether the decision is good law", "")


def test_positive_treatments_are_not_negative_and_unchecked_passages_cannot_be_reviewed(admin, user_a):  # noqa: F811
    t = tag()
    a = decision(admin, f"Invented Reports {t} 4 (2003)")
    b = decision(admin, f"Invented Reports {t} 5 (2004)", pages=["We follow the earlier decision on tokens and apply it here."])
    c = decision(admin, f"Invented Reports {t} 6 (2005)")            # no text loaded
    ok = treat(admin, b, a, "followed", "We follow the earlier decision on tokens")
    assert ok.status_code == 201 and ok.json()["negative"] is False
    assert user_a.get(f"/legal/decisions/{a['id']}/standing").json()["status"] == "TREATMENTS_RECORDED_NONE_NEGATIVE"
    unchecked = treat(admin, c, a, "distinguished", "The facts here are different from the earlier case")
    assert unchecked.status_code == 201 and unchecked.json()["passage_checked"] is False
    refused = admin.post(f"/admin/legal/treatments/{unchecked.json()['id']}/review", json={"reviewer": "Reviewer Lawyer", "reviewed_on": "2026-10-20"})
    assert refused.status_code == 422 and "could not be checked" in refused.json()["detail"]


def test_a_citation_is_loaded_once_and_found_however_it_is_punctuated(admin, user_a):  # noqa: F811
    t = tag()
    first = decision(admin, f"Invented Reports {t} 7 (2006)")
    again = admin.post("/admin/legal/decisions", json={"citation": f"invented reports {t} 7, (2006)", "source_note": "Invented report for testing"})
    assert again.status_code == 201 and again.json()["id"] == first["id"] and again.json()["duplicate"] is True
    assert user_a.get("/legal/decisions", params={"citation": f"INVENTED REPORTS {t} 7 2006"}).json()["id"] == first["id"]
    assert user_a.get("/legal/decisions", params={"citation": "Invented Reports ZZZZZZ 1 (1900)"}).status_code == 404


def test_bad_decision_input_is_refused(admin):  # noqa: F811
    assert admin.post("/admin/legal/decisions", json={"citation": "x", "source_note": "Invented report for testing"}).status_code == 422
    assert admin.post("/admin/legal/decisions", json={"citation": "Invented Reports 1 (1999)", "source_note": "short"}).status_code == 422
    assert admin.post("/admin/legal/decisions", json={"citation": f"Invented Reports {tag()} (1999)", "source_note": "Invented report for testing", "decided_on": "yesterday"}).status_code == 422
    assert admin.post("/admin/legal/decisions", json={"citation": f"Invented Reports {tag()} (1999)", "source_note": "Invented report for testing", "forum_id": "nope"}).status_code == 422


# ---------------------------------------------------------------------------------------------
# who may do what
# ---------------------------------------------------------------------------------------------
def test_loading_and_reviewing_is_for_the_operator_only_and_reading_needs_sign_in(user_a, anon):
    refused = user_a.get("/admin/overview").status_code
    for method, path, body in [("post", "/admin/legal/forums", {"name": "x", "kind": "court", "source_note": "0123456789"}), ("post", "/admin/legal/decisions", {"citation": "xxx", "source_note": "0123456789"}),
                               ("post", "/admin/legal/treatments", {}), ("post", "/admin/legal/graph/rebuild/x", None), ("get", "/admin/legal/graph/summary", None)]:
        kw = {"json": body} if body is not None else {}
        assert getattr(user_a, method)(path, **kw).status_code == refused, path
    for path in ["/legal/history?number=5", "/legal/forums", "/legal/decisions?citation=abc", "/legal/provisions/x/references", "/legal/forums/x/chain", "/legal/decisions/x/standing"]:
        assert anon.get(path).status_code == 401, path
