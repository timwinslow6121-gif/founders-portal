from datetime import date
from app.extensions import db
from app.models import Agency, User, Policy


def test_dashboard_carrier_breakdown_has_no_fake_money(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="Brian", email="b@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        db.session.add(Policy(carrier="UHC", member_id="u1", status="active",
                              agent_id=u.id, agency_id=ag.id, plan_type="MA"))
        db.session.commit()
        from app.routes import _build_dashboard_context
        ctx = _build_dashboard_context(u.id, date.today(), ag.id)
        # money comes from ledger now: with no ledger rows, commission total is $0.00, not an estimate
        assert ctx["monthly_commission"] == "$0.00"
        assert ctx["policy_count"] == 1
        assert "annual_commission" not in ctx
        assert "carrier_breakdown" in ctx
        assert ctx["carrier_breakdown"][0]["carrier"] == "UHC"
        assert "color" in ctx["carrier_breakdown"][0]
