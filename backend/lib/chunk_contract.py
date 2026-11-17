"""The same descriptive fields on every kind of text the app can retrieve (knowledge chunks already carry them), so one filter and one guard can work across them. Plain code, no model, no database.

    judgment_fields(record)      -> fields for a judgment (a case-list record, with or without its text)
    matter_page_fields(doc)      -> one entry per page of a matter document that has text

The fields: kind, trust_tier, source_id, citation_title, page_or_para, script, reviewer, review_date, and where they apply court_code, court_name, year, decision_date, organization_id, matter_id.

Rules kept here, not left to the caller:
- A judgment is T2 (public, not reviewed by a lawyer) and a matter page is T3 (the client's own document, never evidence of what the law says). Neither is ever T1: `reviewer` and `review_date` are None here.
- `script` is the writing system found in the text, never a guessed language. A page or title with no letters is "none".
- `page_or_para` is a PRINTED number only: the page number of a matter page (counted from 1 as the reader shows it). A judgment's paragraph is not known from its case-list record, so it is None; it is never made up.
- A matter page always carries its organisation and matter, so a later filter can drop a page of another organisation."""

from lib import court_hierarchy
from lib.script_detect import judgment_script, script_of

NO_PARAGRAPH = None


def judgment_fields(r: dict) -> dict:
    title = r.get("case_title") or ""
    return {
        "kind": "judgment", "trust_tier": "T2", "source_id": r["id"], "citation_title": r.get("citation") or title or r["id"], "page_or_para": NO_PARAGRAPH,
        "script": r.get("script") or judgment_script(r.get("snippet") or (r.get("text") or "")[:400], title),  # records loaded as Latin carry no field; the others carry their script
        "reviewer": None, "review_date": None,
        "court_code": r.get("court_code"), "court_name": r.get("court_name"), "year": r.get("year"), "decision_date": r.get("decision_date"),
        **court_hierarchy.describe(r.get("court_code")),  # court_level and the State(s) served: from a fixed table, None/[] for a code it does not know
    }


def matter_page_fields(doc: dict) -> list[dict]:
    out = []
    for n, page in enumerate(doc.get("pages") or [], 1):
        text = (page or "").strip()
        if not text:
            continue
        out.append({
            "kind": "matter_page", "trust_tier": "T3", "source_id": doc["id"], "citation_title": doc.get("filename") or doc["id"], "page_or_para": str(n),
            "script": script_of(text), "reviewer": None, "review_date": None,
            "organization_id": doc["organization_id"], "matter_id": doc.get("matter_id"), "exact_text": text,
        })
    return out
