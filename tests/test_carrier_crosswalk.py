import pytest

@pytest.fixture
def ctx():
    from app import create_app
    from app.extensions import db
    from app.models import Agency
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        yield app, ag.id
        db.session.remove(); db.drop_all()

def test_crosswalk_row_roundtrip_and_unique(ctx):
    from app.extensions import db
    from app.models import CarrierIdCrosswalk, Customer
    app, agency_id = ctx
    c = Customer(agency_id=agency_id, first_name="Sandra", last_name="Agner",
                 full_name="Sandra Agner")
    db.session.add(c); db.session.flush()
    row = CarrierIdCrosswalk(agency_id=agency_id, carrier="Humana",
                             carrier_key="00019275764K", key_kind="grpnbr",
                             customer_id=c.id, mbi=None, confidence="exact_id")
    db.session.add(row); db.session.flush()
    got = CarrierIdCrosswalk.query.filter_by(
        agency_id=agency_id, carrier="Humana", carrier_key="00019275764K").first()
    assert got is not None and got.customer_id == c.id
    # unique (agency_id, carrier, carrier_key)
    dup = CarrierIdCrosswalk(agency_id=agency_id, carrier="Humana",
                             carrier_key="00019275764K", key_kind="grpnbr",
                             customer_id=c.id, confidence="exact_id")
    db.session.add(dup)
    with pytest.raises(Exception):
        db.session.flush()


def test_merge_customers_reattaches_crosswalk_row(ctx):
    """CRITICAL-1 regression: a loser stub owning a CarrierIdCrosswalk row must
    merge cleanly via merge_customers — the row is repointed to the keeper (or
    dropped as a duplicate), never left dangling on the deleted loser. SQLite
    won't enforce the FK, so we assert the reattach logic directly rather than
    just 'no exception' (that would pass even if the bug were still present)."""
    from app.extensions import db
    from app.models import CarrierIdCrosswalk, Customer
    from app.customers import merge_customers
    app, agency_id = ctx
    keeper = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                      full_name="Eric Tillman", humana_id="6Q77JG7KE39", stub=False)
    loser = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                     full_name="Eric Tillman", humana_id="6Q77JG7KE39",
                     stub=True, source="commission_import")
    db.session.add_all([keeper, loser]); db.session.flush()
    xw = CarrierIdCrosswalk(agency_id=agency_id, carrier="Humana",
                            carrier_key="00026457660K", key_kind="grpnbr",
                            customer_id=loser.id, mbi="6Q77JG7KE39",
                            confidence="exact_id")
    db.session.add(xw); db.session.flush()
    xw_id = xw.id

    result = merge_customers(keeper.id, [loser.id], agency_id, actor="test")
    assert result["ok"] is True
    db.session.flush()

    # The row must exist and point at the keeper — not dangle on the deleted loser.
    row = CarrierIdCrosswalk.query.get(xw_id)
    assert row is not None
    assert row.customer_id == keeper.id
    # No duplicate-key collision: at most one row per (carrier, carrier_key).
    rows = CarrierIdCrosswalk.query.filter_by(
        agency_id=agency_id, carrier="Humana", carrier_key="00026457660K").all()
    assert len(rows) == 1


def test_merge_customers_keeper_and_loser_each_have_own_crosswalk_row(ctx):
    """Keeper and loser can each own a DIFFERENT crosswalk key (e.g. the same
    person linked under two different GrpNbrs across carriers/years) — both
    must survive the merge, repointed to the keeper, with no collision."""
    from app.extensions import db
    from app.models import CarrierIdCrosswalk, Customer
    from app.customers import merge_customers
    app, agency_id = ctx
    keeper = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                      full_name="Eric Tillman", humana_id="6Q77JG7KE39", stub=False)
    loser = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                     full_name="Eric Tillman", humana_id="6Q77JG7KE39",
                     stub=True, source="commission_import")
    db.session.add_all([keeper, loser]); db.session.flush()
    db.session.add(CarrierIdCrosswalk(agency_id=agency_id, carrier="Humana",
                   carrier_key="00026457660K", key_kind="grpnbr",
                   customer_id=keeper.id, confidence="exact_id"))
    db.session.add(CarrierIdCrosswalk(agency_id=agency_id, carrier="Humana",
                   carrier_key="00019275764K", key_kind="grpnbr",
                   customer_id=loser.id, confidence="exact_id"))
    db.session.flush()

    result = merge_customers(keeper.id, [loser.id], agency_id, actor="test")
    assert result["ok"] is True
    db.session.flush()

    rows = CarrierIdCrosswalk.query.filter_by(agency_id=agency_id, carrier="Humana").all()
    assert len(rows) == 2
    assert all(r.customer_id == keeper.id for r in rows)
    assert {r.carrier_key for r in rows} == {"00026457660K", "00019275764K"}
