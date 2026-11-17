"""Reading case-law citations out of text, in code (no AI): SCC, SCC OnLine, AIR, SCR, INSC and the High Courts' neutral citations, with case names, paragraph references and a
quotation put in brackets after it. Every citation gets ONE canonical form so "A.I.R. 1978 S.C. 597", "AIR 1978 SC 597" and "AIR (1978) SC 597" are found to be the same.

    parse(text)        -> [citation, ...] in the order they appear
    canonical(text)    -> the canonical form of the one citation in `text`, or None
    parse_all(text)    -> {"cases": parse(text), "provisions": legal_search.parse_citations(text with the case citations blanked out)}

Rules this module keeps:
* A part that is not in the text is never guessed. "AIR 1978 SC" (no page) is returned with complete=False, missing=["page"] and NO canonical form.
* Nothing is checked against a real case: a well-formed citation of a case that does not exist is parsed like any other. Whether it exists is the verification layer's question.
* The text of a quotation is returned exactly as written (the quote is located in a judgment later by lib/textmatch).
* Reporters this module does not read (JT, SCALE, Cri LJ, LL, ...) are returned as kind "other_reporter" with no canonical form, so the screen can say they were not read.

A citation: {kind, raw, start, end, canonical, complete, missing[], parts{}, case_name, paras[{from,to}], quote, parallel_group, notes[]}. start/end index the text as given."""

import re
from datetime import date

COURTS = {  # how a court is written in AIR and SCC OnLine, by the lower-case, dot-free form people type
    "sc": "SC", "del": "Del", "bom": "Bom", "mad": "Mad", "cal": "Cal", "all": "All", "kar": "Kar", "ker": "Ker", "guj": "Guj", "pat": "Pat", "raj": "Raj", "mp": "MP", "ori": "Ori", "gau": "Gau",
    "hp": "HP", "utt": "Utt", "chh": "Chh", "jhar": "Jhar", "tel": "Tel", "ap": "AP", "pun": "P&H", "p&h": "P&H", "j&k": "J&K", "jk": "J&K", "mani": "Mani", "megh": "Megh", "sikk": "Sikk", "tri": "Tri",
    "ncdrc": "NCDRC", "sat": "SAT",
}
SUPPLEMENTS = {"cri": "Cri", "civ": "Civ", "l&s": "L&S", "tax": "Tax", "jour": "Jour"}
OTHER_REPORTERS = re.compile(r"\b(?:JT\s+\d{4}|SCALE\s+\(?\d{4}|Cri\.?\s?L\.?J\.?|C\.?T\.?C\.?\s+\d|LL\s+\d{4}\s+SC|ACJ\s+\d|MLJ\s+\(?\d{4}|Bom\.?\s?C\.?R\.?|Mad\.?\s?L\.?J\.?|All\.?\s?L\.?J\.?|ILR\s+\(?\d{4}|MANU/[A-Z]+/\d+)", re.I)

_DOT = r"\.?"
_YEAR = r"(?:18|19|20)\d{2}"
YEAR_RANGE = (1860, date.today().year + 1)

SCC_ONLINE = re.compile(r"(?<!\w)(?P<year>" + _YEAR + r")\s*S\.?C\.?C\.?\s*On\s*-?Line\s+(?P<court>(?:[A-Za-z&]\.?){1,5})(?:\s+(?P<num>\d{1,6})(?!\d))?(?![A-Za-z])", re.I)
INSC = re.compile(r"(?<!\w)(?P<year>" + _YEAR + r")\s+INSC\s+(?P<num>\d{1,6})(?!\d)", re.I)
NEUTRAL = re.compile(r"(?<!\w)(?P<year>" + _YEAR + r"):(?P<court>[A-Z]{2,6}(?:-[A-Z]{1,4})?):(?P<num>\d{1,7})(?!\d)")
AIR = re.compile(r"(?<![\w])A\.?I\.?R\.?\s*\(?(?P<year>" + _YEAR + r")\)?\s+(?P<court>(?:[A-Za-z&]\.?){1,5})(?:\s+(?P<num>\d{1,5})(?!\d))?(?=[\s,;:)\].]|$)", re.I)
SCR = re.compile(r"(?:[\[(]\s*(?P<y1>" + _YEAR + r")\s*[\])]|(?P<y2>" + _YEAR + r"))\s*(?:(?P<v1>\d{1,3})|\(\s*(?P<v2>\d{1,3})\s*\))?\s*S\.?\s?C\.?\s?R\.?(?![A-Za-z])(?:\s*(?P<num>\d{1,5})(?!\d))?", re.I)
SCC_SUPP = re.compile(r"(?<![\w(\[])(?P<year>" + _YEAR + r")\s+Supp\.?\s*(?:\(\s*(?P<vol>\d{1,2})\s*\))?\s*S\.?\s?C\.?\s?C\.?(?![A-Za-z])(?:\s*(?P<num>\d{1,5})(?!\d))?", re.I)
SCC = re.compile(r"(?:\(\s*(?P<y1>" + _YEAR + r")\s*\)|(?<![\w(\[])(?P<y2>" + _YEAR + r"))\s*(?:(?P<v1>\d{1,3})|\(\s*(?P<v2>\d{1,3})\s*\))?\s*S\.?\s?C\.?\s?C\.?(?![A-Za-z])(?!\s*On\s*-?Line)"
                 r"(?:\s*\(\s*(?P<sup>Cri|Civ|L&S|Tax|Jour)\s*\))?(?:\s*(?P<num>\d{1,5})(?!\d))?", re.I)
PARA = re.compile(r"(?:\bparas?\b\.?|\bparagraphs?\b|¶¶?)\s*(?P<list>\d{1,4}(?:\s*(?:[-–—]|to)\s*\d{1,4})?(?:\s*(?:,|and|&)\s*\d{1,4}(?:\s*(?:[-–—]|to)\s*\d{1,4})?)*)", re.I)
VERSUS = re.compile(r"\s(?:v\.?|vs\.?|versus)\s", re.I)
IN_RE = re.compile(r"\bIn\s+re\s+(?P<name>[A-Z][\w.&'’()/-]*(?:\s+(?:[A-Z][\w.&'’()/-]*|of|the|and|&|for|v\.)){0,10})")
QUOTE = re.compile(r"(?:“(?P<a>[^”]{3,3000})”|\"(?P<b>[^\"]{3,3000})\")\s*$")
CONNECT = {"of", "the", "and", "&", "for", "in", "re", "on", "by", "to", "de", "ors", "ors.", "anr", "anr.", "others", "another", "m/s", "m/s.", "or", "at"}
ABBR = {"ltd", "co", "dr", "mr", "mrs", "ms", "shri", "smt", "pvt", "corp", "inc", "bros", "m/s", "no", "govt", "dept", "anr", "ors", "st", "jr", "sr", "prof", "hon", "etc", "u.p", "m.p", "a.p", "t.n"}


def _digits(text: str) -> str:
    """Digits of other scripts to 0-9, one character for one character (so every offset still points into the text as given)."""
    from lib.legal_search import ascii_digits

    return ascii_digits(text)


def _court(token: str) -> tuple[str, bool]:
    key = re.sub(r"[.\s]", "", token).lower()
    if key in COURTS:
        return COURTS[key], True
    return re.sub(r"\s+", " ", token.strip(". ")), False


def _make(kind, m, text, parts, missing, canonical, notes=None) -> dict:
    return {"kind": kind, "raw": text[m.start():m.end()], "start": m.start(), "end": m.end(), "canonical": None if missing else canonical, "complete": not missing, "missing": missing, "parts": parts,
            "case_name": None, "paras": [], "quote": None, "parallel_group": None, "notes": list(notes or [])}


def _year_note(year: int, notes: list) -> None:
    if not YEAR_RANGE[0] <= year <= YEAR_RANGE[1]:
        notes.append(f"the year {year} is outside {YEAR_RANGE[0]}-{YEAR_RANGE[1]}; check it")


def _scc_online(m, text):
    court, known = _court(m.group("court"))
    n, y = m.group("num"), int(m.group("year"))
    notes = [] if known else [f"court code '{court}' is not one this module knows; kept as written"]
    _year_note(y, notes)
    return _make("scc_online", m, text, {"year": y, "court": court, "number": int(n) if n else None}, [] if n else ["number"], f"{y} SCC OnLine {court} {int(n) if n else ''}".strip(), notes)


def _insc(m, text):
    y, n = int(m.group("year")), int(m.group("num"))
    notes: list = []
    _year_note(y, notes)
    return _make("insc", m, text, {"year": y, "number": n}, [], f"{y} INSC {n}", notes)


def _neutral(m, text):
    y, n, court = int(m.group("year")), int(m.group("num")), m.group("court")
    notes: list = []
    _year_note(y, notes)
    kind = "insc" if court == "INSC" else "neutral"
    return _make(kind, m, text, {"year": y, "court": court, "number": n}, [], f"{y}:{court}:{n}", notes)


def _air(m, text):
    court, known = _court(m.group("court"))
    n, y = m.group("num"), int(m.group("year"))
    if not known and not n:
        return None  # "AIR 1978 and the ..." is not a citation
    notes = [] if known else [f"court code '{court}' is not one this module knows; kept as written"]
    _year_note(y, notes)
    return _make("air", m, text, {"year": y, "court": court, "page": int(n) if n else None}, [] if n else ["page"], f"AIR {y} {court} {int(n) if n else ''}".strip(), notes)


def _scr(m, text):
    y = int(m.group("y1") or m.group("y2"))
    vol, n = m.group("v1") or m.group("v2"), m.group("num")
    missing = [x for x, v in (("volume", vol), ("page", n)) if not v]
    notes: list = []
    _year_note(y, notes)
    return _make("scr", m, text, {"year": y, "volume": int(vol) if vol else None, "page": int(n) if n else None}, missing, f"[{y}] {int(vol) if vol else ''} SCR {int(n) if n else ''}".replace("  ", " "), notes)


def _scc_supp(m, text):
    y, vol, n = int(m.group("year")), m.group("vol"), m.group("num")
    notes: list = []
    _year_note(y, notes)
    return _make("scc", m, text, {"year": y, "supplement_volume": int(vol) if vol else None, "page": int(n) if n else None, "supp": True}, [] if n else ["page"],
                 f"{y} Supp{f' ({int(vol)})' if vol else ''} SCC {int(n) if n else ''}".strip(), notes)


def _scc(m, text):
    y = int(m.group("y1") or m.group("y2"))
    vol, n, sup = m.group("v1") or m.group("v2"), m.group("num"), m.group("sup")
    if not (m.group("y1") or vol or n):
        return None  # "2010 SCC" alone is not enough to be a citation
    missing = [x for x, v in (("volume", vol), ("page", n)) if not v]
    notes: list = []
    _year_note(y, notes)
    sup_c = SUPPLEMENTS.get(sup.lower()) if sup else None
    canonical = f"({y}) {int(vol) if vol else ''} SCC{f' ({sup_c})' if sup_c else ''} {int(n) if n else ''}".replace("  ", " ").strip()
    return _make("scc", m, text, {"year": y, "volume": int(vol) if vol else None, "page": int(n) if n else None, "supplement": sup_c}, missing, canonical, notes)


READERS = [(SCC_ONLINE, _scc_online), (INSC, _insc), (NEUTRAL, _neutral), (AIR, _air), (SCC_SUPP, _scc_supp), (SCR, _scr), (SCC, _scc)]


def _words_back(text: str, end: int, lo: int = 0, limit: int = 14) -> int:
    """Start of the case-name words that end at `end` (walks left over capitalised words, connectors and abbreviations)."""
    pos, taken = end, 0
    base = max(lo, end - 220)
    for m in reversed(list(re.finditer(r"\S+", text[base:end]))):
        w = m.group(0)
        s = base + m.start()
        bare = w.strip(",;:()[]“”\"'").rstrip(".")
        ok = bool(bare) and (bare[0].isupper() or bare[0].isdigit() or bare.lower() in CONNECT or bare.lower() in ABBR or bare[0] in "(&")
        if not ok or taken >= limit or (w.endswith((";", ":")) and taken):
            break
        if w.endswith(".") and bare.lower() not in ABBR and not re.fullmatch(r"[A-Z]\.?", bare) and taken and bare.lower() not in CONNECT:
            break  # a full stop after a real word ends the sentence
        pos, taken = s, taken + 1
        if w.startswith(("“", '"')) and taken:
            pos = s + 1
            break
    while pos < end and text[pos] in '[“"':
        pos += 1
    return pos


def _words_fwd(text: str, start: int, hi: int, limit: int = 14) -> int:
    pos, taken = start, 0
    for m in re.finditer(r"\S+", text[start:min(hi, start + 220)]):
        w = m.group(0)
        bare = w.strip(",;:()[]“”\"'").rstrip(".")
        ok = bool(bare) and (bare[0].isupper() or bare[0].isdigit() or bare.lower() in CONNECT or bare.lower() in ABBR or bare[0] in "(&")
        if not ok or taken >= limit:
            break
        taken += 1
        pos = start + m.end()
        if w.endswith((",", ";", ":")) and not w.endswith(("Ltd.,", "Co.,")):
            pos -= 1
            break
        if w.endswith(".") and bare.lower() not in ABBR and not re.fullmatch(r"[A-Z]\.?", bare) and bare.lower() not in CONNECT:
            break
    return pos


def _tidy_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" ,;:")
    return re.sub(r"\s(?:vs\.?|versus|v)\s", " v. ", name, flags=re.I)


def _names(text: str, cites: list[tuple[int, int]]) -> list[dict]:
    """[{start, end, name}] for every 'X v. Y' and 'In re X' in the text."""
    out = []
    for m in VERSUS.finditer(text):
        lo = max([ce for cs, ce in cites if ce <= m.start()], default=0)
        hi = min([cs for cs, ce in cites if cs >= m.end()], default=len(text))
        s, e = _words_back(text, m.start(), lo), _words_fwd(text, m.end(), hi)
        while (w := re.match(r"\s*(\w+)\s", text[s:m.start()] + " ")) and w.group(1).islower() and w.group(1) in CONNECT and s + w.end() < m.start():
            s += w.end() - 1  # a name does not begin with 'in', 'of', 'the' ...: "As held in A. B. Traders v. C. D."
        left, right = text[s:m.start()].strip(), text[m.end():e].strip()
        if left and right and (left[0].isupper() or left[0].isdigit() or left[0] in "(&") and (right[0].isupper() or right[0].isdigit() or right[0] in "(&"):
            s += len(text[s:m.start()]) - len(text[s:m.start()].lstrip())
            out.append({"start": s, "end": e, "name": _tidy_name(f"{left} v {right}")})
    for m in IN_RE.finditer(text):
        out.append({"start": m.start(), "end": m.end(), "name": "In re " + _tidy_name(m.group("name"))})
    return out


def _paras(text: str, end: int) -> tuple[list[dict], int]:
    """Paragraph numbers written straight after a citation: ', para 12', ' (paras 12-14)', ' [at para 7 and 9]'. Returns them and where they end."""
    m = re.match(r"\s*[,(\[]?\s*(?:at\s+|in\s+)?", text[end:end + 40])
    p = PARA.match(text, end + (m.end() if m else 0))
    if not p:
        return [], end
    out = []
    for piece in re.split(r"\s*(?:,|and|&)\s*", p.group("list")):
        r = re.split(r"\s*(?:[-–—]|to)\s*", piece.strip())
        a, b = int(r[0]), int(r[-1])
        out.append({"from": a, "to": b} if a <= b else {"from": a, "to": a, "note": f"range {a}-{b} runs backwards; kept as typed"})
    return out, p.end()


def parse(text: str) -> list[dict]:
    orig = text or ""
    text = _digits(orig)
    taken: list[tuple[int, int]] = []
    found: list[dict] = []
    for rx, reader in READERS:
        for m in rx.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            c = reader(m, text)
            if c:
                taken.append((m.start(), m.end()))
                found.append(c)
    for m in OTHER_REPORTERS.finditer(text):
        if not any(m.start() < e and s < m.end() for s, e in taken):
            taken.append((m.start(), m.end()))
            found.append({"kind": "other_reporter", "raw": m.group(0), "start": m.start(), "end": m.end(), "canonical": None, "complete": False, "missing": [], "parts": {}, "case_name": None, "paras": [],
                          "quote": None, "parallel_group": None, "notes": ["this reporter is not read by VIDHI; the citation was not parsed"]})
    found.sort(key=lambda c: c["start"])

    names = _names(text, taken)
    used: set[int] = set()
    for c in found:
        for i, n in enumerate(names):  # a name directly before the citation (only space, a comma or a bracket between) belongs to it
            if i not in used and n["end"] <= c["start"] and re.fullmatch(r"[\s,(\[]*", text[n["end"]:c["start"]]) and c["start"] - n["end"] <= 6:
                c["case_name"], c["name_start"] = n["name"], n["start"]
                used.add(i)
                break
        c["paras"], c["group_end"] = _paras(text, c["end"]) if c["kind"] != "other_reporter" else ([], c["end"])
    for i, n in enumerate(names):
        if i not in used and not any(n["start"] < e and s < n["end"] for s, e in taken):
            found.append({"kind": "case_name", "raw": text[n["start"]:n["end"]], "start": n["start"], "end": n["end"], "canonical": n["name"], "complete": False, "missing": ["reporter citation"], "parts": {},
                          "case_name": n["name"], "paras": [], "quote": None, "parallel_group": None, "notes": ["a case name with no reporter citation next to it"]})
    found.sort(key=lambda c: c["start"])

    group = 0
    prev = None
    for c in found:  # 'AIR 1978 SC 597 : (1978) 2 SCC 248' is one case reported twice
        if prev and c["kind"] not in ("case_name",) and prev["kind"] not in ("case_name",) and re.fullmatch(r"\s*[:;=]\s*", text[prev.get("group_end", prev["end"]):c.get("name_start", c["start"])]):
            if prev["parallel_group"] is None:
                group += 1
                prev["parallel_group"] = group
            c["parallel_group"] = prev["parallel_group"]
        prev = c

    for c in found:  # a quotation closed just before a bracket that holds this citation: “...” [Name, (2010) 5 SCC 123, para 4]
        first, last = c.get("name_start", c["start"]), c.get("group_end", c["end"])
        before, after = text[:first].rstrip(), text[last:].lstrip()
        if before[-1:] in ("[", "(") and after[:1] == {"[": "]", "(": ")"}.get(before[-1:]) and c["kind"] != "case_name":
            q = QUOTE.search(before[:-1].rstrip())
            if q:
                g = "a" if q.group("a") else "b"
                c["quote"] = orig[q.start(g):q.end(g)].strip()  # as written, in the digits and spelling of the text given
    for c in found:
        c["raw"] = orig[c["start"]:c["end"]]
        c.pop("name_start", None)
        c.pop("group_end", None)
    return found


def canonical(text: str) -> str | None:
    """The canonical form of the single complete citation in `text`; None when there is none or more than one."""
    found = [c for c in parse(text) if c["canonical"] and c["kind"] != "case_name"]
    return found[0]["canonical"] if len(found) == 1 else None


def parse_all(text: str) -> dict:
    """Case citations, and the statute provisions named in the same text (legal_search.parse_citations, run on the text with the case citations blanked out: it would read '5 SCC' as section 5)."""
    from lib.legal_search import parse_citations

    cases = parse(text)
    blank = list(_digits(text or ""))
    for c in cases:
        for i in range(c["start"], c["end"]):
            blank[i] = " "
    return {"cases": cases, "provisions": parse_citations("".join(blank))}
