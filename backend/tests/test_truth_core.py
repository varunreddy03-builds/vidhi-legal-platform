"""The truth engine's pure logic: classification, neutral wording, exact-quote verification, absence scans,
claim statuses, whole-matter context and the verified-library loader. No server or AI needed."""

from pathlib import Path

import pytest

from lib import library
from lib.classify import classify_document, media_kind
from lib.matter_context import build_corpus, index_text, select_context
from lib.neutral import STUB, is_neutral, neutralize
from lib.verify import absence_scan, decide, find_quote, resolve_doc

FIXTURES = Path(__file__).parent / "fixtures" / "legal_library"


# ---------------- classification (bug 5: evidence must not be treated as a contract) ----------------
CHAT = "\n".join(f"[1{i}/06/2026, 10:{i}0] Ravi: message number {i}" for i in range(1, 8))
BANK = "ACCOUNT STATEMENT\nOpening Balance 10,000\nNarration UPI/123 Debit 500\nIFSC SBIN0000001\nClosing Balance 9,500 Credit 0"
FORENSIC = "Forensic Science Laboratory\nLatent print lifted from the balcony railing. Exhibit 4. Chain of custody maintained."
CONTRACT = "This Agreement is made BETWEEN the parties, WHEREAS the supplier agrees. Termination and governing law apply. Indemnify."


@pytest.mark.parametrize(
    "name,text,expected",
    [
        ("08-whatsapp.txt", CHAT, "CHAT"),
        ("export.txt", CHAT, "CHAT"),
        ("hdfc.txt", BANK, "BANK_STATEMENT"),
        ("lab.pdf", FORENSIC, "FORENSIC_REPORT"),
        ("supply.docx", CONTRACT, "CONTRACT"),
        ("note.txt", "Hello, a short note about nothing in particular.", "OTHER"),
    ],
)
def test_classification(name, text, expected):
    assert classify_document(name, [text]) == expected


def test_media_is_classified_by_kind_and_name():
    assert media_kind("cctv-01.mp4") == "VIDEO" and media_kind("a.JPG") == "IMAGE" and media_kind("a.wav") == "AUDIO"
    assert media_kind("a.pdf") == "TEXT"
    assert classify_document("cctv-lobby.mp4", []) == "CCTV_LOG"
    assert classify_document("scene.jpg", []) == "MEDIA"


# ---------------- neutral wording (rule 2) ----------------
def test_neutralize_replaces_only_the_offending_sentence():
    text = "The bank record shows a transfer on 3 May. The witness lied about the date. The chat is dated 4 May."
    out, changed = neutralize(text)
    assert changed and "lied" not in out and STUB in out
    assert "bank record shows a transfer" in out and "chat is dated 4 May" in out


@pytest.mark.parametrize("bad", ["He is a liar.", "This was perjury.", "A dishonest answer.", "They fabricated it.", "Clearly guilty."])
def test_judgements_of_honesty_are_removed(bad):
    out, changed = neutralize(bad)
    assert changed and is_neutral(out)


def test_neutral_text_is_untouched():
    t = "The statement differs from the record in two respects."
    assert neutralize(t) == (t, False) and is_neutral(t)


# ---------------- exact quotes ----------------
def test_find_quote_is_exact_but_tolerant_of_layout():
    pages = ["Page one text.", "The  deceased,\nMr. Rao   was last seen at 9 pm."]
    assert find_quote("the deceased, mr. rao was last seen at 9 pm", pages) == 2
    assert find_quote("The deceased wasn't seen", pages) is None  # invented
    assert find_quote("too short", pages) is None  # under the minimum length proves nothing


def _corpus(*specs):
    docs = [
        {"id": f"id{i}", "filename": n, "doc_class": c, "media_kind": "TEXT", "description": d, "pages": p}
        for i, (n, c, d, p) in enumerate(specs, start=1)
    ]
    return build_corpus(docs)


def test_resolve_doc_forms():
    corpus = _corpus(("a.txt", "OTHER", "", ["x"]), ("b.txt", "OTHER", "", ["y"]))
    assert resolve_doc("DOC-02", corpus)["filename"] == "b.txt"
    assert resolve_doc("doc 1", corpus)["filename"] == "a.txt"
    assert resolve_doc("[DOC-01]", corpus)["filename"] == "a.txt"
    assert resolve_doc("id2", corpus)["filename"] == "b.txt"
    assert resolve_doc("B.TXT", corpus)["filename"] == "b.txt"
    assert resolve_doc("DOC-09", corpus) is None and resolve_doc("", corpus) is None


# ---------------- absence scan (bug 1) ----------------
def test_absence_scan_finds_the_chat_by_class_even_without_the_word():
    corpus = _corpus(("contract.txt", "CONTRACT", "", ["agreement"]), ("08.txt", "CHAT", "", ["[1/6/2026, 10:00] hi there"]))
    scan = absence_scan(["whatsapp chat", "chat"], corpus)
    assert any(h["doc"] == "DOC-02" for h in scan["hits"])


def test_absence_scan_reports_unsearchable_documents():
    corpus = _corpus(("a.txt", "OTHER", "", ["nothing relevant"]), ("cctv.mp4", "CCTV_LOG", "", []))
    scan = absence_scan(["telegram"], corpus)
    assert scan["hits"] == [] and scan["unsearchable"] == ["DOC-02 cctv.mp4"]


# ---------------- claim statuses ----------------
def _decide(kind, **kw):
    base = dict(valid_matter_quote=False, valid_library_quote=False, supports="UNSURE", coverage_complete=True, has_matter=True, conflicts=[], absence=None)
    base.update(kw)
    return decide(kind, **base)


def test_absence_claim_contradicted_by_a_document_is_unsupported_not_verified():
    corpus = _corpus(("08-chat.txt", "CHAT", "", ["[1/6/2026, 10:00] whatsapp message"]))
    status, note = _decide("ABSENCE", absence=absence_scan(["whatsapp"], corpus))
    assert status == "UNSUPPORTED" and "Contradicted" in note and "DOC-01" in note


def test_absence_claim_verified_only_after_searching_everything():
    corpus = _corpus(("a.txt", "OTHER", "", ["plain note"]))
    scan = absence_scan(["telegram"], corpus)
    assert _decide("ABSENCE", absence=scan)[0] == "VERIFIED"
    assert _decide("ABSENCE", absence=scan, coverage_complete=False)[0] == "PARTIALLY_VERIFIED"
    with_media = absence_scan(["telegram"], _corpus(("a.txt", "OTHER", "", ["note"]), ("v.mp4", "MEDIA", "", [])))
    assert _decide("ABSENCE", absence=with_media)[0] == "PARTIALLY_VERIFIED"
    assert _decide("ABSENCE", absence={"terms": [], "hits": [], "searched": 1, "unsearchable": []})[0] == "UNSUPPORTED"


def test_legal_claim_needs_library_text_and_a_full_matter_check():
    assert _decide("LEGAL")[0] == "UNSUPPORTED"
    assert _decide("LEGAL", valid_library_quote=True, supports="YES")[0] == "VERIFIED"
    assert _decide("LEGAL", valid_library_quote=True, supports="PARTIAL")[0] == "PARTIALLY_VERIFIED"  # model unsure
    assert _decide("LEGAL", valid_library_quote=True, supports="YES", has_matter=False)[0] == "PARTIALLY_VERIFIED"
    assert _decide("LEGAL", valid_library_quote=True, supports="YES", coverage_complete=False)[0] == "PARTIALLY_VERIFIED"
    assert _decide("LEGAL", valid_library_quote=True, supports="YES", conflicts=[{"doc": "DOC-01"}])[0] == "PARTIALLY_VERIFIED"


def test_factual_claim_needs_an_exact_passage_and_no_conflict():
    assert _decide("FACTUAL")[0] == "UNSUPPORTED"
    assert _decide("FACTUAL", valid_matter_quote=True, supports="YES")[0] == "VERIFIED"
    assert _decide("FACTUAL", valid_matter_quote=True, supports="YES", conflicts=[{"doc": "DOC-02"}])[0] == "PARTIALLY_VERIFIED"
    assert _decide("FACTUAL", valid_matter_quote=True, supports="YES", coverage_complete=False)[0] == "PARTIALLY_VERIFIED"


def test_model_opinion_alone_never_verifies_anything():
    for kind in ("LEGAL", "FACTUAL", "PROCEDURAL", "ABSENCE"):
        assert _decide(kind, supports="YES")[0] != "VERIFIED", kind


def test_procedural_suggestions_are_never_verified():
    assert _decide("PROCEDURAL")[0] == "UNSUPPORTED"
    assert _decide("PROCEDURAL", valid_matter_quote=True, supports="YES")[0] == "PARTIALLY_VERIFIED"


# ---------------- whole-matter context (bugs 1, 2, 4, 7) ----------------
def _ten_docs(chat_index=8):
    specs = []
    for i in range(1, 11):
        if i == chat_index:
            specs.append((f"{i:02d}-whatsapp.txt", "CHAT", "", ["[1/6/2026, 10:00] Ravi: the balcony door was open " + "filler " * 300]))
        else:
            specs.append((f"{i:02d}-doc.txt", "OTHER", "", [f"Document {i} ordinary content. " + "padding " * 400]))
    return _corpus(*specs)


def test_everything_is_included_when_it_fits():
    corpus = _ten_docs()
    text, cov = select_context("anything", corpus, budget=1_000_000)
    assert cov["complete"] and cov["documents_fully_read"] == 10 and cov["documents_not_read"] == []
    assert "[DOC-08]" in text and "balcony door was open" in text


def test_every_document_is_touched_even_when_the_budget_is_small():
    corpus = _ten_docs()
    text, cov = select_context("is there a whatsapp chat", corpus, budget=22_000)
    assert cov["documents_not_read"] == []  # nothing entirely unread
    assert cov["complete"] is False and cov["documents_partly_read"]  # but honest that it is partial
    for n in range(1, 11):
        assert f"[DOC-{n:02d}]" in text
    assert "balcony door was open" in text  # the relevant passage in doc 08 was prioritised


def test_unread_documents_are_named_when_even_one_passage_each_cannot_fit():
    corpus = _ten_docs()
    _, cov = select_context("whatsapp", corpus, budget=4000)
    assert cov["documents_not_read"] and cov["complete"] is False
    assert "NOT read" in cov["summary"]


def test_index_lists_every_document_including_media():
    corpus = _corpus(("a.txt", "OTHER", "", ["text"]), ("cctv.mp4", "CCTV_LOG", "Lobby camera 9pm", []))
    idx = index_text(corpus)
    assert "[DOC-01] a.txt" in idx and "[DOC-02] cctv.mp4" in idx and "NO TEXT AVAILABLE" in idx and "Lobby camera 9pm" in idx
    _, cov = select_context("x", corpus)
    assert cov["documents_without_text"] == ["DOC-02 cctv.mp4"] and cov["complete"] is True  # text docs fully read


# ---------------- verified library loader (rule 1) ----------------
def test_every_entry_in_the_production_library_is_valid():
    """The shipped folder is empty today. Once a lawyer adds entries, none may be malformed or unsigned -
    a broken entry must fail CI rather than be silently ignored at startup."""
    _, rejected = library.load_entries(library.DEFAULT_DIR)
    assert rejected == []


def test_fixture_library_accepts_signed_entries_and_rejects_bad_ones():
    valid, rejected = library.load_entries(FIXTURES)
    assert sorted(e["id"] for e in valid) == ["test-widget-1", "test-widget-2"]
    reasons = {r["id"]: " ".join(r["errors"]) for r in rejected}
    assert "does not match" in reasons["test-bad-hash"]
    assert "verified_by" in reasons["test-no-verifier"]


@pytest.mark.parametrize(
    "variant",
    [
        "Section 1, Fictional Widget Testing Act, 2000",
        "section 1 fictional widget testing act 2000",
        "Sec. 1, the Fictional Widget Testing Act, 2000",
        "S. 1 Fictional Widget Testing Act 2000",
    ],
)
def test_citation_normalisation_is_forgiving_about_style_only(variant):
    assert library.norm_citation(variant) == library.norm_citation("Section 1, Fictional Widget Testing Act, 2000")


def test_citation_normalisation_never_conflates_different_provisions():
    assert library.norm_citation("Section 1, Fictional Widget Testing Act, 2000") != library.norm_citation("Section 2, Fictional Widget Testing Act, 2000")
    assert library.norm_citation("Section 11, Act") != library.norm_citation("Section 1, Act")
