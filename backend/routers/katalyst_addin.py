"""The Katalyst checks for a word processor's side panel (Word, Google Docs), and the marked-up Word file.

  POST /v1/katalyst/analyze-text   paragraphs (or raw text) in, findings with exact character positions out (lib/katalyst_addin.py)
  POST /v1/katalyst/redline-docx   a .docx in, the same file with native Word review marks (tracked changes and comments) plus a one-page audit summary out (lib/docx_redline.py)

Plain code, no AI. Signed-in session only (the Word panel is served from the app's own address, so the session cookie applies). Nothing is stored: the text is read, answered and dropped.
Each check follows its own switch (AUTHORITY_CHECK_ENABLED, OLD_CODE_CHECK_ENABLED, DEFECT_CHECK_ENABLED, DATE_LIST_ENABLED); a check that is off is reported as off, never as clean."""

import asyncio
import base64
import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from lib import addin_keys, docx_redline, katalyst_audit
from lib.auth import audit, current_user
from lib.db import db
from lib.katalyst_addin import MAX_PARAGRAPH_CHARS, MAX_PARAGRAPHS, MAX_TOTAL_CHARS, Para, analyze, split_text
from lib.ratelimit import UPLOAD_LIMIT, user_limit
from lib.refcheck import spend
from lib.uploads import read_limited, safe_filename, validate_content
from routers.authority import case_source

router = APIRouter(prefix="/v1/katalyst", tags=["katalyst-addin"])
DOCX_MAX = 15 * 1024 * 1024


class ParagraphIn(BaseModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_\-]+$")
    text: str = Field(max_length=MAX_PARAGRAPH_CHARS)


class AnalyzeIn(BaseModel):
    paragraphs: list[ParagraphIn] | None = Field(default=None, max_length=MAX_PARAGRAPHS)
    text: str | None = Field(default=None, max_length=MAX_TOTAL_CHARS)


def _paras(body: AnalyzeIn) -> list[Para]:
    if bool(body.paragraphs) == bool(body.text):
        raise HTTPException(status_code=422, detail="Send either paragraphs (with ids) or raw text, not both and not neither.")
    paras = [Para(p.id, p.text) for p in body.paragraphs] if body.paragraphs else split_text(body.text or "")
    if len({p.id for p in paras}) != len(paras):
        raise HTTPException(status_code=422, detail="Paragraph ids must be different from each other.")
    if sum(len(p.text) for p in paras) > MAX_TOTAL_CHARS:
        raise HTTPException(status_code=413, detail=f"The text is longer than {MAX_TOTAL_CHARS:,} characters. Check it in parts.")
    if not any(p.text.strip() for p in paras):
        raise HTTPException(status_code=422, detail="There is no text to check.")
    return paras


class KeyIn(BaseModel):
    label: str = Field(default="Google Docs", max_length=60)


@router.post("/keys", dependencies=[Depends(user_limit("addin-keys", 20, 3600))])
async def make_key(body: KeyIn, user: dict = Depends(current_user)):
    """A key for the Google Docs add-on. The key itself is in this answer ONCE; only its hash is kept. It works for the two checks above and nothing else."""
    made = await addin_keys.create(user, body.label)
    await audit(user, "ADDIN_KEY_CREATED", detail=made["id"])
    return made


@router.get("/keys")
async def list_keys(user: dict = Depends(current_user)):
    rows = await db.addin_keys.find({"user_id": user["id"]}).sort("created_at", -1).to_list(50)
    return [addin_keys.public(r) for r in rows]


@router.delete("/keys/{key_id}")
async def remove_key(key_id: str, user: dict = Depends(current_user)):
    if not (await db.addin_keys.delete_one({"id": key_id, "user_id": user["id"]})).deleted_count:
        raise HTTPException(status_code=404, detail="Key not found")
    await audit(user, "ADDIN_KEY_REMOVED", detail=key_id)
    return {"ok": True}


def _reserve(user: dict):
    async def reserve(n: int) -> None:
        await spend.reserve(db.authority_spend, user["organization_id"], n)

    return reserve


@router.post("/analyze-text", dependencies=[Depends(user_limit("katalyst-addin", 120, 3600))])
async def analyze_text(body: AnalyzeIn, user: dict = Depends(current_user)):
    paras = _paras(body)
    result = await analyze(paras, await asyncio.to_thread(case_source), _reserve(user))
    await audit(user, "KATALYST_ADDIN_ANALYZE", detail=f"{len(paras)} paragraphs, {len(result['issues'])} findings")
    return result


@router.post("/redline-docx", dependencies=[Depends(user_limit("katalyst-addin", 120, 3600)), Depends(UPLOAD_LIMIT)])
async def redline_docx(file: UploadFile = File(...), apply_replacements: bool = Form(default=False), user: dict = Depends(current_user)):
    """The file with review marks. `apply_replacements` is off unless asked: then nothing is replaced, every finding is a comment. Returns JSON: the Word file and the PDF summary in base64, and the report."""
    name = safe_filename(file.filename)
    data = await read_limited(file, DOCX_MAX, f"File exceeds the {DOCX_MAX // (1024 * 1024)} MB limit")
    validate_content(name, data, (".docx",), "Upload a Word (.docx) file")
    import docx

    try:
        document = await asyncio.to_thread(docx.Document, io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="This Word file could not be opened.") from exc
    paras = docx_redline.paras_of(document)
    if len(paras) > MAX_PARAGRAPHS or sum(len(p.text) for p in paras) > MAX_TOTAL_CHARS:
        raise HTTPException(status_code=413, detail="This document is too long to check in one go.")
    if not any(p.text.strip() for p in paras):
        raise HTTPException(status_code=422, detail="This file has no text to check.")
    result = await analyze(paras, await asyncio.to_thread(case_source), _reserve(user))
    marked, done = await asyncio.to_thread(docx_redline.redline, data, result["issues"], apply_replacements)
    pdf = await asyncio.to_thread(katalyst_audit.to_pdf, result, done, name)
    await audit(user, "KATALYST_ADDIN_REDLINE", detail=f"{len(result['issues'])} findings, {done['comments']} comments, {done['tracked_replacements']} replacements")
    stem = name.rsplit(".", 1)[0]
    return {"filename": f"{stem} (checked).docx", "docx_base64": base64.b64encode(marked).decode(), "audit_pdf_filename": f"{stem} (audit summary).pdf",
            "audit_pdf_base64": base64.b64encode(pdf).decode(), "report": {**result, "marks": done}}
