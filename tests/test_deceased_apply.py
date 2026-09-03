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
