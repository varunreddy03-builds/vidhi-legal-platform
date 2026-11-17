"""One careful way to compare text, used by quote verification, absence scans and the neutral-wording guard.

* `norm` makes two spellings of the same text equal: Unicode NFC, lower case, smart quotes and dashes to plain ones, runs of whitespace to one space, and the INVISIBLE characters
  removed (zero-width and bidirectional controls, soft hyphen, word joiner). The invisible set is the same one `lib/safety.fence` removes before the model sees a document, so a
  quote the model copies from what it was shown matches the stored page. Nothing else is forgiven: look-alike letters and full-width digits stay different.
* `bounded_find` finds a quote only as whole words and whole numbers: "Rs 40,000" is not found inside "Rs 40,000,000", and "0,000" is not found inside "1,00,000".
* `supports` asks whether a quoted passage can really back a claim: every figure in the claim must be on the cited page, and more than half of the claim's distinctive words must
  be near the quote. It cannot prove a claim, it only refuses boilerplate quotes that say nothing about it."""

import re
import unicodedata

MIN_QUOTE = 12  # characters; shorter "quotes" prove nothing
MIN_SUBSTANCE = 8  # letters and digits a quote must contain ("____________" proves nothing)
WINDOW = 400  # characters either side of a quote that count as "near" it

INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿­᠎]")
_PLAIN = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
STOP = set(
    "that this with from have were been there their which would about into also than then they them your will shall such each other what when where whom whose these those does done being "
    "between under over after before while upon said some more most very much many only just like even still both either neither because since until against among within without "
    # words that only frame a comparison between documents ("the first document says ... the second says ...") and carry no fact of their own
    "first second third document documents says states stated describes described differ differs differently agree agrees passage passages quoted".split()
)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = INVISIBLE.sub("", s).translate(_PLAIN)
    return re.sub(r"\s+", " ", s).strip().lower()


def fold_digits(s: str) -> str:
    """Digits of any script to 0-9 (so 5,00,000 and ५,००,००० compare equal where that is wanted)."""
    return "".join(str(unicodedata.digit(c)) if c.isdigit() and not c.isascii() and unicodedata.digit(c, None) is not None else c for c in s)


def wordchar(c: str) -> bool:
    return unicodedata.category(c)[0] in "LMN"


def substance(q: str) -> int:
    return sum(1 for c in q if wordchar(c))


def bounded_find(hay: str, needle: str, start: int = 0) -> int:
    """Index of `needle` in `hay` as whole words/numbers (both already normalised), or -1."""
    if not needle:
        return -1
    pos = start
    while True:
        i = hay.find(needle, pos)
        if i < 0:
            return -1
        j = i + len(needle)
        before, after = (hay[i - 1] if i else ""), (hay[j] if j < len(hay) else "")
        ok = True
        if before and wordchar(needle[0]) and wordchar(before):
            ok = False
        if after and wordchar(needle[-1]) and wordchar(after):
            ok = False
        if needle[-1].isdigit() and after in (",", ".") and j + 1 < len(hay) and hay[j + 1].isdigit():
            ok = False
        if needle[0].isdigit() and before in (",", ".") and i >= 2 and hay[i - 2].isdigit():
            ok = False
        if ok:
            return i
        pos = i + 1


def locate(quote: str, pages: list[str]) -> dict | None:
    """Where a quote is in a document: {"page", "start", "end", "text"} (text = the normalised page, or all pages joined when the quote crosses a page break), or None."""
    q = norm(quote)
    if len(q) < MIN_QUOTE or substance(q) < MIN_SUBSTANCE:
        return None
    npages = [norm(p) for p in pages]
    for n, p in enumerate(npages, start=1):
        k = bounded_find(p, q)
        if k >= 0:
            return {"page": n, "start": k, "end": k + len(q), "text": p}
    joined = " ".join(npages)
    k = bounded_find(joined, q)
    if k < 0:
        return None
    offset = 0
    for n, p in enumerate(npages, start=1):
        if k < offset + len(p) + 1:
            return {"page": n, "start": k, "end": k + len(q), "text": joined}
        offset += len(p) + 1
    return {"page": len(npages), "start": k, "end": k + len(q), "text": joined}


def numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "").rstrip(".") for m in _NUMBER.finditer(fold_digits(norm(text)))}


def _words(text: str) -> list[str]:
    out, cur = [], []
    for c in norm(text):
        if unicodedata.category(c)[0] in "LM":
            cur.append(c)
        else:
            if cur:
                out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def distinctive_stems(text: str) -> set[str]:
    """First five letters of each word that carries meaning (4+ letters, or 3+ outside the Latin alphabet), minus common filler words."""
    stems = set()
    for w in _words(text):
        if w in STOP:
            continue
        if len(w) >= (4 if w.isascii() else 3):
            stems.add(w[:5])
    return stems


# Two separate questions, so one kind of word cannot hide the other: words that turn a rule round, and words that carve an exception out of it. "no" is not a negator in
# "Case No. 5" / "no 7". "shall not charge" and "is prohibited from charging" agree; "may charge ... unless damaged" against either of them differs on the first question.
_NEGATION = re.compile(r"\b(?:not|never|none|nothing|neither|nor|cannot|prohibit\w*|forbid\w*)\b|n't\b|\bno\b(?!\.?\s*\d)")
_EXCEPTION = re.compile(r"\b(?:unless|except|without)\b|\bonly if\b")


def _mostly_latin(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and sum(1 for c in letters if c.isascii()) / len(letters) > 0.9


def polarity_differs(claim_text: str, passages: list[tuple[str, int, int]]) -> bool:
    """True when the claim and the quoted words disagree on whether they SAY a thing is so or is not so ("a lender may charge a fee" quoted from "a lender shall not charge any fee").
    English only: in other scripts there is no reliable word list, so it says False there. It can only add a caution; it never makes a claim more verified."""
    quoted = " ".join(t[s:e] for t, s, e in passages)
    claim = norm(claim_text)
    if not quoted.strip() or not _mostly_latin(claim) or not _mostly_latin(quoted):
        return False
    quoted = norm(quoted)
    negation = bool(_NEGATION.search(claim)) != bool(_NEGATION.search(quoted))
    exception = bool(_EXCEPTION.search(claim)) != bool(_EXCEPTION.search(quoted))
    return negation or exception


# Words for the two sides of a deal or a case. A claim that names one side where the quoted words name the other has the right words and the wrong party.
_ROLE_PAIRS = ("landlord lessor", "tenant lessee", "buyer purchaser vendee", "seller vendor", "employer", "employee workman", "borrower", "lender creditor", "debtor",
               "plaintiff", "defendant", "petitioner appellant", "respondent", "complainant", "accused", "husband", "wife", "licensor", "licensee", "mortgagor", "mortgagee", "payer drawer", "payee")
_ROLE_OF = {w: i for i, group in enumerate(_ROLE_PAIRS) for w in group.split()}
# A party counts only when it is the one acting or being described ("the landlord may ...", "the tenant is ..."), not when it is only mentioned ("return it to the lender").
_ACTING = re.compile(r"\b(" + "|".join(sorted(_ROLE_OF, key=len, reverse=True)) + r")s?(?:\s+[a-z]+){0,2}\s+(?:may|shall|must|can|cannot|will|should|could|would|is|are|has|have|does|did)\b")


def roles_differ(claim_text: str, passages: list[tuple[str, int, int]]) -> bool:
    """True when the party doing the thing in the claim is not the party doing it in the quoted words, and the quoted words have an acting party the claim does not: the same words about the
    other side ("the landlord may end the lease" quoted for "the tenant may end the lease"). A party that is only mentioned, not acting, does not count. Can only add a caution."""
    quoted = norm(" ".join(t[s:e] for t, s, e in passages))
    claim = norm(claim_text)
    in_claim = {_ROLE_OF[m.group(1)] for m in _ACTING.finditer(claim)}
    in_quote = {_ROLE_OF[m.group(1)] for m in _ACTING.finditer(quoted)}
    return bool(in_claim - in_quote) and bool(in_quote - in_claim)


def supports(claim_text: str, passages: list[tuple[str, int, int]]) -> bool:
    """passages: [(normalised page text, start, end)] for each valid citation. See the module docstring for the rule."""
    if not passages:
        return False
    page_numbers = set().union(*(numbers(t) for t, _, _ in passages))
    if not numbers(claim_text) <= page_numbers:
        return False
    wanted = distinctive_stems(claim_text)
    if not wanted:
        return True
    near = set()
    for text, s, e in passages:
        near |= distinctive_stems(text[max(0, s - WINDOW): e + WINDOW])
    return len(wanted & near) / len(wanted) > 0.5  # MORE than half: with two distinctive words, both must be there
