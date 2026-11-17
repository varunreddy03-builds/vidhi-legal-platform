"""Legal data: reading (any signed-in user with read access) and the operator's loading and review routes (admin only, mounted under /api/admin/legal).

Reading never claims verification: every result says whether the text has been compared with the official source by a named reviewer. See lib/legal_store.py."""

import asyncio
import json
import re
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lib import verified_store as vstore
from lib import code_mappings, external_sources, filestore, jobs, legal_compare, legal_review_pack, legal_search, legal_store, library, territories
from lib.auth import audit, current_user
from lib.db import db
from lib.extract import extract_pages
from lib.platform import require_platform_admin
from lib.ratelimit import user_limit
from lib.uploads import read_limited

router = APIRouter(tags=["legal"])
# Its routes are added to the admin router (routers/admin.py). Routes added that way do NOT inherit the admin router's guard, so this router carries the same guard itself.
admin_router = APIRouter(prefix="/admin/legal", tags=["admin", "legal"], dependencies=[Depends(require_platform_admin)])


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _day(value: str | None, name: str) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must be a date like 2026-11-05.") from exc


# ------------------------------------------------------------------ reading

@router.get("/legal/search", dependencies=[Depends(user_limit("legal-search", 300, 3600))])
async def search(q: str = Query("", max_length=300), on: str | None = None, territory: str | None = Query(None, max_length=8), user: dict = Depends(current_user)):
    if territory and not territories.valid_code(territory):
        raise HTTPException(status_code=422, detail="territory must be IN or a code like IN-TG (see /api/library/territories).")
    return await legal_search.search(q, on_date=_day(on, "on"), territory=territory)


@router.get("/legal/provisions/{provision_id}")
async def provision(provision_id: str, user: dict = Depends(current_user)):
    v = await legal_search.provision_view(provision_id)
    if not v:
        raise HTTPException(status_code=404, detail="Provision not found")
    return v


@router.get("/legal/mappings", dependencies=[Depends(user_limit("legal-mappings", 300, 3600))])
async def mappings(number: str = Query(min_length=1, max_length=12), instrument: str | None = Query(None, max_length=80), offence_date: str | None = None, user: dict = Depends(current_user)):
    return await code_mappings.lookup(number.strip().upper(), instrument, _day(offence_date, "offence_date"))


@router.get("/legal/resources")
async def resources(user: dict = Depends(current_user)):
    """Public help services people can be pointed to (free legal aid, tele-law, consumer helpline). Names and purpose only; nothing is fetched from them."""
    return {"resources": external_sources.referrals(), "note": "VIDHI only points you to these services. Whether you qualify is for each service to decide."}


@router.get("/legal/coverage")
async def coverage(user: dict = Depends(current_user)):
    return await legal_store.coverage()


# ------------------------------------------------------------------ the operator's routes (admin router: platform admin required, see routers/admin.py)

class SourceIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    publisher: str = Field(min_length=2, max_length=200)
    jurisdiction: str = "IN"
    document_types: list[str] = Field(default_factory=list, max_length=20)
    access_method: str
    licence_note: str = Field(default="", max_length=1000)
    terms_checked_on: str | None = None
    robots_or_captcha_note: str = Field(default="", max_length=1000)
    update_frequency: str = Field(default="", max_length=200)
    known_limits: str = Field(default="", max_length=1000)
    permission_required: bool = False  # the source's terms need written permission before its text is stored or republished
    permission_reference: str = Field(default="", max_length=1000)  # who gave the permission, when, and where it is kept


class PermissionIn(BaseModel):
    reference: str = Field(min_length=10, max_length=1000)


class CompareIn(BaseModel):
    version_id: str
    second_document_id: str


class RejectIn(BaseModel):
    reviewed_by: str = Field(min_length=5, max_length=120)
    on: str
    reason: str = Field(min_length=10, max_length=1000)


class WithdrawIn(BaseModel):
    reviewed_by: str = Field(min_length=5, max_length=120)
    on: str
    reason: str = Field(min_length=10, max_length=1000)


class SourceUrlIn(BaseModel):
    url: str = Field(min_length=10, max_length=500)


class DocumentIn(BaseModel):
    source_id: str
    title: str = Field(min_length=2, max_length=300)
    issuing_authority: str = Field(default="", max_length=200)
    source_page_url: str = Field(default="", max_length=1000)
    file_url: str = Field(default="", max_length=1000)
    published_on: str | None = None
    licence_note: str = Field(default="", max_length=1000)
    document_kind: str | None = Field(default=None, max_length=40)
    pages: list[str] = Field(min_length=1, max_length=3000)


class InstrumentIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    short_names: list[str] = Field(default_factory=list, max_length=10)
    kind: str = "act"
    year: int | None = Field(default=None, ge=1600, le=2100)
    jurisdiction: str = "IN"


class IngestIn(BaseModel):
    document_id: str
    instrument: InstrumentIn
    version_label: str
    effective_from: str | None = None
    effective_to: str | None = None
    evidence: str = Field(default="", max_length=1000)


class ReviewIn(BaseModel):
    reviewed_by: str = Field(min_length=5, max_length=120)
    on: str
    acknowledge_machine_read: bool = False  # needed when the text came from a scan read by a machine
    acknowledge_second_source_difference: bool = False  # needed when a second official source words the section differently


class CommencementIn(BaseModel):
    date: str | None = None
    evidence: str = Field(default="", max_length=1000)


class NoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=1000)
    provision_id: str | None = None


class MappingIn(BaseModel):
    relationship: str
    equivalence: str | None = Field(default=None, max_length=20)  # exact | partial | related | uncertain | none; "uncertain" (or "none" for absent) if left out: closeness is never assumed
    legacy_provision_ids: list[str] = Field(min_length=1, max_length=20)
    new_provision_ids: list[str] = Field(default_factory=list, max_length=20)
    differences_in_effect: str = Field(min_length=10, max_length=4000)
    commencement: CommencementIn = Field(default_factory=CommencementIn)
    transitional_and_saving: list[NoteIn] = Field(default_factory=list, max_length=20)
    authorities: list[str] = Field(default_factory=list, max_length=20)


@admin_router.get("/external-sources")
async def external_source_registry():
    """Every outside source that was asked about, with its true status. Never shows a token."""
    return {"sources": external_sources.registry(), "policy": "Nothing fetched from outside is ever verified. Depositions, witness statements, transcripts, sealed or protected records and raw case files are never loaded."}


@admin_router.get("/sources")
async def sources():
    return [legal_store.clean(s) for s in await vstore.find_many("legal_sources", {}, sort=[("created_at", 1)])]


@admin_router.post("/sources", status_code=201)
async def add_source(body: SourceIn, admin: dict = Depends(require_platform_admin)):
    for kind in body.document_types:
        ok, why = external_sources.ingest_allowed(kind)
        if not ok:
            raise HTTPException(status_code=422, detail=why)
    try:
        s = await legal_store.register_source(body.model_dump())
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_SOURCE_ADDED", detail=s["name"][:120])
    return s


@admin_router.post("/documents", status_code=201)
async def add_document(body: DocumentIn, admin: dict = Depends(require_platform_admin)):
    if body.document_kind is not None:
        ok, why = external_sources.ingest_allowed(body.document_kind)
        if not ok:
            raise HTTPException(status_code=422, detail=why)
    try:
        d = await legal_store.register_document(body.source_id, body.model_dump(), text_pages=body.pages)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_DOCUMENT_ADDED", detail=f"{d['title'][:100]} {d['sha256'][:12]}")
    return d


@admin_router.post("/documents/upload", status_code=201)
async def upload_document(source_id: str = Form(), title: str = Form(min_length=2, max_length=300), issuing_authority: str = Form(""), source_page_url: str = Form(""), file_url: str = Form(""),
                          published_on: str = Form(""), licence_note: str = Form(""), file: UploadFile = File(...), admin: dict = Depends(require_platform_admin)):
    data = await read_limited(file, 40 * 1024 * 1024, "File exceeds the 40 MB limit")
    pages, err = await asyncio.to_thread(extract_pages, file.filename or "document", data, None)
    meta_in = {"title": title, "issuing_authority": issuing_authority, "source_page_url": source_page_url, "file_url": file_url, "published_on": published_on or None, "licence_note": licence_note,
               "format": (file.filename or "").rsplit(".", 1)[-1].lower()}
    if not any(p.strip() for p in pages):
        if not (file.filename or "").lower().endswith(".pdf") or not (err or "").startswith("No extractable text"):
            raise HTTPException(status_code=422, detail=err or "No text could be read from that file.")
        # a scanned PDF: reading it takes a while, so it goes to the job queue (resumable, retried a limited number of times)
        if not await vstore.find_one("legal_sources", {"id": source_id}):
            raise HTTPException(status_code=422, detail="Unknown source.")
        fid = await filestore.put(file.filename or "document", data, {"legal_source": source_id})
        job_id = await jobs.enqueue("ocr-legal-document", {"source_id": source_id, "meta": meta_in, "stored_file_id": str(fid), "filename": file.filename})
        await audit(admin, "LEGAL_SCAN_QUEUED", detail=f"{title[:100]}")
        return JSONResponse(status_code=202, content={"queued": True, "job_id": job_id, "message": "This is a scanned file. It is being read in the background; check the jobs list for the result."})
    fid = await filestore.put(file.filename or "document", data, {"legal_source": source_id})
    try:
        d = await legal_store.register_document(source_id, meta_in, text_pages=pages, file_bytes=data, stored_file_id=fid)
    except ValueError as exc:
        await filestore.delete(fid)
        raise _bad(exc) from exc
    if d["duplicate"]:
        await filestore.delete(fid)  # the same file was already registered; keep only one stored copy
    await audit(admin, "LEGAL_DOCUMENT_ADDED", detail=f"{title[:100]} {d['sha256'][:12]}")
    return d


@admin_router.get("/jobs")
async def list_jobs():
    return [jobs.view(j) async for j in db.jobs.find({}).sort("created_at", -1).limit(50)]


@admin_router.post("/jobs/run")
async def run_jobs(limit: int = Query(5, ge=1, le=20), admin: dict = Depends(require_platform_admin)):
    """Run due background jobs now (the scheduled trigger does the same every few minutes)."""
    from lib.job_handlers import HANDLERS

    out = await jobs.run_batch(HANDLERS, limit)
    await audit(admin, "LEGAL_JOBS_RUN", detail=f"limit {limit}")
    return out


@admin_router.post("/ingest", status_code=201)
async def ingest(body: IngestIn, admin: dict = Depends(require_platform_admin)):
    try:
        out = await legal_store.ingest(body.document_id, body.instrument.model_dump(), body.version_label, effective_from=body.effective_from, effective_to=body.effective_to, evidence=body.evidence)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_INGESTED", detail=f"{body.instrument.title[:100]}: {out['provisions']} provisions")
    return out


class ImportDraftsIn(BaseModel):
    act_id: str = Field(min_length=1, max_length=120)
    source_id: str
    instrument: InstrumentIn
    version_label: str = "consolidated"
    effective_from: str | None = None
    effective_to: str | None = None
    evidence: str = Field(default="", max_length=1000)


@admin_router.post("/import-drafts", status_code=201)
async def import_drafts(body: ImportDraftsIn, admin: dict = Depends(require_platform_admin)):
    """Turn an Act's loaded draft sections into structured, unreviewed provisions. Refused while the source needs a permission that is not recorded."""
    try:
        out = await legal_store.ingest_drafts(body.act_id, body.source_id, body.instrument.model_dump(), body.version_label, effective_from=body.effective_from, effective_to=body.effective_to, evidence=body.evidence)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_INGESTED", detail=f"drafts of {body.act_id[:60]}: {out['provisions']} provisions")
    return out


@admin_router.post("/provisions/{provision_id}/review")
async def review_provision(provision_id: str, body: ReviewIn, admin: dict = Depends(require_platform_admin)):
    try:
        p = await legal_store.review_provision(provision_id, body.reviewed_by, body.on, body.acknowledge_machine_read, body.acknowledge_second_source_difference)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_PROVISION_REVIEWED", detail=f"{p['number']} by {body.reviewed_by[:60]}")
    return {"id": p["id"], "review_status": p["review_status"], "reviewed_by": p["reviewed_by"], "reviewed_on": p["reviewed_on"]}


@admin_router.post("/provisions/{provision_id}/reject")
async def reject_provision(provision_id: str, body: RejectIn, admin: dict = Depends(require_platform_admin)):
    try:
        p = await legal_store.reject_provision(provision_id, body.reviewed_by, body.on, body.reason)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_PROVISION_REJECTED", detail=f"{p['number']} by {body.reviewed_by[:60]}")
    return {"id": p["id"], "review_status": p["review_status"], "reviewed_by": p["reviewed_by"], "reviewed_on": p["reviewed_on"], "rejected_reason": p.get("rejected_reason")}


@admin_router.post("/provisions/{provision_id}/approve")
async def approve_provision(provision_id: str, body: ReviewIn, admin: dict = Depends(require_platform_admin)):
    """A named reviewer compared this section with the official source: it becomes reviewed AND enters the verified library (the only way a section becomes VERIFIED)."""
    try:
        p, entry = await legal_store.approve_to_library(provision_id, body.reviewed_by, body.on, body.acknowledge_machine_read, body.acknowledge_second_source_difference)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_LIBRARY_APPROVED", detail=f"{entry['id'][:90]} (section {p['number']}) by {body.reviewed_by[:60]} on {entry['verified_on']}; text {entry['text_sha256'][:12]}")
    return {"id": p["id"], "review_status": p["review_status"], "reviewed_by": p["reviewed_by"], "reviewed_on": p["reviewed_on"], "library_entry_id": entry["id"], "text_sha256": entry["text_sha256"], "verified": True}


@admin_router.post("/provisions/{provision_id}/withdraw")
async def withdraw_provision(provision_id: str, body: WithdrawIn, admin: dict = Depends(require_platform_admin)):
    try:
        out = await legal_store.withdraw_from_library(provision_id, body.reviewed_by, body.on, body.reason)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_LIBRARY_WITHDRAWN", detail=f"{out['id'][:90]} by {body.reviewed_by[:60]}: {body.reason[:120]}")
    return {**out, "verified": False}


@admin_router.get("/library-entries/{entry_id}/export")
async def export_library_entry(entry_id: str):
    """A verified entry as a library file, to commit under backend/data/legal_library/IN/ (so git history records it too)."""
    try:
        entry = await library.export_entry(entry_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    name = re.sub(r"[^a-z0-9._-]+", "-", entry["id"].lower())[:80]
    return Response(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{name}.json"'})


@admin_router.post("/documents/{document_id}/source-url")
async def document_source_url(document_id: str, body: SourceUrlIn, admin: dict = Depends(require_platform_admin)):
    try:
        out = await legal_store.set_document_url(document_id, body.url)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_DOCUMENT_URL", detail=f"{document_id[:40]} -> {out['source_page_url'][:120]}")
    return out


@admin_router.post("/sources/{source_id}/permission")
async def record_source_permission(source_id: str, body: PermissionIn, admin: dict = Depends(require_platform_admin)):
    try:
        s = await legal_store.record_permission(source_id, body.reference, admin["email"])
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_SOURCE_PERMISSION", detail=s["name"][:100])
    return s


@admin_router.post("/compare")
async def compare_with_second_source(body: CompareIn, admin: dict = Depends(require_platform_admin)):
    try:
        out = await legal_compare.compare_version(body.version_id, body.second_document_id, admin["email"])
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_SECOND_SOURCE_COMPARED", detail=f"{body.version_id[:8]} different={len(out['different'])}")
    return out


@admin_router.get("/integrity")
async def integrity():
    return await legal_store.integrity_report()


@admin_router.get("/versions")
async def list_versions():
    """Every loaded version with its counts, for the reviewer screen."""
    out = []
    for v in await vstore.find_many("instrument_versions", {}, sort=[("created_at", 1)]):
        inst = await vstore.find_one("instruments", {"id": v["instrument_id"]})
        n = await vstore.count("provisions", {"instrument_version_id": v["id"]})
        out.append({"version_id": v["id"], "act": inst["title"], "label": v["label"], "effective_from": v.get("effective_from"), "effective_to": v.get("effective_to"), "sections": n,
                    "reviewed": await vstore.count("provisions", {"instrument_version_id": v["id"], "review_status": "reviewed"}),
                    "rejected": await vstore.count("provisions", {"instrument_version_id": v["id"], "review_status": "rejected"})})
    return out


@admin_router.get("/versions/{version_id}/provisions")
async def version_provisions(version_id: str, status: str | None = Query(None, max_length=10)):
    """The sections of one version as the reviewer screen shows them: text, status, source address, flags. status = DRAFT | REVIEWED | REJECTED filters."""
    meta, _ = await legal_review_pack.rows_for(version_id)
    out = []
    in_library = {e["provision_id"]: e["id"] for e in await vstore.verified_entries({"origin": library.REVIEWER_SCREEN, "provision_id": {"$exists": True}}, {"provision_id": 1, "id": 1}, limit=0)}
    for p in await vstore.find_many("provisions", {"instrument_version_id": version_id}, sort=[("created_at", 1)]):
        label = {"reviewed": "REVIEWED", "rejected": "REJECTED"}.get(p.get("review_status", "unreviewed"), "DRAFT")
        if status and label != status.upper():
            continue
        out.append({"id": p["id"], "number": p["number"], "heading": p.get("heading", ""), "text": p["text_full"], "status": label, "reviewed_by": p.get("reviewed_by"), "reviewed_on": p.get("reviewed_on"),
                    "rejected_reason": p.get("rejected_reason"), "hash": p["content_sha256"][:12], "machine_read": bool(p.get("machine_read")), "second_source": p.get("second_source"),
                    "library_entry_id": in_library.get(p["id"])})
    doc = await vstore.find_one("legal_documents", {"id": meta["document_id"]}, {"pages": 0}) or {}
    return {**meta, "document_id": meta["document_id"], "source_url": doc.get("file_url") or doc.get("source_page_url") or "", "retrieved_on": doc.get("retrieved_on"), "provisions": out}


@admin_router.get("/review-pack/{version_id}")
async def review_pack(version_id: str, format: str = Query("docx", pattern="^(docx|csv)$"), status: str | None = Query(None, max_length=10)):
    try:
        meta, rows = await legal_review_pack.rows_for(version_id, status)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if format == "csv":
        return Response(legal_review_pack.to_csv(rows), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="review-pack.csv"'})
    return Response(legal_review_pack.to_docx(meta, rows), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": 'attachment; filename="review-pack.docx"'})


@admin_router.get("/mappings/disagreements")
async def mapping_disagreements():
    return await code_mappings.disagreements()


@admin_router.get("/provisions/{provision_id}/library-entry")
async def library_entry(provision_id: str):
    try:
        return await legal_store.build_library_entry(provision_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@admin_router.post("/mappings", status_code=201)
async def add_mapping(body: MappingIn, admin: dict = Depends(require_platform_admin)):
    try:
        m = await code_mappings.create(body.model_dump(), admin["email"])
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_MAPPING_ADDED", detail=m["relationship"])
    return code_mappings.present(m)


class MappingRowsIn(BaseModel):
    legacy_instrument: str = Field(min_length=3, max_length=200)
    new_instrument: str = Field(min_length=3, max_length=200)
    rows: list[dict] = Field(min_length=1, max_length=3000)


@admin_router.post("/mappings/import", status_code=201)
async def import_mappings(body: MappingRowsIn, admin: dict = Depends(require_platform_admin)):
    """Load rows of an official comparison table as unreviewed mappings. Each row passes the same checks as one entered by hand; failures are listed, not guessed."""
    try:
        out = await code_mappings.import_rows(body.legacy_instrument, body.new_instrument, body.rows, admin["email"])
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_MAPPING_ADDED", detail=f"import: {out['created']} created, {len(out['failed'])} failed")
    return out


@admin_router.post("/mappings/{mapping_id}/review")
async def review_mapping(mapping_id: str, body: ReviewIn, admin: dict = Depends(require_platform_admin)):
    try:
        m = await code_mappings.review(mapping_id, body.reviewed_by, body.on)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "LEGAL_MAPPING_REVIEWED", detail=f"{body.reviewed_by[:60]}")
    return code_mappings.present(m)
