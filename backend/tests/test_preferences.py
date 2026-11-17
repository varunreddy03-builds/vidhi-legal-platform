"""Display language and theme follow the person to other devices; only the 22 scheduled languages (and English) are accepted."""

import pytest

CODES = ["en", "as", "bn", "brx", "doi", "gu", "hi", "kn", "ks", "kok", "mai", "ml", "mni", "mr", "ne", "or", "pa", "sa", "sat", "sd", "ta", "te", "ur"]


def test_there_are_22_languages_plus_english():
    assert len(CODES) == 23 and len(set(CODES)) == 23


def test_language_and_theme_are_saved(user_a):
    r = user_a.patch("/auth/preferences", json={"language": "ta", "theme": "light"})
    assert r.status_code == 200, r.text
    me = user_a.get("/auth/me").json()
    assert me["language"] == "ta" and me["theme"] == "light"


@pytest.mark.parametrize("code", CODES)
def test_each_listed_language_is_accepted(user_a, code):
    assert user_a.patch("/auth/preferences", json={"language": code}).status_code == 200


def test_unknown_values_are_refused(user_a):
    assert user_a.patch("/auth/preferences", json={"language": "xx"}).status_code == 422
    assert user_a.patch("/auth/preferences", json={"theme": "purple"}).status_code == 422


def test_needs_sign_in(anon):
    assert anon.patch("/auth/preferences", json={"language": "hi"}).status_code in (401, 403)


def test_one_persons_choice_does_not_change_anothers(user_a, user_b):
    user_a.patch("/auth/preferences", json={"language": "bn"})
    assert user_b.get("/auth/me").json()["language"] in (None, "en")


def test_research_answers_in_the_chosen_language(user_a):
    from tests.conftest import ai_prompts, answer, stub

    marker = "language-marker-hindi-question"
    stub("research", answer("उत्तर"), contains=marker)
    assert user_a.post("/research", json={"question": marker, "language": "hi"}).status_code == 200
    (prompt,) = ai_prompts(marker, "research")
    assert "in Hindi" in prompt and "EXACTLY" in prompt

    marker2 = "language-marker-english-question"
    stub("research", answer("Answer"), contains=marker2)
    assert user_a.post("/research", json={"question": marker2}).status_code == 200
    (prompt2,) = ai_prompts(marker2, "research")
    assert "LANGUAGE:" not in prompt2


def test_unknown_research_language_falls_back_to_english(user_a):
    from tests.conftest import ai_prompts, answer, stub

    marker = "language-marker-unknown-lang"
    stub("research", answer("Answer"), contains=marker)
    assert user_a.post("/research", json={"question": marker, "language": "xx"}).status_code == 200
    (prompt,) = ai_prompts(marker, "research")
    assert "LANGUAGE:" not in prompt
