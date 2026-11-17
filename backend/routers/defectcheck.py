"""Pre-filing defect check: reads a draft and points to drafting slips (blanks, numbering, annexure labels, paragraph references, doubled words) with the sentence and where each is.
Knows no court's rules. Off by default (DEFECT_CHECK_ENABLED=false). No AI, no outside service, no cost. Only the findings are stored; an uploaded file is read in memory and dropped."""

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from lib.auth import audit, current_user
from lib.db import db
from lib.defects import export, report as rep
from lib import retention
from lib.extract import extract_pages
from lib.ratelimit import UPLOAD_LIMIT, user_limit
from lib.uploads import read_limited, safe_filename, validate_content

router = APIRouter(tags=["defectcheck"])

TEXT_EXT = (".pdf", ".docx", ".txt", ".md")
TEXT_MAX = 15 * 1024 * 1024


def _on(user: dict = Depends(current_user)) -> dict:
    if not rep.enabled():
        raise HTTPException(status_code=404, detail="The pre-filing defect check is not switched on.")
    return user


class DefectCheckIn(BaseModel):
    title: str = Field(default="Untitled draft", min_length=1, max_length=200)
    text: str | None = Field(default=None, max_length=300_000)
    document_id: str | None = Field(default=None, max_length=64)


def _public(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in ("_id", "organization_id")}


async def _mine(check_id: str, user: dict) -> dict:
    doc = await db.defect_checks.find_one({"id": check_id, "organization_id": user["organization_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Check not found")
    return doc


async def _save(user: dict, pages: list[str], title: str, source_file: str | None, kind: str, document_id: str | None = None) -> dict:
    try:
        built = rep.build(pages, kind)
    except rep.TooManyFindings as e:
        raise HTTPException(status_code=422, detail=f"This draft has {e.n} places to look at; one check holds at most {rep.MAX_FINDINGS}. Split the draft and check it in parts.") from e
    doc = {"id": str(uuid.uuid4()), "organization_id": user["organization_id"], "created_by": user["id"], "title": title.strip() or "Untitled draft",
           "source_file": source_file, "document_id": document_id, "created_at": datetime.now(timezone.utc).isoformat(), "expires_at": retention.report_expiry(), **built}
    await db.defect_checks.insert_one(dict(doc))
    await audit(user, "DEFECT_CHECK", detail=f"{doc['id']} {built['counts']['total']} findings")
    return _public(doc)


@router.post("/defectchecks", dependencies=[Depends(user_limit("defectcheck", 30, 3600))])
async def create_check(body: DefectCheckIn, user: dict = Depends(_on)):
    if bool(body.text) == bool(body.document_id):
        raise HTTPException(status_code=422, detail="Send either the text or the id of an uploaded document, not both and not neither.")
    if body.document_id:
        doc = await db.documents.find_one({"id": body.document_id, "organization_id": user["organization_id"]})
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        pages = [p or "" for p in doc.get("pages", [])]
        if not any(p.strip() for p in pages):
            raise HTTPException(status_code=409, detail="This file has no readable text to check.")
        return await _save(user, pages, body.title, doc.get("filename"), rep.page_kind(doc.get("filename")), body.document_id)
    return await _save(user, [body.text or ""], body.title, None, "unknown")


@router.post("/defectchecks/file", dependencies=[Depends(user_limit("defectcheck", 30, 3600)), Depends(UPLOAD_LIMIT)])
async def create_check_from_file(file: UploadFile = File(...), title: str = Form(default=""), user: dict = Depends(_on)):
    """Check a draft straight from a file (PDF, Word or text). The file is read in memory and dropped: only the findings are stored."""
    filename = safe_filename(file.filename)
    if not filename.lower().endswith(TEXT_EXT):
        raise HTTPException(status_code=422, detail="Upload a PDF, Word or text file.")
    data = await read_limited(file, TEXT_MAX, f"File exceeds the {TEXT_MAX // (1024 * 1024)} MB limit")
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    validate_content(filename, data, TEXT_EXT, "Upload a PDF, Word or text file")
    pages, err = await asyncio.to_thread(extract_pages, filename, data)
    del data
    if not any((p or "").strip() for p in pages):
        raise HTTPException(status_code=409, detail=err or "This file has no readable text. A scanned PDF must be added to a matter first so it can be read.")
    name = title.strip()[:200] or os.path.splitext(filename)[0][:200] or "Untitled draft"
    return await _save(user, [p or "" for p in pages], name, filename, rep.page_kind(filename))


@router.get("/defectchecks")
async def list_checks(user: dict = Depends(_on)):
    rows = await db.defect_checks.find({"organization_id": user["organization_id"]}, {"items": 0}).sort("created_at", -1).to_list(100)
    return [_public(r) for r in rows]


@router.get("/defectchecks/{check_id}")
async def read_check(check_id: str, user: dict = Depends(_on)):
    return _public(await _mine(check_id, user))


@router.get("/defectchecks/{check_id}/export")
async def export_check(check_id: str, format: Literal["docx", "pdf"] = "docx", user: dict = Depends(_on)):
    doc = _public(await _mine(check_id, user))
    await audit(user, "DEFECT_CHECK_EXPORT", detail=f"{check_id} {format}")
    if format == "pdf":
        return Response(export.to_pdf(doc), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="defect-check.pdf"'})
    return Response(export.to_docx(doc), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": 'attachment; filename="defect-check.docx"'})


@router.delete("/defectchecks/{check_id}")
async def delete_check(check_id: str, user: dict = Depends(_on)):
    await _mine(check_id, user)
    await db.defect_checks.delete_one({"id": check_id, "organization_id": user["organization_id"]})
    await audit(user, "DEFECT_CHECK_DELETE", detail=check_id)
    return {"deleted": True}
