"""Authority Check: reads the cases and statutes a draft cites and reports what could and could not be checked. Off by default (AUTHORITY_CHECK_ENABLED=false).
No AI unless the person asks for the optional proposition check, which can only add a "may not support, please read" caution and never a tick. Cases are looked up in an
outside source (daily per-organisation limit), statutes in our reviewed library. Current status of a case is never checked."""

import asyncio
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from lib.auth import audit, current_user, now
from lib.db import db
from lib import retention
from lib.extract import extract_pages
from lib.ratelimit import UPLOAD_LIMIT, user_limit
from lib.ai import ask_json
from lib.plans import gate_ai, refund_ai
from lib.refcheck import export, propositions, report as rep, spend
from lib.refcheck.lookup import LookupCapExceeded
from lib.refcheck.scsource import SupremeCourtData
from lib.refcheck.sources import Candidate, SourceDown
from lib.uploads import read_limited, safe_filename, validate_content

router = APIRouter(tags=["authority"])
logger = logging.getLogger("vidhi.refcheck")


class NoCaseSource:
    """Stands in when the case dataset is not on this machine. Every lookup says so, so every case ends as 'could not check' and never as 'not found'."""

    name = "none"

    async def search(self, query: str) -> list[Candidate]:
        raise SourceDown("The Supreme Court judgments dataset is not set up on this server (SC_DATA_DIR), so cases cannot be checked.")

    async def fetch(self, doc_id: str) -> dict:
        raise SourceDown("The Supreme Court judgments dataset is not set up on this server (SC_DATA_DIR).")

    def url_for(self, doc_id: str) -> str:
        return ""


_SOURCE: dict = {}
_LOAD = threading.Lock()  # the index takes about 12 seconds to build; one load at a time, so a request that arrives during start-up waits for it instead of building a second copy


def case_source():
    """The local Supreme Court open dataset (free, offline), loaded once per server process from SC_DATA_DIR. Missing or unreadable data gives NoCaseSource, never an invented answer."""
    folder = os.environ.get("SC_DATA_DIR", "").strip()
    if not folder:
        return _SOURCE.setdefault("none", NoCaseSource())
    if folder not in _SOURCE:
        with _LOAD:
            if folder not in _SOURCE:
                try:
                    _SOURCE[folder] = SupremeCourtData(folder)
                except SourceDown:
                    return NoCaseSource()
    return _SOURCE[folder]


async def warm_case_source() -> bool:
    """Loads the dataset index at server start, in a thread, so the first person to check a draft does not wait for it and the server is not frozen while it loads.
    True when a dataset is loaded; False when there is none or it could not be read (every case then reads 'could not check')."""
    if not rep.enabled() or not os.environ.get("SC_DATA_DIR", "").strip():
        return False
    try:
        return not isinstance(await asyncio.to_thread(case_source), NoCaseSource)
    except Exception:  # noqa: BLE001 - a dataset problem must never stop the server
        logger.exception("the case dataset could not be loaded at start-up")
        return False
MAX_PROPOSITION_CHECKS = 15
TEXT_EXT = (".pdf", ".docx", ".txt", ".md")
TEXT_MAX = 15 * 1024 * 1024


def _on(user: dict = Depends(current_user)) -> dict:
    if not rep.enabled():
        raise HTTPException(status_code=404, detail="Authority Check is not switched on.")
    return user


class CheckIn(BaseModel):
    title: str = Field(default="Untitled draft", min_length=1, max_length=200)
    text: str | None = Field(default=None, max_length=300_000)
    document_id: str | None = Field(default=None, max_length=64)
    proposition_check: bool = False  # opt in: uses AI to look for points a case may not support (a caution only, never a confirmation)


class ReviewIn(BaseModel):
    action: Literal["fix", "accept_as_is", "reviewed"]
    note: str = Field(default="", max_length=500)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in ("_id", "organization_id")}


async def _mine(report_id: str, user: dict) -> dict:
    doc = await db.authority_reports.find_one({"id": report_id, "organization_id": user["organization_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Report not found")
    return doc


@router.post("/authority/checks", dependencies=[Depends(user_limit("authority", 30, 3600))])
async def create_check(body: CheckIn, user: dict = Depends(_on)):
    if bool(body.text) == bool(body.document_id):
        raise HTTPException(status_code=422, detail="Send either the draft text or the id of an uploaded document, not both and not neither.")
    if body.document_id:
        doc = await db.documents.find_one({"id": body.document_id, "organization_id": user["organization_id"]})
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        pages = [p or "" for p in doc.get("pages", [])]
        if not any(p.strip() for p in pages):
            raise HTTPException(status_code=409, detail="This file has no readable text to check.")
    else:
        pages = [body.text or ""]
    return await _run_check(user, pages, body.title, body.document_id, body.proposition_check)


@router.post("/authority/checks/file", dependencies=[Depends(user_limit("authority", 30, 3600)), Depends(UPLOAD_LIMIT)])
async def create_check_from_file(file: UploadFile = File(...), title: str = Form(default=""), proposition_check: bool = Form(default=False), user: dict = Depends(_on)):
    """Check a draft straight from a file (PDF, Word or text). The file is read in memory and dropped: it is not stored anywhere, only the report is."""
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
        raise HTTPException(status_code=409, detail=err or "This file has no readable text to check. A scanned PDF must be added to a matter first so it can be read.")
    name = title.strip()[:200] or os.path.splitext(filename)[0][:200] or "Untitled draft"
    return await _run_check(user, [p or "" for p in pages], name, None, proposition_check)


async def _run_check(user: dict, pages: list[str], title: str, document_id: str | None, proposition_check: bool) -> dict:
    async def reserve(n: int) -> None:
        await spend.reserve(db.authority_spend, user["organization_id"], n)

    proposition = None
    if proposition_check:
        tier = await gate_ai(user, "analysis")
        used = 0

        async def proposition(sentence: str, blocks: list[str]) -> dict:
            nonlocal used
            if used >= MAX_PROPOSITION_CHECKS:
                return propositions.short(f"The limit of {MAX_PROPOSITION_CHECKS} AI checks in one report was reached.")
            used += 1
            return await propositions.check(sentence, blocks, ask=ask_json, session_id=f"authority-{user['id']}", tier=tier)

    try:
        built = await rep.build(pages, await asyncio.to_thread(case_source), reserve=reserve, proposition=proposition)
    except rep.TooManyReferences as e:
        await refund_ai(user)
        raise HTTPException(status_code=422, detail=f"This draft cites {e.n} references; one report holds at most {rep.MAX_REFERENCES}. Split the draft and check it in parts.") from e
    except LookupCapExceeded as e:  # the cap is handled inside the case check; this is only a backstop
        await refund_ai(user)
        raise HTTPException(status_code=429, detail="The daily lookup limit for your organisation is used up.") from e
    if proposition_check and not any((i.get("proposition") or {}).get("state") in ("no_flag", "may_not_support") for i in built["items"]):
        await refund_ai(user)  # the AI gave no answer for any reference (none qualified, or it was unavailable): the daily request is given back
    doc = {"id": str(uuid.uuid4()), "proposition_check": proposition_check, "organization_id": user["organization_id"], "created_by": user["id"], "title": title.strip() or "Untitled draft", "document_id": document_id, "created_at": _now(), "expires_at": retention.report_expiry(), **built}
    await db.authority_reports.insert_one(dict(doc))
    await audit(user, "AUTHORITY_CHECK", detail=f"{doc['id']} {built['counts']['total']} references")
    return _public(doc)


@router.get("/authority/checks")
async def list_checks(user: dict = Depends(_on)):
    rows = await db.authority_reports.find({"organization_id": user["organization_id"]}, {"items": 0}).sort("created_at", -1).to_list(100)
    return [_public(r) for r in rows]


@router.get("/authority/checks/{report_id}")
async def read_check(report_id: str, user: dict = Depends(_on)):
    return _public(await _mine(report_id, user))


@router.delete("/authority/checks/{report_id}")
async def delete_check(report_id: str, user: dict = Depends(_on)):
    await _mine(report_id, user)
    await db.authority_reports.delete_one({"id": report_id, "organization_id": user["organization_id"]})
    await audit(user, "AUTHORITY_DELETE", detail=report_id)
    return {"deleted": True}


@router.post("/authority/checks/{report_id}/items/{n}/review")
async def review_item(report_id: str, n: int, body: ReviewIn, user: dict = Depends(_on)):
    doc = await _mine(report_id, user)
    if body.action == "fix" and not body.note.strip():
        raise HTTPException(status_code=422, detail="Say what the corrected reference is (or what must be fixed).")
    if not any(i["n"] == n for i in doc["items"]):
        raise HTTPException(status_code=404, detail="Reference not found in this report")
    review = {"state": body.action, "note": body.note.strip(), "by": user.get("full_name") or user["email"], "at": _now()}
    await db.authority_reports.update_one({"id": report_id, "organization_id": user["organization_id"], "items.n": n}, {"$set": {"items.$.review": review}})
    fresh = await _mine(report_id, user)
    await db.authority_reports.update_one({"id": report_id}, {"$set": {"counts": rep.counts(fresh["items"])}})
    await audit(user, "AUTHORITY_REVIEW", detail=f"{report_id} #{n} {body.action}")
    return _public(await _mine(report_id, user))


class FlagIn(BaseModel):
    problem: Literal["says_not_found_but_it_exists", "says_found_but_it_is_wrong", "unclear_or_confusing", "other"]
    note: str = Field(default="", max_length=500)


@router.post("/authority/checks/{report_id}/items/{n}/flag", dependencies=[Depends(user_limit("pilot-feedback", 200, 86400))])
async def flag_item(report_id: str, n: int, body: FlagIn, user: dict = Depends(_on)):
    """The lawyer says this result is wrong or unclear. It is kept on the report item (so they see their own mark) and, as the reference text and the tool's label only, in the pilot
    feedback the operator reads. Sending again replaces the earlier mark. The sentence around the reference is never copied."""
    doc = await _mine(report_id, user)
    item = next((i for i in doc["items"] if i["n"] == n), None)
    if not item:
        raise HTTPException(status_code=404, detail="Reference not found in this report")
    flag = {"problem": body.problem, "note": body.note.strip(), "at": _now()}
    await db.authority_reports.update_one({"id": report_id, "organization_id": user["organization_id"], "items.n": n}, {"$set": {"items.$.flagged": flag}})
    await db.pilot_feedback.update_one(
        {"kind": "wrong_result", "report_id": report_id, "n": n, "user_id": user["id"]},
        {"$set": {"organization_id": user["organization_id"], "user_email": user["email"], "ref": str(item.get("raw") or "")[:200], "ref_kind": item.get("kind"), "tool_label": item.get("label"),
                  "problem": body.problem, "note": body.note.strip(), "updated_at": now()},
         "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now()}},
        upsert=True,
    )
    await audit(user, "AUTHORITY_FLAG", detail=f"{report_id} #{n} {body.problem}")
    return _public(await _mine(report_id, user))


@router.get("/authority/checks/{report_id}/export")
async def export_check(report_id: str, format: Literal["docx", "pdf"] = "docx", user: dict = Depends(_on)):
    doc = _public(await _mine(report_id, user))
    await audit(user, "AUTHORITY_EXPORT", detail=f"{report_id} {format}")
    if format == "pdf":
        return Response(export.to_pdf(doc), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="authority-check.pdf"'})
    return Response(export.to_docx(doc), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": 'attachment; filename="authority-check.docx"'})
