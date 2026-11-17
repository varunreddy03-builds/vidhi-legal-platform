"""Audiovisual case-study catalogue (Phase 11). A film is a story: never evidence, never a study, never a precedent, never a verified account of real events.

Reads data/knowledge/films.json. Nothing has been watched, transcribed or obtained, so every entry says so; `check()` is what the tests (and a reviewer) run to make sure no entry
claims otherwise without a recorded source. The exercises are written for VIDHI and do not reproduce any film's content."""

import json
import re
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "data" / "knowledge" / "films.json"
LABEL = "Fictional or dramatised story for discussion. Not evidence, not a study, not a legal precedent, not a verified account of real events."
_FACT_WORDS = re.compile(r"\b(proves?|proved|proof|precedent|binding|authority|as a matter of law|establishes? (?:that|the legal rule|the rule)|the court held|settled law|shows? that the law)\b", re.I)

# Only wording that is ABOUT the film being a story counts as a denial ("it is fiction and proves nothing"); a stray "no" or "not" elsewhere in the sentence does not.
_DENIES = re.compile(r"\b(?:is|are)\s+(?:a\s+|an\s+)?(?:fiction|fictional|story|drama|dramati[sz]ation|dramati[sz]ed)\b|\bproves?\s+nothing\b|\bnot\s+(?:a\s+|an\s+)?(?:evidence|proof|precedent|authority|source of law|legal authority|binding)\b|\bcannot\s+be\s+(?:used|treated|cited)\b|\bshould\s+not\s+be\s+(?:used|treated|cited)\b|\bonly a story\b|\bmerely a story\b|\bis not a source\b", re.I)


def _load() -> dict:
    return json.loads(FILE.read_text(encoding="utf-8"))


def catalogue() -> dict:
    d = _load()
    films = []
    for f in d["films"]:
        films.append({**d["defaults"], **f, "category_name": d["categories"][f["category"]], "label": LABEL})
    return {"note": d["note"], "count": len(films), "films": films, "categories": d["categories"]}


def exercises() -> dict:
    d = _load()
    return {"label": "Every scenario is FICTIONAL and written for VIDHI; none is taken from a film.", "exercises": d["exercises"]}


def titles() -> list[str]:
    return [f["title"] for f in _load()["films"]]


def check() -> list[str]:
    """Problems with the catalogue (empty list = fine). An entry may claim a source was obtained or reviewed only if it also names where."""
    d, problems = _load(), []
    seen = set()
    for f in d["films"]:
        full = {**d["defaults"], **f}
        if f["id"] in seen:
            problems.append(f"duplicate id {f['id']}")
        seen.add(f["id"])
        if not (1900 < int(f["year"]) < 2100) or f["category"] not in d["categories"]:
            problems.append(f"{f['id']}: bad year or category")
        if full["source_obtained"] and not f.get("source_note"):
            problems.append(f"{f['id']}: says a source was obtained but names none")
        if full["reviewed"] and not f.get("reviewer"):
            problems.append(f"{f['id']}: says reviewed but names no reviewer")
        if full["availability"]["transcript"].startswith("licensed") and not f.get("source_note"):
            problems.append(f"{f['id']}: claims a licensed transcript without a source")
    return problems


def film_as_fact(sentence: str) -> str | None:
    """The title of a catalogued film if the sentence uses it as proof, precedent or authority; otherwise None."""
    if not _FACT_WORDS.search(sentence) or _DENIES.search(sentence):
        return None
    low = sentence.lower()
    for t in titles():
        if len(t) > 5 and t.lower() in low:  # 'Court' and 'Pink' are too ordinary to match alone
            return t
    for t, year in (("Court", 2014), ("Pink", 2016)):
        if re.search(rf"\b{t}\b\s*\(?{year}\)?", sentence):
            return t
    if re.search(r"\bPink\s+(?:is|was|proves?|shows?|establishes?|as)\b", sentence):  # bare 'Pink' only when it is the subject of a claim
        return "Pink"
    return None
