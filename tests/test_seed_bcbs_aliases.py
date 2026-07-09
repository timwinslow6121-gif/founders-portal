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
    p = Plan(agency_id=agency_id, carrier="BCBS", cms_plan_id=code, year=2026,
             plan_name=name, plan_type="mapd", status="current")
    db.session.add(p); db.session.flush(); return p


def test_variant_alias_lets_repair_recover_via_plan_type(ctx):
    """After seeding the variant alias, a mis-columned BCBS policy (variant name in
    plan_type) recovers through the repair's plan_type path."""
    from app.extensions import db
    from app.models import Policy
    from scripts.seed_bcbs_aliases import seed_aliases
    from scripts.repair_plan_id_linkage import plan_repairs
    app, agency_id = ctx
    b = _bucket(db, agency_id, "H3404-004", "Freedom+ PPO")
    seed_aliases(agency_id, apply=True)
    db.session.add(Policy(agency_id=agency_id, carrier="BCBS", member_id="B1",
                          plan_name="", plan_type="Blue Medicare Freedom+ (PPO)",
                          status="active", plan_id=None))
    db.session.flush()
    res = plan_repairs(agency_id, year=2026, apply=True)
    assert res["linked"] == 1
    assert Policy.query.filter_by(member_id="B1").first().plan_id == b.id


def test_idempotent(ctx):
    from app.extensions import db
    from scripts.seed_bcbs_aliases import seed_aliases
    app, agency_id = ctx
    _bucket(db, agency_id, "H3404-004", "Freedom+ PPO")
    first = seed_aliases(agency_id, apply=True)
    second = seed_aliases(agency_id, apply=True)
    assert first["added"] >= 1 and second["added"] == 0 and second["already"] >= 1
