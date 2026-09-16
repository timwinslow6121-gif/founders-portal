"""tests/test_deceased_apply.py"""
from datetime import date


def _person(app, agency, mbi="1AA1AA1AA11"):
    from app.extensions import db
    from app.models import Customer, Policy
    c = Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                 full_name="Linda Bost", mbi=mbi)
    db.session.add(c); db.session.flush()
    uhc = Policy(agency_id=agency.id, carrier="UHC", member_id=mbi, mbi=mbi,
                 status="active", customer_id=c.id, full_name="Linda Bost")
    bcbs = Policy(agency_id=agency.id, carrier="BCBS", member_id="B1", mbi=mbi,
                  status="active", customer_id=c.id, full_name="Linda Bost")
    db.session.add_all([uhc, bcbs]); db.session.commit()
    return c, uhc, bcbs


def test_apply_death_marks_the_person(app, agency, db_session):
    from app.deceased import apply_death
    with app.app_context():
        c, _, _ = _person(app, agency)
        assert apply_death(c, date(2026, 4, 30), "uhc_commission", agency.id)
        assert c.deceased_date == date(2026, 4, 30)


def test_it_terms_only_the_reporting_carriers_policy(app, agency, db_session):
    """Carrier-scoped: UHC's death must not term a BCBS Medigap."""
    from app.deceased import apply_death
    with app.app_context():
        c, uhc, bcbs = _person(app, agency)
        apply_death(c, date(2026, 4, 30), "uhc_commission", agency.id, carrier="UHC")
        assert uhc.status == "termed"
        assert uhc.term_date == date(2026, 4, 30)
        assert bcbs.status == "active"


def test_without_a_carrier_it_terms_nothing(app, agency, db_session):
    """Manual marking suppresses outreach but never terms a policy."""
    from app.deceased import apply_death
    with app.app_context():
        c, uhc, bcbs = _person(app, agency)
        apply_death(c, date(2026, 4, 30), "agent", agency.id)
        assert uhc.status == "active" and bcbs.status == "active"


def test_it_never_clears_an_existing_mark(app, agency, db_session):
    from app.deceased import apply_death
    with app.app_context():
        c, _, _ = _person(app, agency)
        apply_death(c, date(2026, 4, 30), "uhc_commission", agency.id)
        assert apply_death(c, None, "uhc_commission", agency.id) is False
        assert c.deceased_date == date(2026, 4, 30)


def test_death_date_read_from_a_uhc_fact():
    from types import SimpleNamespace
    from app.deceased import death_date_from_uhc_fact
    f = SimpleNamespace(term_reason_raw="Death", term_date=date(2026, 4, 30))
    assert death_date_from_uhc_fact(f) == date(2026, 4, 30)


def test_other_term_reasons_are_not_deaths():
    from types import SimpleNamespace
    from app.deceased import death_date_from_uhc_fact
    for reason in ("Member Termination", "Enrollment in Another Plan",
                   "Star Plan Change", ""):
        f = SimpleNamespace(term_reason_raw=reason, term_date=date(2026, 4, 30))
        assert death_date_from_uhc_fact(f) is None


def test_death_matching_is_case_insensitive():
    from types import SimpleNamespace
    from app.deceased import death_date_from_uhc_fact
    f = SimpleNamespace(term_reason_raw="DEATH", term_date=date(2026, 4, 30))
    assert death_date_from_uhc_fact(f) == date(2026, 4, 30)


def test_a_policy_created_by_the_death_row_itself_is_termed(app, agency, db_session):
    """The ordering bug this test exists to catch.

    When a UHC commission row reporting a Death resolves to a customer who has no
    existing UHC policy, _attach CREATES one via _attach_policy (which always sets
    status='active'). If apply_death runs BEFORE that creation it terms only the
    rows already in the database, and the row the death itself produced is left
    active forever — the customer reads as deceased while their newest policy for
    the reporting carrier stays live.
    """
    from datetime import date
    from app.extensions import db
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer
    from app.models import Customer, Policy

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                     full_name="Linda Bost", mbi="6MV0WK0MP06")
        db.session.add(c); db.session.commit()
        assert Policy.query.filter_by(agency_id=agency.id, customer_id=c.id).count() == 0

        fact = MemberFact(
            carrier="UHC", full_name="Linda Bost", first_name="Linda", last_name="Bost",
            mbi="6MV0WK0MP06", carrier_member_id="6MV0WK0MP06",
            term_date=date(2026, 5, 31), term_reason_raw="Death",
            row_class=RowClass.RENEWAL, amount=28.92, source_ref="uhc::0::1")
        resolve_customer(fact, agency_id=agency.id, agent_id=None,
                         source="commission_import")
        db.session.commit()

        assert Customer.query.get(c.id).deceased_date == date(2026, 5, 31)
        pols = Policy.query.filter_by(agency_id=agency.id, customer_id=c.id).all()
        assert pols, "the death row should still have produced a policy"
        assert all(p.status == "termed" for p in pols), (
            "the policy created BY the death row was left active — apply_death ran "
            "before _attach_policy")


def test_bob_death_applies_when_resolved_by_exact_id(app, agency, db_session):
    """A BOB row carrying a Deceased Date DOES mark the customer when
    resolve_customer found them by an exact unique ID (here: MBI)."""
    from app.extensions import db
    from app.models import Customer, Policy
    from app.upload import _upsert_customer_from_policy

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                     full_name="Linda Bost", dob=date(1945, 3, 1),
                     mbi="6MV0WK0MP06")
        db.session.add(c); db.session.commit()
        # An existing policy so this resolves via the "mbi" tier's crosswalk hit
        # rather than creating a fresh one — either way match_path == "mbi".
        p = Policy(agency_id=agency.id, carrier="Humana", member_id="6MV0WK0MP06",
                   mbi="6MV0WK0MP06", status="active", customer_id=c.id,
                   full_name="Linda Bost")
        db.session.add(p); db.session.commit()

        rec = {
            "carrier": "Humana", "first_name": "Linda", "last_name": "Bost",
            "full_name": "Linda Bost", "mbi": "6MV0WK0MP06", "member_id": "6MV0WK0MP06",
            "dob": date(1945, 3, 1), "deceased_date": date(2026, 6, 15),
        }
        _upsert_customer_from_policy(rec, agent_id=None, batch_id=None, agency_id=agency.id)
        db.session.commit()

        assert Customer.query.get(c.id).deceased_date == date(2026, 6, 15)


def test_bob_death_does_not_apply_when_resolved_only_by_name_and_dob(app, agency, db_session):
    """Regression: a BOB row must NOT mark someone deceased when resolve_customer
    only matched them by name+DOB (composite or suggest_link) rather than an
    exact unique carrier ID. Marking the wrong person deceased silently drops a
    LIVING customer from their agent's book.

    No MBI, no carrier_member_id anywhere on file — a masked-MBI Humana row
    (real-world case: all 5 August deceased rows had MBI "XXXXX...") can only
    resolve here via name+DOB, i.e. the suggest_link tier (it creates a fresh
    stub customer rather than reusing the name+DOB match) — never an exact ID.
    We assert against BOTH the pre-existing customer AND every customer the
    call produced, so the bug can't hide by landing on a different (stub)
    Customer row than the one this test set up.
    """
    from app.extensions import db
    from app.models import Customer
    from app.upload import _upsert_customer_from_policy

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                     full_name="Linda Bost", dob=date(1945, 3, 1))
        db.session.add(c); db.session.commit()
        assert c.deceased_date is None

        rec = {
            "carrier": "Humana", "first_name": "Linda", "last_name": "Bost",
            "full_name": "Linda Bost", "mbi": None, "member_id": None,
            "dob": date(1945, 3, 1), "deceased_date": date(2026, 6, 15),
        }
        _upsert_customer_from_policy(rec, agent_id=None, batch_id=None, agency_id=agency.id)
        db.session.commit()

        marked = Customer.query.filter(
            Customer.agency_id == agency.id, Customer.deceased_date.isnot(None)
        ).all()
        assert marked == [], (
            "a name+DOB-only resolution must never mark ANY customer deceased "
            f"(found {[(m.id, m.full_name) for m in marked]}) — the spec requires "
            "exact unique-ID matching only (MBI or carrier member id), no "
            "name/DOB fuzzy fallback")
        assert Customer.query.get(c.id).deceased_date is None


def test_bob_row_with_no_deceased_date_is_unaffected(app, agency, db_session):
    from app.extensions import db
    from app.models import Customer
    from app.upload import _upsert_customer_from_policy

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                     full_name="Linda Bost", dob=date(1945, 3, 1),
                     mbi="6MV0WK0MP06")
        db.session.add(c); db.session.commit()

        rec = {
            "carrier": "Humana", "first_name": "Linda", "last_name": "Bost",
            "full_name": "Linda Bost", "mbi": "6MV0WK0MP06", "member_id": "6MV0WK0MP06",
            "dob": date(1945, 3, 1),
        }
        _upsert_customer_from_policy(rec, agent_id=None, batch_id=None, agency_id=agency.id)
        db.session.commit()

        assert Customer.query.get(c.id).deceased_date is None
