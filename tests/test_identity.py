import pytest
from datetime import date
from app.extensions import db
from app.models import (Agency, User, Customer, Policy, CommissionStatement,
                        CommissionLineItem)
from app.identity import resolve_payment_identity, recover_policy_name

@pytest.fixture
def fixt(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        cust = Customer(agency_id=ag.id, first_name="Jane", last_name="Doe",
                        full_name="Jane Doe", primary_agent_id=u.id); db.session.add(cust); db.session.flush()
        pol = Policy(agency_id=ag.id, carrier="BCBS", member_id="112850623", status="active",
                     customer_id=cust.id, agent_id=u.id, first_name="Jane", last_name="Doe")
        db.session.add(pol); db.session.flush()
        st = CommissionStatement(carrier="BCBS", period_label="May 2026", agency_id=ag.id,
                                 statement_date=date(2026, 5, 1))
        db.session.add(st); db.session.flush()
        li = CommissionLineItem(agency_id=ag.id, statement_id=st.id, carrier="BCBS",
            period_label="May 2026", source_ref="bcbs::x::1", raw_amount=10.0,
            split_rate=0.55, classification="agent_commission",
            carrier_member_id="112850623", member_name="DOE, JANE")
        db.session.add(li); db.session.flush()
        # a no-name policy whose line item carries the name
        np = Policy(agency_id=ag.id, carrier="UHC", member_id="NG999", status="active",
                    customer_id=cust.id, agent_id=u.id)  # blank name
        db.session.add(np); db.session.flush()
        nli = CommissionLineItem(agency_id=ag.id, statement_id=st.id, carrier="UHC",
            period_label="May 2026", source_ref="uhc::x::9", raw_amount=5.0, split_rate=0.55,
            classification="agent_commission", carrier_member_id="NG999",
            member_name="SMITH, ROBERT"); db.session.add(nli)
        db.session.commit()
        yield ag.id, li.id, cust.id, np.id

def test_payment_links_by_carrier_member_id(fixt, app):
    ag, li_id, cid, np_id = fixt
    with app.app_context():
        li = db.session.get(CommissionLineItem, li_id)
        r = resolve_payment_identity(li, ag)
        assert r["action"] == "linked" and r["customer_id"] == cid and r["tier"] == "carrier_member_id"
        assert li.customer_id == cid

def test_policy_name_recovered_from_ledger(fixt, app):
    ag, li_id, cid, np_id = fixt
    with app.app_context():
        np = db.session.get(Policy, np_id)
        r = recover_policy_name(np, ag)
        assert r["action"] == "filled"
        assert np.last_name == "Smith" and np.first_name == "Robert"
