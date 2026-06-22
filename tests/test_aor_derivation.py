import pytest
from datetime import date
from app.extensions import db
from app.models import Agency, User, Customer, Policy, CustomerAorHistory
from scripts.recover_aor_intervals import derive_interval_for_customer

@pytest.fixture
def fixt(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=ag.id, first_name="Jane", last_name="Doe", full_name="Jane Doe", primary_agent_id=u.id)
        db.session.add(c); db.session.flush()
        p = Policy(agency_id=ag.id, carrier="UHC", member_id="m1", status="active",
                   customer_id=c.id, agent_id=u.id, effective_date=date(2025,1,1),
                   term_date=None); db.session.add(p)
        # BCBS customer with a term_date (should derive end=None)
        c2 = Customer(agency_id=ag.id, first_name="Bob", last_name="Roe", full_name="Bob Roe", primary_agent_id=u.id)
        db.session.add(c2); db.session.flush()
        p2 = Policy(agency_id=ag.id, carrier="BCBS", member_id="m2", status="active",
                    customer_id=c2.id, agent_id=u.id, effective_date=date(2025,3,1),
                    term_date=date(2026,2,28)); db.session.add(p2)
        # customer whose policy lacks effective_date → should queue
        c3 = Customer(agency_id=ag.id, first_name="No", last_name="Facts", full_name="No Facts", primary_agent_id=u.id)
        db.session.add(c3); db.session.flush()
        p3 = Policy(agency_id=ag.id, carrier="UHC", member_id="m3", status="active",
                    customer_id=c3.id, agent_id=u.id, effective_date=None); db.session.add(p3)
        db.session.commit()
        yield ag.id, c.id, u.id, c2.id, c3.id

def test_derives_interval_from_policy(fixt, app):
    ag, cid, uid, c2, c3 = fixt
    with app.app_context():
        c = db.session.get(Customer, cid)
        r = derive_interval_for_customer(c, ag)
        assert r["action"] == "derived"
        h = CustomerAorHistory.query.filter_by(customer_id=cid).first()
        assert h.carrier == "UHC" and h.effective_date.year == 2025 and h.agent_id == uid

def test_bcbs_end_date_is_none(fixt, app):
    ag, cid, uid, c2, c3 = fixt
    with app.app_context():
        derive_interval_for_customer(db.session.get(Customer, c2), ag)
        h = CustomerAorHistory.query.filter_by(customer_id=c2).first()
        assert h.end_date is None  # BCBS term_date is a renewal, not a termination

def test_no_facts_queues(fixt, app):
    ag, cid, uid, c2, c3 = fixt
    with app.app_context():
        r = derive_interval_for_customer(db.session.get(Customer, c3), ag)
        assert r["action"] == "queued"

def test_idempotent(fixt, app):
    ag, cid, uid, c2, c3 = fixt
    with app.app_context():
        c = db.session.get(Customer, cid)
        derive_interval_for_customer(c, ag); db.session.commit()
        r2 = derive_interval_for_customer(c, ag)
        assert r2["action"] == "skip"
        assert CustomerAorHistory.query.filter_by(customer_id=cid).count() == 1
