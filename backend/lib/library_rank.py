"""Ranking of verified library entries for a question. Pure code: no database, no model, nothing here can say anything the entries do not.

`rank(question, entries, k)` returns at most k of the given entries, best first. It never adds an entry, never edits one and never changes a status, so the rule that only VERIFIED entries can be
cited is kept by the caller (lib/library.find_relevant passes only VERIFIED entries).

How an entry scores:
  * an exact citation (or alias) named in the question, as whole words, puts that entry first: "section 1 of the Fictional Widget Testing Act, 2000";
  * otherwise each word the question shares with the entry counts, more for a word in the citation, title or aliases than for one in the text, and more for a rare word than for a common one
    (a word found in every entry says nothing about which entry fits);
  * plural and simple verb endings are ignored, so "widgets" meets "widget" and "borrowed" meets "borrow" (scoring only; the quote check that makes a claim VERIFIED never uses this).
  * an entry that shares ONLY words found in more than half of all the entries (everyday words such as "must" or "be") is left out unless its citation is named: it is no evidence that the entry is about the question.
Equal scores keep the entries' order, so the result is the same every time."""

import math
import re

from lib import text as _text

MIN_ENTRIES_FOR_EVIDENCE_RULE = 3
HEAD_WEIGHT = 3.0
EXACT_BONUS = 1000.0
_ENDINGS = ("ies", "ing", "ed", "es", "s")


def stem(word: str) -> str:
    """A light, rule-based stem for Latin words of five or more letters; words in other scripts are left as they are."""
    if len(word) < 5 or not word.isascii():
        return word
    for end in _ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 3:
            return word[: -len(end)] + ("y" if end == "ies" else "")
    return word


def _terms(s: str) -> set[str]:
    return {stem(w) for w in _text.tokens(s)}


def _norm_phrase(s: str) -> str:
    from lib.library import norm_citation

    return norm_citation(s)


def _named_in(question_norm: str, keys: list[str]) -> bool:
    for key in keys:
        k = (key or "").strip()
        if len(k) >= 6 and re.search(rf"(?<!\w){re.escape(k)}(?!\w)", question_norm):
            return True
    return False


def rank(question: str, entries: list[dict], k: int = 8) -> list[dict]:
    q = _terms(question)
    question_norm = _norm_phrase(question)
    if not entries or (not q and not question_norm):
        return []
    heads = [_terms(f"{e.get('citation', '')} {e.get('title', '')} {' '.join(e.get('aliases', []) or [])}") for e in entries]
    bodies = [_terms(e.get("text", "")) for e in entries]
    n = len(entries)
    df: dict[str, int] = {}
    for h, b in zip(heads, bodies):
        for t in h | b:
            df[t] = df.get(t, 0) + 1

    def weight(t: str) -> float:
        return math.log(1.0 + n / df[t]) if t in df else 0.0

    def specific(t: str) -> bool:
        """A word that tells entries apart: found in at most half of them. With fewer than three entries nothing can be said, so every word counts."""
        return n < MIN_ENTRIES_FOR_EVIDENCE_RULE or df.get(t, 0) <= max(1, n / 2)

    scored = []
    for i, e in enumerate(entries):
        keys = [e.get("citation", ""), *(e.get("aliases", []) or []), *(e.get("keys", []) or [])]
        exact = _named_in(question_norm, [_norm_phrase(x) for x in keys if x])
        score = sum(HEAD_WEIGHT * weight(t) for t in q & heads[i]) + sum(weight(t) for t in (q & bodies[i]) - heads[i])
        if exact:
            score += EXACT_BONUS
        shared = q & (heads[i] | bodies[i])
        if not exact and not any(specific(t) for t in shared):  # only everyday words in common ("must", "be"): no evidence that this entry is about the question
            continue
        if score > 0:
            scored.append((-score, i, e))
    scored.sort(key=lambda r: (r[0], r[1]))
    return [e for _, _, e in scored[:k]]
