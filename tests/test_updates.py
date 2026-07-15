from datetime import date, timedelta
from app.models import CarrierUpdate, Agency
from app.extensions import db


def _mk(agency_id, **kw):
    u = CarrierUpdate(agency_id=agency_id,
                      update_type=kw.get("update_type", "general"),
                      carrier=kw.get("carrier"),
                      title=kw.get("title", "T"),
                      body=kw.get("body", "B"),
                      plan_id=kw.get("plan_id"),
                      event_date=kw.get("event_date"),
                      is_pinned=kw.get("is_pinned", False),
                      is_active=kw.get("is_active", True),
                      show_until=kw.get("show_until"))
    db.session.add(u); db.session.commit()
    return u


def test_visible_for_filters_orders(db_session, app, agency):
    with app.app_context():
        today = date(2026, 7, 15)
        other = Agency(name="Other"); db.session.add(other); db.session.commit()
        _mk(agency.id, title="pinned", is_pinned=True)
        _mk(agency.id, title="normal")
        _mk(agency.id, title="inactive", is_active=False)
        _mk(agency.id, title="expired", show_until=today - timedelta(days=1))
        _mk(agency.id, title="humana_comm", update_type="commission", carrier="Humana")
        _mk(other.id, title="other_agency", is_pinned=True)

        rows = CarrierUpdate.visible_for(agency.id, today)
        titles = [r.title for r in rows]
        assert titles[0] == "pinned"                 # pinned first
        assert "inactive" not in titles and "expired" not in titles
        assert "other_agency" not in titles          # agency isolation
        # type + carrier filter
        f = CarrierUpdate.visible_for(agency.id, today, update_type="commission", carrier="Humana")
        assert [r.title for r in f] == ["humana_comm"]


from app.updates import UPDATE_PRESENTATION, plan_affect


def test_presentation_covers_all_types():
    from app.models import CarrierUpdate
    assert set(UPDATE_PRESENTATION) == set(CarrierUpdate.UPDATE_TYPES)
    for v in UPDATE_PRESENTATION.values():
        assert "label" in v and "icon" in v and "accent" in v


def test_plan_affect_counts_active_members(db_session, app, agency):
    from app.models import Plan, Policy
    from app.extensions import db
    with app.app_context():
        p = Plan(agency_id=agency.id, carrier="Humana", plan_name="Gold Plus HMO",
                 year=2026, plan_type="mapd", status="current",
                 needs_review=False, is_commissionable=True, has_unresolved_conflicts=False)
        db.session.add(p); db.session.commit()
        for i, st in enumerate(["active", "active", "termed"]):
            db.session.add(Policy(agency_id=agency.id, carrier="Humana",
                                  member_id=f"M{i}", plan_id=p.id, status=st))
        db.session.commit()
        res = plan_affect(p.id, agency.id)
        assert res["count"] == 2 and res["plan_name"] == "Gold Plus HMO"
        assert plan_affect(None, agency.id) is None
        assert plan_affect(999999, agency.id) is None   # missing plan → None, no raise
