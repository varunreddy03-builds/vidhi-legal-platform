"""Phases 8-9. Evidence classification of audio / brain-frequency claims (code only) and the philosophy comparison (scripted model). Rules under test: established science is
not flagged, unsupported claims are named with a safer wording, hedged and denied statements are left alone, reading lists are lists not content, a quotation is DIRECT TEXT only
if it is in a retrieved source, and attributions without a source say so."""

import json
import uuid
from pathlib import Path

import pytest

from lib.evidence_class import CLASSES, classify, framework
from tests.conftest import stub

DATA = Path(__file__).parent.parent / "data" / "knowledge"
REGISTRY = json.loads((DATA / "registry.json").read_text(encoding="utf-8"))["entries"]
DOMAINS = json.loads((DATA / "domains.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("sentence,rule", [
    ("Binaural beats will automatically increase your IQ.", "guaranteed_gain"),
    ("Listening to this tone is proven to boost intelligence.", "guaranteed_gain"),
    ("This audio track raises your genius level.", "intelligence"),
    ("Sound frequencies can unlock your hidden psychic powers.", "hidden_powers"),
    ("A 528 Hz tone repairs your DNA.", "magic_frequency"),
    ("Your brain will simply sync to the beat you hear.", "sound_equals_brain"),
])
def test_unsupported_claims_are_named_with_a_safer_wording(sentence, rule):
    found = classify(f"Some background. {sentence} More background.")
    assert [f["rule"] for f in found] == [rule] and found[0]["safer"] and found[0]["class"] in CLASSES


@pytest.mark.parametrize("sentence", [
    "The brain produces electrical oscillations that EEG can measure.",
    "Alpha, beta and gamma are conventional names, and their boundaries vary between papers.",
    "Some studies have examined whether binaural beats affect attention, with mixed results.",
    "There is no good evidence that a 432 Hz tone heals the body.",
    "Sellers market this audio as boosting intelligence, but that is a commercial claim.",
    "Whether the brain follows an external rhythm is an open research question.",
    "Loudness and exposure time matter for hearing safety.",
])
def test_established_hedged_and_denied_statements_are_left_alone(sentence):
    assert classify(sentence) == []


def test_the_framework_has_the_seven_required_distinctions_and_says_it_is_unreviewed():
    f = framework()
    assert len(f["distinctions"]) == 7 and {c["id"] for c in f["classes"]} >= {"established_mechanism", "experimental_result", "commercial_claim", "unsupported_claim"}
    assert f["reviewed"] is False and f["bands"]["names"] == ["delta", "theta", "alpha", "beta", "gamma"] and "conventions" in f["bands"]["note"]
    assert any("sample size" in a for a in f["appraise_studies_by"])


def test_the_classify_route_needs_no_ai_and_the_framework_route_answers(user_a):
    r = user_a.post("/evidence/classify", json={"text": "Binaural beats will always unlock your hidden powers."})
    assert r.status_code == 200 and r.json()["findings"] and r.json()["note"] is None
    clean = user_a.post("/evidence/classify", json={"text": "EEG measures brain oscillations."}).json()
    assert clean["findings"] == [] and "does not make the text true" in clean["note"]
    assert user_a.get("/evidence/framework").json()["reviewed"] is False


def test_the_reading_lists_point_only_at_registered_works_and_hold_no_content(user_a):
    numbers = {w["number"] for w in REGISTRY}
    for d in DOMAINS["domains"].values():
        assert all(x["number"] in numbers for x in d["works"])
    assert any("not current neuroscience" in x["role"] for x in DOMAINS["domains"]["neuroscience"]["works"])
    body = user_a.get("/knowledge/domains").json()
    assert set(body["domains"]) == {"neuroscience", "philosophy"} and "Not loaded" in body["domains"]["neuroscience"]["primary_literature"]
    assert "not current legal authority" in body["domains"]["philosophy"]["caveat"]
    assert all("excerpt" not in w and "text" not in w for d in body["domains"].values() for w in d["works"])


def view(**kw):
    base = {"author": "Plato", "work": "The Republic", "position": "Justice is each part doing its own work.", "context": "Ancient Athens.", "basis": "direct_text", "quote": "", "sources": []}
    base.update(kw)
    return base


def philosophy(views, **extra):
    return {"question": "What is justice?", "viewpoints": views, "disagreements": ["Hobbes grounds authority in contract, Plato in the good."], "historical_limits": ["Written for a small city-state."],
            "open_questions": [], "confidence": "high", **extra}


def test_without_a_source_every_attribution_says_it_is_unchecked_and_nothing_is_direct_text(user_a):
    tag = uuid.uuid4().hex
    stub("research", philosophy([view(quote="Justice is the advantage of the stronger, as I fabricated it here.")]), contains=tag[:12])
    r = user_a.post("/analysis/philosophy", json={"question": f"zj{tag[:14]} zk{tag[14:]}"})
    assert r.status_code == 200, r.text
    b = r.json()
    v = b["viewpoints"][0]
    assert v["basis"] == "interpretation" and v["quote"] == "" and "not checked" in v["attribution"] and b["quotes_removed"] == 1
    assert b["confidence"] == "low" and b["source_note"] and any("not current legal authority" in x for x in b["limits"])


def test_a_quotation_is_direct_text_only_when_it_is_in_a_retrieved_source(user_a):
    tag = uuid.uuid4().hex[:10]
    word = f"gryphonlaw{tag}"
    passage = f"TEST FIXTURE ONLY. The {word} holds that a ruler ought to treat every subject alike before the law."
    assert user_a.post("/knowledge/private", json={"title": "Fixture treatise", "text": f"Chapter 1\n\n{passage}"}).status_code in (200, 201)
    stub("research", philosophy([view(work="Fixture treatise", quote=f"The {word} holds that a ruler ought to treat every subject alike before the law", sources=["S1"]),
                                  view(author="Hobbes", work="Leviathan", quote="an invented line that no source contains at all", sources=["S1"])], confidence="medium"), contains=word)
    b = user_a.post("/analysis/philosophy", json={"question": f"{word} zq{tag}"}).json()
    good, bad = b["viewpoints"]
    assert good["basis"] == "direct_text" and good["quote"] and "checked against" in good["attribution"]
    assert bad["basis"] == "interpretation" and bad["quote"] == "" and b["quotes_removed"] == 1 and b["confidence"] == "low"


def test_an_empty_philosophy_reply_is_an_error_not_an_answer(user_a):
    tag = uuid.uuid4().hex
    stub("research", philosophy([]), contains=tag[:12])
    assert user_a.post("/analysis/philosophy", json={"question": f"zj{tag[:14]} zk{tag[14:]}"}).status_code == 502


def test_the_analysis_guard_also_removes_an_unsupported_audio_claim_from_a_model_reply(user_a):
    tag = uuid.uuid4().hex
    stub("research", {"summary": "Binaural beats will automatically increase your IQ.", "options": [], "assumptions": [], "alternative_explanations": [], "open_questions": [], "confidence": "high"}, contains=tag[:12])
    b = user_a.post("/analysis/reasoning", json={"question": f"zj{tag[:14]} zk{tag[14:]}"}).json()
    assert [f["rule"] for f in b["removed_by_vidhi"]] == ["unsupported"] and "IQ" not in b["summary"]
