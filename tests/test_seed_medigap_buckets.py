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


def test_seeds_missing_medigap_and_repair_links_by_letter(ctx):
    """After seeding the Humana Plan G bucket, a Humana medigap orphan links by letter."""
    from app.extensions import db
    from app.models import Policy, Plan
    from scripts.seed_medigap_buckets import seed_buckets
    from scripts.repair_plan_id_linkage import plan_repairs
    app, agency_id = ctx
    res = seed_buckets(agency_id, apply=True)
    assert res["created"] == 3
    g = Plan.query.filter_by(carrier="Humana", plan_letter="G").first()
    db.session.add(Policy(agency_id=agency_id, carrier="Humana", member_id="M1",
                          plan_name="HUMANA MED SUPP PLAN G", plan_type="medigap",
                          status="active", plan_id=None))
    db.session.flush()
    rep = plan_repairs(agency_id, year=2026, apply=True)
    assert rep["linked"] == 1
    assert Policy.query.filter_by(member_id="M1").first().plan_id == g.id


def test_idempotent(ctx):
    from scripts.seed_medigap_buckets import seed_buckets
    app, agency_id = ctx
    seed_buckets(agency_id, apply=True)
    res = seed_buckets(agency_id, apply=True)
    assert res["created"] == 0 and res["already"] == 3
