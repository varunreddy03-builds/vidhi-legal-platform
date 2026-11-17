"""Deployment configuration stays honest: every setting the code reads is documented in .env.example, and the container passes them through."""

import os
import re
from pathlib import Path

ROOT = Path(os.path.abspath(__file__)).parents[2]
BACKEND = ROOT / "backend"
# Set by the platform or only for tests/development: not something an operator fills in.
INTERNAL = {"PATH", "HOME", "PYTHONPATH", "PYTEST_CURRENT_TEST", "AI_STUB", "PAYMENTS_STUB", "EMAIL_DRY_RUN", "VOICE_STUB", "TWILIO_STUB", "WEBPUSH_STUB", "GOOGLE_STUB", "IMAGEGEN_STUB",
            "LIBRARY_DIR", "TEMPLATES_DIR", "WEB_CONCURRENCY", "TRUST_PROXY", "ENABLE_DOCS", "MONGO_URL", "DB_NAME", "COOKIE_SECURE", "BCRYPT_COST", "AI_TIMEOUT_SECONDS", "AI_MAX_OUTPUT_TOKENS",
            "MAX_CONTEXT_CHARS", "FREE_CONTEXT_CHARS", "AI_ROUTE"}
READ = re.compile(r"""os\.environ(?:\.get\(|\[)\s*["']([A-Z][A-Z0-9_]+)["']""")
READ_F = re.compile(r"""f?["']RATE_LIMIT_""")


def used_settings() -> set[str]:
    names: set[str] = set()
    for f in BACKEND.rglob("*.py"):
        rel = f.relative_to(BACKEND).parts
        if rel[0] in ("tests", "scripts", "evals") or "venv" in rel:
            continue
        names |= set(READ.findall(f.read_text(encoding="utf-8")))
    return names


def documented() -> set[str]:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, re.M))


def test_every_setting_the_code_reads_is_documented_for_the_operator():
    missing = sorted(n for n in used_settings() - documented() - INTERNAL if not n.startswith("AI_ROUTE"))
    assert missing == [], f"add these to .env.example (or to INTERNAL if they are not operator settings): {missing}"


def test_nothing_in_the_example_file_is_a_real_looking_secret():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            value = line.split("=", 1)[1].strip()
            assert len(value) < 40 and not re.search(r"(sk_(live|test)_|gsk_|AIza|SG\.|rzp_(live|test)_|re_[A-Za-z0-9]{12,})", value), f"{line.split('=')[0]} looks like a real secret"


def test_the_container_loads_settings_from_the_env_file_and_hides_the_database():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "env_file: .env" in compose and 'COOKIE_SECURE: "true"' in compose and 'ENABLE_DOCS: "false"' in compose
    assert re.search(r"expose:\s*\n\s*- \"8001\"", compose) and "27017:27017" not in compose  # the API and the database are not published


def test_the_backend_image_ships_no_tests_or_env_files():
    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert "rm -rf tests .env .env.*" in dockerfile and "USER appuser" in dockerfile and "requirements.lock" in dockerfile


def test_the_secrets_files_are_ignored_by_git():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "**/.env" in ignore and "!.env.example" in ignore