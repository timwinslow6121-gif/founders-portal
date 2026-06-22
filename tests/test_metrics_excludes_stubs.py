import pytest
from app.extensions import db
from app.models import Agency, User, Policy
from app.metrics import Scope, policy_count


def test_stub_policies_excluded(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        db.session.add(Policy(agency_id=ag.id, carrier="UHC", member_id="REAL1",
                              status="active", agent_id=u.id))
        db.session.add(Policy(agency_id=ag.id, carrier="UHC", member_id="uhc::0::5",
                              status="active", agent_id=u.id))  # stub
        db.session.commit()
        assert policy_count(Scope(agency_id=ag.id)) == 1  # stub excluded
