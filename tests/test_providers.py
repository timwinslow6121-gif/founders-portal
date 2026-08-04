import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, User, Provider


@pytest.fixture
def ctx():
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False, WTF_CSRF_ENABLED=False, LOGIN_DISABLED=True)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(email="a@foundersinsuranceagency.com", name="A", is_admin=True,
                 agency_id=ag.id, role="admin")
        db.session.add(u); db.session.commit()
        yield app, ag.id, u.id
        db.session.remove(); db.drop_all()


def test_provider_persists_with_carriers(ctx):
    app, agency_id, uid = ctx
    with app.app_context():
        p = Provider(agency_id=agency_id, name="NE Digestive", provider_type="gastro",
                     city="Kannapolis", county="Cabarrus", bills_ppo_oon="no",
                     created_by_id=uid)
        p.set_carriers(["Humana", "BCBS"])
        db.session.add(p); db.session.commit()
        got = Provider.query.filter_by(name="NE Digestive").first()
        assert got.county == "Cabarrus"
        assert got.bills_ppo_oon == "no"
        assert set(got.carrier_names) == {"Humana", "BCBS"}


def test_provider_set_carriers_replaces(ctx):
    app, agency_id, uid = ctx
    with app.app_context():
        p = Provider(agency_id=agency_id, name="X", created_by_id=uid)
        p.set_carriers(["Humana"]); db.session.add(p); db.session.commit()
        p.set_carriers(["UHC", "Aetna"]); db.session.commit()
        assert set(p.carrier_names) == {"UHC", "Aetna"}   # replaced, not appended
