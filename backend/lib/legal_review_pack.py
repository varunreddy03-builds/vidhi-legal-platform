"""Review pack: everything an advocate needs to go through one loaded version of an Act, section by section, outside the app (Word or CSV), with the source address to compare against.

Status words in the pack are DRAFT (loaded, not yet compared by a named person), REVIEWED (compared by a named person on a date) and REJECTED (a reviewer said it does not match).
The pack contains the loaded text exactly as stored. The advocate's decisions are recorded in the app (admin screen or API) by name and date; the pack itself decides nothing."""

import csv
import io

from lib.db import db

COLUMNS = ["Act", "Section", "Heading", "Text as loaded", "Status", "Reviewed by", "Reviewed on", "Hash (first 12)", "Source address", "Retrieved on", "Effective (as recorded)",
           "Second source", "Read by machine", "Decision (approve / reject)", "Reviewer's note"]
LABEL = {"reviewed": "REVIEWED", "rejected": "REJECTED"}


async def rows_for(version_id: str, status: str | None = None) -> tuple[dict, list[list[str]]]:
    version = await db.instrument_versions.find_one({"id": version_id})
    if not version:
        raise ValueError("Unknown version.")
    inst = await db.instruments.find_one({"id": version["instrument_id"]})
    doc = await db.legal_documents.find_one({"id": version["document_id"]}, {"pages": 0}) or {}
    eff = (f"from {version['effective_from']}" if version.get("effective_from") else "date not recorded") + (f" to {version['effective_to']}" if version.get("effective_to") else "")
    out = []
    async for p in db.provisions.find({"instrument_version_id": version_id}).sort("created_at", 1):
        label = LABEL.get(p.get("review_status", "unreviewed"), "DRAFT")
        if status and label != status.upper():
            continue
        ss = p.get("second_source") or {}
        second = ss.get("status", "not compared") + (f" ({len(ss.get('differences', []))} differences)" if ss.get("status") == "DIFFERENT" else "")
        out.append([inst["title"], p["number"], p.get("heading", ""), p["text_full"], label, p.get("reviewed_by") or "", p.get("reviewed_on") or "", p["content_sha256"][:12],
                    doc.get("file_url") or doc.get("source_page_url") or "(none recorded)", doc.get("retrieved_on") or "", eff, second, "yes" if p.get("machine_read") else "no", "", ""])
    meta = {"act": inst["title"], "version_label": version["label"], "effective": eff, "document_id": version["document_id"], "document": doc.get("title", ""), "document_sha256": doc.get("sha256", ""), "sections": len(out)}
    return meta, out


def to_csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")  # a byte-order mark so Excel shows Indian scripts correctly


def to_docx(meta: dict, rows: list[list[str]]) -> bytes:
    from docx import Document
    from docx.shared import Pt

    d = Document()
    d.add_heading(f"Review pack: {meta['act']}", 1)
    d.add_paragraph(f"Version: {meta['version_label']} ({meta['effective']}). Source file: {meta['document']} (SHA-256 {meta['document_sha256'][:16]}). Sections in this pack: {meta['sections']}.")
    d.add_paragraph("What to do: for each section compare the text below with the official text at the source address. Write approve or reject and a note. The text is shown exactly as loaded. "
                    "Nothing here is legal advice, and nothing counts as reviewed until your name and date are recorded in VIDHI.")
    for r in rows:
        d.add_heading(f"Section {r[1]}" + (f": {r[2]}" if r[2] else ""), 2)
        meta_line = f"Status: {r[4]}" + (f" by {r[5]} on {r[6]}" if r[5] else "") + f" | Hash {r[7]} | Second source: {r[11]} | Read by machine: {r[12]}"
        d.add_paragraph(meta_line).runs[0].font.size = Pt(8)
        d.add_paragraph(f"Source: {r[8]} (retrieved {r[9] or 'date not recorded'}); effective {r[10]}").runs[0].font.size = Pt(8)
        d.add_paragraph(r[3])
        d.add_paragraph("Decision: approve / reject        Note: ______________________________________")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
