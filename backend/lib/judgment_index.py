"""A fast search index over the court case list (Tantivy), so a common word such as "bail" ranks the best 20 of millions of cases in milliseconds.

MongoDB stays the source of truth. The index holds only what is needed to FIND a case (its id, title, court, year and the searchable words); a hit is just a judgment id, and the case itself
is read from MongoDB, so nothing here can say anything about a judgment that the record does not. The index can be thrown away and rebuilt at any time:

    python scripts/judgment_index_build.py            # rebuild from scratch (repeatable)
    python scripts/judgment_index_build.py --update   # add the cases loaded since, and refresh the cases whose text was loaded

If the index is missing, unreadable, or Tantivy is not installed, `search` returns None and the caller uses the older MongoDB text search: nothing breaks, it is only slower on common words."""

import json
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "judgment_index"
STATE_FILE = "vidhi_index_state.json"
SCHEMA_VERSION = 1
MAX_BODY = 400_000  # characters of one judgment's text that are indexed
HEAP = 1_500_000_000
_lock = threading.Lock()
_open: dict = {"dir": None, "stamp": None, "index": None}
_warned = {"x": False}


def index_dir() -> Path:
    return Path(os.environ.get("JUDGMENT_INDEX_DIR") or DEFAULT_DIR)


def _tv():
    try:
        import tantivy

        return tantivy
    except ImportError:
        return None


def _schema(tv):
    sb = tv.SchemaBuilder()
    sb.add_text_field("id", stored=True, tokenizer_name="raw")
    sb.add_text_field("title", stored=False, tokenizer_name="en_stem")
    sb.add_text_field("body", stored=False, tokenizer_name="en_stem")
    sb.add_text_field("court", stored=False, tokenizer_name="raw")
    sb.add_integer_field("year", stored=False, indexed=True, fast=True)
    return sb.build()


def _doc(tv, r: dict):
    d = tv.Document()
    d.add_text("id", str(r["id"]))
    d.add_text("title", str(r.get("case_title") or ""))
    body = " ".join(str(x) for x in (r.get("court_name"), r.get("judge"), r.get("disposal"), r.get("cnr"), r.get("snippet")) if x and str(x) != "None")
    text = r.get("text") or ""
    d.add_text("body", (body + " " + text[:MAX_BODY]).strip())
    d.add_text("court", str(r.get("court_code") or ""))
    try:
        d.add_integer("year", int(r.get("year") or 0))
    except (TypeError, ValueError):
        d.add_integer("year", 0)
    return d


def _write_state(path: Path, **fields) -> None:
    state = {"schema": SCHEMA_VERSION, "updated_at": datetime.now(timezone.utc).isoformat(), **fields}
    (path / STATE_FILE).write_text(json.dumps(state), encoding="utf-8")


def read_state(path: Path | None = None) -> dict | None:
    try:
        return json.loads(((path or index_dir()) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build(records, path: Path | None = None, *, rebuild: bool = True, threads: int = 8, commit_every: int = 1_000_000, progress=None) -> dict:
    """Index `records` (dicts shaped like hc_judgments rows, each with an "_id" in increasing order for the --update watermark). rebuild=True empties the folder first, so a rebuild is repeatable.
    Returns {docs, seconds, watermark}."""
    tv = _tv()
    if tv is None:
        raise RuntimeError("Tantivy is not installed (pip install tantivy).")
    path = path or index_dir()
    t0 = time.time()
    if rebuild and path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    index = tv.Index(_schema(tv), path=str(path))
    writer = index.writer(heap_size=HEAP, num_threads=threads)
    n, last = 0, None
    for r in records:
        writer.add_document(_doc(tv, r))
        n += 1
        last = str(r.get("_id", last))
        if n % commit_every == 0:
            writer.commit()
            if progress:
                progress(n)
    writer.commit()
    del writer  # a second writer can only be opened once this one is released
    old = read_state(path) or {}
    total = (old.get("docs", 0) if not rebuild else 0) + n
    _write_state(path, docs=total, watermark=last or old.get("watermark"), built_at=old.get("built_at") if (not rebuild and old.get("built_at")) else datetime.now(timezone.utc).isoformat())
    _forget()
    return {"docs": total, "added": n, "seconds": round(time.time() - t0, 1), "watermark": last}


def refresh(records, path: Path | None = None) -> int:
    """Replace the entries of cases whose text has been loaded since (delete by id, add again). Returns how many were refreshed."""
    tv = _tv()
    path = path or index_dir()
    if tv is None or read_state(path) is None:
        return 0
    index = tv.Index.open(str(path))
    writer = index.writer(heap_size=300_000_000, num_threads=2)
    n = 0
    for r in records:
        writer.delete_documents("id", str(r["id"]))
        writer.add_document(_doc(tv, r))
        n += 1
    writer.commit()
    del writer
    _forget()
    return n


def _forget() -> None:
    with _lock:
        _open.update(dir=None, stamp=None, index=None)


def _index():
    """The open index, or None when there is none (missing folder, no state file, a different schema, or Tantivy absent). Re-opened when the state file changes (a rebuild)."""
    tv = _tv()
    if tv is None:
        return None
    path = index_dir()
    try:
        stamp = (path / STATE_FILE).stat().st_mtime_ns
    except OSError:
        return None
    with _lock:
        if _open["index"] is not None and _open["dir"] == str(path) and _open["stamp"] == stamp:
            return _open["index"]
        state = read_state(path)
        if not state or state.get("schema") != SCHEMA_VERSION:
            return None
        try:
            index = tv.Index.open(str(path))
        except Exception as exc:  # noqa: BLE001 - a damaged folder must mean "no index", not an error page
            if not _warned["x"]:
                logger.warning("judgment index could not be opened (%s): using the MongoDB text search", type(exc).__name__)
                _warned["x"] = True
            return None
        _open.update(dir=str(path), stamp=stamp, index=index)
        return index


def available() -> bool:
    return _index() is not None


def status() -> dict:
    st = read_state()
    return {"available": available(), "dir": str(index_dir()), **({k: st.get(k) for k in ("docs", "watermark", "built_at", "updated_at")} if st else {})}


def search(terms: list[str], court: "str | list[str] | None" = None, year_from: int | None = None, year_to: int | None = None, skip: int = 0, limit: int = 20) -> dict | None:
    """Ids of the best matches (all `terms` must appear), best first, and how many cases match. None when there is no usable index: the caller then uses the MongoDB text search."""
    index = _index()
    if index is None or not terms:
        return None
    try:
        words = [w for w in terms if re.fullmatch(r"\w{2,}", w, re.U)]
        if not words:
            return None
        q = " ".join(f"+{w}" for w in words)
        codes = [court] if isinstance(court, str) else list(court or [])
        codes = [c for c in codes if re.fullmatch(r"[A-Za-z0-9_]{1,20}", c)]
        if court and not codes:
            return {"ids": [], "total": 0}  # a court filter with no usable code matches nothing; it is never dropped
        if codes:
            q += " +(" + " ".join(f'court:"{c}"' for c in codes) + ")"
        if year_from or year_to:
            q += f" +year:[{int(year_from or 0)} TO {int(year_to or 9999)}]"
        searcher = index.searcher()
        query = index.parse_query(q, ["title", "body"], field_boosts={"title": 3.0})
        res = searcher.search(query, limit, count=True, offset=max(0, skip))
        return {"ids": [searcher.doc(h[1])["id"][0] for h in res.hits], "total": res.count}
    except Exception as exc:  # noqa: BLE001 - never let the index break the page
        if not _warned["x"]:
            logger.warning("judgment index search failed (%s): using the MongoDB text search", type(exc).__name__)
            _warned["x"] = True
        return None
