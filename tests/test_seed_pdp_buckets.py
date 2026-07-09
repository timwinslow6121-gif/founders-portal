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


def test_seeds_pdp_buckets_including_silverscript_plus(ctx):
    from app.models import Plan
    from scripts.seed_pdp_buckets import seed_pdps
    app, agency_id = ctx
    res = seed_pdps(agency_id, apply=True)
    assert res["created"] == 14
    # the one that was missing (S5601-017 SilverScript Plus)
    p = Plan.query.filter_by(carrier="Aetna", cms_plan_id="S5601-017").first()
    assert p is not None and p.plan_type == "PDP"


def test_idempotent_skips_existing(ctx):
    from app.extensions import db
    from app.models import Plan
    from scripts.seed_pdp_buckets import seed_pdps
    app, agency_id = ctx
    # pre-seed one → it should be counted 'already', not duplicated
    db.session.add(Plan(agency_id=agency_id, carrier="Aetna", cms_plan_id="S5601-016",
                        year=2026, plan_name="SilverScript Choice (PDP)", plan_type="PDP",
                        status="current"))
    db.session.commit()
    res = seed_pdps(agency_id, apply=True)
    assert res["already"] == 1 and res["created"] == 13
    second = seed_pdps(agency_id, apply=True)
    assert second["created"] == 0 and second["already"] == 14
