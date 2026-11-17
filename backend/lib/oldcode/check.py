"""Finds references to the older criminal codes in a draft, page by page, for the 'Old-code to new-code checker'.

This only READS the draft. It finds where the Indian Penal Code, the Code of Criminal Procedure or the Indian Evidence Act is named, and the section numbers written next to the name.
It does not know what any section says and does not map one section to another: a mapping comes only from the reviewed store (lib/code_mappings.py), never from this file."""

import re
from dataclasses import dataclass

from lib.refcheck.citations import _sentence_at

ENOUGH = 1001  # a report holds at most 1000 findings and refuses more, so past this point no more sentences are cut out and no more pages are read

ACTS = [  # (key, name shown, how the document may write it)
    ("IPC", "Indian Penal Code", r"(?:Indian\s+Penal\s+Code(?:\s*,?\s*1860)?|I\.?\s?P\.?\s?C\.?)"),
    ("CrPC", "Code of Criminal Procedure", r"(?:Code\s+of\s+Criminal\s+Procedure(?:\s*,?\s*1973)?|Cr\.?\s?P\.?\s?C\.?)"),
    ("IEA", "Indian Evidence Act", r"(?:(?:Indian\s+)?Evidence\s+Act(?:\s*,?\s*1872)?)"),
]
_ACT = "|".join(f"(?P<{k}>{rx})" for k, _, rx in ACTS)
_NUM = r"\d{1,3}(?:\s?-?\s?(?-i:[A-Z]{1,2})\b)?(?:\s*\([^)\n]{1,12}\))*"  # the letter after a number must be a capital: 498A, 304-B (so the word "to" is not one)
_SEP = r"(?:\s*(?:,|/|&|and|to)\s*)"
_LIST = rf"{_NUM}(?:{_SEP}{_NUM})*"
_MARK = r"(?:sections?|secs?\.?|ss\.?|s\.|u/s\.?|under\s+sections?)"
_OF = r"(?:\s*,\s*|\s+)(?:(?:of|in)\s+(?:the\s+)?)?"  # no two \s* side by side: that backtracked quadratically on a long run of spaces
SECTIONS = re.compile(rf"\b{_MARK}\s*(?P<list>{_LIST}){_OF}(?:{_ACT})(?![A-Za-z])", re.I)
MENTION = re.compile(rf"(?<![A-Za-z.])(?:{_ACT})(?![A-Za-z])", re.I)
ONE_NUM = re.compile(r"\d{1,3}(?:\s?-?\s?(?-i:[A-Z]{1,2})\b)?", re.I)
ACT_NAME = {k: n for k, n, _ in ACTS}
NOTE_RANGE = " The text says \"to\" between two sections; the sections between them are not listed here."
NOTE_SECTION = "The draft names this section of the {act}. Check the mapping below, if any, against the official texts."
NOTE_MENTION = "The draft names the {act} without a section number that could be read here."


@dataclass
class Finding:
    kind: str  # section | mention
    act: str  # IPC | CrPC | IEA
    section: str  # canonical form such as 498A or 304B ("" for a mention)
    raw: str  # the words as written
    page: int  # 1-based page (or slice) of the draft
    sentence: str
    note: str
    start: int = 0


def canonical(s: str) -> str:
    """'498-A' and '498 A' and '498a' are the same section label; sub-section brackets are dropped."""
    s = re.sub(r"\([^)]*\)", "", s)
    return re.sub(r"[\s-]+", "", s).upper()


def _which(m: re.Match) -> str:
    return next(k for k, _, _ in ACTS if m.group(k))


def check(pages: list[str]) -> list[Finding]:
    """Every reference found, in reading order. One finding per section number; an act named with no readable section is one mention."""
    out: list[Finding] = []
    for page, text in enumerate(pages, 1):
        if len(out) >= ENOUGH:
            break
        text = text or ""
        taken: list[tuple[int, int]] = []
        for m in SECTIONS.finditer(text):
            taken.append(m.span())
            act = _which(m)
            listed = m["list"]
            ranged = bool(re.search(r"\bto\b", listed, re.I))
            seen: set[str] = set()
            for n in ONE_NUM.finditer(re.sub(r"\([^)]*\)", "", listed)):
                label = canonical(n.group(0))
                if not label or label in seen:
                    continue
                seen.add(label)
                raw = " ".join(m.group(0).split())[:120]
                note = NOTE_SECTION.format(act=ACT_NAME[act]) + (NOTE_RANGE if ranged else "")
                out.append(Finding("section", act, label, raw, page, _sentence_at(text, m.start(), m.end()) if len(out) < ENOUGH else "", note, m.start()))
        for m in MENTION.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            act = _which(m)
            out.append(Finding("mention", act, "", " ".join(m.group(0).split()), page, _sentence_at(text, m.start(), m.end()) if len(out) < ENOUGH else "", NOTE_MENTION.format(act=ACT_NAME[act]), m.start()))
    return out
