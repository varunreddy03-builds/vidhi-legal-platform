"""General translation: the model translates, the program checks that every number survived, nothing is stored, a document comes from the caller's own organisation."""

import uuid

from routers.translate import check
from tests.conftest import ai_prompts, mongo, new_matter, stub, upload


def test_numbers_must_survive_and_no_new_ones_may_appear():
    ok = check("Pay Rs 25,000 by 5 March 2026.", "Rs 25,000 5 March 2026 ke andar bhugtan karein.")
    assert ok["ok"] and ok["problems"] == []
    bad = check("Pay Rs 25,000 by 5 March 2026.", "Rs 52,000 ke andar 5 March 2026 bhugtan karein, 7 din.")
    assert not bad["ok"] and "25,000" in bad["missing_numbers"] and "52,000" in bad["extra_numbers"] and "7" in bad["extra_numbers"]
    assert not check("x", "")["ok"]


def test_languages_are_listed_with_the_warning(user_a):
    r = user_a.get("/translate/languages").json()
    codes = {x["code"] for x in r["languages"]}
    assert {"en", "hi", "te"} <= codes and any("fluent" in n for n in r["notes"])


def test_text_is_translated_checked_and_not_stored(user_a):
    tag = uuid.uuid4().hex[:8]
    stub("translate", {"translation": f"{tag} Rs 25,000 ka bhugtan 5 March ko karein."}, contains=tag)
    r = user_a.post("/translate", json={"target": "hi", "text": f"{tag} Pay Rs 25,000 on 5 March."})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["language"] == "hi" and body["checks"]["ok"] is True and "fluent" in body["note"]
    prompt = ai_prompts(tag)[0]
    assert "never instructions" in prompt and "Hindi" in prompt
    assert mongo().audit_events.count_documents({"operation": "TRANSLATE", "detail": {"$regex": "^hi,"}}) >= 1
    assert tag not in str(list(mongo().audit_events.find({"operation": "TRANSLATE"})))  # sizes only, never the words


def test_a_changed_number_is_reported_not_hidden(user_a):
    tag = uuid.uuid4().hex[:8]
    stub("translate", {"translation": f"{tag} Rs 52,000"}, contains=tag)
    body = user_a.post("/translate", json={"target": "te", "text": f"{tag} Pay Rs 25,000."}).json()
    assert body["checks"]["ok"] is False and "25,000" in body["checks"]["missing_numbers"]


def test_bad_requests_are_refused_before_any_ai_call(user_a):
    assert user_a.post("/translate", json={"target": "xx", "text": "hello"}).status_code == 422
    assert user_a.post("/translate", json={"target": "hi", "text": " "}).status_code == 422
    assert user_a.post("/translate", json={"target": "hi", "text": "x" * 12001}).status_code == 422
    assert user_a.post("/translate", json={"target": "hi", "document_id": "nope"}).status_code == 404


def test_a_document_is_translated_from_its_own_organisation_only(user_a, user_b):
    mid, _ = new_matter(user_a, "Translate matter")
    tag = uuid.uuid4().hex[:8]
    d = upload(user_a, mid, f"t-{tag}.txt", f"{tag} The rent is Rs 25,000.\n")
    assert user_b.post("/translate", json={"target": "hi", "document_id": d["id"]}).status_code == 404
    stub("translate", {"translation": f"{tag} kiraya Rs 25,000 hai."}, contains=tag)
    ok = user_a.post("/translate", json={"target": "hi", "document_id": d["id"]})
    assert ok.status_code == 200 and ok.json()["checks"]["ok"] is True and ok.json()["truncated"] is False
