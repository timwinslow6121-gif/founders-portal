import pytest
from app.extensions import db
from app.models import Agency, User, AgentCarrierContract
from app.attribution import resolve_writing_agent


@pytest.fixture
def fixt(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u1 = User(name="Brian", email="b@x.com", agency_id=ag.id)
        u2 = User(name="Chris", email="c@x.com", agency_id=ag.id)
        db.session.add_all([u1, u2]); db.session.flush()
        db.session.add(AgentCarrierContract(agent_id=u1.id, carrier="UHC", id_value="6515098", agency_id=ag.id))
        db.session.commit()
        yield ag.id, u1.id, u2.id


def test_resolves_known_id(fixt, app):
    ag, u1, u2 = fixt
    with app.app_context():
        assert resolve_writing_agent("UHC", "6515098", ag) == u1


def test_blank_and_unknown_return_none(fixt, app):
    ag, u1, u2 = fixt
    with app.app_context():
        assert resolve_writing_agent("UHC", "", ag) is None
        assert resolve_writing_agent("UHC", "9999999", ag) is None


def test_collision_returns_none(fixt, app):
    ag, u1, u2 = fixt
    with app.app_context():
        db.session.add(AgentCarrierContract(agent_id=u2, carrier="UHC", id_value="6515098", agency_id=ag))
        db.session.commit()
        assert resolve_writing_agent("UHC", "6515098", ag) is None
