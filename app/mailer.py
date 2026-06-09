"""
app/mailer.py

Minimal SendGrid sender, factored from the labels.py usage so multiple features
(birthday labels, recap publish notifications) share one path. Returns True on
send, False when not configured (never raises into request flow).
"""
from flask import current_app
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail


def send_email(to_email, subject, text, html=None) -> bool:
    """Send a plain (and optionally HTML) email. Returns False if SendGrid isn't
    configured or the send fails — callers decide whether that's fatal."""
    api_key = current_app.config.get("SENDGRID_API_KEY")
    from_email = current_app.config.get("LABELS_FROM_EMAIL") or current_app.config.get("MAIL_FROM")
    if not api_key or not from_email or not to_email:
        return False
    message = Mail(from_email=from_email, to_emails=to_email,
                   subject=subject, plain_text_content=text,
                   html_content=html or None)
    try:
        SendGridAPIClient(api_key).send(message)
        return True
    except Exception as e:
        current_app.logger.warning(f"send_email failed to {to_email}: {e}")
        return False
