"""What each kind of queued job does (lib/jobs.py). Handlers are safe to run again: registering the same file twice returns the same record."""

from bson import ObjectId

from lib import filestore, jobs, legal_store, ocr_engine


async def ocr_legal_document(payload: dict) -> dict:
    """Read a scanned law PDF (embedded text, Tesseract if installed, else the hosted reader), then register it with per-page reading metadata."""
    fid = ObjectId(payload["stored_file_id"])
    data = await filestore.read(fid)
    try:
        pages, meta = await ocr_engine.read_pdf(f"legal-scan-{payload['source_id']}", data)
    except ValueError as exc:  # too long, or too large: trying again will not change that
        raise jobs.Permanent(str(exc)) from exc
    if not any(p.strip() for p in pages):
        raise ValueError("No text could be read from that scan.")
    doc = await legal_store.register_document(payload["source_id"], payload["meta"], text_pages=pages, file_bytes=data, stored_file_id=fid, page_meta=meta)
    if doc["duplicate"]:
        await filestore.delete(fid)  # the same file was already registered; keep one stored copy
    return {"document_id": doc["id"], "duplicate": doc["duplicate"], "pages": len(pages), "uncertain_pages": doc.get("uncertain_pages", []), "ocr_status": doc.get("ocr_status")}


HANDLERS = {"ocr-legal-document": ocr_legal_document}