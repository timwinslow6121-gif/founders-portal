"""
tests/test_effective_date_never_moves_forward.py

UHC's September 2026 book of business added a policyEffectiveDate column the
August export did not have, and pre-loaded the 2027 plan year: every member whose
MA/MAPD renews on 1 January carries `2027-01-01`. That date is REAL and is UHC's.

The bug was ours. _import_bob_row assigned

    existing.effective_date = rec["effective_date"]

unconditionally, so a member enrolled in 2022 was rewritten to start 2027-01-01
and the original was lost. 2,037 policies were overwritten; 2,017 were restored
from the 2026-09-01 nightly backup on 2026-09-03.

THE RULE (Tim, 2026-08-28 — the Elva Sprouse precedent, reaffirmed 09-03): a
policy's effective date is when coverage BEGAN, not when the current contract year
took over. A BOB may correct a date backwards or fill a blank one; it may never
push an existing date FORWARD.

This guard is carrier-agnostic on purpose. Any carrier that pre-loads next year's
plan data — routine in AEP season — would otherwise do the same damage.
"""
from datetime import date


def _rec(**kw):
    rec = dict(carrier="UHC", member_id="1AA1AA1AA11", mbi="1AA1AA1AA11",
               first_name="Linda", last_name="Bost", full_name="Linda Bost",
               plan_name="AARP Medicare Advantage NC-15", plan_type="MA",
               status="active", effective_date=date(2027, 1, 1), term_date=None,
               dob=date(1950, 3, 2), phone="", county="", address1="", city="",
               state="NC", zip_code="", agent_id="")
    rec.update(kw)
    return rec


def _seed(app, agency, eff):
    from app.extensions import db
    from app.models import Customer, Policy
    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                     full_name="Linda Bost", mbi="1AA1AA1AA11")
        db.session.add(c); db.session.flush()
        p = Policy(agency_id=agency.id, carrier="UHC", member_id="1AA1AA1AA11",
                   mbi="1AA1AA1AA11", full_name="Linda Bost", status="active",
                   customer_id=c.id, effective_date=eff)
        db.session.add(p); db.session.commit()
        return p.id


def _import(app, agency, rec):
    from app.extensions import db
    from app.models import ImportBatch, Policy
    from app.upload import _import_bob_row
    with app.app_context():
        batch = ImportBatch(agency_id=agency.id, carrier="UHC",
                            filename="uhc.xlsx", status="pending")
        db.session.add(batch); db.session.flush()
        _import_bob_row(rec, batch, agency.id, None, date.today(), [])
        db.session.commit()
        return Policy.query.filter_by(agency_id=agency.id,
                                      member_id=rec["member_id"]).first().effective_date


def test_a_future_date_never_replaces_an_existing_one(app, agency, db_session):
    """The reported bug: UHC's pre-loaded 2027-01-01 overwrote a 2023 enrollment."""
    _seed(app, agency, date(2023, 1, 1))
    assert _import(app, agency, _rec()) == date(2023, 1, 1)


def test_an_earlier_date_still_corrects_the_record(app, agency, db_session):
    """Earliest wins — a BOB carrying an older true start date must be adopted."""
    _seed(app, agency, date(2026, 1, 1))
    assert _import(app, agency, _rec(effective_date=date(2022, 4, 1))) == date(2022, 4, 1)


def test_a_blank_effective_date_is_filled(app, agency, db_session):
    _seed(app, agency, None)
    assert _import(app, agency, _rec(effective_date=date(2026, 7, 1))) == date(2026, 7, 1)


def test_a_missing_date_in_the_file_leaves_the_record_alone(app, agency, db_session):
    """The August UHC export had no effective-date column at all — a parser
    returning None must not blank a date we already hold."""
    _seed(app, agency, date(2024, 5, 1))
    assert _import(app, agency, _rec(effective_date=None)) == date(2024, 5, 1)


def test_the_guard_is_carrier_agnostic(app, agency, db_session):
    """Any carrier pre-loading next year's plan data would do the same damage."""
    _seed(app, agency, date(2023, 1, 1))
    assert _import(app, agency, _rec(carrier="UHC",
                                     effective_date=date(2028, 1, 1))) == date(2023, 1, 1)
