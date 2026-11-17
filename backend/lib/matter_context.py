"""Build what the model reads about a matter - ALL of it, or an honest account of what it did not read.

The old research code sent only the first 6 documents, 4 pages each, cut at 24,000 characters, so a document
could be invisible to the model without anyone knowing (this is why "no WhatsApp chat" was answered while
the chat sat in document 08). Rules now:

  * every document appears in a matter index, always (even media with no text)
  * if all text fits the budget, all of it is included, in order
  * if not, EVERY document still gets at least its best-matching passage, the rest of the budget goes to the
    highest-scoring passages, and `coverage` states precisely what was and was not included
  * a claim can only be VERIFIED when coverage is complete (see lib/verify.py)
"""

import math
import os
import re
from collections import Counter

from lib import text as _text

CHUNK_CHARS = 1500
DEFAULT_BUDGET = 80_000

_STOP = {
    "the", "and", "for", "that", "this", "with", "are", "was", "were", "has", "have", "had", "not", "any", "can",
    "may", "what", "which", "who", "whom", "from", "into", "under", "such", "shall", "will", "would", "should",
    "could", "their", "there", "than", "then", "its", "his", "her", "our", "your", "you", "about", "did", "does",
    "how", "when", "where", "why", "next", "step", "steps", "case", "matter",
}


def budget_chars() -> int:
    try:
        return int(os.environ.get("MAX_CONTEXT_CHARS", DEFAULT_BUDGET))
    except ValueError:
        return DEFAULT_BUDGET


def tokens(text: str) -> list[str]:
    return _text.tokens(text)  # any script: Hindi, Tamil, Telugu... as well as English


def label_for(position: int) -> str:
    return f"DOC-{position:02d}"


def build_corpus(docs: list[dict]) -> list[dict]:
    """docs in upload order -> corpus entries with a stable DOC-nn label."""
    corpus = []
    for i, d in enumerate(docs, start=1):
        pages = [p for p in d.get("pages", [])]
        corpus.append(
            {
                "label": label_for(i),
                "id": d["id"],
                "filename": d.get("filename", ""),
                "doc_class": d.get("doc_class", "OTHER"),
                "media_kind": d.get("media_kind", "TEXT"),
                "description": d.get("description", "") or "",
                "pages": pages,
                "uncertain_pages": list(d.get("uncertain_pages", [])),
                "text_available": any((p or "").strip() for p in pages),
            }
        )
    return corpus


def chunk_corpus(corpus: list[dict]) -> list[dict]:
    chunks = []
    for d in corpus:
        for pno, page in enumerate(d["pages"], start=1):
            page = (page or "").strip()
            if not page:
                continue
            paras = re.split(r"\n\s*\n|\n", page)
            cur = ""
            for para in paras:
                if cur and len(cur) + len(para) + 1 > CHUNK_CHARS:
                    chunks.append({"label": d["label"], "page": pno, "text": cur})
                    cur = ""
                while len(para) > CHUNK_CHARS:  # one huge paragraph
                    chunks.append({"label": d["label"], "page": pno, "text": para[:CHUNK_CHARS]})
                    para = para[CHUNK_CHARS:]
                cur = f"{cur}\n{para}".strip() if cur else para
            if cur:
                chunks.append({"label": d["label"], "page": pno, "text": cur})
    return chunks


def score_chunks(chunks: list[dict], question_tokens: list[str]) -> None:
    """Small BM25-style relevance score, stored on each chunk as 'score'."""
    n = max(len(chunks), 1)
    df = Counter()
    toks = []
    for c in chunks:
        t = Counter(tokens(c["text"]))
        toks.append(t)
        for w in t:
            df[w] += 1
    qset = set(question_tokens)
    for c, t in zip(chunks, toks):
        length = sum(t.values()) or 1
        s = 0.0
        for w in qset:
            if w in t:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                tf = t[w]
                s += idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * length / 150))
        c["score"] = s


def index_text(corpus: list[dict]) -> str:
    """One line per document - always included, so the model always knows everything that exists."""
    lines = []
    for d in corpus:
        text_note = (
            f"{len(d['pages'])} page(s) of text"
            if d["text_available"]
            else "NO TEXT AVAILABLE (media or unreadable file)"
        )
        extra = f" | described as: {d['description'][:200]}" if d["description"] else ""
        lines.append(f"[{d['label']}] {d['filename']} | type: {d['doc_class']} | {text_note}{extra}")
    return "\n".join(lines) if lines else "(this matter has no documents)"


RRF_K = 60


def fuse_scores(chunks: list[dict], meaning_order: list[int]) -> None:
    """Replaces each chunk's word score by a reciprocal-rank fusion of its rank by words and its rank by meaning (`meaning_order` = chunk indexes, best first).
    A chunk missing from `meaning_order` gets only its word rank; equal scores keep the original order."""
    by_words = sorted(range(len(chunks)), key=lambda i: (-chunks[i]["score"], i))
    fused = [0.0] * len(chunks)
    for rank, i in enumerate(by_words, 1):
        fused[i] += 1.0 / (RRF_K + rank) if chunks[i]["score"] > 0 else 0.0  # a passage sharing no word with the question gets nothing from the word side
    seen: set[int] = set()
    for i in meaning_order:
        if 0 <= i < len(chunks) and i not in seen:  # out-of-range and repeated indexes are skipped and do not take a rank
            seen.add(i)
            fused[i] += 1.0 / (RRF_K + len(seen))
    for i, c in enumerate(chunks):
        c["score"] = fused[i]


def needs_ranking(corpus: list[dict], budget: int | None = None) -> bool:
    """True when the matter's text is larger than the reading budget, so passages must be chosen (otherwise everything is read and ranking changes nothing)."""
    budget = budget if budget is not None else budget_chars()
    return sum(len(c["text"]) for c in chunk_corpus(corpus)) > budget


def select_context(question: str, corpus: list[dict], budget: int | None = None, meaning_order: list[int] | None = None) -> tuple[str, dict]:
    """(text of passages to show the model, coverage report). `meaning_order`, when given, is the chunk indexes (of chunk_corpus(corpus)) best first by meaning; it is fused with the word
    score to choose passages. It changes only WHICH passages fill the budget: every document still gets its best passage and the coverage report is computed the same way."""
    budget = budget if budget is not None else budget_chars()
    chunks = chunk_corpus(corpus)
    total = sum(len(c["text"]) for c in chunks)
    selected: set[int] = set(range(len(chunks)))
    ranked_by = "all text included"
    if total > budget:
        score_chunks(chunks, tokens(question))
        ranked_by = "words"
        if meaning_order:
            fuse_scores(chunks, meaning_order)
            ranked_by = "words and meaning"
        selected = set()
        used = 0
        # 1) every document gets its best passage, so nothing is entirely unread if it can be avoided
        best: dict[str, int] = {}
        for i, c in enumerate(chunks):
            if c["label"] not in best or c["score"] > chunks[best[c["label"]]]["score"]:
                best[c["label"]] = i
        for i in sorted(best.values(), key=lambda j: -chunks[j]["score"]):
            if used + len(chunks[i]["text"]) <= budget:
                selected.add(i)
                used += len(chunks[i]["text"])
        # 2) the rest of the budget goes to the highest-scoring passages anywhere
        for i in sorted(range(len(chunks)), key=lambda j: -chunks[j]["score"]):
            if i not in selected and used + len(chunks[i]["text"]) <= budget:
                selected.add(i)
                used += len(chunks[i]["text"])

    by_doc_total = Counter(c["label"] for c in chunks)
    by_doc_in = Counter(chunks[i]["label"] for i in selected)
    with_text = [d for d in corpus if d["text_available"]]
    fully = [d for d in with_text if by_doc_in[d["label"]] == by_doc_total[d["label"]]]
    partial = [d for d in with_text if 0 < by_doc_in[d["label"]] < by_doc_total[d["label"]]]
    none = [d for d in with_text if by_doc_in[d["label"]] == 0]
    no_text = [d for d in corpus if not d["text_available"]]

    parts, last_label, last_page = [], None, None
    for i in sorted(selected, key=lambda j: (chunks[j]["label"], chunks[j]["page"], j)):
        c = chunks[i]
        head = f"--- [{c['label']}] page {c['page']} ---"
        if (c["label"], c["page"]) != (last_label, last_page):
            parts.append(head)
        parts.append(c["text"])
        last_label, last_page = c["label"], c["page"]

    coverage = {
        "documents_total": len(corpus),
        "documents_with_text": len(with_text),
        "documents_fully_read": len(fully),
        "documents_partly_read": [f"{d['label']} {d['filename']}" for d in partial],
        "documents_not_read": [f"{d['label']} {d['filename']}" for d in none],
        "documents_without_text": [f"{d['label']} {d['filename']}" for d in no_text],
        "chars_total": total,
        "chars_included": sum(len(chunks[i]["text"]) for i in selected),
        # complete = every document that HAS text was shown to the model in full
        "complete": len(fully) == len(with_text),
        "passages_chosen_by": ranked_by,
    }
    coverage["summary"] = coverage_summary(coverage)
    return "\n".join(parts), coverage


def coverage_summary(c: dict) -> str:
    if c["documents_total"] == 0:
        return "This matter has no documents."
    base = f"Read {c['documents_fully_read']} of {c['documents_with_text']} document(s) with text in full"
    bits = [base]
    if c["documents_partly_read"]:
        bits.append("only parts of: " + ", ".join(c["documents_partly_read"]))
    if c["documents_not_read"]:
        bits.append("NOT read: " + ", ".join(c["documents_not_read"]))
    if c["documents_without_text"]:
        bits.append("no readable text (not analysed): " + ", ".join(c["documents_without_text"]))
    return "; ".join(bits) + "."
