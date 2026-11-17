"""Reading scanned PDFs (pages that are pictures of text) with a vision-capable model, in the language written.

The text is stored like any other extracted text, but the document is marked as machine-read, because a model can misread a scan:
quotes are still checked against this stored text, so the person is told to compare it with the original before relying on it."""

import base64
import re

from lib import ai

MAX_PDF_BYTES = 15 * 1024 * 1024
READING_NOTE = "Read from a scan by AI. It can contain mistakes, so compare it with the original before you rely on it."
PROMPT = (
    "This is a scanned document. Transcribe EVERY page exactly as written, in the language or languages written and in each language's own script. "
    "Start each page with a line =====PAGE n===== (n = 1, 2, 3...). Do not summarise, translate, correct, explain or add anything. "
    "Write [illegible] for words you cannot read. If a page has no text, write only its marker line."
)
_MARK = re.compile(r"^=====\s*PAGE\s*(\d+)\s*=====\s*$", re.M | re.I)


def split_pages(text: str) -> list[str]:
    """Pages by their markers; if the model ignored the markers the whole text becomes one block."""
    parts = _MARK.split(text or "")
    if len(parts) < 3:
        return [(text or "").strip()] if (text or "").strip() else []
    pages: dict[int, str] = {}
    for i in range(1, len(parts) - 1, 2):
        pages[int(parts[i])] = parts[i + 1].strip()
    return [pages[k] for k in sorted(pages)]


async def ocr_pdf(session_id: str, data: bytes) -> list[str]:
    """One string per page. Raises ValueError if the file is too large and ai.AIError if no model could read it."""
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("That scanned PDF is too large to read automatically (limit 15 MB).")
    text = await ai.read_image_text(session_id, base64.b64encode(data).decode(), f"{PROMPT}\n(Reference: {session_id})", "application/pdf")
    return split_pages(text)