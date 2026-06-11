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


@pytest.fixture(autouse=True)
def _isolate_alerts():
    """Clear in-process throttle/flood state before each test so alert-trigger
    tests can't leak state into each other regardless of run order."""
    from app import alerts
    alerts._reset_throttle()
    yield


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
    # customer_id is folded into detail (PHI accountability — never silently lost)
    assert r.detail == "viewed #5 [customer #5]"


def test_nondomain_login_alerts(app, db, monkeypatch):
    from app import audit
    sent = []
    monkeypatch.setattr("app.alerts.send_email",
                        lambda to, subject, text, **k: sent.append((subject, text)) or True)
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "5.5.5.5"}):
        audit.log_event("login_nondomain", category="auth",
                        detail="attempted evil@gmail.com", agency_id_override=1)
    assert len(sent) == 1
    assert "Security Alert" in sent[0][0]


def test_export_does_not_alert(app, db, monkeypatch):
    from app import audit
    sent = []
    monkeypatch.setattr("app.alerts.send_email",
                        lambda to, subject, text, **k: sent.append(1) or True)
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "5.5.5.5"}):
        audit.log_event("customer_export_csv", category="export",
                        detail="exported book", record_count=5000, agency_id_override=1)
    assert sent == []


def test_429_flood_throttled_to_one_email(app, db, monkeypatch):
    from app import audit  # throttle state reset by autouse _isolate_alerts fixture
    sent = []
    monkeypatch.setattr("app.alerts.send_email",
                        lambda to, subject, text, **k: sent.append(1) or True)
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "7.7.7.7"}):
        for _ in range(10):
            audit.log_event("rate_limit_blocked", category="security",
                            detail="429 on /auth/google", agency_id_override=1)
    assert len(sent) == 1


def test_login_success_does_not_alert(app, db, monkeypatch):
    from app import audit
    sent = []
    monkeypatch.setattr("app.alerts.send_email",
                        lambda to, subject, text, **k: sent.append(1) or True)
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "5.5.5.5"}):
        audit.log_event("login_success", category="auth", agency_id_override=1)
    assert sent == []
