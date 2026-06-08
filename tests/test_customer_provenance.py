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


def _fresh(db, agency):
    from app.models import Customer
    c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B")
    db.session.add(c); db.session.flush()
    return c


def test_import_writes_empty_field(db_session, app, agency):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        action = cp.set_import_value(c, "zip_code", "28205", "bob_import")
        db.session.flush()
        assert action == "written"
        assert c.zip_code == "28205"
        assert cp.trust_of(c, "zip_code") == "carrier_import"


def test_import_skips_blank_incoming(db_session, app, agency):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        assert cp.set_import_value(c, "zip_code", "", "bob_import") == "skipped"
        assert cp.set_import_value(c, "zip_code", None, "bob_import") == "skipped"
        assert c.zip_code is None
        assert cp.get_field(c, "zip_code") is None


def test_import_confirms_same_value(db_session, app, agency):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_import_value(c, "zip_code", "28205", "bob_import"); db.session.flush()
        action = cp.set_import_value(c, "zip_code", "28205", "commission_import")
        assert action == "confirmed"
        assert c.zip_code == "28205"


def test_import_overwrites_other_carrier_value(db_session, app, agency):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_import_value(c, "zip_code", "28205", "bob_import"); db.session.flush()
        action = cp.set_import_value(c, "zip_code", "28202", "commission_import")
        assert action == "written"
        assert c.zip_code == "28202"


def test_import_conflicts_with_agent_value(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "zip_code", "28205", agent_user); db.session.flush()
        action = cp.set_import_value(c, "zip_code", "28202", "bob_import")
        db.session.flush()
        assert action == "conflict_flagged"
        assert c.zip_code == "28205"
        assert c.has_unresolved_conflicts is True
        conflicts = cp.list_conflicts(c)
        assert len(conflicts) == 1
        assert conflicts[0]["field"] == "zip_code"
        assert conflicts[0]["incoming"]["value"] == "28202"


def test_import_conflict_is_idempotent(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "zip_code", "28205", agent_user); db.session.flush()
        cp.set_import_value(c, "zip_code", "28202", "bob_import"); db.session.flush()
        cp.set_import_value(c, "zip_code", "28202", "bob_import"); db.session.flush()
        assert len(cp.list_conflicts(c)) == 1


def test_resolve_conflict_keep_current(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "zip_code", "28205", agent_user); db.session.flush()
        cp.set_import_value(c, "zip_code", "28202", "bob_import"); db.session.flush()

        cp.resolve_conflict(c, "zip_code", "keep_current", agent_user); db.session.flush()
        assert c.zip_code == "28205"
        assert cp.trust_of(c, "zip_code") == "human_verified"
        assert c.has_unresolved_conflicts is False
        assert cp.list_conflicts(c) == []


def test_resolve_conflict_take_incoming(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "zip_code", "28205", agent_user); db.session.flush()
        cp.set_import_value(c, "zip_code", "28202", "bob_import"); db.session.flush()

        cp.resolve_conflict(c, "zip_code", "take_incoming", agent_user); db.session.flush()
        assert c.zip_code == "28202"
        assert cp.trust_of(c, "zip_code") == "human_verified"
        assert c.has_unresolved_conflicts is False


def test_resolve_conflict_no_open_conflict_is_safe_noop(db_session, app, agency, agent_user):
    """resolve_conflict with no open conflict must NOT null/overwrite the field
    (guards against a stale/double-click in the future conflict-queue UI)."""
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "zip_code", "28205", agent_user); db.session.flush()
        # no conflict has been flagged on zip_code
        assert cp.list_conflicts(c) == []

        # both choices must be safe no-ops when there's nothing to resolve
        cp.resolve_conflict(c, "zip_code", "take_incoming", agent_user); db.session.flush()
        assert c.zip_code == "28205"                       # NOT nulled
        assert cp.trust_of(c, "zip_code") == "agent_entered"

        cp.resolve_conflict(c, "zip_code", "keep_current", agent_user); db.session.flush()
        assert c.zip_code == "28205"                       # unchanged
        assert cp.trust_of(c, "zip_code") == "agent_entered"
        assert c.has_unresolved_conflicts is False


def test_keep_current_records_rejected_then_suppresses_reimport(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "email", "m@old.com", agent_user); db.session.flush()
        cp.set_import_value(c, "email", "mark@gmail.com", "bob_import"); db.session.flush()
        cp.resolve_conflict(c, "email", "keep_current", agent_user); db.session.flush()
        action = cp.set_import_value(c, "email", "mark@gmail.com", "bob_import")
        db.session.flush()
        assert action == "suppressed"
        assert cp.list_conflicts(c) == []
        assert c.has_unresolved_conflicts is False
        assert c.email == "m@old.com"


def test_new_different_value_still_flags_after_rejection(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "email", "m@old.com", agent_user); db.session.flush()
        cp.set_import_value(c, "email", "mark@gmail.com", "bob_import"); db.session.flush()
        cp.resolve_conflict(c, "email", "keep_current", agent_user); db.session.flush()
        action = cp.set_import_value(c, "email", "mark@newjob.com", "bob_import")
        db.session.flush()
        assert action == "conflict_flagged"
        assert len(cp.list_conflicts(c)) == 1


def test_take_incoming_records_no_rejection(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "email", "m@old.com", agent_user); db.session.flush()
        cp.set_import_value(c, "email", "mark@gmail.com", "bob_import"); db.session.flush()
        cp.resolve_conflict(c, "email", "take_incoming", agent_user); db.session.flush()
        assert c.email == "mark@gmail.com"
        rec = cp.get_field(c, "email")
        assert rec.get("rejected_values", []) == []


def test_fresh_human_edit_clears_rejected_values(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "email", "m@old.com", agent_user); db.session.flush()
        cp.set_import_value(c, "email", "mark@gmail.com", "bob_import"); db.session.flush()
        cp.resolve_conflict(c, "email", "keep_current", agent_user); db.session.flush()
        assert cp.get_field(c, "email").get("rejected_values") == ["mark@gmail.com"]
        cp.set_human_value(c, "email", "m@new.com", agent_user); db.session.flush()
        assert cp.get_field(c, "email").get("rejected_values", []) == []
        action = cp.set_import_value(c, "email", "mark@gmail.com", "bob_import")
        assert action == "conflict_flagged"
