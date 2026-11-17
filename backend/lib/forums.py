"""Forums (courts, tribunals, authorities) and the remedies each offers, entered by the operator from official sources and reviewed by a named lawyer.

This is a registry, not knowledge: it ships EMPTY. VIDHI does not know which court can issue which writ or hear which kind of dispute; it only repeats what a person
loaded and a lawyer reviewed. Each record carries where the information came from. Any edit sends the record back to unreviewed. A chain of appeal is followed only through the
parent links that were entered, and is called verified only if every forum on it has been reviewed."""

import uuid
from datetime import date, datetime, timezone

from lib import verified_store as store
from lib.db import db

KINDS = ("court", "tribunal", "forum", "authority")
LEVELS = ("apex", "high", "district", "subordinate", "tribunal", "other")
NOT_REVIEWED = "Not reviewed: entered from a source and not yet compared with it by a lawyer. Do not rely on it."
LIMIT = "Which forum can actually hear a matter, and what it can order, depends on the facts and the law in force; a lawyer must decide."


def now() -> datetime:
    return datetime.now(timezone.utc)


def _text(d: dict, key: str, low: int, high: int, required: bool = False) -> str:
    v = str(d.get(key) or "").strip()
    if required and len(v) < low:
        raise ValueError(f"{key.replace('_', ' ').capitalize()} must be at least {low} characters.")
    if len(v) > high:
        raise ValueError(f"{key.replace('_', ' ').capitalize()} is too long.")
    return v


def _clean(d: dict) -> dict:
    kind, level = str(d.get("kind") or "").lower(), str(d.get("level") or "other").lower()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}.")
    if level not in LEVELS:
        raise ValueError(f"level must be one of {', '.join(LEVELS)}.")
    remedies = []
    for r in d.get("remedies") or []:
        name = str((r or {}).get("name") or "").strip()
        if not name or len(name) > 200:
            raise ValueError("Each remedy needs a name of up to 200 characters.")
        remedies.append({"name": name, "provision_ref": str(r.get("provision_ref") or "").strip()[:200], "note": str(r.get("note") or "").strip()[:500]})
    if len(remedies) > 40:
        raise ValueError("Too many remedies on one forum.")
    return {"name": _text(d, "name", 3, 200, True), "kind": kind, "level": level, "territorial": _text(d, "territorial", 0, 500), "subject": _text(d, "subject", 0, 500),
            "pecuniary": _text(d, "pecuniary", 0, 500), "remedies": remedies, "source_note": _text(d, "source_note", 10, 1000, True), "parent_id": d.get("parent_id") or None}


async def _check_parent(forum_id: str | None, parent_id: str | None) -> None:
    if not parent_id:
        return
    if not await db.forums.find_one({"id": parent_id}):
        raise ValueError("The parent forum does not exist.")
    seen, cur = set(), parent_id
    while cur:
        if cur == forum_id or cur in seen:
            raise ValueError("That parent would make a loop in the chain of appeal.")
        seen.add(cur)
        row = await db.forums.find_one({"id": cur}, {"parent_id": 1})
        cur = row.get("parent_id") if row else None


async def add_forum(d: dict) -> dict:
    row = _clean(d)
    await _check_parent(None, row["parent_id"])
    row.update({"id": str(uuid.uuid4()), "review_status": "unreviewed", "reviewed_by": None, "reviewed_on": None, "created_at": now(), "updated_at": now()})
    await store.create(db, "forums", row)
    return public(row)


async def update_forum(forum_id: str, d: dict) -> dict:
    cur = await db.forums.find_one({"id": forum_id})
    if not cur:
        raise ValueError("Unknown forum.")
    row = _clean({**{k: cur.get(k) for k in ("name", "kind", "level", "territorial", "subject", "pecuniary", "remedies", "source_note", "parent_id")}, **d})
    await _check_parent(forum_id, row["parent_id"])
    row.update({"updated_at": now()})
    await store.restore_review(db, "forums", forum_id, {"review_status": "unreviewed", "reviewed_by": None, "reviewed_on": None})  # an edit always needs a fresh review (reset first: never new text under an old review)
    await store.change(db, "forums", {"id": forum_id}, row)
    return public({**cur, **row, "review_status": "unreviewed", "reviewed_by": None, "reviewed_on": None})


async def review_forum(forum_id: str, reviewer: str, on: str) -> dict:
    cur = await db.forums.find_one({"id": forum_id})
    if not cur:
        raise ValueError("Unknown forum.")
    if len(reviewer.strip()) < 5:
        raise ValueError("Give the reviewer's full name.")
    try:
        day = date.fromisoformat(on).isoformat()
    except ValueError as exc:
        raise ValueError("reviewed_on must be a date like 2026-11-05.") from exc
    await store.record_review(db, "forums", forum_id, "reviewed", reviewer, day, (cur.get("source_note") or "").strip())
    return public({**cur, "review_status": "reviewed", "reviewed_by": reviewer.strip(), "reviewed_on": day})


def public(row: dict) -> dict:
    reviewed = row.get("review_status") == "reviewed"
    out = {k: row.get(k) for k in ("id", "name", "kind", "level", "territorial", "subject", "pecuniary", "remedies", "source_note", "parent_id", "review_status", "reviewed_by", "reviewed_on")}
    out["review_statement"] = f"Compared with the source by {row.get('reviewed_by')} on {row.get('reviewed_on')}." if reviewed else NOT_REVIEWED
    out["limit"] = LIMIT
    return out


async def find_forums(remedy: str | None = None, subject: str | None = None, kind: str | None = None, reviewed_only: bool = False) -> list[dict]:
    q: dict = {}
    if kind:
        q["kind"] = kind.lower()
    if reviewed_only:
        q = {**q, "review_status": "reviewed"}
    rows = [r async for r in db.forums.find(q).sort("name", 1)]
    if remedy:
        w = remedy.strip().lower()
        rows = [r for r in rows if any(w in x["name"].lower() for x in r.get("remedies", []))]
    if subject:
        w = subject.strip().lower()
        rows = [r for r in rows if w in (r.get("subject") or "").lower()]
    return [public(r) for r in rows]


async def appeal_chain(forum_id: str) -> dict | None:
    """The forum and each parent above it, as entered. `verified` only if every forum on the chain has been reviewed."""
    chain, seen, cur = [], set(), forum_id
    while cur and cur not in seen:
        seen.add(cur)
        row = await db.forums.find_one({"id": cur})
        if not row:
            break
        chain.append(row)
        cur = row.get("parent_id")
    if not chain or chain[0]["id"] != forum_id:
        return None
    return {"forum_id": forum_id, "chain": [public(r) for r in chain], "verified": all(r.get("review_status") == "reviewed" for r in chain),
            "note": "This follows the parent links that were entered. " + LIMIT}


async def relation(citing_forum_id: str, cited_forum_id: str) -> dict:
    """Is the cited forum above the citing forum in the entered chain? Says UNKNOWN for everything else: same level, other branch, or not entered."""
    c = await appeal_chain(citing_forum_id)
    if not c:
        return {"relation": "UNKNOWN", "verified": False, "note": "One of the forums is not in the registry."}
    ids = [f["id"] for f in c["chain"]]
    if cited_forum_id in ids[1:]:
        above = ids[: ids.index(cited_forum_id) + 1]
        ok = all(f["review_status"] == "reviewed" for f in c["chain"] if f["id"] in above)
        return {"relation": "CITED_FORUM_IS_ABOVE", "verified": ok, "note": "Whether a decision binds also depends on what it decided and the rules on precedent. A lawyer must check."}
    return {"relation": "UNKNOWN", "verified": False, "note": "The registry does not show the cited forum above the citing one. Nothing is concluded."}
