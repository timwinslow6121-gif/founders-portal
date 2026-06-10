"""
app/security.py — S1 access hardening.

Single entry point init_security(app), called once from create_app(). Wires:
  - ProxyFix (trust nginx X-Forwarded-Proto/-For)
  - session/cookie hardening (config is set in config.py; ProxyFix here)
  - HTTP security headers (after_request)
  - Flask-Limiter rate limiting (two-tier key: per-agent / per-IP)

The module-level `limiter` uses in-memory storage, which is per-process; this
relies on one app per gunicorn worker in production (true here). Disabled in
tests/dev via RATELIMIT_ENABLED so the shared test app isn't throttled.

See docs/superpowers/specs/2026-06-10-s1-access-hardening-design.md
"""
from flask import request
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_login import current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

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


def rate_limit_key():
    """Two-tier key: per-agent when logged in (so office-mates sharing one
    NAT IP get independent buckets), per-IP when anonymous."""
    try:
        if current_user.is_authenticated:
            return f"user:{current_user.id}"
    except Exception:
        pass
    return get_remote_address()


# Module-level limiter; attached to the app in init_security().
limiter = Limiter(
    key_func=rate_limit_key,
    default_limits=["600 per hour"],
    storage_uri="memory://",
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

    # Rate limiting. Disabled in tests/dev via config; on in production.
    limiter.enabled = app.config.get("RATELIMIT_ENABLED", True)
    limiter.init_app(app)

    # Decorate already-registered views imperatively. limiter.limit() returns
    # a WRAPPED view function that performs the in-request limit check; we must
    # write that wrapper back into app.view_functions or the limit is recorded
    # but never enforced (the before_request middleware path does not evaluate
    # decorated per-view limits).
    def _apply_limit(endpoint, spec):
        vf = app.view_functions.get(endpoint)
        if vf:
            app.view_functions[endpoint] = limiter.limit(spec)(vf)

    # Tight limits on the unauthenticated auth endpoints (per-IP via key_func,
    # since the user isn't logged in yet at these routes).
    _apply_limit("auth.google_login", "10 per minute")
    _apply_limit("auth.callback", "10 per minute")

    # Webhook limit on the three known inbound webhook view functions.
    # Convention: future inbound webhooks live at /comms/webhook/<name> and
    # should be added here.
    for ep in ("comms.quo_webhook", "comms.calendly_webhook",
               "comms.healthsherpa_webhook"):
        _apply_limit(ep, "60 per minute")
