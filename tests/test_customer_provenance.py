"""
tests/test_customer_provenance.py

Tests for the customer field-provenance engine: precedence, human writes, conflict
lifecycle, round-trip. SQLite in-memory via conftest fixtures. Mirrors
tests/test_plan_provenance.py.
"""
from datetime import date


def test_provenance_columns_exist(db_session, app, agency):
    from app.extensions import db
    from app.models import Customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
                     field_provenance=None, has_unresolved_conflicts=False)
        db.session.add(c)
        db.session.commit()
        assert c.field_provenance is None
        assert c.has_unresolved_conflicts is False
