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


def test_preferred_name_column_exists_and_defaults_null(ctx):
    c = Customer(agency_id=ctx, first_name="Donald", last_name="Horstmann")
    db.session.add(c); db.session.commit()
    assert c.preferred_name is None
    c.preferred_name = "Craig"
    db.session.commit()
    assert c.preferred_name == "Craig"
    assert c.first_name == "Donald"   # legal name unchanged


def test_address_as_prefers_goes_by_then_legal_first(ctx):
    from app.names import address_as
    c = Customer(agency_id=ctx, first_name="Donald", last_name="Horstmann")
    db.session.add(c); db.session.commit()
    assert address_as(c) == "Donald"          # no preferred set -> legal first
    c.preferred_name = "Craig"; db.session.commit()
    assert address_as(c) == "Craig"           # preferred wins for greetings


def test_preferred_name_is_a_provenance_editable_field():
    from app.customer_provenance import PROVENANCE_FIELDS
    assert "preferred_name" in PROVENANCE_FIELDS
