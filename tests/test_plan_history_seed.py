from datetime import date
from app.extensions import db
from app.models import Agency, User, Customer, CustomerAorHistory
from app.upload import _seed_closed_history

def _setup(app):
    ag = Agency(name="T"); db.session.add(ag); db.session.flush()
    u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
    c = Customer(agency_id=ag.id, first_name="Jane", last_name="Doe", full_name="Jane Doe",
                 mbi="1ABC", primary_agent_id=u.id)
    db.session.add(c); db.session.flush()
    return ag.id, c, u.id

def test_seed_writes_closed_interval(db_session, app):
    with app.app_context():
        ag, c, uid = _setup(app); db.session.commit()
        rec = {"carrier": "Aetna", "plan_name": "Aetna Sig PPO",
               "effective_date": date(2024,1,1), "term_date": date(2026,5,31)}
        _seed_closed_history(c, rec, ag)
        h = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="Aetna").first()
        assert h.end_date == date(2026,5,31) and h.plan_name == "Aetna Sig PPO"
        assert h.source == "aetna_bob_history"

def test_seed_is_idempotent(db_session, app):
    with app.app_context():
        ag, c, uid = _setup(app); db.session.commit()
        rec = {"carrier": "Aetna", "plan_name": "X", "effective_date": date(2024,1,1),
               "term_date": date(2026,5,31)}
        _seed_closed_history(c, rec, ag); db.session.commit()
        _seed_closed_history(c, rec, ag)
        assert CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="Aetna").count() == 1

def test_seed_never_touches_open_interval(db_session, app):
    with app.app_context():
        ag, c, uid = _setup(app)
        # customer currently OPEN on Humana
        db.session.add(CustomerAorHistory(agency_id=ag, customer_id=c.id, agent_id=uid,
            carrier="Humana", effective_date=date(2026,6,1), end_date=None))
        db.session.commit()
        rec = {"carrier": "Aetna", "plan_name": "Aetna Sig PPO",
               "effective_date": date(2024,1,1), "term_date": date(2026,5,31)}
        _seed_closed_history(c, rec, ag)
        humana = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="Humana").first()
        assert humana.end_date is None    # untouched
