import os
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("TESTING", "1")

from app import create_app
from app.extensions import db
from app.models import Customer, Agency
from scripts.normalize_customer_names import plan_name_changes


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
