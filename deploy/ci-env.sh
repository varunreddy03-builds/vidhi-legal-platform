#!/usr/bin/env bash
# Makes a THROWAWAY .env for the CI smoke test of the whole stack: random secrets that exist only for this run, built through the real deploy/render_env.py with the production profile.
# Not for a real server (real values come from the host's secret store).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

rand() { python3 -c "import secrets,sys; print(secrets.token_hex(int(sys.argv[1])))" "$1"; }

export DOMAIN="ci.example.test"
export APP_URL="https://ci.example.test"
export CORS_ORIGINS="https://ci.example.test"
export MONGO_ROOT_PASSWORD="$(rand 12)"
export MONGO_APP_PASSWORD="$(rand 12)"
export LINK_SECRET="$(rand 24)"
export WEBHOOK_CRON_SECRET="$(rand 24)"
export DATA_ENCRYPTION_KEY="$(python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")"
export GEMINI_API_KEY="ci-throwaway-not-a-real-key"   # secret-scan: ok (fake throwaway value for the CI smoke test)
export SIGNUP_MODE="open"   # the smoke test does not create accounts; the production profile's invite-only mode is tested in the backend suite

python3 deploy/render_env.py --profile production --out .env
mkdir -p secrets backups
rand 24 > secrets/backup_passphrase
chmod 600 .env
# CI only: the containers run as an unprivileged user (uid 10001) that must be able to read the passphrase and write the backups. On a real server use chown instead (docs/hosting-runbook.md).
chmod 644 secrets/backup_passphrase
chmod 777 backups
