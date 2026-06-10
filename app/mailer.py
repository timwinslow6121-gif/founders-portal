"""
app/mailer.py

Single email path for the whole portal (transactional / low-volume only):
backup alerts, recap publish-notifications, birthday-label PDFs. Uses Brevo's
transactional HTTP API (https://api.brevo.com/v3/smtp/email) via `requests`
(already a dependency — no SDK needed). Returns True on send, False when not
configured or on failure (never raises into a request/flow).

Provider is intentionally behind this ONE function so a future provider swap is
a single-file change. (Migrated off SendGrid 2026-06-09 after its free tier
lapsed — "Maximum credits exceeded".)

NOT for bulk customer email blasts (plan updates to 100+ recipients) — that is a
separate future feature needing deliverability + HIPAA/BAA handling.

Config (Flask app.config, from env):
  BREVO_API_KEY  — Brevo transactional API key
  MAIL_FROM      — verified sender address (e.g. admin@foundersinsuranceagency.com)
  MAIL_FROM_NAME — optional display name (default "Founders Insurance Agency")
"""
import base64
import requests
from flask import current_app

BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"


def send_email(to_email, subject, text, html=None, attachment=None) -> bool:
    """Send a transactional email via Brevo. Returns False if not configured or
    the send fails — callers decide whether that's fatal.

    attachment (optional): dict {"content": bytes, "name": str} — base64-encoded
    here for the Brevo API (used by birthday labels for the PDF).
    """
    api_key = current_app.config.get("BREVO_API_KEY")
    from_email = (current_app.config.get("MAIL_FROM")
                  or current_app.config.get("LABELS_FROM_EMAIL"))
    from_name = current_app.config.get("MAIL_FROM_NAME") or "Founders Insurance Agency"
    if not api_key or not from_email or not to_email:
        return False

    payload = {
        "sender": {"email": from_email, "name": from_name},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": text,
    }
    if html:
        payload["htmlContent"] = html
    if attachment and attachment.get("content") is not None:
        payload["attachment"] = [{
            "content": base64.b64encode(attachment["content"]).decode(),
            "name": attachment.get("name", "attachment"),
        }]

    try:
        resp = requests.post(
            BREVO_ENDPOINT,
            json=payload,
            headers={"api-key": api_key, "accept": "application/json",
                     "content-type": "application/json"},
            timeout=20,
        )
        if resp.status_code in (200, 201, 202):
            return True
        current_app.logger.warning(
            f"send_email to {to_email} failed: HTTP {resp.status_code} {resp.text[:300]}")
        return False
    except Exception as e:
        current_app.logger.warning(f"send_email to {to_email} errored: {e}")
        return False
