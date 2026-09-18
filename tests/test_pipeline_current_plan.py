"""Resolving 'their current plan' -- there is no customers.current_plan_id."""
import datetime as dt


def _plan(db, agency, cms, ptype, name):
    from app.models import Plan
    p = Plan(agency_id=agency.id, carrier="Test", plan_name=name, year=2026,
             plan_type=ptype, cms_plan_id=cms)
    db.session.add(p)
    db.session.commit()
    return p


def _policy(db, agency, customer, plan, eff, county="Cabarrus", status="active"):
    from app.models import Policy
    po = Policy(agency_id=agency.id, customer_id=customer.id, carrier="Test",
                member_id=f"M{plan.id}-{eff.year}", plan_id=plan.id, status=status,
                effective_date=eff, county=county)
    db.session.add(po)
    db.session.commit()
    return po


def test_single_active_policy_resolves(db_session, app, agency, customer):
    from app.extensions import db
    from app.pipeline.plans import current_plan_for
    with app.app_context():
        p = _plan(db, agency, "H1234-001", "mapd", "Gold")
        _policy(db, agency, customer, p, dt.date(2026, 1, 1))
        got = current_plan_for(customer.id, agency.id)
        assert got["plan_id"] == p.id
        assert got["lane"] == "primary_medical"
        assert got["ambiguous"] is False


def test_medigap_plus_pdp_picks_the_pdp_not_the_newest(db_session, app, agency, customer):
    """The real production case: 15 customers hold medigap+pdp. AEP triage is
    about the Part C/D plan, so the PDP must win even when the Medigap policy
    has the later effective date."""
    from app.extensions import db
    from app.pipeline.plans import current_plan_for
    with app.app_context():
        pdp = _plan(db, agency, "S5884-187", "pdp", "Value Rx")
        mg  = _plan(db, agency, "MEDIGAP-N", "medigap", "Plan N")
        _policy(db, agency, customer, pdp, dt.date(2026, 1, 1))
        _policy(db, agency, customer, mg,  dt.date(2026, 6, 1))   # newer
        got = current_plan_for(customer.id, agency.id)
        assert got["plan_id"] == pdp.id, "PDP must win over a newer Medigap"
        assert got["lane"] == "primary_medical"


def test_two_primary_medical_picks_newest_and_flags_ambiguous(db_session, app, agency, customer):
    from app.extensions import db
    from app.pipeline.plans import current_plan_for
    with app.app_context():
        a = _plan(db, agency, "H1111-001", "mapd", "A")
        b = _plan(db, agency, "H2222-001", "mapd", "B")
        _policy(db, agency, customer, a, dt.date(2026, 1, 1))
        _policy(db, agency, customer, b, dt.date(2026, 7, 1))
        got = current_plan_for(customer.id, agency.id)
        assert got["plan_id"] == b.id
        assert got["ambiguous"] is True


def test_county_falls_back_to_policy_when_customer_blank(db_session, app, agency, customer):
    from app.extensions import db
    from app.pipeline.plans import current_plan_for
    with app.app_context():
        customer.county = None
        db.session.commit()
        p = _plan(db, agency, "H1234-001", "mapd", "Gold")
        _policy(db, agency, customer, p, dt.date(2026, 1, 1), county="Rowan")
        assert current_plan_for(customer.id, agency.id)["county"] == "Rowan"


def test_termed_policy_is_not_current(db_session, app, agency, customer):
    from app.extensions import db
    from app.pipeline.plans import current_plan_for
    with app.app_context():
        p = _plan(db, agency, "H1234-001", "mapd", "Gold")
        _policy(db, agency, customer, p, dt.date(2026, 1, 1), status="termed")
        assert current_plan_for(customer.id, agency.id) is None
