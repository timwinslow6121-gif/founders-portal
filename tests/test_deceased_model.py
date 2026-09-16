"""tests/test_deceased_model.py"""
from datetime import date


def test_customer_has_a_deceased_date(app, agency, db_session):
    from app.extensions import db
    from app.models import Customer
    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B",
                     full_name="A B", deceased_date=date(2026, 4, 30))
        db.session.add(c); db.session.commit()
        assert Customer.query.get(c.id).deceased_date == date(2026, 4, 30)


def test_deceased_date_defaults_to_none(app, agency, db_session):
    from app.extensions import db
    from app.models import Customer
    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B")
        db.session.add(c); db.session.commit()
        assert Customer.query.get(c.id).deceased_date is None


def test_policy_keeps_the_carriers_own_term_wording(app, agency, db_session):
    """term_reason_raw holds the carrier's verbatim words; the existing free-text
    term_reason stays for human notes."""
    from app.extensions import db
    from app.models import Policy
    with app.app_context():
        p = Policy(agency_id=agency.id, carrier="UHC", member_id="X1",
                   status="active", term_reason_raw="Death")
        db.session.add(p); db.session.commit()
        assert Policy.query.get(p.id).term_reason_raw == "Death"
