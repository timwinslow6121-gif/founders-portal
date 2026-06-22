import pytest
from app.extensions import db
from app.models import Agency, User, Customer, Policy
from app.commission.member_fact import MemberFact
from app.commission.resolver import _match_by_carrier_member_id

@pytest.fixture
def fixt(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=ag.id, full_name="JANE DOE", first_name="Jane", last_name="Doe",
                     primary_agent_id=u.id); db.session.add(c); db.session.flush()
        p = Policy(agency_id=ag.id, carrier="BCBS", member_id="112850623", status="active",
                   customer_id=c.id, agent_id=u.id, full_name="DOE, JANE"); db.session.add(p)
        db.session.commit()
        yield ag.id, c.id

def test_matches_by_carrier_member_id(fixt, app):
    ag, cid = fixt
    with app.app_context():
        f = MemberFact(carrier="BCBS", full_name="DOE, JANE", carrier_member_id="112850623")
        c = _match_by_carrier_member_id(f, ag)
        assert c is not None and c.id == cid

def test_no_match_wrong_carrier(fixt, app):
    ag, cid = fixt
    with app.app_context():
        f = MemberFact(carrier="Humana", full_name="x", carrier_member_id="112850623")
        assert _match_by_carrier_member_id(f, ag) is None

def test_blank_returns_none(fixt, app):
    ag, cid = fixt
    with app.app_context():
        assert _match_by_carrier_member_id(MemberFact(carrier="BCBS", full_name="x"), ag) is None
