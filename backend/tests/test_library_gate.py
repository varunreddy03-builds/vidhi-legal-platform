"""The review gate: a draft in pending/ can never verify a claim, whatever it says about itself; only an approved entry can."""

import json
import os
import subprocess
import sys
from pathlib import Path


from lib import jurisdictions, library
from tests.conftest import mongo

FIXTURES = Path(os.path.abspath(__file__)).parent / "fixtures" / "legal_library"
ROOT = Path(os.path.abspath(__file__)).parent.parent  # not resolve(): a short junction path must stay short on Windows


def test_a_draft_is_reported_unverified_even_if_it_claims_to_be_verified():
    drafts = library.load_pending(FIXTURES)
    d = next(x for x in drafts if x["id"] == "test-pending-act")
    assert d["status"] == library.PENDING_STATUS and d["reviewer"] is None and d["reviewed_on"] is None


def test_a_draft_is_never_part_of_the_verified_library():
    valid, rejected = library.load_entries(FIXTURES)
    assert "test-pending-act" not in {e["id"] for e in valid} and "test-pending-act" not in {r["id"] for r in rejected}


def test_an_entry_marked_unverified_is_rejected_from_the_library_folder():
    e = {"id": "x", "citation": "c", "kind": "OTHER", "text": "t", "text_sha256": library.sha256_text("t"), "source_name": "s", "source_url": "u",
         "version": "v", "verified_by": "Someone", "verified_on": "2026-01-01", "status": "UNVERIFIED - pending lawyer review"}
    assert any("unverified" in err for err in library.validate_entry(e))


def test_templates_and_underscore_files_are_ignored(tmp_path):
    (tmp_path / "pending").mkdir()
    (tmp_path / "pending" / "_TEMPLATE.json").write_text((ROOT / "data" / "legal_library" / "pending" / "_TEMPLATE.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert library.load_pending(tmp_path) == []  # a folder holding only the template has no draft and no verified entry
    # Since 2026-11-01 the shipped pending/ folder holds mechanically extracted drafts (scripts/law_extract.py); the VERIFIED library must still be empty.
    assert library.load_entries(ROOT / "data" / "legal_library")[0] == []
    assert all(d["status"] == library.PENDING_STATUS and d["reviewer"] is None for d in library.load_pending(ROOT / "data" / "legal_library"))


def test_the_shipped_structure_exists_and_is_empty_of_law():
    base = ROOT / "data" / "legal_library"
    for sub in ("pending", "IN", "AE", "UK", "US", "SG"):
        assert (base / sub).is_dir()
    for sub in ("AE", "UK", "US", "SG"):
        assert "Not supported yet" in (base / sub / "README.md").read_text(encoding="utf-8")
    schema = json.loads((base / "schema.json").read_text(encoding="utf-8"))
    assert {"verified_by", "verified_on", "text_sha256"} <= set(schema["required"])
    assert "UNVERIFIED" in (base / "pending" / "_TEMPLATE.json").read_text(encoding="utf-8")


def test_only_india_is_live_until_the_others_are_ready():
    assert jurisdictions.live() == {"IN"}
    assert {j.currency for j in jurisdictions.REGISTRY.values()} == {"INR", "AED", "GBP", "USD", "SGD"}
    assert not jurisdictions.is_live("AE")


def test_the_api_lists_drafts_as_unverified_and_will_not_serve_them_as_law(user_a):
    lib = user_a.get("/library").json()
    assert lib["pending_count"] >= 1 and all(p["status"] == library.PENDING_STATUS for p in lib["pending"])
    assert "test-pending-act" not in {e["id"] for e in lib["entries"]}
    assert user_a.get("/library/test-pending-act").status_code == 404
    assert mongo().legal_sources.find_one({"id": "test-pending-act"}) is None and mongo().library_entries.find_one({"id": "test-pending-act"}) is None
    juris = {j["code"]: j["status"] for j in user_a.get("/library/jurisdictions").json()}
    assert juris == {"IN": "live", "AE": "planned", "UK": "planned", "US": "planned", "SG": "planned"}


def run_review(tmp: Path, *args: str):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "library_review.py"), *args], capture_output=True, text=True, cwd=ROOT,
                          env={**__import__("os").environ, "LIBRARY_DIR": str(tmp)})


def test_approving_needs_a_reviewer_and_makes_a_verified_entry(tmp_path, monkeypatch):
    lib_dir = tmp_path / "lib"
    (lib_dir / "pending").mkdir(parents=True)
    draft = {"id": "fict-1", "citation": "Section 1, Fictional Act", "kind": "STATUTE_SECTION", "jurisdiction": "IN", "text": "Fictional exact text.",
             "source_name": "Fictional", "source_url": "https://example.invalid/x", "version": "test"}
    (lib_dir / "pending" / "fict-1.json").write_text(json.dumps(draft), encoding="utf-8")
    monkeypatch.setattr("lib.library.DEFAULT_DIR", lib_dir)
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    code = (
        "import sys; sys.argv=['x','approve','--id','fict-1','--reviewer','Test Reviewer','--on','2099-01-01'];"
        "import lib.library as L; from pathlib import Path; L.DEFAULT_DIR=Path(r'%s');"
        "sys.path.insert(0, r'%s'); import runpy; sys.modules['lib.library']=L; runpy.run_path(r'%s', run_name='__main__')" % (lib_dir, ROOT, ROOT / "scripts" / "library_review.py")
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert res.returncode == 0, res.stdout + res.stderr
    approved = json.loads((lib_dir / "IN" / "fict-1.json").read_text(encoding="utf-8"))
    assert approved["verified_by"] == "Test Reviewer" and approved["verified_on"] == "2099-01-01"
    assert approved["text_sha256"] == library.sha256_text("Fictional exact text.")
    assert library.validate_entry(approved) == [] and not (lib_dir / "pending" / "fict-1.json").exists()


def test_a_country_that_is_not_live_cannot_be_approved(tmp_path):
    lib_dir = tmp_path / "lib"
    (lib_dir / "pending").mkdir(parents=True)
    (lib_dir / "pending" / "d.json").write_text(json.dumps({"id": "d", "citation": "c", "kind": "OTHER", "jurisdiction": "UK", "text": "t", "source_name": "s", "source_url": "u", "version": "v"}), encoding="utf-8")
    code = (
        "import sys; sys.argv=['x','approve','--id','d','--reviewer','R','--on','2099-01-01'];"
        "import lib.library as L; from pathlib import Path; L.DEFAULT_DIR=Path(r'%s');"
        "sys.path.insert(0, r'%s'); import runpy; runpy.run_path(r'%s', run_name='__main__')" % (lib_dir, ROOT, ROOT / "scripts" / "library_review.py")
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert res.returncode == 1 and "not live" in res.stdout

def test_draft_law_can_be_searched_and_paged_but_is_always_labelled_not_reviewed(user_a):
    r = user_a.get("/library/drafts", params={"q": "gadget labelled"}).json()
    assert r["status"] == library.PENDING_STATUS and "Not reviewed" in r["note"]
    hit = next(x for x in r["items"] if x["id"] == "test-pending-act")
    assert hit["status"] == library.PENDING_STATUS and "gadget" in hit["excerpt"] and hit["note"] == library.DRAFT_NOTE
    page = user_a.get("/library/drafts", params={"limit": 1}).json()
    assert len(page["items"]) == 1 and page["total"] >= 1
    full = user_a.get("/library/drafts/test-pending-act").json()
    assert "gadget" in full["text"] and full["status"] == library.PENDING_STATUS
    assert user_a.get("/library/drafts/no-such-draft").status_code == 404
    assert any(a["act_id"] == "test-pending" for a in user_a.get("/library/drafts/acts").json()["acts"])
    assert user_a.get("/library/test-pending-act").status_code == 404  # still not served as law


def test_a_repealed_law_is_marked_historical():
    assert library.draft_view({"id": "i", "citation": "c", "legal_currency": "HISTORICAL - not current law; REPEALED by BNS"})["historical"] is True
    assert library.draft_view({"id": "i", "citation": "c", "legal_currency": "Current law"})["historical"] is False


def test_the_library_keeps_its_own_collection_and_clears_old_copies_from_the_operators_sources(user_a, monkeypatch):
    import asyncio

    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])  # each asyncio.run() makes a new event loop; a client belongs to the loop it first ran in
    monkeypatch.setattr(library, "db", client[os.environ["DB_NAME"]])
    db = mongo()
    db.legal_sources.insert_one({"id": "legacy-lib-copy", "origin": "library", "status": "VERIFIED", "citation": "Old copy"})
    db.legal_sources.insert_one({"id": "operator-src-keep", "name": "Operator source", "status": "terms-recorded"})
    try:
        asyncio.run(library.sync_library())
        assert db.legal_sources.find_one({"id": "legacy-lib-copy"}) is None  # the old library copy is gone from the operator's collection
        assert db.legal_sources.find_one({"id": "operator-src-keep"}) is not None  # the operator's own record is untouched
    finally:
        db.legal_sources.delete_many({"id": {"$in": ["legacy-lib-copy", "operator-src-keep"]}})


def _india_code_draft(tmp_path):
    (tmp_path / "pending").mkdir()
    e = {"id": "fict-act-1", "citation": "Section 1, Fictional Act", "kind": "STATUTE_SECTION", "text": "Fictional text.", "text_sha256": library.sha256_text("Fictional text."),
         "source_name": "India Code (Legislative Department): fictional file", "source_url": "https://example.invalid/x", "version": "test", "status": library.PENDING_STATUS}
    (tmp_path / "pending" / "fict.json").write_text(json.dumps({"entries": [e]}), encoding="utf-8")


def test_drafts_from_a_source_that_needs_permission_are_not_loaded_until_the_permission_is_recorded(tmp_path, monkeypatch):
    _india_code_draft(tmp_path)
    monkeypatch.delenv("INDIA_CODE_PERMISSION_REF", raising=False)
    assert library.load_pending(tmp_path) == []
    monkeypatch.setenv("INDIA_CODE_PERMISSION_REF", "short")  # too short to describe who gave it and when
    assert library.load_pending(tmp_path) == []
    monkeypatch.setenv("INDIA_CODE_PERMISSION_REF", "Letter from the Legislative Department dated 2026-12-01, kept in the legal folder")
    assert [d["id"] for d in library.load_pending(tmp_path)] == ["fict-act-1"]




def test_the_ministry_portal_switch_does_not_turn_on_india_code(tmp_path, monkeypatch):
    _india_code_draft(tmp_path)
    ncrb = {"id": "ncrb-fict-1", "citation": "Section 1, The Fictional Act, 2000", "kind": "STATUTE_SECTION", "jurisdiction": "IN", "text": "1. Fictional words.", "text_sha256": library.sha256_text("1. Fictional words."), "source_name": "NCRB Sankalan portal (Ministry of Home Affairs): Chapters and Sections",
            "source_url": "https://example.test/x", "version": "fictional", "status": "UNVERIFIED - pending lawyer review"}
    (tmp_path / "pending" / "ncrb-fict.json").write_text(json.dumps({"entries": [ncrb]}), encoding="utf-8")
    monkeypatch.delenv("INDIA_CODE_PERMISSION_REF", raising=False)
    monkeypatch.delenv("NCRB_PORTAL_USE_REF", raising=False)
    assert library.load_pending(tmp_path) == []
    monkeypatch.setenv("NCRB_PORTAL_USE_REF", "Owner decision in chat, 2026-11-03: use the portal text, unreviewed")
    assert [d["id"] for d in library.load_pending(tmp_path)] == ["ncrb-fict-1"]  # India Code's draft is still not loaded
    monkeypatch.setenv("INDIA_CODE_PERMISSION_REF", "Letter from the Legislative Department dated 2026-12-01, kept in the legal folder")
    assert sorted(d["id"] for d in library.load_pending(tmp_path)) == ["fict-act-1", "ncrb-fict-1"]


def test_the_old_codes_switch_turns_on_only_the_three_repealed_codes(tmp_path, monkeypatch):
    (tmp_path / "pending").mkdir()

    def draft(i, name):
        text = f"{i}. Fictional words."
        return {"id": f"{name}-1", "citation": f"Section 1, {name}", "kind": "STATUTE_SECTION", "jurisdiction": "IN", "text": text, "text_sha256": library.sha256_text(text),
                "source_name": f"India Code (Legislative Department): Act No. 1 of 1860, file {name}", "source_url": "https://example.invalid/x", "version": "test", "status": library.PENDING_STATUS}

    entries = [draft(1, "IPC_1860_Official_Repealed.pdf"), draft(1, "Companies_Act_Official.pdf")]
    (tmp_path / "pending" / "mix.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    for k in ("INDIA_CODE_PERMISSION_REF", "OLD_CODES_USE_REF", "NCRB_PORTAL_USE_REF"):
        monkeypatch.delenv(k, raising=False)
    assert library.load_pending(tmp_path) == []
    monkeypatch.setenv("OLD_CODES_USE_REF", "Owner decision in chat, 2026-11-03: use the three repealed codes, unreviewed")
    assert [d["id"] for d in library.load_pending(tmp_path)] == ["IPC_1860_Official_Repealed.pdf-1"]  # the other India Code Act is still off
