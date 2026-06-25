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


def test_name_search_matches_first_last_despite_middle_initial(client, app, agency, db_session):
    """Searching 'robbie belk' must find a customer stored as 'Robbie A. Belk'.
    Regression: the search did a single substring ILIKE on full_name, so a middle
    initial between first and last broke the contiguous 'robbie belk' match
    (Aetna parser stores names as 'First MI. Last')."""
    from app.extensions import db
    from app.models import User, Customer
    with app.app_context():
        admin = User(email="adminsrch@t.com", name="AdminSrch", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        c = Customer(agency_id=agency.id, first_name="Robbie", last_name="Belk",
                     full_name="Robbie A. Belk", mbi="MBISRCH001")
        db.session.add(c); db.session.commit()
        adminid = admin.id
    with client.session_transaction() as s:
        s["_user_id"] = str(adminid)
    resp = client.get("/customers?q=robbie+belk", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Belk" in resp.data


def test_name_search_matches_last_first_order(client, app, agency, db_session):
    """Searching 'belk robbie' (last first) must also find 'Robbie A. Belk' —
    each token matches the name in any order."""
    from app.extensions import db
    from app.models import User, Customer
    with app.app_context():
        admin = User(email="adminsrch2@t.com", name="AdminSrch2", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        c = Customer(agency_id=agency.id, first_name="Robbie", last_name="Belk",
                     full_name="Robbie A. Belk", mbi="MBISRCH002")
        db.session.add(c); db.session.commit()
        adminid = admin.id
    with client.session_transaction() as s:
        s["_user_id"] = str(adminid)
    resp = client.get("/customers?q=belk+robbie", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Belk" in resp.data


def test_name_search_excludes_partial_token_mismatch(client, app, agency, db_session):
    """Multi-token search is an AND: 'robbie smith' must NOT match 'Robbie A. Belk'
    (only one token matches) — so the fix doesn't over-broaden to OR-any-token."""
    from app.extensions import db
    from app.models import User, Customer
    with app.app_context():
        admin = User(email="adminsrch3@t.com", name="AdminSrch3", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        c = Customer(agency_id=agency.id, first_name="Robbie", last_name="Belk",
                     full_name="Robbie A. Belk", mbi="MBISRCH003")
        db.session.add(c); db.session.commit()
        adminid = admin.id
    with client.session_transaction() as s:
        s["_user_id"] = str(adminid)
    resp = client.get("/customers?q=robbie+smith", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Belk" not in resp.data   # not matched (Smith != Belk)


def test_ajax_search_matches_first_last_despite_middle_initial(client, app, agency, db_session):
    """The live-type AJAX endpoint (/customers/search) — what the search box actually
    calls — must also find 'Robbie A. Belk' by 'robbie belk'."""
    from app.extensions import db
    from app.models import User, Customer
    with app.app_context():
        admin = User(email="adminajax@t.com", name="AdminAjax", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        c = Customer(agency_id=agency.id, first_name="Robbie", last_name="Belk",
                     full_name="Robbie A. Belk", mbi="MBIAJAX001")
        db.session.add(c); db.session.commit()
        adminid = admin.id
    with client.session_transaction() as s:
        s["_user_id"] = str(adminid)
    resp = client.get("/customers/search?q=robbie+belk")
    assert resp.status_code == 200
    data = resp.get_json()
    assert any("Belk" in r["name"] for r in data)
