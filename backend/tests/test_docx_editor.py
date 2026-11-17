"""Word editor: paragraphs of an uploaded .docx are listed, edits are saved as a NEW document, the original never changes, other files are refused, other organisations see nothing."""

import io

import docx

from tests.conftest import new_matter, upload, verify_email


def make_docx(paras: list[str]) -> bytes:
    d = docx.Document()
    for t in paras:
        d.add_paragraph(t)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_edits_make_a_new_document_and_leave_the_original_alone(user_a):
    verify_email(user_a)
    mid, _ = new_matter(user_a, "Word edit")
    d = upload(user_a, mid, "notice.docx", make_docx(["First paragraph about rent.", "Second paragraph about the date."]))
    r = user_a.get(f"/documents/{d['id']}/paragraphs")
    assert r.status_code == 200 and r.json()["paragraphs"] == ["First paragraph about rent.", "Second paragraph about the date."]
    out = user_a.post(f"/documents/{d['id']}/edit-copy", json={"edits": [{"index": 1, "text": "Second paragraph about the new date."}]})
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["filename"] == "notice (edited).docx" and body["changed"] == 1 and body["id"] != d["id"]
    assert user_a.get(f"/documents/{d['id']}/paragraphs").json()["paragraphs"][1] == "Second paragraph about the date."  # original untouched
    assert user_a.get(f"/documents/{body['id']}/paragraphs").json()["paragraphs"] == ["First paragraph about rent.", "Second paragraph about the new date."]
    assert len(user_a.get(f"/matters/{mid}/documents").json()) == 2


def test_no_change_bad_index_and_non_word_files_are_refused(user_a):
    verify_email(user_a)
    mid, _ = new_matter(user_a, "Word refuse")
    d = upload(user_a, mid, "a.docx", make_docx(["Only paragraph."]))
    assert user_a.post(f"/documents/{d['id']}/edit-copy", json={"edits": [{"index": 0, "text": "Only paragraph."}]}).status_code == 422
    assert user_a.post(f"/documents/{d['id']}/edit-copy", json={"edits": [{"index": 5, "text": "x"}]}).status_code == 422
    t = upload(user_a, mid, "n.txt", "plain text note")
    assert user_a.get(f"/documents/{t['id']}/paragraphs").status_code == 422


def test_another_organisation_cannot_read_or_edit(user_a, user_b):
    verify_email(user_a)
    verify_email(user_b)
    mid, _ = new_matter(user_a, "Word tenancy")
    d = upload(user_a, mid, "private.docx", make_docx(["Secret paragraph."]))
    assert user_b.get(f"/documents/{d['id']}/paragraphs").status_code == 404
    assert user_b.post(f"/documents/{d['id']}/edit-copy", json={"edits": [{"index": 0, "text": "changed"}]}).status_code == 404
