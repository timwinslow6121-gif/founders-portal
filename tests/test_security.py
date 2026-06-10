"""
tests/test_security.py — S1 access-hardening tests.

These build their OWN app instances (not the shared session-scoped fixture)
because they need specific config: real cookie-secure flags, rate limits on/off,
and per-request scheme control. SQLite in-memory; no VPS needed.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

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
