"""Builds the server's `.env` from the host's secret store, for a deployment profile (staging or production).

    python deploy/render_env.py --profile staging [--out .env] [--check-only]

Where each value comes from, strongest first:
  1. the process environment: the host's secret store (a GitHub Environment's secrets, a cloud secret manager, a CI job) exports each secret as an environment variable;
  2. the profile file deploy/profiles/<profile>.env (non-secret choices that differ between staging and production);
  3. the default written in .env.example.
Only names listed in .env.example are written. The script refuses to write anything when a required value is missing or unsafe, names the problem WITHOUT printing any value, and writes the
file readable by its owner only. Nothing here talks to the network."""

import argparse
import os
import re
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=(.*)$")
REQUIRED = ("DOMAIN", "DB_NAME", "MONGO_ROOT_PASSWORD", "MONGO_APP_USER", "MONGO_APP_PASSWORD", "APP_URL", "CORS_ORIGINS", "LINK_SECRET", "WEBHOOK_CRON_SECRET", "DATA_ENCRYPTION_KEY")
ONE_OF = ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "NVIDIA_API_KEY", "MISTRAL_API_KEY", "ZAI_API_KEY")
STUBS = ("AI_STUB", "PAYMENTS_STUB", "EMAIL_DRY_RUN", "VOICE_STUB", "TWILIO_STUB", "WEBPUSH_STUB", "GOOGLE_STUB", "IMAGEGEN_STUB")
PLACEHOLDERS = ("DOMAIN", "APP_URL", "CORS_ORIGINS")
SIMPLE = re.compile(r"^[A-Za-z0-9]+$")  # the database passwords go inside a URL


def parse(path: Path, active_only: bool = False) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = LINE.match(raw)
        if not m or (active_only and raw.lstrip().startswith("#")):
            continue
        out[m.group(1)] = m.group(2).split("  #")[0].strip().strip('"')
    return out


def known_names(example: Path) -> list[str]:
    seen, names = set(), []
    for raw in example.read_text(encoding="utf-8").splitlines():
        m = LINE.match(raw)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            names.append(m.group(1))
    return names


def build(profile: str, environ: dict[str, str] | None = None, example: Path | None = None, profiles_dir: Path | None = None) -> tuple[dict[str, str], list[str]]:
    """(values, problems). Problems are sentences that name settings and never contain a value."""
    environ = os.environ if environ is None else environ
    example = example or ROOT / ".env.example"
    pfile = (profiles_dir or ROOT / "deploy" / "profiles") / f"{profile}.env"
    if not pfile.is_file():
        return {}, [f"There is no profile '{profile}' (expected {pfile.name} in deploy/profiles)."]
    defaults = parse(example, active_only=True)
    chosen = parse(pfile, active_only=True)
    values: dict[str, str] = {}
    for name in known_names(example):
        # the placeholder addresses in .env.example are never accepted as a real value: they must come from the secret store or the profile
        fallback = "" if name in PLACEHOLDERS else defaults.get(name, "")
        values[name] = (environ.get(name) or "").strip() or chosen.get(name, "") or fallback
    for name, v in chosen.items():  # a profile may also set a name the example only mentions in a comment
        if name not in values and name in known_names(example):
            values[name] = v

    problems: list[str] = []
    for name in REQUIRED:
        if not values.get(name):
            problems.append(f"{name} is missing: put it in the host's secret store (or the profile, if it is not a secret).")
    if not any(values.get(n) for n in ONE_OF):
        problems.append("No AI provider key is set: one of " + ", ".join(ONE_OF) + " is needed.")
    app = values.get("APP_URL", "")
    if app and not app.startswith("https://"):
        problems.append("APP_URL must be an https address.")
    if "*" in [o.strip() for o in values.get("CORS_ORIGINS", "").split(",")]:
        problems.append("CORS_ORIGINS must name your own address, not a wildcard (*).")
    domain, host = values.get("DOMAIN", ""), re.sub(r"^https://", "", app).split("/")[0]
    if domain and host and domain != host:
        problems.append("DOMAIN and APP_URL must name the same host (the address the proxy gets a certificate for).")
    for name in ("MONGO_ROOT_PASSWORD", "MONGO_APP_PASSWORD"):
        v = values.get(name, "")
        if v and (len(v) < 16 or not SIMPLE.match(v)):
            problems.append(f"{name} must be at least 16 letters and digits only (it is placed inside a URL).")
    for name in ("LINK_SECRET", "WEBHOOK_CRON_SECRET"):
        if values.get(name) and len(values[name]) < 32:
            problems.append(f"{name} must be at least 32 characters.")
    for name in STUBS:  # these are not written to .env (they are not documented settings), but a deploy job that has them switched on is a mistake worth stopping
        if (environ.get(name) or "").strip().lower() == "true":
            problems.append(f"{name} is a test-only switch and must not be true on a server.")
    if (environ.get("COOKIE_SECURE") or values.get("COOKIE_SECURE", "true")).strip().lower() == "false":
        problems.append("COOKIE_SECURE must not be false on a server.")
    return values, problems


def write_env(values: dict[str, str], out: Path) -> None:
    lines = ["# Written by deploy/render_env.py from the host's secret store. Do not edit by hand; do not commit.\n"]
    for name, v in values.items():
        if "\n" in v or "\r" in v:
            raise ValueError(f"{name} has a line break in it")
        if v == "":
            continue  # an unset setting is left OUT: "NAME=" is a real, empty value to the app and to Docker (a number read from it crashed every AI call), and the code's own default applies only when the name is absent
        lines.append(f"{name}={v}\n")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(out, flags, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.writelines(lines)
    try:
        os.chmod(out, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", default=str(ROOT / ".env"))
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args()
    values, problems = build(a.profile)
    if problems:
        print("Nothing was written. Fix these first:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    if a.check_only:
        print(f"Profile '{a.profile}' is complete: {sum(1 for v in values.values() if v)} settings have a value.")
        return 0
    write_env(values, Path(a.out))
    print(f"Wrote {a.out} for profile '{a.profile}' ({sum(1 for v in values.values() if v)} settings with a value). Values are not printed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
