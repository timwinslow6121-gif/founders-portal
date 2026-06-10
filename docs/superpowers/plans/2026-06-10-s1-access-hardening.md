# S1 — Access Hardening + Session Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the portal's session/cookie security, add HTTP security headers, and rate-limit the unauthenticated endpoints — without changing how agents work.

**Architecture:** One new module `app/security.py` exposing `init_security(app)`, called once from `create_app()`. It wires ProxyFix (trust nginx), session/cookie config (12h timeout, Secure/HttpOnly/SameSite, remember-me capped to 12h), a security-headers `after_request` handler (HSTS/CSP/X-Frame-Options/etc.), and a Flask-Limiter instance with a two-tier key function (per-agent for authenticated traffic, per-IP for anonymous). One line added to `auth.py` (`session.permanent = True`). No model, no migration.

**Tech Stack:** Flask 3.0, Flask-Login 0.6.3, Flask-Limiter (new dep), Werkzeug ProxyFix, pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-s1-access-hardening-design.md`

---

## File Structure

- **Create:** `app/security.py` — all of S1. `init_security(app)` (ProxyFix + session config + headers + limiter), the `rate_limit_key()` key function, the `add_security_headers()` after_request handler, and a module-level `limiter` object. Single responsibility: app-wide security middleware.
- **Create:** `tests/test_security.py` — cookie flags, headers, HSTS conditional, rate-limit 429, per-agent keying, session-permanence config.
- **Modify:** `app/__init__.py` — import and call `init_security(app)` in `create_app()`; apply limiter decorators are done inside `init_security` (not here).
- **Modify:** `app/auth.py` — add `session.permanent = True` before `login_user(...)` in `callback()`.
- **Modify:** `config.py` — add `RATELIMIT_ENABLED` flag (default True; tests/dev can disable) and the session-lifetime constants so they're visible/overridable.
- **Modify:** `requirements.txt` — add `flask-limiter`.

**Key design note for the limiter + tests:** Flask-Limiter is initialized with `enabled=app.config["RATELIMIT_ENABLED"]`. The shared session-scoped test `app` fixture sets `RATELIMIT_ENABLED=False` so rate limits don't pollute the rest of the suite. The rate-limit test builds its **own** app instance with limits enabled. Apply route-specific limits inside `init_security(app)` by looking the view functions up on `app.view_functions` (the blueprints are already registered by the time `init_security` runs), and apply the webhook path-prefix limit via a `limiter.request_filter` / explicit decorator on the three known webhook view functions.

---

## Task 1: Add Flask-Limiter dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add the dependency**

Add this line to `requirements.txt` (after `flask-migrate==4.0.5`, grouping with the other Flask extensions):

```
flask-limiter==3.8.0
```

- [ ] **Step 2: Install locally**

Run: `pip install flask-limiter==3.8.0`
Expected: installs `flask-limiter` and its dep `limits`. No errors.

- [ ] **Step 3: Verify import works**

Run: `python3 -c "from flask_limiter import Limiter; from flask_limiter.util import get_remote_address; print('ok')"`
Expected: prints `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "build: add flask-limiter dependency for S1 rate limiting"
```

---

## Task 2: Add S1 config flags to config.py

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add session-lifetime + rate-limit config**

In `config.py`, add `from datetime import timedelta` at the top (after `import os`), then add these inside `class Config` (after the `MAIL_*` block at the end):

```python
    # --- S1: Access hardening / session security ---
    # 12h absolute session timeout, matching Google Workspace's 12h reauth.
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DURATION = timedelta(hours=12)   # cap remember-me to 12h
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

    # Rate limiting (Flask-Limiter). Disabled in tests/dev via env so the shared
    # test app and local http dev aren't throttled. Enabled in production.
    RATELIMIT_ENABLED = os.environ.get("RATELIMIT_ENABLED", "1") == "1"
```

- [ ] **Step 2: Verify config loads**

Run: `python3 -c "from config import Config; from datetime import timedelta; assert Config.PERMANENT_SESSION_LIFETIME == timedelta(hours=12); assert Config.SESSION_COOKIE_SAMESITE == 'Lax'; print('ok')"`
Expected: prints `ok`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat(s1): session-lifetime + cookie + ratelimit config flags"
```

---

## Task 3: Create app/security.py — headers handler (TDD)

Build the module incrementally. Start with the security-headers handler because it's pure-function-testable without login or limiter.

**Files:**
- Create: `app/security.py`
- Create: `tests/test_security.py`

- [ ] **Step 1: Write the failing test for security headers**

Create `tests/test_security.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_security.py::test_security_headers_present -v`
Expected: FAIL — headers are absent (returns `None`), assertion error on `X-Frame-Options`.

- [ ] **Step 3: Create app/security.py with the headers handler**

Create `app/security.py`:

```python
"""
app/security.py — S1 access hardening.

Single entry point init_security(app), called once from create_app(). Wires:
  - ProxyFix (trust nginx X-Forwarded-Proto/-For)
  - session/cookie hardening (config is set in config.py; ProxyFix here)
  - HTTP security headers (after_request)
  - Flask-Limiter rate limiting (two-tier key: per-agent / per-IP)

See docs/superpowers/specs/2026-06-10-s1-access-hardening-design.md
"""
from flask import request
from flask_login import current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
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
    # Trust one hop of nginx for scheme + client IP.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_for=1)

    app.after_request(add_security_headers)
```

- [ ] **Step 4: Wire init_security into create_app**

In `app/__init__.py`, add the import and call. After the line `Migrate(app, db)` and BEFORE the blueprint imports, add:

```python
    from app.security import init_security
    init_security(app)
```

(Placing it before blueprint registration is fine for headers/ProxyFix; Task 6 will move the limiter route-decoration to run AFTER blueprints — see note there. For now `init_security` only does headers + ProxyFix.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_security.py::test_security_headers_present -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/security.py app/__init__.py tests/test_security.py
git commit -m "feat(s1): security headers (CSP, HSTS, X-Frame-Options, etc.)"
```

---

## Task 4: HSTS conditional on HTTPS (TDD)

Verify HSTS is present over https and absent over http.

**Files:**
- Modify: `tests/test_security.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_security.py`:

```python
def test_hsts_present_over_https():
    app = _make_app(RATELIMIT_ENABLED=False)
    client = app.test_client()
    # base_url https + ProxyFix header so request.is_secure is True
    resp = client.get(
        "/auth/login",
        base_url="https://portal.foundersinsuranceagency.com",
    )
    assert "Strict-Transport-Security" in resp.headers


def test_hsts_absent_over_http():
    app = _make_app(RATELIMIT_ENABLED=False)
    client = app.test_client()
    resp = client.get("/auth/login", base_url="http://localhost")
    assert "Strict-Transport-Security" not in resp.headers
```

- [ ] **Step 2: Run tests**

Run: `python3 -m pytest tests/test_security.py -k hsts -v`
Expected: BOTH PASS (the handler in Task 3 already gates on `request.is_secure`; this confirms it). If `test_hsts_present_over_https` fails because ProxyFix/`base_url` didn't set secure, change it to pass header `environ_overrides={"wsgi.url_scheme": "https"}` instead of `base_url`. Re-run until green.

- [ ] **Step 3: Commit**

```bash
git add tests/test_security.py
git commit -m "test(s1): HSTS present over https, absent over http"
```

---

## Task 5: Session permanence in auth callback (TDD)

Ensure the 12h timeout actually engages by marking the session permanent at login, and that the config carries the 12h lifetime.

**Files:**
- Modify: `app/auth.py:116-117` (the `db.session.commit()` / `login_user` area in `callback()`)
- Modify: `tests/test_security.py`

- [ ] **Step 1: Write the failing test for the config + permanence intent**

Add to `tests/test_security.py`:

```python
from datetime import timedelta


def test_session_lifetime_is_12h():
    app = _make_app(RATELIMIT_ENABLED=False)
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(hours=12)
    assert app.config["REMEMBER_COOKIE_DURATION"] == timedelta(hours=12)
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_callback_sets_session_permanent(monkeypatch):
    """The OAuth callback must mark the session permanent so the 12h timeout
    applies. We assert the source calls session.permanent = True."""
    import inspect
    import app.auth as auth_mod
    src = inspect.getsource(auth_mod.callback)
    assert "session.permanent = True" in src
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_security.py -k "session" -v`
Expected: `test_session_lifetime_is_12h` PASSES (config from Task 2). `test_callback_sets_session_permanent` FAILS — the string isn't in the source yet.

- [ ] **Step 3: Add session.permanent in the callback**

In `app/auth.py`, in the `callback()` function, locate:

```python
    db.session.commit()
    login_user(user, remember=True)
```

Change it to:

```python
    db.session.commit()
    session.permanent = True   # S1: engage the 12h PERMANENT_SESSION_LIFETIME
    login_user(user, remember=True)
```

(`session` is already imported in `app/auth.py` — confirm the existing `from flask import ... session ...` import line includes it; it does.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_security.py -k "session" -v`
Expected: BOTH PASS

- [ ] **Step 5: Commit**

```bash
git add app/auth.py tests/test_security.py
git commit -m "feat(s1): mark session permanent at login to engage 12h timeout"
```

---

## Task 6: Flask-Limiter with two-tier key (TDD)

Add rate limiting. The key function returns `user:<id>` when authenticated, else the client IP. Limits applied: per-agent/per-IP global default, tight limits on `/auth/google` and `/auth/callback`, webhook limit on the three known webhook view functions.

**Files:**
- Modify: `app/security.py`
- Modify: `tests/test_security.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_security.py`:

```python
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
    """11th hit on /auth/google within a minute → 429."""
    app = _make_app(RATELIMIT_ENABLED=True)
    client = app.test_client()
    statuses = [client.get("/auth/google").status_code for _ in range(12)]
    assert 429 in statuses
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_security.py -k "rate" -v`
Expected: FAIL — `rate_limit_key` doesn't exist yet; `/auth/google` not limited.

- [ ] **Step 3: Add the key function + limiter to app/security.py**

In `app/security.py`, add after the `_CSP` block (before `add_security_headers`):

```python
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
```

Then, at the END of `init_security(app)` (after `app.after_request(...)`), add:

```python
    # Rate limiting. Disabled in tests/dev via config; on in production.
    limiter.enabled = app.config.get("RATELIMIT_ENABLED", True)
    limiter.init_app(app)

    # Tight limits on the unauthenticated auth endpoints (per-IP via key_func,
    # since the user isn't logged in yet at these routes).
    auth_login = app.view_functions.get("auth.google_login")
    auth_cb = app.view_functions.get("auth.callback")
    if auth_login:
        limiter.limit("10 per minute")(auth_login)
    if auth_cb:
        limiter.limit("10 per minute")(auth_cb)

    # Webhook limit on the three known inbound webhook view functions.
    # Convention: future inbound webhooks live at /comms/webhook/<name> and
    # should be added here (or matched by endpoint prefix 'comms.').
    for ep in ("comms.quo_webhook", "comms.calendly_webhook",
               "comms.healthsherpa_webhook"):
        vf = app.view_functions.get(ep)
        if vf:
            limiter.limit("60 per minute")(vf)
```

- [ ] **Step 4: Confirm the webhook endpoint names**

Run: `python3 -c "
from app import create_app
app = create_app()
print([e for e in app.view_functions if e.startswith('comms.')])
"`
Expected: a list including the three webhook endpoints. **If their names differ** from `comms.quo_webhook` / `comms.calendly_webhook` / `comms.healthsherpa_webhook`, update the tuple in Step 3 to the real endpoint names before continuing. (The functions are at `app/comms/webhooks.py` lines 49/312/459 — their endpoint is `comms.<function_name>`.)

- [ ] **Step 5: Move init_security to run AFTER blueprint registration**

The limiter decorates view functions, so blueprints must be registered first. In `app/__init__.py`, **remove** the `init_security(app)` call added in Task 3 Step 4 (the one near `Migrate`), and instead call it AFTER all `app.register_blueprint(...)` lines (just before the `@app.context_processor` block):

```python
    from app.security import init_security
    init_security(app)
```

(ProxyFix + after_request still work fine when wired post-registration.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_security.py -k "rate" -v`
Expected: ALL PASS. (If `test_auth_google_rate_limited` is flaky due to limiter storage persisting across the session, ensure each `_make_app` builds a fresh app — it does — and that `limiter` state is per-app via `init_app`.)

- [ ] **Step 7: Commit**

```bash
git add app/security.py app/__init__.py tests/test_security.py
git commit -m "feat(s1): flask-limiter rate limiting w/ per-agent two-tier key"
```

---

## Task 7: Full-suite regression + manual smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `python3 -m pytest -q`
Expected: all tests pass (the ~180 existing + the new `test_security.py` cases). If any existing test now 429s or fails on a missing header, the cause is the shared session-scoped `app` fixture having rate limits on — confirm `tests/conftest.py`'s `app` fixture sets `RATELIMIT_ENABLED=False` (add it in `flask_app.config.update(...)` if a regression appears).

- [ ] **Step 2: Manual smoke — app boots and serves**

Run: `RATELIMIT_ENABLED=0 python3 -c "
from app import create_app
app = create_app()
c = app.test_client()
r = c.get('/auth/login')
print('status', r.status_code)
print('xfo', r.headers.get('X-Frame-Options'))
print('csp?', 'Content-Security-Policy' in r.headers)
"`
Expected: `status 200`, `xfo DENY`, `csp? True`.

- [ ] **Step 3: Commit (if conftest needed the flag)**

```bash
git add tests/conftest.py
git commit -m "test(s1): disable rate limits in shared test fixture"
```

(Skip if no conftest change was needed.)

---

## Task 8: Deploy notes verification (documentation)

**Files:**
- Modify: `docs/superpowers/specs/2026-06-10-s1-access-hardening-design.md` (flip Status to Implemented)
- Modify: `CLAUDE.md` (Build Status entry + START HERE block)

- [ ] **Step 1: Mark spec implemented**

In the spec, change the Status line near the top to:
`**Status:** ✅ Implemented (local) — pending VPS deploy + verification`

- [ ] **Step 2: Add a Build Status entry to CLAUDE.md**

Add under Build Status (keep the house style):

```
- **S1 — Access hardening + session security ✅ (2026-06-10, local)** — `app/security.py` `init_security(app)`: ProxyFix (trust nginx scheme/IP), 12h absolute session timeout (matches Google Workspace 12h reauth — confirmed) via PERMANENT_SESSION_LIFETIME + session.permanent at login, Secure/HttpOnly/SameSite=Lax cookies, remember-me capped 12h, security headers (HSTS over https only, CSP permissive-but-real keeping 'unsafe-inline', X-Frame-Options DENY, nosniff, Referrer-Policy), Flask-Limiter (memory) with two-tier key (per-agent user:<id> authenticated / per-IP anonymous — office-NAT fix): 600/hr per agent, 10/min /auth/google + /auth/callback, 60/min /comms/webhook/*. No migration. New dep flask-limiter. tests/test_security.py. Brevo=outbound (N/A); future Twilio SMS webhook auto-covered by convention. Milestone 1 pillar 2; S2 (audit/alert) consumes these events next. See spec 2026-06-10-s1-access-hardening-design.md.
```

Update the START HERE block's NEXT line: S1 done (local) → deploy → **S2 audit/alert is next**.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-06-10-s1-access-hardening-design.md CLAUDE.md
git commit -m "docs(s1): mark implemented; CLAUDE.md build status + next=S2"
```

- [ ] **Step 4: Deploy checklist (run on VPS when ready — NOT part of local impl)**

These are for the deploy session, listed here so nothing is missed:
```bash
# local: push
git push origin main
# VPS:
cd /var/www/founders-portal && git pull \
  && ./venv/bin/pip install -r requirements.txt \
  && systemctl restart founders-portal   # NO migration needed
```
Then verify on the live site:
- Log in via Google — succeeds (CSP allows accounts.google.com).
- Portal loads in BOTH light and dark mode — theme toggle works (CSP didn't break the no-flash inline script).
- DevTools → Network → a page response shows `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options: DENY`. Cookies show `Secure`, `HttpOnly`, `SameSite=Lax`.
- Confirm an agent is NOT logged out mid-session; next day (>12h) a fresh login is required.
- Confirm a real comms webhook (Quo call) still processes (not 429'd).

---

## Self-Review

**Spec coverage** (spec §4–§7 mapped to tasks):
- §4 session/cookie config → Task 2 (config) + Task 5 (session.permanent). ✓
- §5 security headers (HSTS conditional, CSP, X-Frame, nosniff, Referrer) → Task 3 + Task 4. ✓
- §6 rate limiting, two-tier key, per-agent 600/hr, /auth 10/min, webhook 60/min, path/endpoint targeting → Task 6. ✓
- §6 Brevo/Twilio handling → documentation only (no code); covered in Task 8 build-status note. ✓
- §3 ProxyFix → Task 3 Step 3. ✓
- §7 tests (cookie flags, headers, HSTS conditional, 429, per-agent keying, session permanence) → Tasks 3–6 test steps. ✓
- §8 deploy notes → Task 8. ✓
- No migration → confirmed, no migration task. ✓

**Cookie-flag test gap noted:** asserting `Set-Cookie` *flags* directly is brittle (Flask only emits the cookie on an actual login response, and the test client downgrades Secure on http). The plan asserts the **config values** that drive those flags (Task 5 `test_session_lifetime_is_12h` covers Secure/HttpOnly/SameSite) — this is the reliable equivalent and matches the spec §7 "assert via app.config" hedge. No separate brittle Set-Cookie test added by design.

**Placeholder scan:** no TBD/TODO; every code step shows real code; webhook endpoint names have a verify-and-correct step (Task 6 Step 4) rather than a guess.

**Type/name consistency:** `rate_limit_key`, `limiter`, `add_security_headers`, `init_security`, `_CSP`, `RATELIMIT_ENABLED` used identically across all tasks. `init_security` placement is corrected once (Task 3 → moved in Task 6 Step 5) with an explicit instruction, not left contradictory.
