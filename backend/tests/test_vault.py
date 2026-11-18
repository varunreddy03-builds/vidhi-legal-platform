"""The Vault's review table (lib/vault.py, routers/vault.py): the same questions asked of many documents, every answer with a quote the PROGRAM looked up in the document.
A cell is FOUND only when the quote is in the document's own text on the page shown AND backs the answer; otherwise it is marked UNCONFIRMED or NONE_REPORTED, never presented as fact."""

import uuid

import pytest

from lib import vault
from tests.conftest import ai_prompts, mongo, new_matter, stub, upload

LEASE = (
    "LEASE AGREEMENT\nThis lease is made on 1 March 2026 between Meena Traders (the Landlord) and Ravi Kumar (the Tenant).\n"
    "The monthly rent is Rs 25,000, payable on or before the fifth day of each month.\n"
    "Either party may end this lease by giving sixty days written notice.\n"
)
PAGES = [LEASE, "This lease is governed by the laws of India. Disputes go to the courts at Hyderabad.\n"]


def cols(*ids):
    return [{"id": i} for i in ids]


# ---------- the pure rules ----------

def test_columns_are_presets_or_bounded_custom_questions():
    out = vault.clean_columns([{"id": "parties"}, {"id": "parties"}, {"id": "payment"}, {"question": "  Who is the guarantor,   if any? ", "label": "Guarantor"}])
    assert [c["id"] for c in out] == ["parties", "payment", "c1"] and out[2]["question"] == "Who is the guarantor, if any?" and out[2]["label"] == "Guarantor"
    assert out[0] is not vault.PRESET_IDS["parties"]  # a copy: a request cannot change the shared list
    for bad in (None, [], "parties", [{}], [{"id": "no-such-preset"}], [{"question": "hi"}], [{"question": "x" * (vault.MAX_QUESTION + 1)}]):
        with pytest.raises(ValueError):
            vault.clean_columns(bad)
    with pytest.raises(ValueError, match="At most"):
        vault.clean_columns([{"question": f"Question number {i}?"} for i in range(vault.MAX_COLUMNS + 1)])
    assert len(vault.clean_columns([{"question": f"Question number {i}?"} for i in range(vault.MAX_COLUMNS)])) == vault.MAX_COLUMNS


def test_the_prompt_confines_the_model_to_the_document_and_names_every_column():
    cs = vault.clean_columns(cols("parties", "payment"))
    p = vault.prompt_for("DOC-01", "lease.pdf", "<<fenced text>>", cs)
    assert "<<fenced text>>" in p and "id=parties" in p and "id=payment" in p and "[DOC-01] lease.pdf" in p
    assert "ONLY from this document" in p and "EXACT quote" in p and "never use knowledge from outside" in p and "never state what the law" in p and "never judge anyone's honesty" in p


def test_a_cell_is_found_only_when_its_quote_is_in_the_document_and_backs_the_answer():
    cs = vault.clean_columns(cols("payment", "termination", "governing_law", "indemnity", "notices"))
    model = {"cells": [
        {"id": "payment", "answer": "Rs 25,000 a month, by the fifth.", "quote": "The monthly rent is Rs 25,000, payable on or before the fifth day of each month.", "page": 7},  # right quote, wrong page claimed
        {"id": "termination", "answer": "Either party can end it on 60 days notice.", "quote": "Either party may end this lease by giving ninety days written notice.", "page": 1},  # a quote that is NOT there
        {"id": "governing_law", "answer": "Indian law.", "quote": "This lease is governed by the laws of India.", "page": 1},  # found, but on page 2
        {"id": "indemnity", "answer": None, "quote": None, "page": None},
        {"id": "notices", "answer": "Notice of Rs 90,000 must be posted.", "quote": "Either party may end this lease by giving sixty days written notice.", "page": 1},  # a figure that is not on the page
    ]}
    cells = {c["id"]: c for c in vault.verify_cells(model, cs, PAGES)}
    assert cells["payment"]["status"] == "FOUND" and cells["payment"]["page"] == 1  # the page comes from the program, never from the model
    assert cells["termination"]["status"] == "UNCONFIRMED" and cells["termination"]["page"] is None
    assert cells["governing_law"]["status"] == "FOUND" and cells["governing_law"]["page"] == 2
    assert cells["indemnity"]["status"] == "NONE_REPORTED" and cells["indemnity"]["answer"] == "" and "not proof the document is silent" in cells["indemnity"]["note"]
    assert cells["notices"]["status"] == "UNCONFIRMED"  # the quote exists but does not back an amount that is not on the page
    assert [c["id"] for c in vault.verify_cells(model, cs, PAGES)] == [c["id"] for c in cs]  # column order, always


def test_a_missing_malformed_or_hostile_reply_never_makes_a_found_cell():
    cs = vault.clean_columns(cols("parties", "date"))
    for reply in (None, {}, {"cells": "nope"}, {"cells": [1, "x", None]}, {"cells": [{"id": "parties"}]}, ["cells"]):
        got = vault.verify_cells(reply, cs, PAGES)
        assert [c["status"] for c in got] == ["NONE_REPORTED", "NONE_REPORTED"]
    one = vault.verify_cells({"cells": [{"id": "parties", "answer": "x" * 5000, "quote": "Meena Traders (the Landlord) and Ravi Kumar (the Tenant)"}]}, cs, PAGES)[0]
    assert len(one["answer"]) <= vault.MAX_ANSWER


def test_an_answer_that_judges_someones_honesty_is_made_neutral():
    cs = vault.clean_columns(cols("parties"))
    cell = vault.verify_cells({"cells": [{"id": "parties", "answer": "The Landlord is Meena Traders. The Tenant lied about the rent.", "quote": "Meena Traders (the Landlord) and Ravi Kumar (the Tenant)"}]}, cs, PAGES)[0]
    assert "lied" not in cell["answer"] and "Meena Traders" in cell["answer"]


def test_the_csv_cannot_run_a_formula_and_keeps_the_quote_page_and_status_with_every_answer():
    cs = vault.clean_columns(cols("parties"))
    rows = [{"filename": "=HYPERLINK(\"http://x\")", "cells": [{"id": "parties", "answer": "+cmd|' /C calc'!A0", "quote": "@SUM(1)", "page": 3, "status": "FOUND"}]}]
    raw = vault.csv_bytes(cs, rows)
    text = raw.decode("utf-8")
    assert raw.startswith(b"\xef\xbb\xbf") and text.splitlines()[0].lstrip("﻿") == "Document,Parties,Parties - quote,Parties - page,Parties - status"
    assert "'=HYPERLINK" in text and "'+cmd" in text and "'@SUM" in text and ",3,FOUND" in text


# ---------- through the server (scripted AI) ----------

def lease_doc(c, mid):
    name = f"lease-{uuid.uuid4().hex[:8]}.txt"
    d = upload(c, mid, name, LEASE + f"Reference {uuid.uuid4().hex}.\n" + "\f" + PAGES[1])  # unique text: the app refuses the same file twice in one matter
    return d["id"], name


def test_the_table_fills_one_checked_row_per_document_and_can_be_downloaded(user_a):
    mid, title = new_matter(user_a, "Vault")
    doc_id, name = lease_doc(user_a, mid)
    stub("vault-row", {"cells": [
        {"id": "parties", "answer": "Meena Traders (Landlord) and Ravi Kumar (Tenant).", "quote": "Meena Traders (the Landlord) and Ravi Kumar (the Tenant)", "page": 1},
        {"id": "payment", "answer": "Rs 25,000 a month.", "quote": "The monthly rent is Rs 99,999 every month.", "page": 1},
        {"id": "indemnity", "answer": None, "quote": None, "page": None},
    ]}, contains=name)
    r = user_a.post(f"/matters/{mid}/vault/rows", json={"document_id": doc_id, "columns": cols("parties", "payment", "indemnity")})
    assert r.status_code == 200, r.text
    row = r.json()
    assert [c["status"] for c in row["cells"]] == ["FOUND", "UNCONFIRMED", "NONE_REPORTED"] and row["filename"] == name and "organization_id" not in row
    (prompt,) = ai_prompts(name, "vault-row")
    assert "ONLY from this document" in prompt and "Rs 25,000" in prompt  # the document's own words reach the model, fenced
    got = user_a.get(f"/matters/{mid}/vault/rows").json()
    assert len(got["rows"]) == 1 and got["documents_total"] == 1 and got["documents_with_text"] == 1 and [c["id"] for c in got["columns"]] == ["parties", "payment", "indemnity"]
    csv = user_a.get(f"/matters/{mid}/vault/table.csv")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv") and "attachment" in csv.headers["content-disposition"] and csv.headers["cache-control"] == "no-store"
    assert "Meena Traders (Landlord)" in csv.content.decode("utf-8") and name in csv.content.decode("utf-8")

    stub("vault-row", {"cells": [{"id": "parties", "answer": "The Landlord and the Tenant.", "quote": "between Meena Traders (the Landlord) and Ravi Kumar (the Tenant)", "page": 1}]}, contains=name)
    again = user_a.post(f"/matters/{mid}/vault/rows", json={"document_id": doc_id, "columns": cols("parties")})
    assert again.status_code == 200
    rows = user_a.get(f"/matters/{mid}/vault/rows").json()["rows"]
    assert len(rows) == 1 and [c["id"] for c in rows[0]["columns"]] == ["parties"]  # running a document again REPLACES its row
    assert user_a.delete(f"/matters/{mid}/vault/rows").json() == {"deleted": 1}
    assert user_a.get(f"/matters/{mid}/vault/rows").json()["rows"] == []
    assert user_a.get(f"/matters/{mid}/vault/table.csv").status_code == 404  # nothing to download


def test_bad_requests_are_refused_before_any_ai_call(user_a):
    mid, _ = new_matter(user_a, "Vault")
    doc_id, name = lease_doc(user_a, mid)
    url = f"/matters/{mid}/vault/rows"
    assert user_a.post(url, json={"document_id": doc_id, "columns": []}).status_code == 422
    assert user_a.post(url, json={"document_id": doc_id, "columns": [{"question": "hi"}]}).status_code == 422
    assert user_a.post(url, json={"document_id": doc_id, "columns": [{"id": "nope"}]}).status_code == 422
    assert user_a.post(url, json={"document_id": doc_id, "columns": [{"question": f"Question number {i}?"} for i in range(13)]}).status_code == 422
    assert user_a.post(url, json={"document_id": "no-such-document", "columns": cols("parties")}).status_code == 404
    assert user_a.post(f"/matters/no-such-matter/vault/rows", json={"document_id": doc_id, "columns": cols("parties")}).status_code == 404
    assert ai_prompts(name, "vault-row") == []  # none of that reached the model


def test_a_failed_ai_call_says_so_and_keeps_no_row(user_a):
    mid, _ = new_matter(user_a, "Vault")
    doc_id, name = lease_doc(user_a, mid)
    stub("vault-row", "__FAIL__", contains=name)
    r = user_a.post(f"/matters/{mid}/vault/rows", json={"document_id": doc_id, "columns": cols("parties")})
    assert r.status_code in (502, 503) and user_a.get(f"/matters/{mid}/vault/rows").json()["rows"] == []


def test_another_organisation_cannot_read_write_download_or_borrow_a_document(user_a, user_b):
    mid, _ = new_matter(user_a, "Vault")
    doc_id, name = lease_doc(user_a, mid)
    stub("vault-row", {"cells": [{"id": "parties", "answer": "Meena Traders.", "quote": "Meena Traders (the Landlord)", "page": 1}]}, contains=name)
    assert user_a.post(f"/matters/{mid}/vault/rows", json={"document_id": doc_id, "columns": cols("parties")}).status_code == 200
    mine, _ = new_matter(user_b, "Vault")
    assert user_b.get(f"/matters/{mid}/vault/rows").status_code == 404
    assert user_b.get(f"/matters/{mid}/vault/table.csv").status_code == 404
    assert user_b.delete(f"/matters/{mid}/vault/rows").status_code == 404
    assert user_b.post(f"/matters/{mid}/vault/rows", json={"document_id": doc_id, "columns": cols("parties")}).status_code == 404
    assert user_b.post(f"/matters/{mine}/vault/rows", json={"document_id": doc_id, "columns": cols("parties")}).status_code == 404  # my own matter, but THEIR document
    assert len(user_a.get(f"/matters/{mid}/vault/rows").json()["rows"]) == 1  # untouched


def test_a_vault_and_a_tax_matter_are_matters_with_a_kind_and_an_area(user_a):
    default = user_a.post("/matters", json={"title": f"Plain {uuid.uuid4().hex[:6]}"}).json()
    assert default["kind"] == "MATTER" and default["area"] == ""
    v = user_a.post("/matters", json={"title": f"Vault {uuid.uuid4().hex[:6]}", "kind": "VAULT"}).json()
    t = user_a.post("/matters", json={"title": f"Tax {uuid.uuid4().hex[:6]}", "area": "tax"}).json()
    assert v["kind"] == "VAULT" and t["area"] == "tax" and t["kind"] == "MATTER"
    assert user_a.get(f"/matters/{v['id']}").json()["kind"] == "VAULT"
    assert user_a.post("/matters", json={"title": "x", "kind": "SECRET"}).status_code == 422
    assert user_a.post("/matters", json={"title": "x", "area": "space"}).status_code == 422


def test_the_columns_list_and_the_erasure_of_a_matter_take_the_rows_with_it(user_a):
    cols_out = user_a.get("/vault/columns").json()
    assert {p["id"] for p in cols_out["presets"]} >= {"parties", "termination", "governing_law", "indemnity"} and cols_out["max_columns"] == vault.MAX_COLUMNS
    mid, _ = new_matter(user_a, "Vault")
    doc_id, name = lease_doc(user_a, mid)
    stub("vault-row", {"cells": [{"id": "parties", "answer": "Meena Traders.", "quote": "Meena Traders (the Landlord)", "page": 1}]}, contains=name)
    assert user_a.post(f"/matters/{mid}/vault/rows", json={"document_id": doc_id, "columns": cols("parties")}).status_code == 200
    assert mongo().vault_rows.count_documents({"matter_id": mid}) == 1
    assert user_a.delete(f"/matters/{mid}").status_code == 200
    assert mongo().vault_rows.count_documents({"matter_id": mid}) == 0  # erasing the matter erases what was extracted from it


def test_saved_summaries_come_back_without_another_ai_call_and_stay_inside_the_organisation(user_a, user_b):
    mid, _ = new_matter(user_a, "Vault")
    done, done_name = lease_doc(user_a, mid)
    waiting, waiting_name = lease_doc(user_a, mid)
    empty_id, _ = lease_doc(user_a, mid)
    mongo().documents.update_one({"id": empty_id}, {"$set": {"pages": []}})  # a file with no readable text (an empty upload is refused, so it is made empty here)
    scan = {"id": empty_id}
    mongo().documents.update_one({"id": done}, {"$set": {"analysis": {"document_id": done, "doc_class": "CONTRACT", "summary": "A lease of a shop.", "flags": [{"clause": "Termination", "risk": "LOW", "why": "Sixty days notice.", "page": 1,
                                                                                                                                                     "quote": "sixty days written notice", "quote_verified": True}]}}})
    got = user_a.get(f"/matters/{mid}/vault/summaries")
    assert got.status_code == 200
    body = got.json()
    by = {i["document_id"]: i for i in body["items"]}
    assert by[done]["analysis"]["summary"] == "A lease of a shop." and by[done]["analysis"]["flags"][0]["quote_verified"] is True and by[done]["has_text"] is True
    assert by[waiting]["analysis"] is None and by[waiting]["has_text"] is True
    assert body["documents_total"] == 3 and body["summarised"] == 1 and body["waiting"] == 1  # the empty file is not counted as waiting: there is nothing to summarise
    assert ai_prompts(done_name) == [] and ai_prompts(waiting_name) == []  # reading the saved summaries asks the model nothing
    assert user_b.get(f"/matters/{mid}/vault/summaries").status_code == 404
    assert user_a.get("/matters/no-such-matter/vault/summaries").status_code == 404
    assert scan["id"] in by
