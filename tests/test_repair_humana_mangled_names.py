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


def _commission_file(tmp_path):
    """Excel-2003 SpreadsheetML with PID + GrpName (the format the repair reads)."""
    xml = '''<xml version>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<Worksheet ss:Name="CommissionData"><Table>
<Row><Cell><Data ss:Type="String">PID</Data></Cell><Cell><Data ss:Type="String">GrpName</Data></Cell></Row>
<Row><Cell><Data ss:Type="String">356542453</Data></Cell><Cell><Data ss:Type="String">MORGAN JR BILLY N</Data></Cell></Row>
<Row><Cell><Data ss:Type="String">100</Data></Cell><Cell><Data ss:Type="String">VILLEGAS ANASTACIO Z</Data></Cell></Row>
</Table></Worksheet></Workbook>'''
    p = tmp_path / "CommissionData.xlsx"
    p.write_text(xml)
    return str(p)


def _mangled_cust(db, agency_id, first, last, pid):
    from app.models import Customer, Policy
    c = Customer(agency_id=agency_id, first_name=first, last_name=last,
                 full_name=f"{first} {last}")
    db.session.add(c); db.session.flush()
    db.session.add(Policy(agency_id=agency_id, carrier="Humana", member_id=pid,
                          status="active", customer_id=c.id))
    db.session.flush()
    return c


def test_repairs_mangled_name_from_commission_grpname(ctx, tmp_path):
    from app.extensions import db
    from app.models import Customer
    from scripts.repair_humana_mangled_names import repair
    app, agency_id = ctx
    c = _mangled_cust(db, agency_id, "Jr", "Morgan", "356542453")   # 'Jr Morgan'
    db.session.commit()
    res = repair(agency_id, _commission_file(tmp_path), apply=True)
    assert res["fixed"] == 1
    fixed = db.session.get(Customer, c.id)
    assert fixed.first_name == "Billy" and fixed.last_name == "Morgan"
    assert "Billy" in fixed.full_name and "Morgan" in fixed.full_name


def test_dry_run_writes_nothing(ctx, tmp_path):
    from app.extensions import db
    from app.models import Customer
    from scripts.repair_humana_mangled_names import repair
    app, agency_id = ctx
    c = _mangled_cust(db, agency_id, "Jr", "Morgan", "356542453")
    db.session.commit()
    res = repair(agency_id, _commission_file(tmp_path), apply=False)
    assert res["fixed"] == 1
    assert db.session.get(Customer, c.id).first_name == "Jr"   # unchanged


def test_skips_manually_edited(ctx, tmp_path):
    from app.extensions import db
    from app.models import Customer
    from scripts.repair_humana_mangled_names import repair
    app, agency_id = ctx
    c = _mangled_cust(db, agency_id, "Jr", "Morgan", "356542453")
    c.manually_edited = True
    db.session.commit()
    res = repair(agency_id, _commission_file(tmp_path), apply=True)
    assert res["skipped_manual"] == 1 and res["fixed"] == 0
