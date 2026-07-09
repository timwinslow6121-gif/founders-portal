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


def _humana_bob(tmp_path):
    """A tiny Humana BOB (2003-XML the parser can't take, so use xlsx via openpyxl with the
    columns the Humana parser reads: 'Humana ID', 'MbrFirstName', 'MbrLastName', 'Plan Name',
    'Plan Type', 'Medicare No')."""
    import openpyxl
    p = tmp_path / "Humana Book of business.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Humana ID", "Medicare No", "MbrFirstName", "MbrLastName", "Plan Name",
               "Plan Type", "Effective Date"])
    # Anastacio Villegas — has a Humana ID (exact match tier)
    ws.append(["H90477416", "", "Anastacio", "Villegas", "HUMANA GOLD PLUS HMO POS H1036-335", "MA", "2026-01-01"])
    # Tocara Brown — unique name, no ID on the orphan side
    ws.append(["H55500001", "", "Tocara", "Brown", "HUMANA GOLD PLUS SNP-DE HMO H1036-331", "MA", "2026-01-01"])
    # David Young — appears TWICE, but SAME plan → safe
    ws.append(["H55500002", "", "David", "Young", "HUMANA GOLD PLUS HMO POS H1036-335", "MA", "2026-01-01"])
    ws.append(["H55500003", "", "David", "Young", "HUMANA GOLD PLUS HMO POS H1036-335", "MA", "2026-01-01"])
    # Brenda Miller — appears TWICE with DIFFERENT plans → ambiguous, must NOT match
    ws.append(["H55500004", "", "Brenda", "Miller", "HUMANA VALUE RX PLAN PDP", "PDP", "2026-01-01"])
    ws.append(["H55500005", "", "Brenda", "Miller", "HUMANA GOLD PLUS HMO POS H1036-335", "MA", "2026-01-01"])
    wb.save(p)
    return str(p)


def _seed_buckets(db, agency_id):
    from app.models import Plan
    db.session.add(Plan(agency_id=agency_id, carrier="Humana", cms_plan_id="H1036-335",
                        year=2026, plan_name="Gold Plus", plan_type="MA", status="current"))
    db.session.add(Plan(agency_id=agency_id, carrier="Humana", cms_plan_id="H1036-331",
                        year=2026, plan_name="Gold Plus SNP-DE", plan_type="MA", status="current"))
    db.session.flush()


def _orphan(db, agency_id, member_id, name, humana_id=""):
    from app.models import Customer, Policy
    first, _, last = name.partition(" ")
    c = Customer(agency_id=agency_id, first_name=first, last_name=last, full_name=name,
                 humana_id=(humana_id or None))
    db.session.add(c); db.session.flush()
    p = Policy(agency_id=agency_id, carrier="Humana", member_id=member_id, status="active",
               plan_name="", plan_id=None, customer_id=c.id)
    db.session.add(p); db.session.flush()
    return p


def test_matches_by_humana_id_and_unique_name_only(ctx, tmp_path):
    """Match by Humana ID (exact) or UNIQUE name only. ANY shared name is ambiguous and
    left for review — even two 'David Young' rows on the same plan are treated as possibly
    two different people (Tim's rule). Never guess which one an orphan is."""
    from app.extensions import db
    from app.models import Policy
    from scripts.crosswalk_humana_plan_from_bob import crosswalk
    app, agency_id = ctx
    _seed_buckets(db, agency_id)
    p_vil = _orphan(db, agency_id, "111", "Anastacio Villegas", humana_id="H90477416")  # by ID
    p_toc = _orphan(db, agency_id, "222", "Tocara Brown")                                # unique name
    p_dav = _orphan(db, agency_id, "333", "David Young")     # shared name (2 in BOB) — DO NOT bridge
    p_bre = _orphan(db, agency_id, "444", "Brenda Miller")   # shared name — DO NOT bridge
    db.session.commit()
    res = crosswalk(agency_id, _humana_bob(tmp_path), apply=True)
    assert Policy.query.get(p_vil.id).plan_id is not None    # Villegas by ID
    assert Policy.query.get(p_toc.id).plan_id is not None    # Tocara by unique name
    assert Policy.query.get(p_dav.id).plan_id is None        # David Young — ambiguous, NOT bridged
    assert Policy.query.get(p_bre.id).plan_id is None        # Brenda Miller — ambiguous, NOT bridged
    assert res["linked_id"] == 1 and res["linked_name"] == 1  # only Villegas + Tocara
    assert res["ambiguous"] == 2                              # David + Brenda
    assert Policy.query.get(p_toc.id).plan_name == "HUMANA GOLD PLUS SNP-DE HMO H1036-331"


def test_persists_to_crosswalk_table(ctx, tmp_path):
    from app.extensions import db
    from app.models import CarrierIdCrosswalk
    from scripts.crosswalk_humana_plan_from_bob import crosswalk
    app, agency_id = ctx
    _seed_buckets(db, agency_id)
    _orphan(db, agency_id, "111", "Anastacio Villegas", humana_id="H90477416")
    db.session.commit()
    crosswalk(agency_id, _humana_bob(tmp_path), apply=True)
    xw = CarrierIdCrosswalk.query.filter_by(agency_id=agency_id, carrier="Humana").all()
    assert len(xw) >= 1
    assert any(x.carrier_key == "H90477416" for x in xw)


def test_dry_run_writes_nothing(ctx, tmp_path):
    from app.extensions import db
    from app.models import Policy, CarrierIdCrosswalk
    from scripts.crosswalk_humana_plan_from_bob import crosswalk
    app, agency_id = ctx
    _seed_buckets(db, agency_id)
    p = _orphan(db, agency_id, "111", "Anastacio Villegas", humana_id="H90477416")
    db.session.commit()
    res = crosswalk(agency_id, _humana_bob(tmp_path), apply=False)
    assert res["linked_id"] == 1                          # counted
    assert Policy.query.get(p.id).plan_id is None         # not written
    assert CarrierIdCrosswalk.query.count() == 0          # no crosswalk row


def test_not_in_bob_left_untouched_and_reported(ctx, tmp_path):
    from app.extensions import db
    from app.models import Policy
    from scripts.crosswalk_humana_plan_from_bob import crosswalk
    app, agency_id = ctx
    _seed_buckets(db, agency_id)
    p = _orphan(db, agency_id, "999", "Ghost Member")     # not in BOB
    db.session.commit()
    res = crosswalk(agency_id, _humana_bob(tmp_path), apply=True)
    assert Policy.query.get(p.id).plan_id is None
    assert res["not_in_bob"] == 1
    assert any("Ghost Member" in n for n in res["not_in_bob_names"])
