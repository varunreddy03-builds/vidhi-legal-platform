"""Search must work in Indian languages, and an Indian-language question must still find English law."""

import asyncio

import pytest

from lib import ai, matter_context, query_lang, text
from tests.conftest import ai_prompts, answer, new_matter, stub, upload

HINDI = "किरायेदार ने तीन महीने से किराया नहीं दिया है और मकान मालिक ने नोटिस भेजा है"
TAMIL = "வாடகை ஒப்பந்தம் மூன்று மாதங்களாக வாடகை செலுத்தப்படவில்லை"
TELUGU = "అద్దె ఒప్పందం ప్రకారం మూడు నెలల అద్దె చెల్లించలేదు"


def test_words_in_indian_scripts_are_found():
    for sample in (HINDI, TAMIL, TELUGU, "ভাড়াটিয়া তিন মাসের ভাড়া দেয়নি", "ભાડૂતે ત્રણ મહિનાનું ભાડું ચૂકવ્યું નથી", "ਕਿਰਾਏਦਾਰ ਨੇ ਕਿਰਾਇਆ ਨਹੀਂ ਦਿੱਤਾ"):
        assert text.tokens(sample), sample


def test_whole_words_keep_their_vowel_signs():
    assert "किराया" in text.tokens(HINDI) and "मकान" in text.tokens(HINDI)  # not split at the combining vowel signs
    assert "வாடகை" in text.tokens(TAMIL)


def test_function_words_are_dropped_and_english_still_works():
    assert "है" not in text.tokens(HINDI) and "और" not in text.tokens(HINDI)
    assert text.tokens("The Section 138 notice was sent to the debtor") == ["section", "138", "notice", "sent", "debtor"]
    assert text.tokens("") == [] and text.tokens("   ") == []


def test_invisible_characters_do_not_split_words():
    assert text.tokens("kir\u200baya agreement") == ["kiraya", "agreement"]


def test_language_detection_for_searching():
    assert text.mostly_latin("My tenant has not paid rent") and text.mostly_latin("")
    assert not text.mostly_latin(HINDI) and not text.mostly_latin(TAMIL)
    assert text.mostly_latin("Section 138 ka notice kaise bheje")  # Hinglish in Latin letters is searched as written


def test_the_right_hindi_passage_is_chosen_when_documents_exceed_the_budget():
    unrelated = "मौसम आज बहुत अच्छा है और बाजार में भीड़ है। " * 30
    relevant = "किरायेदार ने तीन महीने का किराया नहीं दिया। मकान मालिक ने कानूनी नोटिस भेजा। " * 3
    corpus = matter_context.build_corpus([{"id": "a", "filename": "a.txt", "pages": [unrelated]}, {"id": "b", "filename": "b.txt", "pages": [unrelated, relevant]}])
    shown, cov = matter_context.select_context("किरायेदार किराया नोटिस", corpus, budget=1200)
    assert "मकान मालिक ने कानूनी नोटिस भेजा" in shown and not cov["complete"]


def test_library_search_works_on_indian_script_tokens():
    from lib.library import _tokens

    assert _tokens(HINDI) and "किराया" in _tokens(HINDI)


# ---- searching English law with a question in another language ----
def run(c):
    return asyncio.run(c)


def test_an_english_question_is_never_sent_for_translation(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("must not be called")

    monkeypatch.setattr(ai, "ask_json", boom)
    assert run(query_lang.english_query("What happens if a tenant does not pay rent?", "s")) == "What happens if a tenant does not pay rent?"


def test_a_hindi_question_is_translated_for_searching_only(monkeypatch):
    seen = {}

    async def fake(session_id, prompt, schema, **kw):
        seen.update(prompt=prompt, **kw)
        return {"english": "tenant has not paid rent for three months"}

    monkeypatch.setattr(ai, "ask_json", fake)
    assert run(query_lang.english_query(HINDI, "s")) == "tenant has not paid rent for three months"
    assert seen["tier"] == "free" and seen["purpose"] == "translate-query" and "Do not answer it" in seen["prompt"]


@pytest.mark.parametrize("reply", [Exception("down"), {"english": ""}, {"nothing": 1}])
def test_if_translation_fails_the_original_question_is_used(monkeypatch, reply):
    async def fake(*a, **k):
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(ai, "ask_json", fake)
    assert run(query_lang.english_query(HINDI, "s")) == HINDI


def test_a_hindi_question_finds_the_english_law_it_needs(user_a):
    mid, title = new_matter(user_a, "Hindi")
    upload(user_a, mid, "note.txt", "A short note about the matter. " + title)
    question = f"मैंने एक विजेट उधार लिया था ९९१ {title}, क्या मुझे उसे वापस करना होगा?"
    stub("translate-query", {"english": "must a person who borrows a widget return it"}, contains="९९१")
    stub("research", answer("उत्तर।"), contains=title)
    r = user_a.post("/research", json={"question": question, "matter_id": mid, "mode": "MATTER", "language": "hi"})
    assert r.status_code == 200
    (prompt,) = ai_prompts(title, "research")
    assert "test-widget-1" in prompt  # the English provision was found through the English version of the question
    assert "९९१" in prompt  # while the model is still asked the ORIGINAL question
    assert "must a person who borrows" not in prompt  # the translation is for searching only, not shown to the model


def test_without_the_translation_a_hindi_question_finds_nothing_in_english_law(user_a):
    mid, title = new_matter(user_a, "Hindi")
    upload(user_a, mid, "note.txt", "A short note. " + title)
    stub("translate-query", "__FAIL__", contains="९९२")
    stub("research", answer("उत्तर।"), contains=title)
    assert user_a.post("/research", json={"question": f"क्या विजेट वापस करना होगा ९९२ {title}?", "matter_id": mid, "mode": "MATTER"}).status_code == 200
    (prompt,) = ai_prompts(title, "research")
    assert "test-widget-1" not in prompt and "none are available" in prompt  # honest fallback: no law is offered, so no claim can be verified

def test_an_answer_in_another_language_says_its_legal_terms_are_unreviewed_and_keeps_english_terms(user_a):
    mid, title = new_matter(user_a, "Terms")
    upload(user_a, mid, "note.txt", "A short note about the matter. " + title)
    stub("research", answer("उत्तर।"), contains=title)
    r = user_a.post("/research", json={"question": f"क्या यह वैध है? {title}", "matter_id": mid, "mode": "MATTER", "language": "hi"})
    assert r.status_code == 200
    (prompt,) = ai_prompts(title, "research")
    assert "put the English term in brackets" in prompt and "Never translate the names of Acts" in prompt
    assert r.json()["answer"].count("UNREVIEWED: this answer was written by a program") == 1


def test_an_english_answer_has_no_unreviewed_note_and_no_term_rule(user_a):
    mid, title = new_matter(user_a, "Terms en")
    upload(user_a, mid, "note.txt", "A short note about the matter. " + title)
    stub("research", answer("Answer."), contains=title)
    r = user_a.post("/research", json={"question": f"Is this valid? {title}", "matter_id": mid, "mode": "MATTER"})
    assert r.status_code == 200
    (prompt,) = ai_prompts(title, "research")
    assert "LEGAL TERMS" not in prompt and "UNREVIEWED: this answer" not in r.json()["answer"]


TELUGU = "అద్దెదారు మూడు నెలలుగా అద్దె చెల్లించలేదు, ఏమి చేయాలి?"
TAMIL = "குடியிருப்பவர் மூன்று மாதமாக வாடகை செலுத்தவில்லை, என்ன செய்வது?"


@pytest.mark.parametrize("question", [TELUGU, TAMIL])
def test_a_telugu_or_tamil_question_is_translated_for_searching_only_and_falls_back_to_the_original(monkeypatch, question):
    seen = {}

    async def ok(session_id, prompt, schema, **kw):
        seen.update(prompt=prompt, **kw)
        return {"english": "tenant has not paid rent for three months"}

    monkeypatch.setattr(ai, "ask_json", ok)
    assert run(query_lang.english_query(question, "s")) == "tenant has not paid rent for three months"
    assert seen["tier"] == "free" and seen["purpose"] == "translate-query" and "Do not answer it" in seen["prompt"]

    async def down(*a, **k):
        raise Exception("down")

    monkeypatch.setattr(ai, "ask_json", down)
    assert run(query_lang.english_query(question, "s")) == question  # the original words are searched, which finds nothing in English law: "could not check", never a guess
