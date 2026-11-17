"""Phase 11: the audiovisual catalogue. Rules under test: exactly the 22 owner-listed titles, each with its year and an honest status (nothing obtained, nothing reviewed, no licensed transcript),
every entry labelled as story-not-evidence, exercises labelled fictional, films never in the knowledge library, and a film used as proof or precedent is removed from an analysis."""

import uuid

import pytest

from lib import films
from lib.analysis_guard import clean_text
from tests.conftest import stub

EXPECTED = [
    ("The Godfather", 1972), ("The Social Network", 2010), ("Nightcrawler", 2014), ("The Prestige", 2006), ("Drishyam", 2013),
    ("12 Angry Men", 1957), ("A Few Good Men", 1992), ("Arrival", 2016), ("The Big Short", 2015), ("Moneyball", 2011),
    ("Memento", 2000), ("Eternal Sunshine of the Spotless Mind", 2004), ("Ex Machina", 2014), ("Inside Out", 2015),
    ("Court", 2014), ("Jai Bhim", 2021), ("Section 375", 2019), ("Pink", 2016), ("My Cousin Vinny", 1992),
    ("The Matrix", 1999), ("Gattaca", 1997), ("Oppenheimer", 2023),
]


def test_the_catalogue_is_exactly_the_22_titles_in_the_owners_order_with_their_years():
    got = [(f["title"], f["year"]) for f in films.catalogue()["films"]]
    assert got == EXPECTED and films.check() == []


def test_every_entry_is_honest_about_what_was_obtained_and_labelled_as_a_story():
    for f in films.catalogue()["films"]:
        assert f["source_obtained"] is False and f["reviewed"] is False and f["rights_status"] == "in_copyright_assumed", f["title"]
        assert "none" in f["availability"]["transcript"] and f["subjects"] and f["themes"] and f["country_language"]
        assert "Not evidence" in f["label"] and f["real_events"]


def test_real_events_are_never_called_verified():
    real = {f["title"]: f["real_events"] for f in films.catalogue()["films"] if f["real_events"] != "fiction"}
    assert set(real) == {"The Social Network", "The Big Short", "Moneyball", "Jai Bhim", "Oppenheimer"}
    assert "not a verified account" in real["Jai Bhim"] and not any("verified account of" in v and "not" not in v for v in real.values())


def test_a_claim_of_a_source_or_a_review_without_naming_it_is_caught(monkeypatch):
    d = films._load()
    d["films"][0]["source_obtained"] = True
    d["films"][1]["reviewed"] = True
    monkeypatch.setattr(films, "_load", lambda: d)
    assert len(films.check()) == 2


def test_exercises_are_fictional_and_not_taken_from_any_film():
    ex = films.exercises()
    assert "FICTIONAL" in ex["label"] and len(ex["exercises"]) == 8
    titles = [t.lower() for t in films.titles() if len(t) > 6]
    for e in ex["exercises"]:
        assert e["scenario"].startswith("FICTIONAL SCENARIO") and e["questions"]
        assert not any(t in (e["scenario"] + e["title"]).lower() for t in titles)


@pytest.mark.parametrize("sentence", [
    "Jai Bhim proves that the police always abuse suspects.",
    "The court held in 12 Angry Men that a jury must be unanimous, so this is binding precedent.",
    "Section 375 (2019) establishes that consent can be implied, as a matter of law.",
])
def test_a_film_used_as_proof_or_precedent_is_removed_and_reported(sentence):
    text, flags = clean_text(f"Background first. {sentence} Closing line.")
    assert [f["rule"] for f in flags][-1] == "film_as_fact" or "film_as_fact" in [f["rule"] for f in flags]
    assert sentence not in text


@pytest.mark.parametrize("sentence", [
    "Jai Bhim is a drama that students sometimes discuss when talking about access to justice.",
    "The film Memento is often used to talk about unreliable notes; it is fiction and proves nothing about memory.",
    "The court held that the notice was invalid.",
    "Pink is a Hindi film from 2016.",
])
def test_discussing_a_film_as_a_story_is_left_alone(sentence):
    assert not [f for f in clean_text(sentence)[1] if f["rule"] == "film_as_fact"]


def test_routes_serve_the_catalogue_and_exercises_and_films_are_not_in_the_library(user_a):
    c = user_a.get("/knowledge/films").json()
    assert c["count"] == 22 and "never evidence" in c["note"] or "never" in c["note"]
    assert user_a.get("/knowledge/films/exercises").json()["exercises"][0]["id"] == "X1"
    nothing = user_a.get("/knowledge/search", params={"q": "The Godfather 1972 Drishyam Memento"}).json()
    assert all(h["kind"] != "film" for h in nothing["hits"])


def test_an_analysis_that_cites_a_film_as_precedent_has_that_sentence_removed(user_a):
    tag = uuid.uuid4().hex
    stub("research", {"summary": "Jai Bhim proves that courts always side with the weaker party.", "options": [], "assumptions": [], "alternative_explanations": [], "open_questions": [], "confidence": "high"}, contains=tag[:12])
    b = user_a.post("/analysis/reasoning", json={"question": f"zq{tag[:12]} zw{tag[12:24]} ze{tag[24:]}"}).json()
    assert "film_as_fact" in [r["rule"] for r in b["removed_by_vidhi"]] and "Jai Bhim" not in b["summary"]
