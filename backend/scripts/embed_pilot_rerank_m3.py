"""Pilot: does a MULTILINGUAL re-ranker improve the meaning-based search over the law provisions? Retrieval only: no text-writing model, no database write, nothing leaves this machine.

    C:\\vidhi-tools\\venv-embed\\Scripts\\python.exe -I backend\\scripts\\embed_pilot_rerank_m3.py     (needs onnxruntime, tokenizers, numpy, pymongo; the first pilot's files)

Model: BAAI/bge-reranker-v2-m3 (Apache-2.0), the ONNX int8 conversion from onnx-community, in C:\\vidhi-tools\\embed-pilot\\models\\bge-reranker-v2-m3. The first pilot (embed_pilot.py) left the
English-only MiniLM re-ranker out because it pushed one question the old method answered out of the first 5; it could not be tried on Hindi or Telugu.

It re-orders the top 20 of the HYBRID list (keyword + meaning, which is what the app uses when meaning-based search is on). Same 24 English + 8 Hindi + 8 Telugu questions as the first pilot.

DECISION RULE, fixed before the first run. The thing to beat is HYBRID, not keyword, because hybrid is what is in the app:
  English: adopt only if Recall@3 and Recall@5 are each at least hybrid's AND no question that hybrid answered in its first 3 falls beyond its first 5 (no harm).
  Hindi and Telugu: adopt only if Recall@3 is at least hybrid's AND no question that hybrid answered in its first 3 falls beyond its first 5.
  Time: re-ranking 20 candidates must take under 3 seconds (median) on this PC's CPU.
All of these must hold. The result is written to docs/evals/reranker-m3-pilot-<date>.md as measured, whichever way it falls."""

import hashlib
import json
import os
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from embed_pilot import MODELS, ROOT, WORK, Embedder, first_rank, make_tokenizer, recall, rrf, session  # noqa: E402

MAX_SECONDS = 3.0
N = int(os.environ.get("RERANK_CANDIDATES", "20"))  # first run: 20 (all rules failed only on time). Second run, declared before it ran: 10, every other rule unchanged


class M3Reranker:
    def __init__(self) -> None:
        folder = MODELS / "bge-reranker-v2-m3"
        self.tok, self.sess = make_tokenizer(folder, 512), session(folder / "onnx" / "model_int8.onnx")
        self.inputs = {i.name for i in self.sess.get_inputs()}

    def score(self, query: str, passages: list[str]) -> list[float]:
        out: list[float] = []
        for i in range(0, len(passages), 8):
            enc = self.tok.encode_batch([(query, p) for p in passages[i : i + 8]])
            feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64), "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64)}
            out += self.sess.run(None, {k: v for k, v in feed.items() if k in self.inputs})[0].reshape(len(enc), -1)[:, 0].tolist()
        return out


def main() -> int:
    db = MongoClient("mongodb://127.0.0.1:27017")["vidhi_dev"]
    acts = {i["id"]: (i.get("short_names") or ["?"])[0] for i in db.instruments.find({}, {"id": 1, "short_names": 1})}
    provs = list(db.provisions.find({}, {"_id": 0, "id": 1, "number": 1, "heading": 1, "text_full": 1, "instrument_id": 1}))
    if not any(len(p.get("text_full") or "") > 50 for p in provs):
        raise SystemExit("the provisions hold no text_full: refusing to measure headings only")
    texts = {p["id"]: f"{acts.get(p['instrument_id'], '?')} section {p['number']}: {p.get('heading') or ''}. {(p.get('text_full') or '')[:1500]}" for p in provs}
    ids = [p["id"] for p in provs]
    fp = hashlib.sha256("\n".join(texts[i] for i in ids).encode("utf-8")).hexdigest()[:12]
    cache = WORK / f"provisions_e5_{fp}.npy"
    if not cache.exists():
        raise SystemExit(f"{cache} is missing: run embed_pilot.py first (it makes the vectors for exactly these provisions)")
    mat, emb, rer = np.load(cache), Embedder(), M3Reranker()
    fixture = json.loads((ROOT / "evals" / "retrieval_set.json").read_text(encoding="utf-8"))
    gold = {q["id"]: {e["provision_id"] for e in q["expected"]} for q in fixture["questions"] if q["kind"] == "statute"}
    questions = [(q["id"], "en", q["question"]) for q in fixture["questions"] if q["kind"] == "statute"]
    questions += [(f"{q['qid']}-{q['lang']}", q["lang"], q["text"]) for q in json.loads((ROOT / "evals" / "embed_pilot_queries.json").read_text(encoding="utf-8"))["queries"]]
    lexical = json.loads((WORK / "lexical.json").read_text(encoding="utf-8"))
    rows, ms = [], []
    for key, lang, text in questions:
        expected = gold[key.split("-")[0]]
        e_list = [ids[i] for i in np.argsort(-(mat @ emb.embed([text], "query: ")[0]))[:30]]
        h_list = rrf(lexical.get(key, [])[:10], e_list)
        cand = h_list[:N]
        t = time.time()
        sc = rer.score(text, [texts[c] for c in cand])
        ms.append((time.time() - t) * 1000)
        rr = [c for c, _ in sorted(zip(cand, sc), key=lambda x: -x[1])]
        rows.append({"key": key, "lang": lang, "text": text, "hybrid": first_rank(h_list, expected), "rerank": first_rank(rr, expected)})
        print(key, rows[-1]["hybrid"], rows[-1]["rerank"], flush=True)

    lines = [f"# Multilingual re-ranker pilot (bge-reranker-v2-m3, int8), top {N} candidates, {date.today().isoformat()}", "",
             f"Retrieval only, on the 2,331 unreviewed provisions of six criminal-law Acts in `vidhi_dev`. Re-orders the top {N} of the hybrid list. Same questions as `embeddings-pilot-2026-11-12.md`; the Hindi and Telugu wording is unreviewed.", "",
             "Decision rule, fixed before the first run (see `backend/scripts/embed_pilot_rerank_m3.py`): English: Recall@3 and Recall@5 each at least hybrid's, and no question hybrid answered in its first 3 pushed beyond its first 5. Hindi and Telugu: Recall@3 at least hybrid's, and the same no-harm test. Median time for the candidates under 3 seconds.", ""]
    verdict = {}
    for name, lang, k_need in (("English (24)", "en", (3, 5)), ("Hindi (8)", "hi", (3,)), ("Telugu (8)", "te", (3,))):
        g = [r for r in rows if r["lang"] == lang]
        lines += [f"## {name}", "", "| Method | Recall@1 | Recall@3 | Recall@5 | Recall@10 | Not found in first 10 |", "|---|---|---|---|---|---|"]
        for m in ("hybrid", "rerank"):
            rk = [r[m] for r in g]
            lines.append(f"| {m} | " + " | ".join(f"{recall(rk, k):.0%}" for k in (1, 3, 5, 10)) + f" | {sum(1 for x in rk if x is None)} |")
        harmed = [r["key"] for r in g if r["hybrid"] is not None and r["hybrid"] <= 3 and (r["rerank"] is None or r["rerank"] > 5)]
        ok = all(recall([r["rerank"] for r in g], k) >= recall([r["hybrid"] for r in g], k) for k in k_need) and not harmed
        verdict[lang] = ok
        lines += ["", f"Questions pushed out (hybrid top 3 to beyond 5): {', '.join(harmed) or 'none'}. Rule met: **{'yes' if ok else 'no'}**.", ""]
    med = statistics.median(ms) / 1000
    verdict["time"] = med < MAX_SECONDS
    lines += ["## Time", "", f"Re-ranking {N} candidates: median {med:.2f} s (limit {MAX_SECONDS:.0f} s). Rule met: **{'yes' if verdict['time'] else 'no'}**.", "",
              "## Where each question ranked (blank = not in the first 10)", "", "| Question | Language | Hybrid | Re-rank |", "|---|---|---|---|"]
    lines += [f"| {r['key']}: {r['text'][:60].replace('|', '/')} | {r['lang']} | {r['hybrid'] or ''} | {r['rerank'] or ''} |" for r in rows]
    adopt = all(verdict.values())
    lines += ["", f"## Decision: **{'meets every rule' if adopt else 'does not meet every rule: leave it out'}** ({', '.join(f'{k}: {v}' for k, v in verdict.items())})", ""]
    out = ROOT.parent / "docs" / "evals" / f"reranker-m3-pilot-{date.today().isoformat()}-top{N}.md"
    out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("\n".join(lines[-12:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
