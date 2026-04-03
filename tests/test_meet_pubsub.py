"""
tests/test_meet_pubsub.py

Unit tests for the Google Meet Pub/Sub transcript subscriber callback.

Approach: mock get_transcript_entries and resolve_customer_from_transcript
so tests run without Google Cloud credentials or a live Meet API.
"""

import json
from unittest.mock import MagicMock, patch

import pytest


def make_mock_message(data_dict):
    """Return a mock Pub/Sub message with data encoded as JSON bytes."""
    msg = MagicMock()
    msg.data = json.dumps(data_dict).encode()
    return msg


TRANSCRIPT_DATA = {"transcript": {"name": "conferenceRecords/CR-1/transcripts/TR-1"}}

MOCK_ENTRIES = {
    "transcriptEntries": [
        {"participantName": "John Doe", "text": "I have questions about my plan."},
        {"participantName": "Agent", "text": "Let me help you."},
    ]
}


def test_transcript_event_creates_meeting_summary_note(app, db_session, customer, agent_user):
    """
    process_transcript_event with a matched customer must create
    CustomerNote(note_type='meeting_summary') and ack the message.
    """
    mock_msg = make_mock_message(TRANSCRIPT_DATA)

    with app.app_context():
        from app.models import Customer, User
        cust = Customer.query.filter_by(first_name="John").first()
        agent = User.query.filter_by(email="agent@test.com").first()

        with patch("app.scripts.meet_subscriber.get_transcript_entries", return_value=MOCK_ENTRIES), \
             patch("app.scripts.meet_subscriber.resolve_customer_from_transcript", return_value=(cust, agent)):
            from app.scripts.meet_subscriber import process_transcript_event
            process_transcript_event(mock_msg)

        from app.models import CustomerNote
        note = CustomerNote.query.filter_by(note_type="meeting_summary").first()
        assert note is not None
        assert "John Doe" in note.note_text
        assert note.contact_method == "video"
        assert note.customer_id == cust.id
        assert note.agent_id == agent.id

    mock_msg.ack.assert_called_once()


def test_transcript_no_match_creates_unmatched(app, db_session, agent_user):
    """
    process_transcript_event with no customer match must create
    UnmatchedCall(provider='google_meet') and still ack the message.
    """
    mock_msg = make_mock_message(TRANSCRIPT_DATA)

    with app.app_context():
        with patch("app.scripts.meet_subscriber.get_transcript_entries", return_value={"transcriptEntries": []}), \
             patch("app.scripts.meet_subscriber.resolve_customer_from_transcript", return_value=(None, None)):
            from app.scripts.meet_subscriber import process_transcript_event
            process_transcript_event(mock_msg)

        from app.models import UnmatchedCall
        uc = UnmatchedCall.query.filter_by(provider="google_meet").first()
        assert uc is not None

    mock_msg.ack.assert_called_once()


def test_transcript_event_nacks_on_exception(app, db_session):
    """
    If get_transcript_entries raises an exception, message.nack() must be
    called (not ack) so Pub/Sub retries delivery.
    """
    mock_msg = make_mock_message(TRANSCRIPT_DATA)

    with app.app_context():
        with patch("app.scripts.meet_subscriber.get_transcript_entries", side_effect=RuntimeError("API down")):
            from app.scripts.meet_subscriber import process_transcript_event
            process_transcript_event(mock_msg)

    mock_msg.nack.assert_called_once()
    mock_msg.ack.assert_not_called()
