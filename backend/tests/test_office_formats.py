"""Excel, PowerPoint and email files are read like Word and PDF files: text out, nothing invented, damaged or oversized files refused with a plain message."""
import io
import zipfile

import openpyxl
import pytest
from pptx import Presentation
from pptx.util import Inches

from lib import extract
from tests.conftest import mongo, new_matter, upload  # noqa: F401
from tests.test_admin import admin  # noqa: F401
from tests.conftest import user_a  # noqa: F401


def make_xlsx(rows_by_sheet: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in rows_by_sheet.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_pptx(slides: list[tuple[str, str]], notes: str = "") -> bytes:
    deck = Presentation()
    for title, body in slides:
        s = deck.slides.add_slide(deck.slide_layouts[5])
        s.shapes.title.text = title
        box = s.shapes.add_textbox(Inches(1), Inches(2), Inches(5), Inches(1))
        box.text_frame.text = body
        if notes:
            s.notes_slide.notes_text_frame.text = notes
    buf = io.BytesIO()
    deck.save(buf)
    return buf.getvalue()


EML = b"From: a@example.com\r\nTo: b@example.com\r\nDate: Mon, 02 Mar 2026 10:00:00 +0530\r\nSubject: Notice under Section 138\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nThe cheque was returned on 12 March 2021.\r\n"


def test_xlsx_is_read_sheet_by_sheet_with_cells_in_order():
    pages, err = extract.extract_pages("ledger.xlsx", make_xlsx({"Payments": [["Date", "Amount"], ["2021-03-12", 125000]], "Notes": [["Cheque 004512 returned"]]}))
    assert err is None
    text = "\n".join(pages)
    assert "Sheet: Payments" in text and "Date | Amount" in text and "2021-03-12 | 125000" in text and "Sheet: Notes" in text and "Cheque 004512 returned" in text


def test_a_spreadsheet_with_no_filled_cells_says_so():
    pages, err = extract.extract_pages("empty.xlsx", make_xlsx({"A": [[None, None]]}))
    assert pages == [] and "no filled cells" in err


def test_a_spreadsheet_over_the_cell_limit_is_refused(monkeypatch):
    monkeypatch.setattr(extract, "MAX_SHEET_CELLS", 3)
    pages, err = extract.extract_pages("big.xlsx", make_xlsx({"A": [[1, 2], [3, 4]]}))
    assert pages == [] and "500,000" in err


def test_pptx_gives_one_page_per_slide_with_notes():
    pages, err = extract.extract_pages("deck.pptx", make_pptx([("Facts", "Hearing on 12 March 2021"), ("Law", "Section 138")], notes="Speaker note one"))
    assert err is None and len(pages) == 2
    assert pages[0].startswith("Slide 1") and "Hearing on 12 March 2021" in pages[0] and "Notes: Speaker note one" in pages[0]
    assert "Section 138" in pages[1]


def test_eml_keeps_the_headers_and_body_and_names_but_does_not_open_attachments():
    raw = EML.replace(b"Content-Type: text/plain; charset=utf-8\r\n\r\n", b"Content-Type: multipart/mixed; boundary=XX\r\n\r\n--XX\r\nContent-Type: text/plain\r\n\r\n") + b"--XX\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename=\"notice.pdf\"\r\n\r\nSECRET-ATTACHMENT-BYTES\r\n--XX--\r\n"
    pages, err = extract.extract_pages("mail.eml", raw)
    text = "\n".join(pages)
    assert err is None and "Subject: Notice under Section 138" in text and "returned on 12 March 2021" in text and "Attachments (not read): notice.pdf" in text
    assert "SECRET-ATTACHMENT-BYTES" not in text


def test_html_only_email_is_read_without_tags_or_scripts():
    raw = b"From: a@example.com\r\nSubject: Hi\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><style>p{color:red}</style><body><p>Pay Rs 5,000 by 1 April.</p><script>alert(1)</script></body></html>\r\n"
    pages, err = extract.extract_pages("h.eml", raw)
    text = "\n".join(pages)
    assert err is None and "Pay Rs 5,000 by 1 April." in text and "alert" not in text and "color:red" not in text


def test_a_text_file_renamed_eml_is_refused():
    pages, err = extract.extract_pages("x.eml", b"just some words with no headers")
    assert pages == [] and "does not look like an email" in err


def test_old_office_formats_say_what_to_do():
    for name in ("a.doc", "a.xls", "a.ppt"):
        pages, err = extract.extract_pages(name, b"\xd0\xcf\x11\xe0")
        assert pages == [] and "old Office format" in err and "save it as" in err


@pytest.mark.parametrize("name", ["bad.xlsx", "bad.pptx"])
def test_a_damaged_office_file_gives_a_message_not_a_crash(name):
    pages, err = extract.extract_pages(name, b"PK\x03\x04 this is not a real zip")
    assert pages == [] and err


def test_an_office_zip_that_inflates_past_the_limit_is_refused(monkeypatch):
    monkeypatch.setattr(extract, "MAX_DOCX_UNZIPPED", 1000)
    pages, err = extract.extract_pages("bomb.xlsx", make_xlsx({"A": [["x" * 200] for _ in range(20)]}))
    assert pages == [] and "far more" in err


# ---- through the upload route ----

def test_the_matter_upload_accepts_xlsx_pptx_eml_and_refuses_lookalikes(admin):  # noqa: F811
    mid, _ = new_matter(admin, "Office")
    for name, data, needle in (("ledger.xlsx", make_xlsx({"S": [["Cheque 004512 returned"]]}), "004512"), ("deck.pptx", make_pptx([("Facts", "Hearing on 12 March 2021")]), "12 March 2021"), ("mail.eml", EML, "Section 138")):
        doc = upload(admin, mid, name, data)
        assert doc.get("id")
        got = admin.get(f"/documents/{doc['id']}")
        assert got.status_code == 200 and needle in got.text
    # a zip that is not a spreadsheet, and a binary file renamed .eml, are refused by their content, not their name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "hi")
    assert admin.post(f"/matters/{mid}/documents", files={"file": ("fake.xlsx", buf.getvalue())}).status_code == 415
    assert admin.post(f"/matters/{mid}/documents", files={"file": ("fake.eml", b"\x00\x01\x02binary")}).status_code == 415
    assert admin.post(f"/matters/{mid}/documents", files={"file": ("old.xls", b"\xd0\xcf\x11\xe0")}).status_code == 415


# ---- zip batch ----

def make_zip(files: dict[str, bytes], password_flag: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def post_zip(c, mid, data, name="batch.zip"):
    return c.post(f"/matters/{mid}/documents/zip", files={"file": (name, data)})


def test_a_zip_adds_each_good_file_and_lists_what_it_skipped_and_why(admin):  # noqa: F811
    mid, _ = new_matter(admin, "Zip")
    z = make_zip({
        "folder/notice.txt": b"The notice was sent on 12 March 2021.",
        "ledger.xlsx": make_xlsx({"S": [["Cheque 004512 returned"]]}),
        "__MACOSX/._notice.txt": b"junk",
        ".hidden.txt": b"x",
        "program.exe": b"MZ\x90\x00",
        "inner.zip": make_zip({"a.txt": b"hi"}),
        "fake.pdf": b"this is not a pdf",
    })
    r = post_zip(admin, mid, z)
    assert r.status_code == 200, r.text
    body = r.json()
    by = {x["filename"]: x for x in body["results"]}
    assert body["added"] == 2 and by["notice.txt"]["status"] == "added" and by["ledger.xlsx"]["status"] == "added"
    assert "system or hidden" in by["._notice.txt"]["reason"] and "system or hidden" in by[".hidden.txt"]["reason"]
    assert "not supported" in by["program.exe"]["reason"] and "zip inside a zip" in by["inner.zip"]["reason"]
    assert by["fake.pdf"]["status"] == "skipped" and "valid PDF" in by["fake.pdf"]["reason"]
    assert len(admin.get(f"/matters/{mid}/documents").json()) == 2


def test_the_same_file_twice_in_a_zip_is_added_once(admin):  # noqa: F811
    mid, _ = new_matter(admin, "ZipDup")
    r = post_zip(admin, mid, make_zip({"a.txt": b"same words here", "b.txt": b"same words here"})).json()
    assert r["added"] == 1 and r["skipped"] == 1 and "already in the matter" in [x for x in r["results"] if x["status"] == "skipped"][0]["reason"]


def test_a_zip_with_too_many_files_or_too_much_inside_or_not_a_zip_is_refused(admin, monkeypatch):  # noqa: F811
    mid, _ = new_matter(admin, "ZipLimits")
    many = make_zip({f"f{i}.txt": f"file {i}".encode() for i in range(51)})
    assert post_zip(admin, mid, many).status_code == 413
    assert post_zip(admin, mid, b"PK\x03\x04 not really").status_code == 415
    assert post_zip(admin, mid, b"plain", name="notzip.txt").status_code == 415
    assert admin.get(f"/matters/{mid}/documents").json() == []


def test_a_zip_cannot_write_outside_the_matter_by_its_file_names(admin):  # noqa: F811
    mid, _ = new_matter(admin, "ZipPath")
    r = post_zip(admin, mid, make_zip({"../../etc/evil.txt": b"words in a file", "C:\\Windows\\evil2.txt": b"other words"})).json()
    assert r["added"] == 2
    names = sorted(d["filename"] for d in admin.get(f"/matters/{mid}/documents").json())
    assert names == ["evil.txt", "evil2.txt"]


def test_a_zip_is_refused_for_a_matter_in_another_organisation(admin, user_a):  # noqa: F811
    mid, _ = new_matter(admin, "ZipTenant")
    assert post_zip(user_a, mid, make_zip({"a.txt": b"words"})).status_code in (403, 404)
