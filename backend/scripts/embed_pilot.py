"""Embeddings and re-ranker pilot, step B. Runs in its OWN Python environment (C:\\vidhi-tools\\venv-embed: onnxruntime, tokenizers, numpy, pymongo), never in the app's.

  python scripts/embed_pilot.py [--db vidhi_dev] [--force]

Measures, on the 24 statute questions of evals/retrieval_set.json (plain-English questions, each with the provisions that answer it) and on Hindi and Telugu versions of eight of them
(evals/embed_pilot_queries.json, UNREVIEWED translations): does the right provision appear in the first 1, 3, 5, 10 results for
  keyword    today's retrieval (from step A, scripts/embed_pilot_lexical.py)
  embedding  meaning-based search over the 2,331 provisions (intfloat/multilingual-e5-small, MIT, ONNX)
  hybrid     keyword and embedding results fused by reciprocal rank (k = 60)
  rerank     the top 20 of the hybrid re-ordered by a cross-encoder (cross-encoder/ms-marco-MiniLM-L-6-v2, Apache-2.0, ONNX; English only)
Retrieval only: no AI model that writes text is called, nothing is written to the database, nothing leaves this machine. The provisions are unreviewed law text, so this measures finding, never
verifying.

DECISION RULE, fixed before the first run: a method is worth adopting for English questions only if (1) its Recall@3 and Recall@5 are each at least keyword's, AND (2) it pushes NO question
that keyword answered in the first 3 results out beyond the first 5 (no harm). For Hindi and Telugu the question is whether it finds anything at all, where keyword finds nothing. The result is
written to docs/evals/embeddings-pilot-<date>.md exactly as measured, whichever way it falls. Judgments are not measured here: their case-list records have no text to embed, and there is no
lawyer-checked semantic question set (blocked on a named advocate)."""

import argparse
import json
import os
import sys
import time
import hashlib
from datetime import date
from pathlib import Path

import numpy as np
import onnxruntime as ort
from pymongo import MongoClient
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parent.parent
MODELS = Path(r"C:\vidhi-tools\embed-pilot\models")
WORK = Path(r"C:\vidhi-tools\embed-pilot")
KS = (1, 3, 5, 10)
RRF_K = 60


def make_tokenizer(folder: Path, max_len: int) -> Tokenizer:
    tok = Tokenizer.from_file(str(folder / "tokenizer.json"))
    cfg = json.loads((folder / "tokenizer_config.json").read_text(encoding="utf-8"))
    pad = cfg.get("pad_token")
    pad = pad["content"] if isinstance(pad, dict) else (pad or "[PAD]")
    tok.enable_truncation(max_length=max_len)
    tok.enable_padding(pad_id=tok.token_to_id(pad), pad_token=pad)
    return tok


def session(path: Path) -> ort.InferenceSession:
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
    return ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])


class Embedder:
    def __init__(self) -> None:
        folder = MODELS / "multilingual-e5-small"
        self.tok, self.sess = make_tokenizer(folder, 384), session(folder / "onnx" / "model.onnx")

    def embed(self, texts: list[str], prefix: str, batch: int = 32) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch):
            enc = self.tok.encode_batch([prefix + t for t in texts[i : i + batch]])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            hidden = self.sess.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)})[0]
            pooled = (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)  # mean over real tokens
            out.append(pooled / np.linalg.norm(pooled, axis=1, keepdims=True))
        return np.vstack(out)


class Reranker:
    def __init__(self) -> None:
        folder = MODELS / "ms-marco-MiniLM-L-6-v2"
        self.tok, self.sess = make_tokenizer(folder, 384), session(folder / "onnx" / "model.onnx")

    def score(self, query: str, passages: list[str]) -> list[float]:
        scores: list[float] = []
        for i in range(0, len(passages), 16):
            enc = self.tok.encode_batch([(query, p) for p in passages[i : i + 16]])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            types = np.array([e.type_ids for e in enc], dtype=np.int64)
            scores += self.sess.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": types})[0][:, 0].tolist()
        return scores


def first_rank(returned: list[str], expected: set[str]) -> int | None:
    for i, rid in enumerate(returned[:10], 1):
        if rid in expected:
            return i
    return None


def recall(ranks: list[int | None], k: int) -> float:
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks) if ranks else 0.0


def rrf(*lists: list[str]) -> list[str]:
    score: dict[str, float] = {}
    for lst in lists:
        for rank, rid in enumerate(lst, 1):
            score[rid] = score.get(rid, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(score, key=lambda r: -score[r])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="vidhi_dev")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    db = MongoClient("mongodb://127.0.0.1:27017")[a.db]
    acts = {i["id"]: (i.get("short_names") or ["?"])[0] for i in db.instruments.find({}, {"id": 1, "short_names": 1})}
    # the provision's own words are in `text_full` (an earlier version of this script read a field called `text`, which provisions do not have, so it embedded headings only)
    provs = list(db.provisions.find({}, {"_id": 0, "id": 1, "number": 1, "heading": 1, "text_full": 1, "instrument_id": 1}))
    texts = {p["id"]: f"{acts.get(p['instrument_id'], '?')} section {p['number']}: {p.get('heading') or ''}. {(p.get('text_full') or '')[:1500]}" for p in provs}
    if not any(len(p.get("text_full") or "") > 50 for p in provs):
        raise SystemExit("the provisions hold no text_full: refusing to measure headings only")
    ids = [p["id"] for p in provs]
    emb = Embedder()
    fingerprint = hashlib.sha256("\n".join(texts[i] for i in ids).encode("utf-8")).hexdigest()[:12]  # the cache is valid only for exactly these passages
    cache = WORK / f"provisions_e5_{fingerprint}.npy"
    t0 = time.time()
    if cache.exists() and not a.force:
        mat = np.load(cache)
    else:
        mat = emb.embed([texts[i] for i in ids], "passage: ")
        np.save(cache, mat)
    embed_corpus_s = time.time() - t0

    fixture = json.loads((ROOT / "evals" / "retrieval_set.json").read_text(encoding="utf-8"))
    gold = {q["id"]: {e["provision_id"] for e in q["expected"]} for q in fixture["questions"] if q["kind"] == "statute"}
    questions = [(q["id"], "en", q["question"]) for q in fixture["questions"] if q["kind"] == "statute"]
    questions += [(f"{q['qid']}-{q['lang']}", q["lang"], q["text"]) for q in json.loads((ROOT / "evals" / "embed_pilot_queries.json").read_text(encoding="utf-8"))["queries"]]
    lexical = json.loads((WORK / "lexical.json").read_text(encoding="utf-8"))
    rer = Reranker()

    rows, q_ms, r_ms = [], [], []
    for key, lang, text in questions:
        expected = gold[key.split("-")[0]]
        t = time.time()
        qv = emb.embed([text], "query: ")[0]
        q_ms.append((time.time() - t) * 1000)
        order = np.argsort(-(mat @ qv))
        e_list = [ids[i] for i in order[:30]]
        k_list = lexical.get(key, [])[:10]
        h_list = rrf(k_list, e_list)
        rank_rr = None
        if lang == "en":
            cand = h_list[:20]
            t = time.time()
            sc = rer.score(text, [texts[c] for c in cand])
            r_ms.append((time.time() - t) * 1000)
            rr = [c for c, _ in sorted(zip(cand, sc), key=lambda x: -x[1])]
            rank_rr = first_rank(rr, expected)
        rows.append({"key": key, "lang": lang, "text": text, "keyword": first_rank(k_list, expected), "embedding": first_rank(e_list, expected), "hybrid": first_rank(h_list, expected), "rerank": rank_rr})

    methods = ("keyword", "embedding", "hybrid", "rerank")
    groups = {"English (24)": [r for r in rows if r["lang"] == "en"], "Hindi (8, unreviewed translations)": [r for r in rows if r["lang"] == "hi"], "Telugu (8, unreviewed translations)": [r for r in rows if r["lang"] == "te"]}
    lines = [f"# Embeddings and re-ranker pilot, {date.today().isoformat()}", "",
             "Retrieval only, on the 2,331 unreviewed provisions of six criminal-law Acts in `vidhi_dev`. No text-writing model, no database write, nothing left this machine. Models: `intfloat/multilingual-e5-small` (MIT, ONNX) "
             "and `cross-encoder/ms-marco-MiniLM-L-6-v2` (Apache-2.0, ONNX, English only), run with onnxruntime on the CPU (PyTorch is blocked by this PC's Application Control policy and was not used or worked around).", "",
             "Decision rule, fixed before the first run: adopt for English only if Recall@3 and Recall@5 are each at least keyword's AND no question that keyword answered in the first 3 results falls beyond the first 5.", ""]
    for name, grp in groups.items():
        lines += [f"## {name}", "", "| Method | Recall@1 | Recall@3 | Recall@5 | Recall@10 | Not found in first 10 |", "|---|---|---|---|---|---|"]
        for m in methods:
            if m == "rerank" and not name.startswith("English"):
                continue
            rk = [r[m] for r in grp]
            lines.append(f"| {m} | " + " | ".join(f"{round(100 * recall(rk, k))}%" for k in KS) + f" | {sum(1 for x in rk if x is None)} |")
        lines.append("")
    eng = groups["English (24)"]
    verdicts = []
    for m in ("embedding", "hybrid", "rerank"):
        r3, r5 = recall([r[m] for r in eng], 3) >= recall([r["keyword"] for r in eng], 3), recall([r[m] for r in eng], 5) >= recall([r["keyword"] for r in eng], 5)
        harmed = [r["key"] for r in eng if r["keyword"] is not None and r["keyword"] <= 3 and (r[m] is None or r[m] > 5)]
        verdicts.append((m, r3 and r5 and not harmed, r3, r5, harmed))
    lines += ["## Decision rule, English", "", "| Method | Recall@3 >= keyword | Recall@5 >= keyword | Questions pushed out (keyword top 3 to beyond 5) | Rule met |", "|---|---|---|---|---|"]
    for m, ok, r3, r5, harmed in verdicts:
        lines.append(f"| {m} | {'yes' if r3 else 'no'} | {'yes' if r5 else 'no'} | {', '.join(harmed) or 'none'} | **{'yes' if ok else 'no'}** |")
    lines += ["", "## Where each question ranked (blank = not in the first 10)", "", "| Question | Language | Keyword | Embedding | Hybrid | Re-rank |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['key']}: {r['text'][:60]} | {r['lang']} | " + " | ".join(str(r[m] or "") for m in methods) + " |")
    lines += ["", "## Cost and speed (this PC, CPU only)", "",
              f"- Embedding the 2,331 provisions: {embed_corpus_s:.0f} s (cached afterwards); stored vectors: {mat.shape[0]} x {mat.shape[1]} floats = {mat.nbytes / 1e6:.1f} MB.",
              f"- One question embedded: median {np.median(q_ms):.0f} ms. Re-ranking 20 candidates: median {np.median(r_ms):.0f} ms." if r_ms else "",
              "", "## What this does and does not show", "",
              "- It measures FINDING a provision from a plain question, on 24 questions: a small set. A few questions change the percentages a lot. It is evidence for a decision, not proof.",
              "- The Hindi and Telugu questions are unreviewed translations written by an AI assistant; they show whether a question in another language reaches an English provision, not how good any translation is.",
              "- The re-ranker is English only: no multilingual re-ranker with a confirmed licence and an ONNX file was available, so it was not tested on Hindi or Telugu.",
              "- Judgments were not measured: their case-list records hold no text to embed, and there is no lawyer-checked semantic question set (blocked on a named advocate).",
              "- Nothing here verifies law. A provision found this way is still unreviewed; verification stays in code (`lib/verify.py`, `lib/textmatch.py`)."]
    out = ROOT.parent / "docs" / "evals" / f"embeddings-pilot-{date.today().isoformat()}.md"
    out.write_text("\n".join(x for x in lines if x is not None) + "\n", encoding="utf-8")
    (WORK / "pilot-rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines[:60]))
    print("saved", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
