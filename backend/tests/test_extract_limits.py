"""Reading a PDF takes about 7 ms a page and used to run on the main thread with no page limit: 3,000 pages held the whole server worker for 21 seconds (security audit S7).
Now a PDF over 2,000 pages is refused before any reading, and every upload route reads files in a worker thread."""

import io
import re
from pathlib import Path

from lib import extract

ROOT = Path(__file__).resolve().parent.parent


def pdf(pages: int, text: str = "The petitioner filed the suit on 5th April 2021 under Section 420 IPC and the claim is pending before the court.") -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for i in range(pages):
        c.drawString(40, 800, f"{text} Page {i + 1}.")
        c.showPage()
    c.save()
    return buf.getvalue()


def test_a_pdf_over_the_page_limit_is_refused_before_any_reading_and_under_it_is_read():
    data = pdf(5)
    pages, err = extract.extract_pages("a.pdf", data, 4)
    assert pages == [] and err == "This PDF has 5 pages and the limit is 4. Split it into parts and upload each part."
    pages, err = extract.extract_pages("a.pdf", data, 5)
    assert err is None and len(pages) == 5 and "Page 5" in pages[4]
    pages, err = extract.extract_pages("a.pdf", data, None)  # the administrator's law-library upload has no limit
    assert err is None and len(pages) == 5
    assert extract.MAX_PDF_PAGES == 2000 and extract.extract_pages.__defaults__ == (2000,)  # the limit applies unless a caller says otherwise


def test_a_2001_page_pdf_is_refused_by_the_toolkit_upload_with_a_plain_message(user_a):
    big = pdf(2001, text="x")
    for path in ("/datelists/file", "/defectchecks/file", "/oldcodechecks/file", "/authority/checks/file"):
        r = user_a.post(path, files={"file": ("bundle.pdf", big, "application/pdf")})
        assert r.status_code == 409 and "limit is 2000" in r.json()["detail"], (path, r.status_code, r.text[:200])


def test_every_upload_route_reads_files_in_a_worker_thread_not_on_the_main_thread():
    callers = [p for p in (ROOT / "routers").glob("*.py") if "extract_pages" in p.read_text(encoding="utf-8")]
    assert {p.name for p in callers} >= {"authority.py", "datelist.py", "defectcheck.py", "oldcodecheck.py", "documents.py", "recovery.py", "legal.py"}
    for p in callers:
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"extract_pages\(", text), f"{p.name} calls extract_pages directly on the main thread"  # the thread form is to_thread(extract_pages, ...), with no bracket after the name
        assert "asyncio.to_thread(extract_pages" in text, p.name


# ---- a Word file is a zip: a small file can hold a huge amount (security audit SA5) ----

def docx_with(text: str) -> bytes:
    """A real Word file whose body is one paragraph of `text` (made by writing the body XML directly, so very long text stays cheap to build)."""
    import zipfile

    import docx

    base = io.BytesIO()
    docx.Document().save(base)
    out = io.BytesIO()
    with zipfile.ZipFile(base) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            payload = zin.read(item.filename)
            if item.filename == "word/document.xml":
                head = payload.decode("utf-8").split("<w:body>")[0]
                payload = (head + f'<w:body><w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p></w:body></w:document>').encode("utf-8")
            zout.writestr(item, payload)
    return out.getvalue()


def test_a_small_word_file_that_inflates_past_the_limit_is_refused_without_being_read():
    data = docx_with("a" * (60 * 1024 * 1024))
    assert len(data) < 200_000  # a few kilobytes on disk
    pages, err = extract.extract_pages("bomb.docx", data)
    assert pages == [] and err == extract.TOO_BIG_DOCX and "50 MB" in err


def test_a_word_file_with_too_many_parts_is_refused():
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(extract.MAX_DOCX_MEMBERS + 1):
            z.writestr(f"p{i}.txt", "x")
    assert extract.docx_too_big(buf.getvalue()) == extract.TOO_BIG_DOCX


def test_a_header_that_lies_about_the_size_cannot_make_the_server_read_more():
    import struct
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"a" * (60 * 1024 * 1024))
    raw = bytearray(buf.getvalue())
    for sig, off in ((b"PK", 22), (b"PK", 24)):  # say, in both headers, that the part is 10 bytes long
        i = raw.find(sig)
        raw[i + off:i + off + 4] = struct.pack("<I", 10)
    # the zip reader stops at the size a header gives, so the lie shrinks what is read; the file is either refused or read as almost nothing, never inflated
    pages, err = extract.extract_pages("liar.docx", bytes(raw))
    assert pages == [] and err is not None
    assert extract.docx_too_big(bytes(raw)) in (None, extract.TOO_BIG_DOCX)


def test_a_word_file_with_too_many_pages_of_text_is_refused_with_the_same_limit_as_a_pdf():
    data = docx_with("word " * 1_200_000)  # about 6 MB of text: 2,000+ pages of 2,800 characters
    pages, err = extract.extract_pages("long.docx", data)
    assert pages == [] and "limit is 2000" in err and err.startswith("This Word file")
    pages, err = extract.extract_pages("long.docx", data, None)  # the administrator's law-library upload has no page limit
    assert err is None and len(pages) > 2000


def test_an_ordinary_word_file_and_a_broken_one_behave_as_before():
    pages, err = extract.extract_pages("ok.docx", docx_with("The petitioner filed the suit on 5th April 2021."))
    assert err is None and "petitioner" in pages[0]
    pages, err = extract.extract_pages("bad.docx", b"this is not a zip")
    assert pages == [] and err.startswith("Extraction failed")


def test_the_toolkit_upload_routes_refuse_an_inflating_word_file_in_plain_words(user_a):
    data = docx_with("a" * (60 * 1024 * 1024))
    ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    for path in ("/datelists/file", "/defectchecks/file", "/oldcodechecks/file", "/authority/checks/file"):
        r = user_a.post(path, files={"file": ("bomb.docx", data, ctype)})
        assert r.status_code == 409 and "50 MB" in r.json()["detail"], (path, r.status_code, r.text[:200])


def test_a_file_sent_again_after_a_lost_reply_is_refused_in_words_that_say_it_already_arrived(user_a):
    """Security audit SA10: the app resends a file by itself when the connection returns; if the first copy had arrived, the person is told so instead of seeing a bare error."""
    from tests.conftest import new_matter, upload

    mid, _ = new_matter(user_a)
    upload(user_a, mid, "letter.txt", "The petitioner filed the suit on 5th April 2021.")
    r = user_a.post(f"/matters/{mid}/documents", files={"file": ("letter-again.txt", b"The petitioner filed the suit on 5th April 2021.")})
    assert r.status_code == 409
    assert "already in the matter as 'letter.txt'" in r.json()["detail"] and "arrived the first time" in r.json()["detail"]
