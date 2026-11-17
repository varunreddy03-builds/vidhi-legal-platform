"""Finds drafting slips in a draft, page by page, for the 'Pre-filing defect check'.

This only READS the draft. It knows no court's rules: it cannot say a filing will be accepted or rejected, and it never corrects anything. It points to places a person should look:
blanks and placeholders left unfilled, paragraph numbers that skip or repeat, an annexure series with a label missing, a reference to a paragraph that is not there, and a word typed twice.
Every finding says in neutral words why it may not be a slip at all."""

import re
from dataclasses import dataclass

from lib.refcheck.citations import _sentence_at

ENOUGH = 1001  # a report holds at most 1000 findings and refuses more, so past this point no more sentences are cut out and no more pages are read

BLANKS = [
    (re.compile(r"_{3,}"), "A blank line is left in the text."),
    (re.compile(r"\[\s*(?:_+|\.{2,}|●|•|\*+|x{2,})?\s*\]"), "Empty square brackets are left in the text."),
    (re.compile(r"\[\s*(?:insert|name|date|amount|address|to be filled|tbd|your|enter|fill)[^\]]{0,60}\]", re.I), "A bracketed placeholder is left in the text."),
    (re.compile(r"<<[^>]{1,60}>>"), "A placeholder in double angle brackets is left in the text."),
    (re.compile(r"\bTBD\b|\bX{4,}\b"), "A placeholder (TBD or XXXX) is left in the text."),
    (re.compile(r"\.{6,}|…{3,}"), "A long dotted line is left in the text."),
]
BLANK_NOTE = " Some blanks are meant to be filled by hand after printing."
PARA_LINE = re.compile(r"^[ \t]*(\d{1,3})[.)][ \t]+\S", re.M)
ANNEXURE = re.compile(r"\b(?:Annexure|Annex\.?|Exhibit)[-\s]*(?P<prefix>[A-Z]{1,3})?[-\s]*(?P<num>\d{1,3})\b")
PARA_REF = re.compile(r"\b(?:paragraphs?|paras?\.?)\s+(?P<a>\d{1,3})(?:\s*(?:to|-|–|and)\s*(?P<b>\d{1,3}))?", re.I)
OTHER_DOC = re.compile(r"^\s*(?:,\s*)?(?:of|in)\s+(?:the|this|that|his|her|their|its)?\s*\w+", re.I)
REPEAT = re.compile(r"\b(?P<w>[A-Za-z]{2,})\s+(?P=w)\b", re.I)
ALLOWED_REPEATS = {"that", "had"}


@dataclass
class Finding:
    kind: str  # blank | numbering_gap | numbering_repeat | annexure_gap | dangling_reference | repeated_word
    raw: str  # the text it points to, exactly as written
    page: int  # 1-based page (or slice) of the draft
    sentence: str  # the sentence around it
    note: str  # plain words: what to look at, and why it may not be a slip
    start: int = 0  # position in the page text, for reading order


def _add(out: list[Finding], text: str, page: int, m_start: int, m_end: int, kind: str, raw: str, note: str) -> None:
    out.append(Finding(kind=kind, raw=" ".join(raw.split())[:120], page=page, sentence=_sentence_at(text, m_start, m_end) if len(out) < ENOUGH else "", note=note, start=m_start))


def check(pages: list[str]) -> list[Finding]:
    """Every slip found, in reading order (page by page)."""
    out: list[Finding] = []
    numbered: list[tuple[int, int, int, int]] = []  # (paragraph number, page, start, end), in reading order
    annex: dict[str, dict[int, tuple[int, int, int]]] = {}  # prefix -> number -> (page, start, end) of its first mention

    for page, text in enumerate(pages, 1):
        if len(out) >= ENOUGH:
            break
        text = text or ""
        taken: list[tuple[int, int]] = []
        for rx, note in BLANKS:
            for m in rx.finditer(text):
                if any(m.start() < e and s < m.end() for s, e in taken):
                    continue
                taken.append(m.span())
                _add(out, text, page, m.start(), m.end(), "blank", m.group(0), note + BLANK_NOTE)
        for m in PARA_LINE.finditer(text):
            numbered.append((int(m.group(1)), page, m.start(1), m.end(1)))
        for m in ANNEXURE.finditer(text):
            annex.setdefault((m["prefix"] or "").upper(), {}).setdefault(int(m["num"]), (page, m.start(), m.end()))
        for m in REPEAT.finditer(text):
            if m["w"].lower() in ALLOWED_REPEATS:
                continue
            _add(out, text, page, m.start(), m.end(), "repeated_word", m.group(0), f"The word “{m['w']}” appears twice in a row. Some repeats are correct.")

    prev = None
    for n, page, s, e in numbered:
        text = pages[page - 1] or ""
        if prev is not None and n == prev:
            _add(out, text, page, s, e, "numbering_repeat", str(n), f"Paragraph number {n} appears twice in a row.")
        elif prev is not None and n > prev + 1:
            missing = f"{prev + 1}" if n == prev + 2 else f"{prev + 1} to {n - 1}"
            _add(out, text, page, s, e, "numbering_gap", f"{prev} → {n}", f"The numbered paragraphs go from {prev} to {n}, so {missing} may be missing. A section may use a different list on purpose.")
        prev = n

    for prefix, found in annex.items():
        top = max(found)
        label = lambda k: f"Annexure {prefix + '-' if prefix else ''}{k}"  # noqa: E731
        for k in range(1, top):
            if k not in found:
                page, s, e = found[min(x for x in found if x > k)]
                _add(out, pages[page - 1] or "", page, s, e, "annexure_gap", label(k),
                     f"{label(k)} is not mentioned, although {label(top)} is. It may be mentioned in another document.")

    highest = max((n for n, *_ in numbered), default=0)
    if len(numbered) >= 3:  # only when the draft really numbers its paragraphs
        for page, text in enumerate(pages, 1):
            for m in PARA_REF.finditer(text or ""):
                if OTHER_DOC.match((text or "")[m.end():m.end() + 40]):
                    continue  # "paragraph 24 of the judgment" is about another document
                top = int(m["b"] or m["a"])
                if top > highest:
                    _add(out, text or "", page, m.start(), m.end(), "dangling_reference", m.group(0),
                         f"This refers to paragraph {top}, but the highest numbered paragraph found is {highest}. It may refer to another document.")
    out.sort(key=lambda f: (f.page, f.start))
    return out
