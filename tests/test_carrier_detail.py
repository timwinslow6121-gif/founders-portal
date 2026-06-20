import pytest
from app.extensions import db
from app.models import Agency, User, Policy
from app.metrics import Scope, book_breakdown, attribution_coverage


def test_carrier_scope_breakdowns(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="Brian", email="b@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        for i in range(4):
            db.session.add(Policy(carrier="UHC", member_id=f"u{i}", status="active",
                                  agent_id=u.id, agency_id=ag.id, plan_type="MA", plan_name="NC-0015"))
        db.session.add(Policy(carrier="Humana", member_id="h", status="active",
                              agent_id=u.id, agency_id=ag.id))
        db.session.commit()
        s = Scope(agency_id=ag.id, carrier="UHC")
        bd = book_breakdown(s)
        assert sum(r["count"] for r in bd["by_plan_type"]) == 4
        assert attribution_coverage(s)["pct"] == 100.0


def test_carrier_detail_route_renders(db_session, app):
    """Render-check: /carriers/c/UHC returns 200 for a logged-in user."""
    with app.app_context():
        ag = Agency(name="T2"); db.session.add(ag); db.session.flush()
        u = User(name="Brian", email="brian2@x.com", agency_id=ag.id, is_admin=True)
        db.session.add(u); db.session.flush()
        for i in range(3):
            db.session.add(Policy(carrier="UHC", member_id=f"cu{i}", status="active",
                                  agent_id=u.id, agency_id=ag.id, plan_type="MA",
                                  plan_name="NC-0015"))
        db.session.commit()
        user_id = u.id

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True

    resp = client.get("/carriers/c/UHC")
    assert resp.status_code == 200

    resp_mine = client.get("/carriers/c/UHC?view=mine")
    assert resp_mine.status_code == 200
