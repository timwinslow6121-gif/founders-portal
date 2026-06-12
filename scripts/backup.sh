#!/usr/bin/env bash
# scripts/backup.sh — nightly encrypted off-site backup of the Founders portal DB + .env.
# Run as root on the VPS via cron. Reads config from the portal .env. Exits non-zero on any
# failure so the cron wrapper (backup_report.py) can alert. See docs/RESTORE_RUNBOOK.md.
set -euo pipefail

APP_DIR="${APP_DIR:-/var/www/founders-portal}"
BACKUP_DIR="${BACKUP_DIR:-/root/backups}"
LOG="${BACKUP_LOG:-/var/log/founders-backup.log}"
DB_NAME="${DB_NAME:-founders_portal}"
DB_USER="${DB_USER:-postgres}"            # local peer auth as postgres
RETAIN_DAILY="${RETAIN_DAILY:-30}"
RETAIN_MONTHLY="${RETAIN_MONTHLY:-12}"

log(){ echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
fail(){ log "ERROR: $*"; exit 1; }

# Load config from the portal .env (BACKUP_PASSPHRASE, BACKUP_RCLONE_REMOTE, etc.)
[ -f "$APP_DIR/.env" ] || fail ".env not found at $APP_DIR/.env"
set -a; # shellcheck disable=SC1090
source <(grep -E '^(BACKUP_PASSPHRASE|BACKUP_RCLONE_REMOTE)=' "$APP_DIR/.env" || true); set +a
[ -n "${BACKUP_PASSPHRASE:-}" ] || fail "BACKUP_PASSPHRASE missing in .env"
[ -n "${BACKUP_RCLONE_REMOTE:-}" ] || fail "BACKUP_RCLONE_REMOTE missing in .env"

mkdir -p "$BACKUP_DIR"
TS="$(date '+%Y%m%d_%H%M%S')"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

log "Backup start ($TS)"
# 1. DB dump
sudo -u "$DB_USER" pg_dump "$DB_NAME" | gzip > "$WORK/db.sql.gz" || fail "pg_dump failed"
[ -s "$WORK/db.sql.gz" ] || fail "pg_dump produced empty output"
# 2. .env copy
cp "$APP_DIR/.env" "$WORK/env.backup" || fail ".env copy failed"
# 3. bundle
ARCHIVE="$BACKUP_DIR/founders_portal_${TS}.tar.gz"
tar -czf "$ARCHIVE" -C "$WORK" db.sql.gz env.backup || fail "tar failed"
# 4. encrypt (AES256 symmetric; passphrase from env)
ENC="${ARCHIVE}.gpg"
gpg --batch --yes --symmetric --cipher-algo AES256 \
    --passphrase "$BACKUP_PASSPHRASE" -o "$ENC" "$ARCHIVE" || fail "gpg encrypt failed"
rm -f "$ARCHIVE"   # keep only the encrypted copy locally
log "Encrypted -> $ENC ($(du -h "$ENC" | cut -f1))"

# 5. upload to Drive
# RCLONE_FLAGS: ride through transient Google Drive 403/429 rate-limits. The remote
# uses rclone's SHARED default OAuth client_id (no custom client_id in the config),
# which Google throttles globally — so a nightly run can hit a 'Queries per minute'
# 403 unrelated to our tiny usage. Retries + pacer backoff self-heal it. The durable
# fix is a private OAuth client_id (see scripts/RCLONE_OWN_CLIENT_ID.md).
RCLONE_FLAGS=(--retries 5 --retries-sleep 30s --low-level-retries 10
              --drive-pacer-min-sleep 100ms --drive-pacer-burst 1
              --log-file "$LOG" --log-level INFO)
rclone copy "$ENC" "$BACKUP_RCLONE_REMOTE/" "${RCLONE_FLAGS[@]}" \
    || fail "rclone upload failed"
log "Uploaded to $BACKUP_RCLONE_REMOTE"

# 6. retention — daily: keep newest RETAIN_DAILY .gpg locally + on Drive.
#    monthly: keep the FIRST backup seen each YYYYMM beyond the daily window.
prune() {
  # local
  ls -1t "$BACKUP_DIR"/founders_portal_*.tar.gz.gpg 2>/dev/null | tail -n +$((RETAIN_DAILY+1)) \
    | while read -r f; do
        ym="$(basename "$f" | sed -E 's/founders_portal_([0-9]{6}).*/\1/')"
        # keep one monthly per YYYYMM
        if ! grep -q "$ym" "$BACKUP_DIR/.monthly_keep" 2>/dev/null; then
          echo "$ym" >> "$BACKUP_DIR/.monthly_keep"; log "Retain monthly $ym ($(basename "$f"))"
        else
          rm -f "$f"; log "Pruned local $(basename "$f")"
        fi
      done
  # drive: delete files older than RETAIN_DAILY days EXCEPT keep the monthly-tagged ones is
  # complex via rclone alone; simplest robust rule for a tiny DB: keep last (RETAIN_DAILY +
  # RETAIN_MONTHLY*31) days on Drive via --min-age. This over-keeps slightly (fine at 155KB).
  local max_age=$(( (RETAIN_DAILY + RETAIN_MONTHLY*31) ))
  rclone delete "$BACKUP_RCLONE_REMOTE/" --min-age "${max_age}d" "${RCLONE_FLAGS[@]}" || true
}
prune

log "Backup OK ($TS)"
