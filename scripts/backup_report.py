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
