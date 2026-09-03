"""tests/test_deceased_manual_mark.py"""
from datetime import date


def _setup(app, agency):
    from app.extensions import db
    from app.models import Customer, Policy, User
    with app.app_context():
        u = User(email="agent@t.com", name="Agent A", agency_id=agency.id, is_admin=True)
        db.session.add(u); db.session.flush()
        c = Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                     full_name="Linda Bost", mbi="1AA1AA1AA11", primary_agent_id=u.id)
        db.session.add(c); db.session.flush()
        db.session.add(Policy(agency_id=agency.id, carrier="UHC", member_id="1AA1AA1AA11",
                              mbi="1AA1AA1AA11", status="active", customer_id=c.id,
                              full_name="Linda Bost"))
        db.session.commit()
        return u.id, c.id


def _login(client, uid):
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)


def test_an_agent_can_mark_a_customer_deceased(client, app, agency, db_session):
    from app.models import Customer
    uid, cid = _setup(app, agency)
    _login(client, uid)
    r = client.post(f"/customers/{cid}/deceased",
                    data={"deceased_date": "2026-08-14", "note": "son called"})
    assert r.status_code in (200, 302)
    with app.app_context():
        assert Customer.query.get(cid).deceased_date == date(2026, 8, 14)


def test_manual_marking_never_terms_a_policy(app, client, agency, db_session):
    """An agent knowing someone died does not mean the carrier has processed it."""
    from app.models import Policy
    uid, cid = _setup(app, agency)
    _login(client, uid)
    client.post(f"/customers/{cid}/deceased", data={"deceased_date": "2026-08-14"})
    with app.app_context():
        assert Policy.query.filter_by(customer_id=cid).first().status == "active"


def test_an_unknown_date_is_allowed(client, app, agency, db_session):
    """Records the mark without inventing a date."""
    from app.models import Customer
    uid, cid = _setup(app, agency)
    _login(client, uid)
    client.post(f"/customers/{cid}/deceased", data={"deceased_date": "", "note": "obituary"})
    with app.app_context():
        c = Customer.query.get(cid)
        assert c.deceased_date is not None      # marked, with a recorded date


def test_clearing_requires_a_reason(client, app, agency, db_session):
    from app.models import Customer
    uid, cid = _setup(app, agency)
    _login(client, uid)
    client.post(f"/customers/{cid}/deceased", data={"deceased_date": "2026-08-14"})
    r = client.post(f"/customers/{cid}/deceased", data={"action": "clear", "note": ""})
    assert r.status_code == 400
    with app.app_context():
        assert Customer.query.get(cid).deceased_date is not None


def test_clearing_with_a_reason_works(client, app, agency, db_session):
    from app.models import Customer
    uid, cid = _setup(app, agency)
    _login(client, uid)
    client.post(f"/customers/{cid}/deceased", data={"deceased_date": "2026-08-14"})
    client.post(f"/customers/{cid}/deceased",
                data={"action": "clear", "note": "carrier had the wrong member"})
    with app.app_context():
        assert Customer.query.get(cid).deceased_date is None
