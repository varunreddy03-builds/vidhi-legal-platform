"""The deployment files, checked without Docker (Docker is not on every machine, so these read the files): what is published, what the compose file needs from .env, the proxy and web
settings, and that the staging and production profiles hold choices only, never secrets. render_env.py is tested for what it refuses and what it writes."""

import importlib.util
import re
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")

spec = importlib.util.spec_from_file_location("render_env", ROOT / "deploy" / "render_env.py")
render_env = importlib.util.module_from_spec(spec)
sys.modules["render_env"] = render_env
spec.loader.exec_module(render_env)


def documented() -> set[str]:
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", ENV_EXAMPLE, re.M))


# ---------- compose ----------

def test_every_variable_compose_needs_without_a_default_is_documented_in_env_example():
    needed = {m.group(1) for m in re.finditer(r"\$\{([A-Z][A-Z0-9_]*)\}", COMPOSE)}
    assert needed, "compose should read its settings from .env"
    assert needed <= documented(), sorted(needed - documented())


def test_only_the_proxy_is_published_to_the_internet_and_the_database_and_api_are_not_published_at_all():
    ports = re.findall(r'^\s+- "(\d[\d.]*:\d+(?::\d+)?)"', COMPOSE, re.M)
    assert sorted(ports) == ["127.0.0.1:8080:80", "443:443", "80:80"]  # web on this machine's loopback only; 80 and 443 belong to the proxy
    blocks = {name: body for name, body in re.findall(r"^  (\w+):\n((?:    .*\n|\n)+)", COMPOSE, re.M)}
    for private in ("mongo", "backend", "backup"):
        assert "ports:" not in blocks[private], private
    assert "expose:" in blocks["backend"] and "8001" in blocks["backend"]
    assert 'profiles: ["https"]' in blocks["proxy"] and 'profiles: ["https"]' in blocks["backup"]


def test_containers_drop_privileges_and_wait_for_healthy_dependencies():
    assert COMPOSE.count("no-new-privileges:true") >= 5
    assert COMPOSE.count("cap_drop:") >= 2
    assert "condition: service_healthy" in COMPOSE and COMPOSE.count("condition: service_healthy") >= 4
    assert 'COOKIE_SECURE: "true"' in COMPOSE and 'ENABLE_DOCS: "false"' in COMPOSE
    assert "mongodb://${MONGO_APP_USER}" in COMPOSE and "MONGO_ROOT" not in COMPOSE.split("backend:")[1].split("web:")[0]  # the API never gets the root account


def test_the_backup_passphrase_is_a_secret_file_never_an_environment_value():
    assert "backup_passphrase" in COMPOSE and "/run/secrets/backup_passphrase" in COMPOSE and not re.search(r"^[A-Z_]*PASSPHRASE[A-Z_]*=", ENV_EXAMPLE, re.M)
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/secrets/" in gi and "/backups/" in gi
    di = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "secrets" in di and "backups" in di


def test_caddy_serves_only_the_domain_and_forwards_to_web_without_logging_addresses_or_headers():
    c = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert "{$DOMAIN}" in c and "reverse_proxy web:80" in c
    for deleted in ("request>uri delete", "request>headers delete", "resp_headers delete"):
        assert deleted in c
    assert "tls internal" not in c and "auto_https off" not in c  # real certificates, https always


def test_nginx_trusts_the_forwarded_address_only_from_private_ranges_and_still_sends_the_api_a_single_value():
    n = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
    assert "real_ip_header X-Forwarded-For" in n and "set_real_ip_from 172.16.0.0/12" in n
    assert "set_real_ip_from 0.0.0.0" not in n and "set_real_ip_from ::/0" not in n
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in n and "proxy_pass http://backend:8001;" in n


def test_the_backend_image_has_gnupg_for_backups_runs_as_a_normal_user_and_checks_its_health():
    d = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "gnupg" in d and "USER appuser" in d and "HEALTHCHECK" in d and "/api/health" in d
    assert "tools" not in d.split("rm -rf")[1].split("\n")[0]  # the backup tools are not deleted from the image


# ---------- profiles ----------

@pytest.mark.parametrize("profile", ["staging", "production"])
def test_profiles_hold_choices_only_never_secrets_and_only_names_that_exist(profile):
    text = (ROOT / "deploy" / "profiles" / f"{profile}.env").read_text(encoding="utf-8")
    names = [m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", text, re.M)]
    assert names and set(names) <= documented()
    for n in names:
        assert not re.search(r"SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE|ENCRYPTION", n), n
    values = render_env.parse(ROOT / "deploy" / "profiles" / f"{profile}.env", active_only=True)
    assert values["SIGNUP_MODE"] == "invite" and values["UPLOAD_MAX_DAYS"] == "30"  # decisions D5 and D6
    assert render_env.parse(ROOT / "deploy" / "profiles" / "production.env", active_only=True)["AUTHORITY_CHECK_ENABLED"] == "false"  # decision D6: off until the owner turns it on
    assert values["DB_NAME"] != "vidhi" or profile == "production"  # staging never shares production's database


# ---------- render_env ----------

SECRETS = {
    "DOMAIN": "app.example.in", "APP_URL": "https://app.example.in", "CORS_ORIGINS": "https://app.example.in", "MONGO_ROOT_PASSWORD": "R00tPassw0rdThatIsLongEnough", "MONGO_APP_PASSWORD": "AppPassw0rdThatIsLongEnough1",
    "LINK_SECRET": "l" * 40, "WEBHOOK_CRON_SECRET": "w" * 40, "DATA_ENCRYPTION_KEY": "ChEYHyYtNDtCSVBXXmVsc3qBiI-WnaSrsrnAx87V3OM=", "GEMINI_API_KEY": "AIza-test-not-real",
}


def build(**over):
    env = {**SECRETS, **over}
    return render_env.build("production", environ=env)


def test_a_complete_secret_store_gives_a_complete_env_and_no_problems():
    values, problems = build()
    assert problems == [] and values["SIGNUP_MODE"] == "invite" and values["DB_NAME"] == "vidhi" and values["MONGO_ROOT_USER"] == "root"
    assert values["GEMINI_API_KEY"] == "AIza-test-not-real"  # the secret store wins over the example
    staging, p2 = render_env.build("staging", environ=SECRETS)
    assert p2 == [] and staging["DB_NAME"] == "vidhi_staging" and staging["AUTHORITY_CHECK_ENABLED"] == "true"


@pytest.mark.parametrize("remove", ["MONGO_ROOT_PASSWORD", "LINK_SECRET", "DATA_ENCRYPTION_KEY", "GEMINI_API_KEY", "WEBHOOK_CRON_SECRET", "DOMAIN"])
def test_a_missing_secret_stops_the_build_and_names_it(remove):
    env = {k: v for k, v in SECRETS.items() if k != remove}
    values, problems = render_env.build("production", environ=env)
    assert problems and (remove in " ".join(problems) or "AI provider" in " ".join(problems))


def test_unsafe_choices_are_refused_without_printing_any_value():
    _, problems = build(APP_URL="http://app.example.in")
    assert any("https" in p for p in problems)
    _, problems = build(CORS_ORIGINS="*")
    assert any("wildcard" in p for p in problems)
    _, problems = build(DOMAIN="other.example.in")
    assert any("same host" in p for p in problems)
    _, problems = build(MONGO_APP_PASSWORD="short")
    assert any("MONGO_APP_PASSWORD" in p for p in problems)
    _, problems = build(MONGO_ROOT_PASSWORD="has-a-dash-and-is-long-enough-xx")
    assert any("MONGO_ROOT_PASSWORD" in p for p in problems)
    _, problems = build(LINK_SECRET="tooshort")
    assert any("LINK_SECRET" in p for p in problems)
    _, problems = build(AI_STUB="true")
    assert any("AI_STUB" in p for p in problems)
    _, problems = build(COOKIE_SECURE="false")
    assert any("COOKIE_SECURE" in p for p in problems)
    blob = " ".join(problems) + " ".join(build(LINK_SECRET="hunter2-this-is-short")[1])
    assert "hunter2" not in blob and "R00tPassw0rd" not in blob  # problems name settings, never values


def test_an_unknown_profile_is_refused():
    assert render_env.build("nonsense", environ=SECRETS)[1][0].startswith("There is no profile")


def test_the_env_file_is_written_for_its_owner_only_and_only_known_names_are_written(tmp_path):
    values, problems = build()
    assert not problems
    out = tmp_path / ".env"
    render_env.write_env(values, out)
    text = out.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=AIza-test-not-real" in text and "SIGNUP_MODE=invite" in text and text.startswith("# Written by")
    assert (out.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO)) == 0 or sys.platform == "win32"  # no access for group or others (Windows has no such bits)
    names = {m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", text, re.M)}
    assert names <= documented()
    with pytest.raises(ValueError):
        render_env.write_env({"X_KEY": "line\nbreak"}, tmp_path / "bad.env")


# ---------- CI and the deploy workflow ----------

def test_deploy_runs_the_whole_ci_first_is_inert_until_enabled_and_never_trusts_an_unknown_server():
    d = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "workflow_call:" in ci and "uses: ./.github/workflows/ci.yml" in d and "needs: tests" in d  # no deploy without a green CI
    assert "vars.DEPLOY_ENABLED == 'true'" in d and "workflow_dispatch:" in d and "on:\n  workflow_dispatch" in d  # manual only, and off until the owner switches it on
    assert "environment: ${{ inputs.environment }}" in d  # GitHub Environments hold the secrets and the production approval
    assert "StrictHostKeyChecking=yes" in d and "StrictHostKeyChecking=no" not in d and "ssh-keyscan" not in d
    assert not re.search(r"(echo|printf|cat)[^\n]*\$\{\{\s*secrets\.", d.replace("printf '%s\n' \"$DEPLOY_SSH_KEY\"", "")), "a secret must never be printed"
    secret_names = set(re.findall(r"secrets\.([A-Z][A-Z0-9_]+)", d))
    assert {"DEPLOY_SSH_KEY", "DEPLOY_KNOWN_HOSTS", "DEPLOY_HOST", "DEPLOY_USER", "DEPLOY_PATH"} <= secret_names
    app_secrets = secret_names - {"DEPLOY_SSH_KEY", "DEPLOY_KNOWN_HOSTS", "DEPLOY_HOST", "DEPLOY_USER", "DEPLOY_PATH"}
    assert app_secrets <= documented(), sorted(app_secrets - documented())  # every setting it passes on is a real, documented one
    assert set(render_env.REQUIRED) <= app_secrets | {"DB_NAME", "MONGO_APP_USER"}  # and it passes on everything render_env.py insists on


def test_ci_starts_the_whole_stack_validates_the_proxy_and_proves_a_backup_restores():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for needle in ("deploy/ci-env.sh", "docker compose --profile https config -q", "caddy validate", "docker compose up -d --build", "deploy/smoke.sh", "tools/db_backup.py", "--verify-only", "--replace --yes"):
        assert needle in ci, needle
    assert "AUTHORITY_CHECK_ENABLED" in ci and "E2E_PYTHON" in ci  # the browser job runs the new browser tests
    for script in ("scripts/test-backend.sh", "scripts/test-backend.ps1"):
        text = (ROOT / script).read_text(encoding="utf-8")
        for name in ("AUTHORITY_SOURCE_DISABLED", "UPLOAD_MAX_DAYS", "AUTHORITY_CHECK_ENABLED"):
            assert name in text, (script, name)  # the two test scripts stay in step (CI uses the .sh, this machine the .ps1)
