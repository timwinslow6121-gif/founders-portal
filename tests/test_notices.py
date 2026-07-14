from datetime import date, timedelta

from app.extensions import db
from app.models import Agency, AgencyNotice


def _mk(agency_id, **kw):
    n = AgencyNotice(
        agency_id=agency_id,
        notice_type=kw.get("notice_type", "info"),
        title=kw.get("title", "T"),
        body=kw.get("body", "B"),
        is_active=kw.get("is_active", True),
        show_until=kw.get("show_until"),
        priority=kw.get("priority", 0),
    )
    db.session.add(n)
    db.session.commit()
    return n


def test_visible_for_filters_and_orders(db_session, app, agency):
    with app.app_context():
        other_agency = Agency(name="Other Agency")
        db.session.add(other_agency)
        db.session.commit()

        today = date(2026, 7, 14)
        active = _mk(agency.id, title="active", priority=5)
        _mk(agency.id, title="inactive", is_active=False)
        _mk(agency.id, title="expired", show_until=today - timedelta(days=1))
        future = _mk(agency.id, title="future_exp", show_until=today + timedelta(days=1), priority=1)
        _mk(other_agency.id, title="other_agency", priority=99)

        rows = AgencyNotice.visible_for(agency.id, today)
        titles = [r.title for r in rows]
        assert titles == ["active", "future_exp"]  # inactive/expired/other-agency excluded; priority desc
        assert active.id and future.id


from app.notices import next_aep, NOTICE_PRESENTATION


def test_next_aep_before_oct15():
    assert next_aep(date(2026, 7, 14)) == (93, 2026)

def test_next_aep_on_oct15():
    assert next_aep(date(2026, 10, 15)) == (0, 2026)

def test_next_aep_after_oct15_rolls_to_next_year():
    d, y = next_aep(date(2026, 11, 1))
    assert y == 2027
    assert d == (date(2027, 10, 15) - date(2026, 11, 1)).days

def test_notice_presentation_covers_types():
    assert set(NOTICE_PRESENTATION) == {"info", "alert"}
    for v in NOTICE_PRESENTATION.values():
        assert "accent" in v and "icon" in v


def _login(client, uid):
    # pytest-flask's autouse request-context fixture keeps one app context
    # (and therefore one `g`) alive for the whole test function; flask-login
    # caches the resolved user on `g._login_user` per app-context, so it must
    # be cleared whenever a test switches which user is logged in mid-test
    # (see tests/test_roadmap.py for the same precedent) or current_user
    # won't re-resolve against the new session `_user_id`.
    from flask import g
    g.pop("_login_user", None)
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)


def test_non_admin_forbidden(db_session, app, client, agency, agent_user):
    _login(client, agent_user.id)
    assert client.get("/admin/notices").status_code == 403


def test_admin_can_create_notice(db_session, app, client, agency, admin_user):
    _login(client, admin_user.id)
    r = client.post("/admin/notices/new", data={
        "notice_type": "alert", "title": "Portal maintenance",
        "body": "Brief downtime tonight.", "priority": "3", "show_until": "", "is_active": "on",
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        n = AgencyNotice.query.filter_by(title="Portal maintenance").first()
        assert n and n.notice_type == "alert" and n.priority == 3 and n.show_until is None


def test_blank_title_rerenders_not_500(db_session, app, client, agency, admin_user):
    _login(client, admin_user.id)
    r = client.post("/admin/notices/new", data={
        "notice_type": "info", "title": "", "body": "x", "priority": "0", "is_active": "on"})
    assert r.status_code == 200          # re-render, not a 500
    assert b"Title" in r.data


def test_bad_notice_type_rejected(db_session, app, client, agency, admin_user):
    _login(client, admin_user.id)
    client.post("/admin/notices/new", data={
        "notice_type": "danger", "title": "Bad", "body": "x", "priority": "0", "is_active": "on"})
    with app.app_context():
        assert AgencyNotice.query.filter_by(title="Bad").first() is None


def test_delete_removes_notice(db_session, app, client, agency, admin_user):
    _login(client, admin_user.id)
    client.post("/admin/notices/new", data={
        "notice_type": "info", "title": "Temp", "body": "x", "priority": "0", "is_active": "on"})
    with app.app_context():
        nid = AgencyNotice.query.filter_by(title="Temp").first().id
    client.post(f"/admin/notices/{nid}/delete")
    with app.app_context():
        assert AgencyNotice.query.get(nid) is None


def test_login_route_runs_with_active_notice(db_session, app, client, agency):
    """The login route's board read must not crash the page, even with a live
    notice present. Does NOT assert notice text is in the HTML — the current
    login.html template doesn't render these context vars yet (Task 5)."""
    with app.app_context():
        db.session.add(AgencyNotice(agency_id=agency.id, notice_type="info",
            title="Beta Notice", body="In active development.", is_active=True, priority=1))
        db.session.commit()
    r = client.get("/auth/login")  # unauthenticated
    assert r.status_code == 200
