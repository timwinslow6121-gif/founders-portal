import pytest
from datetime import date
from app.extensions import db
from app.models import Agency, User, Customer, Policy


def test_fill_blanks_only(db_session, app):
    """A BOB-captured field fills a blank but never overwrites a non-blank value."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        cust = Customer(agency_id=ag.id, full_name="Jane Doe", first_name="Jane",
                        last_name="Doe", state="SC", primary_agent_id=u.id)  # state already set
        db.session.add(cust); db.session.flush()
        from app.upload import _fill_if_blank
        _fill_if_blank(cust, "state", "NC")     # existing SC → not overwritten
        _fill_if_blank(cust, "city", "Charlotte")  # blank → filled
        assert cust.state == "SC"
        assert cust.city == "Charlotte"
