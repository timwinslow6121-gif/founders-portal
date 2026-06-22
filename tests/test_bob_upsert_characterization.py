"""
tests/test_bob_upsert_characterization.py

Pins the CURRENT observable behavior of _upsert_customer_from_policy BEFORE it is
refactored to delegate to resolve_customer(). If a test here breaks during the
refactor, the refactor changed BOB behavior — investigate, don't just update.
"""
from datetime import date


def test_bob_creates_customer_by_mbi(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer
    from app.upload import _upsert_customer_from_policy

    with app.app_context():
        rec = {
            "carrier": "UHC", "mbi": "8NP5GM6TK40",
            "first_name": "Ricky", "last_name": "Sweatt", "full_name": "Ricky Sweatt",
            "dob": date(1948, 3, 1), "phone": "7045550100",
            "address1": "1 Main St", "city": "Charlotte", "state": "NC",
            "zip_code": "28202", "county": "Mecklenburg",
            "plan_name": "UHC DSNP", "effective_date": date(2026, 1, 1),
        }
        _upsert_customer_from_policy(rec, agent_user.id, None, agency.id)
        db.session.commit()
        c = Customer.query.filter_by(mbi="8NP5GM6TK40", agency_id=agency.id).first()
        assert c is not None
        assert c.first_name == "Ricky"
        assert c.primary_agent_id == agent_user.id


def test_bob_does_not_overwrite_manually_edited_pii(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer
    from app.upload import _upsert_customer_from_policy

    with app.app_context():
        c = Customer(agency_id=agency.id, mbi="MBIEDIT01", first_name="Original",
                     last_name="Name", full_name="Original Name", phone_primary="111",
                     manually_edited=True, primary_agent_id=agent_user.id)
        db.session.add(c); db.session.commit()

        rec = {"carrier": "UHC", "mbi": "MBIEDIT01", "first_name": "Changed",
               "last_name": "Different", "phone": "999", "effective_date": date(2026, 1, 1)}
        _upsert_customer_from_policy(rec, agent_user.id, None, agency.id)
        db.session.commit()
        db.session.refresh(c)
        assert c.first_name == "Original"
        assert c.phone_primary == "111"


def test_bob_humana_matches_by_humana_id(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer
    from app.upload import _upsert_customer_from_policy

    with app.app_context():
        rec = {"carrier": "Humana", "mbi": None, "member_id": "HUM12345",
               "first_name": "Anna", "last_name": "Lee", "full_name": "Anna Lee",
               "effective_date": date(2026, 1, 1)}
        _upsert_customer_from_policy(rec, agent_user.id, None, agency.id)
        db.session.commit()
        c = Customer.query.filter_by(humana_id="HUM12345", agency_id=agency.id).first()
        assert c is not None


def test_bob_bcbs_aor_end_date_is_none(db_session, app, agency, agent_user):
    """UPDATED for task 2 (prevention boundary, §6): this rec has NO mbi, NO
    carrier_member_id, and NO dob — genuinely weak identity (a bare BCBS name
    row). Pre-prevention this fell through to an unconditional stub+policy;
    now it correctly enqueues a needs-identity MatchSuggestion instead of
    fabricating a customer off a name alone, so there is no AOR interval to
    assert on. Kept here (not deleted) so a future regression that makes weak
    identity create a phantom customer again is caught."""
    from app.extensions import db
    from app.models import Customer, CustomerAorHistory, MatchSuggestion
    from app.upload import _upsert_customer_from_policy

    with app.app_context():
        rec = {"carrier": "BCBS", "mbi": None, "first_name": "Bob", "last_name": "Cee",
               "full_name": "Bob Cee", "effective_date": date(2026, 1, 1),
               "term_date": date(2026, 12, 31)}
        _upsert_customer_from_policy(rec, agent_user.id, None, agency.id)
        db.session.commit()
        c = Customer.query.filter_by(agency_id=agency.id, last_name="Cee").first()
        assert c is None  # weak identity → no phantom customer created
        ms = MatchSuggestion.query.filter_by(agency_id=agency.id, confidence="weak_identity").first()
        assert ms is not None
