"""tests/test_audit.py — S2 audit log + alerting. SQLite in-memory; mailer mocked."""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest


@pytest.fixture
def app():
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
    return app


@pytest.fixture
def db(app):
    from app.extensions import db as _db
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.remove()
        _db.drop_all()


def test_log_event_writes_row_with_context(app, db, monkeypatch):
    from app import audit
    from app.models import AuditLog
    monkeypatch.setattr(audit, "maybe_alert", lambda row: None)
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "9.9.9.9",
                                  "HTTP_USER_AGENT": "TestBrowser/1.0"}):
        audit.log_event("customer_view", category="data_access",
                        detail="viewed #5", customer_id=5, agency_id_override=1)
    rows = AuditLog.query.all()
    assert len(rows) == 1
    r = rows[0]
    assert r.action == "customer_view"
    assert r.category == "data_access"
    assert r.ip_address == "9.9.9.9"
    assert r.user_agent == "TestBrowser/1.0"
    assert r.detail == "viewed #5"
