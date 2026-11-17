"""What happened to a judgment: appeals, and how later judgments treated it, shown ONLY where a source states it.

A relation says "judgment A <relation> <target>" together with the exact sentence of A that states it and where it came from:
  * "stated in the judgment's own text": found by fixed rules (no AI) in judgments VIDHI holds the text of. Only clear statements by the court in the first person ("we") count ("we overrule the view
    expressed in X", "the appeal arises out of the judgment of the High Court in W.P. No. 12 of 2019"). Passive or reported statements ("was overruled by", "the counsel submits that we
    should follow") are skipped, because the direction or the speaker is not certain. A rule can still be wrong, so every relation stays UNVERIFIED until a named reviewer approves it.
  * "entered by a named person" with the source they relied on.
The target is kept as written. It is linked to a loaded judgment only when the text names a CNR (a court case identifier) that matches exactly one loaded record.
Nothing here says whether a judgment is still good law or binds anyone: it reports what is recorded, and says "Not known" when nothing is."""

import hashlib
import re
import uuid
from datetime import date, datetime, timezone

from lib import case_law
from lib import verified_store as vstore
from lib.db import db
from lib.verify import find_quote

RELATIONS = ("appeal_from", "followed", "distinguished", "overruled")
LABEL = {"appeal_from": "This judgment arises from", "followed": "This judgment follows", "distinguished": "This judgment distinguishes", "overruled": "This judgment overrules"}
LATER_LABEL = {"appeal_from": "A later judgment arises from this one (appeal)", "followed": "Followed by a later judgment", "distinguished": "Distinguished by a later judgment", "overruled": "Overruled by a later judgment"}
STATUS_UNVERIFIED = "UNVERIFIED - not reviewed"
STATUS_REVIEWED = "REVIEWED"
NOT_KNOWN = "Not known: no source in VIDHI states what happened to this judgment."
LIMIT = case_law.LIMIT
METHOD = "rules-1"
MAX_QUOTE = 600

# the speaker must be the court itself, and the sentence must not report an argument, a condition or a refusal
SPEAKER = r"we"  # "this Court" is not enough: a judgment often says "this Court distinguished ..." about an EARLIER case of the same court
# a quotation may be an earlier court speaking, so a sentence with quotation marks is skipped too
SKIP = re.compile(r"\b(?:submit(?:s|ted)?|contend(?:s|ed)?|argu(?:e|es|ed)|urg(?:e|es|ed)|pray(?:s|ed)?|counsel|whether|if|should|would|could|cannot|not|never|unable|decline[sd]?|refuse[sd]?|question|therein|said\s+(?:judgment|case|decision))\b|[\"“”]", re.I)
ABBREV = re.compile(r"(?:\b(?:No|Nos|Dr|Mr|Mrs|Ms|Shri|Smt|Hon|Sec|Art|Ltd|Co|Pvt|Vs|v|etc|viz|i\.e|e\.g|Cr|Crl|Civ|Pet|Appl|Misc|Cri|SLP|W\.P|C\.A)|\b[A-Z])\.$")
VERB = {
    "overruled": re.compile(rf"\b{SPEAKER}\s+(?:hereby\s+|respectfully\s+|therefore\s+|accordingly\s+)*overrul(?:e|es)\b(?P<rest>[^.]{{0,260}})", re.I),
    "followed": re.compile(rf"\b{SPEAKER}\s+(?:respectfully\s+|therefore\s+|accordingly\s+)*(?:follow|follows|followed)\b(?P<rest>[^.]{{0,260}})", re.I),
    "distinguished": re.compile(rf"\b{SPEAKER}\s+(?:have\s+|therefore\s+|accordingly\s+)*distinguish(?:ed|es)?\b(?P<rest>[^.]{{0,260}})", re.I),
}
TARGET = [
    re.compile(r"(?:view|decision|judgment|judgement|ruling|holding|ratio|law\s+laid\s+down|opinion)\s+(?:expressed\s+|rendered\s+|taken\s+|laid\s+down\s+|given\s+)?(?:in|by)\s+(?P<t>(?:\b(?:vs?|Ltd|Co|Pvt|Corp|Inc|Dr|Smt|Shri|Anr|Ors|Nos?)\.|[^,;.()]){3,140}?)(?=\s*(?:\(supra\)|\(|,|;|\.|\s+to\s+|\s+in\s+so|$))", re.I),
    re.compile(r"(?:\bin\s+|,\s*)(?P<t>[A-Z][A-Za-z.&'\- ]{1,60}?\s+(?:v\.|vs\.?|versus)\s+[A-Z][A-Za-z.&'\- ]{1,60}?)(?=\s*[(,]|\s+\(supra\)|\.?$)"),
    re.compile(r"(?P<t>[A-Z][\w.&'\- ]{2,60}?)\s*\(supra\)"),
]
APPEAL = re.compile(
    r"(?:aris(?:ing|es|e)\s+out\s+of|against|challenging|assailing)\s+(?:the\s+)?(?:impugned\s+|final\s+|common\s+)?(?:judgment|order)(?:\s+and\s+(?:final\s+)?(?:judgment|order))?"
    r"(?:\s+dated\s+(?P<date>\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Z][a-z]+,?\s+\d{4}))?\s+(?:passed|rendered|made|delivered|pronounced)\s+by\s+(?:the\s+)?"
    r"(?P<court>(?:Hon'ble\s+)?High\s+Court\s+of\s+[A-Z][A-Za-z ]{2,40}?(?:\s+at\s+[A-Z][a-z]+)?|(?:Hon'ble\s+)?Supreme\s+Court(?:\s+of\s+India)?|[A-Z][A-Za-z ]{3,50}?(?:Tribunal|Commission))"
    r"\s+in\s+(?P<ref>(?:\bNos?\.|[^,;.]){3,100}?\d{4})")
CNR = re.compile(r"\b[A-Z]{4}\d{12}\b")
JUDGMENT_WORD = re.compile(r"\b(?:judgments?|judgements?|decisions?|views?|rulings?|reasoning|holdings?|precedents?|cases?|authorit(?:y|ies))\b", re.I)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sentence(text: str, a: int, b: int) -> tuple[int, int]:
    """Bounds of the sentence around text[a:b]: back to the previous full stop that really ends a sentence (not "No." or an initial), forward to the next one."""
    start = max(0, a - 400)
    i = a
    while i > start:
        i = text.rfind(".", start, i)
        if i == -1:
            break
        if text[i + 1 : i + 2] in (" ", "\n") and not ABBREV.search(text[max(0, i - 8) : i + 1]):
            start = i + 1
            break
        i -= 1
    else:
        start = max(0, a - 250)
    end = b
    while True:
        j = text.find(".", end, min(len(text), b + 300))
        if j == -1:
            end = min(len(text), b + 300)
            break
        if text[j + 1 : j + 2] in (" ", "\n", "") and not ABBREV.search(text[max(0, j - 8) : j + 1]):
            end = j + 1
            break
        end = j + 1
    return start, end


def _target(rest: str, sentence: str) -> str | None:
    for src in (rest, sentence):
        for rx in TARGET:
            m = rx.search(src)
            if m:
                return re.sub(r"\s+", " ", m.group("t")).strip(" ,;")
    return None


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def extract(text: str) -> list[dict]:
    """Clear statements by the court about another judgment or about the order appealed from. Each: {relation, target_ref, quote}. Skips anything uncertain."""
    out, seen = [], set()

    def add(rel: str, target: str, a: int, b: int) -> None:
        s, e = _sentence(text, a, b)
        quote = _clean(text[s:e])
        if not quote or len(quote) > MAX_QUOTE:
            return
        key = (rel, target, quote)
        if key not in seen:
            seen.add(key)
            out.append({"relation": rel, "target_ref": target, "quote": quote})

    for rel, rx in VERB.items():
        for m in rx.finditer(text):
            s, e = _sentence(text, m.start(), m.end())
            sentence = _clean(text[s:e])
            if SKIP.search(sentence):
                continue
            tail = _clean(text[m.start() : e])  # the rest of the sentence after the court says it (a full stop inside "v." or "No." must not cut it)
            target = _target(tail, sentence)
            if rel in ("followed", "distinguished") and not target:
                continue  # "we follow the procedure" is not a statement about another judgment
            if rel == "overruled" and not (target or JUDGMENT_WORD.search(tail)):
                continue  # "we overrule the preliminary objections" rules on an objection, not on a judgment
            add(rel, target or "", m.start(), m.end())
    for m in APPEAL.finditer(text):
        s, e = _sentence(text, m.start(), m.end())
        if re.search(r"\b(?:submit(?:s|ted)?|contend(?:s|ed)?|argu(?:e|es|ed)|counsel)\b", text[s:e], re.I):
            continue
        ref = _clean(m.group("ref"))
        target = f"{_clean(m.group('court'))}: {ref}" + (f", order dated {m.group('date')}" if m.group("date") else "")
        add("appeal_from", target, m.start(), m.end())
    return out


def cnr_in(text: str) -> str | None:
    found = set(CNR.findall(text or ""))
    return next(iter(found)) if len(found) == 1 else None  # two different CNRs in one statement: nothing is linked


async def resolve_target(target_ref: str) -> str | None:
    """Link a target to a loaded judgment only by a CNR that matches exactly one record. Anything else stays "as written": a case number alone is shared by many cases."""
    cnr = cnr_in(target_ref)
    if not cnr:
        return None
    rows = await db.hc_judgments.find({"cnr": cnr}, {"id": 1}).limit(2).to_list(2)
    return rows[0]["id"] if len(rows) == 1 else None


def now() -> datetime:
    return datetime.now(timezone.utc)


async def store(from_id: str, items: list[dict], text_sha256: str) -> int:
    """Record found relations (UNVERIFIED). The same statement is never stored twice. Returns how many were new."""
    new = 0
    for it in items:
        if it["relation"] not in RELATIONS:
            continue
        qsha = sha256(it["quote"])
        if await db.judgment_relations.find_one({"from_id": from_id, "relation": it["relation"], "quote_sha256": qsha}, {"id": 1}):
            continue
        await vstore.create(db, "judgment_relations", {
            "id": str(uuid.uuid4()), "from_id": from_id, "relation": it["relation"], "target_ref": it.get("target_ref", ""), "target_id": await resolve_target(f"{it.get('target_ref', '')} {it['quote']}"),
            "quote": it["quote"], "quote_sha256": qsha, "source": "stated in the judgment's own text", "method": METHOD, "from_text_sha256": text_sha256,
            "status": STATUS_UNVERIFIED, "reviewed_by": None, "reviewed_on": None, "rejected_reason": None, "created_at": now()})
        new += 1
    return new


def present(r: dict, later: bool = False) -> dict:
    return {
        "id": r["id"], "relation": r["relation"], "label": (LATER_LABEL if later else LABEL)[r["relation"]], "from_id": r["from_id"], "target_ref": r.get("target_ref", ""), "target_id": r.get("target_id"),
        "quote": r["quote"], "source": r["source"], "status": r["status"], "verified": r["status"] == STATUS_REVIEWED, "reviewed_by": r.get("reviewed_by"), "reviewed_on": r.get("reviewed_on"),
        "source_url": r.get("source_url", ""), "method": r.get("method", ""),
        "note": ("Reviewed: a named reviewer compared this with the judgment." if r["status"] == STATUS_REVIEWED else "Not reviewed: found by fixed rules in the judgment's text and not compared with it by a person."),
    }


async def history(judgment_id: str) -> dict:
    """What is recorded about one judgment: relations its own text states, and relations later judgments state about it (only where the later one names this case's CNR). Rejected ones are left out."""
    own = [present(r) async for r in db.judgment_relations.find({"from_id": judgment_id, "status": {"$ne": "REJECTED"}}).sort("created_at", 1)]
    later = [present(r, later=True) async for r in db.judgment_relations.find({"target_id": judgment_id, "status": {"$ne": "REJECTED"}}).sort("created_at", 1)]
    out = {"judgment_id": judgment_id, "stated_in_this_judgment": own, "stated_by_later_judgments": later, "known": bool(own or later), "limit": LIMIT}
    if not (own or later):
        out["message"] = NOT_KNOWN
    return out


async def add_manual(from_id: str, relation: str, target_ref: str, source_note: str, source_url: str, entered_by: str) -> dict:
    """A named person records a relation and the source they relied on. It is UNVERIFIED until a reviewer approves it."""
    if relation not in RELATIONS:
        raise ValueError(f"relation must be one of {', '.join(RELATIONS)}.")
    if len((entered_by or "").strip()) < 5:
        raise ValueError("Give your full name.")
    note = (source_note or "").strip()
    if len(note) < 20:
        raise ValueError("Quote or describe the source that states this (at least 20 characters).")
    if not await db.hc_judgments.find_one({"id": from_id}, {"id": 1}):
        raise ValueError("Unknown judgment.")
    ref = (target_ref or "").strip()
    if len(ref) < 3:
        raise ValueError("Say which case or order it concerns, as the source writes it.")
    row = {"id": str(uuid.uuid4()), "from_id": from_id, "relation": relation, "target_ref": ref[:300], "target_id": await resolve_target(f"{ref} {note}"), "quote": note[:MAX_QUOTE], "quote_sha256": sha256(note[:MAX_QUOTE]),
           "source": f"entered by {entered_by.strip()[:120]}", "source_url": (source_url or "").strip()[:500], "method": "manual", "from_text_sha256": None, "status": STATUS_UNVERIFIED,
           "reviewed_by": None, "reviewed_on": None, "rejected_reason": None, "created_at": now()}
    await vstore.create(db, "judgment_relations", row)
    return present(row)


def _name_and_day(reviewer: str, on: str) -> tuple[str, str]:
    if len((reviewer or "").strip()) < 5:
        raise ValueError("Give the reviewer's full name.")
    try:
        return reviewer.strip(), date.fromisoformat(str(on)).isoformat()
    except ValueError as exc:
        raise ValueError("Give the date of the review as YYYY-MM-DD.") from exc


async def _source_link(r: dict) -> str:
    """Where the sentence can be read: the court PDF of the judgment it was found in, else the written source the person who entered it gave, else the judgment's id."""
    j = await db.hc_judgments.find_one({"id": r["from_id"]}, {"source_url": 1}) or {}
    return (j.get("source_url") or "").strip() or str(r.get("source") or "").strip() or f"judgment {r['from_id']}"


async def review(relation_id: str, reviewer: str, on: str) -> dict:
    """A named reviewer compared the relation with the judgment. For a relation found in a judgment's text, the quoted sentence must still be in that text (unchanged since it was read)."""
    name, day = _name_and_day(reviewer, on)
    r = await db.judgment_relations.find_one({"id": relation_id})
    if not r:
        raise ValueError("Unknown relation.")
    if r["status"] == "REJECTED":
        raise ValueError("This relation was rejected, so it cannot be approved.")
    if r.get("method") == METHOD:
        j = await db.hc_judgments.find_one({"id": r["from_id"]}, {"text": 1, "text_sha256": 1, "source_url": 1})
        if not j or not j.get("text"):
            raise ValueError("The judgment's text is not loaded, so the quoted sentence cannot be checked.")
        if r.get("from_text_sha256") and j.get("text_sha256") != r["from_text_sha256"]:
            raise ValueError("The judgment's text has changed since this was read from it. Read it again before approving.")
        if find_quote(r["quote"], [j["text"]]) is None:
            raise ValueError("The quoted sentence is not found in the judgment's text, so it cannot be approved.")
    await vstore.record_review(db, "judgment_relations", relation_id, "reviewed", name, day, await _source_link(r))
    return present(await db.judgment_relations.find_one({"id": relation_id}))


async def reject(relation_id: str, reviewer: str, on: str, reason: str) -> dict:
    name, day = _name_and_day(reviewer, on)
    if len((reason or "").strip()) < 10:
        raise ValueError("Say what is wrong with this relation.")
    r = await db.judgment_relations.find_one({"id": relation_id})
    if not r:
        raise ValueError("Unknown relation.")
    await vstore.record_review(db, "judgment_relations", relation_id, "rejected", name, day, await _source_link(r), reason=reason)
    return {**present(await db.judgment_relations.find_one({"id": relation_id})), "rejected_reason": reason.strip()[:1000]}


async def queue(status: str = "UNVERIFIED", skip: int = 0, limit: int = 25) -> dict:
    flt = {"UNVERIFIED": {"status": STATUS_UNVERIFIED}, "REVIEWED": {"status": STATUS_REVIEWED}, "REJECTED": {"status": "REJECTED"}}.get(status.upper(), {"status": STATUS_UNVERIFIED})
    rows, total = [], await db.judgment_relations.count_documents(flt)
    async for r in db.judgment_relations.find(flt).sort("created_at", 1).skip(skip).limit(limit):
        j = await db.hc_judgments.find_one({"id": r["from_id"]}, {"case_title": 1, "court_name": 1, "decision_date": 1, "source_url": 1})
        rows.append({**present(r), "case_title": (j or {}).get("case_title"), "court_name": (j or {}).get("court_name"), "decision_date": (j or {}).get("decision_date"), "judgment_url": (j or {}).get("source_url")})
    return {"items": rows, "total": total}
