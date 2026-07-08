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

def _cms_row(**kw):
    base = {"State Territory Abbreviation": "NC", "Contract ID": "H1036",
            "Plan ID": "335", "Segment ID": "001", "ContractPlanID": "H1036-335",
            "ContractPlanSegmentID": "H1036-335-001",
            "Plan Name": "Humana Gold Plus HMO-POS", "Plan Type": "HMO-POS",
            "Organization Marketing Name": "Humana", "SNP Type": ""}
    base.update(kw); return base

def test_seed_creates_one_bucket_per_contract_plan(ctx):
    from app.extensions import db
    from app.models import Plan
    from scripts.seed_plan_buckets import seed_buckets_from_rows
    app, agency_id = ctx
    rows = [_cms_row(**{"County Name": "MECKLENBURG"}),
            _cms_row(**{"County Name": "UNION"})]   # same plan, 2 counties → ONE bucket
    res = seed_buckets_from_rows(rows, agency_id, apply=True)
    assert res["created"] == 1
    plans = Plan.query.filter_by(agency_id=agency_id, carrier="Humana").all()
    assert len(plans) == 1
    assert plans[0].cms_plan_id == "H1036-335" and plans[0].year == 2026

def test_seed_maps_org_name_to_carrier_and_skips_non_nc(ctx):
    from app.extensions import db
    from app.models import Plan
    from scripts.seed_plan_buckets import seed_buckets_from_rows
    app, agency_id = ctx
    rows = [
        _cms_row(**{"Organization Marketing Name": "Blue Cross and Blue Shield of North Carolina",
                    "Contract ID": "H3449", "Plan ID": "020", "ContractPlanID": "H3449-020",
                    "Plan Name": "Blue Medicare Enhanced"}),
        _cms_row(**{"State Territory Abbreviation": "SC"}),   # non-NC → skipped
    ]
    res = seed_buckets_from_rows(rows, agency_id, apply=True)
    assert Plan.query.filter_by(carrier="BCBS").count() == 1
    assert res["skipped"] >= 1   # the SC row

def test_seed_dry_run_writes_nothing(ctx):
    from app.models import Plan
    from scripts.seed_plan_buckets import seed_buckets_from_rows
    app, agency_id = ctx
    res = seed_buckets_from_rows([_cms_row()], agency_id, apply=False)
    assert res["created"] == 1
    assert Plan.query.count() == 0
