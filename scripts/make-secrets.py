"""Makes the random secrets a new VIDHI server needs, on THIS computer, and never prints any of them.

    python scripts/make-secrets.py --out C:/vidhi-tools/secrets/staging
    python scripts/make-secrets.py --out C:/vidhi-tools/secrets/production      (a different folder: never reuse one server's secrets for another)

It writes into the folder you name (use one outside OneDrive or any synced folder, and outside the repository):
  secrets.env        NAME=value lines for the secrets that are random: MONGO_ROOT_PASSWORD, MONGO_APP_PASSWORD, LINK_SECRET, WEBHOOK_CRON_SECRET, CRON_SECRET (same value as
                     WEBHOOK_CRON_SECRET), DATA_ENCRYPTION_KEY
  deploy_key         a new SSH private key made only for deploying (no passphrase, so the Deploy workflow can use it)
  deploy_key.pub     its public half: this goes to the server (deploy/server-setup.sh)
It refuses to overwrite an existing folder's files unless you pass --force (overwriting would lock you out of data encrypted with the old key). On Windows the folder is
restricted to your own account. The values only ever go to files in that folder; then scripts/upload-github-secrets.ps1 sends them to GitHub when YOU run it.

Back up secrets.env and deploy_key in your password manager: DATA_ENCRYPTION_KEY cannot be recovered, and without it stored files cannot be opened."""

import argparse
import base64
import os
import secrets
import shutil
import string
import subprocess
import sys
from pathlib import Path

ALNUM = string.ascii_letters + string.digits  # the database passwords go inside a URL, so letters and digits only


def alnum(n: int) -> str:
    return "".join(secrets.choice(ALNUM) for _ in range(n))


def make_values() -> dict[str, str]:
    cron = secrets.token_urlsafe(48)
    return {
        "MONGO_ROOT_PASSWORD": alnum(32),
        "MONGO_APP_PASSWORD": alnum(32),
        "LINK_SECRET": secrets.token_urlsafe(48),
        "WEBHOOK_CRON_SECRET": cron,
        "CRON_SECRET": cron,  # the repository secret the Scheduled jobs workflow reads; it must equal WEBHOOK_CRON_SECRET
        "DATA_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
    }


def lock_folder(path: Path) -> None:
    if os.name == "nt":
        user = os.environ.get("USERNAME", "")
        if user:
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F"], capture_output=True, check=False)
    else:
        path.chmod(0o700)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    here = Path(__file__).resolve().parent.parent
    if here in out.resolve().parents or out.resolve() == here:
        print("Refusing: that folder is inside the repository. Secrets must live outside it.", file=sys.stderr)
        return 2
    lowered = str(out.resolve()).lower()
    if "onedrive" in lowered or "dropbox" in lowered or "google drive" in lowered:
        print("Refusing: that folder is synced to a cloud service. Choose a folder that stays on this computer, for example C:/vidhi-tools/secrets/staging.", file=sys.stderr)
        return 2
    files = [out / "secrets.env", out / "deploy_key", out / "deploy_key.pub"]
    if any(f.exists() for f in files) and not a.force:
        print("Refusing: secrets already exist in that folder. Overwriting would make anything encrypted with the old DATA_ENCRYPTION_KEY unreadable. Use --force only for a brand new server.", file=sys.stderr)
        return 1
    if not shutil.which("ssh-keygen"):
        print("ssh-keygen was not found (it comes with Git for Windows and with OpenSSH).", file=sys.stderr)
        return 3
    out.mkdir(parents=True, exist_ok=True)
    lock_folder(out)
    for f in files:
        f.unlink(missing_ok=True)
    values = make_values()
    (out / "secrets.env").write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "vidhi-deploy", "-f", str(out / "deploy_key")], capture_output=True, text=True)
    if r.returncode != 0:
        print("Could not make the deploy key.", file=sys.stderr)
        return 3
    print(f"Wrote {len(values)} secrets and a deploy key into {out}. Nothing was printed or sent anywhere.")
    print("Names: " + ", ".join(values) + ", and deploy_key / deploy_key.pub")
    print("Next: put copies in your password manager, then follow docs/OWNER_TODO.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
