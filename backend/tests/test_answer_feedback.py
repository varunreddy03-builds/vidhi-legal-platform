"""Thumbs up or down on an answer: one vote per person per answer, private to the organisation."""


from tests.conftest import answer, mongo, new_matter, new_member, stub
from tests.test_truth_engine import research


def made_answer(c):
    mid, title = new_matter(c, "Feedback")
    stub("research", answer("An answer."), contains=title)
    return research(c, mid).json()["id"]


def test_a_vote_is_saved_and_can_be_changed(user_a):
    rid = made_answer(user_a)
    assert user_a.get(f"/research/{rid}/feedback").json() == {"rating": None, "comment": ""}
    assert user_a.put(f"/research/{rid}/feedback", json={"rating": "down", "comment": "  missed the second invoice  "}).json() == {"rating": "down", "comment": "missed the second invoice"}
    assert user_a.put(f"/research/{rid}/feedback", json={"rating": "up"}).status_code == 200
    assert user_a.get(f"/research/{rid}/feedback").json() == {"rating": "up", "comment": ""}
    assert mongo().answer_feedback.count_documents({"research_id": rid}) == 1  # replaced, not added


def test_each_person_has_their_own_vote(user_a):
    rid = made_answer(user_a)
    mongo().users.update_one({"id": user_a.user["id"]}, {"$set": {"email_verified": True}})  # inviting people needs a confirmed email
    colleague = new_member(user_a, "LAWYER")
    user_a.put(f"/research/{rid}/feedback", json={"rating": "up"})
    colleague.put(f"/research/{rid}/feedback", json={"rating": "down"})
    assert user_a.get(f"/research/{rid}/feedback").json()["rating"] == "up" and colleague.get(f"/research/{rid}/feedback").json()["rating"] == "down"
    assert mongo().answer_feedback.count_documents({"research_id": rid}) == 2


def test_only_valid_ratings_and_short_comments(user_a):
    rid = made_answer(user_a)
    assert user_a.put(f"/research/{rid}/feedback", json={"rating": "meh"}).status_code == 422
    assert user_a.put(f"/research/{rid}/feedback", json={"rating": "up", "comment": "x" * 501}).status_code == 422
    assert user_a.put(f"/research/{rid}/feedback", json={}).status_code == 422


def test_another_organisation_cannot_vote_on_or_read_an_answer(user_a, user_b):
    rid = made_answer(user_a)
    assert user_b.put(f"/research/{rid}/feedback", json={"rating": "down"}).status_code == 404
    assert user_b.get(f"/research/{rid}/feedback").status_code == 404
    assert mongo().answer_feedback.count_documents({"research_id": rid}) == 0


def test_needs_sign_in_and_a_real_answer(user_a, anon):
    rid = made_answer(user_a)
    assert anon.put(f"/research/{rid}/feedback", json={"rating": "up"}).status_code in (401, 403)
    assert user_a.put("/research/not-an-answer/feedback", json={"rating": "up"}).status_code == 404


def test_feedback_is_part_of_the_export_and_goes_with_the_organisation(user_a):
    rid = made_answer(user_a)
    user_a.put(f"/research/{rid}/feedback", json={"rating": "up", "comment": "good"})
    import io
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(user_a.get("/org/export").content))
    assert "good" in z.read("answer_feedback.json").decode()
    user_a.request("DELETE", "/org", json={"password": user_a.password, "organization_name": user_a.user["organization_name"]})
    assert mongo().answer_feedback.count_documents({"research_id": rid}) == 0