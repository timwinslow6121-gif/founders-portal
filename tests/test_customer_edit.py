"""
tests/test_customer_edit.py

Route + permission tests for inline customer field editing and conflict resolution.
"""
from datetime import date


def _login(client, app, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def _make_customer(db, agency, agent):
    from app.models import Customer
    c = Customer(agency_id=agency.id, first_name="Mitchell", last_name="Thoma",
                 full_name="Mitchell Thoma", primary_agent_id=agent.id, source="bob")
    db.session.add(c); db.session.commit()
    return c


def test_current_aor_agent_can_save_field(client, app, agency, agent_user, db_session):
    from app.extensions import db
    from app.models import Customer
    from app import customer_provenance as cp
    with app.app_context():
        c = _make_customer(db, agency, agent_user); cid = c.id
    _login(client, app, agent_user.id)
    r = client.post(f"/customers/{cid}/field", data={"field": "mbi", "value": "1AB2C34DE56"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    with app.app_context():
        c = Customer.query.get(cid)
        assert c.mbi == "1AB2C34DE56"
        assert cp.trust_of(c, "mbi") == "agent_entered"


def test_save_field_rejects_untracked_field(client, app, agency, agent_user, db_session):
    from app.extensions import db
    with app.app_context():
        c = _make_customer(db, agency, agent_user); cid = c.id
    _login(client, app, agent_user.id)
    r = client.post(f"/customers/{cid}/field", data={"field": "deal_stage", "value": "Active"})
    assert r.status_code == 400


def test_save_field_unknown_customer_404(client, app, agency, agent_user, db_session):
    _login(client, app, agent_user.id)
    r = client.post("/customers/999999/field", data={"field": "mbi", "value": "X"})
    assert r.status_code == 404


def test_former_aor_agent_cannot_save_field(client, app, agency, db_session):
    from app.extensions import db
    from app.models import User, Customer
    with app.app_context():
        owner = User(email="owner@t.com", name="Owner", agency_id=agency.id)
        other = User(email="other@t.com", name="Other", agency_id=agency.id)
        db.session.add_all([owner, other]); db.session.flush()
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
                     primary_agent_id=owner.id, source="bob")
        db.session.add(c); db.session.commit()
        cid = c.id; other_id = other.id
    _login(client, app, other_id)
    r = client.post(f"/customers/{cid}/field", data={"field": "mbi", "value": "X"})
    assert r.status_code in (403, 404)


def test_resolve_conflict_route_keep_current(client, app, agency, agent_user, db_session):
    from app.extensions import db
    from app.models import Customer
    from app import customer_provenance as cp
    with app.app_context():
        c = _make_customer(db, agency, agent_user)
        cp.set_human_value(c, "email", "m@old.com", agent_user)
        cp.set_import_value(c, "email", "mark@gmail.com", "bob_import")
        db.session.commit()
        cid = c.id
    _login(client, app, agent_user.id)
    r = client.post(f"/customers/{cid}/resolve-conflict",
                    data={"field": "email", "choose": "keep_current"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["has_unresolved_conflicts"] is False
    with app.app_context():
        c = Customer.query.get(cid)
        assert c.email == "m@old.com"
        assert cp.list_conflicts(c) == []


def test_resolve_conflict_route_bad_choice_400(client, app, agency, agent_user, db_session):
    from app.extensions import db
    with app.app_context():
        c = _make_customer(db, agency, agent_user); cid = c.id
    _login(client, app, agent_user.id)
    r = client.post(f"/customers/{cid}/resolve-conflict",
                    data={"field": "email", "choose": "bogus"})
    assert r.status_code == 400


def test_resolve_conflict_route_former_aor_blocked(client, app, agency, db_session):
    from app.extensions import db
    from app.models import User, Customer
    with app.app_context():
        owner = User(email="o2@t.com", name="Owner2", agency_id=agency.id)
        other = User(email="x2@t.com", name="Other2", agency_id=agency.id)
        db.session.add_all([owner, other]); db.session.flush()
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
                     primary_agent_id=owner.id, source="bob")
        db.session.add(c); db.session.commit()
        cid = c.id; other_id = other.id
    _login(client, app, other_id)
    r = client.post(f"/customers/{cid}/resolve-conflict",
                    data={"field": "email", "choose": "keep_current"})
    assert r.status_code in (403, 404)


def test_profile_renders_conflict_cell_and_editable_fields(client, app, agency, agent_user, db_session):
    from app.extensions import db
    from app.models import Customer
    from app import customer_provenance as cp
    with app.app_context():
        c = _make_customer(db, agency, agent_user)
        cp.set_human_value(c, "email", "m@old.com", agent_user)
        cp.set_import_value(c, "email", "mark@gmail.com", "bob_import")
        db.session.commit()
        cid = c.id
    _login(client, app, agent_user.id)
    html = client.get(f"/customers/{cid}").data.decode()
    assert "needs review" in html
    assert "mark@gmail.com" in html
    assert 'data-choose="keep_current"' in html
    assert 'data-editable="1"' in html


def test_profile_admin_sees_edit_controls(client, app, agency, db_session):
    from app.extensions import db
    from app.models import User, Customer
    with app.app_context():
        owner = User(email="o3@t.com", name="Owner3", agency_id=agency.id)
        admin = User(email="adm3@t.com", name="Admin3", is_admin=True, agency_id=agency.id)
        db.session.add_all([owner, admin]); db.session.flush()
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
                     primary_agent_id=owner.id, source="bob")
        db.session.add(c); db.session.commit()
        cid = c.id; aid = admin.id
    _login(client, app, aid)
    html = client.get(f"/customers/{cid}").data.decode()
    assert 'data-editable="1"' in html


def test_save_field_invalid_dob_returns_400(client, app, agency, agent_user, db_session):
    from app.extensions import db
    with app.app_context():
        c = _make_customer(db, agency, agent_user); cid = c.id
    _login(client, app, agent_user.id)
    r = client.post(f"/customers/{cid}/field", data={"field": "dob", "value": "not-a-date"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_save_field_valid_dob_ok(client, app, agency, agent_user, db_session):
    from app.extensions import db
    from app.models import Customer
    from datetime import date
    with app.app_context():
        c = _make_customer(db, agency, agent_user); cid = c.id
    _login(client, app, agent_user.id)
    r = client.post(f"/customers/{cid}/field", data={"field": "dob", "value": "1956-08-28"})
    assert r.status_code == 200
    with app.app_context():
        assert Customer.query.get(cid).dob == date(1956, 8, 28)
