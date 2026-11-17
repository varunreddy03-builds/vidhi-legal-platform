"""An INDEPENDENT auditor for /research answers.

It is written from the project's documented rules (CLAUDE.md rules 1 and 2, the docstrings of lib/verify.py and lib/textmatch.py), NOT by calling the app's own matching code, so a
mistake in the app and a mistake in the test cannot cancel each other out. For every claim in a scripted model reply it works out, from the documents alone, what status the app must
give, and `audit` compares that with what the app actually returned. It also re-checks the whole response (disclaimer, neutral wording in every language it knows, citation flags,
review flags), so it judges the app's OUTPUT, not the test's intention.

Rules it encodes:
* Text is compared after: Unicode NFC, lower-casing, smart quotes and dashes to plain ones, invisible characters removed (zero-width and bidirectional controls, soft hyphen,
  word joiner), runs of whitespace collapsed. Nothing else is forgiven: look-alike letters and full-width digits stay different.
* A quote proves nothing if shorter than 12 characters after that, if it has fewer than 8 letters or digits, or if it is found only as a fragment of a longer word or number (a
  quote ending "Rs 40,000" does not match "Rs 40,000,000", and "0,000" does not match inside "1,00,000").
* A factual claim is VERIFIED only if: some matter citation names an existing document that really contains the quote; EVERY matter citation does; the reply says the passage supports
  the claim; every figure in the claim is on the cited page and more than half of the claim's distinctive words (the first five letters of each word of 4+ letters, or 3+ outside
  the Latin alphabet) are within 400 characters of the quote; the claim is not worded as "there is no X" (that needs a search); and the whole matter was read (total text within the
  context budget). A valid quote that fails any of those is PARTIALLY_VERIFIED; no valid quote is UNSUPPORTED.
* "There is no X" is VERIFIED only if none of the search terms (3+ characters, 2+ outside the Latin alphabet; digits of any script read as 0-9) occurs anywhere in any document or the
  matter's own records (terms of 4 characters or fewer must match whole words), no term was too short to search, and at least one term appears in the claim's own wording. A hit makes it
  UNSUPPORTED. Reading budget does not matter: the search is done by code over every document.
* Law is never VERIFIED without a reviewed library entry; these tests have none, so every LEGAL claim is UNSUPPORTED.
* A procedural suggestion is never VERIFIED."""

import re
import unicodedata

MIN_QUOTE = 12
MIN_SUBSTANCE = 8
BUDGET = 80_000
PAGE = 2800  # a text or Word file is read in slices of about this many characters, cut at whitespace
WINDOW = 400
KINDS = ("LEGAL", "FACTUAL", "PROCEDURAL", "ABSENCE")
INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿­᠎]")
PLAIN = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})
FILLER = set(
    "that this with from have were been there their which would about into also than then they them your will shall such each other what when where whom whose these those does done being "
    "between under over after before while upon said some more most very much many only just like even still both either neither because since until against among within without".split()
)
NEGATIVE = re.compile(
    r"\b(there (is|are|was|were) no|no [\w\s]{0,40} (in|among|within|on) the (file|matter|documents?|record)s?|not (mentioned|recorded|found|present|contained|included)|"
    r"nothing (in|about|on)|does not (mention|contain|include|say)|did not (mention|contain|include))\b",
    re.I,
)

# words that accuse or judge honesty, in the languages the product supports
ACCUSATION_LATIN = re.compile(r"\b(lied|lies|lying|liar|liars|perjur\w*|dishonest\w*|deceiv\w*|deceit\w*|fraudulent\w*|fraudster\w*|cheat\w*|swindl\w*)\b", re.I)
ACCUSATION_OTHER = ["झूठ", "धोखा", "धोखाधड़ी", "बेईमान", "फसवणूक", "खोटे बोल", "అబద్ధ", "మోసం", "మోసగాడు", "பொய்", "மோசடி", "ಸುಳ್ಳು", "ವಂಚನೆ", "നുണ", "വഞ്ചന", "মিথ্যা", "প্রতারণা", "જૂઠ", "છેતરપિંડી", "ਝੂਠ", "ਧੋਖਾ", "جھوٹ", "دھوکہ", "دھوکا"]
# class words that make a search term match a document by its type; the generators avoid these as absence terms
CLASS_WORDS = {"whatsapp", "chat", "chats", "messages", "message", "cctv", "footage", "video", "bank statement", "statement of account", "fir", "police report", "contract", "agreement",
               "forensic", "fingerprint", "fingerprints", "post-mortem", "postmortem", "autopsy", "medical", "court order", "letter"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = INVISIBLE.sub("", s).translate(PLAIN)
    return re.sub(r"\s+", " ", s).strip().lower()


def fold(s: str) -> str:
    return "".join(str(unicodedata.digit(c)) if c.isdigit() and not c.isascii() and unicodedata.digit(c, None) is not None else c for c in s)


def _wordchar(c: str) -> bool:
    return unicodedata.category(c)[0] in "LMN"


def find_bounded(d: str, q: str) -> int:
    start = 0
    while True:
        i = d.find(q, start)
        if i < 0:
            return -1
        j = i + len(q)
        before, after = (d[i - 1] if i else ""), (d[j] if j < len(d) else "")
        ok = True
        if before and _wordchar(q[0]) and _wordchar(before):
            ok = False
        if after and _wordchar(q[-1]) and _wordchar(after):
            ok = False
        if q[-1].isdigit() and after in (",", ".") and j + 1 < len(d) and d[j + 1].isdigit():
            ok = False
        if q[0].isdigit() and before in (",", ".") and i >= 2 and d[i - 2].isdigit():
            ok = False
        if ok:
            return i
        start = i + 1


def paginate(text: str) -> list[str]:
    if not text:
        return [""]
    pages, i, n = [], 0, len(text)
    while i < n:
        end = min(i + PAGE, n)
        if end < n:
            cut = None
            for m in re.finditer(r"\s", text[i + PAGE // 2: end]):
                cut = m.start()
            if cut is not None:
                end = i + PAGE // 2 + cut
        pages.append(text[i:end])
        i = end
    return pages


def locate(doc_text: str, quote: str):
    """(normalised page text, start, end) where the quote sits, or None. Pages are the slices the app reads; a quote may also cross a slice boundary."""
    q = norm(quote)
    if len(q) < MIN_QUOTE or sum(1 for c in q if _wordchar(c)) < MIN_SUBSTANCE:
        return None
    pages = [norm(p) for p in paginate(doc_text)]
    for p in pages:
        k = find_bounded(p, q)
        if k >= 0:
            return p, k, k + len(q)
    joined = " ".join(pages)
    k = find_bounded(joined, q)
    return (joined, k, k + len(q)) if k >= 0 else None


def numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "").rstrip(".") for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", fold(norm(text)))}


def stems(text: str) -> set[str]:
    out, cur = set(), []

    def flush():
        w = "".join(cur)
        if w and w not in FILLER and len(w) >= (4 if w.isascii() else 3):
            out.add(w[:5])

    for c in norm(text):
        if unicodedata.category(c)[0] in "LM":
            cur.append(c)
        else:
            flush()
            cur = []
    flush()
    return out


def backed(claim_text: str, hits: list) -> bool:
    if not hits:
        return False
    if not numbers(claim_text) <= set().union(*(numbers(p) for p, _, _ in hits)):
        return False
    wanted = stems(claim_text)
    if not wanted:
        return True
    near = set().union(*(stems(p[max(0, s - WINDOW): e + WINDOW]) for p, s, e in hits))
    return len(wanted & near) / len(wanted) > 0.5


def doc_index(ref, n_docs: int, filenames: list[str]) -> int | None:
    """0-based index of the document a reference names, or None."""
    r = str(ref or "").strip()[:80]
    m = re.fullmatch(r"(?i)\[?doc[\s_-]*0*(\d+)\]?", r)
    if m:
        k = int(m.group(1))
        return k - 1 if 1 <= k <= n_docs else None
    for i, f in enumerate(filenames):
        if r.lower() == f.lower():
            return i
    return None


def expected_claim(claim: dict, docs: list[str], filenames: list[str], complete: bool, records: list[str] | None = None) -> dict:
    kind = str(claim.get("claim_kind", "")).upper()
    kind = kind if kind in KINDS else ("FACTUAL" if docs else "LEGAL")
    supports = str(claim.get("supports", "")).upper() == "YES"
    cites = [c for c in (claim.get("citations") or []) if isinstance(c, dict)]
    flags, hits = [], []
    for c in cites:
        if str(c.get("source", "")).upper() == "LIBRARY":
            flags.append(False)
            continue
        i = doc_index(c.get("ref"), len(docs), filenames)
        hit = locate(docs[i], str(c.get("quote") or "")[:800]) if i is not None else None
        flags.append(bool(hit))
        if hit:
            hits.append(hit)
    matter_flags = [f for f, c in zip(flags, cites) if str(c.get("source", "")).upper() != "LIBRARY"]
    valid, all_valid = any(matter_flags), all(matter_flags)
    text = str(claim.get("text", ""))
    if kind == "ABSENCE":
        raw = [fold(norm(t)) for t in (claim.get("search_terms") or []) if isinstance(t, str) and t.strip()][:8]
        terms = [t for t in raw if len(t) >= (3 if t.isascii() else 2)]
        short = [t for t in raw if len(t) < (3 if t.isascii() else 2)]
        if not docs:
            status = "PARTIALLY_VERIFIED"
        elif not terms:
            status = "UNSUPPORTED"
        else:
            hay = [fold(norm(f"{f} {d}")) for f, d in zip(filenames, docs)] + [fold(norm(r)) for r in (records or [])]

            def hit_term(t: str, h: str) -> bool:
                return (find_bounded(h, t) >= 0) if (len(t) <= 4 and t.isascii()) else (t in h)

            if any(hit_term(t, h) for t in terms for h in hay):
                status = "UNSUPPORTED"
            elif short:
                status = "PARTIALLY_VERIFIED"
            elif not any(t in fold(norm(text)) for t in terms):
                status = "PARTIALLY_VERIFIED"
            else:
                status = "VERIFIED"
        return {"kind": "ABSENCE", "status": status, "citation_flags": flags}
    if kind == "LEGAL":
        return {"kind": kind, "status": "UNSUPPORTED", "citation_flags": flags}
    if kind == "PROCEDURAL":
        return {"kind": kind, "status": "PARTIALLY_VERIFIED" if valid else "UNSUPPORTED", "citation_flags": flags}
    if not valid:
        return {"kind": kind, "status": "UNSUPPORTED", "citation_flags": flags}
    good = supports and all_valid and backed(text, hits) and not NEGATIVE.search(text) and complete
    return {"kind": kind, "status": "VERIFIED" if good else "PARTIALLY_VERIFIED", "citation_flags": flags}


def accuses(text: str) -> list[str]:
    t = unicodedata.normalize("NFKC", INVISIBLE.sub("", text or ""))
    found = [m.group(0) for m in ACCUSATION_LATIN.finditer(t)]
    found += [w for w in ACCUSATION_OTHER if w in t]
    return found


def audit(case: dict, response: dict, records: list[str] | None = None) -> list[str]:
    """Problems found in the app's response for this case; an empty list means the app was right on every check."""
    docs, names = case["documents"], [f"doc{i}.txt" for i in range(1, len(case["documents"]) + 1)]
    complete = sum(len(d) for d in docs) <= BUDGET
    gold_claims = [c for c in case["gold"]["claims"] if isinstance(c, dict) and isinstance(c.get("text"), str) and c["text"].strip()]
    problems: list[str] = []
    got = response.get("claims", [])
    if len(got) != len(gold_claims):
        return [f"the app returned {len(got)} claims for {len(gold_claims)} proposed"]
    for i, (g, r) in enumerate(zip(gold_claims, got)):
        exp = expected_claim(g, docs, names, complete, records)
        if r.get("verification_status") != exp["status"]:
            problems.append(f"claim {i} ({exp['kind']}): app said {r.get('verification_status')}, the documents require {exp['status']}")
        want_review = r.get("verification_status") != "VERIFIED" or exp["kind"] == "PROCEDURAL"
        if bool(r.get("human_review_required")) != want_review:
            problems.append(f"claim {i}: human_review_required is {r.get('human_review_required')}")
        if not str(r.get("note") or "").strip():
            problems.append(f"claim {i}: no plain-language note")
        cites = [c for c in (g.get("citations") or []) if isinstance(c, dict)][:12]
        shown = r.get("citations", [])
        if len(shown) != len(cites):
            problems.append(f"claim {i}: {len(shown)} citations shown for {len(cites)} given")
        else:
            for k, (flag, c, s) in enumerate(zip(exp["citation_flags"], cites, shown)):
                if str(c.get("source", "")).upper() != "LIBRARY" and bool(s.get("quote_verified")) != flag:
                    problems.append(f"claim {i} citation {k}: quote_verified is {s.get('quote_verified')}, the document says {flag}")
        if r.get("verification_status") == "VERIFIED" and exp["kind"] == "LEGAL":
            problems.append(f"claim {i}: law shown as VERIFIED with no reviewed library entry")
    if "not legal advice" not in str(response.get("disclaimer", "")).lower():
        problems.append("the not-legal-advice disclaimer is missing")
    if not str(response.get("answer", "")).strip():
        problems.append("the answer is empty")
    for where, text in [("answer", response.get("answer", ""))] + [(f"claim {i} text", c.get("text", "")) for i, c in enumerate(got)]:
        bad = accuses(text)
        if bad:
            problems.append(f"{where} still contains accusing wording: {bad[:3]}")
    return problems
