def test_integrity_page_admin_only(client, app, agency, db_session):
    from flask import g
    from app.extensions import db
    from app.models import User
    with app.app_context():
        admin = User(email="iadmin@t.com", name="IAdmin", is_admin=True, agency_id=agency.id)
        agent = User(email="iagent@t.com", name="IAgent", is_admin=False, agency_id=agency.id)
        db.session.add_all([admin, agent]); db.session.commit()
        aid, gid = admin.id, agent.id
    # pytest-flask's autouse `_push_request_context` keeps one app context
    # (and therefore one `g`) alive for this whole test function, and that
    # context can be shared with OTHER tests too since `client`/`app` are
    # session-scoped fixtures. flask-login caches the resolved user on
    # `g._login_user` per app-context, so it must be cleared before each
    # client.get() whose expected auth state differs from the previous one
    # (including the very first call here, in case an earlier test in the
    # suite left a logged-in user cached) or current_user won't re-resolve.
    g.pop("_login_user", None)
    client.delete_cookie("session")
    # anonymous -> redirect to login
    assert client.get("/admin/integrity").status_code in (302, 401)
    # agent -> 403
    g.pop("_login_user", None)
    with client.session_transaction() as s: s["_user_id"] = str(gid)
    assert client.get("/admin/integrity").status_code == 403
    # admin -> 200, shows a known invariant key
    g.pop("_login_user", None)
    with client.session_transaction() as s: s["_user_id"] = str(aid)
    r = client.get("/admin/integrity")
    assert r.status_code == 200
    assert b"plan_id_orphans" in r.data
