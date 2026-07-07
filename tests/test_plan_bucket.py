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

def _plan(db, agency_id, **kw):
    from app.models import Plan
    base = dict(agency_id=agency_id, plan_name="X", plan_type="MA", status="current")
    base.update(kw)
    p = Plan(**base); db.session.add(p); db.session.flush(); return p

def test_sorts_year_bound_row_into_existing_code_bucket(ctx):
    from app.extensions import db
    from app.plan_bucket import find_plan_bucket
    app, agency_id = ctx
    bucket = _plan(db, agency_id, carrier="Humana", cms_plan_id="H1036-335", year=2026)
    res = find_plan_bucket("Humana", {"plan_name": "HUMANA GOLD PLUS HMO POS H1036-335",
                                      "plan_type": "MAPD"}, 2026, agency_id)
    assert res["plan_id"] == bucket.id and res["matched_by"] == "code"
    assert res["contract_code"] == "H1036-335" and res["plan_year"] == 2026

def test_miss_returns_none_never_creates(ctx):
    from app.extensions import db
    from app.models import Plan
    from app.plan_bucket import find_plan_bucket
    app, agency_id = ctx
    # no bucket seeded for this code → MISS, and NO Plan is created
    res = find_plan_bucket("Humana", {"plan_name": "HUMANA MYSTERY PLAN H9999-999",
                                      "plan_type": "MAPD"}, 2026, agency_id)
    assert res["plan_id"] is None and res["matched_by"] is None
    assert Plan.query.count() == 0            # never auto-created

def test_sorts_medigap_by_letter_at_perpetual(ctx):
    from app.extensions import db
    from app.plan_bucket import find_plan_bucket
    from app.plan_codes import PERPETUAL
    app, agency_id = ctx
    bucket = _plan(db, agency_id, carrier="BCBS", plan_letter="G", plan_type="medigap",
                   year=PERPETUAL, cms_plan_id=None)
    res = find_plan_bucket("BCBS", {"plan_name": "MEDSUP G 2019", "plan_type": "MS"},
                           2026, agency_id)
    assert res["plan_id"] == bucket.id and res["matched_by"] == "letter"
    assert res["plan_year"] == PERPETUAL

def test_sorts_by_alias_when_no_code(ctx):
    from app.extensions import db
    from app.plan_bucket import find_plan_bucket
    app, agency_id = ctx
    # UHC friendly name, no code → matched via the reviewed alias on the bucket
    bucket = _plan(db, agency_id, carrier="UHC", cms_plan_id="H5253-117", year=2026,
                   plan_name_aliases="aarp medicare advantage from uhc nc-0015")
    res = find_plan_bucket("UHC", {"plan_name": "AARP Medicare Advantage from UHC NC-0015",
                                   "plan_type": "MA"}, 2026, agency_id)
    assert res["plan_id"] == bucket.id and res["matched_by"] == "alias"
