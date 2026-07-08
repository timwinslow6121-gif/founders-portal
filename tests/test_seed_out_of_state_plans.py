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


def test_seeds_the_six_held_oos_plans(ctx):
    from app.models import Plan
    from scripts.seed_out_of_state_plans import seed_plans
    app, agency_id = ctx
    res = seed_plans(agency_id, apply=True)
    assert res["created"] == 6
    # spot-check a couple by code
    assert Plan.query.filter_by(carrier="UHC", cms_plan_id="H5322-040").count() == 1
    assert Plan.query.filter_by(carrier="Aetna", cms_plan_id="H3931-101").count() == 1
    assert Plan.query.filter_by(carrier="Healthspring", cms_plan_id="S5617-359").count() == 1


def test_idempotent(ctx):
    from scripts.seed_out_of_state_plans import seed_plans
    app, agency_id = ctx
    seed_plans(agency_id, apply=True)
    res = seed_plans(agency_id, apply=True)
    assert res["created"] == 0 and res["already"] == 6


def test_dry_run_writes_nothing(ctx):
    from app.models import Plan
    from scripts.seed_out_of_state_plans import seed_plans
    app, agency_id = ctx
    res = seed_plans(agency_id, apply=False)
    assert res["created"] == 6
    assert Plan.query.count() == 0
