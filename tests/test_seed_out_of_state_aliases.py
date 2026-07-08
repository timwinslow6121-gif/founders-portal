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


def _bucket(db, agency_id, carrier, code, name):
    from app.models import Plan
    p = Plan(agency_id=agency_id, carrier=carrier, cms_plan_id=code, year=2026,
             plan_name=name, plan_type="MA", status="current")
    db.session.add(p); db.session.flush(); return p


def test_oos_alias_links_sc_uhc_and_va_aetna(ctx):
    """After seeding, an SC UHC BOB name and Sheila's stale VA Aetna BOB name both
    sort into their real out-of-state buckets via the alias path."""
    from app.extensions import db
    from app.plan_bucket import find_plan_bucket
    from scripts.seed_out_of_state_aliases import seed_aliases
    app, agency_id = ctx
    sc = _bucket(db, agency_id, "UHC", "H5322-040",
                 "AARP Medicare Advantage from UHC SC-0005 (HMO-POS)")
    va = _bucket(db, agency_id, "Aetna", "H3931-101", "Aetna Medicare Signature (HMO-POS)")
    res = seed_aliases(agency_id, apply=True)
    assert res["added"] >= 2
    hit_sc = find_plan_bucket("UHC", {"plan_name": "AARP Medicare Advantage from UHC SC-0005",
                                      "plan_type": "MA"}, 2026, agency_id)
    assert hit_sc["plan_id"] == sc.id and hit_sc["matched_by"] == "alias"
    hit_va = find_plan_bucket("Aetna", {"plan_name": "Aetna Medicare Select (HMO-POS)",
                                        "plan_type": "MA"}, 2026, agency_id)
    assert hit_va["plan_id"] == va.id and hit_va["matched_by"] == "alias"


def test_idempotent(ctx):
    from app.extensions import db
    from scripts.seed_out_of_state_aliases import seed_aliases
    app, agency_id = ctx
    _bucket(db, agency_id, "UHC", "H5322-040", "AARP Medicare Advantage from UHC SC-0005 (HMO-POS)")
    first = seed_aliases(agency_id, apply=True)
    second = seed_aliases(agency_id, apply=True)
    assert first["added"] >= 1 and second["added"] == 0 and second["already"] >= 1


def test_missing_bucket_reported(ctx):
    from scripts.seed_out_of_state_aliases import seed_aliases
    app, agency_id = ctx
    res = seed_aliases(agency_id, apply=True)   # no buckets seeded
    assert res["no_bucket"] == 5 and res["added"] == 0 and res["missing_buckets"]
