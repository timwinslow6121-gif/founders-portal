# Off-Site Automated Backups (S0) — Design Spec

**Date:** 2026-06-09
**Status:** ✅ Implemented + deployed (2026-06-09). Backups live + cron installed + round-trip verified (restore counts matched prod exactly: customers 1025, policies 1046, line_items 591). Email alerts now WORK (migrated SendGrid→Brevo 2026-06-09 — SendGrid free tier had lapsed; all portal email consolidated through app/mailer.py on Brevo; domain DKIM-authenticated). Backup health email verified sending.
**Part of:** Milestone 1 — Security & Resilience. S0 is the FIRST pillar (the safety net under everything else). See [[roadmap-2026-06-09]]. Pillars S1 (access hardening), S2 (audit/alert), S3 (encryption-at-rest), S4 (pentest) are separate specs.

## Goal

Nightly, encrypted, off-site backups of the production database + config to Google Drive, with failure alerting and a tested one-command restore — so a breach, a bad migration, or an accidental delete (Tim has lost CRM data before) is always recoverable, even if the VPS itself is destroyed.

## Context

- DB is small: **16 MB live, ~155 KB gzipped**. Backups are effectively free in space/time, so retention is generous.
- No backup automation exists today. Manual `pg_dump` copies have been written to `/root` — but that's ON the VPS (useless if the VPS dies). The whole point of S0 is getting copies OFF the box.
- VPS: Ubuntu, root access, 18 GB free disk, PostgreSQL 16, `app/mailer.py` (SendGrid) already exists for alerts. No rclone/gpg installed yet.

## Architecture

Five components, all ops/cron (no portal UI):

### 1. Backup script — `scripts/backup.sh` (runs on VPS via cron, as root)
1. `pg_dump founders_portal | gzip` → `db.sql.gz`.
2. Copy the VPS `.env` alongside (so a from-scratch rebuild has secrets/OAuth creds).
3. Bundle into one timestamped archive: `founders_portal_YYYYMMDD_HHMMSS.tar.gz` (contains `db.sql.gz` + `env.backup`).
4. **Encrypt** with `gpg --symmetric --cipher-algo AES256` using a passphrase from `BACKUP_PASSPHRASE` (env var) → `…tar.gz.gpg`. (CRITICAL: the archive contains `.env`, which itself contains `BACKUP_PASSPHRASE` — so the passphrase must ALSO be held off-box by Tim; without his off-box copy, a destroyed VPS means an undecryptable backup. That off-box copy is the recovery key.)
5. **Upload** the `.gpg` to Google Drive via **rclone** to a configured remote+folder (e.g. `gdrive:FoundersPortalBackups/`).
6. Keep a local copy in `/root/backups/` too (fast local restore; Drive is the disaster copy).
7. Log all steps + outcome to `/var/log/founders-backup.log`. Exit non-zero on any failure (so the alert layer fires).

### 2. Retention — grandfather-father-son (in `backup.sh`, after upload)
- Keep **30 daily** + **12 monthly** (the last backup of each month promoted to "monthly"). Prune older than that, BOTH locally (`/root/backups/`) and on Drive (`rclone delete`/`--min-age`). ~6 MB total — negligible. Recovers Tim to any of the last 30 days or any month-end for a year.

### 3. Monitoring / alerting (reuses `app/mailer.py` SendGrid sender)
- **On failure** (pg_dump / gpg / rclone error, or rclone remote unreachable) → email Tim immediately with the failing step + error tail from the log. Low-noise: only failures, never routine success.
- **Weekly health summary** (separate cron, e.g. Monday): email "backups healthy — last good = `<date>`, N daily + M monthly retained on Drive" so silence never hides a quietly-broken job. Implemented as a small Python entrypoint (`scripts/backup_report.py`) that reads the log / lists the Drive folder via rclone and calls `send_email`. (A standalone invocation of the Flask app context to use `mailer.send_email`; or a thin direct SendGrid call mirroring mailer.py if app-context bootstrap is heavy in cron.)

### 4. Restore — `scripts/restore.sh` + `docs/RESTORE_RUNBOOK.md`
- `restore.sh <archive.gpg> [target_db]`: prompt for / read the passphrase → `gpg --decrypt` → untar → `gunzip` → `psql` restore into `target_db` (DEFAULT: `founders_portal_restore_test`, NEVER prod by default — verify before clobbering). Prints row counts of key tables (customers, policies, commission_line_items) after restore so Tim can sanity-check.
- **Runbook** (`docs/RESTORE_RUNBOOK.md`) covers BOTH recovery cases:
  - (a) **Undo an accidental delete / bad migration:** pull latest good backup → restore into `_restore_test` → diff/copy the lost rows back into prod (or, if recent enough, full swap). 
  - (b) **VPS destroyed (full DR):** provision fresh server → install postgres + rclone + gpg → `rclone copy` latest backup from Drive (authenticate rclone fresh) → decrypt with Tim's OFF-BOX passphrase → restore → redeploy code from git → restore `.env` from the backup bundle.

### 5. Scheduling — `/etc/cron.d/founders-backup`
- `backup.sh` nightly (e.g. 3:15 AM server time), as root, output appended to `/var/log/founders-backup.log`.
- `backup_report.py` weekly (e.g. Monday 8 AM).

## Backup scope (what's captured)
- **Database** (pg_dump of founders_portal) — the irreplaceable data.
- **`.env`** — secrets/OAuth/config, so a rebuild is fast. (Extra-sensitive; that's why the bundle is encrypted.)
- NOT uploaded commission files (portal discards them to tempfiles — no persisted file state) and NOT code (in git).

## One-time setup (Tim + Claude at deploy)
1. `apt install rclone gnupg` on the VPS.
2. `rclone config` → OAuth to Tim's Google Drive (interactive; Tim approves once) → remote named `gdrive`, target folder `FoundersPortalBackups/`.
3. Generate a strong `BACKUP_PASSPHRASE`; add to VPS `.env`; **Tim saves a copy off-box** (password manager / safe). This is the recovery key.
4. Install the cron file; run `backup.sh` once manually to seed + verify.

## Config / secrets (added to VPS `.env`)
- `BACKUP_PASSPHRASE` — gpg symmetric key (also held off-box by Tim).
- `BACKUP_ALERT_EMAIL` — where failure/health emails go (Tim).
- `BACKUP_RCLONE_REMOTE` — e.g. `gdrive:FoundersPortalBackups` (so the script isn't hardcoded).
- Reuses existing `SENDGRID_API_KEY`, `LABELS_FROM_EMAIL`/`MAIL_FROM`.

## Testing / verification (an untested backup is not a backup)
- Scripts are bash/Python — verification is a documented round-trip, run at deploy and recorded:
  1. Run `backup.sh` manually → confirm `.gpg` appears locally AND in the Drive folder (`rclone ls`).
  2. Run `restore.sh <that backup>` into `founders_portal_restore_test` → confirm it decrypts, restores, and the printed row counts MATCH prod (customers/policies/commission_line_items).
  3. Simulate a failure (e.g. bad rclone remote) → confirm the failure email fires.
  4. Run `backup_report.py` → confirm the health-summary email arrives.
- No pytest (it's ops scripting outside the app), but the round-trip proof is mandatory before declaring S0 done.

## Boundaries (what S0 is NOT)
- NOT S1-S4 (login lockout, audit log, live-DB encryption-at-rest, pentest).
- NOT a portal UI — backups are cron/ops; status arrives by email.
- NOT point-in-time / WAL-streaming replication (overkill for a 16 MB CRM that changes in monthly bursts; nightly snapshots + 30-day retention is the right recovery-point objective here).
- NOT multi-destination (Google Drive only for now; object-storage second copy was considered and deferred — revisit if PHI-compliance later demands immutable/versioned storage).

## Open items (non-blocking)
- Exact cron times (3:15 AM / Monday 8 AM are defaults; adjust to taste).
- Whether the weekly health check should also do a periodic auto-restore-test (deferred; the deploy round-trip covers initial proof).
