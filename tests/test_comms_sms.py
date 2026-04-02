"""
tests/test_comms_sms.py

Stub tests for SMS send/blast functionality and template management (SC-5).
Will be implemented in Plan 05 when app/comms/sms.py and
app/comms/templates_admin.py are built.
"""

import pytest


def test_sms_blocked_when_no_consent(app, db_session, customer, agent_user):
    pytest.skip("requires comms.sms module — implement in Plan 05")


def test_only_approved_templates_visible_to_agent(app, db_session, agency):
    pytest.skip("requires comms.templates_admin module — implement in Plan 05")


def test_sms_send_creates_customer_note(app, db_session, customer, agent_user):
    pytest.skip("requires comms.sms module — implement in Plan 05")
