"""Comparing two documents: added, deleted and changed words, on the text read; only your own organisation's documents; nothing changed by it."""
import pytest

from lib import doc_diff
from tests.conftest import mongo, new_matter, upload  # noqa: F401
from tests.test_admin import admin  # noqa: F401
from tests.conftest import user_a  # noqa: F401


def ops(result, op):
    return " ".join(s["text"].strip() for s in result["segments"] if s["op"] == op)


def test_added_deleted_and_changed_words_are_found_whole_words_only():
    r = doc_diff.compare("The tenant shall pay rent of Rs 10,000 monthly.", "The tenant shall pay rent of Rs 12,000 monthly and maintenance.")
    assert "10,000" in ops(r, "delete") and "12,000" in ops(r, "insert") and "maintenance." in ops(r, "insert")
    assert not r["identical"] and r["counts"]["added_words"] >= 3 and r["counts"]["deleted_words"] >= 1
    assert "".join(s["text"] for s in r["segments"] if s["op"] != "insert") == "The tenant shall pay rent of Rs 10,000 monthly."  # the first text can be rebuilt
    assert "".join(s["text"] for s in r["segments"] if s["op"] != "delete") == "The tenant shall pay rent of Rs 12,000 monthly and maintenance."  # so can the second


def test_identical_and_empty_texts():
    assert doc_diff.compare("same words", "same words")["identical"] is True
    assert doc_diff.compare("", "")["segments"] == []
    only = doc_diff.compare("", "all new text")
    assert ops(only, "insert") == "all new text" and ops(only, "delete") == ""


def test_a_very_long_document_is_refused_not_run():
    with pytest.raises(ValueError):
        doc_diff.compare("a " * (doc_diff.MAX_CHARS // 2 + 10), "b")


def test_unicode_words_are_kept_whole():
    r = doc_diff.compare("माननीय न्यायालय के समक्ष", "माननीय उच्च न्यायालय के समक्ष")
    assert ops(r, "insert") == "उच्च" and ops(r, "delete") == ""


def make(admin_client, name, text):
    mid, _ = new_matter(admin_client, "Compare")
    return upload(admin_client, mid, name, text)["id"]


def test_the_route_compares_two_documents_and_changes_nothing(admin):  # noqa: F811
    a = make(admin, "v1.txt", "Payment is due within thirty days of the invoice.")
    b = make(admin, "v2.txt", "Payment is due within forty five days of the invoice.")
    before = admin.get(f"/documents/{a}").json()
    r = admin.post("/documents/compare", json={"first_id": a, "second_id": b})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["first"]["filename"] == "v1.txt" and body["second"]["filename"] == "v2.txt" and not body["identical"]
    assert ops(body, "delete") == "thirty" and ops(body, "insert") == "forty five"
    assert admin.get(f"/documents/{a}").json() == before


def test_the_same_document_twice_or_a_missing_one_is_refused(admin):  # noqa: F811
    a = make(admin, "x.txt", "some words here")
    assert admin.post("/documents/compare", json={"first_id": a, "second_id": a}).status_code == 422
    assert admin.post("/documents/compare", json={"first_id": a, "second_id": "nope"}).status_code == 404


def test_a_document_without_text_cannot_be_compared(admin):  # noqa: F811
    a = make(admin, "x.txt", "some words here")
    mid, _ = new_matter(admin, "Empty")
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")
    r = admin.post(f"/matters/{mid}/documents", files={"file": ("pic.png", png)})
    assert r.status_code == 200
    pid = r.json()["id"]
    mongo().documents.update_one({"id": pid}, {"$set": {"pages": []}})
    got = admin.post("/documents/compare", json={"first_id": a, "second_id": pid})
    assert got.status_code == 422 and "no readable text" in got.json()["detail"]


def test_another_organisation_cannot_compare_my_documents(admin, user_a):  # noqa: F811
    a = make(admin, "mine1.txt", "confidential words one")
    b = make(admin, "mine2.txt", "confidential words two")
    assert user_a.post("/documents/compare", json={"first_id": a, "second_id": b}).status_code == 404


def test_low_confidence_reading_is_carried_into_the_comparison_as_a_warning(admin):  # noqa: F811
    a = make(admin, "scan1.txt", "alpha beta gamma")
    b = make(admin, "scan2.txt", "alpha beta delta")
    mongo().documents.update_one({"id": a}, {"$set": {"uncertain_pages": [1], "reading_note": "Read from a scan."}})
    body = admin.post("/documents/compare", json={"first_id": a, "second_id": b}).json()
    assert any("Read from a scan" in w for w in body["warnings"]) and any("low confidence" in w for w in body["warnings"])
