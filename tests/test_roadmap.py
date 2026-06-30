

def test_roadmap_item_column_maps_status(db_session, app, agency):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        cases = {
            "shipped": "shipped",
            "in_progress": "in_progress",
            "submitted": "planned",
            "acknowledged": "planned",
            "planned": "planned",
            "wont_fix": "hidden",
            "dismissed": "hidden",
        }
        for status, expected_col in cases.items():
            it = RoadmapItem(agency_id=agency.id, type="bug_fix",
                             title=f"t-{status}", status=status)
            db.session.add(it); db.session.flush()
            assert it.column == expected_col, f"{status} -> {it.column}, want {expected_col}"


def test_roadmap_item_known_issue_type_is_planned_column(db_session, app, agency):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        it = RoadmapItem(agency_id=agency.id, type="known_issue",
                         title="counts mismatch", status="acknowledged")
        db.session.add(it); db.session.flush()
        assert it.column == "planned"


def _login(client, uid):
    # pytest-flask's autouse request-context fixture keeps one app context
    # (and therefore one `g`) alive for the whole test function; flask-login
    # caches the resolved user on `g._login_user` per app-context, so it must
    # be cleared whenever a test switches which user is logged in mid-test
    # (see tests/test_integrity_dashboard.py for the same precedent) or
    # current_user won't re-resolve against the new session `_user_id`.
    from flask import g
    g.pop("_login_user", None)
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)


def test_board_renders_and_is_shared_across_agents(db_session, app, client, agency):
    from app.extensions import db
    from app.models import RoadmapItem, User
    with app.app_context():
        a1 = User(email="a1@test.com", name="Agent One", agency_id=agency.id)
        a2 = User(email="a2@test.com", name="Agent Two", agency_id=agency.id)
        db.session.add_all([a1, a2]); db.session.flush()
        # agent ONE submits a bug
        db.session.add(RoadmapItem(agency_id=agency.id, type="bug_fix", status="submitted",
                                   title="Birthday labels print blank", submitted_by_id=a1.id))
        db.session.commit()
        a2_id = a2.id

    # agent TWO sees agent ONE's submission on the shared board (anti-duplicate)
    _login(client, a2_id)
    body = client.get("/roadmap").get_data(as_text=True)
    assert "Birthday labels print blank" in body


def test_dismissed_item_off_shared_board_but_in_my_submissions(db_session, app, client, agency):
    from app.extensions import db
    from app.models import RoadmapItem, User
    with app.app_context():
        a1 = User(email="d1@test.com", name="Dee One", agency_id=agency.id)
        a2 = User(email="d2@test.com", name="Dee Two", agency_id=agency.id)
        db.session.add_all([a1, a2]); db.session.flush()
        db.session.add(RoadmapItem(agency_id=agency.id, type="bug_fix", status="dismissed",
                                   title="Dup of something", submitted_by_id=a1.id))
        db.session.commit()
        a1_id, a2_id = a1.id, a2.id

    # other agent does NOT see a dismissed item on the shared board
    _login(client, a2_id)
    assert "Dup of something" not in client.get("/roadmap").get_data(as_text=True)
    # the submitter DOES see it in their own ?mine=1 view
    _login(client, a1_id)
    assert "Dup of something" in client.get("/roadmap?mine=1").get_data(as_text=True)


def test_submit_creates_bug_and_acknowledges(db_session, app, client, agency):
    from app.extensions import db
    from app.models import RoadmapItem, User
    with app.app_context():
        u = User(email="sub@test.com", name="Sub Mitter", agency_id=agency.id)
        db.session.add(u); db.session.commit()
        uid = u.id
    _login(client, uid)
    resp = client.post("/roadmap/submit",
                       data={"title": "Export button does nothing",
                             "issue_text": "Clicking export on customers does nothing."},
                       follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        it = RoadmapItem.query.filter_by(title="Export button does nothing").first()
        assert it is not None
        assert it.type == "bug_fix" and it.status == "submitted"
        assert it.submitted_by_id == uid


def test_board_is_agency_scoped(db_session, app, client, agency):
    from app.extensions import db
    from app.models import RoadmapItem, User, Agency
    with app.app_context():
        other = Agency(name="Other Co"); db.session.add(other); db.session.flush()
        db.session.add(RoadmapItem(agency_id=other.id, type="feature", status="shipped",
                                   title="SECRET other-agency item"))
        u = User(email="scope@test.com", name="Scoped", agency_id=agency.id)
        db.session.add(u); db.session.flush()
        uid = u.id
    _login(client, uid)
    assert "SECRET other-agency item" not in client.get("/roadmap").get_data(as_text=True)


def test_admin_can_edit_status_and_fields(db_session, app, client, agency, admin_user):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        it = RoadmapItem(agency_id=agency.id, type="bug_fix", status="submitted",
                         title="Slow page")
        db.session.add(it); db.session.commit()
        iid, aid = it.id, admin_user.id
    _login(client, aid)
    client.post(f"/roadmap/{iid}/edit",
                data={"status": "shipped", "priority": "high",
                      "fix_text": "Rebuilt it to load fast.", "shipped_on": "2026-06-29"},
                follow_redirects=True)
    with app.app_context():
        it = RoadmapItem.query.get(iid)
        assert it.status == "shipped" and it.priority == "high"
        assert it.fix_text == "Rebuilt it to load fast."
        assert it.column == "shipped"


def test_admin_dismiss_takes_item_off_board(db_session, app, client, agency, admin_user):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        it = RoadmapItem(agency_id=agency.id, type="bug_fix", status="submitted",
                         title="Duplicate report")
        db.session.add(it); db.session.commit()
        iid, aid = it.id, admin_user.id
    _login(client, aid)
    client.post(f"/roadmap/{iid}/edit", data={"status": "dismissed"}, follow_redirects=True)
    with app.app_context():
        assert RoadmapItem.query.get(iid).column == "hidden"


def test_non_admin_cannot_edit(db_session, app, client, agency, agent_user):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        it = RoadmapItem(agency_id=agency.id, type="bug_fix", status="submitted",
                         title="Try to hack")
        db.session.add(it); db.session.commit()
        iid, aid = it.id, agent_user.id
    _login(client, aid)
    resp = client.post(f"/roadmap/{iid}/edit", data={"status": "shipped"})
    assert resp.status_code == 403
    with app.app_context():
        assert RoadmapItem.query.get(iid).status == "submitted"   # unchanged


def test_admin_cannot_edit_other_agency_item(db_session, app, client, agency, admin_user):
    from app.extensions import db
    from app.models import RoadmapItem, Agency
    with app.app_context():
        other = Agency(name="Other"); db.session.add(other); db.session.flush()
        it = RoadmapItem(agency_id=other.id, type="bug_fix", status="submitted",
                         title="Not yours")
        db.session.add(it); db.session.commit()
        iid, aid = it.id, admin_user.id
    _login(client, aid)
    resp = client.post(f"/roadmap/{iid}/edit", data={"status": "shipped"})
    assert resp.status_code == 404    # agency-scoped lookup -> not found


def test_board_renders_columns_and_admin_controls(db_session, app, client, agency, admin_user):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        db.session.add(RoadmapItem(agency_id=agency.id, type="bug_fix", status="shipped",
            title="HRA went to wrong agent", issue_text="Wrong agent at 55%.",
            fix_text="Now reads the real writing agent.", priority="high"))
        db.session.add(RoadmapItem(agency_id=agency.id, type="planned", status="planned",
            title="Merge duplicate customers"))
        db.session.commit()
        aid = admin_user.id
    _login(client, aid)
    body = client.get("/roadmap").get_data(as_text=True)
    assert "HRA went to wrong agent" in body
    assert "Merge duplicate customers" in body
    assert "rm-col" in body                       # the three columns
    assert "rm-issue" in body and "rm-fix" in body  # the issue/fix detail
    assert "/edit" in body                          # admin inline controls present


def test_agent_board_has_no_admin_controls(db_session, app, client, agency, agent_user):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        db.session.add(RoadmapItem(agency_id=agency.id, type="bug_fix", status="shipped",
            title="Something fixed"))
        db.session.commit()
        aid = agent_user.id
    _login(client, aid)
    body = client.get("/roadmap").get_data(as_text=True)
    assert "Something fixed" in body
    assert "/edit" not in body                      # no admin edit form for agents


def test_roadmap_nav_link_present_for_admin_and_agent(db_session, app, client, agency, admin_user, agent_user):
    # the nav is rendered on every page; check the dashboard (or any 200 page)
    for uid_attr in (admin_user, agent_user):
        with app.app_context():
            from app.models import User
            uid = User.query.filter_by(email=uid_attr.email).first().id
        _login(client, uid)
        body = client.get("/roadmap").get_data(as_text=True)
        assert 'href="{{ url_for(\'roadmap.roadmap_board\') }}"' in body or 'href="/roadmap"' in body
