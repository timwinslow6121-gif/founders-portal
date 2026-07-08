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

def test_seed_is_service_area_aware_multi_state(ctx):
    """With states=(NC,SC) an SC plan is seeded; a TX plan is still skipped. Out-of-state
    plans have their OWN CMS codes so they don't collide with NC buckets. (Supports the
    tiny out-of-state tail — e.g. TimW/Anjana's SC book — and white-label tenants.)"""
    from app.extensions import db
    from app.models import Plan
    from scripts.seed_plan_buckets import seed_buckets_from_rows
    app, agency_id = ctx
    rows = [
        _cms_row(**{"State Territory Abbreviation": "NC", "Contract ID": "H1036",
                    "Plan ID": "335", "ContractPlanID": "H1036-335",
                    "Plan Name": "Humana Gold Plus HMO-POS NC"}),
        _cms_row(**{"State Territory Abbreviation": "SC", "Organization Marketing Name": "UnitedHealthcare",
                    "Contract ID": "H5322", "Plan ID": "040", "ContractPlanID": "H5322_040",
                    "Plan Name": "AARP Medicare Advantage from UHC SC-0005 (HMO-POS)"}),
        _cms_row(**{"State Territory Abbreviation": "TX", "Organization Marketing Name": "UnitedHealthcare",
                    "Contract ID": "H4514", "Plan ID": "014", "ContractPlanID": "H4514_014",
                    "Plan Name": "AARP Medicare Advantage from UHC TX-001P (HMO-POS)"}),
    ]
    res = seed_buckets_from_rows(rows, agency_id, apply=True, states=("NC", "SC"))
    assert res["created"] == 2                                   # NC Humana + SC UHC
    assert Plan.query.filter_by(carrier="UHC", cms_plan_id="H5322-040").count() == 1
    assert Plan.query.filter_by(carrier="Humana", cms_plan_id="H1036-335").count() == 1
    assert Plan.query.filter_by(cms_plan_id="H4514-014").count() == 0   # TX not requested → skipped

def test_seed_default_states_is_nc_only(ctx):
    """Default (no states arg) stays NC-only — the out-of-state opt-in must be explicit."""
    from app.models import Plan
    from scripts.seed_plan_buckets import seed_buckets_from_rows
    app, agency_id = ctx
    rows = [_cms_row(**{"State Territory Abbreviation": "SC",
                        "ContractPlanID": "H9999-001", "Plan Name": "SC Plan"})]
    res = seed_buckets_from_rows(rows, agency_id, apply=True)   # default states
    assert res["created"] == 0 and res["skipped"] >= 1
    assert Plan.query.count() == 0

def test_seed_normalizes_real_cms_underscore_form_to_dash(ctx):
    """The REAL CMS Landscape ContractPlanID is UNDERSCORE form (H1036_167). The bucket
    must be stored DASH form (H1036-167) so it matches the sorter (cms_plan_id_of),
    sync_cms_plan_data (_cms_id), and find_plan_bucket — all of which use dash. Storing
    underscore silently orphans every seeded bucket. (This test data mirrors the real
    file; the original fixture used dash and hid the bug.)"""
    from app.models import Plan
    from scripts.seed_plan_buckets import seed_buckets_from_rows
    app, agency_id = ctx
    rows = [_cms_row(**{"Contract ID": "H1036", "Plan ID": "167",
                        "ContractPlanID": "H1036_167",              # real underscore form
                        "ContractPlanSegmentID": "H1036_167_1",
                        "Plan Name": "Humana Gold Plus SNP-DE"})]
    res = seed_buckets_from_rows(rows, agency_id, apply=True)
    assert res["created"] == 1
    plan = Plan.query.filter_by(agency_id=agency_id, carrier="Humana").first()
    assert plan.cms_plan_id == "H1036-167"   # DASH, not the raw underscore
