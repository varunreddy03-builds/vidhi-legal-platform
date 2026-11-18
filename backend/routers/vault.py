"""The Vault's review table (lib/vault.py has the rules): the same questions asked of each document of a matter, one row per document, every answer with a program-checked quote and page.

One document is processed per request, so a person watches the table fill, can stop it, and one slow document cannot make a whole request time out. A Vault is simply a matter whose kind is
VAULT: uploads, per-document summaries and contract flags (POST /documents/{id}/analyze), questions across all documents (POST /research with the matter's id) and deletion are the existing,
tested ones."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from lib import vault
from lib.ai import ai_failure, ask_json, log_ai_failure
from lib.auth import audit, current_user, now, require_intelligence
from lib.db import db
from lib.matter_context import build_corpus, select_context
from lib.plans import context_budget, gate_ai
from lib.ratelimit import AI_LIMIT
from lib.safety import fence

router = APIRouter(tags=["vault"])


class RowIn(BaseModel):
    document_id: str = Field(min_length=1, max_length=64)
    columns: list[dict] = Field(min_length=1, max_length=vault.MAX_COLUMNS)


async def _matter(matter_id: str, user: dict) -> dict:
    m = await db.matters.find_one({"id": matter_id, "organization_id": user["organization_id"]})
    if not m:
        raise HTTPException(status_code=404, detail="Matter not found")
    return m


def _public(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in ("_id", "organization_id", "created_by")}


@router.get("/vault/columns")
async def vault_columns(user: dict = Depends(current_user)):
    return {"presets": list(vault.PRESETS), "max_columns": vault.MAX_COLUMNS, "question_length": [vault.MIN_QUESTION, vault.MAX_QUESTION]}


@router.post("/matters/{matter_id}/vault/rows", dependencies=[Depends(AI_LIMIT)])
async def vault_row(matter_id: str, body: RowIn, user: dict = Depends(require_intelligence)):
    """Ask the chosen columns of ONE document and keep the checked row (replacing that document's earlier row)."""
    await _matter(matter_id, user)
    doc = await db.documents.find_one({"id": body.document_id, "matter_id": matter_id, "organization_id": user["organization_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found in this matter")
    pages: list[str] = doc.get("pages", [])
    if not any((p or "").strip() for p in pages):
        raise HTTPException(status_code=409, detail="This file has no readable text, so there is nothing to put in the table.")
    try:
        columns = vault.clean_columns(body.columns)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tier = await gate_ai(user, "vault-row")
    mine = build_corpus([doc])[0]
    text, cov = select_context(" ".join(c["question"] for c in columns), [mine], budget=context_budget(user))
    prompt = vault.prompt_for(mine["label"], doc.get("filename", ""), fence(text, mine["label"] + " " + doc.get("filename", "")), columns)
    try:
        data = await ask_json(f"vault-{doc['id']}", prompt, vault.SCHEMA, purpose="vault-row", tier=tier)
    except Exception as exc:  # noqa: BLE001
        log_ai_failure("vault row", exc)
        await audit(user, "VAULT_ROW", result="FAILED", matter_id=matter_id)
        raise ai_failure(exc) from exc
    row = {
        "id": str(uuid.uuid4()), "organization_id": user["organization_id"], "matter_id": matter_id, "document_id": doc["id"], "filename": doc.get("filename", ""), "columns": columns,
        "cells": vault.verify_cells(data, columns, pages), "read_in_full": bool(cov["complete"]), "coverage_note": "" if cov["complete"] else cov["summary"],
        "created_by": user["id"], "created_at": now(),
    }
    await db.vault_rows.replace_one({"matter_id": matter_id, "document_id": doc["id"], "organization_id": user["organization_id"]}, row, upsert=True)
    await audit(user, "VAULT_ROW", matter_id=matter_id)
    return _public(row)


async def _rows(matter_id: str, user: dict) -> list[dict]:
    return await db.vault_rows.find({"matter_id": matter_id, "organization_id": user["organization_id"]}).sort("filename", 1).to_list(2000)


@router.get("/matters/{matter_id}/vault/summaries")
async def vault_summaries(matter_id: str, user: dict = Depends(current_user)):
    """Each document's SAVED analysis (summary, clause flags with their program-checked quotes), made earlier by POST /documents/{id}/analyze. Makes no AI call."""
    await _matter(matter_id, user)
    docs = await db.documents.find({"matter_id": matter_id, "organization_id": user["organization_id"]}, {"id": 1, "filename": 1, "doc_class": 1, "analysis": 1, "pages": 1}).sort("filename", 1).to_list(5000)
    items = [{"document_id": d["id"], "filename": d.get("filename", ""), "doc_class": d.get("doc_class", "OTHER"), "has_text": any((p or "").strip() for p in d.get("pages", [])), "analysis": d.get("analysis")} for d in docs]
    return {"items": items, "documents_total": len(items), "summarised": sum(1 for i in items if i["analysis"]), "waiting": sum(1 for i in items if i["has_text"] and not i["analysis"])}


@router.get("/matters/{matter_id}/vault/rows")
async def vault_rows(matter_id: str, user: dict = Depends(current_user)):
    await _matter(matter_id, user)
    rows = await _rows(matter_id, user)
    docs = await db.documents.find({"matter_id": matter_id, "organization_id": user["organization_id"]}, {"pages": 1, "id": 1}).to_list(5000)
    with_text = sum(1 for d in docs if any((p or "").strip() for p in d.get("pages", [])))
    latest = max(rows, key=lambda r: r["created_at"]) if rows else None
    return {"rows": [_public(r) for r in rows], "columns": latest["columns"] if latest else [], "documents_total": len(docs), "documents_with_text": with_text,
            "note": "Each answer carries a quote the program looked up in the document. 'Unconfirmed' and 'nothing reported' cells are marked as such. Check the document before relying on any cell."}


@router.delete("/matters/{matter_id}/vault/rows")
async def vault_clear(matter_id: str, user: dict = Depends(current_user)):
    await _matter(matter_id, user)
    n = (await db.vault_rows.delete_many({"matter_id": matter_id, "organization_id": user["organization_id"]})).deleted_count
    await audit(user, "VAULT_TABLE_CLEARED", matter_id=matter_id)
    return {"deleted": n}


@router.get("/matters/{matter_id}/vault/table.csv")
async def vault_csv(matter_id: str, user: dict = Depends(current_user)):
    m = await _matter(matter_id, user)
    rows = await _rows(matter_id, user)
    if not rows:
        raise HTTPException(status_code=404, detail="The table is empty: run it first.")
    columns = max(rows, key=lambda r: r["created_at"])["columns"]
    name = "".join(ch if ch.isalnum() else "-" for ch in m.get("title", "vault"))[:60].strip("-") or "vault"
    return Response(content=vault.csv_bytes(columns, rows), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}-table.csv"', "Cache-Control": "no-store"})
