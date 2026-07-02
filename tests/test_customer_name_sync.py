import pytest
from app.extensions import db
from app.models import Customer, Agency


@pytest.fixture
def ctx(db_session, app, agency):
    """Fixture that yields the agency_id for use in tests."""
    return agency.id


def test_full_name_synced_from_parts_on_insert(ctx, db_session, app):
    with app.app_context():
        c = Customer(agency_id=ctx, first_name="John", last_name="Connelly")
        db.session.add(c); db.session.commit()
        assert c.full_name == "John Connelly"


def test_full_name_resynced_when_human_edits_first_name(ctx, db_session, app):
    with app.app_context():
        c = Customer(agency_id=ctx, first_name="Jon", last_name="Smith")
        db.session.add(c); db.session.commit()
        assert c.full_name == "Jon Smith"
        c.first_name = "John"            # human corrects a carrier typo
        db.session.commit()
        assert c.full_name == "John Smith"   # event resynced, edit NOT blocked


def test_blank_first_name_keeps_raw_full_name(ctx, db_session, app):
    with app.app_context():
        # commission stub: name only in full_name, blank first/last
        c = Customer(agency_id=ctx, first_name="", last_name="", full_name="CONNELLY, JOHN")
        db.session.add(c); db.session.commit()
        assert c.full_name == "CONNELLY, JOHN"   # event did NOT clobber it to " "


def test_preferred_name_column_exists_and_defaults_null(ctx):
    c = Customer(agency_id=ctx, first_name="Donald", last_name="Horstmann")
    db.session.add(c); db.session.commit()
    assert c.preferred_name is None
    c.preferred_name = "Craig"
    db.session.commit()
    assert c.preferred_name == "Craig"
    assert c.first_name == "Donald"   # legal name unchanged


def test_address_as_prefers_goes_by_then_legal_first(ctx):
    from app.names import address_as
    c = Customer(agency_id=ctx, first_name="Donald", last_name="Horstmann")
    db.session.add(c); db.session.commit()
    assert address_as(c) == "Donald"          # no preferred set -> legal first
    c.preferred_name = "Craig"; db.session.commit()
    assert address_as(c) == "Craig"           # preferred wins for greetings


def test_preferred_name_is_a_provenance_editable_field():
    from app.customer_provenance import PROVENANCE_FIELDS
    assert "preferred_name" in PROVENANCE_FIELDS


# ---------------------------------------------------------------------------
# Guard / characterization tests (Task 3.5)
# ---------------------------------------------------------------------------

from app.integrity import _norm_name
from app.names import normalize_person_name


def test_storage_and_matcher_agree_on_identity():
    """A cluster a human can SEE (same person, messy shapes) must be one the engine can
    MERGE: after normalization, the matcher key is identical across shape variants."""
    # storage normalization of the messy shapes -> canonical full_name
    shapes = ["CONNELLY, JOHN", "John Connelly", "john  connelly"]
    canon_fulls = []
    for s in shapes:
        first, mi, last, full = normalize_person_name(s)
        canon_fulls.append(f"{first} {last}".strip())
    # the matcher key must be identical for all canonical forms (so they cluster + merge)
    keys = {_norm_name(f) for f in canon_fulls}
    assert len(keys) == 1, f"matcher disagrees across canonical shapes: {keys}"


def test_normalized_row_is_not_reflagged_as_drift(ctx):
    """A row the backfill 'fixed' (full_name == first+last) must NOT be seen as drift by
    the sync event on the next write."""
    c = Customer(agency_id=ctx, first_name="John", last_name="Connelly")
    db.session.add(c); db.session.commit()            # event sets full_name
    before = c.full_name
    c.phone_primary = "828-555-0000"                  # unrelated edit triggers before_update
    db.session.commit()
    assert c.full_name == before == "John Connelly"   # stable, no re-drift
