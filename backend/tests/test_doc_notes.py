"""Page notes on a document: kept with the document, seen by the firm, gone with the document, closed to other organisations."""
from tests.conftest import mongo, new_matter, upload  # noqa: F401
from tests.test_admin import admin  # noqa: F401
from tests.conftest import user_a  # noqa: F401


def doc(c, name="n.txt", text="Hearing on 12 March 2021."):
    mid, _ = new_matter(c, "Notes")
    return upload(c, mid, name, text)["id"], mid


def test_add_list_and_delete_a_note(admin):  # noqa: F811
    d, _ = doc(admin)
    r = admin.post(f"/documents/{d}/notes", json={"page": 1, "note": "  Check the date against the notice.  ", "quote": "12 March 2021"})
    assert r.status_code == 201, r.text
    n = r.json()
    assert n["note"] == "Check the date against the notice." and n["page"] == 1 and n["quote"] == "12 March 2021" and n["author"] and "organization_id" not in n
    assert [x["id"] for x in admin.get(f"/documents/{d}/notes").json()] == [n["id"]]
    assert admin.delete(f"/documents/{d}/notes/{n['id']}").status_code == 200
    assert admin.get(f"/documents/{d}/notes").json() == []
    assert admin.delete(f"/documents/{d}/notes/{n['id']}").status_code == 404


def test_bad_notes_are_refused(admin):  # noqa: F811
    d, _ = doc(admin)
    assert admin.post(f"/documents/{d}/notes", json={"page": 0, "note": "x"}).status_code == 422
    assert admin.post(f"/documents/{d}/notes", json={"page": 1, "note": ""}).status_code == 422
    assert admin.post(f"/documents/{d}/notes", json={"page": 1, "note": "   "}).status_code == 422
    assert admin.post(f"/documents/{d}/notes", json={"page": 1, "note": "n" * 2001}).status_code == 422
    assert admin.post(f"/documents/{d}/notes", json={"page": 99, "note": "beyond the end"}).status_code == 422


def test_notes_are_listed_in_page_order(admin):  # noqa: F811
    d, mid = doc(admin, "two.txt", "word " * 3000)  # more than one page of text
    pages = admin.get(f"/documents/{d}").json()["page_count"]
    assert pages >= 2
    admin.post(f"/documents/{d}/notes", json={"page": 2, "note": "second"})
    admin.post(f"/documents/{d}/notes", json={"page": 1, "note": "first"})
    assert [n["note"] for n in admin.get(f"/documents/{d}/notes").json()] == ["first", "second"]


def test_another_organisation_cannot_read_add_or_delete_notes(admin, user_a):  # noqa: F811
    d, _ = doc(admin)
    n = admin.post(f"/documents/{d}/notes", json={"page": 1, "note": "private remark"}).json()
    assert user_a.get(f"/documents/{d}/notes").status_code == 404
    assert user_a.post(f"/documents/{d}/notes", json={"page": 1, "note": "intruder"}).status_code == 404
    assert user_a.delete(f"/documents/{d}/notes/{n['id']}").status_code == 404
    assert len(admin.get(f"/documents/{d}/notes").json()) == 1


def test_notes_go_with_the_document(admin):  # noqa: F811
    d, _ = doc(admin)
    admin.post(f"/documents/{d}/notes", json={"page": 1, "note": "will vanish"})
    assert mongo().doc_notes.count_documents({"document_id": d}) == 1
    assert admin.delete(f"/documents/{d}").status_code == 200
    assert mongo().doc_notes.count_documents({"document_id": d}) == 0
