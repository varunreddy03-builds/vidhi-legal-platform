"""Uploaded files are encrypted at rest (AES-256-GCM) and still download and export as before."""

import base64
import io
import os
import zipfile

import gridfs
import pytest

from lib import crypto
from tests.conftest import mongo, new_matter, upload

SECRET = "The agreement was signed at Hyderabad on 4 June 2026. UNIQUE-PLAINTEXT-MARKER-77"


def raw_bytes(gridfs_id) -> bytes:
    return gridfs.GridFS(mongo()).get(gridfs_id).read()


# ---- the cipher itself ----
def test_round_trip_and_tamper_detection():
    blob = crypto.encrypt(b"hello", b"vidhi-file")
    if not crypto.enabled():
        pytest.skip("no DATA_ENCRYPTION_KEY configured")
    assert blob.startswith(crypto.MAGIC) and b"hello" not in blob
    assert crypto.decrypt(blob, b"vidhi-file") == b"hello"
    with pytest.raises(ValueError):
        crypto.decrypt(blob, b"another-purpose")  # a blob only opens for the purpose it was made for
    flipped = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(ValueError):
        crypto.decrypt(flipped, b"vidhi-file")


def test_plain_legacy_files_still_read():
    assert crypto.decrypt(b"%PDF-1.4 old plain file", b"vidhi-file") == b"%PDF-1.4 old plain file"


def test_two_encryptions_of_the_same_file_differ():
    if not crypto.enabled():
        pytest.skip("no DATA_ENCRYPTION_KEY configured")
    assert crypto.encrypt(b"same", b"x") != crypto.encrypt(b"same", b"x")


def test_a_rotated_key_still_opens_old_files(monkeypatch):
    old = base64.urlsafe_b64encode(os.urandom(32)).decode()
    new = base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", old)
    blob = crypto.encrypt(b"kept", b"a")
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", f"{new},{old}")
    assert crypto.decrypt(blob, b"a") == b"kept"  # old key still listed
    assert crypto.decrypt(crypto.encrypt(b"fresh", b"a"), b"a") == b"fresh"
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", new)
    with pytest.raises(ValueError):
        crypto.decrypt(blob, b"a")  # old key removed: the old file can no longer be opened


def test_small_secrets_are_sealed_even_without_a_key(monkeypatch):
    monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    sealed = crypto.seal_text("JBSWY3DPEHPK3PXP", b"totp")
    assert "JBSWY3DPEHPK3PXP" not in sealed and crypto.open_text(sealed, b"totp") == "JBSWY3DPEHPK3PXP"


def test_a_bad_key_is_refused_loudly(monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "not-a-key")
    with pytest.raises(Exception):
        crypto.configured_keys()


# ---- through the app ----
def test_an_uploaded_document_is_stored_encrypted_and_downloads_unchanged(user_a):
    if not crypto.enabled():
        pytest.skip("no DATA_ENCRYPTION_KEY configured")
    mid, _ = new_matter(user_a)
    doc = upload(user_a, mid, "agreement.txt", SECRET)
    stored = mongo().documents.find_one({"id": doc["id"]})
    at_rest = raw_bytes(stored["gridfs_id"])
    assert at_rest.startswith(crypto.MAGIC) and b"UNIQUE-PLAINTEXT-MARKER-77" not in at_rest
    got = user_a.get(f"/documents/{doc['id']}/file")
    assert got.status_code == 200 and got.content.decode() == SECRET


def test_the_organisation_export_contains_readable_files(user_a):
    if not crypto.enabled():
        pytest.skip("no DATA_ENCRYPTION_KEY configured")
    mid, _ = new_matter(user_a)
    doc = upload(user_a, mid, "export-me.txt", SECRET)
    r = user_a.get("/org/export")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    name = next(n for n in z.namelist() if n.startswith(f"files/{doc['id']}"))
    assert z.read(name).decode() == SECRET


def test_a_file_saved_before_encryption_was_on_still_downloads(user_a):
    mid, _ = new_matter(user_a)
    doc = upload(user_a, mid, "old.txt", "old plain text")
    stored = mongo().documents.find_one({"id": doc["id"]})
    plain_id = gridfs.GridFS(mongo()).put(b"old plain text", filename="old.txt")  # as the app stored files earlier
    mongo().documents.update_one({"id": doc["id"]}, {"$set": {"gridfs_id": plain_id}})
    got = user_a.get(f"/documents/{doc['id']}/file")
    assert got.status_code == 200 and got.content == b"old plain text"
    assert stored["gridfs_id"] != plain_id
