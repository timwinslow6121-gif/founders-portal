"""
app/comms/utils.py

Shared utility functions for the Communications Hub blueprint.

Provides:
    normalize_e164           — normalize phone strings to E.164 format
    find_customer_by_phone   — look up Customer by phone_primary or phone_secondary
    verify_quo_webhook       — validate Quo (OpenPhone) HMAC-SHA256 webhook signature
    verify_calendly_webhook  — validate Calendly webhook signature
    verify_retell_webhook    — validate Retell AI webhook signature
"""
import base64
import hashlib
import hmac
import time

import phonenumbers
from flask import abort, current_app

from app.extensions import db


# ---------------------------------------------------------------------------
# Phone utilities
# ---------------------------------------------------------------------------

def normalize_e164(raw_phone: str | None, default_region: str = "US") -> str | None:
    """
    Normalize a phone number string to E.164 format.

    Returns the E.164 string (e.g. '+17705551234') on success, or None if
    the input is falsy, unparseable, or not a valid number.
    """
    if not raw_phone:
        return None
    try:
        parsed = phonenumbers.parse(raw_phone, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    return None


def find_customer_by_phone(phone: str | None, agency_id: int | None = None):
    """
    Return the first Customer whose phone_primary or phone_secondary matches
    the given E.164 phone string, or None if no match found.

    NOTE: agency_id scoping is added in Plan 07 sweep.  The parameter is
    accepted here so callers can pass it without breaking when Plan 07 adds
    the filter, but it is intentionally unused until then.
    """
    if not phone:
        return None
    from app.models import Customer
    return Customer.query.filter(
        db.or_(
            Customer.phone_primary == phone,
            Customer.phone_secondary == phone,
        )
    ).first()


# ---------------------------------------------------------------------------
# Webhook signature verifiers
# ---------------------------------------------------------------------------

def verify_quo_webhook(request):
    """
    Verify a Quo (OpenPhone) HMAC-SHA256 webhook signature.

    Header format:
        openphone-signature: hmac;1;<unix_timestamp_ms>;<base64_digest>

    The signing key stored in QUO_WEBHOOK_SIGNING_KEY is base64-encoded;
    it must be decoded to raw bytes before use.

    Signed payload: <timestamp_bytes> + b"." + <raw_body_bytes>

    Raises HTTP 403 (via abort) on:
        - Missing or malformed header
        - Signature mismatch
        - Event timestamp > 300 seconds old (replay-attack protection)

    Returns the parsed JSON body dict on success.
    Uses stdlib hmac/hashlib/base64 only — NOT PyJWT.
    """
    sig_header = request.headers.get('openphone-signature', '')
    if not sig_header:
        abort(403)

    fields = sig_header.split(';')
    # Expected: fields[0]="hmac", fields[1]="1", fields[2]=timestamp_ms, fields[3]=base64_digest
    if len(fields) < 4 or fields[0] != 'hmac':
        abort(403)

    timestamp = fields[2]
    provided_digest = fields[3]

    raw_body = request.data  # bytes — do NOT call request.json here

    signed_data = timestamp.encode() + b'.' + raw_body

    signing_key_b64 = current_app.config['QUO_WEBHOOK_SIGNING_KEY']
    signing_key_bytes = base64.b64decode(signing_key_b64)

    computed_digest = base64.b64encode(
        hmac.new(signing_key_bytes, signed_data, hashlib.sha256).digest()
    ).decode()

    if not hmac.compare_digest(computed_digest, provided_digest):
        abort(403)

    # Replay protection — reject events older than 5 minutes
    try:
        ts_seconds = int(timestamp) / 1000  # timestamp is in milliseconds
        if abs(time.time() - ts_seconds) > 300:
            abort(403)
    except (ValueError, TypeError):
        abort(403)

    return request.get_json(force=True)


def verify_calendly_webhook(request):
    """
    Verify a Calendly webhook signature.

    Header format:
        Calendly-Webhook-Signature: t=TIMESTAMP,v1=SIGNATURE

    Signed payload: f"{timestamp}.{body}"
    Secret used:    current_app.config['CALENDLY_WEBHOOK_SECRET']

    Raises HTTP 403 on mismatch or event > 300 seconds old.
    Returns the parsed JSON body dict on success.
    Uses stdlib hmac only — NOT PyJWT.
    """
    sig_header = request.headers.get('Calendly-Webhook-Signature', '')
    if not sig_header:
        abort(403)

    # Parse "t=TIMESTAMP,v1=SIGNATURE"
    parts = {}
    for part in sig_header.split(','):
        if '=' in part:
            k, v = part.split('=', 1)
            parts[k.strip()] = v.strip()

    timestamp = parts.get('t', '')
    provided_sig = parts.get('v1', '')
    if not timestamp or not provided_sig:
        abort(403)

    raw_body = request.data.decode('utf-8')
    signed_data = f"{timestamp}.{raw_body}"

    secret = current_app.config.get('CALENDLY_WEBHOOK_SECRET', '')
    computed_sig = hmac.new(
        secret.encode(), signed_data.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_sig, provided_sig):
        abort(403)

    # Replay protection — 5 minute window
    try:
        if abs(time.time() - int(timestamp)) > 300:
            abort(403)
    except (ValueError, TypeError):
        abort(403)

    return request.get_json(force=True)


def verify_retell_webhook(request):
    """
    Verify a Retell AI webhook signature.

    Header:  x-retell-signature
    Secret:  current_app.config['RETELL_WEBHOOK_SECRET']
             (this IS the Retell API key — dual-purpose)

    # Verify against Retell SDK source if signature fails — confidence on
    # base64 step is LOW; the exact encoding step may differ from their SDK.

    Raises HTTP 403 on mismatch.
    Returns the parsed JSON body dict on success.
    Uses stdlib hmac only — NOT PyJWT.
    """
    provided_sig = request.headers.get('x-retell-signature', '')
    if not provided_sig:
        abort(403)

    raw_body = request.data
    secret = current_app.config.get('RETELL_WEBHOOK_SECRET', '')

    computed_digest = base64.b64encode(
        hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    ).decode()

    if not hmac.compare_digest(computed_digest, provided_sig):
        abort(403)

    return request.get_json(force=True)
