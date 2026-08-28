"""
tests/test_customer_export.py

The customer CSV export used to carry only contact columns (name, MBI, phone,
email, DOB, address, medicaid, stage, agent, pharmacy) — no plan data at all,
so an exported list could not be reconciled against a carrier book.

Two modes now share the same filters and the same customer columns:
  default          — one row per CUSTOMER, primary-medical plan in the named
                     columns ("who do I contact?")
  ?mode=policies   — one row per active POLICY ("does our book match theirs?")

⚠ Plan Type comes from the LINKED PLAN BUCKET, never from Policy.plan_type.
Policy.plan_type holds CARRIER vocabulary (UHC types ~2,133 of 2,272 active
policies "MA" when only ~15 are truly MA-only), so exporting it as the plan
type would be wrong for most rows. The raw carrier string is exported too, in
its own clearly-labelled column, so nothing is hidden.
"""
import csv
import io


def _rows(resp):
    """Skip the leading '#' provenance line, as any consumer of the file does."""
    body = resp.data.decode()
    assert body.startswith("#"), "export lost its filter provenance line"
    return list(csv.DictReader(io.StringIO(body.split("\n", 1)[1])))


def _setup(app, agency, *, with_medigap=False):
    """One customer on an MAPD (linked to a real Plan bucket), optionally also
    holding a Medigap policy so multi-policy behaviour can be asserted."""
    from app.extensions import db
    from app.models import User, Customer, Policy, Plan
    with app.app_context():
        admin = User(email="exp@t.com", name="Exp Admin", is_admin=True, agency_id=agency.id)
        db.session.add(admin)

        plan = Plan(agency_id=agency.id, carrier="UHC", year=2026,
                    plan_name="AARP Medicare Advantage NC-15",
                    plan_type="mapd", cms_plan_id="H5253-117")
        db.session.add(plan); db.session.flush()

        c = Customer(agency_id=agency.id, first_name="Rebecca", last_name="Bingham",
                     full_name="Rebecca Bingham", mbi="3HT2EX5DP84",
                     phone_primary="704-281-4280", county="Mecklenburg")
        db.session.add(c); db.session.flush()

        db.session.add(Policy(
            agency_id=agency.id, carrier="UHC", member_id="3HT2EX5DP84",
            mbi="3HT2EX5DP84", plan_name="AARP Medicare Advantage NC-15",
            plan_type="MA",                     # carrier vocabulary — the trap
            status="active", customer_id=c.id, plan_id=plan.id,
            full_name="Rebecca Bingham"))

        if with_medigap:
            mg = Plan(agency_id=agency.id, carrier="UHC", year=0,
                      plan_name="Medigap Plan G", plan_type="medigap")
            db.session.add(mg); db.session.flush()
            db.session.add(Policy(
                agency_id=agency.id, carrier="UHC", member_id="MG-999",
                mbi="3HT2EX5DP84", plan_name="Medigap Plan G", plan_type="Medigap",
                status="active", customer_id=c.id, plan_id=mg.id,
                full_name="Rebecca Bingham"))

        db.session.commit()
        return admin.id


def _login(client, uid):
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)


def test_export_includes_plan_columns(client, app, agency, db_session):
    uid = _setup(app, agency)
    _login(client, uid)
    resp = client.get("/customers/export")
    assert resp.status_code == 200
    rows = _rows(resp)
    assert len(rows) == 1
    r = rows[0]
    for col in ("Carrier", "Plan Name", "CMS Code", "Plan Type",
                "Carrier Plan Type", "Member ID"):
        assert col in r, f"export is missing the {col!r} column"
    assert r["Carrier"] == "UHC"
    assert r["CMS Code"] == "H5253-117"
    assert r["Member ID"] == "3HT2EX5DP84"


def test_plan_type_comes_from_the_bucket_not_the_carrier_string(client, app, agency, db_session):
    """Policy.plan_type says 'MA'; the linked bucket says 'mapd'. The authoritative
    column must follow the bucket, with the carrier's raw value kept separately."""
    uid = _setup(app, agency)
    _login(client, uid)
    r = _rows(client.get("/customers/export"))[0]
    assert r["Plan Type"].lower() == "mapd"
    assert r["Carrier Plan Type"] == "MA"


def test_customer_mode_is_one_row_per_person(client, app, agency, db_session):
    """A customer holding an MAPD *and* a Medigap is still ONE row; the extra
    plan is surfaced rather than silently dropped."""
    uid = _setup(app, agency, with_medigap=True)
    _login(client, uid)
    rows = _rows(client.get("/customers/export"))
    assert len(rows) == 1
    r = rows[0]
    assert r["Plan Type"].lower() == "mapd"          # primary-medical wins the named cols
    assert "Medigap" in r["Other Active Plans"]


def test_policy_mode_is_one_row_per_policy(client, app, agency, db_session):
    uid = _setup(app, agency, with_medigap=True)
    _login(client, uid)
    rows = _rows(client.get("/customers/export?mode=policies"))
    assert len(rows) == 2
    assert {r["Plan Type"].lower() for r in rows} == {"mapd", "medigap"}
    assert {r["Member ID"] for r in rows} == {"3HT2EX5DP84", "MG-999"}


def test_export_honours_the_active_filters(client, app, agency, db_session):
    """The export must reflect the same filters as the list it was exported from."""
    uid = _setup(app, agency)
    _login(client, uid)
    assert len(_rows(client.get("/customers/export?carrier=UHC"))) == 1
    assert len(_rows(client.get("/customers/export?carrier=Humana"))) == 0


def test_policy_mode_also_honours_filters(client, app, agency, db_session):
    uid = _setup(app, agency, with_medigap=True)
    _login(client, uid)
    rows = _rows(client.get("/customers/export?mode=policies&carrier=Humana"))
    assert rows == []


def test_export_records_the_filters_used(client, app, agency, db_session):
    """An exported file must say what it is a list OF — a CSV that has left the
    building is otherwise indistinguishable from any other export."""
    uid = _setup(app, agency)
    _login(client, uid)
    body = client.get("/customers/export?carrier=UHC&plan_type=all_ma").data.decode()
    first = body.splitlines()[0]
    assert first.startswith("#"), "no filter provenance line"
    assert "Carrier=UHC" in first
    assert "Plan type=all_ma" in first
    # the header row still parses as the header
    rows = list(csv.DictReader(io.StringIO(body.split("\n", 1)[1])))
    assert rows and "CMS Code" in rows[0]


def test_unfiltered_export_says_so(client, app, agency, db_session):
    uid = _setup(app, agency)
    _login(client, uid)
    first = client.get("/customers/export").data.decode().splitlines()[0]
    assert first.startswith("#")
    assert "no filters" in first.lower()
