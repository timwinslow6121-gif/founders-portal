import pytest
from app.extensions import db
from app.models import Customer, Agency


@pytest.fixture
def ctx(db_session, app, agency):
    """Fixture that yields the agency_id for use in tests."""
    return agency.id


def test_full_name_synced_from_parts_on_insert(ctx, db_session, app):
    with app.app_context():
        c = Customer(agency_id=ctx, first_name="John", last_name="Connelly")
        db.session.add(c); db.session.commit()
        assert c.full_name == "John Connelly"


def test_full_name_resynced_when_human_edits_first_name(ctx, db_session, app):
    with app.app_context():
        c = Customer(agency_id=ctx, first_name="Jon", last_name="Smith")
        db.session.add(c); db.session.commit()
        assert c.full_name == "Jon Smith"
        c.first_name = "John"            # human corrects a carrier typo
        db.session.commit()
        assert c.full_name == "John Smith"   # event resynced, edit NOT blocked


def test_blank_first_name_keeps_raw_full_name(ctx, db_session, app):
    with app.app_context():
        # commission stub: name only in full_name, blank first/last
        c = Customer(agency_id=ctx, first_name="", last_name="", full_name="CONNELLY, JOHN")
        db.session.add(c); db.session.commit()
        assert c.full_name == "CONNELLY, JOHN"   # event did NOT clobber it to " "
