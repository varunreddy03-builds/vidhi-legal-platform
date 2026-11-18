"""The verified law library: the ONLY place a legal citation can become "verified".

Entries live as reviewed JSON files in data/legal_library/ (so every addition is visible in git history, with
the lawyer who signed it off). Each entry carries the EXACT source text, where it came from, its version and a
SHA-256 of the text so a transcription slip is caught. At startup the files are synced into Mongo; an entry
that is missing a required field, has no named verifier or fails its hash is rejected and never used.

Nothing here knows any law. The shipped directory is empty by design.

Review gate: a lawyer's review is what makes an entry verified. Drafts sit in `pending/` with status "UNVERIFIED - pending lawyer review".
They are loaded for visibility only (collection legal_source_candidates), can never verify a claim, and become usable only when
`scripts/library_review.py approve` moves them into the library with the reviewer's name and date.
Folders may be grouped by jurisdiction (IN/, AE/, UK/, US/, SG/); only jurisdictions listed as live in lib/jurisdictions.py are used.
"""

import hashlib
import json
import logging
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from lib import law_dates
from lib import textmatch as _textmatch
from lib import verified_store as store
from lib.db import db

logger = logging.getLogger(__name__)

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "legal_library"
KINDS = ("STATUTE_SECTION", "RULE", "CASE", "OTHER")
REQUIRED = (
    "id",
    "citation",
    "kind",
    "text",
    "text_sha256",
    "source_name",
    "source_url",
    "version",
    "verified_by",
    "verified_on",
)
_STOP = {
    "the", "and", "for", "that", "this", "with", "are", "was", "were", "has", "have", "had", "not", "any",
    "can", "may", "what", "which", "who", "whom", "from", "into", "under", "such", "shall", "will", "would",
    "should", "could", "their", "there", "than", "then", "its", "his", "her", "our", "your", "you", "about",
}


def library_dir() -> Path:
    return Path(os.environ.get("LIBRARY_DIR") or DEFAULT_DIR)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def norm_text(s: str) -> str:
    """Normalise for exact-quote comparison: Unicode form, case, whitespace, quote/dash styles and invisible characters (see lib/textmatch.py)."""
    return _textmatch.norm(s)


CASE_NOTE = (
    "A reported decision. Whether it binds the court in question depends on which court decided it and where the matter is heard; VIDHI has not worked that out, "
    "and it does not say whether the decision is still good law. A lawyer must check both."
)


def authority_for(kind: str) -> tuple[str, str]:
    """(authority_level, note) for a verified library entry, from what the entry IS. Legislation is primary; a decision's weight depends on the forum, which is not known here."""
    if kind in ("STATUTE_SECTION", "RULE"):
        return "PRIMARY", ""
    if kind == "CASE":
        return "UNKNOWN", CASE_NOTE
    return "UNKNOWN", "The kind of source is not classified, so its authority is not stated."


def norm_citation(s: str) -> str:
    s = norm_text(s)
    s = re.sub(r"\b(sec|sec\.|s\.|s)\s*(?=\d)", "section ", s)
    s = re.sub(r"\b(art|art\.)\s*(?=\d)", "article ", s)
    s = re.sub(r"[^\w()\s]", " ", s)
    s = re.sub(r"\bthe\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def validate_entry(e: object) -> list[str]:
    if not isinstance(e, dict):
        return ["not an object"]
    errs = [f"missing {k}" for k in REQUIRED if not str(e.get(k) or "").strip()]
    if e.get("kind") not in KINDS:
        errs.append(f"kind must be one of {KINDS}")
    if not errs and sha256_text(e["text"]) != e["text_sha256"]:
        errs.append("text_sha256 does not match the text (transcription error?)")
    if e.get("verified") is False:
        errs.append("marked verified:false")
    if "unverified" in str(e.get("status", "")).lower():
        errs.append("marked unverified: it belongs in pending/ until a lawyer approves it")
    return errs


PENDING_STATUS = "UNVERIFIED - pending lawyer review"
PENDING_REQUIRED = ("id", "citation", "kind", "source_name")


def validate_pending(e: object) -> list[str]:
    """A draft entry only has to say what it is and where it came from. Whatever it claims about review is ignored."""
    if not isinstance(e, dict):
        return ["not an object"]
    errs = [f"missing {k}" for k in PENDING_REQUIRED if not str(e.get(k) or "").strip()]
    if e.get("kind") not in KINDS:
        errs.append(f"kind must be one of {KINDS}")
    return errs


# Sources whose own terms forbid storing or republishing their text without written permission (docs/legal-sources-terms.md). lib/legal_store.py applies the same names to registered sources.
PERMISSION_REQUIRED_NAMES = ("india code", "indiacode", "legislative department", "ncrb sankalan", "crpc_1973_as_amended_clean",
                             "cbic", "sebi", "ministry of labour", "central information commission", "competition commission", "ip india")  # the last six: official sites whose terms have not been read (added 2026-11-18)


# Each source has its own switch, so turning one on never turns on another (India Code stays off while the Ministry portal text is on).
PERMISSION_ENV = {
    "ncrb sankalan": "NCRB_PORTAL_USE_REF",
    # Other official sites: terms not read yet. Each has its own switch, off until the operator writes down what the site's terms allow (who decided, when).
    "cbic": "CBIC_USE_REF", "sebi": "SEBI_USE_REF", "ministry of labour": "LABOUR_MINISTRY_USE_REF", "central information commission": "CIC_USE_REF", "competition commission": "CCI_USE_REF", "ip india": "IPINDIA_USE_REF",
    # Only the three repealed codes (IPC, CrPC, Evidence Act), identified by their file names; the rest of India Code stays under INDIA_CODE_PERMISSION_REF.
    "ipc_1860_official_repealed": "OLD_CODES_USE_REF", "crpc_1973_official_repealed": "OLD_CODES_USE_REF", "indian_evidence_act_1872_official_repealed": "OLD_CODES_USE_REF", "crpc_1973_as_amended_clean": "OLD_CODES_USE_REF",
}
DEFAULT_PERMISSION_ENV = "INDIA_CODE_PERMISSION_REF"


def permission_recorded(source_name: str = "") -> bool:
    """True only when the operator has written down the permission or decision (who gave it, when) for this source: INDIA_CODE_PERMISSION_REF, or NCRB_PORTAL_USE_REF for the Ministry portal text.
    Without it, no draft from that source is loaded, searched or shown."""
    low = str(source_name).lower()
    env = next((v for k, v in PERMISSION_ENV.items() if k in low), DEFAULT_PERMISSION_ENV)
    return len((os.environ.get(env) or "").strip()) >= 10


def needs_permission(source_name: str) -> bool:
    return any(n in str(source_name).lower() for n in PERMISSION_REQUIRED_NAMES)


def load_pending(directory: Path | None = None) -> list[dict]:
    """Draft entries waiting for a lawyer (pending/*.json). Always reported as UNVERIFIED, whatever the file says about itself."""
    d = (directory or library_dir()) / "pending"
    out, seen = [], set()
    if not d.exists():
        return out
    for f in sorted(d.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for e in data.get("entries") if isinstance(data, dict) and "entries" in data else [data]:
            if validate_pending(e) or e["id"] in seen:
                continue
            if needs_permission(e.get("source_name", "")) and not permission_recorded(e.get("source_name", "")):
                continue  # the file stays on disk, but nothing from it is loaded, searched or shown until the permission is recorded
            seen.add(e["id"])
            citation = str(e["citation"])
            out.append({"id": e["id"], "citation": citation, "kind": e["kind"], "source_name": e["source_name"],
                        "source_url": e.get("source_url", ""), "jurisdiction": e.get("jurisdiction", "IN"), "status": PENDING_STATUS,
                        "reviewer": None, "reviewed_on": None, "file": f.name, "seq": len(out),  # seq: the order of the sections in their Act
                        # what a reader needs to look at a draft (all optional: older drafts carry none of it). Whatever a file says about its own review is ignored above.
                        "act_id": str(e["id"]).rsplit("-", 1)[0], "act_title": citation.split(", ", 1)[1] if ", " in citation else citation,
                        "heading": str(e.get("heading", "")), "text": str(e.get("text", "")), "text_sha256": str(e.get("text_sha256", "")),
                        "version": str(e.get("version", "")), "commencement": str(e.get("commencement", "")), "legal_currency": str(e.get("legal_currency", "")),
                        "oversized": bool(e.get("oversized", False)), "text_source": str(e.get("text_source", "")), "coverage_note": str(e.get("coverage_note", ""))})
    return out


def load_entries(directory: Path | None = None) -> tuple[list[dict], list[dict]]:
    """(valid entries, rejected [{file, id, errors}]). Reads every *.json file in the directory."""
    d = directory or library_dir()
    valid, rejected, seen = [], [], set()
    if not d.exists():
        return valid, rejected
    for f in sorted(d.rglob("*.json")):
        rel = f.relative_to(d)
        if rel.parts[0] == "pending" or f.name.startswith("_") or f.name == "schema.json":  # drafts and templates are never part of the verified library
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            rejected.append({"file": f.name, "id": None, "errors": [f"unreadable: {exc}"]})
            continue
        items = data.get("entries") if isinstance(data, dict) and "entries" in data else [data]
        for e in items if isinstance(items, list) else []:
            errs = validate_entry(e)
            if not errs and e["id"] in seen:
                errs = ["duplicate id"]
            if errs:
                rejected.append({"file": f.name, "id": (e or {}).get("id") if isinstance(e, dict) else None, "errors": errs})
                continue
            seen.add(e["id"])
            valid.append(e)
    return valid, rejected


async def sync_library() -> dict:
    """Make Mongo mirror the files: upsert valid entries, withdraw anything no longer in the files."""
    valid, rejected = load_entries()
    for r in rejected:
        logger.error("legal library: rejected %s (%s): %s", r["file"], r["id"], "; ".join(r["errors"]))
    ids = []
    for e in valid:
        keys = list(dict.fromkeys(norm_citation(x) for x in [e["citation"], *e.get("aliases", [])] if x))
        doc = {
            "id": e["id"],
            "jurisdiction": e.get("jurisdiction", "IN"),
            "citation": e["citation"],
            "aliases": e.get("aliases", []),
            "keys": keys,
            "kind": e["kind"],
            "title": e.get("title", ""),
            "text": e["text"],
            "text_norm": norm_text(e["text"]),
            "text_sha256": e["text_sha256"],
            "source_name": e["source_name"],
            "source_url": e["source_url"],
            "version": e["version"],
            "verified_by": e["verified_by"],
            "verified_on": e["verified_on"],
        }
        await store.publish_verified(db, doc, origin="library", replace_text_guard=False)  # the files are the authority for their own entries
        ids.append(e["id"])
    await store.withdraw_missing(db, "library", ids)  # only entries that came from the library files
    # Until 2026-11-02 the library shared the operator's `legal_sources` collection. Move out anything it left there; the operator's own source records (no origin "library") stay.
    await store.delete(db, "legal_sources", {"origin": "library"})
    pending = load_pending()
    await store.delete(db, "legal_source_candidates", {"id": {"$nin": [p["id"] for p in pending]}})
    now = datetime.now(timezone.utc)
    digest = sha256_text("|".join(f"{p['id']}:{p['citation']}:{p['heading']}:{p['text_sha256']}:{p['version']}:{p['legal_currency']}" for p in pending))
    state = await db.library_state.find_one({"_id": "drafts"})
    if state and state.get("digest") == digest and await db.legal_source_candidates.count_documents({}) == len(pending):
        return {"loaded": len(ids), "rejected": len(rejected), "pending": len(pending)}  # nothing changed since the last start: do not rewrite thousands of rows
    await store.replace_many(db, "legal_source_candidates", [{**p, "synced_at": now} for p in pending], batch=500)  # in batches: thousands of drafts must not mean thousands of round trips at every start-up
    await db.library_state.update_one({"_id": "drafts"}, {"$set": {"digest": digest, "synced_at": now}}, upsert=True)
    return {"loaded": len(ids), "rejected": len(rejected), "pending": len(pending)}


async def resolve(ref: str) -> dict | None:
    """A VERIFIED entry by id, or by exact normalised citation / alias. Never fuzzy."""
    if not ref or not ref.strip():
        return None
    by_id = await store.verified_entries({"id": ref.strip()}, limit=1, db=db)
    if by_id:
        return by_id[0]
    by_key = await store.verified_entries({"keys": norm_citation(ref)}, limit=1, db=db)
    return by_key[0] if by_key else None


def _tokens(s: str) -> set[str]:
    from lib import text as _text

    return set(_text.tokens(s))


def _in_force(entry: dict, on: date) -> bool:
    """False only when the entry's own dates show the law was not yet in force, or no longer in force, on that day. Unknown dates keep the entry (nothing is excluded without evidence)."""
    v = law_dates.validity(entry.get("commencement", ""), entry.get("legal_currency", ""), entry.get("act_id"))
    return law_dates.status_on(v, on) not in ("REPEALED", "NOT_YET_IN_FORCE")


async def find_relevant(question: str, k: int = 8, *, act_id: str | None = None, on_date: date | None = None) -> list[dict]:
    """VERIFIED library entries that fit the question, best first - candidates the model may cite. An exact citation named in the question comes first; the ranking itself is lib/library_rank.py.
    Optional filters narrow the candidates BEFORE ranking: `act_id` keeps one Act (done in the database), `on_date` drops entries whose own dates show the law was not in force on that day
    (an entry with unknown dates stays, because nothing is dropped without evidence). Court, language and matter filters do not apply to library entries (they carry none of those fields): UNVERIFIED."""
    from lib import library_rank

    if not (question or "").strip():
        return []
    entries = await store.verified_entries({"act_id": act_id} if act_id else None, limit=0, db=db)
    if on_date:
        entries = [e for e in entries if _in_force(e, on_date)]
    return library_rank.rank(question, entries, k)


async def count() -> int:
    return await store.verified_count(db=db)


DRAFT_NOTE = (
    "Not reviewed: this text was cut from the official PDF by a program and no lawyer has compared it with the source. It is shown so you can look the provision up; "
    "VIDHI does not treat it as verified law and no answer rests on it."
)


def draft_view(d: dict, excerpt: int = 600) -> dict:
    """What a reader sees of a draft law entry. Always labelled not reviewed; a repealed law is marked historical (it applies only to what happened while it was in force)."""
    currency = d.get("legal_currency", "")
    v = law_dates.validity(d.get("commencement", ""), currency, d.get("act_id"))
    return {
        "id": d["id"], "citation": d["citation"], "heading": d.get("heading", ""), "act_id": d.get("act_id", ""), "act_title": d.get("act_title", ""),
        "excerpt": (d.get("text") or "")[:excerpt], "text_length": len(d.get("text") or ""), "source_name": d.get("source_name", ""), "source_url": d.get("source_url", ""),
        "version": d.get("version", ""), "commencement": d.get("commencement", ""), "legal_currency": currency,
        "historical": "repeal" in currency.lower() or "historical" in currency.lower(),
        "text_source": d.get("text_source", ""), "coverage_note": d.get("coverage_note", ""),  # OCR drafts say so, and say how much of the Act was found
        "in_force_from": v["from"].isoformat() if v["from"] else None, "in_force_until": v["to"].isoformat() if v["to"] else None, "in_force_after_year": v["after_year"], "commencement_basis": v["basis"],  # only dates the manifest or a Gazette notification states
        "commencement_source": v.get("source", ""), "in_force_stages": v.get("stages"), "commencement_except": v.get("except_note", ""), "commencement_reviewed": bool(v.get("verified")),
        "status": PENDING_STATUS, "note": DRAFT_NOTE,
    }


def with_date_check(items: list[dict], on: date) -> list[dict]:
    """Add "was it in force on this date?" to draft views. The answer comes only from the dates in the manifest; UNKNOWN when they are not stated."""
    out = []
    for it in items:
        v = {"from": date.fromisoformat(it["in_force_from"]) if it.get("in_force_from") else None, "to": date.fromisoformat(it["in_force_until"]) if it.get("in_force_until") else None,
             "after_year": it.get("in_force_after_year"), "stages": it.get("in_force_stages")}
        s = law_dates.status_on(v, on)
        note = law_dates.BASIS_NOTES.get(it.get("commencement_basis") or "", "") if s == "UNKNOWN" or it.get("commencement_basis") == "AT_ONCE" else ""
        src = it.get("commencement_source") or ""
        base = law_dates.NOTES[s].replace("the dates in the official manifest", "the Gazette notification named here") if src else law_dates.NOTES[s]
        tail = (f" Source: {src}." + (f" {it['commencement_except']}" if it.get("commencement_except") else "")) if src else ""
        out.append({**it, "checked_on": on.isoformat(), "in_force_on_date": s, "date_note": (note + " " if note else "") + base + tail})
    return out


async def search_drafts(question: str, k: int = 6, act_id: str | None = None, skip: int = 0) -> list[dict]:
    """Draft law entries (never verified) that look relevant to a question, best first. For showing to a person only: nothing here can verify a claim."""
    q = " ".join(sorted(_tokens(question)))
    if not q:
        return []
    flt: dict = {"$text": {"$search": q}}
    if act_id:
        flt["act_id"] = act_id
    cur = db.legal_source_candidates.find(flt, {"score": {"$meta": "textScore"}, "_id": 0}).sort([("score", {"$meta": "textScore"})]).skip(skip).limit(k)
    return [draft_view(d) async for d in cur]


# ---- approval from the reviewer screen: still only this module can make an entry VERIFIED ----
REVIEWER_SCREEN = "reviewer_screen"


def _file_shape(d: dict) -> dict:
    """An entry in the shape of the library files (what scripts/library_review.py writes), so it can be exported and committed."""
    keys = ("id", "citation", "kind", "text", "source_name", "source_url", "jurisdiction", "aliases", "title", "version", "text_sha256", "verified_by", "verified_on")
    return {k: d.get(k, [] if k == "aliases" else "") for k in keys}


async def approve_entry(entry: dict, reviewer: str, on: str, *, provision_id: str, provision_sha256: str, document_sha256: str) -> dict:
    """Make one entry VERIFIED because a NAMED person compared it with the official source. The same checks as `scripts/library_review.py approve` (full name, date, live jurisdiction,
    required fields, the text hash recomputed from the text). Records who, when, and the hashes of the provision and of the source document. Never overwrites a verified entry whose
    text is different. Nothing else in the application writes a verified entry."""
    from lib.jurisdictions import REGISTRY, is_live

    name = (reviewer or "").strip()
    if len(name) < 5:
        raise ValueError("Give the reviewer's full name.")
    try:
        day = date.fromisoformat(str(on)).isoformat()
    except ValueError as exc:
        raise ValueError("Give the date of the review as YYYY-MM-DD.") from exc
    juris = entry.get("jurisdiction", "IN")
    if juris not in REGISTRY or not is_live(juris):
        raise ValueError(f"Jurisdiction {juris} is not live yet (lib/jurisdictions.py): it cannot be approved.")
    e = {k: entry[k] for k in ("id", "citation", "kind", "text", "source_name", "source_url") if k in entry}
    e.update(jurisdiction=juris, aliases=entry.get("aliases", []), title=entry.get("heading") or entry.get("title", ""), version=entry.get("version", ""), verified_by=name, verified_on=day)
    e["text"] = str(e.get("text", "")).strip()
    e["text_sha256"] = sha256_text(e["text"])
    errs = validate_entry(e)
    if errs:
        raise ValueError("Not approved: " + "; ".join(errs))
    doc = {
        **_file_shape(e), "keys": list(dict.fromkeys(norm_citation(x) for x in [e["citation"], *e["aliases"]] if x)), "text_norm": norm_text(e["text"]),
        "provision_id": provision_id, "provision_sha256": provision_sha256, "document_sha256": document_sha256, "approved_at": datetime.now(timezone.utc),
    }
    saved = await store.publish_verified(db, doc, origin=REVIEWER_SCREEN)  # refuses a verified entry with the same id and different text
    return _file_shape(saved)


async def withdraw_entry(entry_id: str, reviewer: str, on: str, reason: str) -> dict:
    """Take an entry approved on the reviewer screen out of the verified library (it stays on record as WITHDRAWN). Entries that come from library files are withdrawn by deleting the file."""
    if len((reviewer or "").strip()) < 5:
        raise ValueError("Give the reviewer's full name.")
    try:
        day = date.fromisoformat(str(on)).isoformat()
    except ValueError as exc:
        raise ValueError("Give the date as YYYY-MM-DD.") from exc
    if len((reason or "").strip()) < 10:
        raise ValueError("Say why the entry is being withdrawn.")
    old = await db.library_entries.find_one({"id": entry_id})
    if not old or old.get("status") != "VERIFIED":
        raise ValueError("That entry is not in the verified library.")
    if old.get("origin") != REVIEWER_SCREEN:
        raise ValueError("That entry comes from a library file: withdraw it by removing the file and committing the change.")
    await store.withdraw_verified(db, entry_id, reviewer, day, reason)
    return {"id": entry_id, "status": "WITHDRAWN"}


async def export_entry(entry_id: str) -> dict:
    """A verified entry in the library-file format, so it can be committed under data/legal_library/ (the git history is then its audit trail too)."""
    found = await store.verified_entries({"id": entry_id}, limit=1, db=db)
    if not found:
        raise ValueError("That entry is not in the verified library.")
    return _file_shape(found[0])
