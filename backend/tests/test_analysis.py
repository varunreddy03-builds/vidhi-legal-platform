"""Strategy / reasoning / behaviour analyses through the real API with a scripted model. Rules under test: sources shown are the ones retrieved, a citation to anything else is dropped,
unsafe sentences (diagnoses, guarantees, invented probabilities, certain intent) are removed and reported, confidence can only go down, and ordinary users on the AI plan only."""

import uuid

import pytest

from tests.conftest import ai_prompts, set_plan, stub


def reply(**extra):
    base = {"summary": "Two options are open.", "options": [{"idea": "Wait and document.", "reasoning": "It keeps choices open.", "risks": ["Time passes."], "sources": []}],
            "assumptions": ["The invoice is undisputed."], "alternative_explanations": ["A cash-flow problem."], "open_questions": ["Was there a written promise?"], "confidence": "high"}
    base.update(extra)
    return base


def ask(c, kind, tag, **body):
    return c.post(f"/analysis/{kind}", json={"question": f"zq{tag[:12]} zw{tag[12:24]} ze{tag[24:]}", **body})  # nonsense words: other tests leave searchable fixture text, so ordinary words would match it


@pytest.mark.parametrize("kind", ["strategy", "reasoning", "behaviour"])
def test_each_kind_returns_a_checked_analysis_with_fixed_limits(user_a, kind):
    tag = uuid.uuid4().hex
    stub("research", reply(), contains=tag[:12])
    r = ask(user_a, kind, tag)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == kind and body["summary"] and body["removed_by_vidhi"] == [] and len(body["limits"]) >= 3
    assert body["source_note"] and body["confidence"] == "low"  # nothing was retrieved, so the model's "high" is lowered by code
    assert ai_prompts(tag[:12], "research")  # the model really was asked


def test_unsafe_sentences_are_removed_reported_and_confidence_is_lowered(user_a):
    tag = uuid.uuid4().hex
    stub("research", reply(summary="He is a psychopath. There is a 70% chance they will settle. This always works."), contains=tag[:12])
    body = ask(user_a, "behaviour", tag).json()
    assert sorted(f["rule"] for f in body["removed_by_vidhi"]) == ["diagnosis", "probability", "universal"]
    assert "psychopath" not in body["summary"] and "70%" not in body["summary"] and body["confidence"] == "low"


def test_only_retrieved_sources_can_be_cited(user_a):
    tag = uuid.uuid4().hex[:10]
    word = f"quillgambit{tag}"
    assert user_a.post("/knowledge/private", json={"title": "Our playbook", "text": f"TEST FIXTURE ONLY.\n\nChapter 1\n\nThe {word} idea: name your assumption first."}).status_code in (200, 201)
    stub("research", reply(options=[{"idea": "Name assumptions.", "reasoning": "x", "risks": [], "sources": ["S1", "S9"]}], confidence="medium"), contains=word)
    r = user_a.post("/analysis/reasoning", json={"question": f"{word} zq{tag}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [s["id"] for s in body["sources"]] == ["S1"] and body["sources"][0]["work"] == "Our playbook"
    assert body["options"][0]["sources"] == ["S1"] and body["options"][0]["unmatched_sources"] == 1
    assert body["source_note"] is None and body["confidence"] == "medium"


def test_numbers_the_person_supplied_are_not_called_invented(user_a):
    tag = uuid.uuid4().hex
    stub("research", reply(summary="You noted a 30% chance of delay."), contains=tag[:12])
    body = ask(user_a, "strategy", tag, context="My supplier says there is a 30% chance the goods arrive late.").json()
    assert body["removed_by_vidhi"] == []


def test_a_bad_model_reply_is_a_clear_error_not_an_empty_analysis(user_a):
    tag = uuid.uuid4().hex
    stub("research", reply(summary=""), contains=tag[:12])
    assert ask(user_a, "strategy", tag).status_code == 502


def test_unknown_kind_and_short_question_are_rejected(user_a):
    assert user_a.post("/analysis/telepathy", json={"question": "A long enough question here."}).status_code == 422
    assert user_a.post("/analysis/strategy", json={"question": "short"}).status_code == 422


def test_free_plan_is_counted_like_other_ai_requests_and_anonymous_is_refused(user_a, anon):
    set_plan(user_a, "FREE")
    tag = uuid.uuid4().hex
    stub("research", reply(), contains=tag[:12])
    assert ask(user_a, "strategy", tag).status_code == 200
    assert anon.post("/analysis/strategy", json={"question": "A long enough question here."}).status_code in (401, 403)
