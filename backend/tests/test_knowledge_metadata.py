"""What a stored knowledge chunk says about itself: which paragraphs of the document it holds, the script it is written in, and who owns it. Everything here is a fact the code can
know. Version, reviewer and language are deliberately NOT stored (a private or reference text has no reviewer, and a language cannot be told from letters alone). Older chunks that were
stored before these fields existed must still be found, and must show the fields as unknown rather than guessed. All texts are invented fixtures."""

import uuid

import pytest

from lib import knowledge
from lib.script_detect import script_of
from tests.inproc import run as run_on_client_loop


@pytest.mark.parametrize("text,expected", [
    ("The agreement was signed on 3 March.", "latin"),
    ("यह एक परीक्षण वाक्य है और यह हिंदी में लिखा है", "devanagari"),
    ("ఇది ఒక పరీక్ష వాక్యం మరియు ఇది తెలుగులో వ్రాయబడింది", "telugu"),
    ("இது ஒரு சோதனை வாக்கியம் இது தமிழில் எழுதப்பட்டது", "tamil"),
    ("Section 420 यह धारा", "mixed"),  # about half and half: no single script is claimed
    ("12345 ,.;", "none"),
    ("", "none"),
    ("これはテストです", "other"),  # a script this module does not list
])
def test_the_script_is_read_from_the_letters_and_never_guessed(text, expected):
    assert script_of(text) == expected


def test_the_script_is_not_a_language():
    # Devanagari carries Hindi, Marathi and Sanskrit: the stored value says only what the letters are
    assert script_of("यह एक परीक्षण है") == "devanagari" and "language" not in knowledge.chunk_text("यह एक परीक्षण है")[0]


def test_chunks_say_which_paragraphs_they_hold_counted_across_the_whole_document():
    text = "Chapter 1\n\nfirst paragraph here\n\nsecond paragraph here\n\nChapter 2\n\nthird paragraph here\n"
    chunks = knowledge.chunk_text(text)
    assert [(c["chapter"], c["para_from"], c["para_to"]) for c in chunks] == [("Chapter 1", 1, 2), ("Chapter 2", 3, 3)]  # the count continues into the next chapter
    assert [c["ordinal"] for c in chunks] == [0, 1]


def test_packed_and_split_paragraphs_keep_their_numbers(monkeypatch):
    monkeypatch.setattr(knowledge, "CHUNK", 60)
    short = "a" * 25
    long = "b" * 150
    chunks = knowledge.chunk_text(f"{short}\n\n{short}\n\n{long}\n\n{short}")
    # two short paragraphs packed together; the long one cut into pieces that each carry its number; the leftover end of the long one then packs with the next short paragraph (3 to 4)
    assert [(c["para_from"], c["para_to"]) for c in chunks] == [(1, 2), (3, 3), (3, 3), (3, 4)]
    assert [c["ordinal"] for c in chunks] == list(range(len(chunks)))
    assert "".join(c["text"] for c in chunks).replace("\n", "") == short * 2 + long + short  # nothing lost or repeated, in reading order


def test_an_empty_text_makes_no_chunks_and_a_blank_paragraph_is_not_counted():
    assert knowledge.chunk_text("") == []
    chunks = knowledge.chunk_text("one\n\n   \n\n\n\ntwo")
    assert [(c["para_from"], c["para_to"]) for c in chunks] == [(1, 2)]


def test_stored_chunks_carry_kind_script_and_paragraphs_and_search_shows_them_and_old_chunks_show_unknown():
    from lib.db import db

    async def run():
        org = f"meta-{uuid.uuid4().hex[:8]}"
        out = {}
        try:
            await knowledge.add_private_text(org, "Fixture", "TEST FIXTURE ONLY.\n\nzorbulant first paragraph.\n\nzorbulant second paragraph.")
            row = await db.knowledge_chunks.find_one({"org_id": org})
            out["row"] = {k: row.get(k) for k in ("kind", "script", "para_from", "para_to", "scope")}
            out["no_invented"] = [k for k in ("language", "version", "reviewer", "review_date", "court", "year") if k in row]
            # a chunk stored before these fields existed
            legacy = {"id": uuid.uuid4().hex, "work_number": row["work_number"], "scope": "org", "org_id": org, "sha256": "legacy" + uuid.uuid4().hex, "chapter": "", "ordinal": 99, "text": "zorbulant legacy chunk text"}
            await db.knowledge_chunks.insert_one(legacy)
            hits = (await knowledge.search("zorbulant", org, k=8))["hits"]
            out["hits"] = {h["position"]: (h["paragraphs"], h["script"]) for h in hits}
            out["other_org"] = (await knowledge.search("zorbulant", f"other-{uuid.uuid4().hex[:6]}", k=8))["hits"]
        finally:
            for w in await db.knowledge_works.find({"org_id": org}).to_list(10):
                await db.knowledge_chunks.delete_many({"work_number": w["number"]})
            await db.knowledge_works.delete_many({"org_id": org})
        return out

    out = run_on_client_loop(run())
    assert out["row"] == {"kind": "firm_knowledge", "script": "latin", "para_from": 1, "para_to": 3, "scope": "org"}
    assert out["no_invented"] == []  # nothing is stored that the code cannot know
    assert out["hits"] == {0: ([1, 3], "latin"), 99: (None, None)}  # new chunk: its paragraphs and script; the old chunk: unknown, not guessed
    assert out["other_org"] == []  # another organisation sees none of it


def test_a_library_chunk_is_a_reference_work_not_firm_knowledge():
    from lib.db import db

    async def run():
        number = -int(uuid.uuid4().int % 10**9) - 5_000_000_000
        try:
            await knowledge._store(number, "library", None, "TEST FIXTURE ONLY.\n\nmoonstitch fixture paragraph for the library.", False, status_after=False)
            row = await db.knowledge_chunks.find_one({"work_number": number})
            return row["kind"], row["org_id"], row["scope"]
        finally:
            await db.knowledge_chunks.delete_many({"work_number": number})

    assert run_on_client_loop(run()) == ("reference_work", None, "library")
