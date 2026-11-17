"""Word and PDF copies of a list of dates: the same words as the screen, the page rule stated in the file, and the route's privacy and audit trail."""

import io

from lib.datelist import export, report as rep

TEXT = "The loan was advanced on 01/06/2020. The cheque dated 31/02/2021 was returned. The notice was sent on 5th April 2021."


def built(kind="pdf"):
    return {"title": "Bundle 1", "source_file": "bundle.pdf", "created_at": "2026-10-28T10:00:00+00:00", **rep.build(["Filler.", TEXT], kind)}


def docx_text(data):
    import docx

    d = docx.Document(io.BytesIO(data))
    cells = [c.text for t in d.tables for r in t.rows for c in r.cells]
    return "\n".join([p.text for p in d.paragraphs] + cells)


def pdf_text(data):
    from pypdf import PdfReader

    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


def test_the_word_copy_has_the_notice_the_page_rule_every_date_and_its_notes():
    text = docx_text(export.to_docx(built("pdf")))
    assert rep.NOTICE in text and export.PAGE_NOTES["pdf"] in text and "3 dates" in text
    for raw in ("01/06/2020", "31/02/2021", "5th April 2021"):
        assert raw in text
    assert "page 2" in text and "not a real calendar date" in text and "not read as one day" in text


def test_a_word_or_text_source_says_in_the_file_that_a_part_is_not_a_page():
    text = docx_text(export.to_docx(built("no_pages")))
    assert export.PAGE_NOTES["no_pages"] in text and "page not available" in text and "page 2" not in text


def test_the_pdf_copy_carries_the_same_words():
    text = pdf_text(export.to_pdf(built("pdf"))).replace("\n", " ")
    assert "List of dates: Bundle 1" in text and "01/06/2020" in text and "31/02/2021" in text and "Page numbers are the pages of the PDF file" in text


def test_the_export_routes_work_and_are_private_to_the_organisation(user_a, user_b):
    created = user_a.post("/datelists", json={"title": "To export", "text": TEXT}).json()
    rid = created["id"]
    word = user_a.get(f"/datelists/{rid}/export")
    assert word.status_code == 200 and word.headers["content-type"].endswith("wordprocessingml.document") and "31/02/2021" in docx_text(word.content)
    pdf = user_a.get(f"/datelists/{rid}/export", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"
    assert user_b.get(f"/datelists/{rid}/export").status_code == 404
    assert user_a.get(f"/datelists/{rid}/export", params={"format": "txt"}).status_code == 422
