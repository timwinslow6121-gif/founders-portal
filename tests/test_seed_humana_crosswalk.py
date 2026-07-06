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

def test_seed_links_mbi_bearing_facts_only(ctx):
    """Seed writes a crosswalk row ONLY for facts whose MBI matches an existing
    customer (guaranteed link). Renewal facts (no MBI) are skipped by the seed —
    they get linked at upload time via the seeded key. Never touches money tables."""
    from app.extensions import db
    from app.models import Customer, CarrierIdCrosswalk, CommissionLineItem
    from app.commission.member_fact import MemberFact, RowClass
    from scripts.seed_humana_crosswalk import seed_from_facts
    app, agency_id = ctx
    cust = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                    full_name="Eric Tillman", humana_id="6Q77JG7KE39")
    db.session.add(cust); db.session.flush()
    facts = [
        # new-enrollment: has MBI matching cust.humana_id → seed
        MemberFact(carrier="Humana", full_name="Eric Tillman", first_name="Eric",
                   last_name="Tillman", mbi="6Q77JG7KE39", carrier_member_id="827895454",
                   member_group_key="00026457660K", row_class=RowClass.ENROLLMENT, amount=1.0,
                   source_ref="h::1"),
        # renewal: no MBI → skipped by seed
        MemberFact(carrier="Humana", full_name="Sandra Agner", first_name="Sandra",
                   last_name="Agner", mbi=None, carrier_member_id="591236450",
                   member_group_key="00019275764K", row_class=RowClass.RENEWAL, amount=1.0,
                   source_ref="h::2"),
    ]
    counts = seed_from_facts(facts, agency_id, apply=True)
    assert counts["seeded"] == 1
    assert counts["skipped_no_mbi_match"] == 1
    rows = CarrierIdCrosswalk.query.filter_by(agency_id=agency_id).all()
    assert len(rows) == 1 and rows[0].carrier_key == "00026457660K"
    # money tables untouched
    assert CommissionLineItem.query.count() == 0

def test_seed_prefers_real_customer_over_stub_on_shared_mbi(ctx):
    """MINOR-3 regression: when a real and a stub customer share the same
    humana_id, _match_by_mbi's .first() is arbitrary-order and may return the
    stub. The seed must prefer the REAL (stub=False) customer so the crosswalk
    row never points at a stub (which plan_cleanup then can't use as a keeper,
    and which is CRITICAL-1 fuel — a stub that owns a crosswalk row)."""
    from app.extensions import db
    from app.models import Customer, CarrierIdCrosswalk
    from app.commission.member_fact import MemberFact, RowClass
    from scripts.seed_humana_crosswalk import seed_from_facts
    app, agency_id = ctx
    real = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                    full_name="Eric Tillman", humana_id="6Q77JG7KE39", stub=False)
    stub = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                    full_name="Eric Tillman", humana_id="6Q77JG7KE39",
                    stub=True, source="commission_import")
    db.session.add_all([real, stub]); db.session.flush()
    facts = [
        MemberFact(carrier="Humana", full_name="Eric Tillman", first_name="Eric",
                   last_name="Tillman", mbi="6Q77JG7KE39", carrier_member_id="827895454",
                   member_group_key="00026457660K", row_class=RowClass.ENROLLMENT, amount=1.0,
                   source_ref="h::1"),
    ]
    counts = seed_from_facts(facts, agency_id, apply=True)
    assert counts["seeded"] == 1
    row = CarrierIdCrosswalk.query.filter_by(agency_id=agency_id, carrier="Humana",
                                             carrier_key="00026457660K").first()
    assert row is not None
    assert row.customer_id == real.id
    assert row.customer_id != stub.id


def test_seed_dry_run_writes_nothing(ctx):
    from app.extensions import db
    from app.models import Customer, CarrierIdCrosswalk
    from app.commission.member_fact import MemberFact, RowClass
    from scripts.seed_humana_crosswalk import seed_from_facts
    app, agency_id = ctx
    cust = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                    full_name="Eric Tillman", humana_id="6Q77JG7KE39")
    db.session.add(cust); db.session.flush()
    facts = [MemberFact(carrier="Humana", full_name="Eric Tillman", first_name="Eric",
                        last_name="Tillman", mbi="6Q77JG7KE39",
                        member_group_key="00026457660K", row_class=RowClass.ENROLLMENT,
                        amount=1.0, source_ref="h::1")]
    counts = seed_from_facts(facts, agency_id, apply=False)
    assert counts["seeded"] == 1               # counted
    assert CarrierIdCrosswalk.query.count() == 0   # but nothing written
