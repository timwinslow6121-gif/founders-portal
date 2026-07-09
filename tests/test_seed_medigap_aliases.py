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


def test_aarpmodmedsup_alias_links_via_plan_type_recovery(ctx):
    """UHC 'AARPMODMEDSUP' (in plan_type) recovers: mis-column reads it as the name,
    medigap classify + the seeded alias link it to the UHC Plan G bucket."""
    from app.extensions import db
    from app.models import Policy, Plan
    from scripts.seed_medigap_aliases import seed_aliases
    from scripts.repair_plan_id_linkage import plan_repairs
    app, agency_id = ctx
    g = Plan(agency_id=agency_id, carrier="UHC", plan_letter="G", cms_plan_id=None,
             year=2026, plan_name="Medicare Supplement Plan G", plan_type="medigap",
             status="current")
    db.session.add(g); db.session.flush()
    res = seed_aliases(agency_id, apply=True)
    assert res["added"] == 1
    db.session.add(Policy(agency_id=agency_id, carrier="UHC", member_id="U1",
                          plan_name="", plan_type="AARPMODMEDSUP",
                          status="active", plan_id=None))
    db.session.flush()
    rep = plan_repairs(agency_id, year=2026, apply=True)
    assert rep["linked"] == 1
    assert Policy.query.filter_by(member_id="U1").first().plan_id == g.id


def test_idempotent(ctx):
    from app.extensions import db
    from app.models import Plan
    from scripts.seed_medigap_aliases import seed_aliases
    app, agency_id = ctx
    db.session.add(Plan(agency_id=agency_id, carrier="UHC", plan_letter="G", year=2026,
                        plan_name="Medicare Supplement Plan G", plan_type="medigap",
                        status="current"))
    db.session.flush()
    first = seed_aliases(agency_id, apply=True)
    second = seed_aliases(agency_id, apply=True)
    assert first["added"] == 1 and second["added"] == 0 and second["already"] == 1
