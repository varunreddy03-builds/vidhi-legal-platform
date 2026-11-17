"""A search index over the PARAGRAPHS of judgments whose text is loaded (Tantivy, like lib/judgment_index.py), so a question can be answered with "paragraph 14 of this judgment".

MongoDB stays the source of truth. A hit is only (judgment id, paragraph number, start, end): the words themselves are read from the judgment's stored text, so the index cannot say anything the judgment
does not. It can be deleted and rebuilt at any time (`python scripts/passage_index_build.py`). If it is missing, unreadable or Tantivy is not installed, `search` returns None and `find` falls back to a plain
scan of the one judgment's paragraphs: slower for many judgments, but correct.

Paragraph numbers are the ones printed in the judgment; a judgment with no readable numbering is indexed by blank-line blocks and its hits have n = None (see lib/judgment_paragraphs.py)."""

import json
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from lib import judgment_paragraphs as jp

logger = logging.getLogger(__name__)
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "passage_index"
STATE_FILE = "vidhi_passage_state.json"
SCHEMA_VERSION = 1
MAX_TEXT = 400_000  # characters of one judgment that are read
HEAP = 500_000_000
_lock = threading.Lock()
_open: dict = {"dir": None, "stamp": None, "index": None}


def index_dir() -> Path:
    return Path(os.environ.get("PASSAGE_INDEX_DIR") or DEFAULT_DIR)


def _tv():
    try:
        import tantivy

        return tantivy
    except ImportError:
        return None


def _schema(tv):
    sb = tv.SchemaBuilder()
    sb.add_text_field("jid", stored=True, tokenizer_name="raw")
    sb.add_integer_field("n", stored=True, indexed=True)  # -1 = no printed number
    sb.add_integer_field("start", stored=True, indexed=False)
    sb.add_integer_field("end", stored=True, indexed=False)
    sb.add_text_field("text", stored=False, tokenizer_name="en_stem")
    return sb.build()


def passages_of(text: str) -> list[dict]:
    return jp.passages(jp.split((text or "")[:MAX_TEXT])["paragraphs"])


def build(records, path: Path | None = None, threads: int = 4) -> dict:
    """Index `records` (dicts with "id" and "text"). Empties the folder first, so a rebuild is repeatable. Returns {judgments, passages, numbered, seconds}."""
    tv = _tv()
    if tv is None:
        raise RuntimeError("Tantivy is not installed (pip install tantivy).")
    path = path or index_dir()
    t0 = time.time()
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    index = tv.Index(_schema(tv), path=str(path))
    writer = index.writer(heap_size=HEAP, num_threads=threads)
    judgments = numbered = n_pass = 0
    for r in records:
        text = (r.get("text") or "")[:MAX_TEXT]
        if not text.strip():
            continue
        parsed = jp.split(text)
        judgments += 1
        numbered += parsed["method"] == "numbered"
        for p in jp.passages(parsed["paragraphs"]):
            d = tv.Document()
            d.add_text("jid", str(r["id"]))
            d.add_integer("n", -1 if p["n"] is None else int(p["n"]))
            d.add_integer("start", int(p["start"]))
            d.add_integer("end", int(p["end"]))
            d.add_text("text", p["text"])
            writer.add_document(d)
            n_pass += 1
    writer.commit()
    del writer
    (path / STATE_FILE).write_text(json.dumps({"schema": SCHEMA_VERSION, "judgments": judgments, "passages": n_pass, "numbered": numbered, "built_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    _forget()
    return {"judgments": judgments, "passages": n_pass, "numbered": numbered, "seconds": round(time.time() - t0, 1)}


def read_state(path: Path | None = None) -> dict | None:
    try:
        return json.loads(((path or index_dir()) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _forget() -> None:
    with _lock:
        _open.update(dir=None, stamp=None, index=None)


def _index():
    """The open index, or None (missing folder, no state file, another schema, Tantivy absent). Re-opened when the state file changes (a rebuild)."""
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
        except Exception as exc:  # noqa: BLE001 - a damaged folder means "no index", not an error page
            logger.warning("passage index could not be opened (%s): scanning the judgment instead", type(exc).__name__)
            return None
        _open.update(dir=str(path), stamp=stamp, index=index)
        return index


def available() -> bool:
    return _index() is not None


def words(q: str) -> list[str]:
    return re.findall(r"\w{2,}", (q or "").lower(), re.U)[:12]


def search(terms: list[str], jid: str | None = None, limit: int = 10) -> list[dict] | None:
    """The best paragraphs (all `terms` present): [{jid, n, start, end, score}]. None when there is no usable index (the caller uses `scan`)."""
    index = _index()
    ws = [w for w in terms if re.fullmatch(r"\w{2,}", w, re.U)]
    if index is None or not ws:
        return None
    try:
        q = " ".join(f"+{w}" for w in ws)
        if jid:
            if not re.fullmatch(r"[\w.\-:/]{1,200}", jid):
                return None
            q += f' +jid:"{jid}"'
        searcher = index.searcher()
        res = searcher.search(index.parse_query(q, ["text"]), limit)
        out = []
        for score, addr in res.hits:
            d = searcher.doc(addr)
            n = d["n"][0]
            out.append({"jid": d["jid"][0], "n": None if n < 0 else n, "start": d["start"][0], "end": d["end"][0], "score": round(score, 3)})
        return out
    except Exception as exc:  # noqa: BLE001 - never let the index break the page
        logger.warning("passage index search failed (%s): scanning the judgment instead", type(exc).__name__)
        return None


def scan(text: str, terms: list[str], limit: int = 10) -> list[dict]:
    """The same answer without an index, for ONE judgment: paragraphs that hold every term, the ones that hold them most often first."""
    ws = [w.lower() for w in terms if w]
    hits = []
    for p in passages_of(text):
        low = p["text"].lower()
        if ws and all(w in low for w in ws):
            hits.append({"jid": None, "n": p["n"], "start": p["start"], "end": p["end"], "score": float(sum(low.count(w) for w in ws))})
    return sorted(hits, key=lambda h: -h["score"])[:limit]


def find(jid: str, text: str, query: str, limit: int = 10) -> dict:
    """Paragraphs of ONE judgment that answer `query`: from the index when there is one, else by scanning. {hits, source}; each hit also carries the passage read from `text`."""
    ws = words(query)
    hits = search(ws, jid=jid, limit=limit)
    source = "index"
    if hits is None:
        hits, source = scan(text, ws, limit), "scan"
    for h in hits:
        h["jid"] = jid
        h["text"] = text[h["start"]:h["end"]].strip()
    return {"hits": hits, "source": source}
