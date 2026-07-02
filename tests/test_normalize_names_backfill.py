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
