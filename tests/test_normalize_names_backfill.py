import os
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("TESTING", "1")

from app import create_app
from app.extensions import db
from app.models import Customer, Agency
from scripts.normalize_customer_names import plan_name_changes
from sqlalchemy import text as sa_text


@pytest.fixture
def ctx():
    app = create_app()
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        RATELIMIT_ENABLED=False,
        SESSION_COOKIE_SECURE=False,
        REMEMBER_COOKIE_SECURE=False,
    )
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        yield ag.id
        db.session.remove(); db.drop_all()


def _c(agency_id, **kw):
    base = dict(agency_id=agency_id, first_name="", last_name="")
    base.update(kw); c = Customer(**base); db.session.add(c); db.session.flush(); return c


def test_blank_first_name_recovered_from_full_name(ctx):
    c = _c(ctx, first_name="", last_name="", full_name="CONNELLY, JOHN")
    db.session.commit()
    changes = plan_name_changes(ctx)
    ch = [x for x in changes if x["id"] == c.id][0]
    assert ch["new_first"] == "John" and ch["new_last"] == "Connelly"


def test_folded_mi_with_dirty_last_normalizes_the_last(ctx):
    # I-1 (opus review): a row already MI-folded in first_name but with an ALL-CAPS
    # last must still get the LAST title-cased (never trust a stored last to be clean).
    c = _c(ctx, first_name="Katherine D.", last_name="BRYANT",
           full_name="BRYANT, KATHERINE")
    db.session.commit()
    ch = [x for x in plan_name_changes(ctx) if x["id"] == c.id][0]
    assert ch["new_first"] == "Katherine D."
    assert ch["new_last"] == "Bryant"                 # was ALL-CAPS, now clean
    assert ch["new_full"] == "Katherine D. Bryant"


def test_folded_mi_fully_clean_is_not_a_change(ctx):
    # idempotency: an already-clean folded row is a no-op (no re-drift on re-run).
    c = _c(ctx, first_name="Katherine D.", last_name="Bryant",
           full_name="Katherine D. Bryant")
    db.session.commit()
    assert [x for x in plan_name_changes(ctx) if x["id"] == c.id] == []


def test_all_caps_and_comma_normalized(ctx):
    c = _c(ctx, first_name="", last_name="", full_name="BRYANT D,KATHERINE")
    db.session.commit()
    ch = [x for x in plan_name_changes(ctx) if x["id"] == c.id][0]
    assert ch["new_first"] == "Katherine D." and ch["new_last"] == "Bryant"


def test_already_clean_is_not_a_change(ctx):
    c = _c(ctx, first_name="John", last_name="Smith", full_name="John Smith")
    db.session.commit()
    assert [x for x in plan_name_changes(ctx) if x["id"] == c.id] == []


def test_manually_edited_is_skipped(ctx):
    c = _c(ctx, first_name="", last_name="", full_name="SMITH, BOB", manually_edited=True)
    db.session.commit()
    assert [x for x in plan_name_changes(ctx) if x["id"] == c.id] == []


def test_already_normalized_mi_row_is_not_a_change(ctx):
    """A row already in MI-folded canonical form must produce NO change."""
    # This is the state after a first-pass fix of "BRYANT D,KATHERINE".
    # Before the fix, _desired() re-parses "Katherine D. Bryant" (no comma)
    # → first="Katherine", last="D. Bryant" which differs from stored first="Katherine D.",
    # so it flags the row as changed again (corruption on 2nd run).
    c = _c(ctx,
           first_name="Katherine D.",
           last_name="Bryant",
           full_name="Katherine D. Bryant")
    db.session.commit()
    assert [x for x in plan_name_changes(ctx) if x["id"] == c.id] == [], \
        "Row already in MI-folded form must not be flagged as a change"


def test_backfill_is_idempotent_end_to_end(ctx):
    """Apply the change from a messy row, then verify a second run produces no further change."""
    # Start: blank first/last, full_name in COMMA form
    c = _c(ctx, first_name="", last_name="", full_name="BRYANT D,KATHERINE")
    db.session.commit()

    # First pass: get the desired change
    changes = [x for x in plan_name_changes(ctx) if x["id"] == c.id]
    assert len(changes) == 1, "First pass should produce exactly one change"
    ch = changes[0]
    assert ch["new_first"] == "Katherine D." and ch["new_last"] == "Bryant"

    # Apply the change (simulate --apply)
    c.first_name = ch["new_first"]
    c.last_name  = ch["new_last"]
    c.full_name  = ch["new_full"]
    db.session.commit()

    # Second pass: must be a no-op
    second_pass = [x for x in plan_name_changes(ctx) if x["id"] == c.id]
    assert second_pass == [], \
        f"Second pass after applying changes must be empty, got: {second_pass}"


# ---------------------------------------------------------------------------
# NEW: middle-initial recovery from full_name when first/last already set
# ---------------------------------------------------------------------------

def _c_legacy(agency_id, first_name, last_name, full_name):
    """Insert a Customer row bypassing the before_insert sync event via raw SQL.
    This replicates legacy rows on prod where full_name was set before the sync
    event was added (or set manually), so first/last+full are inconsistent."""
    c = Customer(agency_id=agency_id, first_name=first_name, last_name=last_name)
    db.session.add(c)
    db.session.flush()  # assigns id; before_insert fires and sets full_name = first+last
    # Override the event-written full_name with the legacy value via raw SQL
    db.session.execute(
        sa_text("UPDATE customers SET full_name = :fn WHERE id = :id"),
        {"fn": full_name, "id": c.id},
    )
    db.session.commit()
    db.session.expire(c)  # force reload from DB on next access
    return c


def test_mi_recovered_from_full_name_when_parts_set(ctx):
    """first/last already set; full_name carries a MI that first_name lacks — recover it.
    This tests the legacy-data shape: 191 prod rows predate the before_insert sync event
    and have full_name in 'Last,First MI' form while first/last are already set."""
    c = _c_legacy(ctx, first_name="Colleen", last_name="Beaver", full_name="Beaver,Colleen E")
    ch = [x for x in plan_name_changes(ctx) if x["id"] == c.id][0]
    assert ch["new_first"] == "Colleen E."
    assert ch["new_last"] == "Beaver"
    assert ch["new_full"] == "Colleen E. Beaver"


def test_mi_recovery_case_insensitive_and_titlecases(ctx):
    """ALL-CAPS first/last/full should still produce a clean title-cased result with MI."""
    c = _c_legacy(ctx, first_name="COLLEEN", last_name="BEAVER", full_name="BEAVER,COLLEEN E")
    ch = [x for x in plan_name_changes(ctx) if x["id"] == c.id][0]
    assert ch["new_first"] == "Colleen E."
    assert ch["new_last"] == "Beaver"
    assert ch["new_full"] == "Colleen E. Beaver"


def test_mi_recovery_idempotent(ctx):
    """After MI is folded in, a second run must be a no-op."""
    # This state IS safe to insert via the ORM (before_insert syncs full_name correctly).
    c = _c(ctx, first_name="Colleen E.", last_name="Beaver", full_name="Colleen E. Beaver")
    db.session.commit()
    changes = [x for x in plan_name_changes(ctx) if x["id"] == c.id]
    assert changes == [], f"Already-folded MI row must be a no-op, got: {changes}"


def test_no_mi_recovery_when_fullname_is_different_person(ctx):
    """full_name that normalizes to a DIFFERENT first/last must NOT be trusted for MI recovery.
    Stored first/last are authoritative; full_name is stale/wrong. Result: clean the stored
    parts only (Colleen Beaver), do not cross-contaminate with Smith/Robert."""
    c = _c_legacy(ctx, first_name="Colleen", last_name="Beaver", full_name="Smith,Robert")
    # After the backfill, first="Colleen", last="Beaver", full="Colleen Beaver".
    # Smith/Robert from the stale full_name must not bleed into first/last.
    ch = [x for x in plan_name_changes(ctx) if x["id"] == c.id][0]
    assert ch["new_first"] == "Colleen"
    assert ch["new_last"] == "Beaver"
    assert ch["new_full"] == "Colleen Beaver"


def test_no_mi_recovery_when_fullname_has_mi_but_wrong_last(ctx):
    """The subtle case: full_name carries an MI AND the first matches, but the LAST
    differs ("Davis,Colleen E" vs stored Beaver). The gate requires BOTH first and last
    to match, so recovery must be rejected — never adopt Davis, never fabricate the E."""
    c = _c_legacy(ctx, first_name="Colleen", last_name="Beaver", full_name="Davis,Colleen E")
    ch = [x for x in plan_name_changes(ctx) if x["id"] == c.id][0]
    assert ch["new_first"] == "Colleen"
    assert ch["new_last"] == "Beaver"          # not Davis
    assert ch["new_full"] == "Colleen Beaver"  # no fabricated " E."


def test_no_mi_recovery_when_fullname_has_mi_but_wrong_first(ctx):
    """Mirror case: MI present, LAST matches, but FIRST differs ("Beaver,Robert E").
    Gate rejects — stored Colleen Beaver wins, no Robert, no fabricated E."""
    c = _c_legacy(ctx, first_name="Colleen", last_name="Beaver", full_name="Beaver,Robert E")
    ch = [x for x in plan_name_changes(ctx) if x["id"] == c.id][0]
    assert ch["new_first"] == "Colleen"        # not Robert
    assert ch["new_last"] == "Beaver"
    assert ch["new_full"] == "Colleen Beaver"
