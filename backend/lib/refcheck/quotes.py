"""Quote check (Stage 2a): are the words the draft puts in quotation marks, next to a case citation, really in that judgment, and where?

It runs only for a case the lookup FOUND and whose details agreed (FOUND_MATCHES): a quote cannot be judged against a case that was not confirmed. The comparison is the same
whole-word, whole-number comparison used everywhere else (lib/textmatch.py). Nothing here uses AI and nothing stores judgment text: the result keeps the draft's own quoted
words, a yes/no and the paragraph number.

Per quote, one of:
  QUOTE_FOUND        every stretch of the quote was found in the judgment as the source holds it; the paragraph is recorded
  QUOTE_NOT_FOUND    at least one stretch was not found. This says only that the words are not in the text the source holds: the draft may quote another report, the source's text may
                     differ in spelling or line breaks, or the words may be from a statute or another case. A person checks.
  QUOTE_NOT_CHECKED  nothing could be compared (the case was not confirmed, the source gave no paragraphs, or the quote has too few words to prove anything)
Whether the quoted words are the court's own holding, or counsel's argument or another case quoted inside the judgment, is NOT checked."""

import re

from lib import textmatch

QUOTE_FOUND = "QUOTE_FOUND"
QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
QUOTE_NOT_CHECKED = "QUOTE_NOT_CHECKED"

# "..." / ". . ." / "…" / "[...]" / "[…]" mark words left out; "[the court]" marks words the quoter added. Either way the stretches around them are compared one by one.
_GAP = re.compile(r"\[\s*(?:\.\s*){2,}\]|\.{2,}|(?:\.\s){2,}\.|…|\[[^\]]{0,80}\]")
_PARA_START = re.compile(r"^\s*\(?(\d{1,3})[.)]\s+\S")
_LINE_PARA = re.compile(r"(?m)^\s*\(?\d{1,3}[.)]\s+\S")


def segments(quote: str) -> list[str]:
    """The stretches of a quote that can be compared: the quote cut at omissions and insertions, keeping those long enough to prove anything."""
    out = []
    for part in _GAP.split(quote or ""):
        part = part.strip(" \t\r\n\"'“”‘’,;:-—–")
        if len(textmatch.norm(part)) >= textmatch.MIN_QUOTE and textmatch.substance(part) >= textmatch.MIN_SUBSTANCE:
            out.append(part)
    return out


def paragraph_of(blocks: list[str], index: int) -> dict:
    """Where in the judgment a block is, in the judgment's own numbering: {"paragraph": N or None, "exact": bool, "block": 1-based}. exact is True when the block itself begins with
    its paragraph number (and holds no other numbered paragraph); otherwise the number is that of the nearest numbered paragraph before it and the screen says 'at or after'."""
    i = max(0, min(index, len(blocks) - 1))
    own = _PARA_START.match(blocks[i])
    if own and len(_LINE_PARA.findall(blocks[i])) <= 1:
        return {"paragraph": int(own.group(1)), "exact": True, "block": i + 1}
    for j in range(i, -1, -1):
        m = _PARA_START.match(blocks[j])
        if m:
            return {"paragraph": int(m.group(1)), "exact": False, "block": i + 1}
    return {"paragraph": None, "exact": False, "block": i + 1}


def check_quote(quote: str, blocks: list[str]) -> dict:
    segs = segments(quote)
    base = {"quote": quote[:600], "result": QUOTE_NOT_CHECKED, "paragraph": None, "exact": False, "block": None, "reason": ""}
    if not blocks:
        return {**base, "reason": "The source gave the judgment without paragraphs, so the words could not be located."}
    if not segs:
        return {**base, "reason": "These quoted words are too few to compare with a judgment."}
    first = None
    for s in segs:
        hit = textmatch.locate(s, blocks)
        if hit is None:
            return {**base, "result": QUOTE_NOT_FOUND,
                    "reason": "These words were not found in the text of this judgment as the source holds it. The draft may quote a different report, the source's text may differ in spelling or line breaks, "
                    "or the words may come from a statute or another case. Please check them against the judgment."}
        first = first or hit
    where = paragraph_of(blocks, first["page"] - 1)
    if where["paragraph"] is None:
        reason = f"These words were found in the judgment (block {where['block']}; the source shows no paragraph number there). Whether they are the court's own words is not checked."
    elif where["exact"]:
        reason = f"These words were found in the judgment at paragraph {where['paragraph']}. Whether they are the court's own words is not checked."
    else:
        reason = f"These words were found in the judgment at or after paragraph {where['paragraph']}. Whether they are the court's own words is not checked."
    return {**base, "result": QUOTE_FOUND, **where, "reason": reason}


def check_all(quotes: list[str], blocks: list[str], *, confirmed: bool, shared_sentence: bool = False) -> list[dict]:
    """Every quote beside one citation. `confirmed` is False unless the case itself was found with agreeing details. `shared_sentence` is True when the sentence cites more than one
    case, so a quote that is not found may belong to the other one (said in the reason)."""
    out = []
    for q in quotes:
        if not confirmed:
            out.append({"quote": q[:600], "result": QUOTE_NOT_CHECKED, "paragraph": None, "exact": False, "block": None, "reason": "The case itself was not confirmed, so its quotes were not checked."})
            continue
        r = check_quote(q, blocks)
        if shared_sentence and r["result"] == QUOTE_NOT_FOUND:
            r["reason"] += " This sentence cites more than one case, so the words may belong to the other."
        out.append(r)
    return out


def summary_label(results: list[dict]) -> str:
    """One word for the citation: not found beats not checked beats found; empty when the draft quoted nothing."""
    kinds = {r["result"] for r in results}
    for k in (QUOTE_NOT_FOUND, QUOTE_NOT_CHECKED, QUOTE_FOUND):
        if k in kinds:
            return k
    return ""
