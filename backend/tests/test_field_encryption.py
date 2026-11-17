"""The text taken out of uploaded documents is encrypted in the database and opened again on the way out. Real MongoDB; invented text only."""

import base64
import io
import json
import os
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path

import pytest

from lib import fieldcrypt
from tests.conftest import answer, mongo, new_matter, stub, upload

BACKEND = Path(__file__).resolve().parent.parent
KEY_A = base64.urlsafe_b64encode(b"A" * 32).decode()
KEY_B = base64.urlsafe_b64encode(b"B" * 32).decode()
MARKER = "Ramesh Gupta of 14 Lake View Road paid Rs 4,50,000 on 3 May"


def test_a_page_round_trips_and_plain_or_empty_pages_pass_through(monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", KEY_A)
    sealed = fieldcrypt.seal_page(MARKER)
    assert sealed.startswith("vp1:") and MARKER not in sealed and "Ramesh" not in sealed
    assert fieldcrypt.open_page(sealed) == MARKER
    assert fieldcrypt.seal_page(sealed) == sealed  # never sealed twice
    assert fieldcrypt.open_page("an older plain page") == "an older plain page"  # written before encryption existed
    assert fieldcrypt.seal_page("") == "" and fieldcrypt.open_page("") == ""
    assert fieldcrypt.open_pages(fieldcrypt.seal_pages([MARKER, "", "second"])) == [MARKER, "", "second"]
    assert fieldcrypt.seal_pages(None) is None


def test_without_a_key_nothing_is_encrypted(monkeypatch):
    monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    assert fieldcrypt.seal_page(MARKER) == MARKER


def test_a_page_sealed_with_a_key_that_is_gone_raises_instead_of_returning_garbage(monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", KEY_A)
    sealed = fieldcrypt.seal_page(MARKER)
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", KEY_B)
    with pytest.raises(ValueError):
        fieldcrypt.open_page(sealed)
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", f"{KEY_B},{KEY_A}")  # keeping the old key as well opens it
    assert fieldcrypt.open_page(sealed) == MARKER


def test_an_uploaded_documents_text_is_encrypted_in_the_database_and_still_works_everywhere(user_a):
    mid, title = new_matter(user_a, "Sealed")
    upload(user_a, mid, "paid.txt", f"{MARKER}. {title}")
    row = mongo().documents.find_one({"matter_id": mid})
    stored = json.dumps(row["pages"])
    assert row["pages"] and all(p.startswith("vp1:") for p in row["pages"] if p) and MARKER not in stored and "Ramesh" not in stored  # nothing readable in the database
    # reading goes through the opened view: the export shows the real text
    org_id = user_a.get("/auth/me").json()["organization_id"]
    assert org_id == row["organization_id"]
    z = zipfile.ZipFile(io.BytesIO(user_a.get("/org/export").content))
    assert MARKER in z.read("documents.json").decode("utf-8")
    # and the claim check still finds a quote in it (verification reads the same text)
    claim = {"text": "Ramesh Gupta paid Rs 4,50,000.", "claim_kind": "FACTUAL", "supports": "YES", "citations": [{"source": "MATTER_DOCUMENT", "ref": "DOC-01", "page": 1, "quote": MARKER}]}
    stub("research", answer("Paid.", [claim]), contains=title)
    res = user_a.post("/research", json={"question": f"Who paid? {title}", "matter_id": mid, "mode": "MATTER"}).json()
    assert res["claims"][0]["citations"][0]["quote_verified"] is True


def test_the_startup_migration_encrypts_older_plain_documents_and_can_run_twice():
    from pymongo import MongoClient

    scratch = f"vidhi_fe_mig_{uuid.uuid4().hex[:8]}"  # its own database: the migration seals EVERY plain document it finds, which must never touch the shared test database
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[scratch]
    db.documents.insert_one({"id": "legacy-1", "matter_id": "m", "organization_id": "legacy-org", "filename": "old.txt", "pages": [MARKER, "", "page two of the old document"]})
    code = "import asyncio, sys; sys.path.insert(0, sys.argv[1]); from lib import migrations; asyncio.run(migrations._encrypt_document_pages())"
    env = {**os.environ, "DB_NAME": scratch, "DATA_ENCRYPTION_KEY": KEY_A}
    try:
        for _ in range(2):  # twice: the second run changes nothing
            r = subprocess.run([sys.executable, "-I", "-c", code, str(BACKEND)], capture_output=True, text=True, env=env, cwd=str(BACKEND))
            assert r.returncode == 0, r.stderr
            row = db.documents.find_one({"id": "legacy-1"})
            assert row["pages"][0].startswith("vp1:") and row["pages"][1] == "" and row["pages"][2].startswith("vp1:") and MARKER not in json.dumps(row["pages"])
        # without the key the migration fails (so it is retried later) instead of pretending to be done
        nokey = {k: v for k, v in env.items() if k != "DATA_ENCRYPTION_KEY"}
        db.documents.insert_one({"id": "legacy-2", "matter_id": "m", "organization_id": "legacy-org", "pages": ["plain again"]})
        r = subprocess.run([sys.executable, "-I", "-c", code, str(BACKEND)], capture_output=True, text=True, env=nokey, cwd=str(BACKEND))
        assert r.returncode != 0 and "DATA_ENCRYPTION_KEY" in r.stderr
        assert db.documents.find_one({"id": "legacy-2"})["pages"] == ["plain again"]
    finally:
        client.drop_database(scratch)
        client.close()
