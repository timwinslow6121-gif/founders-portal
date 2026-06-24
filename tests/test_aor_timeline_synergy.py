from datetime import date
from app.extensions import db
from app.models import Agency, User, Customer, CustomerAorHistory
from app.upload import _close_open_aor_on_term, _seed_closed_history


def test_cross_carrier_switch_yields_two_chapters(db_session, app):
    """Aetna termed + Humana enrolled → CLOSED Aetna chapter + OPEN Humana chapter,
    neither undoing the other (the §6c timeline-synergy guarantee)."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=ag.id, full_name="Jane Doe", first_name="Jane",
                     last_name="Doe", mbi="1ABC", primary_agent_id=u.id)
        db.session.add(c); db.session.flush()
        # currently OPEN on Aetna
        db.session.add(CustomerAorHistory(agency_id=ag.id, customer_id=c.id, agent_id=u.id,
            carrier="Aetna", plan_name="Aetna Sig PPO", effective_date=date(2024, 1, 1), end_date=None))
        # a NEW Humana enrollment opens (mimic the resolver's open-interval write)
        db.session.add(CustomerAorHistory(agency_id=ag.id, customer_id=c.id, agent_id=u.id,
            carrier="Humana", plan_name="Humana Gold Plus", effective_date=date(2026, 6, 1), end_date=None))
        db.session.commit()
        # Aetna term row closes ONLY the Aetna chapter
        _close_open_aor_on_term(c, "Aetna", date(2026, 5, 31))
        db.session.commit()
        rows = CustomerAorHistory.query.filter_by(customer_id=c.id).all()
        aetna = next(r for r in rows if r.carrier == "Aetna")
        humana = next(r for r in rows if r.carrier == "Humana")
        assert aetna.end_date == date(2026, 5, 31)   # closed chapter
        assert humana.end_date is None               # current, untouched


def test_seed_past_chapter_never_closes_an_open_interval(db_session, app):
    """§4.2 add-only: seeding a closed Aetna past chapter must NOT touch the
    customer's currently-OPEN Humana interval."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=ag.id, full_name="Bob Roe", first_name="Bob",
                     last_name="Roe", mbi="2DEF", primary_agent_id=u.id)
        db.session.add(c); db.session.flush()
        db.session.add(CustomerAorHistory(agency_id=ag.id, customer_id=c.id, agent_id=u.id,
            carrier="Humana", plan_name="Humana Gold Plus", effective_date=date(2026, 6, 1), end_date=None))
        db.session.commit()
        _seed_closed_history(c, {"carrier": "Aetna", "plan_name": "Aetna Sig PPO",
                                 "effective_date": date(2024, 1, 1), "term_date": date(2026, 5, 31)}, ag.id)
        db.session.commit()
        humana = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="Humana").first()
        aetna = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="Aetna").first()
        assert humana.end_date is None               # open interval untouched
        assert aetna.end_date == date(2026, 5, 31)   # closed past chapter added
