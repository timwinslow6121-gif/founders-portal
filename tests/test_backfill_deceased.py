"""tests/test_backfill_deceased.py"""
from datetime import date


def test_an_mbi_matching_one_customer_is_marked(app, agency, db_session):
    from app.extensions import db
    from app.models import Customer
    from scripts.backfill_deceased import resolve_one
    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                     full_name="Linda Bost", mbi="6MV0WK0MP06")
        db.session.add(c); db.session.commit()
        got, why = resolve_one(agency.id, mbi="6MV0WK0MP06")
        assert got is not None and got.id == c.id and why == ""


def test_an_unmatched_id_marks_nobody(app, agency, db_session):
    from scripts.backfill_deceased import resolve_one
    with app.app_context():
        got, why = resolve_one(agency.id, mbi="NOSUCHMBI99")
        assert got is None and "no customer" in why


def test_an_ambiguous_id_marks_nobody(app, agency, db_session):
    """0 or >1 must refuse — marking the wrong person erases a living customer."""
    from app.extensions import db
    from app.models import Customer
    from scripts.backfill_deceased import resolve_one
    with app.app_context():
        for n in ("A", "B"):
            db.session.add(Customer(agency_id=agency.id, first_name=n, last_name="X",
                                    full_name=f"{n} X", mbi="DUP1DUP1DU1"))
        db.session.commit()
        got, why = resolve_one(agency.id, mbi="DUP1DUP1DU1")
        assert got is None and "2 customers" in why


def test_it_never_matches_on_a_name(app, agency, db_session):
    """No name or DOB fallback anywhere — an ID miss is a refusal, full stop."""
    from app.extensions import db
    from app.models import Customer
    from scripts.backfill_deceased import resolve_one
    with app.app_context():
        db.session.add(Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                                full_name="Linda Bost", mbi="OTHERMBI001"))
        db.session.commit()
        got, _ = resolve_one(agency.id, mbi="6MV0WK0MP06")
        assert got is None
