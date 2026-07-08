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


def _bucket(db, agency_id, code, name):
    from app.models import Plan
    p = Plan(agency_id=agency_id, carrier="UHC", cms_plan_id=code, year=2026,
             plan_name=name, plan_type="MA", status="current")
    db.session.add(p); db.session.flush(); return p


def test_alias_added_and_then_bob_row_sorts_into_bucket(ctx):
    """After seeding, a raw UHC BOB name (no code) sorts into the target bucket
    via find_plan_bucket's alias path."""
    from app.extensions import db
    from app.plan_bucket import find_plan_bucket
    from scripts.seed_uhc_aliases import seed_aliases
    app, agency_id = ctx
    b = _bucket(db, agency_id, "H2406-098", "AARP Medicare Advantage from UHC NC-0017 (PPO)")
    res = seed_aliases(agency_id, apply=True)
    assert res["added"] >= 1
    # the raw BOB name (differs from plan_name by the (PPO) suffix) now sorts in
    hit = find_plan_bucket("UHC", {"plan_name": "AARP Medicare Advantage from UHC NC-0017",
                                   "plan_type": "MA"}, 2026, agency_id)
    assert hit["plan_id"] == b.id and hit["matched_by"] == "alias"


def test_idempotent(ctx):
    from app.extensions import db
    from scripts.seed_uhc_aliases import seed_aliases
    app, agency_id = ctx
    _bucket(db, agency_id, "H2406-098", "AARP Medicare Advantage from UHC NC-0017 (PPO)")
    first = seed_aliases(agency_id, apply=True)
    second = seed_aliases(agency_id, apply=True)
    assert first["added"] >= 1
    assert second["added"] == 0            # nothing added on the second run
    assert second["already"] >= 1


def test_dry_run_writes_nothing(ctx):
    from app.extensions import db
    from app.models import Plan
    from scripts.seed_uhc_aliases import seed_aliases
    app, agency_id = ctx
    _bucket(db, agency_id, "H2406-098", "AARP Medicare Advantage from UHC NC-0017 (PPO)")
    res = seed_aliases(agency_id, apply=False)
    assert res["added"] >= 1
    assert Plan.query.filter_by(cms_plan_id="H2406-098").first().plan_name_aliases is None


def test_missing_bucket_reported_not_crashed(ctx):
    """If a target bucket isn't seeded, it's reported, not fatal."""
    from scripts.seed_uhc_aliases import seed_aliases
    app, agency_id = ctx
    res = seed_aliases(agency_id, apply=True)   # no buckets seeded at all
    assert res["no_bucket"] == 12 and res["added"] == 0
    assert res["missing_buckets"]
