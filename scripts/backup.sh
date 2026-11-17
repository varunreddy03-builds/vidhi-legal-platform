#!/usr/bin/env bash
# Encrypted database backup (documents are inside the database, in GridFS, so this is the whole thing).
#
#   BACKUP_PASSPHRASE_FILE=/secure/backup.pass  bash scripts/backup.sh [output-dir]
#
# Runs mongodump INSIDE the mongo container (no ports opened), compresses, and encrypts with GnuPG (AES-256).
# The passphrase is read from a FILE, never from the command line or the environment, so it cannot leak through
# `ps` or logs. Keep the passphrase somewhere other than the server that holds the backups.
# Output: <dir>/vidhi-YYYYMMDD-HHMMSSZ.archive.gz.gpg   (old ones are removed after KEEP_DAYS, default 30)
set -euo pipefail

OUT_DIR="${1:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
COMPOSE="${COMPOSE:-docker compose}"
: "${BACKUP_PASSPHRASE_FILE:?set BACKUP_PASSPHRASE_FILE to a file holding the encryption passphrase}"
[ -s "$BACKUP_PASSPHRASE_FILE" ] || { echo "passphrase file is missing or empty" >&2; exit 1; }
[ -f .env ] || { echo "run this from the folder that holds docker-compose.yml and .env" >&2; exit 1; }

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"
stamp="$(date -u +%Y%m%d-%H%M%SZ)"
final="$OUT_DIR/vidhi-$stamp.archive.gz.gpg"
partial="$final.partial"

# Credentials are read inside the container from its own environment: they never appear on this command line.
$COMPOSE exec -T mongo sh -c \
  'mongodump --quiet --archive --gzip --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --db "$DB_NAME"' \
  | gpg --batch --yes --quiet --symmetric --cipher-algo AES256 --pinentry-mode loopback \
        --passphrase-file "$BACKUP_PASSPHRASE_FILE" --output "$partial"

# A backup that cannot be decrypted or is empty is worse than none: check before keeping it.
gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$BACKUP_PASSPHRASE_FILE" --decrypt "$partial" | gzip -t
size="$(wc -c < "$partial")"
[ "$size" -gt 1024 ] || { echo "backup is suspiciously small ($size bytes) - not keeping it" >&2; rm -f "$partial"; exit 1; }
mv "$partial" "$final"
chmod 600 "$final"
find "$OUT_DIR" -name 'vidhi-*.archive.gz.gpg' -mtime "+$KEEP_DAYS" -delete
echo "backup written: $final ($size bytes)"
