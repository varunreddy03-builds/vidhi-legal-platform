"""Conflict-of-interest check: does a name already appear in this firm's own VIDHI records?

It compares names, nothing more. What it searches (this organisation only): the parties and title of every matter, the people found in matter documents
(with their stated role), and the creditor and debtor of every recovery case. What it CANNOT know: anything not entered in VIDHI, relationships between
people, other firms' records, or a name spelled in a way it does not recognise. "No match" is therefore never a clearance, and a match is not a conflict:
a lawyer decides. The answer says this every time.

Matching (pure code, no AI): names are lower-cased and cleaned, honorifics (Mr, Smt, Shri, Dr, Adv, M/s ...) and company words (Pvt, Ltd, LLP ...) are ignored,
word order does not matter, an initial matches the full word ("R Kumar" ~ "Ramesh Kumar"), and small spelling differences are tolerated. Indian scripts are compared as
they are written (the same name in two scripts is not recognised: search each spelling).
Strength:  strong = same words (or only honorifics/company words differ);  possible = most words match, with initials or a small spelling difference;
           weak = a single shared word (for example a surname)."""

import re
import unicodedata
from difflib import SequenceMatcher

from lib.db import db

HONORIFICS = {"mr", "mrs", "ms", "miss", "mx", "shri", "shree", "sri", "sh", "smt", "kumari", "km", "dr", "adv", "advocate", "prof", "messrs", "m/s", "late"}
COMPANY = {"pvt", "private", "ltd", "limited", "llp", "inc", "corp", "corporation", "company", "co", "llc", "plc", "the", "and", "&"}
LIMIT_ROWS = 20000
STRENGTH_ORDER = {"strong": 0, "possible": 1, "weak": 2}
NOTICE = (
    "This compares names with what is entered in VIDHI for your organisation only (matter parties and titles, people found in documents, recovery cases). "
    "No match does NOT mean there is no conflict: names can be spelled differently, and anything outside VIDHI is not checked. "
    "A match is not necessarily a conflict. A lawyer decides."
)


def tokens(name: str) -> list[str]:
    text = unicodedata.normalize("NFKC", name).casefold().replace("m/s", " ")
    text = "".join(ch if unicodedata.category(ch)[0] in "LNM" else " " for ch in text)  # letters, digits and combining marks (Indian vowel signs) stay
    words = [w for w in text.split() if w]
    kept = [w for w in words if w not in HONORIFICS and w not in COMPANY]
    return kept or words


def _same_word(a: str, b: str) -> bool:
    if a == b:
        return True
    if (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b)):
        return True
    return len(a) >= 4 and len(b) >= 4 and abs(len(a) - len(b)) <= 2 and SequenceMatcher(None, a, b).ratio() >= 0.85


def compare(query: list[str], cand: list[str]) -> tuple[str, str] | None:
    """(strength, reason) or None."""
    if not query or not cand:
        return None
    if sorted(query) == sorted(cand):
        return "strong", "same words" if query != cand else "same name"
    short, long_ = (query, cand) if len(query) <= len(cand) else (cand, query)
    pool, matched, exact = list(long_), 0, 0
    for w in short:
        hit = next((x for x in pool if x == w), None) or next((x for x in pool if _same_word(w, x)), None)
        if hit:
            pool.remove(hit)
            matched += 1
            exact += hit == w
    if len(short) >= 2 and matched == len(short):
        if len(short) == len(long_):
            return "possible", "same words apart from initials or small spelling differences"
        return "possible", "all the words of the shorter name appear in the longer one"
    if len(query) == 1 or len(cand) == 1:
        if matched == 1 and len(short) == 1:
            return "weak", "one shared word"
    elif matched >= 1 and exact >= 1:
        return "weak", "some words are shared"
    return None


SEPARATOR_WORDS = {"v", "v.", "vs", "vs.", "versus", "and", "&"}
MAX_PARTIES_CHARS = 5000


def parts(text: str) -> list[str]:
    """Names in a parties / title field. Split on commas, semicolons, lines and the words v / vs / versus / and (word by word, so a long run of spaces costs nothing)."""
    out: list[str] = []
    for chunk in re.split(r"[,;\n]+", (text or "")[:MAX_PARTIES_CHARS]):
        cur: list[str] = []
        for w in chunk.split():
            if w.lower() in SEPARATOR_WORDS:
                if cur:
                    out.append(" ".join(cur))
                cur = []
            else:
                cur.append(w)
        if cur:
            out.append(" ".join(cur))
    return [p for p in (x.strip() for x in out) if len(p) >= 2]


async def check(org: str, names: list[str]) -> dict:
    queries = [(n, tokens(n)) for n in names]
    rows: list[dict] = []  # every name the firm has on record: {text, source, ...}
    matters = await db.matters.find({"organization_id": org}, {"id": 1, "title": 1, "parties": 1, "status": 1}).limit(LIMIT_ROWS).to_list(LIMIT_ROWS)
    titles = {m["id"]: m["title"] for m in matters}
    status = {m["id"]: m.get("status", "OPEN") for m in matters}
    for m in matters:
        for p in parts(m.get("parties", "")):
            rows.append({"text": p, "source": "Matter parties", "matter_id": m["id"]})
        for p in parts(m.get("title", "")):
            rows.append({"text": p, "source": "Matter title", "matter_id": m["id"]})
    ents = await db.entities.find({"organization_id": org}, {"matter_id": 1, "name": 1, "aliases": 1, "role": 1}).limit(LIMIT_ROWS).to_list(LIMIT_ROWS)
    for e in ents:
        for n in [e.get("name", ""), *(e.get("aliases") or [])]:
            if n:
                rows.append({"text": n, "source": "Person in a matter" + (f" ({e['role']})" if e.get("role") and e["role"] != "not stated" else ""), "matter_id": e.get("matter_id")})
    cases = await db.recovery_cases.find({"organization_id": org}, {"id": 1, "creditor_name": 1, "debtor_name": 1, "status": 1}).limit(LIMIT_ROWS).to_list(LIMIT_ROWS)
    for c in cases:
        for field, role in (("creditor_name", "creditor"), ("debtor_name", "debtor")):
            if c.get(field):
                rows.append({"text": c[field], "source": f"Recovery case ({role})", "case_id": c["id"], "case_label": f"{c.get('creditor_name', '')} → {c.get('debtor_name', '')}", "case_status": c.get("status", "")})
    prepared = [(r, tokens(r["text"])) for r in rows]
    results = []
    for original, qt in queries:
        found, seen = [], set()
        for r, ct in prepared:
            verdict = compare(qt, ct)
            if not verdict:
                continue
            key = (r["text"].casefold(), r["source"], r.get("matter_id"), r.get("case_id"))
            if key in seen:
                continue
            seen.add(key)
            mid = r.get("matter_id")
            found.append({
                "strength": verdict[0], "reason": verdict[1], "source": r["source"], "matched_text": r["text"],
                "matter_id": mid, "matter_title": titles.get(mid), "matter_status": status.get(mid),
                "case_id": r.get("case_id"), "case_label": r.get("case_label"), "case_status": r.get("case_status"),
                "href": f"/matters/{mid}" if mid else (f"/recovery/cases/{r['case_id']}" if r.get("case_id") else None),
            })
        found.sort(key=lambda m: (STRENGTH_ORDER[m["strength"]], m["matched_text"].casefold()))
        results.append({"name": original, "matches": found[:100], "total_matches": len(found)})
    return {
        "results": results, "notice": NOTICE,
        "searched": {"matters": len(matters), "people_in_matters": len(ents), "recovery_cases": len(cases)},
        "truncated": any(n >= LIMIT_ROWS for n in (len(matters), len(ents), len(cases))),
    }