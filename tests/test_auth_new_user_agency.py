"""A first-time OAuth login must create the User with an agency_id, or the
insert violates users.agency_id NOT NULL and the callback 500s (Michael, 2026-07-02).
"""
import pytest
from app import create_app
from app.extensions import db
from app.models import User, Agency


@pytest.fixture
def app_ctx():
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      DEFAULT_AGENCY_ID=1)
    with app.app_context():
        db.create_all()
        db.session.add(Agency(id=1, name="Founders"))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def test_new_oauth_user_is_created_with_agency_id(app_ctx):
    """Reproduces the Michael 500: a brand-new user (no existing row) must be
    created with the default agency_id set, not NULL."""
    from app.auth import _get_or_create_oauth_user
    user = _get_or_create_oauth_user(
        email="newhire@foundersinsuranceagency.com", name="New Hire", is_admin=False)
    db.session.commit()
    assert user.agency_id == app_ctx.config["DEFAULT_AGENCY_ID"]
    assert user.agency_id is not None


def test_existing_user_login_does_not_touch_agency_id(app_ctx):
    """An existing user logging in keeps their agency_id (regression guard)."""
    from app.auth import _get_or_create_oauth_user
    existing = User(email="mike@foundersinsuranceagency.com", name="Mike", agency_id=1)
    db.session.add(existing); db.session.commit()
    user = _get_or_create_oauth_user(
        email="mike@foundersinsuranceagency.com", name="Mike", is_admin=False)
    db.session.commit()
    assert user.id == existing.id
    assert user.agency_id == 1
