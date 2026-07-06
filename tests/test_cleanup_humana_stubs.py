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

def test_plan_cleanup_pairs_stub_to_real_via_crosswalk(ctx):
    """A legacy stub whose MBI (stored in humana_id by the old importer) matches a
    crosswalk row pointing at a DIFFERENT real customer is a safe merge candidate;
    a stub whose MBI is not in the crosswalk is NOT listed."""
    from app.extensions import db
    from app.models import Customer, CarrierIdCrosswalk
    from scripts.cleanup_humana_stubs import plan_cleanup
    app, agency_id = ctx
    real = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                    full_name="Eric Tillman", humana_id="6Q77JG7KE39", stub=False)
    stub = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                    full_name="Eric Tillman", humana_id="6Q77JG7KE39",
                    stub=True, source="commission_import")
    lonely = Customer(agency_id=agency_id, first_name="No", last_name="Match",
                      full_name="No Match", humana_id="ZZZ0000ZZ00",
                      stub=True, source="commission_import")
    db.session.add_all([real, stub, lonely]); db.session.flush()
    # crosswalk row carries the member's MBI and points to the REAL customer
    db.session.add(CarrierIdCrosswalk(agency_id=agency_id, carrier="Humana",
                   carrier_key="00026457660K", key_kind="grpnbr",
                   customer_id=real.id, mbi="6Q77JG7KE39", confidence="exact_id"))
    db.session.flush()
    pairs = plan_cleanup(agency_id)
    keeper_ids = {p["keeper_id"] for p in pairs}
    loser_ids = {p["stub_id"] for p in pairs}
    assert real.id in keeper_ids
    assert stub.id in loser_ids
    assert lonely.id not in loser_ids   # its MBI isn't in the crosswalk → not a candidate
