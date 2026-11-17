"""Encrypted backup and restore, against a real MongoDB and a real GnuPG: byte-exact round trip (Telugu, binary, dates, GridFS chunks, text index), wrong passphrase, tampering,
refusal to overwrite, and old backups removed."""

import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from bson import Binary, ObjectId
from pymongo import MongoClient

from lib import dbbackup

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture
def client():
    c = MongoClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))
    yield c
    c.close()


@pytest.fixture
def source_db(client):
    name = f"vidhi_bk_src_{uuid.uuid4().hex[:8]}"
    d = client[name]
    d.matters.insert_many([{"id": f"m{i}", "title": f"తెలుగు వివరణ {i} — ₹5,00,000", "when": datetime(2026, 10, 26, 9, 30, tzinfo=timezone.utc), "n": i} for i in range(1200)])  # more than one batch
    d.matters.create_index("id", unique=True)
    d.matters.create_index([("title", "text")], name="title_text")
    d.matters.create_index([("n", 1)], name="n_partial", partialFilterExpression={"n": {"$gt": 10}})
    d.fs.files.insert_one({"_id": ObjectId(), "filename": "scan.pdf", "length": 3})
    d.fs.chunks.insert_one({"files_id": ObjectId(), "n": 0, "data": Binary(b"\x00\x01\xffencrypted-bytes")})
    d.empty_one.insert_one({"x": 1})
    d.empty_one.delete_many({})
    yield name
    client.drop_database(name)


@pytest.fixture
def passfile(tmp_path):
    p = tmp_path / "pass.txt"
    p.write_text("correct horse battery staple (test only)", encoding="utf-8")
    return p


def all_docs(client, db_name):
    d = client[db_name]
    return {n: sorted(d[n].find({}), key=lambda x: str(x.get("_id"))) for n in d.list_collection_names() if not n.startswith("system.")}


def test_round_trip_is_exact_including_indexes_and_the_file_is_encrypted(client, source_db, passfile, tmp_path):
    r = dbbackup.backup(client, source_db, tmp_path / "out", passfile)
    assert r["documents"] == 1202 and r["collections"] >= 3 and Path(r["path"]).name.startswith("vidhi-") and Path(r["path"]).name.endswith(".archive.tar.gz.gpg")
    raw = Path(r["path"]).read_bytes()
    assert b"\x1f\x8b" != raw[:2] and "తెలుగు".encode() not in raw and b"encrypted-bytes" not in raw  # not a plain gzip, no readable text
    target = f"vidhi_bk_dst_{uuid.uuid4().hex[:8]}"
    try:
        rep = dbbackup.restore(client, r["path"], passfile, target)
        assert rep["restored"] is True and rep["collections"]["matters"] == 1200
        assert all_docs(client, source_db) == all_docs(client, target)  # every document equal, ids and dates included
        names = {i["name"] for i in client[target].matters.list_indexes()}
        assert {"_id_", "id_1", "title_text", "n_partial"} <= names
        assert client[target].matters.find_one({"id": "m5"})["title"].startswith("తెలుగు")
        assert client[target].matters.count_documents({"$text": {"$search": "వివరణ"}}) > 0  # the rebuilt text index works
        assert next(i for i in client[target].matters.list_indexes() if i["name"] == "n_partial")["partialFilterExpression"] == {"n": {"$gt": 10}}
    finally:
        client.drop_database(target)


def test_a_wrong_passphrase_stops_before_anything_is_written(client, source_db, passfile, tmp_path):
    r = dbbackup.backup(client, source_db, tmp_path / "out", passfile)
    wrong = tmp_path / "wrong.txt"
    wrong.write_text("not the passphrase", encoding="utf-8")
    target = f"vidhi_bk_dst_{uuid.uuid4().hex[:8]}"
    with pytest.raises(dbbackup.BackupError):
        dbbackup.restore(client, r["path"], wrong, target)
    assert target not in client.list_database_names()


def test_a_changed_byte_is_detected_before_anything_is_written(client, source_db, passfile, tmp_path):
    r = dbbackup.backup(client, source_db, tmp_path / "out", passfile)
    data = bytearray(Path(r["path"]).read_bytes())
    data[len(data) // 2] ^= 0xFF
    Path(r["path"]).write_bytes(bytes(data))
    target = f"vidhi_bk_dst_{uuid.uuid4().hex[:8]}"
    with pytest.raises(dbbackup.BackupError):
        dbbackup.restore(client, r["path"], passfile, target)
    assert target not in client.list_database_names()


def test_a_tampered_archive_inside_the_encryption_fails_the_hash_check(client, source_db, passfile, tmp_path):
    """Someone with the passphrase edits the contents and re-encrypts: the manifest hashes no longer match."""
    import io
    import tarfile

    plain = tmp_path / "plain.tar.gz"
    dbbackup.make_archive(client, source_db, plain)
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(plain, "r:gz") as src, tarfile.open(tampered, "w:gz") as dst:
        for m in src.getmembers():
            data = src.extractfile(m).read()
            if m.name == "data/matters.bson":
                data = data[:-1] + bytes([data[-1] ^ 1])
            info = tarfile.TarInfo(m.name)
            info.size = len(data)
            dst.addfile(info, io.BytesIO(data))
    enc = tmp_path / "t.gpg"
    dbbackup.encrypt_file(tampered, enc, passfile)
    with pytest.raises(dbbackup.BackupError, match="hash"):
        dbbackup.restore(client, enc, passfile, f"vidhi_bk_dst_{uuid.uuid4().hex[:8]}")


def test_restore_refuses_a_database_that_has_data_unless_replace_is_given(client, source_db, passfile, tmp_path):
    r = dbbackup.backup(client, source_db, tmp_path / "out", passfile)
    with pytest.raises(dbbackup.BackupError, match="already holds data"):
        dbbackup.restore(client, r["path"], passfile, source_db)
    client[source_db].matters.delete_many({"n": {"$lt": 600}})
    rep = dbbackup.restore(client, r["path"], passfile, source_db, replace=True)  # the explicit, destructive path
    assert rep["restored"] and client[source_db].matters.count_documents({}) == 1200


def test_verify_only_checks_everything_and_touches_nothing(client, source_db, passfile, tmp_path):
    r = dbbackup.backup(client, source_db, tmp_path / "out", passfile)
    target = f"vidhi_bk_dst_{uuid.uuid4().hex[:8]}"
    rep = dbbackup.restore(client, r["path"], passfile, target, verify_only=True)
    assert rep["restored"] is False and rep["collections"]["matters"] == 1200 and target not in client.list_database_names()


def test_old_backups_are_removed_after_keep_days_and_new_ones_are_kept(client, source_db, passfile, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    old = out / "vidhi-20200101-000000Z.archive.tar.gz.gpg"
    old.write_bytes(b"x" * 2000)
    long_ago = time.time() - 40 * 86400
    os.utime(old, (long_ago, long_ago))
    recent = out / "vidhi-20261020-000000Z.archive.tar.gz.gpg"
    recent.write_bytes(b"y" * 2000)
    r = dbbackup.backup(client, source_db, out, passfile, keep_days=30)
    assert not old.exists() and recent.exists() and Path(r["path"]).exists()


def test_a_missing_or_empty_passphrase_file_is_refused(client, source_db, tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("")
    with pytest.raises(dbbackup.BackupError):
        dbbackup.backup(client, source_db, tmp_path / "out", empty)
    with pytest.raises(dbbackup.BackupError):
        dbbackup.backup(client, source_db, tmp_path / "out", tmp_path / "missing.txt")
    assert not list((tmp_path / "out").glob("vidhi-*")) if (tmp_path / "out").exists() else True


def test_the_command_line_tools_work_end_to_end_and_never_print_the_database_address(source_db, passfile, tmp_path):
    url = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
    env = {**os.environ, "MONGO_URL": url, "DB_NAME": source_db}
    b = subprocess.run([sys.executable, "-I", str(BACKEND / "tools" / "db_backup.py"), "--out-dir", str(tmp_path / "o"), "--passphrase-file", str(passfile)], capture_output=True, text=True, env=env)
    assert b.returncode == 0, b.stderr
    assert "1202 documents" in b.stdout and url not in b.stdout + b.stderr
    f = next((tmp_path / "o").glob("vidhi-*.gpg"))
    target = f"vidhi_bk_cli_{uuid.uuid4().hex[:8]}"
    v = subprocess.run([sys.executable, "-I", str(BACKEND / "tools" / "db_restore.py"), str(f), "--passphrase-file", str(passfile), "--verify-only"], capture_output=True, text=True, env=env)
    assert v.returncode == 0 and "nothing was changed" in v.stdout
    r = subprocess.run([sys.executable, "-I", str(BACKEND / "tools" / "db_restore.py"), str(f), "--passphrase-file", str(passfile), "--target-db", target], capture_output=True, text=True, env=env)
    try:
        assert r.returncode == 0, r.stderr
        assert "matters: 1200" in r.stdout and MongoClient(url)[target].matters.count_documents({}) == 1200
        again = subprocess.run([sys.executable, "-I", str(BACKEND / "tools" / "db_restore.py"), str(f), "--passphrase-file", str(passfile), "--target-db", target], capture_output=True, text=True, env=env)
        assert again.returncode == 1 and "already holds data" in again.stderr
    finally:
        MongoClient(url).drop_database(target)


def test_backup_works_for_a_user_with_no_home_folder(source_db, passfile, tmp_path):
    """The containers run as a user with no home folder; GnuPG must not need one (found by the CI stack job)."""
    url = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
    missing = str(tmp_path / "no-such-home")
    env = {**os.environ, "MONGO_URL": url, "DB_NAME": source_db, "HOME": missing, "APPDATA": missing, "USERPROFILE": missing}
    env.pop("GNUPGHOME", None)
    b = subprocess.run([sys.executable, "-I", str(BACKEND / "tools" / "db_backup.py"), "--out-dir", str(tmp_path / "o"), "--passphrase-file", str(passfile)], capture_output=True, text=True, env=env)
    assert b.returncode == 0, b.stderr
    assert not Path(missing).exists()  # nothing was created in place of the missing home folder
