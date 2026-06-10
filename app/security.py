"""
app/security.py — S1 access hardening.

Single entry point init_security(app), called once from create_app(). Wires:
  - ProxyFix (trust nginx X-Forwarded-Proto/-For)
  - session/cookie hardening (config is set in config.py; ProxyFix here)
  - HTTP security headers (after_request)
  - Flask-Limiter rate limiting (two-tier key: per-agent / per-IP)  [added in a later task]

See docs/superpowers/specs/2026-06-10-s1-access-hardening-design.md
"""
from flask import request
from werkzeug.middleware.proxy_fix import ProxyFix

# Permissive-but-real CSP: keeps existing inline JS/CSS working ('unsafe-inline')
# but locks down origins. Single-line header value.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://accounts.google.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self' https://accounts.google.com"
)


def add_security_headers(resp):
    """after_request handler: attach security headers to every response."""
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Content-Security-Policy"] = _CSP
    # HSTS only over real HTTPS (ProxyFix gives the true scheme behind nginx),
    # so local http://localhost dev isn't poisoned with a year-long HTTPS pin.
    if request.is_secure:
        resp.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return resp


def init_security(app):
    """Wire all S1 protections onto the app. Call once from create_app()."""
    # Trust one hop of nginx for scheme + client IP. Guard against double-wrap:
    # stacking ProxyFix would consume an extra forwarded hop and misread the
    # client IP (which would then corrupt per-IP rate-limit keying).
    if not isinstance(app.wsgi_app, ProxyFix):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_for=1)

    app.after_request(add_security_headers)
