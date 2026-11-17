"""Case-law interaction: decisions and how later decisions treated them (followed, distinguished, overruled ...).

Ships empty. A decision is a record someone loaded (citation text, title, forum, date, where it came from, optionally its text). A treatment is an edge "decision A
<treatment> decision B" with the exact passage of A that shows it. If A's text was loaded the passage must really be in it. A treatment can be reviewed by a named
lawyer only when its passage was checked against loaded text. VIDHI never says a decision is "good law": it reports the treatments that are recorded and says that
is all it knows."""

import re
import uuid
from datetime import date, datetime, timezone

from lib import verified_store as store
from lib.db import db
from lib.library import norm_text
from lib.verify import find_quote

TREATMENTS = ("followed", "applied", "affirmed", "explained", "distinguished", "doubted", "criticised", "overruled", "reversed", "set_aside")
NEGATIVE = {"doubted", "criticised", "overruled", "reversed", "set_aside"}
LIMIT = "This is only what has been loaded. It does not say whether the decision is good law or binds anyone; a lawyer must check the decisions themselves."
NOT_REVIEWED = "Not reviewed: recorded from a source and not yet compared with it by a lawyer."


def now() -> datetime:
    return datetime.now(timezone.utc)


def _norm_citation(s: str) -> str:
    return re.sub(r"[^\w]+", " ", norm_text(s)).strip()


async def add_decision(d: dict) -> dict:
    citation = str(d.get("citation") or "").strip()
    if len(citation) < 3 or len(citation) > 200:
        raise ValueError("Give the citation as it appears in the source (3 to 200 characters).")
    source_note = str(d.get("source_note") or "").strip()
    if len(source_note) < 10:
        raise ValueError("Say where this decision came from (at least 10 characters).")
    decided_on = None
    if d.get("decided_on"):
        try:
            decided_on = date.fromisoformat(d["decided_on"]).isoformat()
        except ValueError as exc:
            raise ValueError("decided_on must be a date like 1999-04-27.") from exc
    forum_id = d.get("forum_id") or None
    if forum_id and not await db.forums.find_one({"id": forum_id}):
        raise ValueError("Unknown forum.")
    key = _norm_citation(citation)
    existing = await db.decisions.find_one({"citation_norm": key})
    if existing:
        return {**public_decision(existing), "duplicate": True}
    row = {"id": str(uuid.uuid4()), "citation": citation, "citation_norm": key, "title": str(d.get("title") or "").strip()[:300], "forum_id": forum_id, "decided_on": decided_on,
           "source_note": source_note[:1000], "pages": [str(p) for p in (d.get("pages") or [])][:3000], "created_at": now()}
    await store.create(db, "decisions", row)
    return public_decision(row)


def public_decision(row: dict) -> dict:
    return {"id": row["id"], "citation": row["citation"], "title": row.get("title", ""), "forum_id": row.get("forum_id"), "decided_on": row.get("decided_on"), "source_note": row.get("source_note", ""),
            "text_loaded": bool(row.get("pages"))}


async def add_treatment(from_id: str, to_id: str, treatment: str, passage: str) -> dict:
    t = (treatment or "").strip().lower()
    if t not in TREATMENTS:
        raise ValueError(f"treatment must be one of {', '.join(TREATMENTS)}.")
    if from_id == to_id:
        raise ValueError("A decision cannot be treated by itself.")
    a, b = await db.decisions.find_one({"id": from_id}), await db.decisions.find_one({"id": to_id})
    if not a or not b:
        raise ValueError("Both decisions must be loaded first.")
    passage = (passage or "").strip()
    if len(passage) < 12:
        raise ValueError("Quote the passage of the later decision that shows the treatment (at least 12 characters).")
    checked = False
    if a.get("pages"):
        if find_quote(passage, a["pages"]) is None:
            raise ValueError("That passage is not in the loaded text of the later decision.")
        checked = True
    row = {"id": str(uuid.uuid4()), "from_decision_id": from_id, "to_decision_id": to_id, "treatment": t, "passage": passage[:2000], "passage_checked": checked, "review_status": "unreviewed",
           "reviewed_by": None, "reviewed_on": None, "created_at": now()}
    await store.create(db, "treatments", row)
    return public_treatment(row)


def public_treatment(row: dict) -> dict:
    reviewed = row.get("review_status") == "reviewed"
    return {"id": row["id"], "from_decision_id": row["from_decision_id"], "to_decision_id": row["to_decision_id"], "treatment": row["treatment"], "negative": row["treatment"] in NEGATIVE,
            "passage": row["passage"], "passage_checked": row["passage_checked"], "review_status": row.get("review_status", "unreviewed"), "reviewed_by": row.get("reviewed_by"),
            "review_statement": f"Compared with the decision by {row.get('reviewed_by')} on {row.get('reviewed_on')}." if reviewed else NOT_REVIEWED}


async def review_treatment(treatment_id: str, reviewer: str, on: str) -> dict:
    row = await db.treatments.find_one({"id": treatment_id})
    if not row:
        raise ValueError("Unknown treatment.")
    if not row.get("passage_checked"):
        raise ValueError("The later decision's text was not loaded, so the passage could not be checked. Load the text first.")
    if len(reviewer.strip()) < 5:
        raise ValueError("Give the reviewer's full name.")
    try:
        day = date.fromisoformat(on).isoformat()
    except ValueError as exc:
        raise ValueError("reviewed_on must be a date like 2026-11-05.") from exc
    later = await db.decisions.find_one({"id": row.get("to_decision_id")}, {"source_note": 1}) or {}
    await store.record_review(db, "treatments", treatment_id, "reviewed", reviewer, day, (later.get("source_note") or "").strip() or f"decision {row.get('to_decision_id')}")
    return public_treatment({**row, "review_status": "reviewed", "reviewed_by": reviewer.strip(), "reviewed_on": day})


async def standing(decision_id: str) -> dict | None:
    d = await db.decisions.find_one({"id": decision_id})
    if not d:
        return None
    rows = [public_treatment(r) async for r in db.treatments.find({"to_decision_id": decision_id}).sort("created_at", 1)]
    for r in rows:
        later = await db.decisions.find_one({"id": r["from_decision_id"]})
        r["later_decision"] = public_decision(later) if later else None
    neg_rev = [r for r in rows if r["negative"] and r["review_status"] == "reviewed"]
    neg_unrev = [r for r in rows if r["negative"] and r["review_status"] != "reviewed"]
    status = "NEGATIVE_TREATMENT_REVIEWED" if neg_rev else "NEGATIVE_TREATMENT_REPORTED_UNREVIEWED" if neg_unrev else ("TREATMENTS_RECORDED_NONE_NEGATIVE" if rows else "NO_TREATMENT_RECORDED")
    return {"decision": public_decision(d), "status": status, "treatments": rows, "negative_reviewed": len(neg_rev), "negative_unreviewed": len(neg_unrev), "note": LIMIT}


async def find_decision(citation: str) -> dict | None:
    row = await db.decisions.find_one({"citation_norm": _norm_citation(citation)})
    return public_decision(row) if row else None
