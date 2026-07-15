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


from tests.test_roadmap import _login


def _admin(client, admin_user):
    _login(client, admin_user.id)

def test_hub_renders_for_agent(client, app, agency, agent_user):
    _login(client, agent_user.id)
    with app.app_context():
        _mk(agency.id, title="Humana killed Gold Plus", update_type="commission", carrier="Humana")
    r = client.get("/updates")
    assert r.status_code == 200
    assert b"Humana killed Gold Plus" in r.data

def test_any_agent_can_post(client, app, agency, agent_user):
    _login(client, agent_user.id)
    r = client.post("/updates/new", data={
        "update_type": "network", "carrier": "Humana",
        "title": "Tryon Medical added for 2026", "body": "Big for Union county.",
        "event_date": "", "plan_id": "", "show_until": ""}, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from app.models import CarrierUpdate
        u = CarrierUpdate.query.filter_by(title="Tryon Medical added for 2026").first()
        assert u and u.update_type == "network" and u.posted_by_id == agent_user.id

def test_blank_title_rerenders_not_500(client, app, agency, agent_user):
    _login(client, agent_user.id)
    r = client.post("/updates/new", data={"update_type": "general", "title": "", "body": "x"})
    assert r.status_code == 200 and b"Title" in r.data

def test_bad_type_rejected(client, app, agency, agent_user):
    _login(client, agent_user.id)
    client.post("/updates/new", data={"update_type": "spam", "title": "X", "body": "y"})
    with app.app_context():
        from app.models import CarrierUpdate
        assert CarrierUpdate.query.filter_by(title="X").first() is None

def test_owner_can_edit_nonowner_cannot(client, app, agency, agent_user, admin_user):
    _login(client, agent_user.id)
    with app.app_context():
        u = _mk(agency.id, title="mine"); u.posted_by_id = agent_user.id
        from app.extensions import db; db.session.commit(); uid = u.id
    # owner edits ok
    assert client.post(f"/updates/{uid}/edit", data={
        "update_type": "general", "title": "mine v2", "body": "b"}).status_code in (200, 302)
    # a DIFFERENT non-admin agent cannot
    with app.app_context():
        from app.models import User; from app.extensions import db
        other = User(email="o@test.com", name="Other", is_admin=False, agency_id=agency.id)
        db.session.add(other); db.session.commit(); oid = other.id
    _login(client, oid)
    assert client.post(f"/updates/{uid}/edit", data={
        "update_type": "general", "title": "hijack", "body": "b"}).status_code == 403

def test_delete_and_pin_admin_only(client, app, agency, agent_user, admin_user):
    with app.app_context():
        u = _mk(agency.id, title="pinnable"); uid = u.id
    _login(client, agent_user.id)
    assert client.post(f"/updates/{uid}/delete").status_code == 403
    assert client.post(f"/updates/{uid}/pin").status_code == 403
    _login(client, admin_user.id)
    assert client.post(f"/updates/{uid}/pin").status_code in (200, 302)
    assert client.post(f"/updates/{uid}/delete").status_code in (200, 302)
