"""Builds the 'List of dates with page references' from a document's pages. Plain code, no AI.

Dates are listed in date order (dates that could not be read as one real day go last, in reading order). Every entry keeps the date exactly as the document wrote it, the sentence it
sits in, notes where it could not be read cleanly, and where it is in the file. A PDF has real pages. A Word or text file does not (the app cuts it into slices), so for those the list
says "page not available" and gives the part of the file instead: a slice number is never shown as a page number."""

import os

from lib.datelist import extract

NOTICE = ("Dates are listed as the document wrote them. Notes mark dates that could not be read cleanly; nothing has been corrected. "
          "Check each date and page against the document before using this list in a filing. This list does not say what an event means or which dates matter.")
MAX_DATES = 3000
SENTENCE_MAX = 300


def enabled() -> bool:
    return os.environ.get("DATE_LIST_ENABLED", "false").lower() == "true"


class TooManyDates(Exception):
    def __init__(self, n: int):
        super().__init__(n)
        self.n = n


def page_kind(filename: str | None) -> str:
    """'pdf' (real pages), 'no_pages' (Word, text: no fixed pages) or 'unknown' (pasted text)."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith((".docx", ".txt", ".md")):
        return "no_pages"
    return "unknown"


def _where(kind: str, n: int, total: int) -> tuple[int | None, str]:
    if kind == "pdf":
        return n, f"page {n}"
    if kind == "no_pages":
        return None, f"page not available (this file type has no fixed pages); part {n} of {total} of the file"
    return None, "page not available (pasted text has no pages)"


def build(pages: list[str], kind: str, today: str | None = None) -> dict:
    found = extract.extract(pages, today)
    if len(found) > MAX_DATES:
        raise TooManyDates(len(found))
    total = len(pages)
    order = {id(f): i for i, f in enumerate(found)}  # reading order, for ties and for dates with no day
    found.sort(key=lambda f: (f.iso is None, f.iso or "", order[id(f)]))
    items = []
    for n, f in enumerate(found, 1):
        page, where = _where(kind, f.page, total)
        items.append({
            "n": n, "raw": f.raw, "date": f.iso, "kind": f.kind, "flags": f.flags, "sentence": f.sentence[:SENTENCE_MAX],
            "page": page, "where": where, "part": f.page,
        })
    return {"items": items, "counts": counts(items), "page_kind": kind, "notice": NOTICE}


def counts(items: list[dict]) -> dict:
    return {"total": len(items), "dated": sum(1 for i in items if i["date"]), "not_read_cleanly": sum(1 for i in items if i["flags"]),
            "no_exact_day": sum(1 for i in items if not i["date"])}
