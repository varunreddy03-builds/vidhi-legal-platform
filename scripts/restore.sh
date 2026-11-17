#!/usr/bin/env bash
# Restore an encrypted backup made by scripts/backup.sh.
#
#   BACKUP_PASSPHRASE_FILE=/secure/backup.pass  bash scripts/restore.sh backups/vidhi-20261019-040000Z.archive.gz.gpg [--yes]
#
# DESTRUCTIVE: replaces the contents of the database (mongorestore --drop). It asks you to type the database
# name first unless --yes is given. Practise this on a spare machine BEFORE you need it (see docs/RUNBOOK.md).
set -euo pipefail

FILE="${1:?usage: restore.sh <backup.archive.gz.gpg> [--yes]}"
COMPOSE="${COMPOSE:-docker compose}"
: "${BACKUP_PASSPHRASE_FILE:?set BACKUP_PASSPHRASE_FILE to a file holding the encryption passphrase}"
[ -f "$FILE" ] || { echo "no such backup: $FILE" >&2; exit 1; }
[ -f .env ] || { echo "run this from the folder that holds docker-compose.yml and .env" >&2; exit 1; }

db_name="$(grep -E '^DB_NAME=' .env | head -1 | cut -d= -f2- | tr -d '\r"')"
[ -n "$db_name" ] || { echo "DB_NAME not found in .env" >&2; exit 1; }

if [ "${2:-}" != "--yes" ]; then
  echo "This REPLACES everything in database '$db_name' with the contents of $FILE."
  read -r -p "Type the database name to continue: " typed
  [ "$typed" = "$db_name" ] || { echo "not confirmed - nothing changed" >&2; exit 1; }
fi

# Decrypt+decompress check first, so a wrong passphrase or a damaged file stops us before anything is dropped.
gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$BACKUP_PASSPHRASE_FILE" --decrypt "$FILE" | gzip -t

gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$BACKUP_PASSPHRASE_FILE" --decrypt "$FILE" \
  | $COMPOSE exec -T mongo sh -c \
    'mongorestore --quiet --archive --gzip --drop --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --nsInclude "$DB_NAME.*"'

echo "restored. Restart the API so it re-checks its indexes:  $COMPOSE restart backend"
