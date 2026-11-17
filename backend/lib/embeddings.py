"""Meaning-based search over the law provisions: an OPTIONAL addition to keyword search, off by default.

Why: a plain question ("What is the punishment for murder?") sometimes shares no word with the provision that answers it, and a question in Hindi shares none with an English provision.
What it is: the multilingual embedding model intfloat/multilingual-e5-small (MIT licence, ONNX file, run on the CPU with onnxruntime). Every provision is turned into a vector once (scripts/embeddings_build.py); a question
is turned into a vector when asked; the nearest provisions are fused with the keyword results by reciprocal rank (see `fuse`).
What it is NOT: it verifies nothing and never says a provision is right. It only widens which unreviewed provisions are SHOWN. Verification stays in lib/verify.py and lib/textmatch.py, untouched. The measured gain is
modest and was measured on 24 questions (docs/evals/embeddings-pilot-2026-11-12.md): English Recall@3 from 79% to 88% and Recall@5 from 92% to 96% when fused with keyword results; embedding alone was WORSE than keyword
search, so it is never used alone.

Re-ranker (a second, separate switch, also off by default): the multilingual cross-encoder BAAI/bge-reranker-v2-m3 (Apache-2.0, ONNX int8) re-orders the FIRST 10 results of the fused list and nothing else: it never adds or
removes a result, never changes a label, and a failure leaves the order as it was. An English-only re-ranker tried first did not meet the adoption rule. This one met every rule that was fixed before it ran, on the same 24 English,
8 Hindi and 8 Telugu questions (docs/evals/reranker-m3-pilot-2026-11-13-top10.md); the sample is small and the Hindi and Telugu wording is unreviewed. Re-ranking 20 candidates met the accuracy rules but took 4.3 s, over
the 3 s limit, so 10 are used (2.1 s on this PC's CPU).

Safety rules:
- Off unless EMBEDDINGS_ENABLED is true AND the model files are present AND the stored vectors match the provisions now in the database (a fingerprint of every provision's id and content hash). A stale or missing store means
  "off", never "guess": keyword search then works exactly as before.
- It can never break a search: any failure is logged (the class of the error, never the question) and keyword results are returned alone.
- This module embeds only provisions: it never reads a matter document or private text, and nothing leaves this machine (no network call). Choosing passages of a matter document
  by meaning is done by a separate module, under its own switch, with the same local model; that module stores nothing."""

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("vidhi.embeddings")

MODEL_NAME = "intfloat/multilingual-e5-small"
RRF_K = 60  # reciprocal rank fusion constant
PASSAGE_CHARS = 1500  # how much of a provision's text is embedded
STORE_VECTORS, STORE_META = "provisions_e5.npy", "provisions_e5.json"
_TRUE = ("1", "true", "yes", "on")


def requested() -> bool:
    return os.environ.get("EMBEDDINGS_ENABLED", "").strip().lower() in _TRUE


def model_dir() -> Path | None:
    d = (os.environ.get("EMBEDDINGS_MODEL_DIR") or "").strip()
    return Path(d) if d else None


def store_dir() -> Path:
    return Path(os.environ.get("EMBEDDINGS_DIR") or Path(__file__).resolve().parent.parent / "data" / "embeddings")


def reranker_dir() -> Path | None:
    d = (os.environ.get("RERANKER_MODEL_DIR") or "").strip()
    return Path(d) if d else None


RERANK_FILE = "onnx/model_int8.onnx"
RERANK_N = 10  # how many of the top results are re-ordered (the measured setting)


def reranker_enabled() -> bool:
    """Meaning-based search is on AND the re-ranker is asked for AND its files exist. Otherwise results keep the fused order."""
    d = reranker_dir()
    return enabled() and os.environ.get("RERANKER_ENABLED", "").strip().lower() in _TRUE and d is not None and (d / RERANK_FILE).exists() and (d / "tokenizer.json").exists()


def enabled() -> bool:
    d = model_dir()
    return requested() and d is not None and (d / "onnx" / "model.onnx").exists() and (d / "tokenizer.json").exists()


# ---------- what is embedded, and the fingerprint that ties vectors to provisions ----------
def passage_text(act: str, p: dict) -> str:
    """The text of one provision as embedded: Act, section, heading, then its own words (`text_full`)."""
    return f"{act} section {p.get('number', '')}: {p.get('heading') or ''}. {(p.get('text_full') or '')[:PASSAGE_CHARS]}"


def fingerprint(provisions: list[dict]) -> str:
    """Changes when a provision is added, removed or its content hash changes: the vectors are valid only for exactly this set."""
    lines = sorted(f"{p['id']}:{p.get('content_sha256', '')}" for p in provisions)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]


# ---------- the model (loaded on first use, kept for the life of the process) ----------
class Embedder:
    def __init__(self, folder: Path) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.tok = Tokenizer.from_file(str(folder / "tokenizer.json"))
        cfg = json.loads((folder / "tokenizer_config.json").read_text(encoding="utf-8"))
        pad = cfg.get("pad_token")
        pad = pad["content"] if isinstance(pad, dict) else (pad or "<pad>")
        self.tok.enable_truncation(max_length=384)
        self.tok.enable_padding(pad_id=self.tok.token_to_id(pad), pad_token=pad)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
        self.sess = ort.InferenceSession(str(folder / "onnx" / "model.onnx"), sess_options=opts, providers=["CPUExecutionProvider"])

    def embed(self, texts: list[str], prefix: str, batch: int = 32):
        import numpy as np

        out = []
        for i in range(0, len(texts), batch):
            enc = self.tok.encode_batch([prefix + t for t in texts[i : i + batch]])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            hidden = self.sess.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)})[0]
            pooled = (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)  # mean over the real tokens
            out.append(pooled / np.linalg.norm(pooled, axis=1, keepdims=True))
        return np.vstack(out)


_embedder: Embedder | None = None


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        d = model_dir()
        if d is None:
            raise RuntimeError("EMBEDDINGS_MODEL_DIR is not set")
        _embedder = Embedder(d)
    return _embedder


def _embed_query(q: str):
    return _get_embedder().embed([q], "query: ")[0]


# ---------- the stored vectors ----------
def build_store(provisions: list[dict], acts: dict[str, str], out_dir: Path | None = None, embedder: Embedder | None = None) -> dict:
    """Embeds every provision and writes the vectors and a small manifest. Returns the manifest."""
    import numpy as np

    out_dir = out_dir or store_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    emb = embedder or _get_embedder()
    ids = [p["id"] for p in provisions]
    matrix = emb.embed([passage_text(acts.get(p.get("instrument_id"), "?"), p) for p in provisions], "passage: ")
    np.save(out_dir / STORE_VECTORS, matrix.astype("float32"))
    meta = {"model": MODEL_NAME, "fingerprint": fingerprint(provisions), "ids": ids}
    (out_dir / STORE_META).write_text(json.dumps(meta), encoding="utf-8")
    return {"provisions": len(ids), "fingerprint": meta["fingerprint"], "dir": str(out_dir)}


def load_store(directory: Path | None = None):
    """(matrix, ids, fingerprint) or None when there is no store."""
    import numpy as np

    d = directory or store_dir()
    if not (d / STORE_VECTORS).exists() or not (d / STORE_META).exists():
        return None
    meta = json.loads((d / STORE_META).read_text(encoding="utf-8"))
    matrix = np.load(d / STORE_VECTORS)
    if meta.get("model") != MODEL_NAME or matrix.shape[0] != len(meta["ids"]):
        return None
    return matrix, meta["ids"], meta["fingerprint"]


def nearest(matrix, ids: list[str], query_vec, k: int) -> list[str]:
    """The ids of the k vectors most similar to the query (vectors are length 1, so the dot product is the cosine)."""
    import numpy as np

    k = max(0, min(k, len(ids)))
    return [ids[i] for i in np.argsort(-(matrix @ query_vec))[:k]]


_state: dict = {"store": None, "checked": False}


async def _current_store():
    """The stored vectors if they exist and match the provisions in the database now; checked once per process, and again after `reset()`."""
    if _state["checked"]:
        return _state["store"]
    from lib.db import db

    loaded = await asyncio.to_thread(load_store)
    store = None
    if loaded is None:
        logger.warning("meaning-based search is switched on but no vectors are stored: run scripts/embeddings_build.py; keyword search only")
    else:
        rows = await db.provisions.find({}, {"_id": 0, "id": 1, "content_sha256": 1}).to_list(None)
        if fingerprint(rows) != loaded[2]:
            logger.warning("meaning-based search: the stored vectors do not match the provisions now in the database: run scripts/embeddings_build.py; keyword search only")
        else:
            store = loaded
    _state.update(store=store, checked=True)
    return store


def reset() -> None:
    """Forget what was loaded (after a rebuild, or in tests)."""
    _state.update(store=None, checked=False)


async def semantic_provision_ids(q: str, k: int = 30) -> list[str]:
    """Provision ids nearest in meaning to the question, best first. Empty when switched off, not set up, stale, or on any failure: it can never break a search."""
    if not enabled() or not (q or "").strip():
        return []
    try:
        store = await _current_store()
        if store is None:
            return []
        vec = await asyncio.to_thread(_embed_query, q.strip()[:300])
        return nearest(store[0], store[1], vec, k)
    except Exception as exc:  # noqa: BLE001 - a search must still work without it; the question itself is never logged
        logger.error("meaning-based search failed (%s); keyword search only", type(exc).__name__)
        return []


# ---------- fusing the two result lists ----------
def fuse(keyword_ids: list[str], semantic_ids: list[str], limit: int) -> tuple[list[str], dict[str, str]]:
    """Reciprocal rank fusion of the keyword list and the meaning list. Returns the ids best first (at most `limit`) and, for each, how it was found: keyword, meaning or both."""
    score: dict[str, float] = {}
    for lst in (keyword_ids, semantic_ids):
        seen: set[str] = set()
        for rank, rid in enumerate(lst, 1):
            if rid in seen:
                continue
            seen.add(rid)
            score[rid] = score.get(rid, 0.0) + 1.0 / (RRF_K + rank)
    first = {rid: i for i, rid in enumerate(dict.fromkeys(keyword_ids + semantic_ids))}  # a tie keeps the order the lists gave
    order = sorted(score, key=lambda r: (-score[r], first[r]))[: max(0, limit)]
    kw, sem = set(keyword_ids), set(semantic_ids)
    return order, {r: "both" if r in kw and r in sem else "keyword" if r in kw else "meaning" for r in order}


# ---------- the re-ranker ----------
class Reranker:
    def __init__(self, folder: Path) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.tok = Tokenizer.from_file(str(folder / "tokenizer.json"))
        cfg = json.loads((folder / "tokenizer_config.json").read_text(encoding="utf-8"))
        pad = cfg.get("pad_token")
        pad = pad["content"] if isinstance(pad, dict) else (pad or "<pad>")
        self.tok.enable_truncation(max_length=512)
        self.tok.enable_padding(pad_id=self.tok.token_to_id(pad), pad_token=pad)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
        self.sess = ort.InferenceSession(str(folder / RERANK_FILE), sess_options=opts, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}

    def score(self, query: str, passages: list[str]) -> list[float]:
        import numpy as np

        out: list[float] = []
        for i in range(0, len(passages), 8):
            enc = self.tok.encode_batch([(query, p) for p in passages[i : i + 8]])
            feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64), "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64)}
            out += self.sess.run(None, {k: v for k, v in feed.items() if k in self.inputs})[0].reshape(len(enc), -1)[:, 0].tolist()
        return out


_reranker: Reranker | None = None


def _rerank_scores(q: str, passages: list[str]) -> list[float]:
    global _reranker
    if _reranker is None:
        d = reranker_dir()
        if d is None:
            raise RuntimeError("RERANKER_MODEL_DIR is not set")
        _reranker = Reranker(d)
    return _reranker.score(q, passages)


async def rerank(q: str, candidates: list[tuple[str, str]]) -> list[str] | None:
    """`candidates` = (id, passage) in the fused order. Returns the ids with the first RERANK_N re-ordered best first and the rest as they were, or None when the re-ranker is off or failed
    (the caller then keeps the order it has). It only re-orders: the set of ids is always exactly the one given."""
    ids = [c[0] for c in candidates]
    if not reranker_enabled() or len(ids) < 2 or not (q or "").strip():
        return None
    try:
        head = candidates[:RERANK_N]
        scores = await asyncio.to_thread(_rerank_scores, q.strip()[:300], [c[1][:PASSAGE_CHARS + 200] for c in head])
        if len(scores) != len(head):
            raise ValueError("wrong number of scores")
        order = [h[0] for _, _, h in sorted(((-s, i, h) for i, (s, h) in enumerate(zip(scores, head))), key=lambda t: (t[0], t[1]))]  # ties keep the fused order
        return order + ids[RERANK_N:]
    except Exception as exc:  # noqa: BLE001 - the question is never logged
        logger.error("re-ranking failed (%s); fused order kept", type(exc).__name__)
        return None
