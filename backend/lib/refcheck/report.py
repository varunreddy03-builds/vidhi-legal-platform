"""Builds an Authority Check report from a draft's pages (Stage 2d). No AI is used anywhere here: the draft is read as data by the reader in citations.py, cases are looked
up by lookup.py through a source, statutes by statutes.py against the reviewed library. Instructions written inside the draft are just text and change nothing.

A report holds, per reference: what the draft wrote, the page and sentence, the label, the reason in plain words, the source link, and a review state a person sets.
Quotes in the draft next to a confirmed case are checked against the judgment (quotes.py); an optional AI step can add a "may not support, please read" caution (propositions.py), never a tick.
It never holds judgment text: the judgment is read in memory for those two steps and dropped. Every report says "current status: not checked": whether a case is still good law is never looked at."""

import os
from collections import Counter

from lib.refcheck import lookup, propositions, quotes, statutes
from lib.refcheck.citations import extract

MAX_REFERENCES = 40
CURRENT_STATUS = "current status: not checked"
REVIEW_ACTIONS = ("fix", "accept_as_is", "reviewed")


def enabled() -> bool:
    return os.environ.get("AUTHORITY_CHECK_ENABLED", "false").lower() == "true"


class TooManyReferences(Exception):
    def __init__(self, n: int):
        super().__init__(n)
        self.n = n


def _case_item(n: int, ref, res: "lookup.Result") -> dict:
    return {
        "n": n, "kind": "case", "raw": ref.raw, "page": ref.page, "sentence": ref.sentence[:600], "label": res.label, "reason": res.reason, "differences": res.differences,
        "source_url": res.source_url, "matched_title": res.matched_title, "confirmed": res.confirmed, "full_search": res.full_search, "checked_at": res.checked_at,
        "attempts": [{"strategy": a.strategy, "query": a.query, "status": a.status, "n": a.n, "at": a.at} for a in res.attempts],
        "old_code_note": "", "current_status": CURRENT_STATUS, "review": {"state": "open"},
        "citation_label": res.label, "quotes": [], "proposition": None,
    }


def _statute_item(n: int, ref, res: "statutes.StatuteResult") -> dict:
    return {
        "n": n, "kind": "statute", "raw": ref.raw, "page": ref.page, "sentence": ref.sentence[:600], "label": res.label, "reason": res.reason, "differences": [],
        "source_url": "", "per_provision": res.per_provision, "old_code_note": res.old_code_note, "current_status": CURRENT_STATUS, "review": {"state": "open"},
    }


def counts(items: list[dict]) -> dict:
    c = Counter(i["label"] for i in items)
    return {"total": len(items), "cases": sum(1 for i in items if i["kind"] == "case"), "statutes": sum(1 for i in items if i["kind"] == "statute"),
            "by_label": dict(c), "open": sum(1 for i in items if i["review"]["state"] == "open"), "old_code_notes": sum(1 for i in items if i.get("old_code_note"))}


def _apply_quote_and_proposition(item: dict, ref, res: "lookup.Result", sentence_cases: int, caution: dict | None) -> None:
    """Adds the quote results and the optional caution to a case item and settles its headline label. Only a case that was FOUND with agreeing details is compared."""
    confirmed = res.label == lookup.FOUND_MATCHES
    if ref.quotes:
        item["quotes"] = quotes.check_all(ref.quotes, res.doc_blocks, confirmed=confirmed, shared_sentence=sentence_cases > 1)
        if item["label"] == lookup.FOUND_MATCHES and quotes.summary_label(item["quotes"]) == quotes.QUOTE_NOT_FOUND:
            item["label"] = quotes.QUOTE_NOT_FOUND
            item["reason"] = "The case was found, but some words the draft quotes were not found in it. " + next(q["reason"] for q in item["quotes"] if q["result"] == quotes.QUOTE_NOT_FOUND)
    item["proposition"] = caution


async def build(pages: list[str], source, *, reserve=None, statute_lookup=None, on_date: str | None = None, proposition=None) -> dict:
    """`proposition`, if given, is an async function (sentence, blocks) -> result dict from propositions.check; it is the opt-in AI step and is asked only for confirmed cases."""
    refs = extract(pages)
    if len(refs) > MAX_REFERENCES:
        raise TooManyReferences(len(refs))
    items = []
    for n, ref in enumerate(refs, 1):
        if ref.kind == "case":
            res = await lookup.check_case(ref, source, reserve=reserve)
            item = _case_item(n, ref, res)
            sentence_cases = sum(1 for r in refs if r.kind == "case" and r.page == ref.page and r.sentence == ref.sentence)
            caution = await proposition(ref.sentence, res.doc_blocks) if (proposition is not None and res.label == lookup.FOUND_MATCHES) else None
            _apply_quote_and_proposition(item, ref, res, sentence_cases, caution)
            if caution and caution.get("state") == "may_not_support" and item["label"] == lookup.FOUND_MATCHES:
                item["label"] = propositions.MAY_NOT_SUPPORT
                item["reason"] = caution["note"]
            res.doc_blocks = []  # the judgment is not kept
            items.append(item)
        else:
            items.append(_statute_item(n, ref, await statutes.check_statute(ref, on_date=on_date, lookup=statute_lookup)))
    attribution = source.attribution() if hasattr(source, "attribution") else None  # "Source: <dataset>, data as of <date>" and the licence credit, when the source has them
    return {"items": items, "counts": counts(items), "current_status": CURRENT_STATUS, "source": getattr(source, "name", ""), "source_attribution": attribution}
