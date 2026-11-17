"""Phase 4 integration tests: one per bug in the audit, run against the live server with a SCRIPTED model.

The server runs with AI_STUB=true (replies queued per test) and a FICTIONAL test law library, so these tests
prove what the code does with whatever the model says - including a model that says wrong things.
"""

import hashlib
import uuid

import httpx
import pytest

from tests.conftest import ai_prompts, answer, mongo, new_matter, stub, upload

UNAVAILABLE = "Our AI service is busy or unavailable right now. Please try again in a minute."
CHAT = "\n".join(f"[1{i}/06/2026, 21:{i}0] Ravi: CHATMARKER message {i} about the balcony door" for i in range(1, 7))


def research(c, mid, question="What happened?", mode="MATTER"):
    return c.post("/research", json={"question": question, "matter_id": mid, "mode": mode})


def claim(text, kind="FACTUAL", cites=None, supports="YES", terms=None, conflicts=None):
    return {"text": text, "claim_kind": kind, "search_terms": terms or [], "supports": supports, "citations": cites or [], "conflicts": conflicts or []}


def doc_cite(ref, quote, page=1):
    return {"source": "MATTER_DOCUMENT", "ref": ref, "page": page, "quote": quote}


def lib_cite(ref, quote):
    return {"source": "LIBRARY", "ref": ref, "quote": quote}


# =============================================================================================
# Bug 1 / 4 / 7: the model must be shown EVERYTHING (or be told what it was not shown)
# =============================================================================================
def test_model_is_shown_all_ten_documents_including_the_eighth(user_a):
    mid, title = new_matter(user_a)
    for i in range(1, 11):
        upload(user_a, mid, f"{i:02d}-whatsapp-chat.txt" if i == 8 else f"{i:02d}-note.txt", CHAT if i == 8 else f"Note number {i}. " + "ordinary text " * 40)
    stub("research", answer("There is a chat in the file."), contains=title)
    r = research(user_a, mid, "Is there a WhatsApp chat in the matter file?")
    assert r.status_code == 200
    (prompt,) = ai_prompts(title, "research")
    for i in range(1, 11):
        assert f"[DOC-{i:02d}]" in prompt  # index lists every document
    assert "CHATMARKER message 3" in prompt  # and the eighth document's text was really shown
    cov = r.json()["coverage"]
    assert cov["complete"] is True and cov["documents_fully_read"] == 10 and "Read 10 of 10" in cov["summary"]


def test_when_the_matter_does_not_fit_the_answer_says_exactly_what_was_not_read(user_a, monkeypatch):
    # The real server's budget is unchanged; a huge matter proves the honest-coverage path end to end.
    mid, title = new_matter(user_a)
    for i in range(1, 8):
        upload(user_a, mid, f"{i:02d}-big.txt", f"Big document {i}. " + ("filler words here " * 4000))  # ~72 KB each
    stub("research", answer("Partial reading."), contains=title)
    cov = research(user_a, mid, "anything").json()["coverage"]
    assert cov["complete"] is False
    assert cov["documents_partly_read"] or cov["documents_not_read"]
    assert "Read" in cov["summary"] and ("only parts" in cov["summary"] or "NOT read" in cov["summary"])


# =============================================================================================
# Bug 1: "no WhatsApp chat" was VERIFIED while document 08 IS the chat
# =============================================================================================
def test_absence_claim_is_refuted_when_the_chat_exists_even_if_the_model_quotes_something(user_a):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01-fir.txt", "FIR registered at the police station about the incident.")
    upload(user_a, mid, "02-whatsapp-chat.txt", CHAT)
    stub(
        "research",
        answer(
            "The file contains no WhatsApp chat.",
            [claim("The matter file contains no WhatsApp chat.", "ABSENCE", cites=[doc_cite("DOC-01", "FIR registered at the police station")], terms=["whatsapp", "chat"])],
        ),
        contains=title,
    )
    res = research(user_a, mid, "Does the file contain a WhatsApp chat?").json()
    c = res["claims"][0]
    assert c["verification_status"] == "UNSUPPORTED"  # was VERIFIED before the fix
    # the prose of the answer still said "no chat"; the correction is added to it, naming the document
    assert "System check" in res["answer"] and "DOC-02" in res["answer"]
    assert "Contradicted" in c["note"] and "DOC-02" in c["note"]
    assert c["human_review_required"] is True


def test_absence_is_verified_only_after_every_document_was_searched(user_a):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01-fir.txt", "FIR registered at the police station.")
    upload(user_a, mid, "02-note.txt", "A note about the flat lease.")
    ab = claim("There is no Telegram chat.", "ABSENCE", terms=["telegram"])
    stub("research", answer("No Telegram chat.", [ab]), contains=title)
    got = research(user_a, mid, "Is there a Telegram chat?").json()["claims"][0]
    assert got["verification_status"] == "VERIFIED" and "Searched all 2 document" in got["note"]

    # Add a video: it cannot be searched, so the honest answer is PARTIALLY_VERIFIED.
    upload(user_a, mid, "cctv-01.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    stub("research", answer("No Telegram chat.", [ab]), contains=title)
    got = research(user_a, mid, "Is there a Telegram chat?").json()["claims"][0]
    assert got["verification_status"] == "PARTIALLY_VERIFIED" and "cctv-01.mp4" in got["note"]


def test_an_absence_claim_about_a_law_section_is_never_verified_by_searching_the_matter(user_a):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01-note.txt", "A note about the flat lease.")
    ab = claim("Section 15 of the MSMED Act is not found in the provided documents.", "ABSENCE", terms=["msmed"])
    stub("research", answer("Not found.", [ab]), contains=title)
    got = research(user_a, mid, "What does section 15 of the MSMED Act say?").json()["claims"][0]
    assert got["verification_status"] == "PARTIALLY_VERIFIED" and "does not show what the law says" in got["note"]


# =============================================================================================
# Quotes are checked in code; the model's opinion never verifies anything
# =============================================================================================
def test_factual_claims_are_verified_only_by_exact_quotes_and_conflicts_are_validated(user_a):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01-ledger.txt", "Ravi borrowed Rs 40,000 on 1 March 2026 from the shop.")
    upload(user_a, mid, "02-owner.txt", "The shop owner says Ravi repaid Rs 10,000 on 5 April 2026.")
    good = doc_cite("DOC-01", "Ravi borrowed Rs 40,000 on 1 March 2026")
    claims = [
        claim("Ravi borrowed Rs 40,000.", cites=[good]),  # 0 exact -> VERIFIED
        claim("Ravi borrowed Rs 90,000.", cites=[doc_cite("DOC-01", "Ravi borrowed Rs 90,000 on 1 March 2026")]),  # 1 invented quote
        claim("Ravi borrowed Rs 40,000 (disputed).", cites=[good], conflicts=[{"ref": "DOC-02", "page": 1, "quote": "Ravi repaid Rs 10,000 on 5 April 2026"}]),  # 2 real conflict
        claim("Ravi borrowed Rs 40,000 from the shop.", cites=[good], conflicts=[{"ref": "DOC-02", "page": 1, "quote": "a sentence that appears nowhere"}]),  # 3 fake conflict ignored
        claim("Ravi borrowed Rs 40,000 (unsure).", cites=[good], supports="PARTIAL"),  # 4 model unsure
        claim("Ravi borrowed Rs 40,000 (no cite).", cites=[]),  # 5 nothing cited
        claim("Cited a document that does not exist.", cites=[doc_cite("DOC-77", "Ravi borrowed Rs 40,000 on 1 March 2026")]),  # 6
    ]
    stub("research", answer("Ravi borrowed money.", claims), contains=title)
    got = research(user_a, mid, "What did Ravi borrow?").json()["claims"]
    status = [c["verification_status"] for c in got]
    assert status == ["VERIFIED", "UNSUPPORTED", "PARTIALLY_VERIFIED", "VERIFIED", "PARTIALLY_VERIFIED", "UNSUPPORTED", "UNSUPPORTED"]
    assert got[0]["citations"][0]["quote_verified"] is True and got[0]["citations"][0]["doc_label"] == "DOC-01"
    assert got[1]["citations"][0]["quote_verified"] is False
    assert len(got[2]["conflicts"]) == 1 and got[2]["conflicts"][0]["doc_label"] == "DOC-02"
    assert got[3]["conflicts"] == []
    assert got[0]["human_review_required"] is False and got[2]["human_review_required"] is True


# =============================================================================================
# Bug 2: "I am unsure" - failures are errors; next-steps questions get grounded answers
# =============================================================================================
@pytest.mark.parametrize(
    "reply",
    ["this is definitely not json", "__FAIL__", {"answer": "", "claims": []}],
    ids=["unparseable", "provider-failure", "empty-answer"],
)
def test_a_failed_or_empty_model_reply_is_an_error_never_displayed_as_unsure(user_a, reply):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01.txt", "Some matter text that is long enough.")
    stub("research", reply, contains=title)
    r = research(user_a, mid, "What are the next steps?")
    assert r.status_code == 502 and r.json()["detail"] == UNAVAILABLE
    assert "unsure" not in r.text.lower()
    assert user_a.get("/research", params={"matter_id": mid}).json() == []  # nothing saved as a fake answer


def test_next_steps_question_gets_concrete_grounded_suggestions_and_missing_information(user_a):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01-fir.txt", "FIR No 12 registered on 3 May 2026 at Central police station.")
    claims = [
        claim("Obtain a certified copy of the FIR.", "PROCEDURAL", cites=[doc_cite("DOC-01", "FIR No 12 registered on 3 May 2026")]),
        claim("Request the forensic report on the exhibits.", "PROCEDURAL"),
    ]
    reply = answer("Next: get the FIR copy and the forensic report.", claims)
    reply["missing_information"] = ["The date the forensic samples were collected"]
    stub("research", reply, contains=title)
    r = research(user_a, mid, "What should be our next steps?").json()
    assert [c["claim_kind"] for c in r["claims"]] == ["PROCEDURAL", "PROCEDURAL"]
    assert [c["verification_status"] for c in r["claims"]] == ["PARTIALLY_VERIFIED", "UNSUPPORTED"]
    assert all(c["human_review_required"] for c in r["claims"])  # suggestions always need a lawyer
    assert r["missing_information"] == ["The date the forensic samples were collected"]
    (prompt,) = ai_prompts(title, "research")
    assert "do not just say you are unsure" in prompt


# =============================================================================================
# Bug 3: law claims - only the verified library can verify, and only by exact text
# =============================================================================================
def test_library_is_loaded_and_bad_entries_are_rejected(user_a):
    lib = user_a.get("/library").json()
    ids = {e["id"] for e in lib["entries"]}
    assert {"test-widget-1", "test-widget-2"} <= ids and not ({"test-bad-hash", "test-no-verifier"} & ids)
    assert all("text" not in e for e in lib["entries"])  # the list is metadata only
    full = user_a.get("/library/test-widget-1").json()
    assert full["text"].startswith("TEST FIXTURE ONLY") and full["verified_by"] and full["source_url"]
    assert user_a.get("/library/test-bad-hash").status_code == 404
    assert user_a.get("/library/test-no-verifier").status_code == 404


@pytest.mark.parametrize(
    "citation",
    ["Section 1, Fictional Widget Testing Act, 2000", "sec 1 fictional widget testing act 2000", "Widget Act s.1", "test-widget-1"],
)
def test_verify_citation_finds_exact_library_entries_regardless_of_style(user_a, citation):
    v = user_a.post("/verify-citation", json={"citation": citation}).json()
    assert v["verification_status"] == "VERIFIED" and v["library_id"] == "test-widget-1"
    assert v["source_text"].startswith("TEST FIXTURE ONLY") and v["verified_by"] and "does not decide" in v["notes"]


def test_verify_citation_never_verifies_what_is_not_in_the_library(user_a):
    v = user_a.post("/verify-citation", json={"citation": "Section 5, Fictional Widget Testing Act, 2000"}).json()
    assert v["verification_status"] == "UNVERIFIED" and v["source_text"] is None
    assert v["suggestions"] and {"test-widget-1", "test-widget-2"} >= {s["id"] for s in v["suggestions"]}
    plain = user_a.post("/verify-citation", json={"citation": "Section 138, Negotiable Instruments Act"}).json()
    assert plain["verification_status"] == "UNVERIFIED"


def test_legal_claims_verify_only_against_library_text_and_a_full_matter_check(user_a):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01.txt", f"Ravi borrowed a widget. {title}")
    exact = "shall return the widget to the lender within thirty days"
    claims = [
        claim("A borrower must return the widget within thirty days.", "LEGAL", cites=[lib_cite("test-widget-1", exact)]),  # 0 -> VERIFIED
        claim("A borrower must return the widget to the lender within thirty days.", "LEGAL", cites=[lib_cite("Section 1, Fictional Widget Testing Act, 2000", exact)]),  # 1 -> VERIFIED
        claim("Return within sixty days.", "LEGAL", cites=[lib_cite("test-widget-1", "shall return the widget within sixty days")]),  # 2 altered quote
        claim("Cites a source that is not in the library.", "LEGAL", cites=[lib_cite("fake-id-123", "anything at all here")]),  # 3
        claim("A general legal point with no source.", "LEGAL"),  # 4
        claim("Library text but the model is unsure.", "LEGAL", cites=[lib_cite("test-widget-1", exact)], supports="PARTIAL"),  # 5
    ]
    stub("research", answer("Answer. Under Section 138 of the Negotiable Instruments Act the cheque is covered.", claims), contains=title)
    r = research(user_a, mid, "Must a borrowed widget be returned in thirty days?").json()
    assert [c["verification_status"] for c in r["claims"]] == ["VERIFIED", "VERIFIED", "UNSUPPORTED", "UNSUPPORTED", "UNSUPPORTED", "PARTIALLY_VERIFIED"]
    cit = r["claims"][0]["citations"][0]
    assert cit["library_id"] == "test-widget-1" and cit["authority_level"] == "PRIMARY" and cit["quote_verified"] is True
    assert r["claims"][2]["citations"][0]["quote_verified"] is False
    assert r["claims"][3]["citations"][0]["authority_level"] == "UNKNOWN"
    # a legal reference that is NOT in the library is surfaced, not hidden
    assert any("138" in ref for ref in r["unverified_references"])
    (prompt,) = ai_prompts(title, "research")
    assert "[test-widget-1]" in prompt and "VERIFIED LAW SOURCES (you may cite ONLY these" in prompt


def test_a_legal_claim_not_tied_to_a_matter_cannot_be_fully_verified(user_a):
    title = f"standalone {uuid.uuid4().hex[:8]} widget"
    exact = "shall return the widget to the lender within thirty days"
    stub("research", answer("Return in thirty days.", [claim("Thirty days.", "LEGAL", cites=[lib_cite("test-widget-1", exact)])]), contains=title)
    r = user_a.post("/research", json={"question": f"Must a borrowed widget be returned? {title}", "mode": "STANDARD"}).json()
    c = r["claims"][0]
    assert c["verification_status"] == "PARTIALLY_VERIFIED" and "not tied to a matter" in c["note"]


def test_with_no_matching_library_source_the_model_is_told_to_cite_nothing(user_a):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01.txt", "A plain note about a lease.")
    stub("research", answer("General answer."), contains=title)
    research(user_a, mid, "What is the notice period for terminating a lease?")
    (prompt,) = ai_prompts(title, "research")
    assert "none are available for this question" in prompt and "Do NOT name any section" in prompt


# =============================================================================================
# Rule 2: neutral wording
# =============================================================================================
def test_judgements_of_honesty_never_reach_the_user(user_a):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01.txt", "The witness said he arrived at nine in the evening.")
    stub(
        "research",
        answer(
            "The witness lied about the time. The statement is recorded in DOC-01.",
            [claim("The witness is a liar and fabricated the time.", cites=[doc_cite("DOC-01", "he arrived at nine in the evening")])],
        ),
        contains=title,
    )
    r = research(user_a, mid, "Was the witness consistent?").json()
    text = r["answer"] + " ".join(c["text"] for c in r["claims"])
    assert "lied" not in text and "liar" not in text and "fabricated" not in text
    assert r["neutral_adjusted"] is True and "The statement is recorded in DOC-01" in r["answer"]


# =============================================================================================
# Bug 7: "who was present" ignored the unmatched balcony fingerprint
# =============================================================================================
def test_presence_answers_must_account_for_unmatched_evidence(user_a):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01-lab.txt", "Forensic report. Exhibit 4 latent print on the balcony railing. Exhibit 2 print on the door handle.")
    for body in (
        {"kind": "FINGERPRINT", "label": "Latent print 4 on balcony railing", "status": "UNMATCHED"},
        {"kind": "FINGERPRINT", "label": "Print 2 on door handle", "status": "MATCHED", "identified_as": "Ravi"},
    ):
        assert user_a.post(f"/matters/{mid}/evidence", json=body).status_code == 200

    stub("research", answer("Ravi was present; his print is on the door handle."), contains=title)
    r = research(user_a, mid, "Who was present at the scene?").json()
    assert "Unresolved evidence" in r["answer"] and "Latent print 4 on balcony railing" in r["answer"]
    assert r["unresolved_evidence"] == ["Latent print 4 on balcony railing - unmatched"]
    (prompt,) = ai_prompts(title, "research")
    assert "Latent print 4 on balcony railing [FINGERPRINT] status UNMATCHED" in prompt

    # If the model already mentions it, nothing is appended - but the list is still returned.
    stub("research", answer("Ravi was present. Latent print 4 on balcony railing remains unmatched."), contains=title)
    r = research(user_a, mid, "Who was present at the scene?").json()
    assert "Unresolved evidence" not in r["answer"] and r["unresolved_evidence"]

    # A question that is not about presence does not get the block.
    stub("research", answer("A summary."), contains=title)
    assert research(user_a, mid, "Summarise the forensic report").json()["unresolved_evidence"] == []


# =============================================================================================
# Bug 5: evidence is not a contract
# =============================================================================================
FORENSIC = (
    "Forensic Science Laboratory report. Exhibit 4: latent print lifted from the balcony railing. "
    "The print was compared with the specimen of Ravi Kumar and does not match. "
    "Exhibit 2: print on the door handle matches Ravi Kumar. Chain of custody maintained."
)


def test_evidence_documents_get_an_evidence_analysis_not_clause_flags(user_a):
    mid, title = new_matter(user_a)
    d = upload(user_a, mid, "scene-report.txt", FORENSIC)
    assert d["doc_class"] == "FORENSIC_REPORT"
    stub(
        "analyze-evidence",
        {
            "summary": "Report on two prints. The analyst lied about nothing.",
            "key_facts": [{"fact": "Exhibit 4 does not match Ravi Kumar", "page": 1, "quote": "compared with the specimen of Ravi Kumar and does not match"}],
            "people": [{"name": "Ravi Kumar", "role": "person whose specimen was compared", "page": 1, "quote": "specimen of Ravi Kumar"}],
            "evidence_items": [
                {"kind": "FINGERPRINT", "label": "Exhibit 4 print, balcony railing", "status": "UNMATCHED", "identified_as": None, "location": "balcony railing", "page": 1, "quote": "latent print lifted from the balcony railing"},
                {"kind": "FINGERPRINT", "label": "Exhibit 2 print, door handle", "status": "MATCHED", "identified_as": "Ravi Kumar", "page": 1, "quote": "print on the door handle matches Ravi Kumar"},
                {"kind": "FINGERPRINT", "label": "Invented exhibit 9", "status": "UNMATCHED", "page": 1, "quote": "this sentence is nowhere in the document"},
            ],
            "anomalies": [{"what": "Exhibit 4 differs from the specimen", "page": 1, "quote": "does not match"}],
            "unclear": [],
        },
        contains=title,
    )
    r = user_a.post(f"/documents/{d['id']}/analyze")
    assert r.status_code == 200
    a = r.json()
    assert a["doc_class"] == "FORENSIC_REPORT" and a["flags"] == []  # no contract clauses on evidence
    assert a["key_facts"][0]["quote_verified"] is True and a["people"][0]["name"] == "Ravi Kumar"
    assert a["evidence_items_found"] == 2  # the invented item (quote not in the document) was dropped
    assert "lied" not in a["summary"] and a["neutral_adjusted"] is True
    items = user_a.get(f"/matters/{mid}/evidence").json()
    by_label = {i["label"]: i for i in items}
    assert set(by_label) == {"Exhibit 4 print, balcony railing", "Exhibit 2 print, door handle"}
    assert by_label["Exhibit 4 print, balcony railing"]["status"] == "UNMATCHED" and by_label["Exhibit 4 print, balcony railing"]["quote_verified"]
    assert by_label["Exhibit 2 print, door handle"]["identified_as"] == "Ravi Kumar" and by_label["Exhibit 2 print, door handle"]["source"] == "AI_EXTRACTED"
    (prompt,) = ai_prompts(title, "analyze-evidence")
    assert "This is evidence, NOT a contract" in prompt and "indemnity" not in prompt.lower()
    assert "[DOC-01] scene-report.txt" in prompt and "forensic report" in prompt.lower()

    # Re-analysing replaces the AI-extracted items rather than piling up duplicates.
    stub("analyze-evidence", {"summary": "Again.", "key_facts": [], "people": [], "anomalies": [], "unclear": [],
                              "evidence_items": [{"kind": "FINGERPRINT", "label": "Exhibit 4 print, balcony railing", "status": "UNMATCHED", "page": 1, "quote": "latent print lifted from the balcony railing"}]}, contains=title)
    assert user_a.post(f"/documents/{d['id']}/analyze").status_code == 200
    assert len(user_a.get(f"/matters/{mid}/evidence").json()) == 1


def test_contracts_still_get_clause_analysis_with_checked_quotes(user_a):
    mid, title = new_matter(user_a)
    d = upload(user_a, mid, "supply.txt", "This Agreement is made WHEREAS the supplier agrees. The supplier shall indemnify the buyer without limit. Termination on seven days notice. Governing law applies.")
    assert d["doc_class"] == "CONTRACT"
    stub(
        "analyze-contract",
        {"summary": "A supply agreement.", "flags": [
            {"clause": "Unlimited indemnity", "risk": "HIGH", "why": "No cap", "page": 1, "quote": "shall indemnify the buyer without limit"},
            {"clause": "Imaginary clause", "risk": "LOW", "why": "x", "page": 1, "quote": "a clause that is not in the contract"},
        ]},
        contains=title,
    )
    a = user_a.post(f"/documents/{d['id']}/analyze").json()
    assert [f["quote_verified"] for f in a["flags"]] == [True, False] and a["flags"][0]["risk"] == "HIGH"
    (prompt,) = ai_prompts(title, "analyze-contract")
    assert "indemnity" in prompt.lower()


def test_media_with_no_text_cannot_be_analysed_but_can_be_described(user_a):
    mid, title = new_matter(user_a)
    d = upload(user_a, mid, "cctv-lobby.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32)
    r = user_a.post(f"/documents/{d['id']}/analyze")
    assert r.status_code == 409 and "no readable text" in r.json()["detail"]
    p = user_a.patch(f"/documents/{d['id']}", json={"description": "Lobby camera 9pm: two people enter"}).json()
    assert p["description"].startswith("Lobby camera")
    stub("research", answer("Noted."), contains=title)
    research(user_a, mid, "What does the footage show?")
    (prompt,) = ai_prompts(title, "research")
    assert "NO TEXT AVAILABLE" in prompt and "described as: Lobby camera 9pm" in prompt


# =============================================================================================
# Bug 4: documents were analysed in isolation - now read together, who is who is resolved
# =============================================================================================
def test_matter_synthesis_resolves_people_across_documents_and_drops_unverifiable_claims(user_a):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01-bank.txt", "Account statement. Account holder: Mr. Anil Rao. Closing Balance 9,500. Debit 500 IFSC SBIN0001.")
    upload(user_a, mid, "02-whatsapp.txt", "\n".join(f"[1{i}/06/2026, 21:{i}0] Anil Rao (the deceased) wrote that he would be at the flat at nine" for i in range(1, 7)))
    q_chat = "Anil Rao (the deceased) wrote that he would be at the flat at nine"
    q_bank = "Account holder: Mr. Anil Rao"
    stub(
        "synthesize",
        {
            "people": [
                {"name": "Anil Rao", "role": "the deceased", "aliases": ["Mr. Rao"], "appearances": [
                    {"ref": "DOC-02", "page": 1, "quote": q_chat},
                    {"ref": "DOC-01", "page": 1, "quote": q_bank},
                    {"ref": "DOC-01", "page": 1, "quote": "a quote that is not in any document"},
                ]},
                {"name": "Ghost Person", "role": "unknown", "aliases": [], "appearances": [{"ref": "DOC-01", "page": 1, "quote": "never written anywhere in the file"}]},
            ],
            "inconsistencies": [
                {"description": "Anil lied about the time he would arrive", "a": {"ref": "DOC-02", "page": 1, "quote": q_chat}, "b": {"ref": "DOC-01", "page": 1, "quote": q_bank}},
                {"description": "Unsupported difference", "a": {"ref": "DOC-02", "page": 1, "quote": "not a real quote at all"}, "b": {"ref": "DOC-01", "page": 1, "quote": q_bank}},
            ],
            "unclear": ["Which flat is meant"],
        },
        contains=title,
    )
    r = user_a.post(f"/matters/{mid}/synthesize")
    assert r.status_code == 200
    s = r.json()
    assert [e["name"] for e in s["entities"]] == ["Anil Rao"] and len(s["entities"][0]["appearances"]) == 2
    assert s["entities"][0]["role"] == "the deceased"
    assert len(s["inconsistencies"]) == 1 and "lied" not in s["inconsistencies"][0]["description"] and s["neutral_adjusted"]
    assert s["dropped_unverified"] >= 2 and s["coverage"]["complete"] is True
    assert user_a.get(f"/matters/{mid}/entities").json()[0]["name"] == "Anil Rao"
    assert len(user_a.get(f"/matters/{mid}/inconsistencies").json()) == 1
    (prompt,) = ai_prompts(title, "synthesize")
    assert "[DOC-01]" in prompt and "[DOC-02]" in prompt  # both documents read together

    # The resolved people now inform research (the 'who is the deceased' gap).
    stub("research", answer("Anil Rao is the deceased."), contains=title)
    research(user_a, mid, "Who is the deceased?")
    (rp,) = ai_prompts(title, "research")
    assert "Anil Rao - the deceased" in rp


def test_synthesis_needs_documents_with_text_and_ai_failure_is_a_plain_error(user_a):
    mid, title = new_matter(user_a)
    assert user_a.post(f"/matters/{mid}/synthesize").status_code == 409
    upload(user_a, mid, "01.txt", "Some text in the matter file.")
    stub("synthesize", "__FAIL__", contains=title)
    r = user_a.post(f"/matters/{mid}/synthesize")
    assert r.status_code == 502 and r.json()["detail"] == UNAVAILABLE


# =============================================================================================
# Bug 6: graph - CCTV missing, document duplicated, edges all generic
# =============================================================================================
def test_media_evidence_is_accepted_stored_and_downloadable(user_a, user_b):
    mid, title = new_matter(user_a)
    video = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 4
    d = upload(user_a, mid, "cctv-01.mp4", video)
    assert d["media_kind"] == "VIDEO" and d["doc_class"] == "CCTV_LOG" and d["text_available"] is False
    assert d["has_file"] is True and d["processing_status"] == "READY"
    f = user_a.get(f"/documents/{d['id']}/file")
    assert f.status_code == 200 and f.content == video and f.headers["content-type"] == "video/mp4"
    assert f.headers["x-content-type-options"] == "nosniff"
    assert user_b.get(f"/documents/{d['id']}/file").status_code == 404
    assert user_a.post(f"/matters/{mid}/documents", files={"file": ("fake.mp4", b"this is not a video")}).status_code == 415


def test_uploading_the_same_file_twice_is_refused_and_never_duplicates_the_graph(user_a):
    mid, _ = new_matter(user_a)
    body = "[10/06/2026, 21:14] Ravi: hello there from the chat export\n" * 6
    first = upload(user_a, mid, "08-whatsapp.txt", body)
    r = user_a.post(f"/matters/{mid}/documents", files={"file": ("08-whatsapp-copy.txt", body.encode())})
    assert r.status_code == 409 and "08-whatsapp.txt" in r.json()["detail"]
    # Legacy duplicates already in the database still show once.
    dup = mongo().documents.find_one({"id": first["id"]})
    dup.pop("_id")
    from datetime import timedelta

    # a LATER duplicate (ObjectId order across processes is not monotonic, so say so with a timestamp)
    mongo().documents.insert_one(
        {**dup, "id": str(uuid.uuid4()), "filename": "08-whatsapp-dup.txt", "created_at": dup["created_at"] + timedelta(seconds=1)}
    )
    nodes = [n for n in user_a.get(f"/matters/{mid}/graph").json()["nodes"] if n["node_type"] == "DOCUMENT"]
    assert len(nodes) == 1 and nodes[0]["label"] == "08-whatsapp.txt"


def test_graph_has_typed_relationships_not_just_generic_links(user_a):
    mid, title = new_matter(user_a)
    bank = upload(user_a, mid, "01-bank.txt", "Account statement. Account holder: Mr. Anil Rao. Closing Balance 9,500. Debit 500 IFSC SBIN0001.")
    chat = upload(user_a, mid, "02-whatsapp.txt", "\n".join(f"[1{i}/06/2026, 21:{i}0] Anil Rao (the deceased) wrote that he would be at the flat" for i in range(1, 7)))
    upload(user_a, mid, "03-cctv.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x01" * 40)
    q1, q2 = "Anil Rao (the deceased) wrote that he would be at the flat", "Account holder: Mr. Anil Rao"
    stub("synthesize", {"people": [{"name": "Anil Rao", "role": "the deceased", "aliases": [], "appearances": [{"ref": "DOC-02", "page": 1, "quote": q1}, {"ref": "DOC-01", "page": 1, "quote": q2}]}],
                        "inconsistencies": [{"description": "The chat and the bank record give different details", "a": {"ref": "DOC-02", "page": 1, "quote": q1}, "b": {"ref": "DOC-01", "page": 1, "quote": q2}}], "unclear": []}, contains=title)
    assert user_a.post(f"/matters/{mid}/synthesize").status_code == 200
    user_a.post(f"/matters/{mid}/evidence", json={"kind": "CCTV_SIGHTING", "label": "Lobby sighting 9pm", "status": "MATCHED", "identified_as": "Anil Rao", "document_id": chat["id"]})
    user_a.post(f"/matters/{mid}/facts", json={"value": "Account closed on 3 May", "document_id": bank["id"]})
    user_a.post(f"/matters/{mid}/timeline", json={"event_date": "2026-05-03", "description": "Account closed", "document_id": bank["id"]})

    g = user_a.get(f"/matters/{mid}/graph").json()
    rels = {e["relation"] for e in g["edges"]}
    assert {"PART_OF", "MENTIONS", "EVIDENCES", "IDENTIFIED_AS", "CONTRADICTS", "DERIVED_FROM"} <= rels
    assert "RELATES_TO" not in rels  # every link now says what it is
    types = {n["node_type"] for n in g["nodes"]}
    assert {"MATTER", "DOCUMENT", "PERSON", "EVIDENCE", "FACT", "EVENT"} <= types
    docs = {n["label"]: n for n in g["nodes"] if n["node_type"] == "DOCUMENT"}
    assert set(docs) == {"01-bank.txt", "02-whatsapp.txt", "03-cctv.mp4"}  # the CCTV file is on the graph
    assert docs["03-cctv.mp4"]["sublabel"] == "CCTV_LOG" and docs["02-whatsapp.txt"]["sublabel"] == "CHAT"
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])


def test_graph_claims_are_deduplicated_across_research_runs(user_a):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01.txt", "Ravi borrowed Rs 40,000 on 1 March 2026 from the shop.")
    for _ in range(2):
        stub("research", answer("Ravi borrowed money.", [claim("Ravi borrowed Rs 40,000.", cites=[doc_cite("DOC-01", "Ravi borrowed Rs 40,000 on 1 March 2026")])]), contains=title)
        research(user_a, mid, "What did Ravi borrow?")
    g = user_a.get(f"/matters/{mid}/graph").json()
    assert len([n for n in g["nodes"] if n["node_type"] == "CLAIM"]) == 1
    assert any(e["relation"] == "SUPPORTS" for e in g["edges"])  # verified quote -> the document supports the claim


# =============================================================================================
# Document handling details
# =============================================================================================
def test_document_type_can_be_corrected_and_images_are_read_when_possible(user_a):
    mid, title = new_matter(user_a)
    d = upload(user_a, mid, "note.txt", "A plain note that is not obviously anything in particular.")
    assert d["doc_class"] == "OTHER" and d["doc_class_source"] == "AUTO"
    p = user_a.patch(f"/documents/{d['id']}", json={"doc_class": "LETTER"}).json()
    assert p["doc_class"] == "LETTER" and p["doc_class_source"] == "USER"
    assert user_a.patch(f"/documents/{d['id']}", json={"doc_class": "NOT_A_CLASS"}).status_code == 422

    stub("ocr", {"text": "Receipt for Rs 500 paid to the shop"})
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64 + uuid.uuid4().hex.encode()
    img = upload(user_a, mid, "receipt.png", png)
    assert img["media_kind"] == "IMAGE" and img["has_file"] is True
    detail = user_a.get(f"/documents/{img['id']}").json()
    assert detail["pages"] == ["Receipt for Rs 500 paid to the shop"] and detail["text_available"] is True


def test_facts_and_events_can_only_link_to_documents_in_the_same_matter(user_a, user_b):
    mid_a, _ = new_matter(user_a)
    mid_b, _ = new_matter(user_b)
    foreign = upload(user_b, mid_b, "b.txt", "Belongs to another organisation entirely.")
    own = upload(user_a, mid_a, "a.txt", "Belongs to this matter in this organisation.")
    assert user_a.post(f"/matters/{mid_a}/facts", json={"value": "x", "document_id": foreign["id"]}).status_code == 422
    assert user_a.post(f"/matters/{mid_a}/timeline", json={"event_date": "2026-05-03", "description": "x", "document_id": foreign["id"]}).status_code == 422
    assert user_a.post(f"/matters/{mid_a}/evidence", json={"label": "Item", "document_id": foreign["id"]}).status_code == 422
    assert user_a.post(f"/matters/{mid_a}/facts", json={"value": "x", "document_id": own["id"]}).status_code == 200


def test_deleting_a_matter_removes_everything_it_created(user_a):
    mid, title = new_matter(user_a)
    d = upload(user_a, mid, "cctv.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x02" * 40)
    upload(user_a, mid, "t.txt", "Anil Rao is named here in the text of this document.")
    user_a.post(f"/matters/{mid}/evidence", json={"label": "Some item", "document_id": d["id"]})
    stub("synthesize", {"people": [{"name": "Anil Rao", "role": "x", "appearances": [{"ref": "DOC-02", "page": 1, "quote": "Anil Rao is named here in the text"}]}], "inconsistencies": []}, contains=title)
    user_a.post(f"/matters/{mid}/synthesize")
    db = mongo()
    gid = db.documents.find_one({"id": d["id"]})["gridfs_id"]
    assert db.fs.files.count_documents({"_id": gid}) == 1 and db.entities.count_documents({"matter_id": mid}) == 1
    assert user_a.delete(f"/matters/{mid}").status_code == 200
    assert db.fs.files.count_documents({"_id": gid}) == 0
    for coll in ("documents", "evidence_items", "entities", "inconsistencies", "facts"):
        assert db[coll].count_documents({"matter_id": mid}) == 0, coll


# =============================================================================================
# Another organisation can reach none of it
# =============================================================================================
def test_other_org_cannot_reach_evidence_people_files_or_analysis(user_a, user_b):
    mid, title = new_matter(user_a)
    d = upload(user_a, mid, "x.txt", "Text that another firm must never be able to read.")
    ev = user_a.post(f"/matters/{mid}/evidence", json={"label": "Secret item"}).json()
    for method, path, body in (
        ("GET", f"/matters/{mid}/evidence", None),
        ("POST", f"/matters/{mid}/evidence", {"label": "planted"}),
        ("PATCH", f"/matters/{mid}/evidence/{ev['id']}", {"status": "MATCHED"}),
        ("DELETE", f"/matters/{mid}/evidence/{ev['id']}", None),
        ("GET", f"/matters/{mid}/entities", None),
        ("GET", f"/matters/{mid}/inconsistencies", None),
        ("POST", f"/matters/{mid}/synthesize", None),
        ("GET", f"/documents/{d['id']}/file", None),
        ("PATCH", f"/documents/{d['id']}", {"description": "hijack"}),
        ("POST", f"/documents/{d['id']}/analyze", None),
    ):
        r = user_b.request(method, path, json=body)
        assert r.status_code == 404, f"{method} {path} -> {r.status_code}"
    assert user_a.get(f"/matters/{mid}/evidence").json()[0]["label"] == "Secret item"
    # and the router exposes no unauthenticated route
    with httpx.Client(base_url=str(user_a.base_url)) as anon:
        assert anon.get(f"/matters/{mid}/evidence").status_code == 401
        assert anon.get("/library").status_code == 401


def test_every_research_answer_records_the_version_of_each_source_it_used(user_a):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01.txt", f"Ravi borrowed a widget. {title}")
    exact = "shall return the widget to the lender within thirty days"
    stub("research", answer("A borrower must return the widget.", [claim("A borrower must return the widget to the lender within thirty days.", "LEGAL", cites=[lib_cite("test-widget-1", exact)])]), contains=title)
    r = research(user_a, mid, "Must a borrowed widget be returned in thirty days?").json()
    versions = r["source_versions"]
    library = [s for s in versions if s["source_kind"] == "verified_library"]
    assert library and all(s["status"] == "VERIFIED" and s["reviewed_by"] and s["checked_on"] and s["version"] and s["source_link"] and len(s["text_sha256"]) == 64 for s in library)
    documents = [s for s in versions if s["source_kind"] == "matter_document"]
    assert documents and documents[0]["citation"] == "01.txt" and len(documents[0]["text_sha256"]) == 64 and documents[0]["status"].startswith("UNVERIFIED")
    assert mongo().research_results.find_one({"id": r["id"]})["source_versions"] == versions  # saved with the answer, not only returned


def test_a_verified_citation_lookup_names_the_version_it_showed(user_a):
    v = user_a.post("/verify-citation", json={"citation": "test-widget-1"}).json()
    assert v["verification_status"] == "VERIFIED"
    (s,) = v["source_versions"]
    assert s["source_kind"] == "verified_library" and s["id"] == "test-widget-1" and s["version"] == v["version"] and s["reviewed_by"] == v["verified_by"] and s["checked_on"] == v["verified_on"]
    assert s["text_sha256"] == hashlib.sha256(v["source_text"].encode("utf-8")).hexdigest()  # the hash is of the exact text that was shown
    assert user_a.post("/verify-citation", json={"citation": "Section 9, No Such Act"}).json()["source_versions"] == []  # nothing was used, so nothing is recorded
