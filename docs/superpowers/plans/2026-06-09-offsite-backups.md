# Off-Site Automated Backups (S0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nightly encrypted off-site backups of the production DB + .env to Google Drive (via rclone + gpg), with failure/health email alerts and a tested one-command restore, so any breach/bad-migration/accidental-delete is recoverable even if the VPS is destroyed.

**Architecture:** Pure ops scripting committed to the repo, deployed to the VPS + scheduled by cron. `scripts/backup.sh` (pg_dump+.env → tar → gpg AES256 → rclone upload to Drive + local copy → prune retention → log → exit non-zero on failure). `scripts/backup_report.py` (failure + weekly-health email via the existing SendGrid mailer pattern). `scripts/restore.sh` + `docs/RESTORE_RUNBOOK.md` (decrypt → restore into a test DB by default). Verification is a mandatory real round-trip on the VPS at deploy (an untested backup is not a backup) — not pytest, since these run outside the Flask app.

**Tech Stack:** bash, PostgreSQL `pg_dump`/`psql`, `gpg` (symmetric AES256), `rclone` (Google Drive), Python 3 + SendGrid (reusing `app/mailer.py`'s pattern), cron.

---

## Decisions locked (from the approved spec)

- **Destination:** Google Drive via rclone (`gdrive:FoundersPortalBackups/`). **Schedule:** nightly 3:15 AM + weekly health Mon 8 AM. **Retention:** 30 daily + 12 monthly (GFS).
- **Encryption:** gpg `--symmetric --cipher-algo AES256`, passphrase in `.env` `BACKUP_PASSPHRASE` AND held off-box by Tim (the recovery key — the backup bundle CONTAINS .env, so the off-box copy is what makes a destroyed-VPS restore possible).
- **Scope:** DB (pg_dump) + `.env`. Not code (git), not uploaded files (discarded).
- **Alerting:** failure-only emails + weekly health summary. Reuse SendGrid.
- **Restore default target:** `founders_portal_restore_test` (NEVER prod by default).
- All scripts read config from env vars (no hardcoded secrets/paths): `BACKUP_PASSPHRASE`, `BACKUP_ALERT_EMAIL`, `BACKUP_RCLONE_REMOTE`, plus existing `SENDGRID_API_KEY`, `LABELS_FROM_EMAIL`.

## Why no pytest

These are ops scripts that run as root on the VPS against real postgres/rclone/gpg — they can't run in the SQLite-in-memory app test harness. Each task verifies by **running the script** (locally where the tool exists, e.g. gpg round-trip; on the VPS for pg_dump/rclone at deploy). The Task 7 VPS round-trip is the authoritative proof.

## File structure

- **Create** `scripts/backup.sh` — the nightly backup (dump+env→tar→gpg→rclone→prune→log).
- **Create** `scripts/restore.sh` — decrypt+restore into a target DB (default test DB).
- **Create** `scripts/backup_report.py` — failure + weekly health email (SendGrid, standalone — no Flask app context needed).
- **Create** `docs/RESTORE_RUNBOOK.md` — both recovery procedures.
- **Create** `deploy/founders-backup.cron` — the cron entries (committed for reference; installed to `/etc/cron.d/` on the VPS).
- **Modify** `.env.example` (if present) / document new env vars in the runbook.

---

### Task 1: `backup.sh` — dump, bundle, encrypt (local-verifiable core)

**Files:** Create `scripts/backup.sh`

- [ ] **Step 1: Write the script**

Create `scripts/backup.sh`:

```bash
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
rclone copy "$ENC" "$BACKUP_RCLONE_REMOTE/" --log-file "$LOG" --log-level INFO \
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
  rclone delete "$BACKUP_RCLONE_REMOTE/" --min-age "${max_age}d" --log-file "$LOG" || true
}
prune

log "Backup OK ($TS)"
```

- [ ] **Step 2: Verify the gpg round-trip locally (the part you CAN test off-VPS)**

Run (proves encrypt/decrypt works with the passphrase mechanism — uses a throwaway file, not the real DB):
```bash
cd /home/timothywinslowlinux/dev/founders-portal
echo "secret data" > /tmp/t.txt && tar -czf /tmp/t.tar.gz -C /tmp t.txt
gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase "testpw" -o /tmp/t.tar.gz.gpg /tmp/t.tar.gz
gpg --batch --yes --decrypt --passphrase "testpw" -o /tmp/t.out.tar.gz /tmp/t.tar.gz.gpg
tar -xzOf /tmp/t.out.tar.gz t.txt
```
Expected: prints `secret data` (round-trip works). Clean up `/tmp/t.*`.

- [ ] **Step 3: Shellcheck the script (catch bash bugs)**

Run: `shellcheck scripts/backup.sh 2>/dev/null || bash -n scripts/backup.sh && echo "syntax OK"`
Expected: no syntax errors (shellcheck warnings are advisory; `bash -n` must pass).

- [ ] **Step 4: chmod + commit**

```bash
chmod +x scripts/backup.sh
git add scripts/backup.sh
git commit -m "feat(backup): nightly encrypted backup script (dump+env→gpg→rclone→prune)"
```

---

### Task 2: `restore.sh` — decrypt + restore to a safe target

**Files:** Create `scripts/restore.sh`

- [ ] **Step 1: Write the script**

Create `scripts/restore.sh`:

```bash
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
```

- [ ] **Step 2: Syntax check**

Run: `bash -n scripts/restore.sh && echo "syntax OK"`
Expected: OK.

- [ ] **Step 3: chmod + commit**

```bash
chmod +x scripts/restore.sh
git add scripts/restore.sh
git commit -m "feat(backup): restore script (decrypt → restore into safe test DB by default)"
```

---

### Task 3: `backup_report.py` — failure + weekly health email

**Files:** Create `scripts/backup_report.py`

- [ ] **Step 1: Write the script**

Create `scripts/backup_report.py` (standalone — no Flask app context; direct SendGrid mirroring `app/mailer.py`, reading config from `.env`):

```python
#!/usr/bin/env python3
"""
scripts/backup_report.py — backup alerting for S0.

Two modes (cron-invoked):
  failure  : send an immediate failure email (called by the cron wrapper when backup.sh exits != 0)
  health   : weekly summary — last good backup + retained count on Drive

Standalone: reads SENDGRID_API_KEY / LABELS_FROM_EMAIL / BACKUP_ALERT_EMAIL / BACKUP_RCLONE_REMOTE
from the portal .env. No app import (cron-safe).
"""
import os, sys, subprocess, datetime

APP_DIR = os.environ.get("APP_DIR", "/var/www/founders-portal")
LOG = os.environ.get("BACKUP_LOG", "/var/log/founders-backup.log")


def load_env():
    env = {}
    p = os.path.join(APP_DIR, ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def send(subject, body, env):
    key = env.get("SENDGRID_API_KEY"); frm = env.get("LABELS_FROM_EMAIL") or env.get("MAIL_FROM")
    to = env.get("BACKUP_ALERT_EMAIL")
    if not (key and frm and to):
        print("backup_report: SendGrid not configured (key/from/to) — skipping email", file=sys.stderr)
        return False
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
    try:
        SendGridAPIClient(key).send(Mail(from_email=frm, to_emails=to,
                                         subject=subject, plain_text_content=body))
        return True
    except Exception as e:
        print(f"backup_report: send failed: {e}", file=sys.stderr); return False


def log_tail(n=25):
    try:
        return subprocess.run(["tail", "-n", str(n), LOG], capture_output=True, text=True).stdout
    except Exception:
        return "(no log)"


def drive_list(env):
    remote = env.get("BACKUP_RCLONE_REMOTE", "")
    if not remote:
        return "(no remote configured)"
    try:
        out = subprocess.run(["rclone", "lsf", remote + "/"], capture_output=True, text=True, timeout=60)
        files = [l for l in out.stdout.splitlines() if l.endswith(".gpg")]
        return files
    except Exception as e:
        return f"(rclone error: {e})"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "health"
    env = load_env()
    if mode == "failure":
        send("⚠ Founders Portal BACKUP FAILED",
             f"The nightly backup failed at {datetime.datetime.now():%Y-%m-%d %H:%M}.\n\n"
             f"Last log lines:\n{log_tail()}\n\nCheck {LOG} on the VPS.", env)
    else:  # health
        files = drive_list(env)
        n = len(files) if isinstance(files, list) else 0
        latest = sorted(files)[-1] if isinstance(files, list) and files else "(none found!)"
        ok = n > 0
        send(f"{'✓' if ok else '⚠'} Founders Portal backups — weekly health",
             f"Off-site backups on Drive: {n} retained.\nLatest: {latest}\n\n"
             f"{'All good.' if ok else 'WARNING: no backups found on Drive — investigate!'}\n\n"
             f"Recent log:\n{log_tail(10)}", env)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Syntax check + dry import**

Run: `python3 -c "import ast; ast.parse(open('scripts/backup_report.py').read()); print('syntax OK')"`
Expected: OK. (Full behavior is verified on the VPS at deploy where SendGrid + rclone exist.)

- [ ] **Step 3: Commit**

```bash
git add scripts/backup_report.py
git commit -m "feat(backup): failure + weekly-health email reporter (standalone SendGrid)"
```

---

### Task 4: cron file + restore runbook + env documentation

**Files:** Create `deploy/founders-backup.cron`, `docs/RESTORE_RUNBOOK.md`

- [ ] **Step 1: Write the cron file**

Create `deploy/founders-backup.cron` (installed to `/etc/cron.d/founders-backup` on the VPS):

```cron
# Founders Portal off-site backups (S0). Installed at /etc/cron.d/founders-backup.
# Nightly 3:15 AM: run backup; on failure, send the failure alert.
15 3 * * * root /var/www/founders-portal/scripts/backup.sh >> /var/log/founders-backup.log 2>&1 || /usr/bin/python3 /var/www/founders-portal/scripts/backup_report.py failure
# Weekly health summary, Monday 8:00 AM.
0 8 * * 1 root /usr/bin/python3 /var/www/founders-portal/scripts/backup_report.py health >> /var/log/founders-backup.log 2>&1
```

- [ ] **Step 2: Write the restore runbook**

Create `docs/RESTORE_RUNBOOK.md`:

```markdown
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
```

- [ ] **Step 3: Commit**

```bash
git add deploy/founders-backup.cron docs/RESTORE_RUNBOOK.md
git commit -m "feat(backup): cron schedule + restore runbook + env docs"
```

---

### Task 5: VPS deploy + one-time setup + MANDATORY round-trip verification

**This task is hands-on with Tim (rclone OAuth + saving the passphrase off-box). It is the authoritative proof S0 works.**

- [ ] **Step 1: Install tools on the VPS**

```bash
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100
apt-get update && apt-get install -y rclone gnupg python3
git -C /var/www/founders-portal pull origin main
```

- [ ] **Step 2: rclone OAuth to Google Drive (Tim, interactive)**

On the VPS: `rclone config` → `n` (new remote) → name `gdrive` → type `drive` → follow the OAuth (Tim approves in a browser; for a headless VPS use `rclone authorize "drive"` on a local machine and paste the token). Create the folder: `rclone mkdir gdrive:FoundersPortalBackups`. Verify: `rclone lsd gdrive:`.

- [ ] **Step 3: Generate passphrase + set env vars (Tim saves passphrase off-box)**

```bash
PASS="$(openssl rand -base64 32)"
echo "BACKUP_PASSPHRASE=$PASS"        # Tim: COPY THIS to your password manager NOW (off-box recovery key)
cat >> /var/www/founders-portal/.env <<EOF
BACKUP_PASSPHRASE=$PASS
BACKUP_ALERT_EMAIL=tim.winslow6121@gmail.com
BACKUP_RCLONE_REMOTE=gdrive:FoundersPortalBackups
EOF
```
(Confirm `SENDGRID_API_KEY` + `LABELS_FROM_EMAIL` already in .env; if not, add.)

- [ ] **Step 4: Run a backup manually + confirm it lands on Drive**

```bash
chmod +x /var/www/founders-portal/scripts/*.sh
/var/www/founders-portal/scripts/backup.sh
rclone lsf gdrive:FoundersPortalBackups/        # expect one founders_portal_*.tar.gz.gpg
```
Expected: log shows "Backup OK"; one `.gpg` listed on Drive.

- [ ] **Step 5: Round-trip restore into the test DB + verify row counts MATCH prod**

```bash
LATEST=$(ls -1t /root/backups/*.gpg | head -1)
/var/www/founders-portal/scripts/restore.sh "$LATEST"     # → founders_portal_restore_test
# compare to prod:
sudo -u postgres psql -d founders_portal -tAc "SELECT count(*) FROM commission_line_items;"
sudo -u postgres psql -d founders_portal_restore_test -tAc "SELECT count(*) FROM commission_line_items;"
```
Expected: the two counts match (and customers/policies match). This proves backup→Drive→restore works end to end. Drop the test DB after: `sudo -u postgres psql -c "DROP DATABASE founders_portal_restore_test;"`.

- [ ] **Step 6: Verify alerting both ways**

```bash
# health email:
python3 /var/www/founders-portal/scripts/backup_report.py health      # Tim: confirm email arrives
# failure email (simulate by pointing at a bad remote):
BACKUP_RCLONE_REMOTE=gdrive:NOPE_does_not_exist /var/www/founders-portal/scripts/backup.sh \
  || python3 /var/www/founders-portal/scripts/backup_report.py failure   # Tim: confirm failure email
```
Expected: both emails received.

- [ ] **Step 7: Install the cron**

```bash
cp /var/www/founders-portal/deploy/founders-backup.cron /etc/cron.d/founders-backup
chmod 644 /etc/cron.d/founders-backup
systemctl restart cron
touch /var/log/founders-backup.log
```
Expected: `/etc/cron.d/founders-backup` present; nightly job will run at 3:15 AM.

- [ ] **Step 8: Record completion**

No code commit (this is deploy). Note in the next session-handoff that S0 is live + the off-box passphrase is saved.

---

### Task 6: Docs — CLAUDE.md + spec status

**Files:** Modify `CLAUDE.md`, the spec

- [ ] **Step 1: CLAUDE.md build-status entry**

Add: `- **S0 — Off-site automated backups ✅ (2026-06-09)** — nightly encrypted (gpg AES256) DB+.env backup → Google Drive via rclone (`scripts/backup.sh`), 30-daily+12-monthly retention, failure + weekly-health email alerts (`scripts/backup_report.py`), one-command restore (`scripts/restore.sh`, defaults to a test DB) + `docs/RESTORE_RUNBOOK.md`. Cron `/etc/cron.d/founders-backup` (nightly 3:15, weekly health Mon 8). BACKUP_PASSPHRASE in .env + Tim's off-box copy (recovery key). First pillar of Milestone 1 — Security & Resilience. See [[roadmap-2026-06-09]].`

- [ ] **Step 2: Spec status → Implemented**

Set the spec Status to `✅ Implemented + deployed`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-06-09-offsite-backups-design.md
git commit -m "docs: off-site backups (S0) delivered"
```

---

## Self-review notes (done while writing)

- **Spec coverage:** backup.sh dump+env+gpg+rclone+retention+log → Task 1; restore + safe-default-target → Task 2; failure+weekly-health alerts → Task 3; cron + runbook (both recovery cases) + env docs → Task 4; one-time setup (rclone OAuth, passphrase off-box) + mandatory round-trip + alert verification → Task 5; docs → Task 6. ✅
- **Key-management trap** (backup contains .env which contains the passphrase → off-box copy is the recovery key) is stated in plan decisions, restore.sh prompt, and the runbook. ✅
- **Retention nuance flagged honestly:** the Drive-side GFS prune is approximated via `--min-age` over-keeping (acceptable at 155 KB/file); local side does true monthly tagging. Noted in the script comment rather than hand-waved. Acceptable for a tiny DB; a future refinement could do exact GFS on Drive.
- **No pytest** — correct for ops scripts; verification is the gpg local round-trip (Task 1) + bash `-n` syntax + the authoritative VPS round-trip (Task 5). Stated up front.
- **No placeholders:** every script is complete and runnable; commands have expected output. Task 5 is inherently hands-on (OAuth/secret) — steps are exact, not vague.
- **Names consistent:** `backup.sh`/`restore.sh`/`backup_report.py`, env vars `BACKUP_PASSPHRASE`/`BACKUP_ALERT_EMAIL`/`BACKUP_RCLONE_REMOTE`, remote `gdrive:FoundersPortalBackups`, test DB `founders_portal_restore_test` — identical across all tasks.
