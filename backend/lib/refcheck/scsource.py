"""The Supreme Court open dataset as a case source for Authority Check: same interface as the old Indian Kanoon adapter (name, search, fetch, url_for), but local, free and offline.

What it can and cannot do (checked on the real data):
  * Searches by neutral citation ('2024 INSC 735'), by SCR report citation ('[2024] 10 SCR 108'), by party names, and by party names with the year. 43,578 judgments, 1950 to 2026.
  * SCC and AIR report numbers are NOT in the data, so a query for one finds nothing; the checker then says "report number not verifiable from this source" and relies on the neutral
    citation, party names and year.
  * The index keeps the metadata in memory. The judgment text is read from the local archive only for a judgment that was matched (fetch), and cut into paragraph blocks for the quote check.
  * COMPLETENESS IS UNVERIFIED: nobody has shown this dataset holds every judgment of the Court for any year. So `complete_for()` is False for every year, and the checker therefore never
    answers "not found after a full search" from it; it says "could not check". A judgment newer than `as_of` is also "could not check".
Licence: CC-BY-4.0, Dattam Labs, from the Supreme Court's eCourts pages. The attribution is carried into every report (see `attribution`)."""

import re
import tarfile
from datetime import date
from functools import lru_cache
from pathlib import Path

from lib.refcheck import scdata
from lib.refcheck.lookup import _side_matches, _tokens
from lib.refcheck.sources import Candidate, SourceDown

DATASET = "Indian Supreme Court Judgments (open dataset, Dattam Labs)"
REGISTRY = "https://registry.opendata.aws/indian-supreme-court-judgments/"
LICENCE = "CC-BY-4.0"
BUCKET_URL = "https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com/"
COURT = "Supreme Court of India"
_QUOTED = re.compile(r'^\s*"(.+)"\s*$')
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_VS = re.compile(r"\s+(?:vs\.?|versus|v\.)\s+", re.I)


def _norm_scr(text: str) -> str | None:
    m = scdata.SCR.search(text)
    return f"{m.group(1)} {m.group(2).lower()} {m.group(3)}" if m else None


def _norm_insc(text: str) -> str | None:
    m = scdata.INSC.search(text.replace(":", " "))
    return f"{m.group(1)} {int(m.group(2))}" if m else None


class SupremeCourtData:
    name = "supreme-court-open-data"
    report_series = ("SCR",)  # the only report series whose numbers appear in this data (SCC and AIR do not)

    def __init__(self, root: str | Path, records: list[scdata.Judgment] | None = None):
        self.root = Path(root)
        recs = records
        if recs is None:
            recs = []
            for y in range(1950, date.today().year + 2):
                recs += scdata.read_year(self.root, y)
            recs = scdata.merge_duplicates(recs)
        if not recs:
            raise SourceDown("The Supreme Court dataset is not on this machine (run scripts/opendata_download.py).")
        self.records = {r.stem: r for r in recs}
        self.by_neutral: dict[str, list[str]] = {}
        self.by_scr: dict[str, list[str]] = {}
        self.by_token: dict[str, set[str]] = {}
        for r in recs:
            if r.neutral:
                self.by_neutral.setdefault(_norm_insc(r.neutral) or "", []).append(r.stem)
            if r.scr:
                self.by_scr.setdefault(_norm_scr(r.scr) or "", []).append(r.stem)
            for tok in _tokens(r.petitioner) | _tokens(r.respondent):
                self.by_token.setdefault(tok, set()).add(r.stem)
        stamps = [r.scraped_at[:10] for r in recs if r.scraped_at]
        self.as_of: date = date.fromisoformat(max(stamps)) if stamps else date.min  # the newest page the dataset holds

    # ------------------------------------------------------------ what a report must say about this source
    def attribution(self) -> dict:
        return {"dataset": DATASET, "as_of": self.as_of.isoformat(), "licence": LICENCE, "registry": REGISTRY, "records": len(self.records),
                "text": f"Source: {DATASET}, data as of {self.as_of.isoformat()}. Licensed {LICENCE}; judgments from the Supreme Court of India's eCourts pages, compiled by Dattam Labs."}

    def covers(self, year: int | None) -> bool:
        """False when the cited year is later than the newest judgment the dataset holds."""
        return not year or year <= self.as_of.year

    def complete_for(self, year: int | None) -> bool:
        """Always False: that this dataset holds EVERY judgment of a year is unverified, so 'not found' can never be concluded from it."""
        return False

    # ------------------------------------------------------------ the adapter interface used by lookup.check_case
    def _candidate(self, stem: str) -> Candidate:
        r = self.records[stem]
        title = f"{r.petitioner} vs {r.respondent} on {r.year}"  # ends with the year, the form the comparison code reads
        return Candidate(self.name, stem, title, COURT, self.url_for(stem), snippet=" ".join(x for x in (r.neutral, r.scr) if x))

    def url_for(self, doc_id: str) -> str:
        r = self.records.get(doc_id)
        year = (r.folders[0] if r and r.folders else r.year if r else doc_id.split("_")[0])
        return f"{BUCKET_URL}data/pdf/year={year}/english/{doc_id}_EN.pdf"

    async def search(self, query: str) -> list[Candidate]:
        q = (query or "").strip()
        quoted = _QUOTED.match(q)
        if quoted:  # a quoted query is a citation: neutral or report
            inner = quoted.group(1)
            insc = _norm_insc(inner)
            if insc:
                return [self._candidate(s) for s in self.by_neutral.get(insc, [])[:20]]
            scr = _norm_scr(inner)
            if scr:
                return [self._candidate(s) for s in self.by_scr.get(scr, [])[:20]]
            return []  # SCC, AIR and other report series are not in this data: no match is possible, and the caller must not read this as "not found"
        parts = _VS.split(q, maxsplit=1)
        if len(parts) != 2:
            return []
        year_m = _YEAR.findall(parts[1])
        year = int(year_m[-1]) if year_m else None
        a, b = parts[0], _YEAR.sub("", parts[1]).strip()
        pool = None
        for tok in sorted(_tokens(a) | _tokens(b), key=lambda t: len(self.by_token.get(t, ()))):
            hits = self.by_token.get(tok)
            if hits:
                pool = hits
                break
        out = []
        for stem in sorted(pool or ()):
            r = self.records[stem]
            if year and abs(r.year - year) > 1:
                continue
            if (_side_matches(a, r.petitioner) and _side_matches(b, r.respondent)) or (_side_matches(a, r.respondent) and _side_matches(b, r.petitioner)):
                out.append(self._candidate(stem))
            if len(out) >= 20:
                break
        return out

    async def fetch(self, doc_id: str) -> dict:
        """{"title", "text", "blocks"}: a header built from the dataset's own metadata (so the citations on the page can be compared), then the judgment's paragraphs read from the local PDF."""
        r = self.records.get(doc_id)
        if not r:
            raise SourceDown("That judgment is not in the dataset.")
        try:
            pdf = self._pdf_bytes(r)
            blocks = judgment_blocks(pdf)
        except (OSError, KeyError, tarfile.TarError, ValueError) as exc:
            raise SourceDown(f"The judgment's file could not be read from the local dataset ({type(exc).__name__}).") from exc
        header = f"Equivalent citations: {r.scr or '(none shown)'}; {r.neutral or '(none shown)'}. {r.petitioner} versus {r.respondent}."
        if not readable(blocks):  # a table, a non-English file or a bad scan: its text cannot be trusted to contain a quote, so none is offered (the quote check then says "not checked")
            return {"title": r.title, "text": header, "blocks": []}
        return {"title": r.title, "text": header + " " + " ".join(blocks), "blocks": [header] + blocks}

    def _pdf_bytes(self, r: scdata.Judgment) -> bytes:
        name = f"{r.stem}_EN.pdf"
        for folder in (r.folders or [r.year]):
            tar = _open_tar(str(self.root / "data" / "tar" / f"year={folder}" / "english" / "english.tar"))
            try:
                return tar.extractfile(tar.getmember(name)).read()
            except KeyError:
                continue  # this year's archive does not hold it; the other folder may
        raise KeyError(name)


@lru_cache(maxsize=6)
def _open_tar(path: str) -> tarfile.TarFile:
    return tarfile.open(path)


COMMON = frozenset("the of and to in that is was for a".split())


def readable(blocks: list[str]) -> bool:
    """True when the extracted text looks like English prose. Measured on 60 real judgments (1964-2026): prose has letters in at least 0.88 of its non-space characters and common English
    words as about a quarter of its words; the one file that failed (a 2024 table-like file) had 0.79 and 0.16. The cut-offs sit between those."""
    text = " ".join(blocks)
    chars = [c for c in text if not c.isspace()]
    words = text.split()
    if len(words) < 150 or not chars:
        return False
    alpha = sum(c.isalpha() for c in chars) / len(chars)
    common = sum(1 for w in words if w.lower().strip(".,;:()") in COMMON) / len(words)
    return alpha >= 0.85 and common >= 0.18


NUMBERED = re.compile(r"\n(?=\s*\d{1,3}\.\s+\S)")


def judgment_blocks(pdf: bytes) -> list[str]:
    """Paragraph blocks of a judgment PDF: the page texts joined, cut before each numbered paragraph and at blank lines. Whitespace is tidied; no word is changed."""
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    blocks: list[str] = []
    for chunk in re.split(r"\n\s*\n", NUMBERED.sub("\n\n", text)):
        chunk = " ".join(chunk.split())
        if chunk:
            blocks.append(chunk)
    return blocks
