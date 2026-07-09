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


def _aetna_bob(tmp_path):
    """A tiny Aetna BOB (CSV format the parser reads) with MBI + code columns."""
    import openpyxl
    p = tmp_path / "Aetna Book of Business.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Member ID", "Medicare Number", "First Name", "Last Name",
               "Coverage Effective Date", "Member Status", "Plan Name",
               "Writing Agent NPN", "Writing Agent First Name", "Writing Agent Last Name",
               "CMS Contract Number", "PBP Code"])
    ws.append(["NG1", "2WA7KC0TM50", "Barbara", "Overcash", "2026-01-01", "A",
               "Aetna Medicare Value Plus (HMO)", "1", "J", "B", "H3146", "6"])
    wb.save(p)
    return str(p)


def test_crosswalk_links_orphan_by_mbi_from_bob(ctx, tmp_path):
    """A blank-plan Aetna orphan whose MBI is in the BOB gets its plan from the BOB,
    sorted into the seeded bucket by the full code, plan_name filled."""
    from app.extensions import db
    from app.models import Policy, Plan
    from scripts.crosswalk_aetna_plan_from_bob import crosswalk
    app, agency_id = ctx
    bucket = Plan(agency_id=agency_id, carrier="Aetna", cms_plan_id="H3146-006", year=2026,
                  plan_name="Value Plus HMO", plan_type="MA", status="current")
    db.session.add(bucket)
    db.session.add(Policy(agency_id=agency_id, carrier="Aetna", member_id="NG1",
                          mbi="2WA7KC0TM50", plan_name="", plan_type="MAPD",
                          status="active", plan_id=None))
    db.session.commit()
    bob = _aetna_bob(tmp_path)
    res = crosswalk(agency_id, bob, apply=True)
    assert res["linked"] == 1
    pol = Policy.query.filter_by(member_id="NG1").first()
    assert pol.plan_id == bucket.id
    assert pol.plan_name == "Aetna Medicare Value Plus (HMO)"   # filled from BOB


def test_crosswalk_dry_run_writes_nothing(ctx, tmp_path):
    from app.extensions import db
    from app.models import Policy, Plan
    from scripts.crosswalk_aetna_plan_from_bob import crosswalk
    app, agency_id = ctx
    db.session.add(Plan(agency_id=agency_id, carrier="Aetna", cms_plan_id="H3146-006",
                        year=2026, plan_name="Value Plus HMO", plan_type="MA", status="current"))
    db.session.add(Policy(agency_id=agency_id, carrier="Aetna", member_id="NG1",
                          mbi="2WA7KC0TM50", plan_name="", status="active", plan_id=None))
    db.session.commit()
    res = crosswalk(agency_id, _aetna_bob(tmp_path), apply=False)
    assert res["linked"] == 1
    assert Policy.query.filter_by(member_id="NG1").first().plan_id is None


def test_crosswalk_no_bucket_left_untouched(ctx, tmp_path):
    """If the BOB plan has no seeded bucket, the orphan is reported, not auto-bucketed."""
    from app.extensions import db
    from app.models import Policy
    from scripts.crosswalk_aetna_plan_from_bob import crosswalk
    app, agency_id = ctx
    db.session.add(Policy(agency_id=agency_id, carrier="Aetna", member_id="NG1",
                          mbi="2WA7KC0TM50", plan_name="", status="active", plan_id=None))
    db.session.commit()
    res = crosswalk(agency_id, _aetna_bob(tmp_path), apply=True)   # no bucket seeded
    assert res["linked"] == 0 and res["no_bucket"] == 1
    assert Policy.query.filter_by(member_id="NG1").first().plan_id is None
