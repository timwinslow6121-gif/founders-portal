"""
tests/test_comms_webhooks.py

Stub tests for Quo/Twilio/Calendly webhook handlers.
Requirements covered: SC-1 (Quo call logging), SC-2 (unmatched call),
SC-3 (Quo SMS logging), SC-6 (idempotency), WEBH-01, WEBH-02.

Will be implemented in Plan 03 (Quo) and Plan 04 (Calendly) when
the comms blueprint webhook handlers are built.
"""

import pytest


def test_quo_invalid_hmac_returns_403(client):
    pytest.skip("requires comms blueprint — implement in Plan 03")


def test_quo_duplicate_idempotency(client, db_session):
    pytest.skip("requires comms blueprint — implement in Plan 03")


def test_quo_call_completed_creates_note(client, db_session, customer):
    pytest.skip("requires comms blueprint — implement in Plan 03")


def test_quo_missed_call_creates_unmatched(client, db_session):
    pytest.skip("requires comms blueprint — implement in Plan 03")


def test_quo_sms_received_creates_note(client, db_session, customer):
    pytest.skip("requires comms blueprint — implement in Plan 03")


def test_calendly_booking_creates_note(client, db_session, customer, agent_user):
    pytest.skip("requires comms blueprint — implement in Plan 04")


def test_calendly_unmatched_booking(client, db_session):
    pytest.skip("requires comms blueprint — implement in Plan 04")


def test_unknown_number_creates_unmatched_call(client, db_session):
    pytest.skip("requires comms blueprint — implement in Plan 03")
