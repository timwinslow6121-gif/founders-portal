"""The admin /admin/customers/duplicates page must render (200), not 500.
Regression: the template iterates `{% for mbi, rows in groups %}` (tuple shape),
but the admin view appended a flat list of Customer-lists -> `rows|length` on a
Customer -> TypeError -> 500 whenever a name+DOB+phone group existed (2026-07-02).
"""
import os
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app import create_app
from app.extensions import db
from app.models import Customer, Agency, User


@pytest.fixture
def ctx():
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False, SESSION_COOKIE_SECURE=False,
                      REMEMBER_COOKIE_SECURE=False, WTF_CSRF_ENABLED=False)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        admin = User(email="a@b.com", name="Admin", is_admin=True, agency_id=ag.id,
                     role="admin")
        db.session.add(admin); db.session.flush()
        yield app, ag.id, admin
        db.session.remove(); db.drop_all()


def _login(client, admin):
    with client.session_transaction() as s:
        s["_user_id"] = str(admin.id); s["_fresh"] = True


def test_duplicates_page_renders_with_a_name_dob_phone_group(ctx):
    from datetime import date
    app, agency_id, admin = ctx
    # Two customers sharing name + DOB + phone => an admin MBI-section "group".
    for _ in range(2):
        db.session.add(Customer(agency_id=agency_id, first_name="Sam", last_name="Jones",
                                full_name="Sam Jones", dob=date(1950, 1, 1),
                                phone_primary="828-555-0101"))
    db.session.commit()
    client = app.test_client(); _login(client, admin)
    resp = client.get("/admin/customers/duplicates")
    assert resp.status_code == 200          # was 500: TypeError object of type Customer has no len()
    assert b"Sam" in resp.data


def test_duplicates_page_renders_when_empty(ctx):
    app, agency_id, admin = ctx
    client = app.test_client(); _login(client, admin)
    resp = client.get("/admin/customers/duplicates")
    assert resp.status_code == 200
