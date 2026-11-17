"""Read how each Act says it comes into force, from the Act's OWN section 1, for the Acts whose manifest row gives no commencement date.

    python scripts/law_commencement.py [--write]

Writes data/legal_library/pending/_commencement.json: {act_id: {"basis", "date"?, "year"?, "quote"}}. basis is one of
  EXPLICIT_DATE   the Act's own words give a date ("shall come into force on 1st April 1983")
  AT_ONCE         "comes into force at once / on publication": on enactment, which happened in the year in the Act's title (the day itself is not in the text)
  PARTIAL         different provisions start at different times ("Section 6 at once, the rest from ..."): no single date for the Act
  NOTIFICATION    "on such date as the Government may by notification appoint": the real date is in a Gazette notification that is NOT in our files
  NO_CLAUSE       no commencement sentence was found in the text we hold (Rules usually take effect when published in the Gazette; that is not in the text)
Nothing is guessed: the quote is the Act's own sentence, and a date is never filled in where the text does not give one."""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import law_dates  # noqa: E402

PENDING = Path(__file__).resolve().parent.parent / "data" / "legal_library" / "pending"
OUT = Path(__file__).resolve().parent.parent / "data" / "legal_library" / "pending" / "_commencement.json"
FORCE = re.compile(r"[^.;]*\b(?:come|comes|came|deemed to have come)\s+into\s+(?:force|operation)[^.]*\.?", re.I)
NOTIFY = re.compile(r"such\s+dates?\s+as\b.{0,160}?(?:notification|appoint)", re.I | re.S)
AT_ONCE = re.compile(r"\b(?:at\s+once|forthwith|on\s+the\s+date\s+of\s+its\s+publication|on\s+its\s+publication|immediately\s+on\s+the\s+publication)", re.I)
PARTIAL = re.compile(r"^[\s(\w)]{0,12}?(?:this\s+section|sections?\b|items?\b|clauses?\b|sub-?sections?\b|chapters?\b|parts?\b|articles?\b|rules?\b)", re.I)
AFTER_PHRASE = re.compile(r"(?:force|operation)\b[^.;]{0,40}?\b(?:on|from|with\s+effect\s+from|w\.e\.f\.?)\s+(?:the\s+)?(.{0,40})", re.I)
YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


def clause(entries: list[dict]) -> str | None:
    """The sentence in which the Act says when it comes into force, from the first sections (the 'Short title, extent and commencement' section)."""
    for e in entries[:6]:
        text = re.sub(r"\s+", " ", e.get("text", ""))
        if not re.search(r"short title|commencement|come into (force|operation)", e.get("heading", "") + " " + text[:400], re.I):
            continue
        m = FORCE.search(text)
        if m:
            return m.group(0).strip()[:400]
    return None


def classify(entries: list[dict]) -> dict:
    title_year = YEAR.findall(entries[0].get("act_title", "") or entries[0].get("citation", "")) or YEAR.findall(entries[0].get("act_id", "") or "")
    year = int(title_year[-1]) if title_year else None
    q = clause(entries)
    if not q:
        return {"basis": "NO_CLAUSE", "year": year, "quote": None}
    if NOTIFY.search(q):
        return {"basis": "NOTIFICATION", "year": year, "quote": q}
    if PARTIAL.search(q) or re.search(r"remaining\s+(?:provisions|sections)", q, re.I):
        return {"basis": "PARTIAL", "year": year, "quote": q}  # different provisions start at different times: no single date for the Act
    after = AFTER_PHRASE.search(q)
    ds = law_dates.dates_in(after.group(1)) if after else []
    if ds and ds[0][0] <= 3:  # the date must come right after "into force on"; a date elsewhere in the sentence is not the start date
        return {"basis": "EXPLICIT_DATE", "date": ds[0][1].isoformat(), "year": year, "quote": q}
    if AT_ONCE.search(q) and year:
        return {"basis": "AT_ONCE", "year": year, "quote": q}
    return {"basis": "NO_CLAUSE", "year": year, "quote": q}  # a clause we could not read into a date: kept for a person to read, never turned into a guess


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    result: dict = {}
    for f in sorted(PENDING.glob("*.json")):
        if f.name.startswith("_"):
            continue
        entries = json.loads(f.read_text(encoding="utf-8")).get("entries", [])
        if not entries:
            continue
        if not entries[0].get("commencement", "").lower().startswith("not stated"):
            continue  # the manifest already gives a date for this Act
        result[entries[0].get("act_id") or f.stem] = classify(entries)
    counts: dict = {}
    for v in result.values():
        counts[v["basis"]] = counts.get(v["basis"], 0) + 1
    print(f"{len(result)} Acts without a manifest date: {counts}")
    if a.write:
        OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
