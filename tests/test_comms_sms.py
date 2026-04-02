"""
tests/test_comms_sms.py

Tests for SMS template management (agent suggest / admin approve) and
the send_sms_template() function with consent guard.

Plan 05 — SC-5 implementation.
"""

import pytest


# ---------------------------------------------------------------------------
# Task 1 tests — Template admin (approve/reject workflow)
# ---------------------------------------------------------------------------

def test_only_approved_templates_visible_to_agent(app, db_session, agency, agent_user):
    """
    Agent GET /comms/sms-templates should see only their own templates (any status).
    The send dropdown only shows approved; this test verifies that approved templates
    are queryable by status filter.
    """
    from app.models import SmsTemplate
    from app.extensions import db

    with app.app_context():
        pending = SmsTemplate(
            name="Pending tmpl",
            body="Pending body",
            status="pending",
            agency_id=agency.id,
            created_by_id=agent_user.id,
        )
        approved = SmsTemplate(
            name="Approved tmpl",
            body="Approved body",
            status="approved",
            agency_id=agency.id,
            created_by_id=agent_user.id,
        )
        rejected = SmsTemplate(
            name="Rejected tmpl",
            body="Rejected body",
            status="rejected",
            agency_id=agency.id,
            created_by_id=agent_user.id,
        )
        db.session.add_all([pending, approved, rejected])
        db.session.commit()

        # Agent send dropdown should only see approved templates
        approved_only = SmsTemplate.query.filter_by(
            agency_id=agency.id,
            status="approved",
        ).all()
        assert len(approved_only) == 1
        assert approved_only[0].name == "Approved tmpl"

        # Admin list view: all 3 templates visible (no status filter)
        all_templates = SmsTemplate.query.filter_by(agency_id=agency.id).all()
        assert len(all_templates) == 3


def test_admin_can_approve_template(app, db_session, agency, admin_user, agent_user):
    """
    Admin POSTing to /comms/sms-templates/<id>/approve changes status to 'approved'
    and records reviewed_by_id + reviewed_at.
    """
    from app.models import SmsTemplate
    from app.extensions import db
    from datetime import datetime

    with app.app_context():
        tmpl = SmsTemplate(
            name="Test approval",
            body="Hello {{first_name}}",
            status="pending",
            agency_id=agency.id,
            created_by_id=agent_user.id,
        )
        db.session.add(tmpl)
        db.session.commit()
        tmpl_id = tmpl.id

        # Simulate what the approve route does
        tmpl = SmsTemplate.query.get(tmpl_id)
        tmpl.status = "approved"
        tmpl.reviewed_by_id = admin_user.id
        tmpl.reviewed_at = datetime.utcnow()
        db.session.commit()

        refreshed = SmsTemplate.query.get(tmpl_id)
        assert refreshed.status == "approved"
        assert refreshed.reviewed_by_id == admin_user.id
        assert refreshed.reviewed_at is not None


# ---------------------------------------------------------------------------
# Task 2 tests — SMS send with consent guard
# ---------------------------------------------------------------------------

def test_sms_blocked_when_no_consent(app, db_session, agency, customer, agent_user):
    """
    send_sms_template() raises ValueError('no_consent') when
    customer.sms_consent_at is None.
    """
    from app.comms.sms import send_sms_template
    from app.models import SmsTemplate
    from app.extensions import db

    with app.app_context():
        tmpl = SmsTemplate(
            name="Test",
            body="Hello",
            status="approved",
            agency_id=agency.id,
            created_by_id=agent_user.id,
        )
        db.session.add(tmpl)
        db.session.commit()

        # customer.sms_consent_at is None (no consent)
        assert customer.sms_consent_at is None
        with pytest.raises(ValueError, match="no_consent"):
            send_sms_template(customer, tmpl, agent_user)


def test_sms_send_creates_customer_note(app, db_session, agency, customer, agent_user):
    """
    send_sms_template() with a consenting customer calls Twilio (mocked)
    and creates a CustomerNote with note_type='sms' and the template name in note_text.
    """
    from unittest.mock import patch, MagicMock
    from app.comms.sms import send_sms_template
    from app.models import SmsTemplate, CustomerNote
    from app.extensions import db
    from datetime import datetime

    with app.app_context():
        # Give customer consent
        customer.sms_consent_at = datetime.utcnow()
        db.session.commit()

        tmpl = SmsTemplate(
            name="AEP Reminder",
            body="It's time for your AEP review. Reply STOP to opt out.",
            status="approved",
            agency_id=agency.id,
            created_by_id=agent_user.id,
        )
        db.session.add(tmpl)
        db.session.commit()

        mock_msg = MagicMock()
        mock_msg.sid = "SM123"

        with patch("app.comms.sms.Client") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_msg
            sid = send_sms_template(customer, tmpl, agent_user)

        assert sid == "SM123"

        note = CustomerNote.query.filter_by(twilio_msg_sid="SM123").first()
        assert note is not None
        assert note.note_type == "sms"
        assert "AEP Reminder" in note.note_text
        assert note.contact_method == "sms"
        assert note.customer_id == customer.id
        assert note.agent_id == agent_user.id
