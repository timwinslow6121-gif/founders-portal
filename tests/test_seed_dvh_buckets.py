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


def test_seeds_dvh_and_bob_row_sorts_in_via_alias(ctx):
    from app.extensions import db
    from app.models import Plan
    from app.plan_bucket import find_plan_bucket
    from app.plan_codes import PERPETUAL
    from scripts.seed_dvh_buckets import seed_dvh
    app, agency_id = ctx
    res = seed_dvh(agency_id, apply=True)
    assert res["created"] == 1
    p = Plan.query.filter_by(agency_id=agency_id, carrier="Humana", plan_type="dvh").first()
    assert p is not None and p.year == PERPETUAL
    # a BOB row with the raw DVH name sorts into the bucket via its alias
    hit = find_plan_bucket("Humana", {"plan_name": "NC EXTEND 1250 MNTH DEL '23",
                                      "plan_type": "dvh"}, 2026, agency_id)
    assert hit["plan_id"] == p.id


def test_idempotent(ctx):
    from scripts.seed_dvh_buckets import seed_dvh
    app, agency_id = ctx
    seed_dvh(agency_id, apply=True)
    res = seed_dvh(agency_id, apply=True)
    assert res["created"] == 0 and res["already"] == 1
