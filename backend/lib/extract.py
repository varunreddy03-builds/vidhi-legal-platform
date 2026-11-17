"""Document text extraction with page anchoring. Returns (pages, error)."""

import codecs
import io
import re


MIN_TEXT_LAYER = 20  # characters on a PDF page for it to count as having a text layer
NOT_TEXT = "This does not look like a UTF-8 text file (it may be saved in another encoding). Re-save it as UTF-8 (in Notepad: File > Save As > Encoding: UTF-8) and upload it again."


def decode_text(data: bytes) -> tuple[str, None] | tuple[None, str]:
    """(text, None) or (None, reason). UTF-8 (with or without a byte-order mark) and UTF-16/32 with a byte-order mark (what Windows Notepad calls "Unicode") are read exactly.
    Anything else is refused instead of being turned silently into garbage, because text with wrong characters in it can never be checked against a quote."""
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        enc = "utf-32"
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        enc = "utf-16"
    else:
        enc = "utf-8-sig"
    try:
        text = data.decode(enc)
    except UnicodeDecodeError:
        if enc != "utf-8-sig":
            return None, NOT_TEXT
        text = data.decode("utf-8", errors="replace")
        if text.count("�") > max(2, len(text) // 100):  # a stray byte or two is tolerated; a whole file in another encoding is not
            return None, NOT_TEXT
    controls = sum(1 for c in text if ord(c) < 32 and c not in "\n\r\t")
    if controls > len(text) * 0.02:  # UTF-16 without a byte-order mark reads as valid UTF-8 full of control characters; so does a binary file renamed .txt
        return None, NOT_TEXT
    return text, None


MAX_PDF_PAGES = 2000  # reading takes about 7 ms a page, so this is about 14 seconds of work for one upload; a longer bundle must be split
MAX_DOCX_UNZIPPED = 50 * 1024 * 1024  # a Word file is a zip: what it holds once opened, not its size on disk, is what the server has to read (security audit SA5)
MAX_DOCX_MEMBERS = 3000
TOO_BIG_DOCX = "This Word file holds far more than its size suggests (more than 50 MB of content once opened), so it was not read. Save it as a PDF or split it into parts, and upload again."


def docx_too_big(data: bytes) -> str | None:
    """A message when the Word file would inflate past the limit, else None. It counts the bytes actually produced while reading (a header can lie about a size), and stops as soon as the limit is passed."""
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = z.infolist()
            if len(members) > MAX_DOCX_MEMBERS:
                return TOO_BIG_DOCX
            total = 0
            for m in members:
                if m.is_dir():
                    continue
                with z.open(m) as f:
                    while chunk := f.read(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_DOCX_UNZIPPED:
                            return TOO_BIG_DOCX
    except zipfile.BadZipFile:
        return None  # not a zip at all: the reader below gives its own message
    return None


def extract_pages(filename: str, data: bytes, max_pages: int | None = MAX_PDF_PAGES) -> tuple[list[str], str | None]:
    name = filename.lower()
    try:
        if name.endswith(".pdf"):
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            if max_pages is not None and len(reader.pages) > max_pages:
                return [], f"This PDF has {len(reader.pages)} pages and the limit is {max_pages}. Split it into parts and upload each part."
            pages = [(p.extract_text() or "").strip() for p in reader.pages]
            with_text = sum(1 for p in pages if len(p.replace(" ", "")) >= MIN_TEXT_LAYER)
            if with_text * 2 < len(pages) or not any(pages):  # no text layer, or mostly pictures with a stamp or watermark: read it as a scan
                return [], "No extractable text (this looks like a scanned PDF)"
            return pages, None
        if name.endswith(".docx"):
            import docx

            if (too_big := docx_too_big(data)):
                return [], too_big
            pages = _paginate(_docx_text(docx.Document(io.BytesIO(data))))
            if max_pages is not None and len(pages) > max_pages:
                return [], f"This Word file has about {len(pages)} pages of text and the limit is {max_pages}. Split it into parts and upload each part."
            return pages, None
        if name.endswith((".txt", ".md")):
            text, problem = decode_text(data)
            return ([], problem) if problem else (_paginate(text), None)
        if name.endswith(".xlsx"):
            return _xlsx_pages(data, max_pages)
        if name.endswith(".pptx"):
            return _pptx_pages(data)
        if name.endswith(".eml"):
            return _eml_pages(data)
        if name.endswith((".doc", ".xls", ".ppt")):
            ext = name.rsplit(".", 1)[-1]
            return [], f"This is an old Office format (.{ext}). Open it in Word, Excel or PowerPoint and save it as .{ext}x, then upload that."
    except Exception as exc:  # noqa: BLE001
        return [], f"Extraction failed: {exc}"
    return [], "Unsupported format. Upload PDF, DOCX, XLSX, PPTX, EML or TXT"


NL = chr(10)
MAX_SHEET_CELLS = 500_000 # a spreadsheet can hold millions of cells; reading stops here and says so
TOO_MANY_CELLS = "This spreadsheet has more than 500,000 filled cells, so it was not read. Export the sheets you need as separate smaller files and upload those."


def _cell_text(v) -> str:
    return "" if v is None else str(v).strip()


def _xlsx_pages(data: bytes, max_pages: int | None) -> tuple[list[str], str | None]:
    """One text block per sheet: its name, then each non-empty row with the cells joined by " | ". Values are read as saved (formulas show their last saved result, never a recalculation)."""
    import openpyxl

    if (too_big := docx_too_big(data)):
        return [], too_big
    book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out: list[str] = []
    cells = 0
    for sheet in book.worksheets:
        lines = [f"Sheet: {sheet.title}"]
        for row in sheet.iter_rows(values_only=True):
            vals = [_cell_text(v) for v in row]
            if any(vals):
                cells += sum(1 for v in vals if v)
                if cells > MAX_SHEET_CELLS:
                    return [], TOO_MANY_CELLS
                lines.append(" | ".join(vals).rstrip(" |"))
        if len(lines) > 1:
            out.extend(_paginate(NL.join(lines)))
    if not out:
        return [], "No extractable text (this spreadsheet has no filled cells)"
    if max_pages is not None and len(out) > max_pages:
        return [], f"This spreadsheet has about {len(out)} pages of text and the limit is {max_pages}. Split it into parts and upload each part."
    return out, None


def _pptx_pages(data: bytes) -> tuple[list[str], str | None]:
    """One page per slide: its text boxes and tables in order, then its speaker notes."""
    from pptx import Presentation

    if (too_big := docx_too_big(data)):
        return [], too_big
    deck = Presentation(io.BytesIO(data))
    pages: list[str] = []
    for n, slide in enumerate(deck.slides, 1):
        lines = [f"Slide {n}"]
        for shape in slide.shapes:
            if shape.has_text_frame:
                lines.extend(p.text for p in shape.text_frame.paragraphs if p.text.strip())
            elif getattr(shape, "has_table", False) and shape.has_table:
                lines.extend(" | ".join(c.text.strip() for c in row.cells) for row in shape.table.rows)
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip() if slide.notes_slide.notes_text_frame else ""
            if notes:
                lines.append("Notes: " + notes)
        pages.append(NL.join(lines))
    if not any(len(p.split(NL)) > 1 for p in pages):
        return [], "No extractable text (this presentation has no text on its slides; pictures are not read)"
    return pages, None


def _eml_pages(data: bytes) -> tuple[list[str], str | None]:
    """An email as text: From, To, Cc, Date, Subject, the plain-text body (or the HTML body with its tags removed), and the NAMES of attachments. Attachments are not opened: upload them as their own files."""
    from email import policy
    from email.parser import BytesParser

    msg = BytesParser(policy=policy.default).parsebytes(data)
    head = [f"{h}: {msg[h]}" for h in ("From", "To", "Cc", "Date", "Subject") if msg[h]]
    if not head:
        return [], "This does not look like an email file (no From, To, Date or Subject lines)."
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        text = body.get_content()
        if body.get_content_type() == "text/html":
            text = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</(?:script|style)>", " ", text))
            text = text.replace(chr(9), " ")
    names = [a.get_filename() or "(unnamed)" for a in msg.iter_attachments()]
    lines = head + ["", text.strip()] + (["", "Attachments (not read): " + ", ".join(names)] if names else [])
    return _paginate(NL.join(lines)), None


def _table_lines(table) -> list[str]:
    return [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]


def _docx_text(doc) -> str:
    """Body paragraphs and tables in document order, then headers and footers. Footnotes, text boxes and tracked changes are not read (see `unread_parts`)."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    parts: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            parts.append(Paragraph(child, doc).text)
        elif tag == "tbl":
            parts.extend(_table_lines(Table(child, doc)))
    seen: set[str] = set()
    for section in doc.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer, section.even_page_header, section.even_page_footer):
            lines = [p.text for p in part.paragraphs] + [line for t in part.tables for line in _table_lines(t)]
            for line in lines:
                if line.strip() and line not in seen:
                    seen.add(line)
                    parts.append(line)
    return "\n".join(parts)


def unread_parts(filename: str, data: bytes) -> list[str]:
    """Things in the file that the reader does not extract, so a statement that something is absent from it cannot be called certain."""
    if not filename.lower().endswith(".docx"):
        return []
    import zipfile

    found = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            body = z.read("word/document.xml").decode("utf-8", errors="ignore")
            if "<w:txbxContent" in body:
                found.append("text boxes")
            if "<w:ins " in body or "<w:del " in body:
                found.append("tracked changes")
            for part, label in (("word/footnotes.xml", "footnotes"), ("word/endnotes.xml", "endnotes"), ("word/comments.xml", "comments")):
                if part in z.namelist() and re.search(r"<w:t[ >]", z.read(part).decode("utf-8", errors="ignore")):
                    found.append(label)
    except Exception:  # noqa: BLE001
        found.append("parts that could not be inspected")
    return found


def _paginate(text: str, chars: int = 2800) -> list[str]:
    """Slices of about `chars` characters, cut at whitespace so no word is split. Joining the slices with a space gives back the same text (up to whitespace)."""
    if not text:
        return [""]
    pages, i, n = [], 0, len(text)
    while i < n:
        end = min(i + chars, n)
        if end < n:
            m = None
            for m in re.finditer(r"\s", text[i + chars // 2: end]):
                pass
            if m:
                end = i + chars // 2 + m.start()
        pages.append(text[i:end])
        i = end
    return pages


CITATION_RE = re.compile(
    r"(?:(?:Section|Sec\.|S\.|Article|Art\.)\s*\d+[A-Za-z\-]*(?:\s*of\s*the\s*[A-Z][\w\s,]{3,60}?(?:Act|Code|Constitution)(?:,?\s*\d{4})?)?)"
    r"|(?:\(\d{4}\)\s*\d+\s*SCC\s*\d+)"
    r"|(?:AIR\s*\d{4}\s*(?:SC|Del|Bom|Mad|Cal)\s*\d+)",
    re.IGNORECASE,
)

DATE_RE = re.compile(r"\b(\d{1,2}[\/\-\s](?:\d{1,2}|[A-Z][a-z]{2,8})[\/\-\s]\d{2,4})\b")


def extract_entities(pages: list[str]) -> dict:
    citations: list[dict] = []
    dates: list[dict] = []
    seen_c: set[str] = set()
    seen_d: set[str] = set()
    for idx, page in enumerate(pages, start=1):
        for m in CITATION_RE.finditer(page):
            val = " ".join(m.group(0).split())
            if val.lower() in seen_c or len(citations) >= 60:
                continue
            seen_c.add(val.lower())
            citations.append({"text": val, "page": idx})
        for m in DATE_RE.finditer(page):
            val = m.group(1).strip()
            if val in seen_d or len(dates) >= 60:
                continue
            seen_d.add(val)
            dates.append({"text": val, "page": idx})
    return {"citations": citations, "dates": dates}
