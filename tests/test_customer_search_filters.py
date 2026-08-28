"""
tests/test_customer_search_filters.py

The live search dropdown (/customers/search) applied ONLY the name filter while
the page's carrier / plan-type / agent / medicaid / language filters were
ignored — so searching "Johnny" with "Rebekah Long + Medicare Advantage" active
returned every Johnny in the agency, including other agents' customers.

Search must NARROW the filtered list, never escape it.
"""


def _setup(app, agency):
    from app.extensions import db
    from app.models import User, Customer, Policy, Plan
    with app.app_context():
        admin = User(email="s@t.com", name="S Admin", is_admin=True, agency_id=agency.id)
        reb = User(email="reb@t.com", name="Rebekah Long", agency_id=agency.id)
        other = User(email="oth@t.com", name="Other Agent", agency_id=agency.id)
        db.session.add_all([admin, reb, other]); db.session.flush()

        plan = Plan(agency_id=agency.id, carrier="Humana", year=2026,
                    plan_name="Gold Plus", plan_type="mapd", cms_plan_id="H1036-335")
        db.session.add(plan); db.session.flush()

        # Same name, two different agents, so only the filter can tell them apart.
        for owner, mbi in ((reb, "1AA1AA1AA11"), (other, "2BB2BB2BB22")):
            c = Customer(agency_id=agency.id, first_name="Johnny", last_name="Johnson",
                         full_name="Johnny Johnson", mbi=mbi, primary_agent_id=owner.id)
            db.session.add(c); db.session.flush()
            db.session.add(Policy(agency_id=agency.id, carrier="Humana", member_id=mbi,
                                  mbi=mbi, plan_name="Gold Plus", plan_type="MAPD",
                                  status="active", customer_id=c.id, plan_id=plan.id,
                                  full_name="Johnny Johnson"))
        db.session.commit()
        return admin.id, reb.id


def _login(client, uid):
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)


def test_search_without_filters_finds_both(client, app, agency, db_session):
    admin_id, _ = _setup(app, agency)
    _login(client, admin_id)
    assert len(client.get("/customers/search?q=Johnny").get_json()) == 2


def test_search_respects_the_active_agent_filter(client, app, agency, db_session):
    """The reported bug: an agent filter on the page did not reach the dropdown."""
    admin_id, reb_id = _setup(app, agency)
    _login(client, admin_id)
    out = client.get(f"/customers/search?q=Johnny&agent_id={reb_id}").get_json()
    assert len(out) == 1
    assert out[0]["agent"] == "Rebekah Long"


def test_search_respects_the_active_carrier_filter(client, app, agency, db_session):
    admin_id, _ = _setup(app, agency)
    _login(client, admin_id)
    assert client.get("/customers/search?q=Johnny&carrier=UHC").get_json() == []
    assert len(client.get("/customers/search?q=Johnny&carrier=Humana").get_json()) == 2


def test_search_respects_the_active_plan_type_filter(client, app, agency, db_session):
    admin_id, _ = _setup(app, agency)
    _login(client, admin_id)
    assert len(client.get("/customers/search?q=Johnny&plan_type=all_ma").get_json()) == 2
    assert client.get("/customers/search?q=Johnny&plan_type=PDP").get_json() == []
