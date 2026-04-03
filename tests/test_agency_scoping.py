"""
tests/test_agency_scoping.py

Multi-tenant agency scoping tests (SC-7).
Verifies that Customer records from Agency A are invisible to Agency B queries.
These are DB-level tests — no HTTP routes, no current_user mocking required.
"""

import pytest


def test_customer_query_scoped_to_agency(app, db_session):
    """Customers from Agency A are invisible to Agency B queries."""
    from app.models import Agency, Customer

    agency_a = Agency(name="Agency A")
    agency_b = Agency(name="Agency B")
    db_session.add_all([agency_a, agency_b])
    db_session.flush()

    c_a = Customer(
        first_name="Alice", last_name="A", full_name="Alice A",
        agency_id=agency_a.id,
    )
    c_b = Customer(
        first_name="Bob", last_name="B", full_name="Bob B",
        agency_id=agency_b.id,
    )
    db_session.add_all([c_a, c_b])
    db_session.commit()

    results = Customer.query.filter_by(agency_id=agency_b.id).all()
    assert len(results) == 1
    assert results[0].full_name == "Bob B"


def test_cross_tenant_query_returns_nothing(app, db_session):
    """agency_id filter on non-existent agency returns empty list."""
    from app.models import Customer

    results = Customer.query.filter_by(agency_id=9999).all()
    assert results == []
