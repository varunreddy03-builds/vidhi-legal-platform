"""PDF exports cannot draw Indian scripts: they say so instead of printing black boxes, and the English-only PDF is unchanged."""
import io

from lib import pdfsafe
from lib.datelist import export, report as rep


def pdf_text(data):
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


def built(title):
    return {"title": title, "source_file": "bundle.pdf", "created_at": "2026-10-28T10:00:00+00:00", **rep.build(["Filler.", "The cheque dated 31/02/2021 was returned."], "pdf")}


def test_guard_replaces_what_cannot_be_drawn_and_counts_it():
    g = pdfsafe.Guard()
    assert g.escape("A \u0939\u093f\u0928\u094d\u0926\u0940 & B") == "A ?????? &amp; B"
    assert g.count == 6
    assert "Word version" in g.note() and "6 characters" in g.note()


def test_ordinary_latin_text_and_curly_quotes_are_untouched():
    g = pdfsafe.Guard()
    assert g.escape("Caf\u00e9 \u2013 \u201cquoted\u201d \u20b9") == "Caf\u00e9 \u2013 \u201cquoted\u201d ?" and g.count == 1  # the rupee sign is not in the built-in font either


def test_pdf_with_a_hindi_title_carries_the_note_at_the_top():
    text = pdf_text(export.to_pdf(built("\u0939\u093f\u0928\u094d\u0926\u0940 file")))
    assert "cannot draw" in text and "Word version" in text and text.index("cannot draw") < text.index("31/02/2021")


def test_pdf_in_english_has_no_note():
    assert "cannot draw" not in pdf_text(export.to_pdf(built("Bundle 1")))
