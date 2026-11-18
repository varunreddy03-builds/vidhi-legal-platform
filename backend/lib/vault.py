"""The Vault's review table: ask the same questions of many documents and get one row per document, with an exact quote and a page for every answer.

A Vault is a matter whose kind is VAULT (routers/vault.py): everything a matter already has (upload, deletion, one firm never seeing another's data) is reused. This module is the part that
is new, and it is plain code except for the one question put to the model per document.

The rules, enforced here and not left to the model:
- The model is asked, for each column, for an answer, the EXACT quote that supports it and its page. Nothing is accepted on its word: the quote is looked up in the document's own text
  (lib/textmatch.locate: whole words and whole numbers, layout forgiven) and the answer must be backed by it (lib/textmatch.supports: every figure in the answer is on that page and
  the distinctive words are near the quote).
- FOUND = quote found, on the page shown, and it backs the answer. UNCONFIRMED = an answer came back but the program could not confirm it (shown, and marked so). NONE_REPORTED = the model gave
  no answer: that is NOT proof the document is silent, and the cell says so. "Not in the document" is never stated as a fact.
- Answers are made neutral (lib/neutral) and cut to a length; a custom question is limited in length; at most MAX_COLUMNS columns.
- The CSV neutralises cells that a spreadsheet would run as a formula."""

import csv
import io
import re

from lib import textmatch
from lib.neutral import neutralize

MAX_COLUMNS = 12
MIN_QUESTION, MAX_QUESTION = 5, 300
MAX_ANSWER = 600

PRESETS: tuple[dict, ...] = (
    {"id": "parties", "label": "Parties", "question": "Who are the parties to this document, and in what roles?"},
    {"id": "date", "label": "Date", "question": "What is the date of this document, or the date it takes effect?"},
    {"id": "term", "label": "Term and renewal", "question": "How long does it run, and can it be renewed or extended?"},
    {"id": "termination", "label": "Termination", "question": "How can each party end it, and on what notice?"},
    {"id": "payment", "label": "Payment", "question": "What is to be paid, when, and what happens if payment is late?"},
    {"id": "indemnity", "label": "Indemnity", "question": "Does either party promise to indemnify the other? For what?"},
    {"id": "liability", "label": "Limit of liability", "question": "Is either party's liability limited or excluded? How?"},
    {"id": "confidentiality", "label": "Confidentiality", "question": "What must be kept confidential, and for how long?"},
    {"id": "governing_law", "label": "Governing law", "question": "Which law does the document say governs it?"},
    {"id": "disputes", "label": "Disputes", "question": "Where, and how, are disputes to be resolved (courts, arbitration, mediation)?"},
    {"id": "notices", "label": "Notices", "question": "How and where must notices be given?"},
    {"id": "change_of_control", "label": "Change of control or assignment", "question": "What does it say about assignment or a change of control of a party?"},
    {"id": "signatures", "label": "Signatures", "question": "Who signed, and on what date?"},
)
PRESET_IDS = {p["id"]: p for p in PRESETS}

SCHEMA = '{"cells": [{"id": str, "answer": str or null, "quote": str or null, "page": int or null}]}'

STATUS_NOTE = {
    "FOUND": "The program found this quote on the page shown, and it backs the answer. (Checked by the program, not by the AI.)",
    "UNCONFIRMED": "The program could not confirm this answer: the quote was not found as written, or it does not back the answer. Read the document before relying on it.",
    "NONE_REPORTED": "The AI reported nothing for this. That is not proof the document is silent: search the document yourself.",
}


def clean_columns(raw) -> list[dict]:
    """The columns for one run: preset ids and/or custom questions. Raises ValueError with a plain sentence."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("Choose at least one column.")
    if len(raw) > MAX_COLUMNS:
        raise ValueError(f"At most {MAX_COLUMNS} columns at a time.")
    out, seen, custom = [], set(), 0
    for item in raw:
        item = item if isinstance(item, dict) else {}
        pid = str(item.get("id") or "").strip()
        if pid in PRESET_IDS:
            if pid in seen:
                continue
            seen.add(pid)
            out.append(dict(PRESET_IDS[pid]))
            continue
        question = " ".join(str(item.get("question") or "").split())
        if not (MIN_QUESTION <= len(question) <= MAX_QUESTION):
            raise ValueError(f"A column is either one of the listed ones or a question of {MIN_QUESTION} to {MAX_QUESTION} characters.")
        custom += 1
        label = " ".join(str(item.get("label") or "").split())[:40] or question[:40]
        out.append({"id": f"c{custom}", "label": label, "question": question})
    if not out:
        raise ValueError("Choose at least one column.")
    return out


def prompt_for(label: str, filename: str, fenced_text: str, columns: list[dict]) -> str:
    cols = "\n".join(f"- id={c['id']}: {c['question']}" for c in columns)
    return (
        f"DOCUMENT ([{label}] {filename}):\n{fenced_text}\n\n"
        "For EACH column below, answer ONLY from this document. Give: a short answer in plain words; the EXACT quote copied word for word from the document that supports it; and the page "
        "number of that quote. If the document does not say, set answer, quote and page to null. Never guess, never use knowledge from outside this document, never state what the law "
        "provides, and never judge anyone's honesty (describe differences neutrally). Reply with one cell per column, using the same id.\n"
        f"COLUMNS:\n{cols}"
    )


def _cell(col: dict, status: str, answer: str, quote: str, page: int | None) -> dict:
    return {"id": col["id"], "status": status, "answer": answer, "quote": quote, "page": page, "note": STATUS_NOTE[status]}


def verify_cells(model: dict | None, columns: list[dict], pages: list[str]) -> list[dict]:
    """One checked cell per column, in column order. `model` is the parsed reply; anything missing or malformed is treated as 'nothing reported'."""
    reported = model.get("cells") if isinstance(model, dict) else None
    by_id = {str(c.get("id")): c for c in reported if isinstance(c, dict)} if isinstance(reported, list) else {}
    out = []
    for col in columns:
        c = by_id.get(col["id"]) or {}
        answer = " ".join(str(c.get("answer") or "").split())
        quote = " ".join(str(c.get("quote") or "").split())
        if not answer:
            out.append(_cell(col, "NONE_REPORTED", "", "", None))
            continue
        answer = neutralize(answer[:MAX_ANSWER])[0]
        loc = textmatch.locate(quote, pages) if quote else None
        if loc and textmatch.supports(answer, [(loc["text"], loc["start"], loc["end"])]):
            out.append(_cell(col, "FOUND", answer, quote[:600], loc["page"]))
        else:
            out.append(_cell(col, "UNCONFIRMED", answer, quote[:600], loc["page"] if loc else None))
    return out


_FORMULA = re.compile(r"^[=+\-@\t\r]")


def _safe(value) -> str:
    s = "" if value is None else str(value)
    return "'" + s if _FORMULA.match(s) else s


def csv_bytes(columns: list[dict], rows: list[dict]) -> bytes:
    """The table as CSV (with a byte-order mark so Excel reads the languages right). Each answer is followed by its quote, page and status."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    head = ["Document"]
    for c in columns:
        head += [c["label"], f"{c['label']} - quote", f"{c['label']} - page", f"{c['label']} - status"]
    w.writerow([_safe(h) for h in head])
    for r in rows:
        cells = {c["id"]: c for c in r.get("cells", [])}
        line = [r.get("filename", "")]
        for col in columns:
            c = cells.get(col["id"]) or {}
            line += [c.get("answer", ""), c.get("quote", ""), c.get("page") or "", c.get("status", "")]
        w.writerow([_safe(x) for x in line])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")
