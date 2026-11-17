import asyncio
import base64
import hashlib
import io
import logging
import os
import uuid
import zipfile
from typing import Literal
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from lib.ai import _TIER as _ai_tier
from lib.ai import ai_failure, ask_json, log_ai_failure, read_image_text
from lib.auth import audit, current_user, now, require_intelligence
from lib.plans import context_budget, gate_ai
from lib.classify import DOC_CLASSES, classify_document, media_kind
from lib import filestore
from lib import doc_diff
from lib.db import db
from lib.extract import extract_entities, extract_pages, unread_parts
from lib.matter_context import build_corpus, index_text, select_context
from lib.purge import purge_document
from lib import ocr, ocr_engine
from lib.neutral import neutralize
from lib.safety import fence, note_for, scan
from lib.ratelimit import AI_LIMIT, UPLOAD_LIMIT, hit
from lib.uploads import read_limited, safe_filename, validate_content
from lib.verify import find_quote
from models.schemas import (
    Anomaly,
    ClauseFlag,
    DocumentAnalysis,
    DocumentDetail,
    DocumentOut,
    KeyFact,
    PersonRef,
)
from routers.matters import get_matter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])

class _SkipReading(Exception):
    """Internal: stop reading a photo (the person is told why) but keep the file."""


MAX_MATTER_DOCS = 400
MB = 1024 * 1024
TEXT_MAX = 15 * MB
MEDIA_MAX = 50 * MB
TEXT_EXT = (".pdf", ".docx", ".xlsx", ".pptx", ".eml", ".txt", ".md")
MEDIA_EXT = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".mp3", ".wav", ".m4a")
ALLOWED = TEXT_EXT + MEDIA_EXT
MIME = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".m4a": "audio/mp4", ".txt": "text/plain", ".md": "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_OCR_PROMPT = (
    "This image is evidence in a legal matter. Transcribe ALL the text you can see, exactly as written and in "
    "order. If there is no readable text, reply with nothing. Do NOT describe the picture and do NOT add anything."
)


async def _read_scan(user: dict, matter_id: str, data: bytes, err: str | None) -> tuple[list[str], str | None, str | None, list[dict]]:
    """A scanned PDF has no text layer: read it with a vision model. It costs one AI request, so the plan's allowance applies."""
    try:
        tier = await gate_ai(user, "ocr")
        token = _ai_tier.set("free" if tier == "free" else "full")  # a free plan reads scans with the light models only
        try:
            pages, meta = await ocr_engine.read_pdf(f"doc-scan-{matter_id}", data)
        finally:
            _ai_tier.reset(token)
    except HTTPException as exc:
        return [], f"This is a scanned PDF. Reading scans uses an AI request. {exc.detail}", None, []
    except ValueError as exc:
        return [], str(exc), None, []
    except Exception:  # noqa: BLE001
        logger.info("scanned PDF could not be read", exc_info=True)
        return [], "We could not read this scan right now. Try again, or upload a clearer copy.", None, []
    if not any(p.strip() for p in pages):
        return [], "We could not find any readable text in this scan. Try a clearer copy.", None, []
    return pages, None, ocr.READING_NOTE, meta


@router.get("/matters/{matter_id}/documents", response_model=list[DocumentOut])
async def list_documents(matter_id: str, user: dict = Depends(current_user)):
    await get_matter(matter_id, user)
    docs = await db.documents.find({"matter_id": matter_id}).sort("created_at", -1).to_list(200)
    return [DocumentOut(**d) for d in docs]


@router.post(
    "/matters/{matter_id}/documents", response_model=DocumentOut, dependencies=[Depends(UPLOAD_LIMIT)]
)
async def upload_document(
    matter_id: str, file: UploadFile = File(...), user: dict = Depends(current_user)
):
    await get_matter(matter_id, user)
    if await db.documents.count_documents({"matter_id": matter_id}) >= MAX_MATTER_DOCS:  # a hard cap, so no list in the product is ever silently cut short
        raise HTTPException(status_code=409, detail=f"A matter can hold up to {MAX_MATTER_DOCS} documents. Start a second matter for the rest.")
    filename = safe_filename(file.filename)
    kind = media_kind(filename)
    limit = MEDIA_MAX if kind != "TEXT" else TEXT_MAX
    data = await read_limited(file, limit, f"File exceeds the {limit // MB} MB limit")
    return await _ingest(user, matter_id, filename, data)


async def _ingest(user: dict, matter_id: str, filename: str, data: bytes) -> DocumentOut:
    """Validate, read and store one file in a matter. Shared by the single upload and the zip batch."""
    if await db.documents.count_documents({"matter_id": matter_id}) >= MAX_MATTER_DOCS:
        raise HTTPException(status_code=409, detail=f"A matter can hold up to {MAX_MATTER_DOCS} documents. Start a second matter for the rest.")
    kind = media_kind(filename)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    validate_content(
        filename, data, ALLOWED, "Upload a PDF, Word, Excel, PowerPoint, email (.eml), text, image, audio or video file"
    )
    checksum = hashlib.sha256(data).hexdigest()
    dup = await db.documents.find_one({"matter_id": matter_id, "checksum": checksum})
    if dup:
        raise HTTPException(
            status_code=409, detail=f"This exact file is already in the matter as '{dup['filename']}'. If your connection dropped while you were sending it, it arrived the first time: you do not need to send it again."
        )

    err: str | None = None
    reading_note = None
    page_meta: list[dict] = []
    if kind == "TEXT":
        pages, err = await asyncio.to_thread(extract_pages, filename, data)
        if not pages and filename.lower().endswith(".pdf") and (err or "").startswith("No extractable text"):
            pages, err, reading_note, page_meta = await _read_scan(user, matter_id, data, err)
    elif kind == "IMAGE":
        pages = []  # best effort: read any text in the photo; the file is kept either way
        try:
            try:
                tier = await gate_ai(user, "ocr")  # same daily allowance and light-model rule as every other AI request
            except HTTPException as exc:
                reading_note = f"The text in this photo was not read. {exc.detail}"
                raise _SkipReading from exc
            await hit("ai", user["id"], 40, 3600)
            text = await read_image_text(
                f"doc-ocr-{matter_id}", base64.b64encode(data).decode(), _OCR_PROMPT,
                MIME.get(os.path.splitext(filename.lower())[1], "image/png"), tier=tier,
            )
            pages = [text] if text.strip() else []
            page_meta = [ocr_engine._meta(1, "hosted-vision", "any", None, [ocr_engine.HOSTED_WARNING], text)] if pages else []
        except _SkipReading:
            pass
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            logger.info("image OCR unavailable; registering image without text", exc_info=True)
    else:  # video / audio: nothing to extract - registered as evidence, described by the user
        pages = []
    uncertain = set(ocr_engine.uncertain_pages(page_meta))
    if kind == "TEXT" and pages:
        blank = [i for i, p in enumerate(pages, start=1) if not p.strip()] if filename.lower().endswith(".pdf") else []
        unread = unread_parts(filename, data)
        if blank:  # a page with no text among pages that have it: probably a picture, so nothing can be said about what is on it
            uncertain |= set(blank)
            reading_note = (reading_note or "") + f" Page(s) {', '.join(map(str, blank[:20]))} have no readable text and were not read."
        if unread:  # parts of a Word file that the reader does not extract
            uncertain |= set(range(1, len(pages) + 1))
            reading_note = (reading_note or "") + f" This Word file contains {', '.join(unread)} which VIDHI does not read, so statements about what is missing from it are not certain."
        reading_note = reading_note.strip() if reading_note else reading_note
    entities = extract_entities(pages) if pages else {"citations": [], "dates": []}
    flags = scan("\n".join(pages) + "\n" + filename)  # instruction-like text: still used as data, but the person is told
    file_id = await filestore.put(filename, data, {"matter_id": matter_id, "organization_id": user["organization_id"]})
    doc = {
        "id": str(uuid.uuid4()),
        "matter_id": matter_id,
        "organization_id": user["organization_id"],
        "filename": filename,
        "document_type": filename.rsplit(".", 1)[-1].upper(),
        "size_bytes": len(data),
        "page_count": len(pages),
        "processing_status": "READY" if (pages or kind != "TEXT") else "FAILED",
        "failure_reason": err,
        "security_note": note_for(flags) or None,
        "reading_note": reading_note,
        "page_meta": page_meta,  # how each page was read (engine, languages, real confidence only when an engine reported one, warnings)
        "uncertain_pages": sorted(uncertain),
        "checksum": checksum,
        "doc_class": classify_document(filename, pages),
        "doc_class_source": "AUTO",
        "media_kind": kind,
        "description": "",
        "text_available": bool(pages),
        "has_file": True,
        "gridfs_id": file_id,
        "citations": entities["citations"],
        "dates": entities["dates"],
        "pages": pages,
        "created_by": user["id"],
        "created_at": now(),
    }
    await db.documents.insert_one(dict(doc))
    await audit(user, "DOCUMENT_UPLOAD", matter_id=matter_id, detail=filename)
    if flags:
        await audit(user, "DOCUMENT_INSTRUCTION_LIKE_TEXT", matter_id=matter_id, detail=f"{filename}: {', '.join(flags)}")
    doc.pop("pages", None)
    return DocumentOut(**doc)


ZIP_MAX = 100 * MB  # the zip itself
ZIP_MAX_FILES = 50  # files taken from one zip
ZIP_MAX_UNZIPPED = 300 * MB  # what the members hold once opened; a header can lie, so the bytes actually read are counted too


@router.post("/matters/{matter_id}/documents/zip", dependencies=[Depends(UPLOAD_LIMIT)])
async def upload_zip(matter_id: str, file: UploadFile = File(...), user: dict = Depends(current_user)):
    """Add the files in a zip to a matter, each one checked and read exactly as if uploaded alone. A file that cannot be added is listed with its reason; the others are still added.
    Folders are flattened (only the file name is kept), zips inside zips and password-protected files are not opened, and system files (__MACOSX, hidden files) are skipped."""
    await get_matter(matter_id, user)
    name = safe_filename(file.filename)
    if not name.lower().endswith(".zip"):
        raise HTTPException(status_code=415, detail="Upload a .zip file here. For a single document use the ordinary upload.")
    data = await read_limited(file, ZIP_MAX, f"The zip exceeds the {ZIP_MAX // MB} MB limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=415, detail="That file does not look like a valid ZIP file.") from exc
    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) > ZIP_MAX_FILES:
            raise HTTPException(status_code=413, detail=f"This zip holds {len(infos)} files and the limit is {ZIP_MAX_FILES} at a time. Split it into smaller zips.")
        if sum(i.file_size for i in infos) > ZIP_MAX_UNZIPPED:
            raise HTTPException(status_code=413, detail=f"This zip holds more than {ZIP_MAX_UNZIPPED // MB} MB once opened, so it was not read. Split it into smaller zips.")
        results: list[dict] = []
        total = 0
        for info in infos:
            shown = os.path.basename(info.filename.replace("\\", "/")) or info.filename
            if "__MACOSX/" in info.filename or shown.startswith((".", "~$")):
                results.append({"filename": shown, "status": "skipped", "reason": "A system or hidden file."})
                continue
            fname = safe_filename(shown)
            ext = os.path.splitext(fname.lower())[1]
            if info.flag_bits & 0x1:
                results.append({"filename": fname, "status": "skipped", "reason": "Password-protected files are not opened. Remove the password and add it again."})
                continue
            if ext == ".zip":
                results.append({"filename": fname, "status": "skipped", "reason": "A zip inside a zip is not opened. Unpack it and add its files."})
                continue
            if ext not in ALLOWED:
                results.append({"filename": fname, "status": "skipped", "reason": "This file type is not supported."})
                continue
            limit = MEDIA_MAX if media_kind(fname) != "TEXT" else TEXT_MAX
            with archive.open(info) as member:
                blob = member.read(limit + 1)
            total += len(blob)
            if len(blob) > limit:
                results.append({"filename": fname, "status": "skipped", "reason": f"The file exceeds the {limit // MB} MB limit."})
                continue
            if total > ZIP_MAX_UNZIPPED:
                results.append({"filename": fname, "status": "skipped", "reason": "The zip holds more than the allowed total once opened."})
                continue
            try:
                doc = await _ingest(user, matter_id, fname, blob)
                results.append({"filename": fname, "status": "added", "document_id": doc.id, "processing_status": doc.processing_status})
            except HTTPException as exc:
                results.append({"filename": fname, "status": "skipped", "reason": str(exc.detail)})
    added = sum(1 for r in results if r["status"] == "added")
    await audit(user, "DOCUMENT_ZIP_UPLOAD", matter_id=matter_id, detail=f"{name}: {added} added, {len(results) - added} skipped")
    return {"added": added, "skipped": len(results) - added, "results": results}


class CompareIn(BaseModel):
    first_id: str = Field(min_length=1, max_length=64)
    second_id: str = Field(min_length=1, max_length=64)


@router.post("/documents/compare")
async def compare_documents(body: CompareIn, user: dict = Depends(current_user)):
    """What is added, deleted or changed between two documents of this organisation, word by word, on the text VIDHI read. Changes nothing; no AI."""
    if body.first_id == body.second_id:
        raise HTTPException(status_code=422, detail="Choose two different documents to compare.")
    docs = []
    for doc_id in (body.first_id, body.second_id):
        doc = await db.documents.find_one({"id": doc_id, "organization_id": user["organization_id"]}, {"pages": 1, "filename": 1, "matter_id": 1, "uncertain_pages": 1, "reading_note": 1, "id": 1, "text_available": 1})
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        if not doc.get("pages"):
            raise HTTPException(status_code=422, detail=f"'{doc['filename']}' has no readable text, so it cannot be compared.")
        docs.append(doc)
    texts = ["\n\n".join(d["pages"]) for d in docs]
    try:
        result = await asyncio.to_thread(doc_diff.compare, texts[0], texts[1])
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=f"A document is longer than {doc_diff.MAX_CHARS:,} characters of text, so the comparison was not run. Compare it in parts.") from exc
    warnings = [f"'{d['filename']}': {d['reading_note']}" for d in docs if d.get("reading_note")] + [
        f"'{d['filename']}': pages {', '.join(map(str, d['uncertain_pages'][:15]))} were read with low confidence, so differences there may be reading errors." for d in docs if d.get("uncertain_pages")
    ]
    for d in docs:
        await audit(user, "DOCUMENT_COMPARE", matter_id=d["matter_id"], detail=f"{docs[0]['filename']} vs {docs[1]['filename']}")
    return {"first": {"id": docs[0]["id"], "filename": docs[0]["filename"]}, "second": {"id": docs[1]["id"], "filename": docs[1]["filename"]}, "warnings": warnings, **result}


class NoteIn(BaseModel):
    page: int = Field(ge=1, le=100000)
    note: str = Field(min_length=1, max_length=2000)
    quote: str = Field(default="", max_length=500)  # the passage the note is about, if the person copied it in


MAX_NOTES_PER_DOCUMENT = 500


async def _doc_in_org(document_id: str, user: dict) -> dict:
    doc = await db.documents.find_one({"id": document_id, "organization_id": user["organization_id"]}, {"id": 1, "matter_id": 1, "page_count": 1, "filename": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/documents/{document_id}/notes")
async def list_notes(document_id: str, user: dict = Depends(current_user)):
    await _doc_in_org(document_id, user)
    rows = await db.doc_notes.find({"document_id": document_id, "organization_id": user["organization_id"]}, {"_id": 0, "organization_id": 0}).sort([("page", 1), ("created_at", 1)]).to_list(MAX_NOTES_PER_DOCUMENT)
    return rows


@router.post("/documents/{document_id}/notes", status_code=201)
async def add_note(document_id: str, body: NoteIn, user: dict = Depends(current_user)):
    """A note on one page of a document, kept with the document and seen by everyone in the firm who can open it. It is the firm's own remark: not evidence, not sent to any AI."""
    doc = await _doc_in_org(document_id, user)
    if doc.get("page_count") and body.page > doc["page_count"]:
        raise HTTPException(status_code=422, detail=f"This document has {doc['page_count']} page(s).")
    if await db.doc_notes.count_documents({"document_id": document_id}) >= MAX_NOTES_PER_DOCUMENT:
        raise HTTPException(status_code=409, detail=f"A document can hold up to {MAX_NOTES_PER_DOCUMENT} notes.")
    row = {"id": str(uuid.uuid4()), "organization_id": user["organization_id"], "document_id": document_id, "matter_id": doc["matter_id"], "page": body.page, "note": body.note.strip(), "quote": body.quote.strip(),
           "author": user.get("full_name") or user.get("email") or "Someone", "created_by": user["id"], "created_at": now()}
    if not row["note"]:
        raise HTTPException(status_code=422, detail="Write the note first.")
    await db.doc_notes.insert_one(dict(row))
    await audit(user, "DOCUMENT_NOTE_ADD", matter_id=doc["matter_id"], detail=f"{doc['filename']} p.{body.page}")
    row.pop("organization_id")
    row.pop("_id", None)
    return row


@router.delete("/documents/{document_id}/notes/{note_id}")
async def delete_note(document_id: str, note_id: str, user: dict = Depends(current_user)):
    doc = await _doc_in_org(document_id, user)
    gone = await db.doc_notes.delete_one({"id": note_id, "document_id": document_id, "organization_id": user["organization_id"]})
    if not gone.deleted_count:
        raise HTTPException(status_code=404, detail="Note not found")
    await audit(user, "DOCUMENT_NOTE_DELETE", matter_id=doc["matter_id"], detail=note_id)
    return {"ok": True}


@router.get("/documents/{document_id}", response_model=DocumentDetail)
async def read_document(document_id: str, user: dict = Depends(current_user)):
    doc = await db.documents.find_one(
        {"id": document_id, "organization_id": user["organization_id"]}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await audit(user, "DOCUMENT_ACCESS", matter_id=doc["matter_id"], detail=doc["filename"])
    return DocumentDetail(**doc)


@router.get("/documents/{document_id}/file")
async def download_document(document_id: str, user: dict = Depends(current_user)):
    """The original uploaded file (e.g. the CCTV clip), for the owner's organisation only."""
    doc = await db.documents.find_one({"id": document_id, "organization_id": user["organization_id"]})
    if not doc or not doc.get("gridfs_id"):
        raise HTTPException(status_code=404, detail="File not found")
    data = await filestore.read(doc["gridfs_id"])
    ext = os.path.splitext(doc["filename"].lower())[1]
    await audit(user, "DOCUMENT_DOWNLOAD", matter_id=doc["matter_id"], detail=doc["filename"])
    return Response(
        content=data,
        media_type=MIME.get(ext, "application/octet-stream"),
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urlquote(doc['filename'])}"},
    )


MAX_EDIT_PARAGRAPHS = 3000


async def _docx_of(document_id: str, user: dict):
    """The stored Word file as a python-docx Document (never changed in place), or a plain refusal."""
    import docx  # imported here: only the Word editor needs it

    doc = await db.documents.find_one({"id": document_id, "organization_id": user["organization_id"]})
    if not doc or not doc.get("gridfs_id"):
        raise HTTPException(status_code=404, detail="File not found")
    if not doc["filename"].lower().endswith(".docx"):
        raise HTTPException(status_code=422, detail="Only Word (.docx) files can be edited here.")
    data = await filestore.read(doc["gridfs_id"])
    try:
        return doc, docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="This Word file could not be opened for editing.") from exc


@router.get("/documents/{document_id}/paragraphs")
async def docx_paragraphs(document_id: str, user: dict = Depends(current_user)):
    """The body paragraphs of a Word file, in order, for the editor. Tables, headers and pictures are not shown and are kept as they are."""
    doc, word = await _docx_of(document_id, user)
    paras = [p.text for p in word.paragraphs]
    await audit(user, "DOCUMENT_ACCESS", matter_id=doc["matter_id"], detail=doc["filename"])
    return {"filename": doc["filename"], "paragraphs": paras[:MAX_EDIT_PARAGRAPHS], "truncated": len(paras) > MAX_EDIT_PARAGRAPHS}


class ParagraphEdit(BaseModel):
    index: int = Field(ge=0, lt=100000)
    text: str = Field(max_length=20000)


class EditCopyIn(BaseModel):
    edits: list[ParagraphEdit] = Field(min_length=1, max_length=MAX_EDIT_PARAGRAPHS)


@router.post("/documents/{document_id}/edit-copy")
async def docx_edit_copy(document_id: str, body: EditCopyIn, user: dict = Depends(current_user)):
    """Saves the edited paragraphs as a NEW document in the same matter ("... (edited).docx"). The original is never changed; tables, headers and pictures are carried over untouched.
    A changed paragraph keeps the look of its first run; text styled in several ways inside one changed paragraph takes the first style."""
    doc, word = await _docx_of(document_id, user)
    paras = word.paragraphs
    changed = 0
    for e in body.edits:
        if e.index >= len(paras):
            raise HTTPException(status_code=422, detail=f"There is no paragraph {e.index + 1} in this document.")
        p = paras[e.index]
        if p.text == e.text:
            continue
        if p.runs:
            p.runs[0].text = e.text
            for r in p.runs[1:]:
                r.text = ""
        else:
            p.add_run(e.text)
        changed += 1
    if not changed:
        raise HTTPException(status_code=422, detail="Nothing was changed.")
    buf = io.BytesIO()
    word.save(buf)
    stem = os.path.splitext(doc["filename"])[0]
    out = await _ingest(user, doc["matter_id"], f"{stem} (edited).docx", buf.getvalue())
    await audit(user, "DOCUMENT_EDIT_COPY", matter_id=doc["matter_id"], detail=f"{document_id} -> {out.id}")
    return {"id": out.id, "filename": out.filename, "changed": changed}


class DocumentPatch(BaseModel):
    doc_class: Literal[DOC_CLASSES] | None = None  # type: ignore[valid-type]
    description: str | None = Field(default=None, max_length=2000)


@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def update_document(document_id: str, body: DocumentPatch, user: dict = Depends(current_user)):
    """Correct the document type, or describe a video/audio file (the only 'text' such evidence has)."""
    doc = await db.documents.find_one({"id": document_id, "organization_id": user["organization_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    patch: dict = {}
    if body.doc_class is not None:
        patch["doc_class"], patch["doc_class_source"] = body.doc_class, "USER"
    if body.description is not None:
        patch["description"] = body.description.strip()
    if patch:
        await db.documents.update_one({"id": document_id}, {"$set": patch})
        await audit(user, "DOCUMENT_UPDATE", matter_id=doc["matter_id"], detail=doc["filename"])
    return DocumentOut(**(await db.documents.find_one({"id": document_id})))


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str, user: dict = Depends(current_user)):
    doc = await db.documents.find_one({"id": document_id, "organization_id": user["organization_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await purge_document(doc)  # the same function the 30-day expiry job uses
    await audit(user, "DOCUMENT_DELETE", matter_id=doc["matter_id"], detail=document_id)
    return {"ok": True}


# ---------------------------------------------------------------------------------------------
# Analysis: the prompt and fields depend on WHAT the document is
# ---------------------------------------------------------------------------------------------
CONTRACT_SCHEMA = (
    '{"summary": string, "flags": [{"clause": string, "risk": "HIGH"|"MEDIUM"|"LOW", "why": string, '
    '"page": number, "quote": string}]}'
)
EVIDENCE_SCHEMA = (
    '{"summary": string, "key_facts": [{"fact": string, "page": number, "quote": string}], '
    '"people": [{"name": string, "role": string, "page": number, "quote": string}], '
    '"evidence_items": [{"kind": "FINGERPRINT"|"FOOTPRINT"|"DNA"|"CCTV_SIGHTING"|"WITNESS_STATEMENT"|'
    '"DEVICE_RECORD"|"DOCUMENT"|"OTHER", "label": string, "status": "MATCHED"|"UNMATCHED"|"UNIDENTIFIED"|"UNKNOWN", '
    '"identified_as": string|null, "location": string|null, "page": number, "quote": string}], '
    '"anomalies": [{"what": string, "page": number, "quote": string}], "unclear": [string]}'
)
_KINDS = {"FINGERPRINT", "FOOTPRINT", "DNA", "CCTV_SIGHTING", "WITNESS_STATEMENT", "DEVICE_RECORD", "DOCUMENT", "OTHER"}
_STATUSES = {"MATCHED", "UNMATCHED", "UNIDENTIFIED", "UNKNOWN"}

CLASS_GUIDE = {
    "CHAT": "a chat/message export. Note who said what and when, any promises, admissions, amounts, places and times.",
    "BANK_STATEMENT": "a bank statement. Note account holders, dates, amounts, counterparties and unusual transactions.",
    "FIR_POLICE": "a police record. Note the complainant, accused, officers, dates, places and what is alleged.",
    "FORENSIC_REPORT": "a forensic report. Note every exhibit/specimen, what was found where, and for each whether it was MATCHED to a named person, UNMATCHED (compared, no match) or UNIDENTIFIED (not yet compared). Never leave an unmatched item out.",
    "MEDICAL": "a medical record. Note the person, dates, findings, cause/manner stated and who signed.",
    "CCTV_LOG": "a CCTV/log record. Note each time-stamped sighting, who is seen, where, and whether the person is identified.",
    "COURT_ORDER": "a court record. Note the court, parties, dates, directions and next dates.",
    "LETTER": "a letter. Note sender, recipient, dates and what is asked or admitted.",
    "OTHER": "a document of unknown type. Note the people, dates, amounts, places and events it states.",
    "MEDIA": "a media file described by the user.",
}


async def _matter_brief(matter: dict, corpus: list[dict]) -> str:
    facts = await db.facts.find({"matter_id": matter["id"]}).to_list(100)
    ents = await db.entities.find({"matter_id": matter["id"]}).to_list(100)
    parts = [
        f"MATTER: {matter['title']}\nParties: {matter.get('parties', '') or '(not recorded)'}\n{matter.get('description', '')}",
        "ALL DOCUMENTS IN THIS MATTER (you are analysing only one of them, but know the others exist):\n" + index_text(corpus),
    ]
    if ents:
        parts.append("PEOPLE ALREADY IDENTIFIED IN THE MATTER:\n" + "\n".join(f"- {e['name']} ({e.get('role', 'not stated')})" for e in ents))
    if facts:
        parts.append("FACTS RECORDED BY THE LAWYER:\n" + "\n".join(f"- [{f['status']}] {f['value']}" for f in facts))
    return "\n\n".join(parts)


def _checked(quote: str, page, pages: list[str]) -> tuple[int | None, bool]:
    """(page where the quote really is, whether it was found exactly). Falls back to the model's page."""
    found = find_quote(quote or "", pages)
    return (found, True) if found else ((page if isinstance(page, int) else None), False)


@router.post(
    "/documents/{document_id}/analyze",
    response_model=DocumentAnalysis,
    dependencies=[Depends(AI_LIMIT)],
)
async def analyze_document(document_id: str, user: dict = Depends(require_intelligence)):
    doc = await db.documents.find_one({"id": document_id, "organization_id": user["organization_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.get("text_available") and not any((p or "").strip() for p in doc.get("pages", [])):
        raise HTTPException(
            status_code=409,
            detail="This file has no readable text to analyse. Add a description of it in the Documents list, "
            "or record what it shows as facts / evidence items.",
        )
    tier = await gate_ai(user, "analyze-contract" if doc.get("doc_class") == "CONTRACT" else "analyze-evidence")
    matter = await db.matters.find_one({"id": doc["matter_id"], "organization_id": user["organization_id"]})
    all_docs = (
        await db.documents.find({"matter_id": doc["matter_id"]}).sort([("created_at", 1), ("_id", 1)]).to_list(500)
    )
    corpus = build_corpus(all_docs)
    mine = next((d for d in corpus if d["id"] == document_id), None) or build_corpus([doc])[0]  # a matter with more than 500 documents must not make this one fail
    body_text, cov = select_context("", [mine], budget=context_budget(user))
    pages: list[str] = doc.get("pages", [])
    cls = doc.get("doc_class", "OTHER")
    brief = fence(await _matter_brief(matter, corpus), "MATTER RECORDS")
    coverage_note = "" if cov["complete"] else "Only part of this document fit in the analysis; " + cov["summary"]

    if cls == "CONTRACT":
        prompt = (
            f"{brief}\n\nDOCUMENT TO ANALYSE ([{mine['label']}] a contract):\n{fence(body_text, mine['label'] + ' ' + doc['filename'])}\n\n"
            "Summarise this contract for an Indian lawyer and flag risky or one-sided clauses (indemnity, liability, "
            "termination, payment, confidentiality, IP, dispute resolution, governing law). Only flag clauses that "
            "actually appear above. For each flag give the page and an EXACT quote copied from the text. "
            "Describe issues neutrally; never judge anyone's honesty."
        )
        schema, purpose = CONTRACT_SCHEMA, "analyze-contract"
    else:
        prompt = (
            f"{brief}\n\nDOCUMENT TO ANALYSE ([{mine['label']}], "
            f"{CLASS_GUIDE.get(cls, CLASS_GUIDE['OTHER'])}):\n{fence(body_text, mine['label'] + ' ' + doc['filename'])}\n\n"
            "This is evidence, NOT a contract: do not look for contract clauses. Produce: a short factual summary; "
            "key facts; every person named and the role the document states (write 'not stated' if it does not say - "
            "never guess who someone is); every evidence item (fingerprints, sightings, records...) including ones "
            "that are UNMATCHED or UNIDENTIFIED; and anomalies - places where this document differs from another "
            "document or fact above, or contradicts itself, described neutrally (say 'differs from', never that "
            "anyone lied). EVERY item needs the page and an EXACT quote copied word-for-word from this document."
        )
        schema, purpose = EVIDENCE_SCHEMA, "analyze-evidence"

    try:
        data = await ask_json(f"doc-{document_id}", prompt, schema, purpose=purpose, tier=tier)
    except Exception as exc:  # noqa: BLE001
        log_ai_failure("document analysis", exc)
        await audit(user, "DOCUMENT_ANALYZE", result="FAILED", matter_id=doc["matter_id"])
        raise ai_failure(exc) from exc

    adjusted = False

    def clean(text: object, limit: int) -> str:
        nonlocal adjusted
        out, changed = neutralize(str(text or "")[:limit])
        adjusted = adjusted or changed
        return out

    summary = clean(data.get("summary"), 2000)
    flags, facts, people, anomalies, found_items = [], [], [], [], 0
    if cls == "CONTRACT":
        for f in data.get("flags", []) or []:
            if not isinstance(f, dict) or not f.get("clause"):
                continue
            risk = str(f.get("risk", "MEDIUM")).upper()
            q = str(f.get("quote", ""))[:600]
            page, ok = _checked(q, f.get("page"), pages) if q else (f.get("page") if isinstance(f.get("page"), int) else None, None)
            flags.append(
                ClauseFlag(
                    clause=clean(f["clause"], 300),
                    risk=risk if risk in ("HIGH", "MEDIUM", "LOW") else "MEDIUM",
                    why=clean(f.get("why", ""), 600),
                    page=page,
                    quote=q,
                    quote_verified=ok,
                )
            )
    else:
        for f in data.get("key_facts", []) or []:
            if isinstance(f, dict) and f.get("fact"):
                q = str(f.get("quote", ""))[:600]
                page, ok = _checked(q, f.get("page"), pages)
                facts.append(KeyFact(fact=clean(f["fact"], 400), page=page, quote=q, quote_verified=ok))
        for p in data.get("people", []) or []:
            if isinstance(p, dict) and p.get("name"):
                q = str(p.get("quote", ""))[:600]
                page, ok = _checked(q, p.get("page"), pages)
                people.append(PersonRef(name=str(p["name"])[:120], role=clean(p.get("role") or "not stated", 120), page=page, quote=q, quote_verified=ok))
        for a in data.get("anomalies", []) or []:
            if isinstance(a, dict) and a.get("what"):
                q = str(a.get("quote", ""))[:600]
                page, ok = _checked(q, a.get("page"), pages)
                anomalies.append(Anomaly(what=clean(a["what"], 500), page=page, quote=q, quote_verified=ok))
        # Evidence items are saved to the matter's evidence list ONLY when their quote is really in the document.
        await db.evidence_items.delete_many({"document_id": document_id, "source": "AI_EXTRACTED"})
        seen = set()
        for it in data.get("evidence_items", []) or []:
            if not isinstance(it, dict) or not it.get("label"):
                continue
            q = str(it.get("quote", ""))[:600]
            page, ok = _checked(q, it.get("page"), pages)
            key = str(it["label"]).strip().lower()
            if not ok or key in seen:
                continue
            seen.add(key)
            kind, status = str(it.get("kind", "OTHER")).upper(), str(it.get("status", "UNKNOWN")).upper()
            await db.evidence_items.insert_one(
                {
                    "id": str(uuid.uuid4()),
                    "matter_id": doc["matter_id"],
                    "organization_id": user["organization_id"],
                    "kind": kind if kind in _KINDS else "OTHER",
                    "label": str(it["label"])[:200],
                    "status": status if status in _STATUSES else "UNKNOWN",
                    "identified_as": (str(it["identified_as"])[:200] if it.get("identified_as") else None),
                    "location": (str(it["location"])[:200] if it.get("location") else None),
                    "document_id": document_id,
                    "page": page,
                    "quote": q,
                    "quote_verified": True,
                    "source": "AI_EXTRACTED",
                    "created_at": now(),
                }
            )
            found_items += 1

    result = DocumentAnalysis(
        document_id=document_id,
        doc_class=cls,
        summary=summary or "No summary could be produced from this document.",
        flags=flags,
        key_facts=facts,
        people=people,
        anomalies=anomalies,
        evidence_items_found=found_items,
        unclear=[str(x)[:300] for x in (data.get("unclear") or [])][:10],
        coverage_note=coverage_note,
        neutral_adjusted=adjusted,
    )
    await db.documents.update_one({"id": document_id}, {"$set": {"analysis": result.model_dump()}})
    await audit(user, "DOCUMENT_ANALYZE", matter_id=doc["matter_id"], detail=doc["filename"])
    return result
