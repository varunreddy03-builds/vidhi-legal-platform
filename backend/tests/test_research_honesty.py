"""Fixes from the real-case evaluation (docs/VIDHI_REAL_CASE_EVALUATION.md). The research answer must never state a legal time limit from the model's memory, must say inside the
answer text itself when nothing was checked, must tell the model what to do with a named section or case it cannot place, and must not list fragments such as 'v Union' as references."""

import uuid

import pytest

from lib.analysis_guard import DEADLINE_NOTE, strip_unverified_deadlines
from tests.conftest import ai_prompts, new_matter, stub, answer


@pytest.mark.parametrize("sentence", [
    "The notice must be sent within 15 days of the cheque being dishonoured.",
    "An appeal against a decree before the High Court is 30 days from the date of the decree.",
    "Limitation for a money suit is 3 years.",
    "A suit must be filed within three years.",
    "Reply to the notice within thirty days.",
])
def test_a_legal_time_limit_is_removed_when_no_verified_source_backs_it(sentence):
    out, n = strip_unverified_deadlines(f"First. {sentence} Last.")
    assert n == 1 and sentence not in out and "First." in out and "Last." in out and "[Removed by VIDHI" in out


@pytest.mark.parametrize("sentence", [
    "The Supreme Court laid down guidelines in 1997.",
    "He paid Rs 5,000 within 3 days.",  # a time with no legal step
    "The firm has 12 years of experience in appeals.",
])
def test_ordinary_sentences_and_document_facts_are_left_alone(sentence):
    assert strip_unverified_deadlines(sentence) == (sentence, 0)


def ask_general(c, text):
    mid, title = new_matter(c, "Honesty")
    stub("research", answer(text, []), contains=title)
    r = c.post("/research", json={"question": f"Question about a rule. {title}", "matter_id": mid, "mode": "MATTER"})
    assert r.status_code == 200, r.text
    return r.json(), title


def test_the_answer_text_itself_says_it_is_unchecked_and_a_stated_deadline_is_removed(user_a):
    res, _ = ask_general(user_a, "The complaint must be filed within 30 days of the notice period ending. Other words stay.")
    assert res["answer"].startswith("Not checked against any source")
    assert "within 30 days" not in res["answer"] and DEADLINE_NOTE in res["answer"] and "Other words stay." in res["answer"]


def test_a_plain_answer_without_a_deadline_gets_the_unchecked_line_but_no_deadline_note(user_a):
    res, _ = ask_general(user_a, "The court gave directions about procedure.")
    assert res["answer"].startswith("Not checked against any source") and DEADLINE_NOTE not in res["answer"]


def test_the_model_is_told_to_say_it_cannot_confirm_a_section_or_case_it_cannot_place(user_a):
    _, title = ask_general(user_a, "Fine.")
    (prompt,) = ai_prompts(title, "research")
    assert "I cannot verify this from the materials provided" in prompt and "Never state a legal time limit" in prompt


def test_case_name_fragments_are_not_listed_as_unverified_references(user_a):
    res, _ = ask_general(user_a, "Section 377 and Article 356 were discussed in Navtej v Union and Bommai v State of Karnataka.")
    assert not any(r.lower().startswith(("v union", "v state", "v.")) for r in res["unverified_references"])


def test_a_failed_ai_call_does_not_use_up_a_free_daily_request(user_a):
    """Found by the feature walk: a 502 'AI busy' still cost one of the five free requests a day. Seven failures in a row must leave the allowance untouched."""
    from tests.conftest import set_plan

    set_plan(user_a, "FREE")
    mid, title = new_matter(user_a, "Refund")
    for i in range(7):
        stub("research", "__FAIL__", contains=title)
        r = user_a.post("/research", json={"question": f"Anything? {title} {i}", "matter_id": mid, "mode": "MATTER"})
        assert r.status_code == 502, (i, r.status_code, r.text[:120])
    stub("research", answer("A real answer.", []), contains=title)
    ok = user_a.post("/research", json={"question": f"Last try {title}", "matter_id": mid, "mode": "MATTER"})
    assert ok.status_code == 200, ok.text[:200]  # still allowed: the failures were given back


def _factual_claim_reply(text, quote):
    return {"text": text, "claim_kind": "FACTUAL", "supports": "YES", "citations": [{"source": "MATTER_DOCUMENT", "ref": "DOC-01", "page": 1, "quote": quote}]}


def test_a_factual_label_does_not_let_a_legal_assertion_through_on_a_quote_that_never_mentions_the_law(user_a):
    """The model labelled a statement about what the law requires as FACTUAL and backed it with a matter quote that says nothing of any section: it must not come out VERIFIED."""
    from tests.conftest import upload

    mid, title = new_matter(user_a, "Label")
    upload(user_a, mid, "lease.txt", f"The tenant shall give two months notice before leaving. {title}")
    legal_looking = _factual_claim_reply("Section 106 requires two months notice before a tenant leaves.", "The tenant shall give two months notice before leaving.")
    stub("research", answer("Two months.", [legal_looking]), contains=title)
    res = user_a.post("/research", json={"question": f"Notice? {title}", "matter_id": mid, "mode": "MATTER"}).json()
    assert res["claims"][0]["claim_kind"] == "LEGAL" and res["claims"][0]["verification_status"] != "VERIFIED"


def test_a_document_that_itself_names_the_section_keeps_its_factual_claim(user_a):
    from tests.conftest import upload

    mid, title = new_matter(user_a, "Label2")
    upload(user_a, mid, "lease2.txt", f"This lease is made under Section 106 and the tenant shall give two months notice. {title}")
    fact = _factual_claim_reply("The lease says it is made under Section 106.", "This lease is made under Section 106")
    stub("research", answer("As stated.", [fact]), contains=title)
    res = user_a.post("/research", json={"question": f"What does it say? {title}", "matter_id": mid, "mode": "MATTER"}).json()
    assert res["claims"][0]["claim_kind"] == "FACTUAL"


def test_a_document_reference_protects_a_period_only_if_the_document_contains_it():
    """Found by the code review: adding '(DOC-1)' to a sentence used to be a way round the deadline rule."""
    sentence = "The notice must be sent in 30 days (DOC-1)."
    assert strip_unverified_deadlines(sentence)[1] == 1  # no evidence: removed
    assert strip_unverified_deadlines(sentence, "The lease says notice in 30 days.")[1] == 0  # the matter's own text has it: kept
    assert strip_unverified_deadlines(sentence, "The lease says nothing about notice.")[1] == 1  # the document does not have it: removed
    assert strip_unverified_deadlines("The notice was sent within 15 days (DOC-02).", "sent on 3 May")[1] == 1

