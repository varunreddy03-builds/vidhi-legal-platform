"""Load the Supreme Court case list (from the local copy of the public dataset, SC_DATA_DIR) into the same judgment collection as the High Courts.

    python scripts/sc_load_index.py [--from-year 1999] [--to-year 2026] [--root C:\vidhi-tools\data\sc] [--mongo-url mongodb://127.0.0.1:27017] [--db vidhi_dev]

The dataset knows the YEAR of a judgment, not its exact date, so the range is applied by year. Text is not stored: the app fetches the judgment's PDF when someone opens it.
Every record is "UNVERIFIED - not reviewed". Data: Indian Supreme Court Judgments, Dattam Labs, CC-BY-4.0."""

import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo import ASCENDING, MongoClient  # noqa: E402
from pymongo.errors import BulkWriteError  # noqa: E402

from lib import verified_store as vstore  # noqa: E402
from lib.script_detect import stored_script  # noqa: E402
from lib.refcheck import scdata  # noqa: E402
from lib.refcheck.scsource import BUCKET_URL  # noqa: E402

STATUS = "UNVERIFIED - not reviewed"
ATTRIBUTION = "Indian Supreme Court Judgments, Dattam Labs, from the Supreme Court's eCourts pages, licence CC-BY-4.0: https://registry.opendata.aws/indian-supreme-court-judgments"
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


NAME_TOKEN = re.compile(r"^(?:[A-Z][A-Z.'\-]*[,.*]?|[*,.])$")


def judges(bench: str | None) -> str | None:
    """The judges' names at the start of the dataset's "bench" field (capital-letter words); whatever follows (a headnote, a report reference) is dropped."""
    kept: list[str] = []
    for tok in (bench or "").split():
        if not NAME_TOKEN.match(tok):
            break
        kept.append(tok)
    while kept and re.fullmatch(r"[A-Z]\.?|[*,.]", kept[-1]):  # a stray "A B" or "." left at the end belongs to the headnote
        kept.pop()
    return " ".join(kept).replace(" *", "").replace(" ,", ",").strip(" ,.")[:120] or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-year", type=int, default=1999)
    ap.add_argument("--to-year", type=int, default=2026)
    ap.add_argument("--root", default=r"C:\vidhi-tools\data\sc")
    ap.add_argument("--mongo-url", default="mongodb://127.0.0.1:27017")
    ap.add_argument("--db", default="vidhi_dev")
    a = ap.parse_args()
    recs = []
    for y in range(a.from_year, a.to_year + 1):
        recs += scdata.read_year(Path(a.root), y)
    recs = scdata.merge_duplicates(recs)
    col = vstore.sync_collection(MongoClient(a.mongo_url)[a.db], "hc_judgments")
    col.create_index([("id", ASCENDING)], name="id", unique=True)
    col.create_index([("court_code", ASCENDING), ("decision_date", ASCENDING)], name="court_date")
    docs = []
    for r in recs:
        if not (a.from_year <= r.year <= a.to_year):
            continue
        year = r.folders[0] if r.folders else r.year
        title = f"{r.petitioner} vs {r.respondent}".strip(" vs")
        docs.append({
            **({"script": s} if (s := stored_script(" ".join(x for x in (r.neutral, r.scr) if x), title)) else {}),
            "id": f"sc-{r.stem}", "court_code": "SC", "bench": "", "year": r.year, "court_name": "Supreme Court of India", "case_title": f"{r.petitioner} vs {r.respondent}".strip(" vs"),
            "judge": judges(r.bench), "cnr": None,  # the dataset's "bench" field is the judges' names, sometimes followed by the headnote
             "registration_date": None, "decision_date": None, "disposal": None, "citation": " ; ".join(x for x in (r.neutral, r.scr) if x) or None,
            "snippet": " ".join(x for x in (r.neutral, r.scr) if x), "pdf_exists": True, "source_url": f"{BUCKET_URL}data/pdf/year={year}/english/{r.stem}_EN.pdf",
            "text": "", "text_chars": 0, "text_kind": "NOT_LOADED", "text_sha256": EMPTY_SHA, "licence": "CC-BY-4.0", "attribution": ATTRIBUTION, "status": STATUS, "origin": "bulk",
        })
    n = 0
    for i in range(0, len(docs), 5000):
        try:
            col.insert_many(docs[i : i + 5000], ordered=False)
        except BulkWriteError:
            pass  # already loaded in an earlier run
        n += len(docs[i : i + 5000])
    print(f"Supreme Court: {n} judgments for {a.from_year} to {a.to_year}; collection holds {col.estimated_document_count()}")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
