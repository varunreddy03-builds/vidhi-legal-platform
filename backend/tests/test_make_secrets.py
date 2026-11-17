"""scripts/make-secrets.py: random secrets for a new server, written to a folder, never printed, never overwritten by accident, never inside the repository or a synced folder."""

import base64
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO / "scripts" / "make-secrets.py"

pytestmark = pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="ssh-keygen is not installed on this machine")


def run(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True)


def read(folder):
    return dict(line.split("=", 1) for line in (folder / "secrets.env").read_text(encoding="utf-8").splitlines())


def test_it_writes_valid_secrets_a_deploy_key_and_prints_none_of_the_values(tmp_path):
    out = tmp_path / "staging"
    r = run("--out", str(out))
    assert r.returncode == 0, r.stderr
    values = read(out)
    assert set(values) == {"MONGO_ROOT_PASSWORD", "MONGO_APP_PASSWORD", "LINK_SECRET", "WEBHOOK_CRON_SECRET", "CRON_SECRET", "DATA_ENCRYPTION_KEY"}
    for name in ("MONGO_ROOT_PASSWORD", "MONGO_APP_PASSWORD"):
        assert values[name].isalnum() and len(values[name]) == 32  # inside a URL: letters and digits only
    assert values["CRON_SECRET"] == values["WEBHOOK_CRON_SECRET"]  # the Scheduled jobs workflow and the app must agree
    assert len(values["LINK_SECRET"]) >= 48 and len({*values.values()}) == 5  # all different except the cron pair
    key = base64.urlsafe_b64decode(values["DATA_ENCRYPTION_KEY"] + "=" * (-len(values["DATA_ENCRYPTION_KEY"]) % 4))
    assert len(key) == 32  # what lib/crypto.py requires
    assert (out / "deploy_key").read_text().startswith("-----BEGIN " + "OPENSSH PRIVATE KEY-----")  # written in two parts so the commit scanner does not mistake the test for a key
    assert (out / "deploy_key.pub").read_text().startswith("ssh-ed25519 ")
    shown = r.stdout + r.stderr
    assert not any(v in shown for v in values.values())  # names only, never values


def test_two_runs_make_different_secrets_and_the_second_will_not_overwrite_without_force(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert run("--out", str(a)).returncode == 0 and run("--out", str(b)).returncode == 0
    assert read(a)["LINK_SECRET"] != read(b)["LINK_SECRET"]
    before = (a / "secrets.env").read_text()
    again = run("--out", str(a))
    assert again.returncode == 1 and "already exist" in again.stderr and (a / "secrets.env").read_text() == before
    assert run("--out", str(a), "--force").returncode == 0 and (a / "secrets.env").read_text() != before


def test_it_refuses_a_synced_folder_and_a_folder_inside_the_repository(tmp_path):
    synced = tmp_path / "OneDrive" / "Documents" / "secrets"
    r = run("--out", str(synced))
    assert r.returncode == 2 and "synced" in r.stderr and not synced.exists()
    inside = REPO / "deploy" / "secrets-should-not-exist"
    r = run("--out", str(inside))
    assert r.returncode == 2 and "inside the repository" in r.stderr and not inside.exists()
