"""Phase 10: the legal-reasoning workflow through the real API with a scripted model. Rules under test: law comes only from the verified library; a reference the library did not
supply is removed; only live jurisdictions are analysed; status is never better than PARTIALLY_VERIFIED and current validity is never claimed; books and philosophy are context only;
and the existing citation verifier still refuses an invented citation (regression)."""

import uuid
import pytest
from datetime import datetime, timezone

from lib.library import norm_citation, sha256_text
from tests.conftest import mongo, stub


MINE: list[str] = []  # the entries THIS worker's current test made (workers run in parallel: a test must only remove its own rows, not another test's)


@pytest.fixture(autouse=True)
def _remove_fixture_law():
    """The library must look empty to every other test, so the entries made here are deleted as soon as the test ends."""
    MINE.clear()
    yield
    mongo().library_entries.delete_many({"origin": "test-fixture", "id": {"$in": list(MINE)}})


def seed(kind="STATUTE_SECTION", jurisdiction="IN"):
    """One VERIFIED library entry with invented text and a unique word, inserted directly (the library ships empty)."""
    tag = uuid.uuid4().hex[:10]
    word = f"zorblax{tag}"
    text = f"{word} qzx{tag} wvu{tag} jkl{tag}"  # made only of nonsense words: ordinary words would make this entry match other tests' questions
    cit = f"{word.capitalize()} Rules 7"
    mongo().library_entries.insert_one({"id": f"fixture-{tag}", "jurisdiction": jurisdiction, "citation": cit, "aliases": [], "keys": [norm_citation(cit)], "kind": kind, "title": "", "text": text,
                                      "text_norm": text.lower(), "text_sha256": sha256_text(text), "source_name": "Invented fixture", "source_url": "https://example.invalid/x", "version": "fixture v1",
                                      "verified_by": "Fixture Reviewer", "verified_on": "2026-10-23", "status": "VERIFIED", "origin": "test-fixture", "synced_at": datetime.now(timezone.utc)})
    MINE.append(f"fixture-{tag}")
    return word, cit, f"fixture-{tag}"


def reply(**kw):
    base = {"issue": "Whether notice was needed.", "jurisdiction_stated": "India", "facts_given": ["A notice was not sent."], "missing_evidence": ["The agreement itself."],
            "legal_questions": ["Was written notice required?"], "factual_disputes": ["Whether notice was sent."], "arguments": [], "distinctions_and_exceptions": [],
            "uncertainty": ["The agreement is not seen."], "conflicting_authorities": [], "areas_to_look_up": ["notice requirements"], "confidence": "high"}
    base.update(kw)
    return base


def ask(c, word, **extra):
    return c.post("/legal-reasoning", json={"question": f"{word} zq{uuid.uuid4().hex[:8]}", **extra})


def test_only_live_jurisdictions_are_analysed(user_a):
    for code in ("AE", "US", "XX"):
        r = user_a.post("/legal-reasoning", json={"question": "Is a notice needed before ending this arrangement?", "jurisdiction": code})
        assert r.status_code == 422 and "does not cover" in r.json()["detail"]


def test_with_no_library_entry_nothing_is_verified_and_the_answer_says_so(user_a):
    word = f"nolaw{uuid.uuid4().hex[:10]}"
    stub("research", reply(arguments=[{"side": "for", "point": "Notice was probably needed.", "library_ids": ["L1"]}]), contains=word)
    b = ask(user_a, word).json()
    assert b["verification"]["status"] == "UNSUPPORTED" and b["verification"]["complete"] is False and b["confidence"] == "low"
    assert b["source_note"] and b["library_entries"] == [] and b["arguments"][0]["library_ids"] == [] and b["arguments"][0]["supported_by_library"] is False
    assert b["jurisdiction"] == "IN" and [t["tier"] for t in b["authority_hierarchy"]][0] == "constitution" and b["authority_hierarchy"][-1]["tier"] == "context"
    assert any("amendments" in x for x in b["limits"])


def test_a_library_entry_is_shown_with_its_version_and_reviewer_and_status_stays_partial(user_a):
    word, cit, lid = seed()
    stub("research", reply(arguments=[{"side": "for", "point": f"{cit} requires written notice.", "library_ids": ["L1", "L9"]},
                                       {"side": "against", "point": "The agreement may exclude it.", "library_ids": []}], confidence="medium"), contains=word)
    b = ask(user_a, word).json()
    e = b["library_entries"][0]
    assert e["library_id"] == lid and e["tier"] == "legislation" and e["version"] == "fixture v1" and e["verified_by"] == "Fixture Reviewer" and e["authority_level"] == "PRIMARY"
    assert b["arguments"][0]["library_ids"] == ["L1"] and b["arguments"][0]["supported_by_library"] and b["verification"]["citations_to_unknown_entries_dropped"] == 1
    assert b["verification"]["status"] == "UNSUPPORTED"  # the second argument has no library support, so the whole answer is not called supported
    assert b["verification"]["complete"] is False and "current validity is not confirmed" in b["verification"]["note"] and b["confidence"] == "low"
    assert cit in b["arguments"][0]["point"]  # a reference that IS in the library is kept


def test_all_arguments_supported_gives_partially_verified_never_verified(user_a):
    word, cit, _ = seed()
    stub("research", reply(arguments=[{"side": "for", "point": f"{cit} requires written notice.", "library_ids": ["L1"]}], confidence="medium"), contains=word)
    b = ask(user_a, word).json()
    assert b["verification"]["status"] == "PARTIALLY_VERIFIED" and b["verification"]["complete"] is False and b["confidence"] == "medium"


def test_a_reference_the_library_did_not_supply_is_removed_and_listed(user_a):
    word, cit, _ = seed()
    stub("research", reply(uncertainty=["Section 138 of the Negotiable Instruments Act may apply here.", "The facts are incomplete."],
                           arguments=[{"side": "for", "point": f"Under {cit} written notice is needed. See also Sharma v. Verma.", "library_ids": ["L1"]}]), contains=word)
    b = ask(user_a, word).json()
    assert [r["rule"] for r in b["removed_by_vidhi"]] and all(r["rule"] == "citation_not_in_library" for r in b["removed_by_vidhi"])
    refs = " ".join(r["reference"] for r in b["removed_by_vidhi"])
    assert "Section 138" in refs or "Negotiable" in refs
    assert "Section 138" not in " ".join(b["uncertainty"]) and "The facts are incomplete." in b["uncertainty"] and "Sharma v" not in b["arguments"][0]["point"]
    assert b["confidence"] == "low"


def test_a_case_is_never_called_good_law_and_its_court_is_not_guessed(user_a):
    word, cit, _ = seed(kind="CASE")
    stub("research", reply(arguments=[{"side": "for", "point": f"{cit} discusses notice.", "library_ids": ["L1"]}]), contains=word)
    b = ask(user_a, word).json()
    assert b["library_entries"][0]["tier"] == "judgment_court_not_recorded" and b["case_note"] and "good law" in b["case_note"]


def test_an_entry_from_another_jurisdiction_is_not_used(user_a):
    word, _, _ = seed(jurisdiction="UK")
    stub("research", reply(), contains=word)
    b = ask(user_a, word).json()
    assert b["library_entries"] == [] and b["verification"]["status"] == "UNSUPPORTED"


def test_an_argument_resting_on_philosophy_alone_is_not_supported(user_a):
    word = f"nolaw{uuid.uuid4().hex[:10]}"
    stub("research", reply(arguments=[{"side": "for", "point": "Hobbes would say the contract binds.", "library_ids": []}]), contains=word)
    b = ask(user_a, word).json()
    assert b["arguments"][0]["supported_by_library"] is False and b["verification"]["arguments_without_library_support"] == 1


def test_an_empty_model_reply_is_an_error(user_a):
    word = f"nolaw{uuid.uuid4().hex[:10]}"
    stub("research", reply(issue=""), contains=word)
    assert ask(user_a, word).status_code == 502


def test_regression_the_citation_verifier_still_refuses_an_invented_citation(user_a):
    r = user_a.post("/verify-citation", json={"citation": f"Section 4{uuid.uuid4().int % 900} of the Imaginary Contracts Act 1850"})
    assert r.status_code == 200 and r.json()["verification_status"] != "VERIFIED" and r.json()["library_id"] is None


def test_a_reasoning_answer_records_the_version_and_hash_of_each_library_entry_it_was_given(user_a):
    word, cit, lid = seed()
    stub("research", reply(arguments=[{"side": "for", "point": f"{cit} requires written notice.", "library_ids": ["L1"]}]), contains=word)
    b = ask(user_a, word).json()
    (s,) = b["source_versions"]
    tag = lid[len("fixture-"):]
    assert s["source_kind"] == "verified_library" and s["id"] == lid and s["version"] == "fixture v1" and s["source_link"] == "https://example.invalid/x"
    assert s["reviewed_by"] == "Fixture Reviewer" and s["checked_on"] == "2026-10-23" and s["status"] == "VERIFIED" and s["text_sha256"] == sha256_text(f"{word} qzx{tag} wvu{tag} jkl{tag}")


def test_a_reasoning_answer_with_no_library_entry_records_no_source(user_a):
    word = f"nolaw{uuid.uuid4().hex[:10]}"
    stub("research", reply(), contains=word)
    assert ask(user_a, word).json()["source_versions"] == []  # nothing was used, so nothing is claimed
