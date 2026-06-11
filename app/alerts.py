"""
app/alerts.py — S2 breach alerting: 2 trigger rules + de-duped plain-English
email. The SINGLE place alert rules live. No DB writes. No time-of-day logic
(Founders agents work all hours — off-hours alerting was deliberately removed).

Triggers:
  1. Non-domain / failed login (action in login_failed/login_nondomain).
  2. 429 flood (>= FLOOD_COUNT rate_limit_blocked from one source in FLOOD_WINDOW).
Exports are LOG-ONLY (never alert).
"""
import time
import logging
from collections import defaultdict, deque
from flask import current_app
from app.mailer import send_email

_log = logging.getLogger(__name__)

FLOOD_COUNT = 5
FLOOD_WINDOW = 300
ALERT_THROTTLE_WINDOW = 300

_flood_hits = defaultdict(deque)
_last_alert_at = {}


def _reset_throttle():
    """Test helper — clear in-process state."""
    _flood_hits.clear()
    _last_alert_at.clear()


def _throttled(trigger, source_key):
    now = time.time()
    last = _last_alert_at.get((trigger, source_key), 0)
    if now - last < ALERT_THROTTLE_WINDOW:
        return True
    _last_alert_at[(trigger, source_key)] = now
    return False


def _source_key(row):
    return row.ip_address or (f"user:{row.user_id}" if row.user_id else "unknown")


def maybe_alert(row):
    """Apply the 2 trigger rules; on a match (and not throttled), send email."""
    if row.category == "auth" and row.action in ("login_failed", "login_nondomain"):
        _send("login", row, _compose_login(row))
        return

    if row.category == "security" and row.action == "rate_limit_blocked":
        key = _source_key(row)
        hits = _flood_hits[key]
        now = time.time()
        hits.append(now)
        while hits and now - hits[0] > FLOOD_WINDOW:
            hits.popleft()
        if not hits:
            # Dead source key — drop it so per-IP state doesn't grow unbounded
            # in a long-running worker.
            _flood_hits.pop(key, None)
        if len(hits) >= FLOOD_COUNT:
            _send("flood", row, _compose_flood(row, len(hits)))
        return

    return


def _send(trigger, row, message):
    key = _source_key(row)
    if _throttled(trigger, key):
        return
    subject, text = message
    try:
        to = current_app.config.get("MAIL_FROM") or ""
        if to:
            send_email(to, subject, text)
    except Exception:
        _log.exception("alert email send failed")


def _compose_login(row):
    subject = "🔔 Founders Portal Security Alert — login attempt blocked"
    text = (
        "What happened:  A login attempt was blocked.\n"
        f"Who / where:    {row.detail or 'unknown'} — from IP {row.ip_address or 'unknown'}"
        f" — {row.user_agent or 'unknown device'}.\n"
        f"When:           {row.created_at} UTC.\n"
        "Access granted? NO — the portal blocked it (only @foundersinsuranceagency.com can get in).\n\n"
        "What it means & what to do: An outsider may be probing the login. No action\n"
        "needed — it was already blocked. If you see many of these from the same IP,\n"
        "that IP is worth blocking at the firewall (see the Incident Response Runbook)."
    )
    return subject, text


def _compose_flood(row, count):
    subject = "🔔 Founders Portal Security Alert — rate-limit flood"
    text = (
        "What happened:  One source is hammering the portal (possible bot/attack).\n"
        f"Who / where:    IP {row.ip_address or 'unknown'} — {count}+ blocked requests in a few minutes.\n"
        f"When:           {row.created_at} UTC.\n"
        "Access granted? NO — S1's rate limiter is auto-blocking it.\n\n"
        "What it means & what to do: Automated abuse or a DoS attempt. It's already\n"
        "being blocked. If it persists, block that IP at the firewall (see the\n"
        "Incident Response Runbook)."
    )
    return subject, text
