"""High Court judgments, for LOOKING THINGS UP. Source: the public dataset "Indian High Court Judgments" (AWS Open Data, CC-BY-4.0, Dattam Labs, taken from eCourts), 25 High Courts.

* A record is built only from the dataset's own metadata file and the text of its PDF. Nothing is summarised, rewritten or completed here.
* Every record is "not reviewed": no lawyer has compared it with the court's own copy. It can never make a claim VERIFIED. Whether a judgment is still good law,
  was appealed or was overruled is not known to this module, and the view says so.
* Text comes from the PDF's own text layer; a scanned judgment is read by OCR (scripts/ocr_pdf.py) and is then marked as OCR. A file that cannot be opened is kept, marked unreadable.
* Records are files in data/hc_judgments/*.jsonl (written by scripts/hc_ingest.py) and are copied into MongoDB at start-up."""

import hashlib
import html
import json
import logging
import os
import asyncio
import re
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from lib import chunk_contract, court_hierarchy, judgment_index
from lib.script_detect import NAMES as SCRIPT_NAMES
from lib.script_detect import stored_script
from lib import verified_store as store
from lib.db import db

logger = logging.getLogger("vidhi.hc")

DEFAULT_DIR = Path(os.path.abspath(__file__)).parent.parent / "data" / "hc_judgments"
BUCKET = "https://indian-high-court-judgments.s3.ap-south-1.amazonaws.com"
STATUS = "UNVERIFIED - not reviewed"
LICENCE = "CC-BY-4.0"
ATTRIBUTION = "Indian High Court Judgments, Dattam Labs, from the eCourts website, licence CC-BY-4.0: https://registry.opendata.aws/indian-high-court-judgments"
NOTE = (
    "Not reviewed: this judgment was read from the public High Court dataset by a program. Nobody has compared it with the court's own copy, and it does not say whether the "
    "judgment was later appealed, set aside or overruled. Read the court's own copy before relying on it."
)
TEXT_KINDS = ("TEXT", "OCR", "UNREADABLE", "NOT_LOADED", "NO_TEXT_LAYER")
# NOT_LOADED = only the case details are stored; the text is fetched from the public archive when someone opens the judgment. NO_TEXT_LAYER = the court's PDF is a picture (needs OCR).
ORIGIN_FILE = "sample-file"  # records that come from data/hc_judgments/*.jsonl; the bulk-loaded case lists (scripts/hc_load_metadata.py, scripts/sc_load_index.py) have origin "bulk"
ALLOWED_HOSTS = ("https://indian-high-court-judgments.s3.ap-south-1.amazonaws.com/", "https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com/")
MAX_PDF_BYTES = 15 * 1024 * 1024
MIN_TEXT = 200
COUNT_CAP = 10000


def sha256_text(t: str) -> str:
    return hashlib.sha256((t or "").encode("utf-8")).hexdigest()


def _clean(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def _iso(d: str) -> str | None:
    m = re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})", d or "")
    if not m:
        return None
    try:
        return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
    except ValueError:
        return None


def parse_metadata(meta: dict) -> dict:
    """The dataset's raw metadata record (court, an HTML snippet, the PDF path) into plain fields. A field the snippet does not contain is None, never filled in."""
    h = meta.get("raw_html", "") or ""

    def field(rx: str) -> str | None:
        m = re.search(rx, h, re.S)
        return _clean(m.group(1)) if m and _clean(m.group(1)) else None

    title = field(r"<font size='3'>(.*?)</button>") or field(r"<font[^>]*>([^<]*\bvs\b[^<]*)</font>")
    return {
        "court_name": _clean(meta.get("court_name", "")),
        "case_title": title,
        "judge": field(r"Judge\s*:\s*([^<]+)"),
        "cnr": field(r"CNR :</span><font[^>]*>\s*([^<]+)"),
        "registration_date": _iso(field(r"Date of registration :</span><font[^>]*>\s*([^<]+)") or ""),
        "decision_date": _iso(field(r"Decision Date :</span><font[^>]*>\s*([^<]+)") or ""),
        "disposal": field(r"Disposal Nature :</span><font[^>]*>\s*([^<]+)"),
    }


def build_record(meta: dict, name: str, year: str, court: str, bench: str, text: str, text_kind: str) -> dict:
    assert text_kind in TEXT_KINDS
    p = parse_metadata(meta)
    s = stored_script(text[:400], p.get("case_title"))
    return {
        **({"script": s} if s else {}),
        "id": f"hc-{court}-{bench}-{name}",
        "court_code": court,
        "bench": bench,
        "year": int(year),
        **p,
        "source_url": f"{BUCKET}/data/pdf/year={year}/court={court}/bench={bench}/{name}.pdf",
        "text": text,
        "text_chars": len(text),
        "text_kind": text_kind,  # TEXT = the PDF's own text, OCR = read from a picture by a program, UNREADABLE = the file could not be opened
        "text_sha256": sha256_text(text),
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
        "status": STATUS,
    }


def validate_record(r: dict) -> list[str]:
    errs = [f"missing {k}" for k in ("id", "court_code", "court_name", "source_url", "text_kind", "text_sha256") if not r.get(k)]
    if r.get("text_kind") not in TEXT_KINDS:
        errs.append("bad text_kind")
    if r.get("status") != STATUS:
        errs.append("status must be the not-reviewed status; a judgment record can never be marked verified")
    if r.get("text_sha256") != sha256_text(r.get("text", "")):
        errs.append("text does not match its hash")
    return errs


def load_records(folder: Path | None = None) -> tuple[list[dict], list[str]]:
    folder = Path(folder or os.environ.get("HC_JUDGMENTS_DIR") or DEFAULT_DIR)
    out, bad, seen = [], [], set()
    if not folder.is_dir():
        return out, bad
    for f in sorted(folder.glob("*.jsonl")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                bad.append(f"{f.name}:{n} unreadable")
                continue
            errs = validate_record(r) + (["duplicate id"] if r.get("id") in seen else [])
            if errs:
                bad.append(f"{f.name}:{n} {r.get('id')}: {'; '.join(errs)}")
                continue
            seen.add(r["id"])
            out.append(r)
    return out, bad


async def sync_judgments(folder: Path | None = None) -> dict:
    recs, bad = load_records(folder)
    for b in bad:
        logger.error("high court judgments: rejected %s", b)
    now = datetime.now(timezone.utc)
    digest = sha256_text("|".join(f"{r['id']}:{r['text_sha256']}" for r in recs))
    state = await db.library_state.find_one({"_id": "hc_judgments"})
    await store.delete(db, "hc_judgments", {"origin": ORIGIN_FILE, "id": {"$nin": [r["id"] for r in recs]}})  # only the records that came from files: bulk-loaded case lists are left alone
    if state and state.get("digest") == digest and await db.hc_judgments.count_documents({"origin": ORIGIN_FILE}) == len(recs):
        return {"judgments": len(recs), "rejected": len(bad)}
    await store.replace_many(db, "hc_judgments", [{**r, "origin": ORIGIN_FILE, "synced_at": now} for r in recs], batch=200)
    await db.library_state.update_one({"_id": "hc_judgments"}, {"$set": {"digest": digest, "synced_at": now}}, upsert=True)
    return {"judgments": len(recs), "rejected": len(bad)}


def view(r: dict, excerpt: int = 500) -> dict:
    """What a reader sees: always labelled not reviewed, with the attribution the licence asks for."""
    text = r.get("text") or ""
    return {
        "id": r["id"], "court_code": r["court_code"], "court_name": r.get("court_name", ""), "bench": r.get("bench", ""), "year": r.get("year"),
        "case_title": r.get("case_title"), "judge": r.get("judge"), "cnr": r.get("cnr"), "decision_date": r.get("decision_date"), "registration_date": r.get("registration_date"),
        "disposal": r.get("disposal"), "source_url": r.get("source_url", ""), "text_kind": r.get("text_kind"), "text_chars": r.get("text_chars", len(text)),
        "excerpt": text[:excerpt] if text else (r.get("snippet") or "")[:excerpt], "citation": r.get("citation"), "script": chunk_contract.judgment_fields(r)["script"],
        "contract": chunk_contract.judgment_fields(r), "licence": r.get("licence", LICENCE), "attribution": r.get("attribution", ATTRIBUTION), "status": STATUS, "note": NOTE,
    }


_COURTS: dict = {"at": 0.0, "rows": []}


async def courts() -> list[dict]:
    """Every court with its number of judgments. Counting millions of rows takes a while, so the answer is kept for ten minutes."""
    if _COURTS["rows"] and time.monotonic() - _COURTS["at"] < 600:
        return _COURTS["rows"]
    rows = []
    for code in await db.hc_judgments.distinct("court_code"):  # distinct and count both run on the court_date index; grouping over millions of full records does not
        one = await db.hc_judgments.find_one({"court_code": code}, {"court_name": 1, "_id": 0})
        rows.append({"court_code": code, "court_name": (one or {}).get("court_name", code), "count": await db.hc_judgments.count_documents({"court_code": code})})
    rows.sort(key=lambda r: r["court_name"])
    _COURTS.update(at=time.monotonic(), rows=rows)
    return _COURTS["rows"]


TEXT_MAX_MS = 8000  # a text search over millions of records must never run for minutes
RANK_MAX_MS = 2500  # how long ranking by relevance may take before the first matches are returned unranked
TEXT_TERMS = 5
COMMON = frozenset("what does did the say said about and for from with that this those these which whether under upon shall may can will would should could not any all are was were has have had been being into law laws court courts section sections act acts case cases held order judgment judgement high supreme india indian state states party parties petition petitioner respondent appeal".split())  # words in nearly every judgment: they rank nothing, and requiring them would hide good matches


class SearchTooBroad(Exception):
    """The words matched so many judgments that ranking them took too long."""


def text_words(q: str) -> list[str]:
    """The words a question is searched by: a few words as typed; a long question (many words, most of them common) only its TEXT_TERMS longest words. All of them must appear."""
    words = list(dict.fromkeys(w.lower() for w in re.findall(r"\w{2,}", q or "", re.U)))
    if len(words) <= 3:
        return words
    words = [w for w in words if w not in COMMON] or words
    longest = set(sorted(words, key=len, reverse=True)[:TEXT_TERMS])
    return [w for w in words if w in longest]


def text_terms(q: str) -> str:
    """The MongoDB text-index query for some words. A few words are searched as typed; a longer question as its longest words, each in quotes (all must appear)."""
    words = text_words(q)
    n = len(set(w.lower() for w in re.findall(r"\w{2,}", q or "", re.U)))
    return " ".join(words) if n <= 3 else " ".join(f'"{w}"' for w in words)


async def _by_ids(ids: list[str]) -> list[dict]:
    """The cases for these ids, in the order given (the index ranked them; MongoDB holds the facts)."""
    rows = {r["id"]: r async for r in db.hc_judgments.find({"id": {"$in": ids}}, {"_id": 0})}
    return [rows[i] for i in ids if i in rows]


async def search(q: str = "", court: str | None = None, skip: int = 0, limit: int = 20, year_from: int | None = None, year_to: int | None = None, script: str | None = None, state: str | None = None, court_level: str | None = None) -> tuple[list[dict], int]:
    """`script` filters by the writing system of the title and opening (see lib/script_detect.py; a name from SCRIPT_NAMES, or "latin"). Almost every record is Latin, so a record stores `script` only when
    it is not Latin and "latin" means "no script stored". The search index does not hold scripts: a non-Latin script is answered from MongoDB (few records, so it is quick), and "latin" with words
    is answered by the index with the non-Latin hits dropped, so its total can be a few too many."""
    from pymongo.errors import ExecutionTimeout

    if script is not None and script not in SCRIPT_NAMES:
        raise ValueError(f"Unknown script '{script}'")
    codes = None  # the court codes the State and level filters allow (all of them together); None = no such filter
    for allowed in ([court_hierarchy.courts_for_state(state)] if state else []) + ([court_hierarchy.courts_for_level(court_level)] if court_level else []) + ([[court]] if court else []):
        codes = allowed if codes is None else [c for c in codes if c in allowed]
    if codes is not None and not codes:
        return [], 0  # e.g. a State this table does not know, or a level with no records: nothing, never "everything"
    court = codes[0] if codes and len(codes) == 1 else None
    if (q or "").strip() and script in (None, "latin"):  # the index knows no scripts: a non-Latin script goes to MongoDB below
        # The search index ranks the best matches in milliseconds, whatever the words. If it is missing or unusable the older MongoDB text search below answers instead.
        found = await asyncio.to_thread(judgment_index.search, text_words(q), (codes if codes else court) or None, year_from, year_to, skip, limit)
        if found is not None:
            rows = await _by_ids(found["ids"])
            return [{**view(r), "ranked": True} for r in rows if script != "latin" or not r.get("script")], found["total"]
    flt: dict = {}
    if codes:
        flt["court_code"] = codes[0] if len(codes) == 1 else {"$in": codes}
    if script == "latin":
        flt["script"] = {"$exists": False}
    elif script:
        flt["script"] = script
    years = {**({"$gte": year_from} if year_from else {}), **({"$lte": year_to} if year_to else {})}
    q = text_terms(q)
    if years and q:
        flt["year"] = years  # a text search cannot be combined with $or; its matches are few and ranked by score
    elif years:
        # By decision date, which the newest_first index serves; a plain year filter walks millions of records. A record with no date is judged by its year field.
        dates = {**({"$gte": f"{year_from:04d}-01-01"} if year_from else {}), **({"$lt": f"{year_to + 1:04d}-01-01"} if year_to else {})}
        flt["$or"] = [{"decision_date": dates}, {"decision_date": "", "year": years}]
    try:
        if not q:
            total = await db.hc_judgments.count_documents(flt, limit=COUNT_CAP, maxTimeMS=TEXT_MAX_MS)  # an exact count over millions of matches is slow and nobody needs it: COUNT_CAP means "at least this many"
            cur = db.hc_judgments.find(flt, {"_id": 0}).sort([("decision_date", -1), ("id", 1)])
            return [view(r) async for r in cur.skip(skip).limit(limit).max_time_ms(TEXT_MAX_MS)], total
        flt["$text"] = {"$search": q}
        try:  # ranked by relevance when that is quick; ranking millions of matches is not
            cur = db.hc_judgments.find(flt, {"score": {"$meta": "textScore"}, "_id": 0}).sort([("score", {"$meta": "textScore"})])
            items = [view(r) async for r in cur.skip(skip).limit(limit).max_time_ms(RANK_MAX_MS)]
        except ExecutionTimeout:
            cur = db.hc_judgments.find(flt, {"_id": 0})  # too many matches to rank: the first matches the index finds, labelled as not ranked
            items = [{**view(r), "ranked": False} async for r in cur.skip(skip).limit(limit).max_time_ms(TEXT_MAX_MS)]
        # Counting every text match is as slow as ranking them. A full page means "there may be more": the total is then a floor (the page shows "at least").
        return items, skip + len(items) + (1 if len(items) == limit else 0)
    except ExecutionTimeout as e:
        raise SearchTooBroad("too many matches") from e


def _download_pdf(url: str) -> bytes:
    if not url.startswith(ALLOWED_HOSTS):  # only the two public archives, never an address from anywhere else
        raise ValueError("not an archive address")
    with urllib.request.urlopen(url, timeout=40) as resp:  # noqa: S310 - host checked above
        data = resp.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("file too large")
    return data


def _pdf_text(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    return chr(10).join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages).strip()


async def get(judgment_id: str) -> dict | None:
    """The full record. For a case whose text is not stored yet, the court's PDF is fetched from the public archive now, read, and kept so the next reader does not wait."""
    r = await db.hc_judgments.find_one({"id": judgment_id}, {"_id": 0})
    if not r:
        return None
    error = None
    if r.get("text_kind") == "NOT_LOADED":
        try:
            text = await asyncio.to_thread(lambda: _pdf_text(_download_pdf(r["source_url"])))
            kind = "TEXT" if len(text) >= MIN_TEXT else "NO_TEXT_LAYER"
            if kind == "NO_TEXT_LAYER":
                text = ""
            r = {**r, "text": text, "text_chars": len(text), "text_kind": kind, "text_sha256": sha256_text(text)}
            await store.change(db, "hc_judgments", {"id": judgment_id}, {"text": text, "text_chars": len(text), "text_kind": kind, "text_sha256": r["text_sha256"]})
        except Exception as exc:  # noqa: BLE001 - network, a missing file or a broken PDF: say so, keep the case details
            logger.warning("judgment text could not be fetched for %s: %s", judgment_id, type(exc).__name__)
            error = "The text could not be fetched from the public archive right now. Open the court PDF with the link."
    return {**view(r, excerpt=0), "text": r.get("text", ""), "text_sha256": r.get("text_sha256"), **({"text_error": error} if error else {})}


async def exists(judgment_id: str) -> bool:
    return await db.hc_judgments.find_one({"id": judgment_id}, {"id": 1}) is not None
