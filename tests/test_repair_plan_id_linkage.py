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

def test_repair_recovers_miscolumned_plan_name_from_plan_type(ctx):
    """Legacy BCBS policies carry the real plan NAME in the plan_type column (older parser
    bug). The repair recovers them: matches on plan_type-as-name, and on apply FIXES the
    data — copies the name into plan_name and resets plan_type to its real category."""
    from app.extensions import db
    from app.models import Policy, Plan
    from scripts.repair_plan_id_linkage import plan_repairs
    app, agency_id = ctx
    # bucket whose alias is the real plan name
    db.session.add(Plan(agency_id=agency_id, carrier="BCBS", cms_plan_id="H3449-012",
                        year=2026, plan_name="Medical Only HMO-POS", plan_type="mapd",
                        plan_name_aliases="Blue Medicare Medical Only (HMO-POS)",
                        status="current"))
    # mis-columned policy: plan_name BLANK, real name sits in plan_type
    db.session.add(Policy(agency_id=agency_id, carrier="BCBS", member_id="B1",
                          plan_name="", plan_type="Blue Medicare Medical Only (HMO-POS)",
                          status="active", plan_id=None))
    db.session.flush()
    res = plan_repairs(agency_id, year=2026, apply=True)
    assert res["linked"] == 1
    pol = Policy.query.filter_by(member_id="B1").first()
    assert pol.plan_id is not None
    # data fixed: name moved into plan_name, plan_type reset to the bucket's category
    assert pol.plan_name == "Blue Medicare Medical Only (HMO-POS)"
    assert pol.plan_type.lower() in ("mapd", "ma")          # real category, not the name

def test_repair_ignores_generic_plan_type(ctx):
    """A generic plan_type (MAPD/PDP) is NOT a plan name — must not be mistaken for one."""
    from app.extensions import db
    from app.models import Policy, Plan
    from scripts.repair_plan_id_linkage import plan_repairs
    app, agency_id = ctx
    db.session.add(Policy(agency_id=agency_id, carrier="BCBS", member_id="B2",
                          plan_name="", plan_type="MAPD",
                          status="active", plan_id=None))
    db.session.flush()
    res = plan_repairs(agency_id, year=2026, apply=True)
    assert res["leftover"] == 1                              # not recovered from "MAPD"
    pol = Policy.query.filter_by(member_id="B2").first()
    assert pol.plan_id is None and pol.plan_name == ""       # untouched

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
