"""Meaning-based search over the law provisions (lib/embeddings.py): off by default; when on it only widens which unreviewed provisions are shown, it can never break a search, and a stale or
missing store means "off". The model itself is not needed for most of these tests (a small stand-in produces vectors); one test uses the real model when EMBEDDINGS_MODEL_DIR points at it."""

import logging
import os
from pathlib import Path

import pytest

from lib import embeddings, legal_search
from tests.inproc import run
from tests.legal_fixtures import FICTIONAL_PENAL_ACT
from tests.test_admin import admin  # noqa: F401  (fixture)
from tests.test_legal_data import load, prov_id


class FakeEmbedder:
    """Four dimensions: murder, theft, bail, other. A text goes to the dimension of the first of those words it contains (so no model is needed)."""

    WORDS = ("murder", "theft", "bail")

    def embed(self, texts, prefix, batch=32):
        import numpy as np

        out = np.zeros((len(texts), 4), dtype="float32")
        for i, t in enumerate(texts):
            low = t.lower()
            out[i, next((k for k, w in enumerate(self.WORDS) if w in low), 3)] = 1.0
        return out


PROVISIONS = [
    {"id": "p-murder", "number": "302", "heading": "Punishment for murder", "text_full": "Whoever commits murder shall be punished.", "instrument_id": "i1", "content_sha256": "aa"},
    {"id": "p-theft", "number": "379", "heading": "Punishment for theft", "text_full": "Whoever commits theft shall be punished.", "instrument_id": "i1", "content_sha256": "bb"},
    {"id": "p-bail", "number": "437", "heading": "When bail may be taken", "text_full": "Bail may be taken in a non-bailable case.", "instrument_id": "i1", "content_sha256": "cc"},
]


@pytest.mark.parametrize("value,expected", [(None, False), ("", False), ("false", False), ("0", False), ("no", False), ("true", True), ("TRUE", True), ("1", True), ("on", True)])
def test_it_is_off_unless_clearly_turned_on_and_the_model_files_exist(monkeypatch, tmp_path, value, expected):
    (tmp_path / "onnx").mkdir()
    (tmp_path / "onnx" / "model.onnx").write_bytes(b"x")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EMBEDDINGS_MODEL_DIR", str(tmp_path))
    if value is None:
        monkeypatch.delenv("EMBEDDINGS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("EMBEDDINGS_ENABLED", value)
    assert embeddings.enabled() is expected


def test_turned_on_but_without_model_files_it_stays_off(monkeypatch, tmp_path):
    monkeypatch.setenv("EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("EMBEDDINGS_MODEL_DIR", str(tmp_path / "nowhere"))
    assert embeddings.enabled() is False
    monkeypatch.delenv("EMBEDDINGS_MODEL_DIR")
    assert embeddings.enabled() is False
    assert run(embeddings.semantic_provision_ids("What is the punishment for murder?")) == []


def test_fusion_puts_what_both_lists_found_first_keeps_ties_in_order_and_says_how_each_was_found():
    order, how = embeddings.fuse(["a", "b", "c"], ["c", "d", "a"], 10)
    assert order[:2] == ["a", "c"] and set(order) == {"a", "b", "c", "d"}  # found by both: first
    assert how == {"a": "both", "c": "both", "b": "keyword", "d": "meaning"}
    assert embeddings.fuse(["a", "b"], ["x", "y"], 3)[0] == ["a", "x", "b"]  # equal scores keep the order the lists gave: keyword first at each rank
    assert embeddings.fuse(["a", "b", "c"], [], 2) == (["a", "b"], {"a": "keyword", "b": "keyword"})  # nothing from meaning: keyword order, cut to the limit
    assert embeddings.fuse([], ["x"], 5) == (["x"], {"x": "meaning"})
    assert embeddings.fuse(["a", "a", "b"], ["b", "b"], 5)[0] == ["b", "a"]  # a repeated id counts once per list: b (rank 3 + rank 1) beats a (rank 1)
    assert embeddings.fuse([], [], 5) == ([], {}) and embeddings.fuse(["a"], ["a"], 0) == ([], {})


def test_the_fingerprint_changes_with_any_provision_but_not_with_their_order():
    base = embeddings.fingerprint(PROVISIONS)
    assert embeddings.fingerprint(list(reversed(PROVISIONS))) == base
    assert embeddings.fingerprint(PROVISIONS[:2]) != base  # one removed
    changed = [dict(PROVISIONS[0], content_sha256="zz")] + PROVISIONS[1:]
    assert embeddings.fingerprint(changed) != base  # one provision's content changed
    assert embeddings.fingerprint(PROVISIONS + [{"id": "p-new", "content_sha256": "dd"}]) != base  # one added


def test_a_stored_set_of_vectors_ranks_by_meaning_and_survives_a_round_trip(tmp_path):
    out = embeddings.build_store(PROVISIONS, {"i1": "IPC"}, tmp_path, embedder=FakeEmbedder())
    assert out["provisions"] == 3 and out["fingerprint"] == embeddings.fingerprint(PROVISIONS)
    matrix, ids, fp = embeddings.load_store(tmp_path)
    assert ids == ["p-murder", "p-theft", "p-bail"] and fp == out["fingerprint"] and matrix.shape == (3, 4)
    vec = FakeEmbedder().embed(["a question about theft"], "query: ")[0]
    assert embeddings.nearest(matrix, ids, vec, 2)[0] == "p-theft"
    assert embeddings.nearest(matrix, ids, vec, 99) and len(embeddings.nearest(matrix, ids, vec, 99)) == 3 and embeddings.nearest(matrix, ids, vec, 0) == []
    assert embeddings.load_store(tmp_path / "empty") is None  # no store: None, not an error


class StubDb:
    class _Cursor:
        def __init__(self, rows):
            self.rows = rows

        async def to_list(self, n):
            return self.rows

    def __init__(self, rows):
        outer = self
        self.rows = rows

        class Provisions:
            def find(self, *a, **k):
                return StubDb._Cursor(outer.rows)

        self.provisions = Provisions()


def switch_on(monkeypatch, tmp_path, rows):
    import lib.db

    (tmp_path / "model" / "onnx").mkdir(parents=True)
    (tmp_path / "model" / "onnx" / "model.onnx").write_bytes(b"x")
    (tmp_path / "model" / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("EMBEDDINGS_MODEL_DIR", str(tmp_path / "model"))
    monkeypatch.setenv("EMBEDDINGS_DIR", str(tmp_path / "store"))
    monkeypatch.setattr(lib.db, "db", StubDb(rows))
    monkeypatch.setattr(embeddings, "_embed_query", lambda q: FakeEmbedder().embed([q], "query: ")[0])
    embeddings.reset()


def test_when_on_and_current_it_answers_with_the_nearest_provisions(monkeypatch, tmp_path):
    embeddings.build_store(PROVISIONS, {"i1": "IPC"}, tmp_path / "store", embedder=FakeEmbedder())
    switch_on(monkeypatch, tmp_path, PROVISIONS)
    try:
        assert run(embeddings.semantic_provision_ids("who commits murder", k=2))[0] == "p-murder"
        assert run(embeddings.semantic_provision_ids("   ")) == []
    finally:
        embeddings.reset()


def test_a_missing_or_stale_store_means_off_and_a_failure_never_breaks_the_search(monkeypatch, tmp_path, caplog):
    switch_on(monkeypatch, tmp_path, PROVISIONS)  # no store written yet
    try:
        assert run(embeddings.semantic_provision_ids("murder")) == []
        embeddings.build_store(PROVISIONS, {"i1": "IPC"}, tmp_path / "store", embedder=FakeEmbedder())
        embeddings.reset()
        monkeypatch.setattr(__import__("lib.db", fromlist=["db"]), "db", StubDb(PROVISIONS[:2]))  # a provision was removed since the vectors were made
        assert run(embeddings.semantic_provision_ids("murder")) == []
        embeddings.reset()
        monkeypatch.setattr(__import__("lib.db", fromlist=["db"]), "db", StubDb(PROVISIONS))
        secret = "a confidential client question about murder"

        def boom(q):
            raise RuntimeError("model exploded")

        monkeypatch.setattr(embeddings, "_embed_query", boom)
        with caplog.at_level(logging.ERROR, logger="vidhi.embeddings"):
            assert run(embeddings.semantic_provision_ids(secret)) == []
        assert "RuntimeError" in caplog.text and "confidential" not in caplog.text and secret not in caplog.text  # the class of the error is logged, never the question
    finally:
        embeddings.reset()


def test_search_is_unchanged_when_off_and_fused_with_how_each_was_found_when_on(admin, user_a, monkeypatch):  # noqa: F811
    word = f"zqmeaning{os.urandom(3).hex()}"
    t = load(admin, pages=[p.replace("festival of lamps", f"festival of lamps {word}") for p in FICTIONAL_PENAL_ACT])
    kept = prov_id(user_a, "3", t["title"])
    other = prov_id(user_a, "4", t["title"])
    q = f"hoards tokens festival of lamps {word}"
    exact_q = f"Section 3 of the {t['title']}"
    exact_off = run(legal_search.search(exact_q))["exact"]
    off = run(legal_search.search(q, limit=5))
    assert exact_off and "meaning_search" not in off and all("found_by" not in v for v in off["text"]) and kept in [v["id"] for v in off["text"]]

    async def fake(question, k=30):
        return [other, kept]

    monkeypatch.setattr(embeddings, "semantic_provision_ids", fake)
    on = run(legal_search.search(q, limit=5))
    by = {v["id"]: v["found_by"] for v in on["text"]}
    assert on["meaning_search"] == "used" and set(by) >= {kept, other} and len(on["text"]) <= 5
    assert by[kept] == "both" and by[other] in ("meaning", "both") and on["text"][0]["id"] == kept  # found by both lists: ranked first
    off_view = next(v for v in off["text"] if v["id"] == kept)
    on_view = next(v for v in on["text"] if v["id"] == kept)
    assert {k: x for k, x in on_view.items() if k != "found_by"} == off_view  # the provision itself is exactly what keyword search shows: only `found_by` is added, nothing is relabelled or verified
    assert run(legal_search.search(exact_q))["exact"] == exact_off  # exact citations are untouched


def rerank_files(tmp_path):
    (tmp_path / "rr" / "onnx").mkdir(parents=True)
    (tmp_path / "rr" / "onnx" / "model_int8.onnx").write_bytes(b"x")
    (tmp_path / "rr" / "tokenizer.json").write_text("{}", encoding="utf-8")
    return tmp_path / "rr"


@pytest.mark.parametrize("meaning,rr,files,expected", [("true", "true", True, True), ("true", "", True, False), ("true", "false", True, False), ("", "true", True, False), ("true", "true", False, False)])
def test_the_reranker_needs_meaning_search_its_own_switch_and_its_files(monkeypatch, tmp_path, meaning, rr, files, expected):
    (tmp_path / "m" / "onnx").mkdir(parents=True)
    (tmp_path / "m" / "onnx" / "model.onnx").write_bytes(b"x")
    (tmp_path / "m" / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EMBEDDINGS_MODEL_DIR", str(tmp_path / "m"))
    monkeypatch.setenv("EMBEDDINGS_ENABLED", meaning)
    monkeypatch.setenv("RERANKER_ENABLED", rr)
    monkeypatch.setenv("RERANKER_MODEL_DIR", str(rerank_files(tmp_path) if files else tmp_path / "nowhere"))
    assert embeddings.reranker_enabled() is expected


def test_the_reranker_only_reorders_the_first_ten_keeps_ties_in_order_and_never_changes_the_set(monkeypatch, tmp_path):
    monkeypatch.setenv("EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("EMBEDDINGS_MODEL_DIR", str(tmp_path / "m"))
    (tmp_path / "m" / "onnx").mkdir(parents=True)
    (tmp_path / "m" / "onnx" / "model.onnx").write_bytes(b"x")
    (tmp_path / "m" / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("RERANKER_ENABLED", "true")
    monkeypatch.setenv("RERANKER_MODEL_DIR", str(rerank_files(tmp_path)))
    cands = [(f"p{i}", f"passage {i}") for i in range(14)]
    seen = {}

    def scores(q, passages):
        seen["n"] = len(passages)
        return [0.0, 0.0, 5.0, 1.0, 5.0, 0.0, 0.0, 0.0, 0.0, 9.0][: len(passages)]

    monkeypatch.setattr(embeddings, "_rerank_scores", scores)
    got = run(embeddings.rerank("a question", cands))
    assert seen["n"] == 10  # only the first ten are scored
    assert got[:10] == ["p9", "p2", "p4", "p3", "p0", "p1", "p5", "p6", "p7", "p8"]  # best first; equal scores keep the fused order
    assert got[10:] == ["p10", "p11", "p12", "p13"] and sorted(got) == sorted(c[0] for c in cands)  # the rest untouched, nothing added or lost
    assert run(embeddings.rerank("a question", cands[:1])) is None and run(embeddings.rerank("  ", cands)) is None


def test_a_reranker_failure_or_a_switched_off_reranker_means_the_order_is_kept_and_the_question_is_not_logged(monkeypatch, tmp_path, caplog):
    cands = [("a", "x"), ("b", "y")]
    monkeypatch.delenv("RERANKER_ENABLED", raising=False)
    assert run(embeddings.rerank("q", cands)) is None
    monkeypatch.setattr(embeddings, "reranker_enabled", lambda: True)
    secret = "a confidential client question about murder"

    def boom(q, passages):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(embeddings, "_rerank_scores", boom)
    with caplog.at_level(logging.ERROR, logger="vidhi.embeddings"):
        assert run(embeddings.rerank(secret, cands)) is None
    assert "RuntimeError" in caplog.text and secret not in caplog.text
    monkeypatch.setattr(embeddings, "_rerank_scores", lambda q, p: [1.0])  # the wrong number of scores is a failure too
    assert run(embeddings.rerank("q", cands)) is None


def test_search_marks_a_reranked_result_and_only_reorders_it(admin, user_a, monkeypatch):  # noqa: F811
    word = f"zqrerank{os.urandom(3).hex()}"
    t = load(admin, pages=[p.replace("festival of lamps", f"festival of lamps {word}") for p in FICTIONAL_PENAL_ACT])
    kept = prov_id(user_a, "3", t["title"])
    other = prov_id(user_a, "4", t["title"])
    q = f"hoards tokens festival of lamps {word}"

    async def fake(question, k=30):
        return [other, kept]

    monkeypatch.setattr(embeddings, "semantic_provision_ids", fake)
    plain = run(legal_search.search(q, limit=50))
    assert "reranked" not in plain
    ids = {v["id"] for v in plain["text"]}  # the limit is above the number of matches: with a smaller one, equal keyword scores are cut at an arbitrary place; equal scores may also come in any order, so sets are compared, not positions
    given = {}

    async def flip(question, cands):
        given["ids"] = [c[0] for c in cands]
        assert set(given["ids"]) == ids and all(c[1] for c in cands)
        return list(reversed(given["ids"]))

    monkeypatch.setattr(embeddings, "rerank", flip)
    on = run(legal_search.search(q, limit=50))
    assert on["reranked"] is True and [v["id"] for v in on["text"]] == list(reversed(given["ids"]))
    assert {v["id"]: v for v in on["text"]} == {v["id"]: v for v in plain["text"]}  # the very same views, including how each was found

    async def invent(question, cands):
        return [c[0] for c in cands] + ["not-a-provision"]  # a different set is never accepted

    monkeypatch.setattr(embeddings, "rerank", invent)
    refused = run(legal_search.search(q, limit=50))
    assert "reranked" not in refused and {v["id"] for v in refused["text"]} == ids


def test_the_new_code_makes_no_network_call_and_sends_no_client_text_anywhere():
    text = (Path(__file__).resolve().parent.parent / "lib" / "embeddings.py").read_text(encoding="utf-8")
    for banned in ("requests", "httpx", "aiohttp", "urllib", "socket", "ask_json", "lib.ai", "google"):
        assert banned not in text, banned
    assert "db.provisions" in text and "matter" not in text.replace("matter document", "").lower()  # only provisions are read; no matter document or private text


@pytest.mark.skipif(not (os.environ.get("EMBEDDINGS_MODEL_DIR") and (Path(os.environ.get("EMBEDDINGS_MODEL_DIR", "x")) / "onnx" / "model.onnx").exists()), reason="needs the real model (EMBEDDINGS_MODEL_DIR)")
def test_the_real_model_finds_the_murder_provision_for_an_english_and_a_hindi_question():
    import numpy as np

    emb = embeddings.Embedder(Path(os.environ["EMBEDDINGS_MODEL_DIR"]))
    passages = ["IPC section 302: Punishment for murder. Whoever commits murder shall be punished with death or imprisonment for life.",
                "IPC section 379: Punishment for theft. Whoever commits theft shall be punished with imprisonment.",
                "CrPC section 437: When bail may be taken in case of non-bailable offence. Bail may be granted by a court."]
    mat = emb.embed(passages, "passage: ")
    for question in ("What is the punishment for murder?", "हत्या के लिए क्या सज़ा है?"):
        q = emb.embed([question], "query: ")[0]
        assert int(np.argmax(mat @ q)) == 0, question
