"""Finds the dates written in a document, page by page, for the 'List of dates with page references'.

This only READS what the document says. It never decides what an event means, never corrects a date, and never says a date is wrong: it can only mark a date it could not read
cleanly (not a real calendar date, day and month both could be either, only two digits for the year, no day given) and leave the decision to the lawyer.

Date shapes understood (the document's own spelling is always kept in `raw`):
  2021-03-12 · 12/03/2021 · 12-03-2021 · 12.03.2021 · 12th March 2021 · 3rd day of May 2020 · 12-Mar-2021 · 12 Mar, 2021 · March 12, 2021 · March 2021 (month only)
Numeric dates are read as DAY/MONTH/YEAR (the usual order in Indian documents) and, when the day and month could swap, the entry says so."""

import re
from dataclasses import dataclass, field
from datetime import date

from lib.refcheck.citations import _sentence_at

ENOUGH = 3001  # a report holds at most 3000 dates and refuses more, so past this point no more sentences are cut out and no more pages are read

MONTHS = {m: i for i, names in enumerate(
    [("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"), ("july", "jul"),
     ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"), ("december", "dec")], 1) for m in names}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
_YEAR = r"(?:19|20)\d{2}"
_ORD = r"(?:st|nd|rd|th)?"

ISO = re.compile(rf"\b(?P<y>{_YEAR})-(?P<m>\d{{2}})-(?P<d>\d{{2}})\b")
NUMERIC = re.compile(rf"(?<![\d/.\-])(?P<d>\d{{1,2}})(?P<sep>[/.\-])(?P<m>\d{{1,2}})(?P=sep)(?P<y>{_YEAR}|\d{{2}})(?![\d/.\-]?\d)")
DAY_MONTH_YEAR = re.compile(rf"\b(?P<d>\d{{1,2}}){_ORD}\s+(?:day\s+of\s+|of\s+)?(?P<mon>{_MON})\b\.?,?\s+(?P<y>{_YEAR})\b", re.I)
DAY_MON_DASH = re.compile(rf"(?<![\d-])(?P<d>\d{{1,2}})-(?P<mon>{_MON})\.?-(?P<y>{_YEAR}|\d{{2}})(?!\d)", re.I)
MONTH_DAY_YEAR = re.compile(rf"\b(?P<mon>{_MON})\b\.?\s+(?P<d>\d{{1,2}}){_ORD},?\s+(?P<y>{_YEAR})\b", re.I)
MONTH_YEAR = re.compile(rf"\b(?P<mon>{_MON})\b\.?,?\s+(?P<y>{_YEAR})\b", re.I)


@dataclass
class Found:
    raw: str  # the date exactly as the document wrote it
    page: int  # 1-based page (or slice) of the document
    sentence: str  # the sentence around it: what the date is attached to
    iso: str | None = None  # YYYY-MM-DD when the date could be read as one real day; None otherwise
    kind: str = ""  # iso | numeric | day_month_year | month_day_year | month_year
    flags: list[str] = field(default_factory=list)  # plain-words notes for the lawyer; never an accusation
    start: int = 0  # position in the page text, to keep reading order


def _make(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def extract_page(text: str, page: int, today: str | None = None) -> list[Found]:
    """Every date written on one page, in reading order. `today` (YYYY-MM-DD) lets a date later than today be noted; None skips that note."""
    out: list[Found] = []
    taken: list[tuple[int, int]] = []

    def free(m: re.Match) -> bool:
        return not any(m.start() < e and s < m.end() for s, e in taken)

    def add(m: re.Match, kind: str, iso: str | None, flags: list[str]) -> None:
        taken.append(m.span())
        if iso and today and iso > today:
            flags.append("This date is later than today.")
        out.append(Found(raw=" ".join(m.group(0).split()), page=page, sentence=_sentence_at(text, m.start(), m.end()) if len(out) < ENOUGH else "", iso=iso, kind=kind, flags=flags, start=m.start()))

    for m in ISO.finditer(text):
        iso = _make(int(m["y"]), int(m["m"]), int(m["d"]))
        add(m, "iso", iso, [] if iso else ["This is not a real calendar date. It is shown as written."])
    for rx, kind in ((DAY_MONTH_YEAR, "day_month_year"), (MONTH_DAY_YEAR, "month_day_year")):
        for m in rx.finditer(text):
            if not free(m):
                continue
            iso = _make(int(m["y"]), MONTHS[m["mon"].lower()], int(m["d"]))
            add(m, kind, iso, [] if iso else ["This is not a real calendar date. It is shown as written."])
    for m in DAY_MON_DASH.finditer(text):  # 12-Mar-2021 and 12-Mar-21
        if not free(m):
            continue
        if len(m["y"]) == 2:
            add(m, "day_month_year", None, ["The year has only two digits, so the date was not read. Check it in the document."])
            continue
        iso = _make(int(m["y"]), MONTHS[m["mon"].lower()], int(m["d"]))
        add(m, "day_month_year", iso, [] if iso else ["This is not a real calendar date. It is shown as written."])
    for m in NUMERIC.finditer(text):
        if not free(m):
            continue
        d, mo, y = int(m["d"]), int(m["m"]), m["y"]
        flags: list[str] = []
        if len(y) == 2:
            if m["sep"] == ".":  # 1.2.20 is far more likely a clause number than a date
                continue
            add(m, "numeric", None, ["The year has only two digits, so the date was not read. Check it in the document."])
            continue
        iso = _make(int(y), mo, d)
        if iso is None:
            if _make(int(y), d, mo):  # the digits fit only month/day: do not guess
                flags.append("Read as day/month/year this is not a real date, but it would be one as month/day/year. It is shown as written; check it in the document.")
            else:
                flags.append("This is not a real calendar date. It is shown as written.")
        elif d <= 12 and d != mo:
            flags.append("Read as day/month/year. If the document uses month/day/year, this is a different date.")
        add(m, "numeric", iso, flags)
    for m in MONTH_YEAR.finditer(text):
        if not free(m):
            continue
        add(m, "month_year", None, ["Only the month and year are given, so there is no exact day."])
    out.sort(key=lambda f: f.start)
    return out


def extract(pages: list[str], today: str | None = None) -> list[Found]:
    """Every date in the document, in reading order (page by page). Every appearance is kept: a date written on pages 2 and 5 is two entries."""
    found: list[Found] = []
    for i, text in enumerate(pages, 1):
        if len(found) >= ENOUGH:
            break
        found.extend(extract_page(text or "", i, today))
    return found
