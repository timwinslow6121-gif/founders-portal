import datetime
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


def _bob(tmp_path):
    import openpyxl
    p = tmp_path / "Humana Book of business.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Humana ID", "MbrFirstName", "MbrLastName", "Birth Date", "Gender",
               "Primary Phone", "Secondary Phone", "Resident Address", "Resident City",
               "Resident State", "Resident Zip Code", "Resident County", "Inactive Date",
               "Medicare No", "Plan Name"])
    # active member with full contact data, no inactive date
    ws.append(["H111", "Nancy", "Adkins", "1950-03-04", "F", "704-555-0101", "",
               "12 Oak St", "Charlotte", "NC", "28202", "MECKLENBURG", "", "XXXXXAB12", "Gold Plus"])
    # inactive member (should auto-term)
    ws.append(["H222", "John", "Abernathy", "1948-07-21", "M", "704-555-0202", "",
               "9 Pine Rd", "Concord", "NC", "28025", "CABARRUS", "4/30/2026", "XXXXXCD34", "Gold Plus"])
    wb.save(p)
    return str(p)


def _cust(db, agency_id, humana_id, **kw):
    from app.models import Customer
    base = dict(agency_id=agency_id, first_name="X", last_name="Y", full_name="X Y",
                humana_id=humana_id)
    base.update(kw)
    c = Customer(**base); db.session.add(c); db.session.flush(); return c


def _humana_pol(db, agency_id, cust, status="active"):
    from app.models import Policy
    p = Policy(agency_id=agency_id, carrier="Humana", member_id=f"pid{cust.id}",
               status=status, customer_id=cust.id)
    db.session.add(p); db.session.flush(); return p


def test_fills_blank_fields_only(ctx, tmp_path):
    from app.extensions import db
    from app.models import Customer
    from scripts.enrich_humana_from_bob import enrich
    app, agency_id = ctx
    c = _cust(db, agency_id, "H111", dob=None, phone_primary=None,
              city="EXISTING CITY")   # city already set → must NOT be overwritten
    _humana_pol(db, agency_id, c)
    db.session.commit()
    res = enrich(agency_id, _bob(tmp_path), apply=True)
    got = db.session.get(Customer, c.id)
    assert got.dob == datetime.date(1950, 3, 4)         # filled
    assert got.phone_primary == "704-555-0101"          # filled
    assert got.city == "EXISTING CITY"                  # NOT overwritten
    assert res["customers_filled"] == 1


def test_skips_manually_edited(ctx, tmp_path):
    from app.extensions import db
    from app.models import Customer
    from scripts.enrich_humana_from_bob import enrich
    app, agency_id = ctx
    c = _cust(db, agency_id, "H111", dob=None, manually_edited=True)
    _humana_pol(db, agency_id, c)
    db.session.commit()
    enrich(agency_id, _bob(tmp_path), apply=True)
    assert db.session.get(Customer, c.id).dob is None   # untouched


def test_auto_terms_inactive_member(ctx, tmp_path):
    from app.extensions import db
    from app.models import Policy
    from scripts.enrich_humana_from_bob import enrich
    app, agency_id = ctx
    c = _cust(db, agency_id, "H222")
    p = _humana_pol(db, agency_id, c)
    db.session.commit()
    res = enrich(agency_id, _bob(tmp_path), apply=True)
    got = db.session.get(Policy, p.id)
    assert got.status == "termed"
    assert got.term_date == datetime.date(2026, 4, 30)
    assert res["termed"] == 1


def test_moves_mbi_from_humana_id_column(ctx, tmp_path):
    from app.extensions import db
    from app.models import Customer
    from scripts.enrich_humana_from_bob import enrich
    app, agency_id = ctx
    # humana_id holds an MBI-format value; mbi blank
    c = _cust(db, agency_id, "8QV9Q10TC36", mbi=None)
    _humana_pol(db, agency_id, c)
    db.session.commit()
    res = enrich(agency_id, _bob(tmp_path), apply=True)
    got = db.session.get(Customer, c.id)
    assert got.mbi == "8QV9Q10TC36"
    assert res["mbi_moved"] == 1


def test_idless_stub_matches_by_unique_name_fills_and_backfills_id(ctx, tmp_path):
    """An ID-less commission stub (no Humana ID) matches the BOB by UNIQUE name → fills its
    blank fields, auto-terms if inactive, AND backfills the Humana ID for permanent linking."""
    from app.extensions import db
    from app.models import Customer, Policy
    from scripts.enrich_humana_from_bob import enrich
    app, agency_id = ctx
    # John Abernathy is in the BOB (H222, inactive 4/30) — stub has no Humana ID
    c = _cust(db, agency_id, humana_id=None, first_name="John", last_name="Abernathy",
              full_name="John Abernathy", dob=None)
    p = _humana_pol(db, agency_id, c)
    db.session.commit()
    res = enrich(agency_id, _bob(tmp_path), apply=True)
    got = db.session.get(Customer, c.id)
    assert got.humana_id == "H222"                        # ID backfilled
    assert got.dob == datetime.date(1948, 7, 21)          # field filled by name-match
    assert db.session.get(Policy, p.id).status == "termed"  # auto-termed
    assert res["matched_by_name"] == 1 and res["id_backfilled"] == 1


def _bob_with_renewal(tmp_path):
    """A member with a 12/31/2025-inactive OLD plan row AND a 1/1/2026 ACTIVE new plan row
    = an AEP plan renewal, NOT a termination."""
    import openpyxl
    p = tmp_path / "Humana Book of business.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Humana ID", "MbrFirstName", "MbrLastName", "Birth Date", "Gender",
               "Primary Phone", "Secondary Phone", "Resident Address", "Resident City",
               "Resident State", "Resident Zip Code", "Resident County", "Inactive Date",
               "Medicare No", "Plan Name"])
    ws.append(["H333", "Clifton", "Winecoff", "", "M", "", "", "", "", "", "", "",
               "12/31/2025", "XXXXXEF56", "Gold Plus H1036-291"])   # old plan ended
    ws.append(["H333", "Clifton", "Winecoff", "", "M", "", "", "", "", "", "", "",
               "", "XXXXXEF56", "Gold Plus H1036-335"])             # new plan ACTIVE
    wb.save(p)
    return str(p)


def test_renewal_not_termed(ctx, tmp_path):
    """A member with an inactive old plan BUT an active new plan (AEP renewal) must NOT be
    termed — the regression that would have wrongly termed 103 active members."""
    from app.extensions import db
    from app.models import Policy
    from scripts.enrich_humana_from_bob import enrich
    app, agency_id = ctx
    c = _cust(db, agency_id, "H333")
    p = _humana_pol(db, agency_id, c)
    db.session.commit()
    res = enrich(agency_id, _bob_with_renewal(tmp_path), apply=True)
    assert db.session.get(Policy, p.id).status == "active"   # NOT termed — still current
    assert res["termed"] == 0


def test_dry_run_writes_nothing(ctx, tmp_path):
    from app.extensions import db
    from app.models import Customer, Policy
    from scripts.enrich_humana_from_bob import enrich
    app, agency_id = ctx
    c = _cust(db, agency_id, "H222", dob=None)
    p = _humana_pol(db, agency_id, c)
    db.session.commit()
    res = enrich(agency_id, _bob(tmp_path), apply=False)
    assert res["filled_fields"] >= 1 and res["termed"] == 1   # counted
    assert db.session.get(Customer, c.id).dob is None          # not written
    assert db.session.get(Policy, p.id).status == "active"     # not termed
