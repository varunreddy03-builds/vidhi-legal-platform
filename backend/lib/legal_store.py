"""Storage for the legal-data layer: sources, documents, instruments, versions, provisions and chunks (MongoDB, shared public text: no organisation field).

Rules this module enforces (tests/test_legal_data.py):
* Everything ingested is `unreviewed`. A provision becomes `reviewed` only when a named person and a date are recorded, and only if its text still matches the
  hash recorded at ingestion. Nothing here can mark a claim VERIFIED: verification stays in lib/verify.py and works only from the reviewed library files.
  `build_library_entry` produces the library-format draft (always "UNVERIFIED - pending lawyer review") for a person to save under pending/ and approve with
  scripts/library_review.py, so there is ONE path to verification.
* A version's effective dates (and a repeal) are stored only when evidence is given with them. Unknown stays unknown (null); no date is ever guessed.
* Versions are never overwritten: new text is a new version row. Re-registering the same file (same SHA-256) is a no-op that returns the existing record.
* Coverage numbers are counted from the database, never typed in."""

import hashlib
import re
import unicodedata
import uuid
from datetime import date, datetime, timezone

from pymongo.errors import DuplicateKeyError

from lib import law_dates, legal_structure, territories, textmatch
from lib.db import db
from lib import library
from lib import verified_store as store
from lib.library import PENDING_STATUS, sha256_text

ACCESS = ("manual-supplied", "public-page", "api")
KINDS = ("act", "code", "rule", "regulation", "notification", "order", "constitution", "other")
VERSION_LABELS = ("original", "amendment", "consolidated", "other")
MAX_PAGES_CHARS = 12_000_000


def now() -> datetime:
    return datetime.now(timezone.utc)


def norm(s: str) -> str:
    """Lower-case words for comparing names. Letters, digits AND combining marks stay, so Indian-script words (whose vowel signs are marks) are not cut apart."""
    text = unicodedata.normalize("NFKC", s or "").casefold()
    return " ".join("".join(ch if unicodedata.category(ch)[0] in "LNM" else " " for ch in text).split())


def iso(value: str | None, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field} must be a date like 2026-11-05.") from exc


def clean(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "_id"}


def public_doc(doc: dict) -> dict:
    """A document record as shown to the operator: never the page text (large) or the internal file id (not JSON)."""
    out = {k: v for k, v in clean(doc).items() if k not in ("pages", "stored_file_id")}
    out["has_stored_file"] = doc.get("stored_file_id") is not None
    return out


async def register_source(d: dict) -> dict:
    if d["access_method"] not in ACCESS:
        raise ValueError(f"access_method must be one of {', '.join(ACCESS)}.")
    doc = {
        "id": str(uuid.uuid4()), "name": d["name"].strip(), "publisher": d["publisher"].strip(), "jurisdiction": d.get("jurisdiction", "IN"), "document_types": d.get("document_types", []),
        "access_method": d["access_method"], "licence_note": d.get("licence_note", ""), "terms_checked_on": iso(d.get("terms_checked_on"), "terms_checked_on"),
        "robots_or_captcha_note": d.get("robots_or_captcha_note", ""), "update_frequency": d.get("update_frequency", ""), "known_limits": d.get("known_limits", ""),
        # A source whose terms forbid storing or republishing its text without written permission is marked here; nothing can be loaded from it until the permission is recorded.
        "permission_required": bool(d.get("permission_required", False)) or any(n in f"{d['name']} {d['publisher']}".lower() for n in PERMISSION_REQUIRED_NAMES),
        "permission_reference": (d.get("permission_reference") or "").strip(),
        "status": "terms-not-read" if not d.get("terms_checked_on") else "terms-recorded", "created_at": now(),
    }
    await store.create(db, "legal_sources", doc)
    return clean(doc)


# Sources whose published terms (read 2026-10-26, docs/legal-sources-terms.md) allow personal non-commercial use only and forbid automated access and commercial republication without
# written permission. A source registered under one of these names always needs a recorded permission, whatever the form said.
PERMISSION_REQUIRED_NAMES = library.PERMISSION_REQUIRED_NAMES


def use_blocked(source: dict) -> str | None:
    """Why text from this source may not be loaded yet, or None. Encodes the source's own terms: no written permission recorded, no text."""
    if source.get("permission_required") and not (source.get("permission_reference") or "").strip():
        return (f"\"{source.get('name', 'This source')}\" has terms that require written permission before its text is stored or republished, and no permission is recorded for it. "
                "Record the permission (who gave it, and when) on the source, or do not load text from it.")
    return None


async def record_permission(source_id: str, reference: str, recorded_by: str) -> dict:
    ref = (reference or "").strip()
    if len(ref) < 10:
        raise ValueError("Describe the permission: who gave it, on what date, and where the letter or email is kept.")
    src = await db.legal_sources.find_one({"id": source_id})
    if not src:
        raise ValueError("Unknown source.")
    await store.change(db, "legal_sources", {"id": source_id}, {"permission_reference": ref, "permission_recorded_by": recorded_by, "permission_recorded_on": now().date().isoformat()})
    return clean(await db.legal_sources.find_one({"id": source_id}))


async def register_document(source_id: str, meta: dict, *, text_pages: list[str], file_bytes: bytes | None = None, stored_file_id=None, page_meta: list[dict] | None = None) -> dict:
    """One acquired official document. The hash is of the file when there is one, else of the text. Same source + same hash returns the existing record."""
    src = await db.legal_sources.find_one({"id": source_id})
    if not src:
        raise ValueError("Unknown source.")
    blocked = use_blocked(src)
    if blocked:
        raise ValueError(blocked)
    if sum(len(p) for p in text_pages) > MAX_PAGES_CHARS:
        raise ValueError("That document is too large to load as text in one piece.")
    digest = hashlib.sha256(file_bytes).hexdigest() if file_bytes is not None else sha256_text("\f".join(text_pages))
    existing = await db.legal_documents.find_one({"source_id": source_id, "sha256": digest})
    if existing:
        return {**public_doc(existing), "duplicate": True}
    doc = {
        "id": str(uuid.uuid4()), "source_id": source_id, "title": meta["title"].strip(), "issuing_authority": meta.get("issuing_authority", ""), "source_page_url": meta.get("source_page_url", ""),
        "file_url": meta.get("file_url", ""), "published_on": iso(meta.get("published_on"), "published_on"), "licence_note": meta.get("licence_note", ""), "sha256": digest,
        "format": meta.get("format", "text"), "retrieved_on": iso(meta.get("retrieved_on"), "retrieved_on") or now().date().isoformat(),
        "ocr_status": "machine-read" if any(m.get("engine") not in (None, "embedded-text") for m in (page_meta or [])) else "not-needed",
        "page_meta": page_meta or [], "uncertain_pages": [m["page"] for m in (page_meta or []) if m.get("uncertain")],
        "index_status": "not-ingested", "stored_file_id": stored_file_id, "pages": text_pages, "created_at": now(),
    }
    try:
        await store.create(db, "legal_documents", doc)
    except DuplicateKeyError:  # two identical files registered at the same moment: the unique index lets exactly one win
        return {**public_doc(await db.legal_documents.find_one({"source_id": source_id, "sha256": digest})), "duplicate": True}
    return {**public_doc(doc), "duplicate": False}


async def _instrument(meta: dict) -> dict:
    jurisdiction = meta.get("jurisdiction", "IN")
    if not territories.valid_code(jurisdiction):
        raise ValueError("jurisdiction must be IN (central law) or a State/UT code such as IN-TG.")
    key = norm(meta["title"])
    found = await db.instruments.find_one({"title_norm": key, "jurisdiction": jurisdiction})
    if found:
        return found
    doc = {"id": str(uuid.uuid4()), "title": meta["title"].strip(), "title_norm": key, "short_names": [s.strip() for s in meta.get("short_names", []) if s.strip()], "kind": meta.get("kind", "act"),
           "jurisdiction": jurisdiction, "year": meta.get("year"), "created_at": now()}
    if doc["kind"] not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}.")
    await store.create(db, "instruments", doc)
    return doc


async def ingest(document_id: str, instrument: dict, version_label: str, *, effective_from: str | None = None, effective_to: str | None = None, evidence: str = "", parsed: dict | None = None) -> dict:
    """Parse a registered document into provisions (all unreviewed) under a new, never-overwritten version. `parsed` is a ready-made {"provisions", "warnings"} (used when the document is a set of
    draft sections that were each parsed on their own); otherwise the document's pages are parsed here."""
    if version_label not in VERSION_LABELS:
        raise ValueError(f"version_label must be one of {', '.join(VERSION_LABELS)}.")
    f, t = iso(effective_from, "effective_from"), iso(effective_to, "effective_to")
    if (f or t) and len(evidence.strip()) < 10:
        raise ValueError("A date of effect needs the evidence for it (for example the notification that brought it into force). Leave the date empty if it is not known.")
    document = await db.legal_documents.find_one({"id": document_id})
    if not document:
        raise ValueError("Unknown document.")
    blocked = use_blocked(await db.legal_sources.find_one({"id": document["source_id"]}) or {})
    if blocked:
        raise ValueError(blocked)
    inst = await _instrument(instrument)
    existing = await db.instrument_versions.find_one({"instrument_id": inst["id"], "document_id": document_id})
    if existing:
        return {"version_id": existing["id"], "instrument_id": inst["id"], "created": False, "provisions": await db.provisions.count_documents({"instrument_version_id": existing["id"]}), "warnings": existing.get("warnings", [])}
    parsed = parsed or legal_structure.parse_provisions(document["pages"])
    if not parsed["provisions"]:
        raise ValueError("No sections were found in that text. Check the document and its layout.")
    version = {"id": str(uuid.uuid4()), "instrument_id": inst["id"], "document_id": document_id, "label": version_label, "effective_from": f, "effective_to": t, "evidence": evidence.strip() if (f or t) else "",
               "warnings": parsed["warnings"], "created_at": now()}
    await store.create(db, "instrument_versions", version)
    rows, chunk_rows = [], []
    for p in parsed["provisions"]:
        pid = str(uuid.uuid4())
        rows.append({
            "id": pid, "instrument_id": inst["id"], "instrument_version_id": version["id"], "number": p["number"], "number_norm": p["number"].upper(), "heading": p["heading"], "part": p["part"],
            "chapter": p["chapter"], "page_start": p["page_start"], "kind": p["kind"], "components": p["components"], "text_full": p["text_full"], "content_sha256": sha256_text(p["text_full"]),
            "machine_read": document.get("ocr_status") == "machine-read", "page_uncertain": p["page_start"] in document.get("uncertain_pages", []),
            "review_status": "unreviewed", "reviewed_by": None, "reviewed_on": None, "created_at": now(),
        })
        chunk_rows += [{"id": str(uuid.uuid4()), "parent_id": pid, **c} for c in legal_structure.make_chunks(p)]
    await store.create_many(db, "provisions", rows)
    if chunk_rows:
        await store.create_many(db, "provision_chunks", chunk_rows)
    await store.change(db, "legal_documents", {"id": document_id}, {"index_status": "ingested-unreviewed"})
    from lib import legal_graph  # local import: legal_graph imports legal_search, which imports this module

    await legal_graph.build_edges(version["id"])
    return {"version_id": version["id"], "instrument_id": inst["id"], "created": True, "provisions": len(rows), "warnings": parsed["warnings"]}


SECTION_NUMBER = re.compile(r"^(?:Section|Article|Rule|Regulation|Order)\s+(?P<n>[0-9]+[A-Za-z]{0,3}(?:-[A-Za-z]{1,2})?)\s*,")


FIRST_LINE = re.compile(r"^(?P<n>[0-9]+[A-Za-z]{0,3}(?:-[A-Za-z]{1,2})?)\s*\.\s*(?P<h>.{0,400}?)\s*\.?\s*[\u2014\u2013-]+\s*(?P<rest>.*)$", re.S)
DASH_FIRST = re.compile(r"^(?P<n>[0-9]+[A-Za-z]{0,3}(?:-[A-Za-z]{1,2})?)\s*\.\s*[\u2014\u2013-]+\s*(?P<h>[^\u2014\u2013]{3,400}?)\s*\.\s*[\u2014\u2013-]+\s*(?P<rest>.*)$", re.S)
CHAPTER_TAIL = re.compile(r"^[ \t]*(?:CHAPTER|PART)\s+[IVXLCDM0-9]+[A-Z]?\b", re.M)


def _clean(s: str) -> str:
    return " ".join(str(s).split()).rstrip(". ").strip()


def draft_parts(draft: dict, number: str) -> tuple[str, str]:
    """(heading, words) of a draft section. The extractor keeps the section's own first line: "12. Heading.-Text" or "12.-Heading.-Text" (heading wrapped over lines, or missing from the
    entry). The heading is returned on one line; the words are the draft's own, cut at a Chapter/Part heading that the extractor left at the end of the section."""
    body = str(draft.get("text", "")).strip()
    entry_heading = _clean(draft.get("heading", ""))
    m = DASH_FIRST.match(body)
    if m and m.group("n").upper() == number.upper():
        heading, rest = _clean(m.group("h")), m.group("rest").strip()
    else:
        m = FIRST_LINE.match(body)
        if m and m.group("n").upper() == number.upper():
            heading, rest = _clean(m.group("h")) or entry_heading, m.group("rest").strip()
        else:
            heading, rest = entry_heading, re.sub(rf"^{re.escape(number)}\s*\.\s*", "", body, count=1)
    tail = CHAPTER_TAIL.search(rest)
    if tail and tail.start() > 0:
        rest = rest[: tail.start()].rstrip()
    return heading, rest


def draft_rest(draft: dict, number: str) -> str:
    """The words of a draft section after its own first line."""
    return draft_parts(draft, number)[1]


def draft_line(draft: dict, number: str) -> str:
    heading, rest = draft_parts(draft, number)
    return f"{number}. {heading}.\u2014{rest}" if heading else f"{number}. {rest}"


def draft_pages(drafts: list[dict]) -> tuple[list[str], list[str]]:
    """The Act's text rebuilt from its draft sections, in order (kept as the document's text, with its hash). The heading is written on one clean line (the PDF often wrapped it);
    the words of the section are the draft's own. A draft whose citation has no readable number is left out and reported."""
    lines, left_out = [], []
    for d in drafts:
        m = SECTION_NUMBER.match(str(d.get("citation", "")))
        if not m:
            left_out.append(str(d.get("citation", d.get("id", "?")))[:80])
            continue
        lines.append(draft_line(d, m.group("n")))
    return ["\n\n".join(lines)], left_out


def parse_drafts(drafts: list[dict]) -> dict:
    """One provision per draft section, each parsed on its own (so one odd entry cannot throw off the sections around it). A draft the parser cannot structure is kept whole as a single rule.
    {"provisions", "warnings", "left_out"}."""
    provisions, warnings, left_out = [], [], []
    for d in drafts:
        m = SECTION_NUMBER.match(str(d.get("citation", "")))
        if not m:
            left_out.append(str(d.get("citation", d.get("id", "?")))[:80])
            continue
        n = m.group("n")
        line = draft_line(d, n)
        res = legal_structure.parse_provisions([line])
        mine = [p for p in res["provisions"] if p["kind"] == "section" and p["number"].upper() == n.upper()]
        p = mine[0] if len(mine) == 1 and len(res["provisions"]) == 1 else None
        # Lossless: a provision is either structured with ALL the draft's words, or kept whole as one rule. (Some drafts hold footnotes or the start of the next section; splitting on those would drop words.)
        if p is not None and len(textmatch.norm(p["text_full"])) < 0.99 * len(textmatch.norm(line)):
            p = None
        if p is None:
            heading, rest = draft_parts(d, n)
            p = {"number": n, "heading": heading, "part": None, "chapter": None, "page_start": 1, "kind": "section", "components": [{"kind": "rule", "label": "", "text": rest}], "text_full": line}
            warnings.append(f"{n}: kept whole as one rule (it could not be split without losing words)")
        p["page_start"] = 1
        provisions.append(p)
    return {"provisions": provisions, "warnings": warnings[:200], "left_out": left_out}


async def ingest_drafts(act_id: str, source_id: str, instrument: dict, version_label: str = "consolidated", *, effective_from: str | None = None, effective_to: str | None = None, evidence: str = "") -> dict:
    """Bring an Act's draft sections (legal_source_candidates) into the structured store as UNREVIEWED provisions, so provisos, explanations and exceptions stay attached to their rule.
    The same gate as any other document applies: a source whose terms need written permission cannot be used until the permission is recorded. A draft can never make anything verified."""
    drafts = await db.legal_source_candidates.find({"act_id": act_id}, {"_id": 0}).sort("seq", 1).to_list(20000)
    if not drafts:
        raise ValueError("No draft sections for that Act are loaded. (If the drafts are switched off, the written permission has to be recorded first.)")
    pages, left_out = draft_pages(drafts)
    parsed = parse_drafts(drafts)
    document = await register_document(source_id, {"title": instrument["title"], "source_page_url": drafts[0].get("source_url", "")}, text_pages=pages)
    out = await ingest(document["id"], instrument, version_label, effective_from=effective_from, effective_to=effective_to, evidence=evidence, parsed=parsed)
    warnings = list(out.get("warnings", []))
    first = drafts[0]
    v = law_dates.validity(first.get("commencement", ""), first.get("legal_currency", ""), act_id)  # only dates written in the official manifest text; unknown stays unknown
    await store.set_commencement(db, out["instrument_id"], {
        "commencement_text": first.get("commencement", ""), "legal_currency_text": first.get("legal_currency", ""), "act_in_force_from": v["from"].isoformat() if v["from"] else None,
        "act_in_force_until": v["to"].isoformat() if v["to"] else None, "act_in_force_after_year": v["after_year"], "act_commencement_basis": v["basis"], **_notified_fields(v)},
        reviewed_by=v.get("reviewed_by"), reviewed_on=v.get("reviewed_on"))
    if left_out:
        warnings.append(f"{len(left_out)} draft(s) had no readable section number and were left out: {', '.join(left_out[:5])}")
    if out.get("created") and out["provisions"] != len(drafts) - len(left_out):
        warnings.append(f"The parser found {out['provisions']} provisions for {len(drafts) - len(left_out)} draft sections: compare them before any review.")
    return {**out, "drafts": len(drafts), "warnings": warnings}


async def review_provision(provision_id: str, reviewer: str, on: str, acknowledge_machine_read: bool = False, acknowledge_second_source_difference: bool = False) -> dict:
    """Record that a named person compared this provision with the official text. The text must be unchanged since ingestion."""
    p = await db.provisions.find_one({"id": provision_id})
    if not p:
        raise ValueError("Unknown provision.")
    if len(reviewer.strip()) < 5:
        raise ValueError("Give the reviewer's full name.")
    day = iso(on, "reviewed_on")
    if not day:
        raise ValueError("Give the date of the review.")
    if sha256_text(p["text_full"]) != p["content_sha256"]:
        raise ValueError("The stored text no longer matches its recorded hash, so it cannot be marked reviewed.")
    if (p.get("machine_read") or p.get("page_uncertain")) and not acknowledge_machine_read:
        raise ValueError("This provision comes from a scan read by a machine" + (" and its page was read with low confidence or unreadable words" if p.get("page_uncertain") else "")
                         + ". Compare it word by word with the official page, then confirm that by ticking the acknowledgement.")
    version = await db.instrument_versions.find_one({"id": p["instrument_version_id"]})
    document = await db.legal_documents.find_one({"id": version["document_id"], "sha256": {"$exists": True}}) if version else None
    if not document:
        raise ValueError("A provision can be reviewed only if it points to a registered, hashed source document.")
    if not (document.get("file_url") or document.get("source_page_url") or "").strip():
        raise ValueError("A provision can be marked reviewed only if its source document has a source address (URL), so anyone can check it against the official text. Add the address to the document first.")
    if (p.get("second_source") or {}).get("status") == "DIFFERENT" and not acknowledge_second_source_difference:
        raise ValueError("A second official source worded this provision differently. Read both, then confirm that by ticking the acknowledgement.")
    await store.record_review(db, "provisions", provision_id, "reviewed", reviewer, day, (document.get("file_url") or document.get("source_page_url") or "").strip())
    return clean(await db.provisions.find_one({"id": provision_id}))


async def reject_provision(provision_id: str, reviewer: str, on: str, reason: str) -> dict:
    """A named reviewer says this loaded text does NOT match the official text. It stays unreviewed (never used as verified) and is marked rejected with the reason."""
    p = await db.provisions.find_one({"id": provision_id})
    if not p:
        raise ValueError("Unknown provision.")
    if len(reviewer.strip()) < 5:
        raise ValueError("Give the reviewer's full name.")
    day = iso(on, "reviewed_on")
    if not day:
        raise ValueError("Give the date of the review.")
    if len((reason or "").strip()) < 10:
        raise ValueError("Say what does not match the official text.")
    version = await db.instrument_versions.find_one({"id": p["instrument_version_id"]})
    document = (await db.legal_documents.find_one({"id": version["document_id"]}, {"pages": 0}) if version else None) or {}
    await store.record_review(db, "provisions", provision_id, "rejected", reviewer, day, (document.get("file_url") or document.get("source_page_url") or "").strip(), reason=reason)
    return clean(await db.provisions.find_one({"id": provision_id}))


async def integrity_report() -> dict:
    """Checks every loaded provision against its own recorded hash and source. Flags, never repairs: a changed text or a reviewed provision without a source address needs a person."""
    mismatched, no_source = [], []
    async for p in db.provisions.find({}, {"id": 1, "number": 1, "text_full": 1, "content_sha256": 1, "review_status": 1, "instrument_id": 1, "instrument_version_id": 1}):
        if sha256_text(p["text_full"]) != p["content_sha256"]:
            mismatched.append({"provision_id": p["id"], "number": p["number"], "review_status": p.get("review_status", "unreviewed")})
        if p.get("review_status") == "reviewed":
            v = await db.instrument_versions.find_one({"id": p["instrument_version_id"]})
            d = await db.legal_documents.find_one({"id": v["document_id"]}, {"pages": 0}) if v else None
            if not d or not (d.get("file_url") or d.get("source_page_url") or "").strip():
                no_source.append({"provision_id": p["id"], "number": p["number"]})
    return {"hash_mismatch": mismatched, "reviewed_without_source_url": no_source, "ok": not mismatched and not no_source,
            "meaning": "A hash mismatch means the stored text is no longer what was loaded. Such a provision cannot be marked reviewed, and one already reviewed must be re-loaded and re-reviewed."}


async def build_library_entry(provision_id: str) -> dict:
    """A draft in the library's own format, ALWAYS marked unverified. A person saves it under backend/data/legal_library/pending/ and a lawyer approves it
    with scripts/library_review.py, which is the only way text becomes verifying."""
    p = await db.provisions.find_one({"id": provision_id})
    if not p:
        raise ValueError("Unknown provision.")
    inst = await db.instruments.find_one({"id": p["instrument_id"]})
    version = await db.instrument_versions.find_one({"id": p["instrument_version_id"]})
    doc = await db.legal_documents.find_one({"id": version["document_id"]})
    source = await db.legal_sources.find_one({"id": doc["source_id"]})
    slug = re.sub(r"[^a-z0-9]+", "-", f"{inst['title']}-{p['number']}-{version['label']}".lower()).strip("-")
    return {
        "_note": "UNVERIFIED - pending lawyer review. Compare with the official source, then ask a lawyer to run scripts/library_review.py approve.",
        "id": slug, "citation": f"{'Section ' if p['kind'] == 'section' else ''}{p['number']}, {inst['title']}", "kind": "STATUTE_SECTION" if p["kind"] == "section" else "OTHER",
        "jurisdiction": inst["jurisdiction"], "text": p["text_full"], "source_name": f"{source['name']} - {doc['title']}", "source_url": doc.get("file_url") or doc.get("source_page_url") or "",
        "version": version["label"] + (f", effective {version['effective_from']}" if version.get("effective_from") else ", effective date not recorded"),
        "status": PENDING_STATUS, "reviewer": None, "reviewed_on": None,
    }


async def coverage() -> dict:
    """Counts straight from the database. 'Indexed' means loaded; it never means complete."""
    reviewed = await db.provisions.count_documents({"review_status": "reviewed"})
    total = await db.provisions.count_documents({})
    rejected = await db.provisions.count_documents({"review_status": "rejected"})
    per = []
    async for i in db.instruments.find({}).sort("title_norm", 1):
        versions = await db.instrument_versions.count_documents({"instrument_id": i["id"]})
        n = await db.provisions.count_documents({"instrument_id": i["id"]})
        r = await db.provisions.count_documents({"instrument_id": i["id"], "review_status": "reviewed"})
        warn = await db.instrument_versions.count_documents({"instrument_id": i["id"], "warnings.0": {"$exists": True}})
        undated = await db.instrument_versions.count_documents({"instrument_id": i["id"], "effective_from": None})
        per.append({"instrument": i["title"], "versions": versions, "provisions": n, "reviewed": r, "versions_with_parser_warnings": warn, "versions_without_effective_date": undated})
    return {
        "sources": await db.legal_sources.count_documents({}), "sources_terms_not_read": await db.legal_sources.count_documents({"status": "terms-not-read"}),
        "sources_needing_permission": await db.legal_sources.count_documents({"permission_required": True, "permission_reference": ""}),
        "documents": await db.legal_documents.count_documents({}), "instruments": await db.instruments.count_documents({}), "provisions": total, "provisions_reviewed": reviewed, "provisions_rejected": rejected,
        "mappings": await db.code_mappings.count_documents({}), "mappings_reviewed": await db.code_mappings.count_documents({"review_status": "reviewed"}), "per_instrument": per,
        "meaning": "These are counts of what has been loaded. They do not mean the platform covers every Act or judgment, and unreviewed text cannot verify anything.",
    }


def _notified_fields(v: dict) -> dict:
    """The instrument fields that say where a start date came from when it came from a Gazette notification (source, stages, an exception note, whether a person reviewed it)."""
    return {"act_commencement_source": v.get("source", ""), "act_in_force_stages": v.get("stages"), "act_commencement_except": v.get("except_note", ""), "act_commencement_reviewed": bool(v.get("verified"))}


async def refresh_commencement() -> list[dict]:
    """Apply the Gazette notifications in `_commencement_notifications.json` to the loaded instruments whose own text gives no start date. An instrument matches by one of its short names
    (lower case) being an act id in the notification. A date the instrument already has from its own text is left alone. Returns what was set."""
    done = []
    async for inst in db.instruments.find({}, {"_id": 0}):
        if inst.get("act_in_force_from") and not inst.get("act_commencement_source"):
            continue  # a date from the Act's own text wins
        for short in [str(s).lower() for s in inst.get("short_names", [])]:
            n = law_dates.notification_for(short)
            if not n:
                continue
            v = law_dates.validity("", inst.get("legal_currency_text", ""), short)
            if not v.get("from"):
                continue
            await store.set_commencement(db, inst["id"], {
                "commencement_text": v["note"], "act_in_force_from": v["from"].isoformat(), "act_in_force_until": v["to"].isoformat() if v["to"] else None, "act_in_force_after_year": None,
                "act_commencement_basis": v["basis"], **_notified_fields(v)}, reviewed_by=v.get("reviewed_by"), reviewed_on=v.get("reviewed_on"))
            done.append({"instrument": inst["title"], "from": v["from"].isoformat(), "basis": v["basis"], "notification": n["number"]})
            break
    return done


async def approve_to_library(provision_id: str, reviewer: str, on: str, acknowledge_machine_read: bool = False, acknowledge_second_source_difference: bool = False) -> tuple[dict, dict]:
    """A named reviewer compared this provision with the official source: mark it reviewed AND add it to the verified library, in that order and together. All the usual checks apply
    (name, date, text unchanged since loading, a source address, the machine-read and second-source acknowledgements). A rejected provision cannot be approved. If the library refuses
    the entry, the provision goes back to its earlier status, so a section is never "reviewed" without a library entry. Returns (provision, library entry)."""
    p = await db.provisions.find_one({"id": provision_id})
    if not p:
        raise ValueError("Unknown provision.")
    if p.get("review_status") == "rejected":
        raise ValueError("This section was rejected, so it cannot be approved. Load the corrected text as a new version and review that.")
    before = {k: p.get(k) for k in ("review_status", "reviewed_by", "reviewed_on")}
    entry = await build_library_entry(provision_id)
    entry["heading"] = p.get("heading", "")
    version = await db.instrument_versions.find_one({"id": p["instrument_version_id"]})
    document = await db.legal_documents.find_one({"id": version["document_id"]}, {"pages": 0}) or {}
    reviewed = await review_provision(provision_id, reviewer, on, acknowledge_machine_read, acknowledge_second_source_difference)
    try:
        saved = await library.approve_entry(entry, reviewer, on, provision_id=provision_id, provision_sha256=p["content_sha256"], document_sha256=document.get("sha256", ""))
    except ValueError:
        await store.restore_review(db, "provisions", provision_id, before)
        raise
    return reviewed, saved


async def withdraw_from_library(provision_id: str, reviewer: str, on: str, reason: str) -> dict:
    """Undo an approval made on the reviewer screen: the library entry is WITHDRAWN (kept on record) and the provision goes back to unreviewed."""
    found = await store.verified_entries({"provision_id": provision_id}, limit=1, db=db)
    entry = found[0] if found else None
    if not entry:
        raise ValueError("That section is not in the verified library.")
    out = await library.withdraw_entry(entry["id"], reviewer, on, reason)
    await store.restore_review(db, "provisions", provision_id, {"review_status": "unreviewed", "reviewed_by": None, "reviewed_on": None})
    return out


async def set_document_url(document_id: str, url: str) -> dict:
    """Record the official address of a loaded document (a reviewer cannot approve a section whose source has no address). The text and its hash do not change."""
    u = (url or "").strip()
    if not re.match(r"^https?://\S{4,480}$", u):
        raise ValueError("Give the web address of the official source, starting with https://")
    d = await db.legal_documents.find_one({"id": document_id}, {"pages": 0})
    if not d:
        raise ValueError("Unknown document.")
    await store.change(db, "legal_documents", {"id": document_id}, {"source_page_url": u})
    return {"id": document_id, "source_page_url": u}
