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

def test_plan_cleanup_pairs_stub_to_real_via_crosswalk(ctx):
    """A legacy stub whose MBI (stored in humana_id by the old importer) matches a
    crosswalk row pointing at a DIFFERENT real customer is a safe merge candidate;
    a stub whose MBI is not in the crosswalk is NOT listed."""
    from app.extensions import db
    from app.models import Customer, CarrierIdCrosswalk
    from scripts.cleanup_humana_stubs import plan_cleanup
    app, agency_id = ctx
    real = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                    full_name="Eric Tillman", humana_id="6Q77JG7KE39", stub=False)
    stub = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                    full_name="Eric Tillman", humana_id="6Q77JG7KE39",
                    stub=True, source="commission_import")
    lonely = Customer(agency_id=agency_id, first_name="No", last_name="Match",
                      full_name="No Match", humana_id="ZZZ0000ZZ00",
                      stub=True, source="commission_import")
    db.session.add_all([real, stub, lonely]); db.session.flush()
    # crosswalk row carries the member's MBI and points to the REAL customer
    db.session.add(CarrierIdCrosswalk(agency_id=agency_id, carrier="Humana",
                   carrier_key="00026457660K", key_kind="grpnbr",
                   customer_id=real.id, mbi="6Q77JG7KE39", confidence="exact_id"))
    db.session.flush()
    pairs = plan_cleanup(agency_id)
    keeper_ids = {p["keeper_id"] for p in pairs}
    loser_ids = {p["stub_id"] for p in pairs}
    assert real.id in keeper_ids
    assert stub.id in loser_ids
    assert lonely.id not in loser_ids   # its MBI isn't in the crosswalk → not a candidate


_MID = [0]

def _mk(db, agency_id, name, *, stub, eff=None, **kw):
    """Helper: a Humana customer + one Humana policy (for the name+eff tier).
    Each policy gets a unique member_id (the (carrier, member_id) unique index)."""
    from app.models import Customer, Policy
    fn, ln = (name.split(" ", 1) + [""])[:2]
    c = Customer(agency_id=agency_id, first_name=fn, last_name=ln, full_name=name,
                 stub=stub, source=("commission_import" if stub else "bob"), **kw)
    db.session.add(c); db.session.flush()
    if eff is not None:
        _MID[0] += 1
        db.session.add(Policy(agency_id=agency_id, carrier="Humana",
                              member_id=f"M{_MID[0]}", customer_id=c.id,
                              effective_date=eff))
    db.session.flush()
    return c


def test_name_eff_tier_merges_unique_non_jan1_pairs_only(ctx):
    """The name+eff tier pairs a stub to a real customer ONLY when: the effective
    date is NOT Jan 1 (AEP mass-date, weak), the (name, eff) matches EXACTLY ONE
    real customer, and the name is not shared by 3+ customers. Proven safe: across
    the whole book, no two DIFFERENT real people share a name + non-Jan-1 eff."""
    from app.extensions import db
    from scripts.cleanup_humana_stubs import plan_cleanup_by_name_eff
    from datetime import date
    app, agency_id = ctx

    # (A) SAFE: non-Jan-1 eff, unique real match, name not shared by 3+
    real_a = _mk(db, agency_id, "Eric Tillman", stub=False, eff=date(2026, 3, 1),
                 humana_id="H111")
    stub_a = _mk(db, agency_id, "Eric Tillman", stub=True, eff=date(2026, 3, 1))

    # (B) EXCLUDED: Jan-1 eff (AEP mass-date) — too weak
    real_b = _mk(db, agency_id, "Nancy Adkins", stub=False, eff=date(2026, 1, 1),
                 humana_id="H222")
    stub_b = _mk(db, agency_id, "Nancy Adkins", stub=True, eff=date(2026, 1, 1))

    # (C) EXCLUDED: name shared by 3+ customers (David-White risk), even non-Jan-1
    real_c = _mk(db, agency_id, "David White", stub=False, eff=date(2026, 4, 1),
                 humana_id="H333")
    stub_c = _mk(db, agency_id, "David White", stub=True, eff=date(2026, 4, 1))
    other_c = _mk(db, agency_id, "David White", stub=False, eff=date(2026, 9, 1),
                  humana_id="H444")  # third "David White" → shared name

    # (D) EXCLUDED: no real twin at that (name, eff) — commission-only island
    stub_d = _mk(db, agency_id, "Zed Lonely", stub=True, eff=date(2026, 5, 1))

    pairs = plan_cleanup_by_name_eff(agency_id)
    loser_ids = {p["stub_id"] for p in pairs}
    keepers = {p["stub_id"]: p["keeper_id"] for p in pairs}

    assert stub_a.id in loser_ids and keepers[stub_a.id] == real_a.id  # A merges
    assert stub_b.id not in loser_ids   # B: Jan-1 excluded
    assert stub_c.id not in loser_ids   # C: shared-name excluded
    assert stub_d.id not in loser_ids   # D: no real twin
    # every pair carries a reason/tier tag for the dry-run report
    for p in pairs:
        assert p.get("tier") == "name_eff"
