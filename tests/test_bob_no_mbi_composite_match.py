"""
tests/test_bob_no_mbi_composite_match.py

Every monthly Humana BOB upload created a fresh duplicate CUSTOMER for members
whose row carries no MBI (Humana masks it). The 2026-09-01 upload alone made 46:

    cust  8219  Anastacio Villegas  dob=1956-05-02  mbi='5EN4NW3VF63'  (June)
    cust 14962  Anastacio Villegas  dob=1956-05-02  mbi=None           (September)

The BOB identity path went MBI -> _find_name_dob_match, and that helper
DELIBERATELY creates a stub and files a human suggestion, because name+DOB
alone is not trusted to auto-match (§6 prevention boundary -- two people can
share a name and birthday).

But _composite_match already exists for exactly this: name + DOB + a
corroborating zip or phone. It was simply never called on this branch. On the
real 48 clusters it matches 46 (45 by zip, 46 by phone); the 2 it declines are
Cheatham and Mullis, which genuinely lack corroborating data and SHOULD stay
human decisions.

So this closes the recurring duplicate without weakening the boundary.
"""


def _bob_rec(**kw):
    from datetime import date
    rec = dict(carrier="Humana", member_id="H90477416", mbi="",
               first_name="Anastacio", last_name="Villegas",
               full_name="Anastacio Villegas", dob=date(1956, 5, 2),
               plan_name="Gold Plus", plan_type="MA", status="active",
               effective_date=None, term_date=None, agent_id=None,
               phone="704-555-0134", zip_code="28025", city="Concord",
               state="NC", address1="1 Main St", county="Cabarrus")
    rec.update(kw)
    return rec


def _seed(app, agency, **kw):
    """An existing customer from a prior BOB, WITH an MBI."""
    from app.extensions import db
    from app.models import Customer
    from datetime import date
    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Anastacio",
                     last_name="Villegas", full_name="Anastacio Villegas",
                     dob=date(1956, 5, 2), mbi="5EN4NW3VF63",
                     phone_primary=kw.get("phone", "704-555-0134"),
                     zip_code=kw.get("zip_code", "28025"))
        db.session.add(c); db.session.commit()
        return c.id


def _resolve(app, agency, rec):
    from app.commission.resolver import resolve_customer
    from app.upload import member_fact_from_bob_rec
    with app.app_context():
        return resolve_customer(member_fact_from_bob_rec(rec), agency_id=agency.id,
                                agent_id=None, batch_id=None, source="bob")


def test_no_mbi_bob_row_matches_existing_customer_on_name_dob_phone(app, agency, db_session):
    """The reported bug: a Humana BOB row with no MBI must NOT create a
    second customer when name, DOB and phone all agree."""
    cid = _seed(app, agency)
    r = _resolve(app, agency, _bob_rec(mbi=""))
    assert r.customer is not None
    assert r.customer.id == cid, "created a duplicate customer instead of matching"
    assert not r.created_customer


def test_matching_on_zip_alone_is_enough(app, agency, db_session):
    cid = _seed(app, agency)
    r = _resolve(app, agency, _bob_rec(mbi="", phone=""))
    assert r.customer.id == cid


def test_name_and_dob_alone_still_refuses_to_auto_match(app, agency, db_session):
    """The §6 boundary holds: without a corroborating zip or phone, two people
    sharing a name and birthday must NOT be merged automatically."""
    cid = _seed(app, agency)
    r = _resolve(app, agency, _bob_rec(mbi="", phone="", zip_code=""))
    assert r.customer.id != cid, "auto-matched on name+DOB alone — boundary broken"


def test_a_different_dob_never_matches(app, agency, db_session):
    cid = _seed(app, agency)
    r = _resolve(app, agency, _bob_rec(mbi="", dob=__import__("datetime").date(1970, 1, 1)))
    assert r.customer.id != cid


def test_a_row_with_an_mbi_still_takes_the_mbi_path(app, agency, db_session):
    cid = _seed(app, agency)
    r = _resolve(app, agency, _bob_rec(mbi="5EN4NW3VF63"))
    assert r.customer.id == cid
