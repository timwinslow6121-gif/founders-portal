"""
tests/test_comms_webhooks.py

Unit tests for the Quo (formerly OpenPhone) webhook handler.
Requirements covered: SC-1 (Quo call logging), SC-2 (unmatched call),
SC-6 (Quo SMS logging), WEBH-01 (idempotency).

Approach: unittest.mock.patch bypasses HMAC verification so tests run
without a live Quo signing key.  Each test posts to /comms/webhook/quo
and queries SQLite in-memory DB to verify the correct model was created.
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared payloads
# ---------------------------------------------------------------------------

QUO_CALL_PAYLOAD = {
    "type": "call.completed",
    "data": {
        "object": {
            "id": "test-call-001",
            "userId": "US-test-agent",
            "direction": "incoming",
            "status": "completed",
            "duration": 180,
            "answeredAt": "2024-01-23T16:50:05.000Z",
            "completedAt": "2024-01-23T16:55:05.000Z",
            "participants": ["+17705551234", "+14045559876"],
        }
    },
}

QUO_MISSED_CALL_PAYLOAD = {
    "type": "call.completed",
    "data": {
        "object": {
            "id": "test-call-missed-001",
            "userId": "US-test-agent",
            "direction": "incoming",
            "status": "no-answer",
            "duration": 0,
            "answeredAt": None,
            "completedAt": "2024-01-23T16:50:05.000Z",
            "participants": ["+19995550001", "+14045559876"],
        }
    },
}

QUO_UNKNOWN_CALL_PAYLOAD = {
    "type": "call.completed",
    "data": {
        "object": {
            "id": "test-call-unknown-001",
            "userId": "US-test-agent",
            "direction": "incoming",
            "status": "completed",
            "duration": 60,
            "answeredAt": "2024-01-23T16:50:05.000Z",
            "completedAt": "2024-01-23T16:51:05.000Z",
            "participants": ["+19995550002", "+14045559876"],
        }
    },
}

QUO_RECORDING_PAYLOAD = {
    "type": "call.recording.completed",
    "data": {
        "object": {
            "id": "test-call-002",
            "userId": "US-test-agent",
            "participants": ["+17705551234", "+14045559876"],
        }
    },
}

QUO_SMS_PAYLOAD = {
    "type": "message.received",
    "data": {
        "object": {
            "id": "msg-001",
            "from": "+17705551234",
            "to": ["+14045559876"],
            "direction": "incoming",
            "text": "Hello I need help",
            "userId": "US-test-agent",
        }
    },
}

QUO_SMS_NO_TEXT_PAYLOAD = {
    "type": "message.received",
    "data": {
        "object": {
            "id": "msg-002",
            "from": "+17705551234",
            "to": ["+14045559876"],
            "direction": "incoming",
            "userId": "US-test-agent",
        }
    },
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _post_quo(client, payload):
    """POST a JSON payload to /comms/webhook/quo."""
    return client.post(
        "/comms/webhook/quo",
        data=json.dumps(payload),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_quo_invalid_hmac_returns_403(client):
    """
    POST without a valid openphone-signature header must return 403.
    verify_quo_webhook is NOT mocked here — HMAC check must fire and reject.
    """
    resp = client.post(
        "/comms/webhook/quo",
        data=json.dumps(QUO_CALL_PAYLOAD),
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_quo_call_completed_creates_note(client, db_session, customer, agent_user, app):
    """
    call.completed with answeredAt set and a known customer phone number must
    create CustomerNote(note_type='call').
    """
    with app.app_context():
        from app.models import User
        from app.extensions import db

        # Give the agent a quo_user_id so it can be resolved from the webhook payload
        agent = User.query.filter_by(email="agent@test.com").first()
        agent.quo_user_id = "US-test-agent"
        db.session.commit()

    with patch("app.comms.utils.verify_quo_webhook", return_value=QUO_CALL_PAYLOAD):
        resp = _post_quo(client, QUO_CALL_PAYLOAD)

    assert resp.status_code == 200

    with app.app_context():
        from app.models import CustomerNote
        note = CustomerNote.query.filter_by(quo_call_id="test-call-001").first()
        assert note is not None
        assert note.note_type == "call"


def test_quo_duplicate_idempotency(client, db_session, customer, agent_user, app):
    """
    Posting the same call.completed event twice must create only one CustomerNote.
    Second POST returns 200 but does not insert a duplicate.
    """
    with app.app_context():
        from app.models import User
        from app.extensions import db

        agent = User.query.filter_by(email="agent@test.com").first()
        agent.quo_user_id = "US-test-agent"
        db.session.commit()

    with patch("app.comms.utils.verify_quo_webhook", return_value=QUO_CALL_PAYLOAD):
        resp1 = _post_quo(client, QUO_CALL_PAYLOAD)
        resp2 = _post_quo(client, QUO_CALL_PAYLOAD)

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    with app.app_context():
        from app.models import CustomerNote
        count = CustomerNote.query.filter_by(quo_call_id="test-call-001").count()
        assert count == 1


def test_quo_missed_call_creates_unmatched(client, db_session, app):
    """
    call.completed with status='no-answer' and answeredAt=None for a phone
    number NOT in the Customer table must create an UnmatchedCall.
    No CustomerNote should be created.
    """
    with app.app_context():
        from app.models import User, Agency
        from app.extensions import db

        agency = Agency(name="Test Agency")
        db.session.add(agency)
        db.session.flush()

        agent = User.query.filter_by(email="agent@test.com").first()
        if agent is None:
            agent = User(email="agent@test.com", name="Agent", is_admin=False)
            db.session.add(agent)
            db.session.flush()
        agent.quo_user_id = "US-test-agent"
        db.session.commit()

    with patch("app.comms.utils.verify_quo_webhook", return_value=QUO_MISSED_CALL_PAYLOAD):
        resp = _post_quo(client, QUO_MISSED_CALL_PAYLOAD)

    assert resp.status_code == 200

    with app.app_context():
        from app.models import UnmatchedCall, CustomerNote
        unmatched = UnmatchedCall.query.filter_by(
            call_sid="test-call-missed-001"
        ).first()
        assert unmatched is not None

        note = CustomerNote.query.filter_by(
            quo_call_id="test-call-missed-001"
        ).first()
        assert note is None


def test_quo_unknown_number_creates_unmatched(client, db_session, app):
    """
    call.completed for a phone number not in the Customer table must create
    an UnmatchedCall record.
    """
    with app.app_context():
        from app.models import User, Agency
        from app.extensions import db

        agency = Agency(name="Test Agency 2")
        db.session.add(agency)
        db.session.flush()

        agent = User.query.filter_by(email="agent@test.com").first()
        if agent is None:
            agent = User(email="agent@test.com", name="Agent", is_admin=False)
            db.session.add(agent)
            db.session.flush()
        agent.quo_user_id = "US-test-agent"
        db.session.commit()

    with patch("app.comms.utils.verify_quo_webhook", return_value=QUO_UNKNOWN_CALL_PAYLOAD):
        resp = _post_quo(client, QUO_UNKNOWN_CALL_PAYLOAD)

    assert resp.status_code == 200

    with app.app_context():
        from app.models import UnmatchedCall
        unmatched = UnmatchedCall.query.filter_by(
            call_sid="test-call-unknown-001"
        ).first()
        assert unmatched is not None


def test_quo_recording_completed_creates_voicemail_note(
    client, db_session, customer, agent_user, app
):
    """
    call.recording.completed for a known customer phone must create
    CustomerNote(note_type='voicemail').  The Quo REST API call is mocked.
    """
    with app.app_context():
        from app.models import User
        from app.extensions import db

        agent = User.query.filter_by(email="agent@test.com").first()
        agent.quo_user_id = "US-test-agent"
        db.session.commit()

    mock_recording_resp = MagicMock()
    mock_recording_resp.json.return_value = {
        "data": [{"url": "https://quo.com/recordings/test.mp3"}]
    }

    with patch("app.comms.utils.verify_quo_webhook", return_value=QUO_RECORDING_PAYLOAD), \
         patch("requests.get", return_value=mock_recording_resp):
        resp = _post_quo(client, QUO_RECORDING_PAYLOAD)

    assert resp.status_code == 200

    with app.app_context():
        from app.models import CustomerNote
        note = CustomerNote.query.filter_by(quo_call_id="test-call-002").first()
        assert note is not None
        assert note.note_type == "voicemail"


def test_quo_sms_received_creates_note(client, db_session, customer, agent_user, app):
    """
    message.received for a known customer phone must create
    CustomerNote(note_type='sms') with note_text from data.object.text.
    """
    with app.app_context():
        from app.models import User
        from app.extensions import db

        agent = User.query.filter_by(email="agent@test.com").first()
        agent.quo_user_id = "US-test-agent"
        db.session.commit()

    with patch("app.comms.utils.verify_quo_webhook", return_value=QUO_SMS_PAYLOAD):
        resp = _post_quo(client, QUO_SMS_PAYLOAD)

    assert resp.status_code == 200

    with app.app_context():
        from app.models import CustomerNote
        note = CustomerNote.query.filter_by(twilio_msg_sid="msg-001").first()
        assert note is not None
        assert note.note_type == "sms"
        assert note.note_text == "Hello I need help"


def test_quo_sms_missing_text_creates_note_anyway(
    client, db_session, customer, agent_user, app
):
    """
    message.received without a 'text' field must still create a CustomerNote
    with note_text as empty string — not raise an error.
    """
    with app.app_context():
        from app.models import User
        from app.extensions import db

        agent = User.query.filter_by(email="agent@test.com").first()
        agent.quo_user_id = "US-test-agent"
        db.session.commit()

    with patch("app.comms.utils.verify_quo_webhook", return_value=QUO_SMS_NO_TEXT_PAYLOAD):
        resp = _post_quo(client, QUO_SMS_NO_TEXT_PAYLOAD)

    assert resp.status_code == 200

    with app.app_context():
        from app.models import CustomerNote
        note = CustomerNote.query.filter_by(twilio_msg_sid="msg-002").first()
        assert note is not None
        assert note.note_type == "sms"
        assert note.note_text == ""


# ---------------------------------------------------------------------------
# Calendly stubs (Plan 04) — kept for continuity
# ---------------------------------------------------------------------------

def test_calendly_booking_creates_note(client, db_session, customer, agent_user):
    pytest.skip("requires comms blueprint — implement in Plan 04")


def test_calendly_unmatched_booking(client, db_session):
    pytest.skip("requires comms blueprint — implement in Plan 04")
