# Founders Portal — Backup & Restore Runbook (S0)

Backups: nightly, encrypted (gpg AES256), uploaded to Google Drive `FoundersPortalBackups/`
via rclone. Retention 30 daily + 12 monthly. Each backup = encrypted tar of `db.sql.gz` + `.env`.

## The recovery key
`BACKUP_PASSPHRASE` lives in the VPS `.env` AND in Tim's off-box copy (password manager / safe).
The backup bundle CONTAINS `.env`, so if the VPS is gone you MUST use the off-box passphrase to
decrypt. Without it, backups are unrecoverable. Keep it safe.

## Case A — Undo an accidental delete / bad migration (VPS alive)
1. List backups:  `rclone lsf gdrive:FoundersPortalBackups/`
2. Pull the one you want: `rclone copy gdrive:FoundersPortalBackups/<file>.gpg /root/backups/`
3. Restore into a TEST db (safe, default):
   `cd /var/www/founders-portal && ./scripts/restore.sh /root/backups/<file>.gpg`
   → confirm the printed row counts look right.
4. Copy the lost rows from `founders_portal_restore_test` back into `founders_portal`
   (targeted `INSERT … SELECT` for the affected table), OR if the whole DB should roll back:
   `./scripts/restore.sh /root/backups/<file>.gpg founders_portal` (it will require typing
   `OVERWRITE PROD`). Restart: `systemctl restart founders-portal`.

## Case B — VPS destroyed (full disaster recovery)
1. Provision a fresh Ubuntu server; install: `apt install postgresql rclone gnupg python3`.
2. `rclone config` → re-auth to Google Drive (remote `gdrive`).
3. `rclone copy gdrive:FoundersPortalBackups/<latest>.gpg .`
4. `git clone` the repo to `/var/www/founders-portal`.
5. Restore (you'll be prompted for the OFF-BOX passphrase since .env isn't present yet):
   `./scripts/restore.sh <latest>.gpg founders_portal`
6. Restore `.env`: the restore script drops the backed-up `.env` as `restored_env_*.backup` —
   move it to `/var/www/founders-portal/.env`.
7. `./venv/bin/pip install -r requirements.txt && flask db upgrade && systemctl restart founders-portal`.

## Required .env vars (S0)
- `BACKUP_PASSPHRASE` — gpg key (ALSO keep off-box).
- `BACKUP_ALERT_EMAIL` — failure/health emails recipient.
- `BACKUP_RCLONE_REMOTE` — e.g. `gdrive:FoundersPortalBackups`.
- (reuses `SENDGRID_API_KEY`, `LABELS_FROM_EMAIL`.)
