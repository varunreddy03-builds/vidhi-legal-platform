"""What happened to a judgment: shown only where a source states it, never guessed, never "good law". Invented judgments and invented parties only."""

import hashlib
import json
import random
import string

import pytest

from lib import judgment_relations as jr
from tests.conftest import mongo
from tests.test_admin import admin  # noqa: F401  (fixture)

NAME = "Adv Invented Reviewer"
DAY = "2026-11-03"


def tag() -> str:
    return "".join(random.choices(string.ascii_lowercase, k=6))


# ---- the rules (no database) ----

def kinds(text):
    return [(i["relation"], i["target_ref"]) for i in jr.extract(text)]


def test_a_clear_statement_by_the_court_is_found_with_its_exact_sentence():
    text = "Counsel were heard. Therefore, we overrule the view expressed in Alpha Traders v. Beta Mills (supra) to this extent. The appeal is allowed."
    got = jr.extract(text)
    assert [(i["relation"], i["target_ref"]) for i in got] == [("overruled", "Alpha Traders v. Beta Mills")]
    assert got[0]["quote"] in text and got[0]["quote"].startswith("Therefore, we overrule")
    assert kinds("We respectfully follow the decision in Gamma Ltd. v. Delta Co. (supra).") == [("followed", "Gamma Ltd. v. Delta Co.")]
    assert kinds("We have distinguished the decision in Epsilon v. Zeta, which turned on other facts.") == [("distinguished", "Epsilon v. Zeta")]


def test_anything_uncertain_is_skipped_rather_than_guessed():
    for text in (
        "The view in Alpha v. Beta (supra) was overruled by a later Bench.",  # passive: who overruled whom is not the court's own statement here
        "Learned counsel submits that we should follow the decision in Alpha v. Beta (supra).",  # an argument, not the court
        "We do not follow the decision in Alpha v. Beta (supra).",  # a refusal
        "If we were to overrule the view expressed in Alpha v. Beta (supra), the result would differ.",  # a condition
        "In that case this Court distinguished the decision in Alpha v. Beta (supra).",  # an EARLIER judgment speaking
        "The court said: \"we overrule the view expressed in Alpha v. Beta (supra)\".",  # a quotation
        "We overrule the preliminary objections and hold that the appeal is maintainable.",  # an objection, not a judgment
        "We follow the procedure laid down in the Rules.",  # not another judgment
    ):
        assert jr.extract(text) == [], text


def test_an_appeal_is_read_from_the_court_and_case_number_the_text_names_and_the_whole_sentence_is_kept():
    text = "This appeal arises out of the judgment and order dated 12.03.2019 passed by the High Court of Gujarat at Ahmedabad in Special Civil Application No. 123 of 2018. Notice was issued."
    got = jr.extract(text)
    assert len(got) == 1 and got[0]["relation"] == "appeal_from"
    assert "High Court of Gujarat" in got[0]["target_ref"] and "No. 123 of 2018" in got[0]["target_ref"] and "12.03.2019" in got[0]["target_ref"]
    assert got[0]["quote"].endswith("No. 123 of 2018.") and "Notice was issued" not in got[0]["quote"]  # "No." did not end the sentence
    assert jr.extract("Counsel submits that the appeal arises out of the order passed by the High Court of Gujarat in Writ Petition No. 5 of 2018.") == []


# ---- the screen's data ----

MINE: dict = {"judgments": []}


@pytest.fixture(autouse=True)
def _clean_up():
    MINE["judgments"].clear()
    yield
    ids = list(MINE["judgments"])
    mongo().hc_judgments.delete_many({"id": {"$in": ids}})
    mongo().judgment_relations.delete_many({"$or": [{"from_id": {"$in": ids}}, {"target_id": {"$in": ids}}]})


def judgment(text="", cnr=None, **over):
    jid = f"ufj-{tag()}"
    MINE["judgments"].append(jid)
    doc = {"id": jid, "court_code": "98_7", "court_name": "Invented Court For Relation Tests", "bench": "invented", "year": 2020, "case_title": f"WP/1/2020 of INVENTED {jid} Vs STATE", "judge": None, "cnr": cnr or f"ZZZZ{random.randrange(10**11, 10**12)}",
           "decision_date": "2020-05-01", "disposal": None, "source_url": "https://example.invalid/j.pdf", "text": text, "text_chars": len(text), "text_kind": "TEXT" if text else "NOT_LOADED",
           "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "status": "UNVERIFIED - not reviewed", **over}
    mongo().hc_judgments.insert_one(doc)
    return jid, doc


def history(c, jid):
    r = c.get(f"/judgments/{jid}/history")
    assert r.status_code == 200, r.text
    return r.json()


def record(jid, text):
    """Store what the rules find in `text`, through the real code, on a database client of its own (the app's client belongs to the app's event loop)."""
    import asyncio
    import os

    from motor.motor_asyncio import AsyncIOMotorClient

    async def go():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        old = jr.db
        jr.db = client[os.environ["DB_NAME"]]
        try:
            return await jr.store(jid, jr.extract(text), hashlib.sha256(text.encode()).hexdigest())
        finally:
            jr.db = old
            client.close()

    return asyncio.run(go())


OVERRULE = "We overrule the view expressed in Alpha Traders v. Beta Mills (supra) to this extent."


def test_a_judgment_with_no_source_for_its_history_says_not_known_and_never_good_law(user_a):
    jid, _ = judgment("A short order. The petition is dismissed.")
    got = history(user_a, jid)
    assert got["known"] is False and got["message"] == "Not known: no source in VIDHI states what happened to this judgment."
    assert got["stated_in_this_judgment"] == [] and got["stated_by_later_judgments"] == []
    assert "does not say whether" in got["limit"].lower()  # the one place the phrase appears is the disclaimer
    blob = json.dumps({k: v for k, v in got.items() if k != "limit"}).lower()
    for claim in ("good law", "still valid", "remains valid", "binding"):
        assert claim not in blob
    assert user_a.get("/judgments/no-such-judgment/history").status_code == 404


def test_a_stated_relation_shows_with_its_sentence_its_source_and_is_unverified(user_a):
    text = f"Heard. {OVERRULE} Appeal allowed."
    jid, _ = judgment(text)
    assert record(jid, text) == 1 and record(jid, text) == 0  # the same statement is never stored twice
    got = history(user_a, jid)
    assert got["known"] is True and "message" not in got
    r = got["stated_in_this_judgment"][0]
    assert r["relation"] == "overruled" and r["target_ref"] == "Alpha Traders v. Beta Mills" and r["quote"] in text
    assert r["source"] == "stated in the judgment's own text" and r["status"] == "UNVERIFIED - not reviewed" and r["verified"] is False and "not compared" in r["note"]


def test_a_later_judgment_is_linked_only_when_it_names_one_cnr_that_matches_one_record(user_a):
    earlier, edoc = judgment("The earlier order.")
    text = f"We overrule the decision in Alpha v. Beta (supra), CNR {edoc['cnr']}, as reported."
    later, _ = judgment(text)
    record(later, text)
    seen = history(user_a, earlier)
    assert [r["label"] for r in seen["stated_by_later_judgments"]] == ["Overruled by a later judgment"] and seen["stated_by_later_judgments"][0]["from_id"] == later
    # the same CNR on two records: no link is made
    twin, tdoc = judgment("Twin one.")
    twin2, _ = judgment("Twin two.", cnr=tdoc["cnr"])
    text2 = f"We follow the decision in Gamma v. Delta (supra), CNR {tdoc['cnr']}."
    third, _ = judgment(text2)
    record(third, text2)
    assert history(user_a, twin)["stated_by_later_judgments"] == [] and history(user_a, twin2)["stated_by_later_judgments"] == []
    # a case number alone (no CNR) links nothing
    text3 = "We follow the decision in Gamma v. Delta (supra), W.P. No. 1 of 2020."
    fourth, _ = judgment(text3)
    record(fourth, text3)
    assert mongo().judgment_relations.find_one({"from_id": fourth})["target_id"] is None


def pending(jid):
    return mongo().judgment_relations.find_one({"from_id": jid})


def test_approval_needs_a_named_reviewer_and_the_sentence_must_still_be_in_the_text(admin, user_a):  # noqa: F811
    text = f"Heard. {OVERRULE}"
    jid, _ = judgment(text)
    record(jid, text)
    rid = pending(jid)["id"]
    assert admin.post(f"/admin/judgments/relations/{rid}/approve", json={"reviewed_by": "Adv", "on": DAY}).status_code == 422
    assert admin.post(f"/admin/judgments/relations/{rid}/approve", json={"reviewed_by": NAME, "on": "later"}).status_code == 422
    assert pending(jid)["status"] == "UNVERIFIED - not reviewed"
    mongo().hc_judgments.update_one({"id": jid}, {"$set": {"text": "Heard. The text was replaced.", "text_sha256": "0" * 64}})
    changed = admin.post(f"/admin/judgments/relations/{rid}/approve", json={"reviewed_by": NAME, "on": DAY})
    assert changed.status_code == 422 and "changed" in changed.json()["detail"]
    mongo().hc_judgments.update_one({"id": jid}, {"$set": {"text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}})
    ok = admin.post(f"/admin/judgments/relations/{rid}/approve", json={"reviewed_by": NAME, "on": DAY})
    assert ok.status_code == 200 and ok.json()["verified"] is True and ok.json()["reviewed_by"] == NAME
    shown = history(user_a, jid)["stated_in_this_judgment"][0]
    assert shown["verified"] is True and shown["reviewed_by"] == NAME and shown["reviewed_on"] == DAY
    assert mongo().audit_events.find_one({"operation": "JUDGMENT_RELATION_REVIEWED", "detail": {"$regex": NAME}})


def test_a_rejected_relation_is_hidden_and_cannot_be_approved_and_the_log_records_it(admin, user_a):  # noqa: F811
    text = OVERRULE
    jid, _ = judgment(text)
    record(jid, text)
    rid = pending(jid)["id"]
    assert admin.post(f"/admin/judgments/relations/{rid}/reject", json={"reviewed_by": NAME, "on": DAY, "reason": "short"}).status_code == 422
    assert admin.post(f"/admin/judgments/relations/{rid}/reject", json={"reviewed_by": NAME, "on": DAY, "reason": "The sentence is about a different case."}).status_code == 200
    assert history(user_a, jid)["known"] is False and history(user_a, jid)["message"].startswith("Not known")
    again = admin.post(f"/admin/judgments/relations/{rid}/approve", json={"reviewed_by": NAME, "on": DAY})
    assert again.status_code == 422 and "rejected" in again.json()["detail"]
    assert mongo().audit_events.find_one({"operation": "JUDGMENT_RELATION_REJECTED", "detail": {"$regex": NAME}})


def test_a_named_person_can_record_a_relation_with_its_source_and_it_starts_unverified(admin, user_a):  # noqa: F811
    jid, _ = judgment("An order.")
    body = {"from_id": jid, "relation": "appeal_from", "target_ref": "Invented High Court, W.P. No. 9 of 2019", "source_note": "The cause list of 2021 shows this order challenged in SLP 1 of 2021.", "entered_by": NAME}
    assert admin.post("/admin/judgments/relations", json={**body, "entered_by": "Adv"}).status_code == 422
    assert admin.post("/admin/judgments/relations", json={**body, "source_note": "too short"}).status_code == 422
    assert admin.post("/admin/judgments/relations", json={**body, "relation": "is_good_law"}).status_code == 422
    assert admin.post("/admin/judgments/relations", json={**body, "from_id": "no-such-judgment"}).status_code == 422
    r = admin.post("/admin/judgments/relations", json=body)
    assert r.status_code == 201 and r.json()["status"] == "UNVERIFIED - not reviewed" and r.json()["source"] == f"entered by {NAME}"
    assert history(user_a, jid)["stated_in_this_judgment"][0]["verified"] is False
    queue = admin.get("/admin/judgments/relations", params={"status": "UNVERIFIED"}).json()
    assert any(i["id"] == r.json()["id"] for i in queue["items"]) and queue["total"] >= 1


ROUTES = [("get", "/admin/judgments/relations", None), ("post", "/admin/judgments/relations", {"from_id": "x", "relation": "followed", "target_ref": "abc", "source_note": "n" * 25, "entered_by": NAME}),
          ("post", "/admin/judgments/relations/x/approve", {"reviewed_by": NAME, "on": DAY}), ("post", "/admin/judgments/relations/x/reject", {"reviewed_by": NAME, "on": DAY, "reason": "Invented reason here."})]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_only_the_operator_can_use_the_relation_review_routes_and_history_needs_a_login(user_a, user_b, anon, method, path, body):
    expected = user_a.get("/admin/overview")
    for client in (user_a, user_b):  # an ordinary user and a user of another organisation are turned away exactly like any other admin page
        r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == expected.status_code == 404 and r.json() == expected.json()
    assert getattr(anon, method)(path, **({"json": body} if body is not None else {})).status_code in (401, 403)
    assert anon.get("/judgments/anything/history").status_code in (401, 403)
