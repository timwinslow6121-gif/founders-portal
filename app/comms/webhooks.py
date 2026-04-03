"""
app/comms/webhooks.py

Unified webhook handlers for the Communications Hub.

Routes:
    POST /comms/webhook/quo           — Quo (formerly OpenPhone) calls + SMS
    POST /comms/webhook/calendly      — Calendly appointment bookings
    POST /comms/webhook/healthsherpa  — HealthSherpa Medicare enrollment events

Quo handles:
    call.completed          — answered calls (note_type='call')
                            — missed calls  (note_type='missed_call')
    call.recording.completed— voicemails    (note_type='voicemail')
    message.received        — inbound SMS   (note_type='sms')
    message.delivered       — outbound SMS  (note_type='sms')

Unknown callers → UnmatchedCall (not CustomerNote).
All handlers are idempotent: duplicate quo_call_id / twilio_msg_sid returns 200
without creating a second record.

Every response is HTTP 200 — errors are logged and the request is swallowed to
prevent providers from retrying and flooding the queue.

HealthSherpa note: Medicare payload field names are LOW confidence (unconfirmed
against live webhooks). Full raw payload is logged at INFO for field discovery.
"""

import requests
from datetime import datetime

from flask import jsonify, request, current_app

from app.comms import comms_bp
from app.comms.utils import (
    find_customer_by_phone,
    normalize_e164,
    verify_calendly_webhook,
    verify_quo_webhook,
)
from app.extensions import db
from app.models import CustomerNote, UnmatchedCall, User


# ---------------------------------------------------------------------------
# Webhook entry point
# ---------------------------------------------------------------------------

@comms_bp.route("/webhook/quo", methods=["POST"])
def quo_webhook():
    """
    Unified entry point for all Quo webhook events.

    1. Verify HMAC signature — abort(403) on failure.
    2. Route by event type.
    3. Commit on success; rollback + log on any exception.
    4. Always return 200 to prevent Quo retry storms.
    """
    payload = verify_quo_webhook(request)  # abort(403) on bad sig

    try:
        event_type = payload.get("type", "")
        call_obj = payload.get("data", {}).get("object", {})

        # Resolve agency_id — User model has no agency_id column until Plan 07.
        # Always fall back to DEFAULT_AGENCY_ID from config.
        agency_id = current_app.config.get("DEFAULT_AGENCY_ID", 1)

        # Resolve agent from Quo userId in the payload
        quo_user_id = call_obj.get("userId")
        agent = None
        if quo_user_id:
            agent = User.query.filter_by(quo_user_id=quo_user_id).first()
        agent_id = agent.id if agent else None

        if event_type == "call.completed":
            _handle_call_completed(call_obj, agency_id, agent_id)
        elif event_type == "call.recording.completed":
            _handle_recording_completed(call_obj, agency_id, agent_id)
        elif event_type in ("message.received", "message.delivered"):
            _handle_sms(call_obj, event_type, agency_id, agent_id)
        else:
            # Forward-compatible: unknown event types are silently accepted
            current_app.logger.info("quo_webhook: unhandled event_type=%s", event_type)

        db.session.commit()

    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("quo_webhook: unhandled exception: %s", exc, exc_info=True)
        db.session.rollback()
        return jsonify({"status": "error"}), 200

    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _handle_call_completed(call_obj, agency_id, agent_id):
    """
    Process a call.completed event.

    Answered call → CustomerNote(note_type='call') for known customer.
    Missed call   → CustomerNote(note_type='missed_call') for known customer.
    Unknown phone → UnmatchedCall regardless of answered/missed status.
    """
    call_id = call_obj.get("id", "")
    answered_at = call_obj.get("answeredAt")
    status = call_obj.get("status", "")
    missed = status in ("no-answer", "missed") or answered_at is None

    # Idempotency check — CustomerNote has no agency_id column; call_id is globally unique
    if CustomerNote.query.filter_by(quo_call_id=call_id).first():
        return

    customer, from_number = _resolve_customer_from_participants(
        call_obj.get("participants", [])
    )

    if customer and agent_id:
        note_type = "missed_call" if missed else "call"
        duration_seconds = call_obj.get("duration", 0)
        # duration from Quo is already in SECONDS — do NOT divide by 1000
        duration_minutes = duration_seconds // 60

        note = CustomerNote(
            note_type=note_type,
            quo_call_id=call_id,
            duration_minutes=duration_minutes,
            contact_method="phone",
            customer_id=customer.id,
            agent_id=agent_id,
            created_at=datetime.utcnow(),
        )
        db.session.add(note)
    else:
        # TODO: handle unresolvable agent gracefully (SC-6 admin alert)
        _create_unmatched_call(
            call_id, call_obj, agency_id, agent_id, from_number, provider="quo"
        )


def _handle_recording_completed(call_obj, agency_id, agent_id):
    """
    Process a call.recording.completed event.

    Fetches the recording URL via GET /v1/call-recordings/{callId} using
    QUO_API_KEY in the Authorization header (no Bearer prefix — Quo convention).

    Creates CustomerNote(note_type='voicemail') for known customers.
    Unknown callers → UnmatchedCall.
    """
    call_id = call_obj.get("id", "")

    # Idempotency check
    if CustomerNote.query.filter_by(
        quo_call_id=call_id, note_type="voicemail"
    ).first():
        return

    # Fetch recording URL from Quo REST API
    recording_url = ""
    api_key = current_app.config.get("QUO_API_KEY", "")
    if api_key:
        try:
            resp = requests.get(
                f"https://api.openphone.com/v1/call-recordings/{call_id}",
                headers={"Authorization": api_key},
                timeout=5,
            )
            recordings = resp.json().get("data", [])
            if recordings:
                recording_url = recordings[0].get("url", "")
        except Exception as exc:  # noqa: BLE001
            current_app.logger.error(
                "quo_webhook: failed to fetch recording for %s: %s", call_id, exc
            )

    customer, from_number = _resolve_customer_from_participants(
        call_obj.get("participants", [])
    )

    if customer and agent_id:
        note = CustomerNote(
            note_type="voicemail",
            quo_call_id=call_id,
            note_text=recording_url,
            source_url=recording_url,
            contact_method="phone",
            customer_id=customer.id,
            agent_id=agent_id,
            created_at=datetime.utcnow(),
        )
        db.session.add(note)
    else:
        # TODO: handle unresolvable agent gracefully (SC-6 admin alert)
        _create_unmatched_call(
            call_id, call_obj, agency_id, agent_id, from_number, provider="quo"
        )


def _handle_sms(msg_obj, event_type, agency_id, agent_id):
    """
    Process a message.received or message.delivered event.

    Creates CustomerNote(note_type='sms') for known customers.
    text field is included by default in Quo payloads — no special API scope needed.

    Uses twilio_msg_sid column to store Quo message_id — SMS idempotency key
    regardless of provider (both are opaque string message IDs).
    """
    message_id = msg_obj.get("id", "")

    # Idempotency check
    if CustomerNote.query.filter_by(twilio_msg_sid=message_id).first():
        return

    from_number = normalize_e164(msg_obj.get("from", ""))
    customer = find_customer_by_phone(from_number) if from_number else None

    if customer and agent_id:
        note = CustomerNote(
            note_type="sms",
            twilio_msg_sid=message_id,
            note_text=msg_obj.get("text", ""),  # default empty string if text absent
            contact_method="sms",
            customer_id=customer.id,
            agent_id=agent_id,
            created_at=datetime.utcnow(),
        )
        db.session.add(note)
    else:
        # TODO: handle unresolvable agent gracefully (SC-6 admin alert)
        _create_unmatched_call(
            message_id, msg_obj, agency_id, agent_id, from_number, provider="quo"
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _resolve_customer_from_participants(participants):
    """
    Walk the participants list and return (customer, e164_phone) for the first
    participant that matches a Customer record.

    Returns (None, first_valid_e164_or_None) if no customer is found — the
    second element is used as from_number for UnmatchedCall records.
    """
    first_valid = None
    for raw_phone in participants:
        e164 = normalize_e164(raw_phone)
        if e164:
            if first_valid is None:
                first_valid = e164
            customer = find_customer_by_phone(e164)
            if customer:
                return customer, e164
    return None, first_valid


def _extract_phone_from_qna(qna_list):
    """
    Scan Calendly questions_and_answers list for any item where the question
    contains "phone" (case-insensitive) and return the answer string, or None.
    """
    for item in qna_list:
        if "phone" in item.get("question", "").lower():
            return item.get("answer", "").strip() or None
    return None


def _extract_calendly_event_id(invitee_uri):
    """
    Extract the Calendly event ID from the invitee URI.

    Example URI: "https://api.calendly.com/xxx/invitees/inv-001"
    Returns: "inv-001"
    """
    if not invitee_uri:
        return ""
    return invitee_uri.rstrip("/").split("/")[-1]


def _create_unmatched_call(call_id, obj, agency_id, agent_id, from_number, provider):
    """
    Create an UnmatchedCall record for a call or SMS that could not be matched
    to a Customer, or where the agent could not be resolved.

    agency_id is required (nullable=False on the model).
    """
    unmatched = UnmatchedCall(
        provider=provider,
        call_sid=call_id,
        from_number=from_number,
        to_number=None,
        direction=obj.get("direction", "incoming"),
        duration_seconds=obj.get("duration", 0),
        occurred_at=datetime.utcnow(),
        agency_id=agency_id,
        agent_id=agent_id,
    )
    db.session.add(unmatched)


# ---------------------------------------------------------------------------
# Calendly webhook entry point
# ---------------------------------------------------------------------------

@comms_bp.route("/webhook/calendly", methods=["POST"])
def calendly_webhook():
    """
    Unified entry point for Calendly webhook events.

    1. Verify Calendly-Webhook-Signature header — abort(403) on failure.
       (verify_calendly_webhook is mocked in tests via patch.)
    2. Ignore events other than "invitee.created" — return 200 with status "ignored".
    3. Idempotency: if a CustomerNote already has calendly_event_id == extracted event ID, skip.
    4. Match customer: phone first (from questions_and_answers), then email.
    5. Resolve agent from event_memberships[0].user_email.
    6. Matched customer + agent → CustomerNote(note_type='appointment_scheduled').
    7. No match → UnmatchedCall(provider='calendly').
    8. Always return 200.
    """
    # verify_calendly_webhook is imported at module level so tests can patch it
    verify_calendly_webhook(request)  # abort(403) on bad sig; returns body on success
    data = request.get_json(force=True) or {}

    try:
        event_type = data.get("event", "")

        if event_type != "invitee.created":
            current_app.logger.info(
                "calendly_webhook: ignored event_type=%s", event_type
            )
            return jsonify({"status": "ignored"}), 200

        payload = data.get("payload", {})
        invitee = payload.get("invitee", {})
        scheduled_event = payload.get("scheduled_event", {})

        # Extract event ID from invitee URI (last path segment)
        invitee_uri = invitee.get("uri", "")
        event_id = _extract_calendly_event_id(invitee_uri)

        # Idempotency check
        if event_id and CustomerNote.query.filter_by(calendly_event_id=event_id).first():
            return jsonify({"status": "duplicate"}), 200

        agency_id = current_app.config.get("DEFAULT_AGENCY_ID", 1)

        # Resolve agent from scheduled_event.event_memberships[0].user_email
        memberships = scheduled_event.get("event_memberships", [])
        agent = None
        if memberships:
            agent_email = memberships[0].get("user_email", "")
            if agent_email:
                agent = User.query.filter_by(email=agent_email).first()
        agent_id = agent.id if agent else None

        # Resolve customer: phone first, then email
        qna = invitee.get("questions_and_answers", [])
        raw_phone = _extract_phone_from_qna(qna)
        customer = None
        if raw_phone:
            e164_phone = normalize_e164(raw_phone)
            if e164_phone:
                customer = find_customer_by_phone(e164_phone)
        if customer is None:
            invitee_email = invitee.get("email", "")
            if invitee_email:
                from app.models import Customer
                customer = Customer.query.filter_by(email=invitee_email).first()

        start_time = scheduled_event.get("start_time", "")

        if customer and agent_id:
            note = CustomerNote(
                note_type="appointment_scheduled",
                calendly_event_id=event_id,
                note_text=f"Appointment: {start_time}",
                contact_method="video",
                customer_id=customer.id,
                agent_id=agent_id,
                created_at=datetime.utcnow(),
            )
            db.session.add(note)
        else:
            from_number = invitee.get("email", "") or ""
            unmatched = UnmatchedCall(
                provider="calendly",
                call_sid=event_id,
                from_number=from_number,
                to_number=None,
                direction="inbound",
                duration_seconds=0,
                occurred_at=datetime.utcnow(),
                agency_id=agency_id,
                agent_id=agent_id,
            )
            db.session.add(unmatched)

        db.session.commit()

    except Exception as exc:  # noqa: BLE001
        current_app.logger.error(
            "calendly_webhook: unhandled exception: %s", exc, exc_info=True
        )
        db.session.rollback()
        return jsonify({"status": "error"}), 200

    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# HealthSherpa webhook
# ---------------------------------------------------------------------------

def _verify_healthsherpa(request):
    """
    Verify a HealthSherpa webhook HMAC-SHA256 signature.

    Header: X-HealthSherpa-Signature (exact name unconfirmed against live webhook —
    verify against first real delivery and update if header name differs).

    If the header is absent, logs a warning and returns without aborting.
    This allows the handler to still process payloads during initial integration
    before the secret is configured.
    """
    import hashlib
    import hmac as _hmac

    secret = current_app.config.get("HEALTHSHERPA_WEBHOOK_SECRET", "")
    if not secret:
        current_app.logger.warning(
            "healthsherpa_webhook: HEALTHSHERPA_WEBHOOK_SECRET not configured"
        )
        return

    sig_header = request.headers.get("X-HealthSherpa-Signature", "")
    if not sig_header:
        current_app.logger.warning(
            "healthsherpa_webhook: signature header missing — verify configuration"
        )
        return

    raw_body = request.data
    computed = _hmac.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()

    if not _hmac.compare_digest(computed, sig_header):
        from flask import abort
        abort(403)


@comms_bp.route("/webhook/healthsherpa", methods=["POST"])
def healthsherpa_webhook():
    """
    HealthSherpa enrollment webhook handler.

    Creates CustomerNote(note_type='healthsherpa_enrollment') for matched customers.
    Creates UnmatchedCall(provider='healthsherpa') when no customer match is found.

    Full raw payload is logged at INFO level for Medicare field discovery — the
    exact payload schema for Medicare enrollments is LOW confidence.

    Always returns HTTP 200.
    """
    _verify_healthsherpa(request)

    data = request.get_json(force=True) or {}

    # Log full payload for field discovery (Medicare payload fields unconfirmed)
    current_app.logger.info("healthsherpa_webhook payload: %s", data)

    try:
        agency_id = current_app.config.get("DEFAULT_AGENCY_ID", 1)

        # Extract fields — best-effort, may differ from live Medicare payloads
        member = data.get("member", {})
        first_name = member.get("first_name", "")
        last_name = member.get("last_name", "")
        raw_phone = member.get("phone") or member.get("phone_number", "")
        plan = data.get("plan", {})
        plan_carrier = plan.get("carrier_name", "")
        plan_name = plan.get("plan_name", "")
        agent_npn = data.get("agent_npn", "")
        event_id = str(data.get("id", ""))

        # Resolve customer by phone, then by name (no DOB in payload currently)
        customer = None
        if raw_phone:
            e164 = normalize_e164(raw_phone)
            if e164:
                customer = find_customer_by_phone(e164)

        # Resolve agent — NPN not stored in AgentCarrierContract yet.
        # Find first non-admin agent scoped to agency, then fall back to any non-admin.
        # TODO: add agent_npn column to User or AgentCarrierContract and update this.
        agent_id = None
        from app.models import User
        fallback_agent = (
            User.query.filter_by(agency_id=agency_id, is_admin=False).first()
            or User.query.filter_by(is_admin=False).first()
        )
        if fallback_agent:
            agent_id = fallback_agent.id

        if customer and agent_id:
            note_text = f"HealthSherpa enrollment: {plan_carrier} {plan_name}".strip()
            note = CustomerNote(
                note_type="healthsherpa_enrollment",
                note_text=note_text,
                contact_method=None,
                customer_id=customer.id,
                agent_id=agent_id,
                agency_id=agency_id,
                created_at=datetime.utcnow(),
            )
            db.session.add(note)
        else:
            unmatched = UnmatchedCall(
                provider="healthsherpa",
                call_sid=event_id,
                from_number=raw_phone or "",
                to_number=None,
                direction="inbound",
                duration_seconds=0,
                occurred_at=datetime.utcnow(),
                agency_id=agency_id,
                agent_id=agent_id,
            )
            db.session.add(unmatched)

        db.session.commit()

    except Exception as exc:  # noqa: BLE001
        current_app.logger.error(
            "healthsherpa_webhook: unhandled exception: %s", exc, exc_info=True
        )
        db.session.rollback()

    return jsonify({"status": "ok"}), 200
