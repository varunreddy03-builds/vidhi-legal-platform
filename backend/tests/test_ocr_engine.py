"""Page-by-page reading: embedded text, Tesseract (replaced here by a stand-in: none is installed on this machine), then the hosted reader.
Confidence appears only when an engine really reported one."""

import asyncio
import io

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from lib import ocr, ocr_engine
from tests.test_ocr import scanned_pdf

TSV_HEAD = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"


def tsv(words: list[tuple[str, float]], line=1) -> str:
    rows = [f"5\t1\t1\t1\t{line}\t{i}\t0\t0\t10\t10\t{conf}\t{w}" for i, (w, conf) in enumerate(words, 1)]
    return TSV_HEAD + "\n".join(["1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t"] + rows) + "\n"


def mixed_pdf() -> bytes:
    """Page 1 has a real text layer; pages 2 and 3 are pictures only."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 700, "Page one has an ordinary text layer with plenty of words in it.")
    c.save()
    w = PdfWriter()
    w.append(PdfReader(io.BytesIO(buf.getvalue())))
    w.append(PdfReader(io.BytesIO(scanned_pdf(2))))
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def run(coro):
    return asyncio.run(coro)


def test_tsv_gives_text_and_the_mean_of_real_word_confidences_only():
    text, conf, words = ocr_engine.parse_tsv(tsv([("Hello", 90.0), ("world", 70.0), ("faint", 50.0)]))
    assert text == "Hello world faint" and conf == 70.0 and words == 3
    assert ocr_engine.parse_tsv(TSV_HEAD) == ("", None, 0)  # nothing read: no confidence is invented
    assert ocr_engine.parse_tsv("not tsv at all")[1] is None


def test_a_page_is_uncertain_when_empty_unreadable_or_low_confidence_and_never_for_unknown_confidence_alone():
    m = ocr_engine._meta
    assert m(1, "tesseract", "eng", 91.2, [], "clear text")["uncertain"] is False
    low = m(1, "tesseract", "eng", 41.0, [], "blurry text")
    assert low["uncertain"] is True and any("Low reading confidence (41.0)" in w for w in low["warnings"])
    assert m(1, "tesseract", "eng", 59.9, [], "x")["uncertain"] is True and m(1, "tesseract", "eng", 60.0, [], "x")["uncertain"] is False
    assert m(1, "hosted-vision", "any", None, [], "")["uncertain"] is True  # an empty page is never certain
    marked = m(1, "hosted-vision", "any", None, [], "Name: [illegible] Singh")
    assert marked["uncertain"] is True and any("[illegible]" in w for w in marked["warnings"])
    unknown = m(1, "hosted-vision", "any", None, [], "Plainly readable text")
    assert unknown["uncertain"] is True and unknown["confidence"] is None  # a hosted reader reports no confidence at all, so its pages must be checked against the original
    assert m(1, "embedded-text", "", None, [], "Plainly readable text")["uncertain"] is False  # the PDF's own text layer is not a reading


def test_without_tesseract_scanned_pages_go_to_the_hosted_reader_and_report_no_confidence(monkeypatch):
    monkeypatch.setattr(ocr_engine, "tesseract_cmd", lambda: None)

    async def hosted(session_id, data):
        return ["Page one text layer ignored by the reader", "Scan page two text", "Scan page three [illegible] text"]

    monkeypatch.setattr(ocr, "ocr_pdf", hosted)
    pages, meta = run(ocr_engine.read_pdf("s1", mixed_pdf()))
    assert [m["engine"] for m in meta] == ["embedded-text", "hosted-vision", "hosted-vision"]
    assert pages[0].startswith("Page one has an ordinary text layer")  # the real text layer is kept, not replaced by the reader
    assert [m["confidence"] for m in meta] == [None, None, None] and [m["uncertain"] for m in meta] == [False, True, True]  # a hosted reader's pages are always uncertain
    assert ocr_engine.HOSTED_WARNING in meta[1]["warnings"] and ocr_engine.uncertain_pages(meta) == [2, 3]


def test_with_tesseract_scanned_pages_get_its_real_confidence_and_missing_languages_are_reported(monkeypatch):
    monkeypatch.setattr(ocr_engine, "tesseract_cmd", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr_engine, "renderer_available", lambda: True)
    monkeypatch.setattr(ocr_engine, "installed_languages", lambda cmd: {"eng", "tel"})  # Hindi data not installed
    monkeypatch.setattr(ocr_engine, "render_pages", lambda data, dpi=300: [b"png1", b"png2", b"png3"])
    seen = []

    def fake(cmd, png, langs):
        seen.append(langs)
        return tsv([("Clear", 95.0), ("words", 85.0)]) if png == b"png2" else tsv([("blurry", 30.0), ("smudge", 40.0)])

    monkeypatch.setattr(ocr_engine, "run_tesseract", fake)

    async def never(*a, **k):
        raise AssertionError("the hosted reader must not be used when Tesseract read every page")

    monkeypatch.setattr(ocr, "ocr_pdf", never)
    pages, meta = run(ocr_engine.read_pdf("s2", mixed_pdf()))
    assert [m["engine"] for m in meta] == ["embedded-text", "tesseract", "tesseract"] and seen == ["eng+tel", "eng+tel"]
    assert meta[1]["confidence"] == 90.0 and meta[1]["uncertain"] is False and pages[1] == "Clear words"
    assert meta[2]["confidence"] == 35.0 and meta[2]["uncertain"] is True
    assert any("Language data not installed: hin" in w for w in meta[1]["warnings"])
    assert ocr_engine.uncertain_pages(meta) == [3]


def test_a_page_tesseract_cannot_read_falls_back_to_the_hosted_reader(monkeypatch):
    monkeypatch.setattr(ocr_engine, "tesseract_cmd", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr_engine, "renderer_available", lambda: True)
    monkeypatch.setattr(ocr_engine, "installed_languages", lambda cmd: {"eng"})
    monkeypatch.setattr(ocr_engine, "render_pages", lambda data, dpi=300: [b"a", b"b", b"c"])

    def flaky(cmd, png, langs):
        if png == b"c":
            raise RuntimeError("tesseract crashed")
        return tsv([("fine", 88.0)])

    monkeypatch.setattr(ocr_engine, "run_tesseract", flaky)

    async def hosted(session_id, data):
        return ["x", "y", "Rescued by the hosted reader"]

    monkeypatch.setattr(ocr, "ocr_pdf", hosted)
    pages, meta = run(ocr_engine.read_pdf("s3", mixed_pdf()))
    assert [m["engine"] for m in meta] == ["embedded-text", "tesseract", "hosted-vision"] and pages[2] == "Rescued by the hosted reader"


def test_mismatched_page_counts_from_the_hosted_reader_are_flagged(monkeypatch):
    monkeypatch.setattr(ocr_engine, "tesseract_cmd", lambda: None)

    async def hosted(session_id, data):
        return ["only one block of text"]

    monkeypatch.setattr(ocr, "ocr_pdf", hosted)
    pages, meta = run(ocr_engine.read_pdf("s4", mixed_pdf()))
    assert any("Page boundaries" in w for w in meta[1]["warnings"]) and pages[2] == "" and meta[2]["uncertain"] is True

def test_character_error_rate_is_the_edit_distance_over_the_correct_length():
    cer = ocr_engine.char_error_rate
    assert cer("hello world", "hello world") == 0.0 and cer("hello  world", "hello world") == 0.0  # whitespace is normalised
    assert cer("abcd", "abxd") == 0.25 and cer("abcd", "") == 1.0 and cer("", "") == 0.0 and cer("", "x") == 1.0
    assert cer("abcd", "abcde") == 0.25 and cer("తెలుగు", "తెలుగు") == 0.0 and 0 < cer("తెలుగు", "తెలగు") < 1
