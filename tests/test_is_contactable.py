"""tests/test_is_contactable.py"""
from datetime import date


def test_a_living_customer_is_contactable(app, agency, db_session):
    from app.models import Customer, is_contactable
    with app.app_context():
        assert is_contactable(Customer(agency_id=agency.id, first_name="A",
                                       last_name="B", full_name="A B"))


def test_a_deceased_customer_is_not_contactable(app, agency, db_session):
    from app.models import Customer, is_contactable
    with app.app_context():
        assert not is_contactable(Customer(
            agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
            deceased_date=date(2026, 4, 30)))


def test_none_is_not_contactable(app, agency, db_session):
    """Defensive: a missing customer must never be treated as mailable."""
    from app.models import is_contactable
    with app.app_context():
        assert not is_contactable(None)
