"""Plain-text uploads in other encodings (Windows Notepad's "Unicode" is UTF-16): they must be read correctly or refused, never turned silently into garbage."""

import pytest

from lib.extract import extract_pages

TELUGU = "ఈ ఒప్పందం ప్రకారం చెల్లింపు 45 రోజుల్లో చేయాలి."
HINDI = "भुगतान 45 दिनों के भीतर किया जाएगा।"
ENGLISH = "Payment is due within 45 days of the invoice date."


@pytest.mark.parametrize("text", [ENGLISH, TELUGU, HINDI])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"])
def test_text_files_are_read_back_exactly_in_the_common_encodings(text, encoding):
    data = text.encode(encoding)
    if encoding in ("utf-16-le", "utf-16-be"):
        data = (b"\xff\xfe" if encoding == "utf-16-le" else b"\xfe\xff") + data  # Notepad writes the byte-order mark
    pages, error = extract_pages("terms.txt", data)
    assert error is None and "".join(pages).replace("\n", "") == text


@pytest.mark.parametrize("text", [TELUGU, HINDI])
def test_a_text_file_in_an_unreadable_encoding_is_refused_not_garbled(text):
    pages, error = extract_pages("terms.txt", text.encode("utf-16-le")[:-1])  # no byte-order mark and cut mid-character: cannot be UTF-8
    assert pages == [] and error and "UTF-8" in error
    pages, error = extract_pages("terms.txt", (ENGLISH * 3).encode("cp1252") + "é".encode("cp1252") * 40)  # an old Windows file with accented letters
    assert pages == [] and error and "UTF-8" in error


def test_one_stray_byte_in_a_long_file_does_not_throw_the_whole_file_away():
    data = (ENGLISH + " ") .encode() * 60 + b"\xff" + (ENGLISH + " ").encode() * 60
    pages, error = extract_pages("terms.txt", data)
    assert error is None and "Payment is due" in pages[0]
