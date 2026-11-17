"""Finds case citations and statute references in a document's text, page by page.

This only READS what the draft says. It never decides whether a case exists or what a law says: that is the job of a source (lookup.py) and of the reviewed
library. Every reference keeps the sentence around it (the proposition it is cited for), any words in quotation marks near it, and the page it is on.

Citation shapes understood (the draft's own spelling is always kept in `raw`):
  neutral        2023 INSC 123 · 2024:DHC:1234 · 2023:BHC-AS:456
  SCC            (2020) 7 SCC 1 · 2020 (7) SCC 1
  SCC OnLine     2021 SCC OnLine SC 123
  AIR            AIR 2017 SC 4161
  SCR            [2019] 4 SCR 1 · (1973) Supp SCR 1
  statute        Section 63 of the Bharatiya Sakshya Adhiniyam · Section 138, Negotiable Instruments Act, 1881 · Article 21 of the Constitution
"""

import re
from dataclasses import dataclass, field

_YEAR = r"(?:19|20)\d{2}"
_NEUTRAL_ANCHORED = re.compile(rf"\b(?P<year>{_YEAR})\s*(?:INSC\s+|:INSC:)(?P<num>\d{{1,6}})\b|\b(?P<year2>{_YEAR}):(?P<court2>[A-Z]{{2,6}}(?:-[A-Z]{{1,4}})?):(?P<num2>\d{{1,6}})\b")
SCC = re.compile(rf"(?:\((?P<y1>{_YEAR})\)\s*(?P<v1>\d{{1,3}})|(?P<y2>{_YEAR})\s*\((?P<v2>\d{{1,3}})\))\s*SCC\s*(?!OnLine)(?P<page>\d{{1,5}})\b")
SCC_ONLINE = re.compile(rf"\b(?P<year>{_YEAR})\s*SCC\s*OnLine\s*(?P<court>[A-Za-z]{{2,8}})\s*(?P<num>\d{{1,6}})\b")
AIR = re.compile(rf"\bAIR\s*(?P<year>{_YEAR})\s*(?P<court>[A-Za-z]{{2,8}})\s*(?P<page>\d{{1,5}})\b")
SCR = re.compile(rf"(?:\[(?P<y1>{_YEAR})\]|\((?P<y2>{_YEAR})\))\s*(?:(?P<v>\d{{1,3}}|Supp\.?)\s*)SCR\s*(?P<page>\d{{1,5}})\b")
# "A v. B", "A vs B", "State of X v. Y": starts at a capital letter, no sentence break inside
_TOK = r"(?:[A-Z]|\((?=[A-Za-z]))[\w.&'’()\-/]*"  # a capitalised word, or one that opens with a bracket such as "(Retd.)"
PARTY = rf"{_TOK}(?:\s+(?:{_TOK}|of|and|the|for|in|on|ors?\.?|anr\.?|&)){{0,9}}"
CASE_NAME = re.compile(rf"(?P<a>{PARTY})\s+(?:v\.?|vs\.?|versus)\s+(?P<b>{PARTY})")
STATUTE = re.compile(
    r"\b(?P<unit>Sections?|Sec\.|S\.|Articles?|Art\.|Rule|Order)\s+(?P<num>\d+[A-Za-z]{0,2}(?:\(\w+\))*(?:\s*(?:,|and|&|to)\s*\d+[A-Za-z]{0,2}(?:\(\w+\))*)*)"
    r"\s*(?:,|of(?:\s+the)?)?\s*(?P<act>(?:The\s+)?[A-Z][A-Za-z.&'’()\- ]{2,80}?(?:Act|Code|Sanhita|Adhiniyam|Constitution|Rules|Order|Procedure)(?:\s*,?\s*(?:19|20)\d{2})?|IPC|CrPC|CPC|BNS|BNSS|BSA|NI Act|Evidence Act)"
)
OLD_CODES = re.compile(r"\b(?:IPC|Indian Penal Code|CrPC|Cr\.P\.C\.?|Code of Criminal Procedure|Indian Evidence Act|Evidence Act)\b", re.I)
QUOTE = re.compile(r"[\"“‘]([^\"”’]{12,600})[\"”’]")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[“\"])")


@dataclass
class Reference:
    kind: str  # "case" or "statute"
    raw: str  # the citation exactly as the draft wrote it
    page: int  # 1-based page of the draft
    sentence: str  # the sentence around it: the point it is cited for
    quotes: list[str] = field(default_factory=list)  # words in quotation marks in that sentence
    # case fields (empty for statutes)
    case_name: str = ""
    parties: tuple[str, str] = ("", "")
    year: int | None = None
    court: str = ""  # as written: SC, Bom, Del, INSC ...
    neutral: str = ""  # normalised neutral citation when the draft gave one, for example "2023 INSC 123"
    report: str = ""  # normalised report citation, for example "(2020) 7 SCC 1" or "AIR 2017 SC 4161"
    reporter: str = ""  # SCC | AIR | SCR | SCC OnLine | neutral
    volume: str = ""
    start_page: str = ""
    # statute fields
    unit: str = ""
    number: str = ""
    act: str = ""
    old_code: bool = False  # an old criminal code (IPC, CrPC, Evidence Act): flagged for the future old-code checker

    @property
    def key(self) -> str:
        """The same reference written twice (even on different pages) has the same key."""
        if self.kind == "case":
            return "case|" + (self.neutral or self.report or re.sub(r"\W+", " ", self.raw.lower()).strip())
        return "statute|" + re.sub(r"\W+", " ", f"{self.unit} {self.number} {self.act}".lower()).strip()


_ABBREV = frozenset("v vs no nos ltd co pvt mr mrs ms dr sri smt shri st sec secs art arts s u ors anr anr. i.e e.g cf viz etc dept govt hon ld".split())
_LEAD = frozenset("see also cf vide in per compare and but held following hence thus relied on the case of".split())


_ABBREV_TAIL = re.compile(r"([A-Za-z.]+)\.$")


def _boundaries(text: str) -> list[int]:
    cuts = [0]
    for m in _SENTENCE_END.finditer(text):
        word = _ABBREV_TAIL.search(text[max(0, m.start() - 12):m.start()])
        if word and word.group(1).lower().strip(".") in _ABBREV:
            continue  # "v.", "Ltd.", "No." do not end a sentence
        cuts.append(m.end())
    return cuts + [len(text)]


_LONG_TEXT = 20_000  # above this, only the text around the match is searched for the sentence ends
_WINDOW = 1_500  # the sentence shown is at most 900 characters, 300 of them before the match when the sentence start is far: 1,500 either side is more than it can use


def _sentence_at(text: str, start: int, end: int) -> str:
    if len(text) > _LONG_TEXT:  # a huge page with thousands of matches otherwise re-scans the whole page for every one (quadratic)
        a, b = max(0, start - _WINDOW), min(len(text), end + _WINDOW)
        text, start, end = text[a:b], start - a, end - a
    cuts = _boundaries(text)
    lo = max((c for c in cuts if c <= start), default=0)
    hi = min((c for c in cuts if c >= end), default=len(text))
    seg = text[lo:hi]
    if start - lo > 600:  # a very long run with no sentence end: show the part around the match, not its first 900 characters (which would not contain it)
        seg = seg[start - lo - 300:]
    return " ".join(seg.split())[:900]


def _strip_lead(name: str) -> str:
    words = name.split()
    while len(words) > 1 and words[0].lower().strip(",.:;") in _LEAD:
        words.pop(0)
    return " ".join(words)


def _parties_before(text: str, start: int) -> tuple[str, str]:
    window = text[max(0, start - 220):start]
    best = None
    for m in CASE_NAME.finditer(window):
        best = m
    if not best:
        return ("", "")
    return (_strip_lead(" ".join(best.group("a").split()).strip(" ,;:")), " ".join(best.group("b").split()).strip(" ,;:"))


def _clean_act(act: str) -> str:
    act = re.sub(r"^The\s+", "", " ".join(act.split())).strip(" ,.")
    return {"IPC": "Indian Penal Code", "CrPC": "Code of Criminal Procedure", "CPC": "Code of Civil Procedure", "BNS": "Bharatiya Nyaya Sanhita", "BNSS": "Bharatiya Nagarik Suraksha Sanhita", "BSA": "Bharatiya Sakshya Adhiniyam", "NI Act": "Negotiable Instruments Act"}.get(act, act)


def extract_page(text: str, page: int) -> list[Reference]:
    refs: list[Reference] = []

    def add(kind: str, m: re.Match, **kw) -> None:
        sentence = _sentence_at(text, m.start(), m.end())
        refs.append(Reference(kind=kind, raw=" ".join(m.group(0).split()), page=page, sentence=sentence, quotes=[q.strip() for q in QUOTE.findall(sentence)], **kw))

    taken: list[tuple[int, int]] = []

    def free(m: re.Match) -> bool:
        return not any(m.start() < e and s < m.end() for s, e in taken)

    for m in SCC_ONLINE.finditer(text):
        taken.append(m.span())
        a, b = _parties_before(text, m.start())
        y = int(m.group("year"))
        add("case", m, case_name=f"{a} v. {b}" if a else "", parties=(a, b), year=y, court=m.group("court").upper(), reporter="SCC OnLine", report=f"{y} SCC OnLine {m.group('court').upper()} {m.group('num')}", start_page=m.group("num"))
    for m in _NEUTRAL_ANCHORED.finditer(text):
        if not free(m):
            continue
        taken.append(m.span())
        a, b = _parties_before(text, m.start())
        if m.group("year"):
            y, court, num = int(m.group("year")), "INSC", m.group("num")
        else:
            y, court, num = int(m.group("year2")), m.group("court2"), m.group("num2")
        norm = f"{y} INSC {num}" if court == "INSC" else f"{y}:{court}:{num}"
        add("case", m, case_name=f"{a} v. {b}" if a else "", parties=(a, b), year=y, court=court, reporter="neutral", neutral=norm, start_page=num)
    for m in SCC.finditer(text):
        if not free(m):
            continue
        taken.append(m.span())
        a, b = _parties_before(text, m.start())
        y, v = int(m.group("y1") or m.group("y2")), m.group("v1") or m.group("v2")
        add("case", m, case_name=f"{a} v. {b}" if a else "", parties=(a, b), year=y, court="SC", reporter="SCC", report=f"({y}) {v} SCC {m.group('page')}", volume=v, start_page=m.group("page"))
    for m in AIR.finditer(text):
        if not free(m):
            continue
        taken.append(m.span())
        a, b = _parties_before(text, m.start())
        y = int(m.group("year"))
        court = m.group("court")
        add("case", m, case_name=f"{a} v. {b}" if a else "", parties=(a, b), year=y, court=court.upper() if court.upper() == "SC" else court.title(), reporter="AIR", report=f"AIR {y} {court.upper() if court.upper() == 'SC' else court.title()} {m.group('page')}", start_page=m.group("page"))
    for m in SCR.finditer(text):
        if not free(m):
            continue
        taken.append(m.span())
        a, b = _parties_before(text, m.start())
        y = int(m.group("y1") or m.group("y2"))
        add("case", m, case_name=f"{a} v. {b}" if a else "", parties=(a, b), year=y, court="SC", reporter="SCR", report=f"[{y}] {m.group('v')} SCR {m.group('page')}", volume=m.group("v"), start_page=m.group("page"))
    # a case named with a year and court but no report citation, e.g. "X v. Y (2019) (Delhi High Court)": too uncertain to treat as a citation; it is not guessed at.
    for m in STATUTE.finditer(text):
        if any(m.start() < e and s < m.end() for s, e in taken):
            continue
        act = _clean_act(m.group("act"))
        unit = {"sec.": "Section", "s.": "Section", "art.": "Article", "sections": "Section", "articles": "Article"}.get(m.group("unit").lower(), m.group("unit").title())
        add("statute", m, unit=unit, number=" ".join(m.group("num").split()), act=act, old_code=bool(OLD_CODES.search(act) or OLD_CODES.search(m.group("act"))))
    return refs


def extract(pages: list[str]) -> list[Reference]:
    """Every reference in the document, in reading order, with the page of its FIRST appearance kept and later repeats dropped."""
    seen: dict[str, Reference] = {}
    for i, text in enumerate(pages, 1):
        for ref in extract_page(text or "", i):
            seen.setdefault(ref.key, ref)
    return list(seen.values())
