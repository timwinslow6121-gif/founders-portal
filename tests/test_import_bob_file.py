"""The headless BOB import harness runs the same pipeline as /upload/bulk."""
from datetime import date


def test_harness_imports_and_sorts_into_bucket(db_session, app, agency, agent_user, tmp_path):
    """A minimal Humana-style BOB xlsx imports: policy created, plan_name set, and
    sorted into a pre-seeded bucket — proving the harness drives find_plan_bucket."""
    import openpyxl
    from app.extensions import db
    from app.models import Plan, Policy
    from scripts.import_bob_file import import_bob
    with app.app_context():
        db.session.add(Plan(agency_id=agency.id, carrier="Humana", cms_plan_id="H1036-335",
                            year=2026, plan_name="Gold Plus", plan_type="MA",
                            status="current"))
        db.session.commit()
        # a tiny Humana BOB (the parser keys on 'Humana ID'; plan code embedded in name)
        p = tmp_path / "Humana Book of business.xlsx"
        wb = openpyxl.Workbook(); ws = wb.active
        ws.append(["Humana ID", "Medicare No", "MbrFirstName", "MbrLastName", "Plan Name",
                   "Plan Type", "Effective Date", "Contract-PBP-Segment ID"])
        ws.append(["H94316794", "XXXXXU3KK18", "John", "Murray",
                   "HUMANA GOLD PLUS HMO POS H1036-335", "MA", "2026-01-01", "H1036-335-002"])
        wb.save(p)
        res = import_bob(agency.id, str(p), admin=True)
        assert res["carrier"] == "Humana"
        assert res["records"] >= 1
        pol = Policy.query.filter_by(agency_id=agency.id, member_id="H94316794").first()
        assert pol is not None
        assert pol.plan_name == "HUMANA GOLD PLUS HMO POS H1036-335"
        assert pol.plan_id is not None                 # sorted into the seeded bucket
        assert Plan.query.get(pol.plan_id).cms_plan_id == "H1036-335"
