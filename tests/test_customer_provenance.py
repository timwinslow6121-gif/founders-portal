"""
tests/test_customer_provenance.py

Tests for the customer field-provenance engine: precedence, human writes, conflict
lifecycle, round-trip. SQLite in-memory via conftest fixtures. Mirrors
tests/test_plan_provenance.py.
"""
from datetime import date


def test_provenance_columns_exist(db_session, app, agency):
    from app.extensions import db
    from app.models import Customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
                     field_provenance=None, has_unresolved_conflicts=False)
        db.session.add(c)
        db.session.commit()
        assert c.field_provenance is None
        assert c.has_unresolved_conflicts is False


def test_constants_and_empty_reads(db_session, app, agency):
    from app import customer_provenance as cp
    from app.models import Customer
    from app.extensions import db

    assert cp.TRUST_ORDER == {"carrier_import": 1, "agent_entered": 2, "human_verified": 3}
    assert "mbi" in cp.PROVENANCE_FIELDS and "zip_code" in cp.PROVENANCE_FIELDS
    assert "id" not in cp.PROVENANCE_FIELDS and "full_name" not in cp.PROVENANCE_FIELDS

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B")
        db.session.add(c); db.session.flush()
        assert cp.get_field(c, "zip_code") is None
        assert cp.trust_of(c, "zip_code") is None


def test_set_human_value_writes_column_and_meta(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.models import Customer
    from app.extensions import db

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B")
        db.session.add(c); db.session.flush()

        cp.set_human_value(c, "zip_code", "28205", agent_user)
        db.session.flush()

        assert c.zip_code == "28205"
        rec = cp.get_field(c, "zip_code")
        assert rec["value"] == "28205"
        assert rec["trust"] == "agent_entered"
        assert rec["source"] == "agent_edit"
        assert rec["updated_by"] == agent_user.name
        assert len(rec["history"]) == 1
        assert c.manually_edited is True

        cp.set_human_value(c, "zip_code", "28202", agent_user, note="fixed typo", verify=True)
        db.session.flush()
        assert c.zip_code == "28202"
        rec = cp.get_field(c, "zip_code")
        assert rec["trust"] == "human_verified"
        assert rec["source"] == "aj_verified"
        assert len(rec["history"]) == 2
        assert rec["history"][-1]["note"] == "fixed typo"


def test_set_human_value_dob_serializes(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.models import Customer
    from app.extensions import db
    from datetime import date

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B")
        db.session.add(c); db.session.flush()
        cp.set_human_value(c, "dob", date(1956, 8, 28), agent_user)
        db.session.flush()
        assert c.dob == date(1956, 8, 28)
        assert cp.get_field(c, "dob")["value"] == "1956-08-28"
