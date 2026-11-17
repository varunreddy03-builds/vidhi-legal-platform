"""Meaning-based choice of passages from a matter's documents (lib/matter_meaning.py + lib/matter_context.select_context). Off by default. When on, it only changes WHICH passages fill
the reading budget of a large matter: every document still gets its best passage, the coverage report is computed the same way, and the client's text never leaves this machine or is stored."""

import asyncio
import logging
import os
from pathlib import Path

import pytest

from lib import embeddings, matter_meaning
from lib.matter_context import build_corpus, chunk_corpus, fuse_scores, needs_ranking, select_context

ROOT = Path(__file__).resolve().parent.parent


def corpus(*pages_per_doc):
    return build_corpus([{"id": f"d{i}", "filename": f"{i:02d}.txt", "doc_class": "OTHER", "media_kind": "TEXT", "description": "", "pages": pages} for i, pages in enumerate(pages_per_doc, 1)])


ANSWER = "The remittance for invoice 4471 is overdue by ninety days and the buyer has sent no reply."  # shares no word with the question below
QUESTION = "Was the payment late?"


def big_matter():
    filler = [f"Paragraph {n} about the warehouse lease, the parking area, rent receipts and painting work. " * 6 for n in range(60)]
    return corpus(["\n".join(filler[:30])], ["\n".join(filler[30:]) + "\n" + ANSWER])


def answer_index(c):
    return next(i for i, ch in enumerate(chunk_corpus(c)) if "remittance" in ch["text"])


def test_fusion_gives_a_passage_with_no_shared_word_its_meaning_rank_and_keeps_ties_stable():
    chunks = [{"score": 3.0}, {"score": 0.0}, {"score": 1.0}, {"score": 0.0}]
    fuse_scores(chunks, [1, 0])
    s = [c["score"] for c in chunks]
    assert s[0] > s[1] > s[2] > 0 and s[3] == 0.0  # 0: words rank 1 + meaning rank 2; 1: meaning rank 1 only; 2: words rank 2 only; 3: nothing
    ties = [{"score": 0.0}, {"score": 0.0}]
    fuse_scores(ties, [])
    assert [c["score"] for c in ties] == [0.0, 0.0]
    odd = [{"score": 1.0}]
    fuse_scores(odd, [5, -1, 0, 0])  # out-of-range and repeated indexes are skipped and take no rank
    assert odd[0]["score"] == pytest.approx(1 / 61 + 1 / 61)


def test_a_small_matter_is_read_in_full_and_meaning_changes_nothing():
    c = corpus(["Short page one."], ["Short page two."])
    plain = select_context(QUESTION, c)
    with_meaning = select_context(QUESTION, c, meaning_order=[1, 0])
    assert plain == with_meaning and plain[1]["complete"] is True and plain[1]["passages_chosen_by"] == "all text included" and not needs_ranking(c)


def test_in_a_large_matter_meaning_brings_in_the_passage_that_shares_no_word_with_the_question():
    c = big_matter()
    budget = 6000
    assert needs_ranking(c, budget)
    text_words, cov_words = select_context(QUESTION, c, budget=budget)
    assert "remittance" not in text_words and cov_words["passages_chosen_by"] == "words"  # by words alone the answer is missed
    order = [answer_index(c)] + [i for i in range(len(chunk_corpus(c))) if i != answer_index(c)]
    text_m, cov_m = select_context(QUESTION, c, budget=budget, meaning_order=order)
    assert "remittance for invoice 4471 is overdue" in text_m and cov_m["passages_chosen_by"] == "words and meaning"
    for cov in (cov_words, cov_m):  # the honesty rules are untouched: both documents touched, and the report says the matter was only partly read
        assert cov["documents_not_read"] == [] and cov["complete"] is False and cov["chars_included"] <= budget
    assert set(cov_m) == set(cov_words)


class FakeEmbedder:
    """Two dimensions: money words versus everything else. The question and the answer share no word, but both are about money."""

    MONEY = ("payment", "remittance", "invoice", "overdue", "late")

    def embed(self, texts, prefix, batch=32):
        import numpy as np

        out = np.zeros((len(texts), 2), dtype="float32")
        for i, t in enumerate(texts):
            out[i, 0 if any(w in t.lower() for w in self.MONEY) else 1] = 1.0
        return out


def switch_on(monkeypatch, tmp_path):
    (tmp_path / "onnx").mkdir()
    (tmp_path / "onnx" / "model.onnx").write_bytes(b"x")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("EMBEDDINGS_MODEL_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDINGS_MATTER_ENABLED", "true")
    monkeypatch.setattr(embeddings, "_get_embedder", lambda: FakeEmbedder())
    matter_meaning._cache.clear()


@pytest.mark.parametrize("model,matter_switch,expected", [("true", "true", True), ("true", "", False), ("true", "false", False), ("", "true", False)])
def test_it_needs_the_model_and_its_own_switch(monkeypatch, tmp_path, model, matter_switch, expected):
    (tmp_path / "onnx").mkdir()
    (tmp_path / "onnx" / "model.onnx").write_bytes(b"x")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EMBEDDINGS_MODEL_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDINGS_ENABLED", model)
    monkeypatch.setenv("EMBEDDINGS_MATTER_ENABLED", matter_switch)
    assert matter_meaning.enabled() is expected


def test_off_by_default_it_answers_nothing(monkeypatch):
    monkeypatch.delenv("EMBEDDINGS_MATTER_ENABLED", raising=False)
    assert asyncio.run(matter_meaning.passage_order(QUESTION, ["a", "b"])) is None


def test_when_on_it_ranks_passages_by_meaning_and_the_whole_route_then_finds_the_answer(monkeypatch, tmp_path):
    switch_on(monkeypatch, tmp_path)
    texts = ["The parking area is shared.", ANSWER, "Rent receipts for March."]
    assert asyncio.run(matter_meaning.passage_order(QUESTION, texts))[0] == 1
    c = big_matter()
    order = asyncio.run(matter_meaning.passage_order(QUESTION, [ch["text"] for ch in chunk_corpus(c)]))
    assert order[0] == answer_index(c)
    assert "remittance for invoice 4471" in select_context(QUESTION, c, budget=6000, meaning_order=order)[0]


def test_nothing_to_rank_too_many_passages_or_a_failure_means_word_ranking_and_nothing_is_logged(monkeypatch, tmp_path, caplog):
    switch_on(monkeypatch, tmp_path)
    assert asyncio.run(matter_meaning.passage_order("  ", ["a"])) is None and asyncio.run(matter_meaning.passage_order(QUESTION, [])) is None
    assert asyncio.run(matter_meaning.passage_order(QUESTION, ["x"] * (matter_meaning.MAX_CHUNKS + 1))) is None

    class Boom:
        def embed(self, *a, **k):
            raise RuntimeError("model exploded")

    monkeypatch.setattr(embeddings, "_get_embedder", lambda: Boom())
    matter_meaning._cache.clear()
    secret = "Confidential: the client admits the cheque bounced"
    with caplog.at_level(logging.ERROR, logger="vidhi.embeddings"):
        assert asyncio.run(matter_meaning.passage_order("did the cheque bounce", [secret, "other text"])) is None
    assert "RuntimeError" in caplog.text and "cheque" not in caplog.text and "Confidential" not in caplog.text


def test_passage_vectors_are_kept_in_memory_only_and_the_code_makes_no_network_call():
    matter_part = (ROOT / "lib" / "matter_meaning.py").read_text(encoding="utf-8")
    for banned in ("np.save", "write_text", "write_bytes", "open(", "db.", "insert", "requests", "httpx", "urllib", "socket"):
        assert banned not in matter_part, banned
    route = (ROOT / "routers" / "research.py").read_text(encoding="utf-8")
    assert "if needs_ranking(corpus, budget):" in route and "matter_meaning.passage_order(body.question, [c[\"text\"] for c in chunk_corpus(corpus)])" in route
    assert "meaning_order=meaning" in route  # the route passes the order on; select_context does the rest, tested above


@pytest.mark.skipif(not (os.environ.get("EMBEDDINGS_MODEL_DIR") and (Path(os.environ.get("EMBEDDINGS_MODEL_DIR", "x")) / "onnx" / "model.onnx").exists()), reason="needs the real model (EMBEDDINGS_MODEL_DIR)")
def test_the_real_model_picks_the_answer_passage_for_an_english_and_a_hindi_question(monkeypatch):
    monkeypatch.setenv("EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("EMBEDDINGS_MATTER_ENABLED", "true")
    monkeypatch.setattr(embeddings, "_embedder", None)
    matter_meaning._cache.clear()
    texts = ["The parking area of the warehouse is shared by both tenants.", ANSWER, "The walls were painted in March and the receipts are attached."]
    for q in (QUESTION, "क्या भुगतान में देरी हुई?"):
        assert asyncio.run(matter_meaning.passage_order(q, texts))[0] == 1, q
