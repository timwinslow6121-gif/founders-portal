from datetime import date
from app.extensions import db
from app.models import Agency, User, Customer, CustomerAorHistory
from app.upload import _close_open_aor_on_term


def test_term_closes_open_interval(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=ag.id, first_name="Jane", last_name="Doe", full_name="Jane Doe", primary_agent_id=u.id)
        db.session.add(c); db.session.flush()
        db.session.add(CustomerAorHistory(agency_id=ag.id, customer_id=c.id, agent_id=u.id,
            carrier="Aetna", plan_name="Aetna Sig PPO", effective_date=date(2024,1,1), end_date=None))
        db.session.commit()
        _close_open_aor_on_term(c, "Aetna", date(2026,5,31))
        h = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="Aetna").first()
        assert h.end_date == date(2026,5,31)


def test_bcbs_open_interval_stays_none(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=ag.id, first_name="Bob", last_name="Smith", full_name="Bob Smith", primary_agent_id=u.id); db.session.add(c); db.session.flush()
        db.session.add(CustomerAorHistory(agency_id=ag.id, customer_id=c.id, agent_id=u.id,
            carrier="BCBS", effective_date=date(2024,1,1), end_date=None))
        db.session.commit()
        _close_open_aor_on_term(c, "BCBS", date(2026,5,31))
        h = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="BCBS").first()
        assert h.end_date is None
