#!/usr/bin/env bash
# scripts/restore.sh — decrypt a backup and restore into a target DB.
# Usage: restore.sh <archive.tar.gz.gpg> [target_db]
# Default target = founders_portal_restore_test (NEVER prod unless you name it explicitly).
# Reads BACKUP_PASSPHRASE from $APP_DIR/.env, or prompts if absent (DR from a fresh box).
set -euo pipefail

APP_DIR="${APP_DIR:-/var/www/founders-portal}"
DB_USER="${DB_USER:-postgres}"
ENC="${1:?Usage: restore.sh <archive.tar.gz.gpg> [target_db]}"
TARGET="${2:-founders_portal_restore_test}"

[ -f "$ENC" ] || { echo "Backup file not found: $ENC"; exit 1; }

# passphrase: from .env if present, else prompt (DR scenario where .env isn't restored yet)
if [ -f "$APP_DIR/.env" ] && grep -q '^BACKUP_PASSPHRASE=' "$APP_DIR/.env"; then
  PASS="$(grep '^BACKUP_PASSPHRASE=' "$APP_DIR/.env" | cut -d= -f2-)"
else
  read -rsp "Enter BACKUP_PASSPHRASE (your off-box copy): " PASS; echo
fi

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
echo "Decrypting…"
gpg --batch --yes --decrypt --passphrase "$PASS" -o "$WORK/b.tar.gz" "$ENC" || { echo "Decrypt failed (wrong passphrase?)"; exit 1; }
tar -xzf "$WORK/b.tar.gz" -C "$WORK"
[ -f "$WORK/db.sql.gz" ] || { echo "No db.sql.gz in archive"; exit 1; }

echo "Restoring into DB: $TARGET"
if [ "$TARGET" = "founders_portal" ]; then
  read -rp "*** TARGET IS PRODUCTION. Type 'OVERWRITE PROD' to continue: " c
  [ "$c" = "OVERWRITE PROD" ] || { echo "Aborted."; exit 1; }
fi
sudo -u "$DB_USER" psql -c "DROP DATABASE IF EXISTS \"$TARGET\";" 2>/dev/null || true
sudo -u "$DB_USER" psql -c "CREATE DATABASE \"$TARGET\";"
gunzip -c "$WORK/db.sql.gz" | sudo -u "$DB_USER" psql -d "$TARGET" >/dev/null
echo "Restore complete. Row counts:"
sudo -u "$DB_USER" psql -d "$TARGET" -c \
  "SELECT 'customers' t, count(*) FROM customers UNION ALL \
   SELECT 'policies', count(*) FROM policies UNION ALL \
   SELECT 'commission_line_items', count(*) FROM commission_line_items;"
echo "The .env from the backup is at: $WORK/env.backup (copied below before cleanup)"
cp "$WORK/env.backup" "./restored_env_$(date +%s).backup" 2>/dev/null || true
