import pytest
from app.extensions import db
from app.models import Agency, User, AgentCarrierContract
from app.attribution import resolve_writing_agent


def test_resolver_used_for_admin_upload_row(db_session, app):
    """Proxy test: a policy carrying a mapped writing-id resolves to the agent.

    This guards the seam that app/upload.py's admin-upload write sites call
    into (resolve_writing_agent) — the full upload path is integration-heavy
    and verified live separately.
    """
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="Brian", email="b@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        db.session.add(AgentCarrierContract(agent_id=u.id, carrier="UHC", id_value="6515098", agency_id=ag.id))
        db.session.commit()
        assert resolve_writing_agent("UHC", "6515098", ag.id) == u.id
