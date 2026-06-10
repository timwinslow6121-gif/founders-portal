"""
tests/test_security.py — S1 access-hardening tests.

These build their OWN app instances (not the shared session-scoped fixture)
because they need specific config: real cookie-secure flags, rate limits on/off,
and per-request scheme control. SQLite in-memory; no VPS needed.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from datetime import timedelta

import pytest


def _make_app(**overrides):
    """Fresh app with security wired, plus test overrides."""
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, **overrides)
    return app


def test_security_headers_present():
    app = _make_app(RATELIMIT_ENABLED=False)
    client = app.test_client()
    resp = client.get("/auth/login")  # public route, no login needed
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_hsts_present_over_https():
    app = _make_app(RATELIMIT_ENABLED=False)
    client = app.test_client()
    resp = client.get(
        "/auth/login",
        headers={"X-Forwarded-Proto": "https"},
        base_url="https://portal.foundersinsuranceagency.com",
    )
    assert "Strict-Transport-Security" in resp.headers


def test_hsts_absent_over_http():
    app = _make_app(RATELIMIT_ENABLED=False)
    client = app.test_client()
    resp = client.get("/auth/login", base_url="http://localhost")
    assert "Strict-Transport-Security" not in resp.headers


def test_session_lifetime_is_12h():
    app = _make_app(RATELIMIT_ENABLED=False)
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(hours=12)
    assert app.config["REMEMBER_COOKIE_DURATION"] == timedelta(hours=12)
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_callback_sets_session_permanent():
    """The OAuth callback must mark the session permanent so the 12h timeout
    applies. We assert the source calls session.permanent = True."""
    import inspect
    import app.auth as auth_mod
    src = inspect.getsource(auth_mod.callback)
    assert "session.permanent = True" in src


def test_rate_limit_key_anonymous_uses_ip():
    """Anonymous request → key is the client IP."""
    app = _make_app(RATELIMIT_ENABLED=False)
    from app.security import rate_limit_key
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "1.2.3.4"}):
        assert rate_limit_key() == "1.2.3.4"


def test_rate_limit_key_authenticated_uses_user(monkeypatch):
    """Authenticated request → key is user:<id>, NOT the IP (office-NAT fix)."""
    app = _make_app(RATELIMIT_ENABLED=False)
    from app import security as sec

    class _FakeUser:
        is_authenticated = True
        id = 42

    monkeypatch.setattr(sec, "current_user", _FakeUser())
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "1.2.3.4"}):
        assert sec.rate_limit_key() == "user:42"


def test_auth_google_rate_limited():
    """11th+ hit on /auth/google within a minute → 429."""
    app = _make_app(RATELIMIT_ENABLED=True)
    client = app.test_client()
    statuses = [client.get("/auth/google").status_code for _ in range(12)]
    assert 429 in statuses
