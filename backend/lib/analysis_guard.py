"""Checks run in CODE on everything the model writes for the strategy, reasoning and behaviour analyses (never trusted to the model's good manners).

A sentence is REMOVED, and the removal is reported, when it:
  * puts a diagnostic label on a person (psychopath, narcissist, bipolar...) as a statement about that person, rather than explaining the concept;
  * presents a strategy as guaranteed, universal or foolproof;
  * states a probability or percentage the person never supplied;
  * states another person's intent as certain fact ("is manipulating you", "clearly wants to");
  * presents an unsupported audio or brain-frequency claim as fact (lib/evidence_class.py);
  * uses a catalogued film as proof, precedent or authority (lib/films.py).
Honesty judgements ("lied", "fraudster") go through lib/neutral.py as everywhere else in VIDHI.
English wording only: other scripts have no reliable word list here, so non-English text is NOT screened by this module (the response says so). Rules like these cannot catch every phrasing;
they are a net under the prompt, not a proof, and the response tells the reader it is educational analysis."""

import re

from lib.evidence_class import screen_sentence
from lib.films import film_as_fact

_DIAG = re.compile(r"(psychopath\w*|psycho\b|sociopath\w*|narcissis\w*|narcissistic personality|antisocial personality|borderline personality|\bNPD\b|\bASPD\b|\bBPD\b|bipolar|schizophren\w*|sadist\w*|machiavellian\w*|dark triad)", re.I)
_REL = r"boss|partner|husband|wife|spouse|friend|colleague|manager|father|mother|son|daughter|uncle|aunt|cousin|ex|client|opponent|respondent|accused|defendant|plaintiff|petitioner|brother|sister|neighbou?r|landlord|tenant|employer|supervisor|co-?founder|director|judge|witness|lawyer|party|man|woman|person|teacher|doctor"
# the name alternative is case-sensitive; the rest is not. It is run on the sentence with the diagnostic word blanked, so "Narcissism is a trait" does not look like "<Name> is ..."
_PERSON = re.compile(rf"\b((?i:he|she|they|him|her|his|their|you|(?:my|your|his|her|their|our|the|that|this|other)\s+(?:other\s+)?(?:{_REL}))|(?:Mr|Mrs|Ms|Dr|Shri|Smt)\.?\s+[A-Z][a-z]+|[A-Z][a-z]+'s\s+(?i:{_REL})|[A-Z][a-z]+ (?:is|was|has|seems|appears))\b")
_ASSERT = re.compile(r"\b(is|are|was|were|has|have|seem(?:s|ed)?|appear(?:s|ed)?|looks? like|turns? out|must be|clearly|definitely|obviously|suffers? from|diagnos\w+ with|classic|textbook|total|pure|pathological|certified|through and through)\b|'s\b|'re\b", re.I)
_HEDGE = re.compile(r"\b(cannot|can't|can not|not|never|should not|without)\b.{0,50}\b(diagnos\w*|label\w*|profil\w*|call\w*|describe|assum\w*|speculat\w*)", re.I)
_UNIVERSAL = re.compile(r"\b(always works?|never fails?|guaranteed?\s+(?:way|method|approach|strategy|tactic|result|outcome|win|success|victory|settlement|to\s+\w+)|guarantees?\b[^.\n]{0,40}\b(?:success|results?|outcomes?|win|victory|settle\w*|payment|recover\w*)|in every case|without exception|universal (?:law|truth|rule)|invariably|cannot fail|foolproof|sure-?fire|works every time)\b", re.I)
# an honest negation sits right next to the word ("no method can guarantee a result", "it does not always work"), not anywhere before it ("nobody doubts it always works" is still a claim)
_NEGATED_GUARANTEE = re.compile(r"\b(?:no|not|never|cannot|can't|nobody|nothing|isn't|aren't)\s+(?:[a-z']+\s+){0,3}(?:guarantee\w*|foolproof|sure-?fire)\b|\bnot\s+always\s+works?\b|\bdoes\s+not\s+always\b", re.I)
_PROB = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?(?:%|per ?cent|percent)|\b(?:probability|chance|likelihood|odds)\b[^.\n]{0,50}?\b(\d{1,3}(?:\.\d+)?)\b", re.I)
_PROBCTX = re.compile(r"\b(?:chance|chances|probab\w*|likel\w+|odds|prospects?|succe\w+|win|settle\w*|certain\w*)\b", re.I)  # a percentage is a probability claim only in this kind of sentence ("interest is 12% a year" is not)
_PROB2 = re.compile(r"\b(?:ten|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|a hundred|one hundred)[\s-]?(?:per ?cent|percent)\b|\b\d{1,2}[\s-]in[\s-]\d{1,2}\b[^.\n]{0,20}\b(?:chance|odds|likel\w+)", re.I)
_MOTIVE = re.compile(r"\b(?:is|are|was)\s+(?:clearly |obviously |definitely |certainly |deliberately )?(?:lying|manipulating|gaslighting|deceiving|scheming|plotting)\b|\b(?:clearly|obviously|definitely|certainly)\s+(?:intends?|wants?|plans?|is trying|tries|attempts?|is attempting|trying)\s+to\b|\b(?:plans?|plotting|intends?|is planning)\s+to\s+(?:deceive|cheat|defraud|trick|con|scam|mislead|manipulate)\b", re.I)
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_NUM = re.compile(r"\d+(?:\.\d+)?")

REASONS = {
    "diagnosis": "labelled a person with a diagnosis, which this tool cannot do",
    "universal": "presented a strategy as guaranteed or universal",
    "probability": "gave a probability the person never supplied",
    "motive": "stated someone's intent as certain fact",
    "unsupported": "presented an unsupported audio or brain-frequency claim as fact",
    "film_as_fact": "treated a film as proof, precedent or legal authority",
}


def _is_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(1 for c in letters if c.isascii()) / len(letters) > 0.9


def _violation(sentence: str, given_numbers: set[str]) -> str | None:
    if _DIAG.search(sentence) and _PERSON.search(_DIAG.sub("X", sentence)) and _ASSERT.search(sentence) and not _HEDGE.search(sentence):
        return "diagnosis"
    if _UNIVERSAL.search(sentence) and not _NEGATED_GUARANTEE.search(sentence):  # "no method can guarantee a result" is the honest wording
        return "universal"
    for m in _PROB.finditer(sentence):
        nums = set(_NUM.findall(m.group(0)))
        percent = bool(re.search(r"%|per ?cent|percent", m.group(0), re.I))
        if nums and not nums <= given_numbers and (not percent or _PROBCTX.search(sentence)):
            return "probability"
    m2 = _PROB2.search(sentence)
    if m2 and _PROBCTX.search(sentence):
        digits = set(_NUM.findall(m2.group(0)))
        if not (digits and digits <= given_numbers):  # spelled-out figures ("seventy percent") can never have been typed as digits, so they count as new
            return "probability"
    if _MOTIVE.search(sentence):
        return "motive"
    if screen_sentence(sentence):
        return "unsupported"
    if film_as_fact(sentence):
        return "film_as_fact"
    return None


def clean_text(text: str, given: str = "") -> tuple[str, list[dict]]:
    """(text with offending sentences replaced by a visible note, what was removed). `given` is what the person wrote, so numbers they supplied are allowed through."""
    if not isinstance(text, str) or not text.strip() or not _is_english(text):
        return text, []
    nums = set(_NUM.findall(given))
    flags = []
    result = text
    for s in _SPLIT.split(text):
        rule = _violation(s, nums) if s.strip() else None
        if rule:
            flags.append({"rule": rule, "removed": s.strip()[:160]})
            result = result.replace(s, f"[Removed by VIDHI: this {REASONS[rule]}.]", 1)
    return result, flags


def clean_tree(value, given: str = "", flags: list | None = None):
    """Apply clean_text to every string anywhere inside a model reply (lists, dicts, nested). Returns the cleaned copy; removals are appended to `flags`."""
    flags = flags if flags is not None else []
    if isinstance(value, str):
        text, f = clean_text(value, given)
        flags.extend(f)
        return text
    if isinstance(value, list):
        return [clean_tree(v, given, flags) for v in value]
    if isinstance(value, dict):
        return {k: clean_tree(v, given, flags) for k, v in value.items()}
    return value


# ---- legal time limits: a wrong deadline is the most harmful thing the app can say, so an unverified one is never shown (found by the real-case evaluation, docs/VIDHI_REAL_CASE_EVALUATION.md)
_PNUM = r"(?:\d{1,4}(?:\s?[-–]\s?\d{1,4})?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty-five|sixty|ninety)"
_PUNIT = r"(?:days?|weeks?|months?|years?)"
_PERIOD = re.compile(rf"\b(?:within|in|after|before|period of|limit of|limitation of|not later than|no later than|for|is|are|be|of)\s+(?:[a-z-]+\s+){{0,3}}{_PNUM}\s*{_PUNIT}\b|\b{_PNUM}\s*{_PUNIT}\s+(?:from|of|after|to|for|limit|period)", re.I)
_PROCESS = re.compile(r"\b(?:notice|appeal|complaint|file[ds]?|filing|limitation|plaint|suit|petition|revision|review|reply|written statement|bail|charge-?sheet|prosecution|claim|time[- ]barred|deadline|summons|execution|demand)\b", re.I)
DEADLINE_NOTE = ("Time limits for legal steps (such as notices, appeals and complaints) are not stated here because VIDHI cannot check them against a verified source. "
                 "Look up the exact period, and when it starts to run, in the Act itself, or ask a lawyer.")


def _period_in(sentence: str, evidence: str) -> bool:
    """True if every period (such as '15 days') the sentence states appears in the matter's own text."""
    if not evidence:
        return False
    ev = "".join(evidence.lower().split())
    found = [re.sub(r"\s+", "", m.group(0).lower()) for m in re.finditer(rf"{_PNUM}\s*{_PUNIT}", sentence, re.I)]
    return bool(found) and all(f in ev for f in found)


def strip_unverified_deadlines(text: str, evidence: str = "") -> tuple[str, int]:
    """Replace each sentence that gives a legal time limit (a number of days, months or years next to a legal step) with a visible note. Returns (text, how many were removed).
    Call it only when no verified library source supports the answer. A sentence that points at a matter document (DOC-nn) is left alone only if the period it states really appears
    in that matter's own text (`evidence`): otherwise adding '(DOC-1)' would be a way round the rule."""
    if not isinstance(text, str) or not text.strip() or not _is_english(text):
        return text, 0
    n, out = 0, text
    for s in _SPLIT.split(text):
        if not (s.strip() and _PERIOD.search(s) and _PROCESS.search(s)):
            continue
        if re.search(r"DOC-\d", s) and _period_in(s, evidence):
            continue
        out = out.replace(s, "[Removed by VIDHI: this stated a legal time limit that cannot be verified.]", 1)
        n += 1
    return out, n
