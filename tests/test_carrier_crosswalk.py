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
