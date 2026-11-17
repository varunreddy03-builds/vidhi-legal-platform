"""Reads the Supreme Court open dataset (registry.opendata.aws/indian-supreme-court-judgments, CC-BY-4.0, Dattam Labs) from the local copy made by scripts/opendata_download.py.

What the dataset gives per judgment (checked on real files, 2026-10-27): a metadata JSON {raw_html, path, citation_year, nc_display, scraped_at} and the judgment as an English PDF with the
same stem (`2024_10_108_125.json` <-> `2024_10_108_125_EN.pdf`). The parties, the SCR report citation ("[2024] 10 S.C.R. 108"), the neutral citation ("2024 INSC 735") and the bench are
INSIDE raw_html, so this module reads them out of that HTML. Nothing here guesses: a field that is not on the page stays empty. SCC and AIR numbers are not in the data.

The metadata is indexed up front (small). The judgment text is NOT pre-extracted: it is read from the local archive for the one judgment a citation matched, when a quote or a point has to
be checked (the archives are about 21 GiB; reading 43,000 PDFs in advance would take hours and its quality is unverified)."""

import html
import re
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

TAGS = re.compile(r"<[^>]+>")
SCR = re.compile(r"\[\s*((?:19|20)\d{2})\s*\]\s*(\d{1,3}|Supp\.?)\s*S\.?C\.?R\.?\s*(\d{1,5})", re.I)
INSC = re.compile(r"\b((?:19|20)\d{2})\s*INSC\s*(\d{1,5})\b")
VERSUS = re.compile(r"^(?:versus|vs\.?|v\.?)$", re.I)
NOISE = re.compile(r"(Disclaimer|Judgments in\s+regional|Supreme Court Registry|Visitors to the site|The information made available|National Informatics|translation)", re.I)


@dataclass
class Judgment:
    stem: str  # '2024_10_108_125': the file name without extension, same for the metadata and the PDF
    year: int
    petitioner: str = ""
    respondent: str = ""
    neutral: str = ""  # '2024 INSC 735' when the page shows one
    scr: str = ""  # '[2024] 10 SCR 108' when the page shows one
    bench: str = ""
    nc_display: str = ""  # the dataset's own neutral-citation field, as given
    scraped_at: str = ""
    folders: list = field(default_factory=list)  # the year folders that hold this judgment (the same judgment can sit in two: decided in one year, reported in the next)

    @property
    def title(self) -> str:
        return f"{self.petitioner} versus {self.respondent}".strip()

    def as_row(self) -> dict:
        return {"stem": self.stem, "year": self.year, "petitioner": self.petitioner, "respondent": self.respondent, "neutral": self.neutral, "scr": self.scr,
                "bench": self.bench, "nc_display": self.nc_display, "scraped_at": self.scraped_at}


def page_lines(raw_html: str) -> list[str]:
    """The visible text of the saved page, one non-empty line per block, with the court's standing disclaimers removed."""
    text = html.unescape(TAGS.sub("\n", raw_html or ""))
    out = []
    for line in text.splitlines():
        line = " ".join(line.split())
        if line and not NOISE.search(line) and line not in ("English", "|"):
            out.append(line)
    return out


def parse_record(meta: dict, stem: str, year: int) -> Judgment:
    j = Judgment(stem=stem, year=year, nc_display=str(meta.get("nc_display") or ""), scraped_at=str(meta.get("scraped_at") or ""))
    lines = page_lines(meta.get("raw_html", ""))
    for i, line in enumerate(lines):
        if VERSUS.match(line) and 0 < i < len(lines) - 1:
            j.petitioner, j.respondent = lines[i - 1], lines[i + 1]
            break
    blob = " ".join(lines[:40])
    m = INSC.search(blob) or INSC.search(j.nc_display.replace("INSC", " INSC "))
    if m:
        j.neutral = f"{m.group(1)} INSC {int(m.group(2))}"
    s = SCR.search(blob)
    if s:
        j.scr = f"[{s.group(1)}] {s.group(2)} SCR {int(s.group(3)) if s.group(3).isdigit() else s.group(3)}"
    c = re.search(r"Coram\s*:\s*(.+?)(?:\s+Issue for Consideration|\s+Headnotes|$)", " ".join(lines[:60]))
    if c:
        j.bench = c.group(1).strip(" *")[:200]
    return j


def merge_duplicates(records: list[Judgment]) -> list[Judgment]:
    """One record per judgment. Checked on the real data: 43,578 listed entries are 38,397 distinct judgments, because 5,181 appear in two year folders. The decision year is the year in
    the neutral citation when there is one, else the earliest folder; `folders` keeps every folder so the file can be found."""
    by: dict[str, Judgment] = {}
    for r in records:
        if r.stem not in by:
            by[r.stem] = r
            r.folders = [r.year]
        elif r.year not in by[r.stem].folders:
            by[r.stem].folders.append(r.year)
    for r in by.values():
        r.folders.sort()
        m = INSC.search(r.neutral or "")
        r.year = int(m.group(1)) if m else r.folders[0]
    return list(by.values())


def read_year(root: Path, year: int) -> list[Judgment]:
    path = root / "metadata" / "tar" / f"year={year}" / "metadata.tar"
    if not path.exists():
        return []
    import json

    out = []
    with tarfile.open(path) as t:
        for member in t:
            if member.isfile() and member.name.endswith(".json"):
                try:
                    meta = json.load(t.extractfile(member))
                except ValueError:
                    continue
                out.append(parse_record(meta, member.name[:-5], year))
    return out
