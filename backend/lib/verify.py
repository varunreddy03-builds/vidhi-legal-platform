"""Claim verification, decided in CODE. The model proposes; this module disposes.

A claim is VERIFIED only when the exact source text exists (a verified-library entry for law, a quoted
passage in the matter's own documents for facts), the quote really bears on the claim (its figures and most of its
distinctive words are in or near the quoted passage), EVERY citation given checks out, the whole matter was checked
(coverage complete, nothing unread) and nothing in the documents conflicts. For "there is no X" claims the only
acceptable proof is an exhaustive scan of every document for the terms the claim names - never a single quote. The
model's own opinion can lift a claim at most to PARTIALLY_VERIFIED; it can never make one VERIFIED on its own.
Text comparison rules (what counts as the same text) live in lib/textmatch.py.
"""

import re

from lib import textmatch
from lib.library import norm_text
from lib.textmatch import MIN_QUOTE  # noqa: F401  (re-exported: other modules import it from here)

# Search terms that also match a document CLASS (so "whatsapp"/"chat" finds a chat export even if the word
# never appears in its text).
CLASS_ALIASES: dict[str, set[str]] = {
    "whatsapp": {"CHAT"}, "chat": {"CHAT"}, "chats": {"CHAT"}, "messages": {"CHAT"}, "message": {"CHAT"},
    "cctv": {"CCTV_LOG"}, "footage": {"CCTV_LOG"}, "video": {"CCTV_LOG"},
    "bank statement": {"BANK_STATEMENT"}, "statement of account": {"BANK_STATEMENT"},
    "fir": {"FIR_POLICE"}, "police report": {"FIR_POLICE"},
    "contract": {"CONTRACT"}, "agreement": {"CONTRACT"},
    "forensic": {"FORENSIC_REPORT"}, "fingerprint": {"FORENSIC_REPORT"}, "fingerprints": {"FORENSIC_REPORT"},
    "post-mortem": {"MEDICAL"}, "postmortem": {"MEDICAL"}, "autopsy": {"MEDICAL"}, "medical": {"MEDICAL"},
    "court order": {"COURT_ORDER"}, "letter": {"LETTER"},
}

# A FACTUAL claim worded as "there is no X" cannot be verified by a quote: only the exhaustive scan of an ABSENCE claim can show it.
NEGATIVE_CLAIM = re.compile(
    r"\b(there (is|are|was|were) no|no [\w\s]{0,40} (in|among|within|on) the (file|matter|documents?|record)s?|not (mentioned|recorded|found|present|contained|included)|"
    r"nothing (in|about|on)|does not (mention|contain|include|say)|did not (mention|contain|include))\b",
    re.I,
)
SHORT_LATIN_TERM = 4  # search terms this short (after normalising) match whole words only, so "FIR" is not "first"


def find_quote(quote: str, pages: list[str]) -> int | None:
    """1-based page number whose text contains `quote` as whole words/numbers (after normalising), also across a page break; None if absent or the quote proves nothing."""
    hit = textmatch.locate(quote, pages)
    return hit["page"] if hit else None


def locate_quote(quote: str, pages: list[str]) -> dict | None:
    return textmatch.locate(quote, pages)


def resolve_doc(ref: str, corpus: list[dict]) -> dict | None:
    """Find a document from a model-given reference: 'DOC-08', 'doc 8', a document id or an exact filename."""
    if not ref:
        return None
    r = str(ref).strip()[:80]
    m = re.fullmatch(r"(?i)\[?doc[\s_-]*0*(\d{1,6})\]?", r)
    if m:
        want = f"DOC-{int(m.group(1)):02d}"
        return next((d for d in corpus if d["label"] == want), None)
    for d in corpus:
        if r == d["id"] or r.lower() == d["filename"].lower():
            return d
    return None


def _normalised(d: dict) -> tuple[str, str]:
    """The document's file name + description and its text, normalised once and kept on the corpus entry."""
    if "_norm" not in d:
        fold = lambda s: textmatch.fold_digits(norm_text(s))  # noqa: E731
        d["_norm"] = (fold(f"{d['filename']} {d['description']}"), fold(" ".join(d["pages"])))
    return d["_norm"]


def _term_hits(term: str, hay: str) -> bool:
    if not term:
        return False
    if len(term) <= SHORT_LATIN_TERM and term.isascii():
        return textmatch.bounded_find(hay, term) >= 0
    return term in hay


def absence_scan(terms: list[str], corpus: list[dict], extra_texts: list[str] | None = None, claim_text: str | None = None) -> dict:
    """Search EVERY document (filename, class, description, all page text) and the recorded matter facts for each term.

    Returns {terms, hits, searched, unsearchable, uncertain, short_terms, unlinked}. `short_terms` were too short to search; `unlinked` means none of the terms appears in the claim's own
    wording, so the search does not show what the claim says."""
    clean, short = [], []
    for t in terms:
        if not isinstance(t, str) or not t.strip():
            continue
        n = textmatch.fold_digits(norm_text(t))
        (clean if len(n) >= (3 if n.isascii() else 2) else short).append(n)
    hits = []
    for d in corpus:
        hay_meta, hay_text = _normalised(d)
        for t in clean:
            where = None
            if _term_hits(t, hay_meta):
                where = "file name / description"
            elif _term_hits(t, hay_text):
                where = "document text"
            elif d["doc_class"] in CLASS_ALIASES.get(t, set()):
                where = f"document type ({d['doc_class']})"
            if where:
                hits.append({"doc": d["label"], "filename": d["filename"], "term": t, "where": where})
    for text in extra_texts or []:
        nt = textmatch.fold_digits(norm_text(text))
        for t in clean:
            if _term_hits(t, nt):
                hits.append({"doc": "RECORDED", "filename": "recorded fact / evidence item", "term": t, "where": "matter records"})
    claim_norm = textmatch.fold_digits(norm_text(claim_text)) if claim_text is not None else None
    return {
        "terms": clean,
        "short_terms": short,
        "unlinked": bool(claim_norm is not None and clean and not any(t in claim_norm for t in clean)),
        "hits": hits,
        "searched": len(corpus),
        "unsearchable": [f"{d['label']} {d['filename']}" for d in corpus if not d["text_available"]],
        "uncertain": [f"{d['label']} {d['filename']}" for d in corpus if d.get("uncertain_pages")],  # read with low confidence, an empty page or unreadable words
    }


# The library holds the WORDS of a provision, not whether it is the law today. A claim that says it is in force, or that rests on a repealed code, goes beyond what the quote shows.
IN_FORCE_CLAIM = re.compile(r"\b(in force|currently|presently|at present|still (applies|applicable|valid|good law|the law|in effect)|good law|today|is the law|present law|current law|in effect|applies now|operative)\b", re.I)
REPEALED_MARK = re.compile(r"\b(repealed|omitted|ceased|superseded|replaced by)\b|\b(?:Indian Penal Code|IPC|Code of Criminal Procedure|CrPC|Cr\.P\.C|Indian Evidence Act)\b", re.I)
IN_FORCE_NOTE = "the library shows the words of the provision, not whether it is in force today, so check its current status"
OLD_CODE_CAP_NOTE = "this is from an older code (or a provision marked repealed): the Bharatiya Nyaya Sanhita, Bharatiya Nagarik Suraksha Sanhita and Bharatiya Sakshya Adhiniyam exist, so a person must check which law applies"


def cap_for_currency(status: str, note: str, claim_text: str, entry: dict | None) -> tuple[str, str]:
    """A VERIFIED legal claim becomes PARTIALLY_VERIFIED when it says the law is in force, or when its source is an older code or marked repealed. Never raises a status."""
    if status != "VERIFIED":
        return status, note
    marks = " ".join(str(entry.get(k) or "") for k in ("citation", "title", "version", "source_name")) if entry else ""
    if REPEALED_MARK.search(marks):
        return "PARTIALLY_VERIFIED", f"Source text is in the verified library, but {OLD_CODE_CAP_NOTE}" + ("; also " + IN_FORCE_NOTE if IN_FORCE_CLAIM.search(claim_text or "") else "") + "."
    if IN_FORCE_CLAIM.search(claim_text or ""):
        return "PARTIALLY_VERIFIED", f"Source text is in the verified library, but {IN_FORCE_NOTE}."
    return status, note


def decide(
    kind: str,
    *,
    valid_matter_quote: bool,
    valid_library_quote: bool,
    supports: str,
    coverage_complete: bool,
    has_matter: bool,
    conflicts: list[dict],
    absence: dict | None,
    quote_on_uncertain_page: bool = False,
    all_citations_valid: bool = True,
    claim_backed: bool = True,
    unread: list[str] | None = None,
    uncertain_elsewhere: bool = False,
    negative_claim: bool = False,
    polarity_differs: bool = False,
    roles_differ: bool = False,
    instruction_quote: bool = False,
) -> tuple[str, str]:
    """(status, plain-language note). status in VERIFIED | PARTIALLY_VERIFIED | UNSUPPORTED."""
    yes = supports == "YES"
    if kind == "ABSENCE":
        if not absence or not absence["terms"]:
            return "UNSUPPORTED", "No search terms were given, so this could not be checked against the documents."
        if absence["hits"]:
            h = absence["hits"][0]
            more = f" (+{len(absence['hits']) - 1} more)" if len(absence["hits"]) > 1 else ""
            return "UNSUPPORTED", f"Contradicted: the matter does contain material matching this - {h['doc']} {h['filename']} ({h['where']}){more}."
        searched = "; ".join(f"'{t}'" for t in absence["terms"])
        if absence.get("short_terms"):
            return "PARTIALLY_VERIFIED", f"Nothing matched {searched}, but these search terms were too short to search: {', '.join(absence['short_terms'])}."
        if absence.get("uncertain"):
            return "PARTIALLY_VERIFIED", "Nothing matched, but these documents have pages that were read with low confidence or could not be read, so the absence is not certain: " + ", ".join(absence["uncertain"]) + "."
        if absence.get("unlinked"):
            return "PARTIALLY_VERIFIED", f"Nothing matched {searched}, but none of those search terms appears in the claim, so check that they cover what it says."
        if coverage_complete and not absence["unsearchable"]:
            return "VERIFIED", f"Searched all {absence['searched']} document(s) in the matter for {searched}; nothing matched."
        why = (
            "these have no readable text: " + ", ".join(absence["unsearchable"])
            if absence["unsearchable"]
            else "not every document could be searched"
        )
        return "PARTIALLY_VERIFIED", f"Nothing matched in the documents that could be searched, but {why}."

    def common_gaps() -> list[str]:
        gaps = []
        if not yes:
            gaps.append("the source's support for the claim is not certain" if kind == "LEGAL" else "the passage may not fully support the claim")
        if not claim_backed:
            gaps.append("the quoted passage does not contain the figures or most of the words of the claim, so it may not support it")
        if not all_citations_valid:
            gaps.append("at least one other citation given could not be found")
        if polarity_differs:
            gaps.append("the claim and the quoted words differ on whether something is or is not so (for example one says \"not\" and the other does not), so read the quote itself")
        if roles_differ:
            gaps.append("the claim names a different party from the quoted words (for example the tenant where the quote says the landlord), so read the quote itself")
        if instruction_quote:
            gaps.append("the quoted words are an instruction to an AI, not a fact; a document cannot verify anything by telling the checker to")
        return gaps

    if kind == "LEGAL":
        if not valid_library_quote:
            return "UNSUPPORTED", "No verified law source in the library backs this - a lawyer must check it."
        gaps = common_gaps()
        if not has_matter:
            gaps.append("it is not tied to a matter, so it was not checked against any documents")
        else:
            if not coverage_complete:
                gaps.append("not every matter document was fully read")
            if unread:
                gaps.append("these documents were not read (no text): " + ", ".join(unread))
            if uncertain_elsewhere:
                gaps.append("some pages were read with low confidence, so a conflicting passage could have been missed")
        if conflicts:
            gaps.append("a matter document conflicts with it")
        if not gaps:
            return "VERIFIED", "Exact text found in the verified law library and checked against every matter document."
        return "PARTIALLY_VERIFIED", "Source text is in the verified library, but " + "; ".join(gaps) + "."

    if kind == "FACTUAL":
        if not valid_matter_quote:
            return "UNSUPPORTED", "No exact passage in the matter documents backs this."
        gaps = common_gaps()
        if negative_claim:
            gaps.append("it says something is absent, which only a search of every document can show (state it as an absence claim with search terms)")
        if quote_on_uncertain_page:
            gaps.append("the passage is on a page that was read from a scan with low confidence or unreadable words, so it must be checked against the original")
        elif uncertain_elsewhere:
            gaps.append("some pages were read with low confidence, so a conflicting passage could have been missed")
        if not coverage_complete:
            gaps.append("not every matter document was fully read")
        if unread:
            gaps.append("these documents were not read (no text): " + ", ".join(unread))
        if conflicts:
            gaps.append("another document says something different (see the conflict)")
        if polarity_differs:
            gaps.append("the claim says the opposite of the quoted passage (one affirms what the other denies), so it must be checked by a person")
        if not gaps:
            return "VERIFIED", "Exact passage found in the documents; every document was read and none conflicts."
        return "PARTIALLY_VERIFIED", "Exact passage found, but " + "; ".join(gaps) + "."

    # PROCEDURAL: a suggested step, never verifiable
    if valid_matter_quote:
        return "PARTIALLY_VERIFIED", "A suggested step grounded in the documents - it still needs a lawyer's judgment."
    return "UNSUPPORTED", "A suggested step, not something that can be verified - for lawyer review."
