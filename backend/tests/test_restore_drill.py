"""The restore drill (tools/restore_drill.py): it must restore the newest backup into a throwaway database, check it, and always clean up, without touching the live database.
Real MongoDB and GnuPG, like test_db_backup.py. Invented data only."""

import base64
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import gridfs
import pytest
from pymongo import MongoClient

from lib import crypto, dbbackup
from tools.restore_drill import DrillFailed, FILE_AAD, run_drill

BACKEND = Path(__file__).resolve().parent.parent
KEY_A = base64.urlsafe_b64encode(b"A" * 32).decode()
KEY_B = base64.urlsafe_b64encode(b"B" * 32).decode()


@pytest.fixture
def client():
    c = MongoClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))
    yield c
    c.close()


@pytest.fixture
def passfile(tmp_path):
    p = tmp_path / "pass.txt"
    p.write_text("drill passphrase (test only)", encoding="utf-8")
    return p


@pytest.fixture
def live_db(client, monkeypatch):
    """A small 'live' database whose uploads are encrypted with KEY_A, and a recorder of every database the drill restores into."""
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", KEY_A)
    name = f"vidhi_drill_src_{uuid.uuid4().hex[:8]}"
    d = client[name]
    bucket = gridfs.GridFSBucket(d)
    for i in range(3):
        fid = bucket.upload_from_stream(f"f{i}.txt", crypto.encrypt(f"invented file {i}".encode(), FILE_AAD))
        d.documents.insert_one({"id": f"d{i}", "gridfs_id": fid, "filename": f"f{i}.txt"})
    d.matters.insert_many([{"id": f"m{i}", "title": f"Invented matter {i}"} for i in range(40)])
    d.matters.create_index("id", unique=True)
    yield name
    client.drop_database(name)


@pytest.fixture
def made_backup(client, live_db, passfile, tmp_path):
    out = tmp_path / "backups"
    dbbackup.backup(client, live_db, out, passfile)
    return out


@pytest.fixture
def targets(monkeypatch):
    """Every throwaway database the drill restored into (so a test can check it was dropped without racing other tests)."""
    seen: list[str] = []
    real = dbbackup.restore

    def record(client, archive, passphrase, target_db, replace=False, verify_only=False):
        if not verify_only:
            seen.append(target_db)
        return real(client, archive, passphrase, target_db, replace=replace, verify_only=verify_only)

    monkeypatch.setattr(dbbackup, "restore", record)
    return seen


def test_a_good_backup_passes_and_the_throwaway_database_is_dropped(client, live_db, made_backup, passfile, targets):
    r = run_drill(client, made_backup, passfile, live_db=live_db)  # a folder: the newest file is used
    assert r["documents"] >= 43 and r["collections"]["matters"] == 40
    assert r["files_checked"] == 3 and r["files_unreadable"] == 0
    assert targets == [r["target"]] and r["target"].startswith("restore_drill_") and r["target"] != live_db
    assert r["target"] not in client.list_database_names()  # cleaned up
    assert client[live_db].matters.count_documents({}) == 40  # the live database was not touched


def test_keep_leaves_the_copy_for_a_look(client, live_db, made_backup, passfile, targets):
    r = run_drill(client, made_backup, passfile, live_db=live_db, keep=True)
    try:
        assert r["target"] in client.list_database_names() and client[r["target"]].matters.count_documents({}) == 40
    finally:
        client.drop_database(r["target"])


def test_a_lost_or_wrong_file_key_fails_the_drill_and_still_cleans_up(client, live_db, made_backup, passfile, targets, monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", KEY_B)  # the key on this machine is not the one the files were saved with
    with pytest.raises(DrillFailed, match="could not be opened"):
        run_drill(client, made_backup, passfile, live_db=live_db)
    assert len(targets) == 1 and targets[0] not in client.list_database_names()


def test_a_wrong_passphrase_fails_before_anything_is_created(client, live_db, made_backup, tmp_path, targets):
    wrong = tmp_path / "wrong.txt"
    wrong.write_text("not the passphrase", encoding="utf-8")
    with pytest.raises(DrillFailed, match="did not pass its own checks"):
        run_drill(client, made_backup, wrong, live_db=live_db)
    assert targets == []


def test_an_old_backup_fails_the_drill(client, live_db, made_backup, passfile, targets):
    f = next(made_backup.glob("*.gpg"))
    old = time.time() - 5 * 86400
    os.utime(f, (old, old))
    with pytest.raises(DrillFailed, match="hours old"):
        run_drill(client, made_backup, passfile, live_db=live_db)
    assert targets == []


def test_a_folder_with_no_backup_fails(client, live_db, passfile, tmp_path, targets):
    (tmp_path / "empty").mkdir()
    with pytest.raises(DrillFailed, match="No backup file"):
        run_drill(client, tmp_path / "empty", passfile, live_db=live_db)


def test_a_changed_byte_in_the_backup_fails_and_nothing_is_restored(client, live_db, made_backup, passfile, targets):
    f = next(made_backup.glob("*.gpg"))
    data = bytearray(f.read_bytes())
    data[len(data) // 2] ^= 0xFF
    f.write_bytes(bytes(data))
    with pytest.raises(DrillFailed):
        run_drill(client, made_backup, passfile, live_db=live_db)
    assert targets == []


def test_the_command_line_prints_counts_but_never_the_database_address_or_document_text(client, live_db, made_backup, passfile):
    url = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
    env = {**os.environ, "MONGO_URL": url, "DB_NAME": live_db, "DATA_ENCRYPTION_KEY": KEY_A}
    ok = subprocess.run([sys.executable, "-I", str(BACKEND / "tools" / "restore_drill.py"), "--backup", str(made_backup), "--passphrase-file", str(passfile)], capture_output=True, text=True, env=env)
    assert ok.returncode == 0, ok.stderr
    assert "PASS" in ok.stdout and "3 stored uploads opened" in ok.stdout and "dropped" in ok.stdout
    assert url not in ok.stdout + ok.stderr and "Invented matter" not in ok.stdout + ok.stderr
    bad = subprocess.run([sys.executable, "-I", str(BACKEND / "tools" / "restore_drill.py"), "--backup", str(made_backup), "--passphrase-file", str(passfile)], capture_output=True, text=True, env={**env, "DATA_ENCRYPTION_KEY": KEY_B})
    assert bad.returncode == 1 and "FAIL" in bad.stderr and url not in bad.stdout + bad.stderr
