"""
tests/test_backfill_customer_provenance.py

Tests the backfill seeding logic for the customer provenance engine.
"""
from datetime import date


def test_backfill_manually_edited_seeds_all_as_agent_entered(db_session, app, agency):
    from app.extensions import db
    from app.models import Customer
    from app import customer_provenance as cp
    from scripts.backfill_customer_provenance import seed_customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Mitchell", last_name="Thoma",
                     full_name="Mitchell Thoma", mbi="9ABC", zip_code="28205",
                     email="m@x.com", manually_edited=True, source="bob")
        db.session.add(c); db.session.flush()

        seed_customer(c)
        db.session.flush()

        assert cp.trust_of(c, "mbi") == "agent_entered"
        assert cp.trust_of(c, "zip_code") == "agent_entered"
        assert cp.trust_of(c, "email") == "agent_entered"
        assert cp.get_field(c, "county") is None     # unpopulated -> no provenance


def test_backfill_plain_customer_seeds_carrier_import(db_session, app, agency):
    from app.extensions import db
    from app.models import Customer
    from app import customer_provenance as cp
    from scripts.backfill_customer_provenance import seed_customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
                     zip_code="28202", manually_edited=False, source="bob")
        db.session.add(c); db.session.flush()
        seed_customer(c); db.session.flush()
        assert cp.trust_of(c, "zip_code") == "carrier_import"
        assert cp.get_field(c, "zip_code")["source"] == "bob"


def test_backfill_is_idempotent(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer
    from app import customer_provenance as cp
    from scripts.backfill_customer_provenance import seed_customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
                     zip_code="28202", manually_edited=False, source="bob")
        db.session.add(c); db.session.flush()
        cp.set_human_value(c, "zip_code", "28205", agent_user); db.session.flush()

        seed_customer(c); db.session.flush()
        assert cp.trust_of(c, "zip_code") == "agent_entered"   # untouched by backfill
        assert c.zip_code == "28205"
