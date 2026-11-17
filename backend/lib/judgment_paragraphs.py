"""A judgment as numbered paragraphs, and where a quotation sits in it. Pure code, no AI.

    split(text)                  -> {"paragraphs": [{n, label, start, end, text}], "method", "warnings"}
    locate_quote(paras, q)       -> {"n", "start", "end", "exact", "similarity", "note"} or None

split: judgments number their paragraphs "1.", "2.", ... at the start of a line (also "[1]", "(1)", "1)", and digits of other scripts). A number is accepted only when it continues the run: the next one is
the one after the last accepted (a missing marker is allowed, up to 3 numbers; the gap is reported), so "2010." at the start of a line, an amount ("12. Rs ...") or a list inside a paragraph are not taken
for paragraph starts. Text before paragraph 1 is the preamble (n = 0). A paragraph number is only ever one that is PRINTED in the judgment: when fewer than 3 consecutive numbers are found, the text is split at
blank lines and every paragraph has n = None (never a number made up).

locate_quote: first an exact find (lib/textmatch rules: whole words, whole numbers) inside one paragraph or across two neighbours. If that fails, an APPROXIMATE find that forgives the damage a scan does
(r-n read as m, i-l-I-| confused, line-break hyphens, stray spaces, ligatures) but never a different number or a lost "not": it returns exact=False with the similarity. An approximate find is a pointer for a
person to read, never a verification: only exact=True may be treated as the quotation being in the judgment."""

import re
import unicodedata
from difflib import SequenceMatcher

from lib import textmatch

MAX_GAP = 3  # a paragraph marker lost by the scan: up to this many numbers may be skipped
MIN_RUN = 3  # fewer numbered paragraphs than this and the text is split at blank lines instead
LINE_NUMBER = re.compile(r"^[ \t]*(?:\[\s*(?P<a>\d{1,3})\s*\]|\(\s*(?P<b>\d{1,3})\s*\)|(?P<c>\d{1,3})\s*[.)])(?=[ \t]*\S|[ \t]*$)", re.M)
NEGATIONS = {"not", "no", "never", "nor", "neither", "cannot", "without", "none"}
MIN_SIMILARITY = 0.92
OCR_FOLD = str.maketrans({"|": "l", "!": "l", "i": "l", "ı": "l", "ſ": "s", "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff"})


def _digits(text: str) -> str:
    return "".join(str(unicodedata.digit(c)) if c.isdigit() and not c.isascii() and unicodedata.digit(c, None) is not None else c for c in text)


def split(text: str) -> dict:
    text = text or ""
    seen = _digits(text)  # one character for one character: offsets still point into `text`
    marks: list[tuple[int, int, int]] = []  # (number, start of the marker line, end of the marker)
    last, warnings = 0, []
    for m in LINE_NUMBER.finditer(seen):
        n = int(m.group("a") or m.group("b") or m.group("c"))
        if n == last + 1 or (last == 0 and 1 <= n <= 2) or last + 1 < n <= last + 1 + MAX_GAP and last > 0:
            if n != last + 1 and last > 0:
                warnings.append(f"paragraph number(s) {last + 1}-{n - 1} not found; the scan may have lost them")
            elif last == 0 and n == 2:
                warnings.append("paragraph 1 not found")
            marks.append((n, m.start(), m.end()))
            last = n
    if len(marks) >= MIN_RUN:
        return _numbered(text, marks, warnings)
    return _by_blank_lines(text, ["fewer than 3 consecutive numbered paragraphs found: split at blank lines, paragraph numbers not available"])


def _para(n, label, start, end, text) -> dict:
    return {"n": n, "label": label, "start": start, "end": end, "text": text[start:end].strip()}


def _numbered(text: str, marks: list, warnings: list) -> dict:
    out = []
    first = marks[0][1]
    if text[:first].strip():
        out.append(_para(0, "Preamble", 0, first, text))
    for i, (n, s, e) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        out.append(_para(n, f"Paragraph {n}", s, end, text))
    for p in out:  # trim the offsets to the text itself, so text[start:end] is the paragraph
        raw = text[p["start"]:p["end"]]
        p["start"] += len(raw) - len(raw.lstrip())
        p["end"] -= len(raw) - len(raw.rstrip())
    return {"paragraphs": [p for p in out if p["text"]], "method": "numbered", "warnings": warnings}


def _by_blank_lines(text: str, warnings: list) -> dict:
    out, k = [], 0
    for m in re.finditer(r"\S(?:.|\n(?!\s*\n))*", text):
        k += 1
        out.append({"n": None, "label": f"Block {k}", "start": m.start(), "end": m.end(), "text": m.group(0).strip()})
    return {"paragraphs": out, "method": "blank-lines", "warnings": warnings}


def passages(paragraphs: list[dict], limit: int = 1500) -> list[dict]:
    """The pieces that are indexed: a paragraph, or its sentences grouped into pieces of at most `limit` characters (the same paragraph number, offsets into the judgment text)."""
    out = []
    for p in paragraphs:
        if len(p["text"]) <= limit:
            out.append({"n": p["n"], "start": p["start"], "end": p["end"], "text": p["text"]})
            continue
        pos = piece = 0
        raw_start = p["start"]
        for m in re.finditer(r"[^.?!;\n]+[.?!;]*\s*", p["text"]):
            if m.end() - pos > limit and m.start() > pos:
                out.append({"n": p["n"], "start": raw_start + pos, "end": raw_start + m.start(), "text": p["text"][pos:m.start()]})
                pos = m.start()
        out.append({"n": p["n"], "start": raw_start + pos, "end": raw_start + len(p["text"]), "text": p["text"][pos:]})
    return out


# ---- finding a quotation ----

def _exact(quote: str, paragraphs: list[dict]) -> dict | None:
    q = textmatch.norm(quote)
    if len(q) < textmatch.MIN_QUOTE or textmatch.substance(q) < textmatch.MIN_SUBSTANCE:
        return None
    for p in paragraphs:
        if textmatch.bounded_find(textmatch.norm(p["text"]), q) >= 0:
            return {"n": p["n"], "start": p["start"], "end": p["end"], "exact": True, "similarity": 1.0, "note": None}
    for p, nxt in zip(paragraphs, paragraphs[1:]):  # a quotation that runs over into the next paragraph
        if textmatch.bounded_find(textmatch.norm(p["text"] + " " + nxt["text"]), q) >= 0:
            return {"n": p["n"], "start": p["start"], "end": nxt["end"], "exact": True, "similarity": 1.0, "note": f"runs from {p['label']} into {nxt['label']}"}
    return None


def _squash(s: str) -> str:
    s = unicodedata.normalize("NFKC", textmatch.norm(s))
    s = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", s).translate(OCR_FOLD)
    s = s.replace("rn", "m").replace("vv", "w")
    return re.sub(r"[^\w]", "", s)


def _edges_agree(quote_norm: str, window: str) -> bool:
    qw, ww = quote_norm.split(), textmatch.norm(window).split()
    if not qw or not ww:
        return False
    return all(SequenceMatcher(None, _squash(a), _squash(b)).ratio() >= 0.75 for a, b in ((qw[0], ww[0]), (qw[-1], ww[-1])))


def _negations(s: str) -> int:
    return sum(1 for w in re.findall(r"[a-z]+", textmatch.norm(s)) if w in NEGATIONS)


def _approx(quote: str, paragraphs: list[dict]) -> dict | None:
    q = textmatch.norm(quote)
    if len(q) < textmatch.MIN_QUOTE or textmatch.substance(q) < textmatch.MIN_SUBSTANCE:
        return None
    want, nums, neg = _squash(quote), textmatch.numbers(quote), _negations(quote)
    qwords = set(re.findall(r"\w{4,}", q))
    best = None
    scored = sorted(paragraphs, key=lambda p: -len(qwords & set(re.findall(r"\w{4,}", textmatch.norm(p["text"])))))[:6]  # only the paragraphs that share the quotation's longer words
    qfirst = _squash(q.split()[0])
    for p in scored:
        words = [(m.start(), m.end()) for m in re.finditer(r"\S+", p["text"])]
        folded = [_squash(p["text"][s:e]) for s, e in words]
        qn = max(1, len(q.split()))
        for i, first in enumerate(folded):
            if not first or SequenceMatcher(None, qfirst, first).ratio() < 0.75:
                continue  # a window must begin where the quotation begins
            for width in range(max(1, qn - 3), qn + 4):
                if i + width > len(words):
                    break
                have = "".join(folded[i:i + width])
                if abs(len(have) - len(want)) > max(3, len(want) * 0.15):
                    continue
                sm = SequenceMatcher(None, want, have, autojunk=False)
                if sm.quick_ratio() < MIN_SIMILARITY or sm.ratio() < MIN_SIMILARITY:
                    continue
                s, e = words[i][0], words[i + width - 1][1]
                window = p["text"][s:e]
                if textmatch.numbers(window) != nums or _negations(window) != neg:
                    continue  # a different figure or a lost "not" is a different statement, however alike the letters
                if not _edges_agree(q, window) or _negations(p["text"][max(0, s - 12):s] + " " + p["text"][e:e + 12]) > 0 and neg == 0:
                    continue  # the window must end on the quotation's own last word, and not sit right beside a "not" the quotation lacks
                r = sm.ratio()
                if best is None or r > best[0]:
                    best = (r, p, p["start"] + s, p["start"] + e)
    if not best:
        return None
    r, p, s, e = best
    return {"n": p["n"], "start": s, "end": e, "exact": False, "similarity": round(r, 3), "note": "approximate: the letters differ in the way a scan does; read the judgment before relying on it"}


def locate_quote(paragraphs: list[dict], quote: str) -> dict | None:
    """Where `quote` is: {"n", "start", "end", "exact", "similarity", "note"}. start/end index the judgment text (the paragraph for an exact find, the matching words for an approximate one)."""
    return _exact(quote, paragraphs) or _approx(quote, paragraphs)
