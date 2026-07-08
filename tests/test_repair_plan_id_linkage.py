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

def test_repair_links_to_bucket_and_reports_leftover(ctx):
    from app.extensions import db
    from app.models import Policy, Plan
    from scripts.repair_plan_id_linkage import plan_repairs
    app, agency_id = ctx
    db.session.add(Plan(agency_id=agency_id, carrier="Humana", cms_plan_id="H1036-335",
                        year=2026, plan_name="Gold Plus", plan_type="MA", status="current"))
    db.session.add(Policy(agency_id=agency_id, carrier="Humana", member_id="M1",
                          plan_name="HUMANA GOLD PLUS HMO POS H1036-335", plan_type="MAPD",
                          status="active", plan_id=None))
    db.session.add(Policy(agency_id=agency_id, carrier="Humana", member_id="M2",
                          plan_name="HUMANA MYSTERY H9999-999", plan_type="MAPD",
                          status="active", plan_id=None))
    db.session.flush()
    res = plan_repairs(agency_id, year=2026, apply=True)
    assert res["linked"] == 1 and res["leftover"] == 1
    assert Policy.query.filter_by(member_id="M1").first().plan_id is not None
    assert Policy.query.filter_by(member_id="M2").first().plan_id is None   # no bucket → untouched
    assert Plan.query.count() == 1                                          # none created
    assert any("H9999-999" in n for n in res["leftover_names"])

def test_repair_dry_run_writes_nothing(ctx):
    from app.extensions import db
    from app.models import Policy, Plan
    from scripts.repair_plan_id_linkage import plan_repairs
    app, agency_id = ctx
    db.session.add(Plan(agency_id=agency_id, carrier="Humana", cms_plan_id="H1036-335",
                        year=2026, plan_name="Gold Plus", plan_type="MA", status="current"))
    db.session.add(Policy(agency_id=agency_id, carrier="Humana", member_id="M1",
                          plan_name="HUMANA GOLD PLUS HMO POS H1036-335", plan_type="MAPD",
                          status="active", plan_id=None))
    db.session.flush()
    res = plan_repairs(agency_id, year=2026, apply=False)
    assert res["linked"] == 1
    assert Policy.query.filter_by(member_id="M1").first().plan_id is None   # not written
