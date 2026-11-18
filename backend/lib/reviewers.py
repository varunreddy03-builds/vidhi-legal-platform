"""Advocates who compare the library's text with the official text, and how their confirmation is recorded.

Two kinds of reviewer, by the owner's decision (2026-11-18):
- every reviewer is shown only as "Advocate R-01", "R-02", ... (owner, 2026-11-18: no names are shown, Pavani's included). A reviewer may have their own account and confirm an Act themselves.
  (The code can still show a reviewer by name if the owner ever chooses to, but nothing does today.) Their real names and enrolment numbers are kept in `legal_reviewers` (operator-only: no public or customer route reads them)
  and are never written into a provision, a log line or an API reply other than the operator's own list. The operator records an anonymous reviewer's confirmation after receiving it
  in writing, and the log keeps the reference of that confirmation.

A confirmation never decides anything by itself. It goes through legal_store.review_provision, which is the only way a provision becomes "reviewed": hash unchanged, source address present,
and the two acknowledgements (scan read by a machine; second source worded differently) are NEVER given here, so those provisions are skipped and listed for a person to compare one by one.
Judgments can never be marked verified, whoever has read them (lib/hc_judgments.validate_record)."""

import re
import uuid

from lib import legal_store
from lib.auth import now
from lib.db import db

LABEL = re.compile(r"^Advocate R-\d{2,3}$")


class ReviewerError(ValueError):
    pass


async def next_code() -> str:
    n = 0
    async for r in db.legal_reviewers.find({"named_publicly": False}, {"label": 1}):
        m = re.search(r"(\d+)$", r.get("label", ""))
        n = max(n, int(m.group(1)) if m else 0)
    return f"Advocate R-{n + 1:02d}"


async def register(*, private_name: str, enrolment_no: str, bar_council: str, named_publicly: bool, public_label: str, user_id: str | None) -> dict:
    private_name = " ".join(private_name.split())
    if len(private_name) < 5:
        raise ReviewerError("Give the advocate's full name (kept private unless they are to be shown by name).")
    if len(enrolment_no.strip()) < 3:
        raise ReviewerError("Give the enrolment number (kept private).")
    if named_publicly:
        label = " ".join(public_label.split())
        if len(label) < 5 or LABEL.match(label):
            raise ReviewerError("A reviewer shown by name needs the name to show, for example: Advocate Pavani.")
    else:
        label = await next_code()
    row = {"id": str(uuid.uuid4()), "label": label, "named_publicly": named_publicly, "private_name": private_name, "enrolment_no": enrolment_no.strip(), "bar_council": bar_council.strip()[:120],
           "user_id": user_id, "active": True, "created_at": now()}
    await db.legal_reviewers.insert_one(row)
    return row


def operator_view(r: dict) -> dict:
    return {k: v for k, v in r.items() if k != "_id"}


def public_view(r: dict, acts: int, provisions: int) -> dict:
    """The only shape that leaves the operator's console: the label and what was confirmed."""
    return {"label": r["label"], "named": bool(r["named_publicly"]), "acts_confirmed": acts, "provisions_confirmed": provisions}


async def confirm_act(reviewer: dict, instrument_id: str, on: str, *, compared_with_official_text: bool, mode: str, recorded_by: str, reference: str = "") -> dict:
    if not reviewer.get("active"):
        raise ReviewerError("This reviewer is not active.")
    if not compared_with_official_text:
        raise ReviewerError("Confirm that every provision was compared with the official text, word by word.")
    inst = await db.instruments.find_one({"id": instrument_id})
    if not inst:
        raise ReviewerError("Unknown Act.")
    done, skipped = 0, []
    async for p in db.provisions.find({"instrument_id": instrument_id, "review_status": {"$nin": ["reviewed", "rejected"]}}, {"id": 1, "number": 1}).sort("number", 1):
        try:
            await legal_store.review_provision(p["id"], reviewer["label"], on)  # no acknowledgements: see the module note
            done += 1
        except ValueError as exc:
            skipped.append({"provision_id": p["id"], "number": p.get("number"), "reason": str(exc)[:240]})
    entry = {"id": str(uuid.uuid4()), "reviewer_id": reviewer["id"], "instrument_id": instrument_id, "instrument": inst.get("title", ""), "on": on, "mode": mode, "recorded_by": recorded_by,
             "reference": reference.strip()[:200], "confirmed": done, "skipped": len(skipped), "created_at": now()}
    await db.legal_review_log.insert_one(entry)
    return {"confirmed": done, "skipped": skipped, "instrument": inst.get("title", ""), "reviewer": reviewer["label"],
            "note": "Skipped provisions need a person to compare them one by one (machine-read scan, a second source worded differently, or a text problem)."}


async def public_list() -> list[dict]:
    out = []
    async for r in db.legal_reviewers.find({"active": True}).sort("label", 1):
        log = await db.legal_review_log.find({"reviewer_id": r["id"]}).to_list(5000)
        out.append(public_view(r, len({x["instrument_id"] for x in log}), sum(x["confirmed"] for x in log)))
    return out
