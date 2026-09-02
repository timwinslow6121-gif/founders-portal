"""
tests/test_resolver_policy_mbi_fallback.py

Commission import created a SECOND active policy for a member who already had
one from the BOB, whenever the carrier keys the two files differently:

    BOB row        member_id='8QN7HG8JM38'  mbi='8QN7HG8JM38'
    commission row carrier_member_id='D7A4R5'  mbi='8QN7HG8JM38'

_match_by_mbi correctly found the CUSTOMER by MBI, so both rows landed on one
person -- but _crosswalk looked up the POLICY by (carrier, member_id) alone,
missed it, and _attach_policy made a duplicate. The BOB path (upload.py) has
had an MBI fallback for exactly this reason; the resolver did not.

This is the bug that makes duplicates reappear on every monthly upload. It is
NOT the no-MBI case (Humana PID / BCBS member number) -- here the MBI is
present on BOTH rows and still missed.
"""


def _fact(**kw):
    from app.commission.resolver import MemberFact
    base = dict(carrier="Devoted", carrier_member_id="", mbi="", first_name="",
                last_name="", full_name="", plan_type="", effective_date=None,
                term_date=None, source_ref="devoted::x::1")
    base.update(kw)
    return MemberFact(**{k: v for k, v in base.items()
                         if k in MemberFact.__dataclass_fields__})


def _seed_bob_policy(app, agency):
    from app.extensions import db
    from app.models import Customer, Policy
    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Teresa", last_name="Pickler",
                     full_name="Teresa Pickler", mbi="8QN7HG8JM38")
        db.session.add(c); db.session.flush()
        p = Policy(agency_id=agency.id, carrier="Devoted",
                   member_id="8QN7HG8JM38", mbi="8QN7HG8JM38",
                   full_name="Teresa Pickler", status="active", customer_id=c.id)
        db.session.add(p); db.session.commit()
        return c.id, p.id


def test_crosswalk_finds_the_policy_by_mbi_when_member_id_differs(app, agency, db_session):
    """The carrier's commission id ('D7A4R5') differs from the BOB id, but the
    MBI is identical -- the existing policy must be found, not duplicated."""
    from app.commission.resolver import _crosswalk
    cid, pid = _seed_bob_policy(app, agency)
    with app.app_context():
        found = _crosswalk(_fact(carrier_member_id="D7A4R5", mbi="8QN7HG8JM38"),
                           agency.id)
        assert found is not None, "existing policy not found by MBI — duplicate incoming"
        assert found.id == pid


def test_crosswalk_still_prefers_an_exact_member_id_match(app, agency, db_session):
    """The MBI fallback must not override a direct (carrier, member_id) hit."""
    from app.commission.resolver import _crosswalk
    cid, pid = _seed_bob_policy(app, agency)
    with app.app_context():
        found = _crosswalk(_fact(carrier_member_id="8QN7HG8JM38",
                                 mbi="8QN7HG8JM38"), agency.id)
        assert found.id == pid


def test_crosswalk_does_not_match_across_carriers(app, agency, db_session):
    """A shared MBI across carriers is one PERSON, not one policy."""
    from app.commission.resolver import _crosswalk
    _seed_bob_policy(app, agency)
    with app.app_context():
        assert _crosswalk(_fact(carrier="UHC", carrier_member_id="X1",
                                mbi="8QN7HG8JM38"), agency.id) is None


def test_crosswalk_ignores_a_blank_mbi(app, agency, db_session):
    """A blank MBI must never match a policy whose mbi is also blank/NULL."""
    from app.extensions import db
    from app.models import Customer, Policy
    from app.commission.resolver import _crosswalk
    with app.app_context():
        c = Customer(agency_id=agency.id, full_name="No Mbi", first_name="No",
                     last_name="Mbi")
        db.session.add(c); db.session.flush()
        db.session.add(Policy(agency_id=agency.id, carrier="Devoted",
                              member_id="ONLY-ID", mbi=None, status="active",
                              customer_id=c.id, full_name="No Mbi"))
        db.session.commit()
        assert _crosswalk(_fact(carrier_member_id="OTHER", mbi=""), agency.id) is None
