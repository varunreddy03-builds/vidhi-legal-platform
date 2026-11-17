"""The knowledge library: books and reference works, kept as TWO separate things.

* a WORK is a catalogue entry (title, author, rights, status). Importing the registry creates works and nothing else: it does not make any text available.
* CHUNKS are the indexed text of a work. They exist only after a person has recorded the work's rights AND approved ingestion. Every chunk keeps where it came from (work, chapter, position, hash).

Rules this module enforces (they come from the master expansion prompt, and tests/test_knowledge.py checks each one):
  - a status only moves forward, and never past "Registered" without written evidence;
  - "Authorized for ingestion" needs verified rights that allow full-text indexing, plus a written owner approval;
  - "Ingested" and "Indexed" are set only by ingestion itself, never by hand;
  - a repeat entry (the same work listed inside a collection) shares ONE source record, and the same text is never indexed twice;
  - library text is shared; private text belongs to one organisation and is invisible to every other;
  - search returns short excerpts with provenance and says plainly when nothing is indexed. It makes no claim a book supports anything it was not shown to support.
No embeddings, no outside service, no new dependency: search is the database's own text index, as for the legal library."""

import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pymongo.errors import BulkWriteError

from lib.db import db
from lib.script_detect import NAMES as SCRIPT_NAMES
from lib.script_detect import script_of

logger = logging.getLogger(__name__)

REGISTRY = Path(__file__).resolve().parent.parent / "data" / "knowledge" / "registry.json"
PERMISSIONS = ("private_analysis", "full_text_indexing", "commercial_use", "redistribution", "model_training")
SET_BY_SYSTEM = ("Ingested", "Indexed")
SEARCHABLE = ("Ingested", "Indexed", "Retrieval verified", "Evaluation passed")
EXCERPT = 500  # characters returned per hit: enough to locate and judge a passage, not to reproduce a book
# The text index keeps every word (books are in many languages), so very common English words would swamp a question; they are dropped from the QUERY only, and only when real words remain.
QUERY_STOP = frozenset("a an the of and or to in on at for from by with as is are was were be been it its that this these those if not no do does did he she they we you i his her their our your me my who whom which what when where how than then so such shall may can could would should will have has had".split())
CHUNK = 1500
# a heading line is a keyword followed by a NUMBER (digits, a roman numeral or a number word), as in "BOOK X.", "Chapter 3" or "Section 228.": ordinary sentences that merely begin with "Part" or "Article" are not headings
HEADING = re.compile(r"^\s*(?:chapter|book|part|section|canto|article|discourse|letter)\s+(?:\d+|[IVXLCDM]+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|first|second|third|fourth|fifth)\b[\s.:\-—–]*.{0,80}$", re.I)


def now() -> datetime:
    return datetime.now(timezone.utc)


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _public(w: dict) -> dict:
    return {k: v for k, v in w.items() if k != "_id"}


async def import_registry() -> dict:
    """Add the catalogue entries that are missing. An existing work is never touched, so a status someone earned is never reset."""
    reg = load_registry()
    existing = {w["number"] async for w in db.knowledge_works.find({}, {"number": 1})}
    new = [{**e, "rights": None, "coverage": "unknown", "chunks": 0, "created_at": now()} for e in reg["entries"] if e["number"] not in existing]
    if new:
        await db.knowledge_works.insert_many(new)
    return {"in_registry": len(reg["entries"]), "added": len(new), "already_there": len(reg["entries"]) - len(new)}


async def _canonical(number: int) -> dict:
    w = await db.knowledge_works.find_one({"number": number})
    if not w:
        raise LookupError("No such work. Import the registry first.")
    if w.get("canonical_of"):
        w = await db.knowledge_works.find_one({"number": w["canonical_of"]}) or w
    return w


async def set_status(number: int, status: str, evidence: str, approval: str = "") -> dict:
    w = await _canonical(number)
    ladder = (await _ladder())
    if status not in ladder:
        raise ValueError(f"status must be one of: {', '.join(ladder)}.")
    if len(evidence.strip()) < 10:
        raise ValueError("A status change needs written evidence (at least 10 characters): a link, a licence, a hash, a test result.")
    if status in SET_BY_SYSTEM:
        raise ValueError(f"'{status}' is set only by ingesting text; it cannot be set by hand.")
    cur = w["status"]
    if cur == "Unavailable or blocked":
        # a mistaken block can be undone, but only back to the early rungs: it must earn its way to authorisation again
        if status == "Unavailable or blocked" or ladder.index(status) > ladder.index("Source located"):
            raise ValueError("A blocked work can only go back to 'Registered', 'Source not yet located' or 'Source located', with evidence.")
    elif status != "Unavailable or blocked" and ladder.index(status) <= ladder.index(cur):
        raise ValueError(f"Statuses only move forward ('{cur}' -> '{status}' is not forward).")
    if status in ("Retrieval verified", "Evaluation passed") and ladder.index(cur) < ladder.index("Indexed"):
        raise ValueError("Retrieval can only be verified for text that has been ingested and indexed.")
    if status != "Unavailable or blocked" and ladder.index(status) >= ladder.index("Authorized for ingestion"):
        # every rung from authorisation onwards needs recorded rights and the owner's written approval: no rung can be used to skip them
        r = w.get("rights")
        if not r or "full_text_indexing" not in r.get("permitted", []):
            raise ValueError("Record rights that allow full-text indexing before authorising ingestion.")
        given = approval.strip() if status == "Authorized for ingestion" else (approval.strip() or str(w.get("approval") or "").strip())
        if len(given) < 10:
            raise ValueError("Authorising ingestion needs the owner's written approval (who approved, and when).")
    patch = {"status": status, "evidence": evidence.strip(), "status_changed_at": now()}
    if approval.strip():
        patch["approval"] = approval.strip()
    await db.knowledge_works.update_one({"number": w["number"]}, {"$set": patch})
    return _public(await db.knowledge_works.find_one({"number": w["number"]}))


async def _ladder() -> list[str]:
    return load_registry()["statuses"]


async def record_rights(number: int, terms_quote: str, permitted: list[str], source_url: str, edition: str) -> dict:
    w = await _canonical(number)
    bad = [p for p in permitted if p not in PERMISSIONS]
    if bad:
        raise ValueError(f"Unknown permission(s): {', '.join(bad)}. Allowed: {', '.join(PERMISSIONS)}.")
    if len(terms_quote.strip()) < 10 or len(source_url.strip()) < 8 or not edition.strip():
        raise ValueError("Rights need the quoted terms, where they were read, and the exact edition or translation.")
    rights = {"terms_quote": terms_quote.strip(), "permitted": sorted(set(permitted)), "source_url": source_url.strip(), "recorded_at": now()}
    await db.knowledge_works.update_one({"number": w["number"]}, {"$set": {"rights": rights, "rights_status": "verified", "edition": edition.strip()}})
    return _public(await db.knowledge_works.find_one({"number": w["number"]}))


def chunk_text(text: str) -> list[dict]:
    """Chapters by heading lines, then paragraphs packed up to CHUNK characters. Each chunk keeps its chapter label and its order, and which paragraphs of the document it holds
    (`para_from` to `para_to`, counted from 1 over every non-empty paragraph, so "paragraph 12" can be found again). A long paragraph cut into pieces gives every piece its number."""
    chapters: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        if HEADING.match(line) and len(line.strip()) < 120:
            chapters.append((line.strip(), []))
        else:
            chapters[-1][1].append(line)
    out: list[dict] = []
    ordinal, para_no = 0, 0

    def emit(label: str, body: str, first: int, last: int) -> None:
        nonlocal ordinal
        out.append({"chapter": label, "ordinal": ordinal, "para_from": first, "para_to": last, "text": body})
        ordinal += 1

    for label, lines in chapters:
        cur, cur_from, cur_to = "", 0, 0
        for para in re.split(r"\n\s*\n", "\n".join(lines)):
            para = para.strip()
            if not para:
                continue
            para_no += 1
            if len(para) > CHUNK:
                if cur:  # what came before this long paragraph is its own chunk, so the text stays in reading order
                    emit(label, cur, cur_from, cur_to)
                    cur = ""
                start = 0
                while len(para) - start > CHUNK:
                    emit(label, para[start:start + CHUNK], para_no, para_no)
                    start += CHUNK
                para = para[start:]
            if cur and len(cur) + len(para) + 2 > CHUNK:
                emit(label, cur, cur_from, cur_to)
                cur = ""
            if cur:
                cur = f"{cur}\n\n{para}".strip()
                cur_to = para_no
            else:
                cur, cur_from, cur_to = para, para_no, para_no
        if cur:
            emit(label, cur, cur_from, cur_to)
    return out


_index_ready = False


async def _ensure_index() -> None:
    global _index_ready
    if _index_ready:
        return
    await db.knowledge_chunks.create_index([("text", "text")], default_language="none", name="knowledge_text")  # no stemming: books are in many languages
    # one chunk per (work, owner, text hash): two ingests running at once cannot store the same chunk twice
    try:
        await db.knowledge_chunks.create_index([("work_number", 1), ("scope", 1), ("org_id", 1), ("sha256", 1)], unique=True, name="knowledge_chunk_unique")
    except Exception:  # noqa: BLE001 - old duplicates in an existing database: search must keep working; the index is retried on the next start
        logger.exception("could not create the unique chunk index (duplicate chunks already exist?)")
    _index_ready = True


async def ingest_text(number: int, text: str, complete: bool) -> dict:
    """Index a library work's text. Refused unless the work is authorised and its rights allow it."""
    w = await _canonical(number)
    if w["status"] not in ("Authorized for ingestion", "Ingestion pending", "Ingested", "Indexed"):
        raise PermissionError(f"'{w['title']}' is '{w['status']}', not authorised for ingestion. Nothing was stored.")
    r = w.get("rights") or {}
    if "full_text_indexing" not in r.get("permitted", []):
        raise PermissionError("The recorded rights do not allow full-text indexing. Nothing was stored.")
    if len(str(w.get("approval") or "").strip()) < 10:
        raise PermissionError("No written approval from the owner is recorded for this work. Nothing was stored.")
    return await _store(w["number"], "library", None, text, complete, status_after=True)


async def add_private_text(org_id: str, title: str, text: str) -> dict:
    """A document an organisation brings itself. It gets its own record and is visible to that organisation only; it never touches the registry."""
    if not text.strip():
        raise ValueError("There is no text to store.")  # checked before the record exists, so a blank upload leaves nothing behind
    docs, chars = await _private_usage(org_id)
    if docs >= MAX_PRIVATE_DOCS:
        raise ValueError(f"Your organisation already holds {MAX_PRIVATE_DOCS} private documents. Delete one to add another.")
    if chars + len(text) > MAX_PRIVATE_CHARS:
        raise ValueError("Your organisation's private document storage is full. Delete a document to add another.")
    number = -int(uuid.uuid4().int % 10**9) - 1  # negative: can never collide with a registry number
    await db.knowledge_works.insert_one({"number": number, "id": f"private-{uuid.uuid4().hex[:10]}", "title": title.strip()[:200] or "Private document", "authors": "", "kind": "private", "scope": "org",
                                         "org_id": org_id, "status": "Ingested", "evidence": "added by the organisation", "coverage": "unknown", "chunks": 0, "collections": [], "created_at": now()})
    return await _store(number, "org", org_id, text, False, status_after=False)


MAX_PRIVATE_DOCS = int(os.environ.get("KNOWLEDGE_MAX_PRIVATE_DOCS", "200"))
MAX_PRIVATE_CHARS = int(os.environ.get("KNOWLEDGE_MAX_PRIVATE_CHARS", "20000000"))  # per organisation, in characters of stored text


async def _private_usage(org_id: str) -> tuple[int, int]:
    """(documents, characters) this organisation already holds, counted from its stored chunks."""
    docs = await db.knowledge_works.count_documents({"scope": "org", "org_id": org_id})
    agg = await db.knowledge_chunks.aggregate([{"$match": {"scope": "org", "org_id": org_id}}, {"$group": {"_id": None, "n": {"$sum": {"$strLenCP": "$text"}}}}]).to_list(1)
    return docs, int(agg[0]["n"]) if agg else 0


async def delete_private(org_id: str, number: int) -> int:
    """Remove one private document of this organisation (and only that organisation's)."""
    w = await db.knowledge_works.find_one({"number": number, "scope": "org", "org_id": org_id})
    if not w:
        raise LookupError("No such document.")
    await db.knowledge_chunks.delete_many({"work_number": number, "scope": "org", "org_id": org_id})
    await db.knowledge_works.delete_one({"number": number, "scope": "org", "org_id": org_id})
    return 1


async def list_private(org_id: str) -> list[dict]:
    return [{"number": w["number"], "title": w["title"], "chunks": w.get("chunks", 0)} async for w in db.knowledge_works.find({"scope": "org", "org_id": org_id}).sort("created_at", 1)]


async def _store(number: int, scope: str, org_id: str | None, text: str, complete: bool, status_after: bool) -> dict:
    if not text.strip():
        raise ValueError("There is no text to store.")
    await _ensure_index()
    pieces = chunk_text(text)
    have = {c["sha256"] async for c in db.knowledge_chunks.find({"work_number": number, "scope": scope, "org_id": org_id}, {"sha256": 1})}
    rows, skipped = [], 0
    for p in pieces:
        h = hashlib.sha256(p["text"].encode("utf-8")).hexdigest()
        if h in have:
            skipped += 1
            continue
        have.add(h)
        # `kind` and `script` are facts the code knows (who owns it, which letters it is written in). Version, reviewer and language are NOT stored: a private or reference text has
        # none of them, and a language cannot be told from letters alone.
        rows.append({"id": uuid.uuid4().hex, "work_number": number, "scope": scope, "org_id": org_id, "sha256": h, "created_at": now(),
                     "kind": "firm_knowledge" if scope == "org" else "reference_work", "script": script_of(p["text"]), **p})
    if rows:
        try:
            await db.knowledge_chunks.insert_many(rows, ordered=False)
        except BulkWriteError as exc:  # a concurrent ingest stored some of the same chunks first: the unique index refused them, which is the point
            dup = sum(1 for e in exc.details.get("writeErrors", []) if e.get("code") == 11000)
            if dup != len(exc.details.get("writeErrors", [])):
                raise
            rows, skipped = rows[: len(rows) - dup], skipped + dup
    total = await db.knowledge_chunks.count_documents({"work_number": number, "scope": scope, "org_id": org_id})
    before = (await db.knowledge_works.find_one({"number": number}, {"coverage": 1})) or {}
    patch: dict = {"chunks": total, "coverage": "full" if (complete or before.get("coverage") == "full") else "partial"}  # a later partial load never downgrades a work that was loaded in full
    if status_after:
        patch.update({"status": "Indexed", "evidence": f"{total} chunks stored; text sha256 {hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"})
    await db.knowledge_works.update_one({"number": number}, {"$set": patch})
    return {"work_number": number, "chunks_added": len(rows), "chunks_skipped_as_duplicates": skipped, "chunks_total": total, "coverage": patch["coverage"]}


KINDS = ("firm_knowledge", "reference_work")


def own_or_shared(rows: list[dict], org_id: str) -> list[dict]:
    """The last line of defence for tenant isolation: whatever the database returned, keep only shared library chunks and THIS organisation's own. The query already asks for exactly
    that; this drops a foreign row even if a later change to the query ever lets one through."""
    return [r for r in rows if r.get("scope") == "library" or (r.get("scope") == "org" and r.get("org_id") == org_id)]


async def search(query: str, org_id: str, k: int = 8, collection: str | None = None, *, script: str | None = None, kind: str | None = None) -> dict:
    """Library chunks plus this organisation's own private chunks, best first. Every hit says where it came from and how much of the work is indexed.
    `script` (the letters a chunk is written in) and `kind` (firm_knowledge or reference_work) narrow the candidates inside the database query, before the limit. Chunks stored before those
    fields existed have neither, so a filter on them leaves those chunks out; no filter leaves everything in."""
    if script is not None and script not in SCRIPT_NAMES:
        raise ValueError(f"Unknown script '{script}'.")
    if kind is not None and kind not in KINDS:
        raise ValueError(f"Unknown kind '{kind}'. Use one of: {', '.join(KINDS)}.")
    if os.environ.get("KNOWLEDGE_ENABLED", "true").strip().lower() in ("0", "false", "no", "off"):
        return {"hits": [], "note": "The book library is switched off on this server.", "limits": "Nothing was searched."}
    q = query.strip()
    kept = [w for w in re.findall(r"\w+", q) if w.lower() not in QUERY_STOP]
    if kept and len(kept) < len(re.findall(r"\w+", q)):
        q = " ".join(kept)
    if not q:
        return {"hits": [], "note": "Type a question or a phrase to search."}
    await _ensure_index()
    flt = {"$text": {"$search": q}, "$or": [{"scope": "library"}, {"scope": "org", "org_id": org_id}]}
    if script:
        flt["script"] = script
    if kind:
        flt["kind"] = kind
    if collection:  # restrict inside the database query: filtering after the limit could return nothing although matches exist in that collection
        flt["work_number"] = {"$in": [w["number"] async for w in db.knowledge_works.find({"collections": collection}, {"number": 1})]}
    rows = await db.knowledge_chunks.find(flt, {"score": {"$meta": "textScore"}}).sort([("score", {"$meta": "textScore"})]).limit(max(1, min(k, 20)) * 3).to_list(60)
    rows = own_or_shared(rows, org_id)
    works = {w["number"]: w async for w in db.knowledge_works.find({"number": {"$in": list({r["work_number"] for r in rows})}})}
    hits = []
    for r in rows:
        w = works.get(r["work_number"])
        if not w or (r["scope"] == "library" and w["status"] not in SEARCHABLE):
            continue
        if collection and collection not in w.get("collections", []):
            continue
        hits.append({"work": w["title"], "authors": w.get("authors", ""), "kind": w.get("kind"), "scope": r["scope"], "chapter": r["chapter"] or None, "position": r["ordinal"],
                     "paragraphs": [r["para_from"], r["para_to"]] if r.get("para_from") else None, "script": r.get("script"),  # older chunks were stored without these: shown as unknown, never guessed
                     "excerpt": r["text"][:EXCERPT] + ("..." if len(r["text"]) > EXCERPT else ""), "chunk_sha256": r["sha256"][:16], "score": round(float(r.get("score", 0)), 3),
                     "work_coverage": w.get("coverage", "unknown"), "edition": w.get("edition")})
        if len(hits) >= k:
            break
    note = "" if hits else "No indexed source matches. Either nothing relevant has been loaded or the wording differs; this is not evidence that no book discusses it."
    return {"hits": hits, "note": note, "limits": "Excerpts are for locating a passage. Whether a passage supports a claim must be judged from the passage itself; a book is not law, and nothing here verifies a legal claim."}


async def dashboard() -> dict:
    ladder = await _ladder()
    counts = {s: await db.knowledge_works.count_documents({"status": s, "scope": {"$ne": "org"}}) for s in ladder}
    return {"works": await db.knowledge_works.count_documents({"scope": {"$ne": "org"}}), "by_status": counts, "chunks_in_library": await db.knowledge_chunks.count_documents({"scope": "library"})}


async def domains() -> dict:
    """The reading lists (neuroscience, philosophy) joined with each work's status in the registry. Lists, not content: nothing is searchable until a work is ingested."""
    cfg = json.loads((REGISTRY.parent / "domains.json").read_text(encoding="utf-8"))
    works = {w["number"]: w async for w in db.knowledge_works.find({"number": {"$in": [x["number"] for d in cfg["domains"].values() for x in d["works"]]}})}
    out = {}
    for key, d in cfg["domains"].items():
        out[key] = {**{k: v for k, v in d.items() if k != "works"},
                    "works": [{**x, "title": (works.get(x["number"]) or {}).get("title"), "status": (works.get(x["number"]) or {}).get("status", "Not imported yet")} for x in d["works"]]}
    return {"note": cfg["note"], "domains": out}
