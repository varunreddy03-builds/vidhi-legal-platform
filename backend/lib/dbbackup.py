"""Encrypted database backup and restore that needs only Python, pymongo and GnuPG (no mongodump), so the same code runs on a laptop, in CI and in the backup container.

An archive is a tar.gz holding, for every collection, its documents as raw BSON (byte for byte, GridFS file chunks included; uploads are already encrypted by the app when
DATA_ENCRYPTION_KEY is set), its index definitions, and a manifest with the document count and SHA-256 of every file. The archive is then encrypted with GnuPG (AES-256, passphrase read
from a FILE, never from the command line or the environment).

A backup is only kept after it has been decrypted again and every hash in the manifest checked. A restore checks the same hashes BEFORE it touches the database, refuses to write into a
database that already has data unless told to replace it, and compares the restored counts with the manifest afterwards."""

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bson
from bson import json_util
from bson.codec_options import CodecOptions
from bson.raw_bson import RawBSONDocument

FORMAT = "vidhi-backup/1"
BATCH = 500
RAW = CodecOptions(document_class=RawBSONDocument)
GIT_GPG = "C:/Program Files/Git/usr/bin/gpg.exe"


class BackupError(Exception):
    pass


def gpg_bin() -> str:
    found = os.environ.get("GPG_BIN") or shutil.which("gpg") or (GIT_GPG if os.path.exists(GIT_GPG) else None)
    if not found:
        raise BackupError("GnuPG (gpg) was not found. Install it, or set GPG_BIN to its path.")
    return found


def _sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_passphrase_file(path: str | Path) -> None:
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        raise BackupError("The passphrase file is missing or empty.")


# ------------------------------------------------------------------ the archive

def make_archive(client, db_name: str, dest: str | Path) -> dict:
    """Write every collection of `db_name` to a tar.gz at `dest`; returns the manifest."""
    database = client[db_name]
    names = sorted(n for n in database.list_collection_names() if not n.startswith("system."))
    manifest = {"format": FORMAT, "db_name": db_name, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "collections": {}}
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(dest, "w:gz") as tar:
        for name in names:
            part = os.path.join(tmp, f"{name}.bson")
            count = 0
            with open(part, "wb") as out:
                for doc in database.get_collection(name, codec_options=RAW).find({}):
                    out.write(doc.raw)
                    count += 1
            idx = [{"name": i["name"], "key": list(i["key"].items()), "options": {k: v for k, v in i.items() if k not in ("v", "key", "ns", "name")}}
                   for i in database[name].list_indexes() if i["name"] != "_id_"]
            idx_path = os.path.join(tmp, f"{name}.indexes.json")
            Path(idx_path).write_text(json_util.dumps(idx), encoding="utf-8")
            manifest["collections"][name] = {"documents": count, "bson_sha256": _sha256_file(part), "indexes_sha256": _sha256_file(idx_path)}
            tar.add(part, arcname=f"data/{name}.bson")
            tar.add(idx_path, arcname=f"data/{name}.indexes.json")
            os.remove(part)
        blob = json.dumps(manifest, indent=1).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(blob)
        info.mtime = int(datetime.now(timezone.utc).timestamp())
        tar.addfile(info, io.BytesIO(blob))
    return manifest


def read_manifest(archive: str | Path) -> dict:
    with tarfile.open(archive, "r:gz") as tar:
        try:
            m = json.load(tar.extractfile("manifest.json"))
        except KeyError as exc:
            raise BackupError("This is not a VIDHI backup (no manifest).") from exc
    if m.get("format") != FORMAT:
        raise BackupError(f"Unknown backup format {m.get('format')!r}.")
    return m


def verify_archive(archive: str | Path) -> dict:
    """Recompute every hash in the manifest. Raises BackupError on the first file that does not match or is missing; returns the manifest when all is well."""
    manifest = read_manifest(archive)
    with tarfile.open(archive, "r:gz") as tar:
        names = set(tar.getnames())
        for coll, info in manifest["collections"].items():
            for member, key in ((f"data/{coll}.bson", "bson_sha256"), (f"data/{coll}.indexes.json", "indexes_sha256")):
                if member not in names:
                    raise BackupError(f"The backup is missing {member}.")
                h = hashlib.sha256()
                f = tar.extractfile(member)
                for chunk in iter(lambda f=f: f.read(1024 * 1024), b""):
                    h.update(chunk)
                if h.hexdigest() != info[key]:
                    raise BackupError(f"{member} does not match its recorded hash: the backup is damaged or was changed.")
    return manifest


# ------------------------------------------------------------------ encryption

def _homedir_arg(path: str) -> str:
    """Git for Windows ships an MSYS build of GnuPG that reads 'C:\\...' in --homedir as a relative path; it needs '/c/...'. Everywhere else the path is passed as it is."""
    exe = gpg_bin().replace("\\", "/").lower()
    if os.name == "nt" and "/git/usr/bin/" in exe and len(path) > 2 and path[1] == ":":
        return "/" + path[0].lower() + path[2:].replace("\\", "/")
    return path


def _gpg(args: list[str], passphrase_file: str | Path) -> None:
    _check_passphrase_file(passphrase_file)
    # GnuPG wants a home folder for its settings. The containers' user deliberately has none, so each call gets a fresh private one that is removed afterwards
    # (symmetric encryption needs no stored keys). Found by the CI stack job: "can't create directory '/home/appuser/.gnupg'".
    with tempfile.TemporaryDirectory(prefix="vidhi-gpg-") as home:
        try:
            os.chmod(home, 0o700)
        except OSError:
            pass
        cmd = [gpg_bin(), "--homedir", _homedir_arg(home), "--batch", "--yes", "--quiet", "--pinentry-mode", "loopback", "--passphrase-file", str(passphrase_file), *args]
        res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise BackupError("GnuPG failed (wrong passphrase, damaged file, or gpg not working): " + (res.stderr.strip().splitlines() or ["no message"])[-1][:200])


def encrypt_file(src: str | Path, dest: str | Path, passphrase_file: str | Path) -> None:
    _gpg(["--symmetric", "--cipher-algo", "AES256", "--output", str(dest), str(src)], passphrase_file)


def decrypt_file(src: str | Path, dest: str | Path, passphrase_file: str | Path) -> None:
    _gpg(["--decrypt", "--output", str(dest), str(src)], passphrase_file)


# ------------------------------------------------------------------ backup

def backup(client, db_name: str, out_dir: str | Path, passphrase_file: str | Path, keep_days: int = 30) -> dict:
    """Make an encrypted backup in out_dir, prove it can be read back, and delete backups older than keep_days. Returns {path, bytes, documents, collections}."""
    _check_passphrase_file(passphrase_file)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(out, 0o700)
    except OSError:
        pass
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    final = out / f"vidhi-{stamp}.archive.tar.gz.gpg"
    partial = out / (final.name + ".partial")
    with tempfile.TemporaryDirectory() as tmp:
        plain = os.path.join(tmp, "backup.tar.gz")
        manifest = make_archive(client, db_name, plain)
        encrypt_file(plain, partial, passphrase_file)
        # a backup that cannot be read back is worse than none: decrypt it again and check every hash before keeping it
        check = os.path.join(tmp, "check.tar.gz")
        try:
            decrypt_file(partial, check, passphrase_file)
            verify_archive(check)
        except BackupError:
            partial.unlink(missing_ok=True)
            raise
    size = partial.stat().st_size
    partial.replace(final)
    try:
        os.chmod(final, 0o600)
    except OSError:
        pass
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    for old in out.glob("vidhi-*.archive.tar.gz.gpg"):
        if old != final and datetime.fromtimestamp(old.stat().st_mtime, timezone.utc) < cutoff:
            old.unlink()
    return {"path": str(final), "bytes": size, "documents": sum(c["documents"] for c in manifest["collections"].values()), "collections": len(manifest["collections"])}


# ------------------------------------------------------------------ restore

def restore(client, archive_gpg: str | Path, passphrase_file: str | Path, target_db: str, replace: bool = False, verify_only: bool = False) -> dict:
    """Decrypt, verify, then (unless verify_only) write into target_db. An existing, non-empty target is refused unless replace=True, which drops the collections first."""
    with tempfile.TemporaryDirectory() as tmp:
        plain = os.path.join(tmp, "restore.tar.gz")
        decrypt_file(archive_gpg, plain, passphrase_file)
        manifest = verify_archive(plain)  # nothing in the database changes before this passes
        report = {"collections": {n: c["documents"] for n, c in manifest["collections"].items()}, "source_db": manifest["db_name"], "created_at": manifest["created_at"], "restored": False}
        if verify_only:
            return report
        database = client[target_db]
        existing = [n for n in database.list_collection_names() if not n.startswith("system.")]
        if existing and not replace:
            raise BackupError(f"The database '{target_db}' already holds data ({len(existing)} collections). Restore into an empty database, or pass replace to overwrite it.")
        for n in existing:
            database.drop_collection(n)
        with tarfile.open(plain, "r:gz") as tar:
            for name, info in manifest["collections"].items():
                if name not in database.list_collection_names():
                    database.create_collection(name)  # an empty collection is restored too
                coll = database.get_collection(name, codec_options=RAW)
                batch, count = [], 0
                for doc in bson.decode_file_iter(tar.extractfile(f"data/{name}.bson"), codec_options=RAW):
                    batch.append(doc)
                    if len(batch) >= BATCH:
                        coll.insert_many(batch, ordered=True)
                        count += len(batch)
                        batch = []
                if batch:
                    coll.insert_many(batch, ordered=True)
                    count += len(batch)
                for ix in json_util.loads(tar.extractfile(f"data/{name}.indexes.json").read().decode("utf-8")):
                    keys, opts = [tuple(k) for k in ix["key"]], dict(ix["options"])
                    if any(k == "_fts" for k, _ in keys):  # a text index is stored as _fts/_ftsx plus weights; it is rebuilt from the weights
                        keys = [(f, "text") for f in opts.get("weights", {})]
                    database[name].create_index(keys, name=ix["name"], **opts)
                if count != info["documents"] or database[name].count_documents({}) != info["documents"]:
                    raise BackupError(f"Collection {name}: restored {database[name].count_documents({})} documents but the backup holds {info['documents']}.")
        report["restored"] = True
        return report
