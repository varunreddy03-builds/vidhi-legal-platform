"""Rare illustrations: off by default, Pro only, capped per month, labelled, refused for anything that could pass as evidence."""

import gridfs
import pytest

from lib import crypto, imagegen
from tests.conftest import mongo, set_plan

GOOD = "a simple timeline diagram showing three steps from start to finish"


def make(c, prompt=GOOD):
    return c.post("/images/generate", json={"prompt": prompt})


def test_status_for_pro_and_free(user_a):
    assert user_a.get("/images/status").json() == {"enabled": True, "pro_only": True, "cap": 3, "remaining": 3}
    set_plan(user_a, "FREE")
    assert user_a.get("/images/status").json()["enabled"] is False


def test_a_picture_is_made_stored_encrypted_labelled_and_fetched(user_a):
    r = make(user_a)
    assert r.status_code == 200 and r.json()["remaining"] == 2 and "not evidence" in r.json()["label"]
    img = user_a.get(f"/images/{r.json()['id']}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.headers["x-ai-generated"] == "true" and img.content.startswith(b"\x89PNG")
    assert img.headers["cache-control"] == "private, no-store"
    row = mongo().generated_images.find_one({"id": r.json()["id"]})
    if crypto.enabled():
        assert gridfs.GridFS(mongo()).get(row["gridfs_id"]).read().startswith(crypto.MAGIC)
    assert mongo().audit_events.find_one({"operation": "IMAGE_GENERATED", "detail": r.json()["id"]})


def test_the_free_plan_is_asked_to_upgrade(user_a):
    set_plan(user_a, "FREE")
    assert make(user_a).status_code == 402


@pytest.mark.parametrize("prompt", [
    "a photo of the debtor outside his shop", "a realistic portrait of a judge", "a copy of his signature on the agreement", "an Aadhaar card with my details",
    "a fake receipt showing payment", "court order stamped and sealed", "एक तस्वीर जिसमें उसका हस्ताक्षर हो", "a bank statement showing the payment",
])
def test_anything_that_could_pass_as_evidence_or_show_a_real_person_is_refused(user_a, prompt):
    r = make(user_a, prompt)
    assert r.status_code == 422 and "evidence" in r.json()["detail"]
    assert user_a.get("/images/status").json()["remaining"] == 3  # a refusal costs nothing


def test_the_monthly_cap_holds(user_a):
    assert [make(user_a).status_code for _ in range(4)] == [200, 200, 200, 429]
    assert user_a.get("/images/status").json()["remaining"] == 0
    assert "used its 3 illustrations" in make(user_a).json()["detail"]


def test_the_cap_is_per_organisation_and_pictures_are_private(user_a, user_b):
    made = make(user_a).json()["id"]
    assert user_b.get(f"/images/{made}").status_code == 404
    assert user_b.get("/images/status").json()["remaining"] == 3


def test_short_or_huge_prompts_are_rejected(user_a):
    assert make(user_a, "ab").status_code == 422
    assert make(user_a, "x " * 400).status_code == 422


def test_needs_sign_in(anon):
    assert anon.post("/images/generate", json={"prompt": GOOD}).status_code in (401, 403)
    assert anon.get("/images/status").status_code in (401, 403)


def test_erasing_the_organisation_removes_its_pictures(user_a):
    made = make(user_a).json()["id"]
    gid = mongo().generated_images.find_one({"id": made})["gridfs_id"]
    r = user_a.request("DELETE", "/org", json={"password": user_a.password, "organization_name": user_a.user["organization_name"]})
    assert r.status_code == 200
    assert mongo().generated_images.count_documents({"id": made}) == 0
    assert not gridfs.GridFS(mongo()).exists(gid)


def test_the_prompt_is_wrapped_to_keep_it_an_illustration():
    w = imagegen.wrap("two arrows between boxes")
    assert "No text" in w and "no real people" in w and "two arrows between boxes" in w
    assert imagegen.refusal(GOOD) is None and imagegen.refusal("a clock and a calendar") is None
    assert imagegen.refusal("willing helpers") is None  # whole words only

def test_documents_are_refused_even_inside_a_harmless_sentence():
    assert imagegen.refusal("a diagram from invoice to payment") is not None  # stricter on purpose: a document word is refused
    assert imagegen.refusal("a tick mark and a check mark") is None
