"""List of dates with page references: reads every date written in a draft or bundle and lists it with the sentence it sits in and where it is in the file.
Off by default (DATE_LIST_ENABLED=false). No AI, no outside service, no cost. Only the list is stored; an uploaded file is read in memory and dropped."""

import asyncio
import os
import uuid
from datetime import datetime, timezone

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from lib.auth import audit, current_user
from lib.datelist import export, report as rep
from lib.dates import today_iso
from lib.db import db
from lib import retention
from lib.extract import extract_pages
from lib.ratelimit import UPLOAD_LIMIT, user_limit
from lib.uploads import read_limited, safe_filename, validate_content

router = APIRouter(tags=["datelist"])

TEXT_EXT = (".pdf", ".docx", ".txt", ".md")
TEXT_MAX = 15 * 1024 * 1024


def _on(user: dict = Depends(current_user)) -> dict:
    if not rep.enabled():
        raise HTTPException(status_code=404, detail="The list of dates is not switched on.")
    return user


class DateListIn(BaseModel):
    title: str = Field(default="Untitled list", min_length=1, max_length=200)
    text: str | None = Field(default=None, max_length=300_000)
    document_id: str | None = Field(default=None, max_length=64)


def _public(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in ("_id", "organization_id")}


async def _mine(list_id: str, user: dict) -> dict:
    doc = await db.date_lists.find_one({"id": list_id, "organization_id": user["organization_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="List not found")
    return doc


async def _save(user: dict, pages: list[str], title: str, source_file: str | None, kind: str, document_id: str | None = None) -> dict:
    try:
        built = rep.build(pages, kind, today_iso())
    except rep.TooManyDates as e:
        raise HTTPException(status_code=422, detail=f"This document has {e.n} dates; one list holds at most {rep.MAX_DATES}. Split the document and list it in parts.") from e
    doc = {"id": str(uuid.uuid4()), "organization_id": user["organization_id"], "created_by": user["id"], "title": title.strip() or "Untitled list",
           "source_file": source_file, "document_id": document_id, "created_at": datetime.now(timezone.utc).isoformat(), "expires_at": retention.report_expiry(), **built}
    await db.date_lists.insert_one(dict(doc))
    await audit(user, "DATE_LIST", detail=f"{doc['id']} {built['counts']['total']} dates")
    return _public(doc)


@router.post("/datelists", dependencies=[Depends(user_limit("datelist", 30, 3600))])
async def create_list(body: DateListIn, user: dict = Depends(_on)):
    if bool(body.text) == bool(body.document_id):
        raise HTTPException(status_code=422, detail="Send either the text or the id of an uploaded document, not both and not neither.")
    if body.document_id:
        doc = await db.documents.find_one({"id": body.document_id, "organization_id": user["organization_id"]})
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        pages = [p or "" for p in doc.get("pages", [])]
        if not any(p.strip() for p in pages):
            raise HTTPException(status_code=409, detail="This file has no readable text to list dates from.")
        return await _save(user, pages, body.title, doc.get("filename"), rep.page_kind(doc.get("filename")), body.document_id)
    return await _save(user, [body.text or ""], body.title, None, "unknown")


@router.post("/datelists/file", dependencies=[Depends(user_limit("datelist", 30, 3600)), Depends(UPLOAD_LIMIT)])
async def create_list_from_file(file: UploadFile = File(...), title: str = Form(default=""), user: dict = Depends(_on)):
    """List the dates straight from a file (PDF, Word or text). The file is read in memory and dropped: only the list is stored."""
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
    name = title.strip()[:200] or os.path.splitext(filename)[0][:200] or "Untitled list"
    return await _save(user, [p or "" for p in pages], name, filename, rep.page_kind(filename))


@router.get("/datelists")
async def list_lists(user: dict = Depends(_on)):
    rows = await db.date_lists.find({"organization_id": user["organization_id"]}, {"items": 0}).sort("created_at", -1).to_list(100)
    return [_public(r) for r in rows]


@router.get("/datelists/{list_id}")
async def read_list(list_id: str, user: dict = Depends(_on)):
    return _public(await _mine(list_id, user))


@router.get("/datelists/{list_id}/export")
async def export_list(list_id: str, format: Literal["docx", "pdf"] = "docx", user: dict = Depends(_on)):
    doc = _public(await _mine(list_id, user))
    await audit(user, "DATE_LIST_EXPORT", detail=f"{list_id} {format}")
    if format == "pdf":
        return Response(export.to_pdf(doc), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="list-of-dates.pdf"'})
    return Response(export.to_docx(doc), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": 'attachment; filename="list-of-dates.docx"'})


@router.delete("/datelists/{list_id}")
async def delete_list(list_id: str, user: dict = Depends(_on)):
    await _mine(list_id, user)
    await db.date_lists.delete_one({"id": list_id, "organization_id": user["organization_id"]})
    await audit(user, "DATE_LIST_DELETE", detail=list_id)
    return {"deleted": True}
