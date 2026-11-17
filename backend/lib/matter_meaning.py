"""Choosing passages from ONE matter's documents by meaning, for Research on a matter larger than the reading budget. OFF by default.

Why: when a matter has more text than the model can be shown, passages are chosen by matching words (lib/matter_context.py). A question that shares no word with the passage that answers it
("Was the payment late?" against "The remittance is overdue") then misses it, and so does a question in Hindi about an English document. This module ranks the passages by meaning with the local
model of lib/embeddings.py, and lib/matter_context.select_context fuses that rank with the word rank.

Rules:
- Needs the model (EMBEDDINGS_ENABLED and its files) AND its own switch EMBEDDINGS_MATTER_ENABLED, because it runs the model over client documents.
- The model runs on this machine. Passages and their vectors are kept only in this process's memory (keyed by a hash of the passage, so a repeated question is quick) and are never written to disk,
  a database or a log, and never sent anywhere.
- It only re-orders passages. Which documents were read, and the coverage report the verifier relies on, are worked out the same way as before.
- Any failure, an empty question, or a matter too large to embed in one request means "no meaning order": the word ranking is used, exactly as before. The question and the text are never logged."""

import asyncio
import hashlib
import logging
import os

from lib import embeddings

logger = logging.getLogger("vidhi.embeddings")

MAX_CHUNKS = 200  # about 300,000 characters. Measured on a laptop CPU: the FIRST question on a matter of 60 passages took 5.3 s, 200 passages 12 s; later questions on the same matter 0.01 s
# (vectors are kept in memory). A larger matter keeps the word ranking only, so no request waits much longer than that.
CACHE_MAX = 20_000
_cache: dict[str, object] = {}  # sha256 of a passage -> its vector, in memory only
_TRUE = ("1", "true", "yes", "on")


def enabled() -> bool:
    return embeddings.enabled() and os.environ.get("EMBEDDINGS_MATTER_ENABLED", "").strip().lower() in _TRUE


def _vectors(texts: list[str]):
    import numpy as np

    keys = [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]
    todo = [i for i, k in enumerate(keys) if k not in _cache]
    if todo:
        vecs = embeddings._get_embedder().embed([texts[i][: embeddings.PASSAGE_CHARS] for i in todo], "passage: ")
        if len(_cache) + len(todo) > CACHE_MAX:
            _cache.clear()
        for i, v in zip(todo, vecs):
            _cache[keys[i]] = v
    return np.vstack([_cache[k] for k in keys])


def _order(question: str, texts: list[str]) -> list[int]:
    import numpy as np

    mat = _vectors(texts)
    q = embeddings._get_embedder().embed([question.strip()[:300]], "query: ")[0]
    return [int(i) for i in np.argsort(-(mat @ q), kind="stable")]


async def passage_order(question: str, texts: list[str]) -> list[int] | None:
    """Indexes of `texts` best first by meaning, or None (switched off, nothing to rank, too many passages, or any failure)."""
    if not enabled() or not (question or "").strip() or not texts or len(texts) > MAX_CHUNKS:
        return None
    try:
        return await asyncio.to_thread(_order, question, texts)
    except Exception as exc:  # noqa: BLE001
        logger.error("meaning-based passage choice failed (%s); word ranking only", type(exc).__name__)
        return None
