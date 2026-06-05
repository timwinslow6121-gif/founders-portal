"""
tests/test_customer_filters.py

Regression tests for the customer-list carrier/plan-type filter
(_apply_customer_filters in app/customers.py).

The original filter matched customers to policies BY MBI ONLY. Humana (and
BCBS) policies mostly have NULL mbi, so the carrier=Humana filter hid those
customers even though their policies ARE linked via the Policy.customer_id FK.
"""


def test_carrier_filter_finds_no_mbi_humana_customer_via_fk(client, app, agency, db_session):
    """A Humana customer with NULL mbi, linked by customer_id FK, must appear in
    the carrier=Humana filter (regression: filter was MBI-only, hid Humana)."""
    from app.extensions import db
    from app.models import User, Customer, Policy
    with app.app_context():
        admin = User(email="admin2@t.com", name="Admin2", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        # Humana customer, NO mbi, only humana_id
        c = Customer(agency_id=agency.id, first_name="Mitchell", last_name="Thoma",
                     full_name="Mitchell Thoma", mbi=None, humana_id="H1036335")
        db.session.add(c); db.session.flush()
        p = Policy(agency_id=agency.id, carrier="Humana", member_id="H1036335",
                   mbi=None, plan_type="MAPD", status="active", customer_id=c.id,
                   full_name="Mitchell Thoma")
        db.session.add(p); db.session.commit()
        adminid = admin.id; cid = c.id
    with client.session_transaction() as s:
        s["_user_id"] = str(adminid)
    resp = client.get("/customers?carrier=Humana", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Thoma" in resp.data    # the no-MBI Humana customer is now visible


def test_carrier_filter_still_finds_mbi_customer_via_fallback(client, app, agency, db_session):
    """A customer WITH an mbi, linked to a matching policy, must still appear
    (proves the MBI fallback path keeps working alongside the FK path)."""
    from app.extensions import db
    from app.models import User, Customer, Policy
    with app.app_context():
        admin = User(email="admin3@t.com", name="Admin3", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        # UHC customer WITH mbi; policy linked via mbi but NOT customer_id FK
        c = Customer(agency_id=agency.id, first_name="Wanda", last_name="Whitmore",
                     full_name="Wanda Whitmore", mbi="1EG4TE5MK72")
        db.session.add(c); db.session.flush()
        p = Policy(agency_id=agency.id, carrier="UHC", member_id="U123",
                   mbi="1EG4TE5MK72", plan_type="MAPD", status="active",
                   customer_id=None, full_name="Wanda Whitmore")
        db.session.add(p); db.session.commit()
        adminid = admin.id
    with client.session_transaction() as s:
        s["_user_id"] = str(adminid)
    resp = client.get("/customers?carrier=UHC", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Whitmore" in resp.data


def test_carrier_filter_excludes_other_carrier(client, app, agency, db_session):
    """The filter must NOT return a customer whose only policy is a different carrier."""
    from app.extensions import db
    from app.models import User, Customer, Policy
    with app.app_context():
        admin = User(email="admin4@t.com", name="Admin4", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        c = Customer(agency_id=agency.id, first_name="Aetna", last_name="Personne",
                     full_name="Aetna Personne", mbi=None, humana_id=None)
        db.session.add(c); db.session.flush()
        p = Policy(agency_id=agency.id, carrier="Aetna", member_id="A1",
                   mbi=None, plan_type="MAPD", status="active", customer_id=c.id,
                   full_name="Aetna Personne")
        db.session.add(p); db.session.commit()
        adminid = admin.id
    with client.session_transaction() as s:
        s["_user_id"] = str(adminid)
    resp = client.get("/customers?carrier=Humana", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Personne" not in resp.data
