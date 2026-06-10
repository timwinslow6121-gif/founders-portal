# S2 — Audit Log + Breach Alerting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing business-only `AuditLog` into a security audit trail (every login/data-view/export with forensic detail), with a tightly-scoped 2-trigger email alerting layer and an admin viewer — so Tim has a complete record and gets paged ONLY on outsider-flavored events.

**Architecture:** Two new modules — `app/audit.py` (`log_event()` seam: captures request context, writes one AuditLog row, hands off to alerts) and `app/alerts.py` (2 trigger rules + de-duped plain-English Brevo email). Migration 025 extends `audit_logs` with ip_address, user_agent, agency_id, category, severity, record_count. ~10 thin `log_event(...)` hooks across auth/security/customers/labels/agent_settings/upload. Admin-only `/admin/audit-log` viewer. Plus a hand-written `docs/INCIDENT_RESPONSE_RUNBOOK.md`.

**Tech Stack:** Flask 3.0, Flask-SQLAlchemy, Flask-Migrate (Alembic), Flask-Login, existing `app/mailer.py` (Brevo). No new dependency.

**Spec:** `docs/superpowers/specs/2026-06-10-s2-audit-log-breach-alerting-design.md`

---

## File Structure

- **Modify:** `app/models.py` — add 6 columns to the `AuditLog` model (ip_address, user_agent, agency_id, category, severity, record_count).
- **Create:** `migrations/versions/025_audit_log_security_fields.py` — Alembic migration, down_revision="024".
- **Create:** `app/audit.py` — `log_event(...)` seam. ONLY place that writes AuditLog. Captures request context, inserts row, calls `app.alerts.maybe_alert(row)` guarded by try/except (a failing alert must never break the caller).
- **Create:** `app/alerts.py` — `maybe_alert(row)` + the 2 trigger rules + de-dup throttle + plain-English email composition. Module constants `FLOOD_COUNT`, `FLOOD_WINDOW`, `ALERT_THROTTLE_WINDOW`.
- **Create:** `tests/test_audit.py` — full coverage (SQLite in-memory, mailer mocked).
- **Modify (thin hooks):** `app/auth.py`, `app/security.py`, `app/customers.py`, `app/labels.py`, `app/agent_settings.py`, `app/upload.py` (migrate 2 existing writes).
- **Create:** `app/templates/audit_log.html` + a route (add to `app/routes.py`, admin-only) + nav entry in `app/templates/base.html` admin block.
- **Create:** `docs/INCIDENT_RESPONSE_RUNBOOK.md` (drafted WITH Tim — Task 9).

**Design note — `log_event` signature (used identically everywhere):**
```python
log_event(action, *, category, detail=None, user=None,
          customer_id=None, severity="info", record_count=None)
```
It reads `ip_address`/`user_agent` from the Flask `request` (S1 ProxyFix makes `request.remote_addr` the real client IP) and `agency_id`/`user_id` from `user` (falling back to `current_user`). Safe outside a request context (no request → ip/ua None). It commits its own row (`db.session.add` + `db.session.commit`) OR is documented to require the caller to commit — THIS PLAN chooses: `log_event` does `db.session.add(row); db.session.commit()` itself, so a hook is truly one line. (The 2 upload.py sites already commit after; an extra commit there is harmless.)

---

## Task 1: Extend AuditLog model + migration 025

**Files:**
- Modify: `app/models.py` (AuditLog class, ~line 202)
- Create: `migrations/versions/025_audit_log_security_fields.py`

- [ ] **Step 1: Add columns to the AuditLog model**

In `app/models.py`, the `AuditLog` class currently has `id, user_id, user, action, detail, created_at`. Add these columns after `detail`:

```python
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(256))
    agency_id = db.Column(db.Integer, db.ForeignKey("agencies.id"), index=True)
    category = db.Column(db.String(32), index=True)
    severity = db.Column(db.String(16), default="info")
    record_count = db.Column(db.Integer)
```

- [ ] **Step 2: Create the migration**

Create `migrations/versions/025_audit_log_security_fields.py`:

```python
"""S2: add security/forensic fields to audit_logs

Revision ID: 025
Revises: 024
"""
from alembic import op
import sqlalchemy as sa

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("audit_logs") as batch:
        batch.add_column(sa.Column("ip_address", sa.String(length=45), nullable=True))
        batch.add_column(sa.Column("user_agent", sa.String(length=256), nullable=True))
        batch.add_column(sa.Column("agency_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("category", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("severity", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("record_count", sa.Integer(), nullable=True))
    op.create_index("ix_audit_logs_agency_id", "audit_logs", ["agency_id"])
    op.create_index("ix_audit_logs_category", "audit_logs", ["category"])


def downgrade():
    op.drop_index("ix_audit_logs_category", table_name="audit_logs")
    op.drop_index("ix_audit_logs_agency_id", table_name="audit_logs")
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_column("record_count")
        batch.drop_column("severity")
        batch.drop_column("category")
        batch.drop_column("agency_id")
        batch.drop_column("user_agent")
        batch.drop_column("ip_address")
```

- [ ] **Step 3: Verify the model imports and migration is the head**

Run: `python3 -c "from app.models import AuditLog; print([c.name for c in AuditLog.__table__.columns])"`
Expected: list includes `ip_address, user_agent, agency_id, category, severity, record_count`.

Run: `python3 -c "import migrations.versions.025_audit_log_security_fields as m; print(m.revision, m.down_revision)" 2>/dev/null || echo "025 chains 024 (verify file)"`
Expected: confirms `025` / `024` (the import may fail on the numeric module name — that's fine, the file content is what matters; Alembic loads by path).

- [ ] **Step 4: Run full suite (SQLite create_all builds the new columns)**

Run: `python3 -m pytest -q`
Expected: all pass (tests use `db.create_all()`, so they pick up the new columns without running the migration). Baseline before S2 = 188.

- [ ] **Step 5: Commit**

```bash
git add app/models.py migrations/versions/025_audit_log_security_fields.py
git commit -m "feat(s2): extend AuditLog with security/forensic fields + migration 025

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: app/audit.py — log_event() seam (TDD)

**Files:**
- Create: `app/audit.py`
- Create: `tests/test_audit.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit.py`:

```python
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
    # no alert for this category
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
```

(Note: the test passes `agency_id_override=1` because there's no logged-in user in a bare request context. The real `log_event` signature uses `user=`/`current_user` for agency_id; for testability it also accepts an explicit override. See Step 3.)

- [ ] **Step 2: Run to confirm FAIL**

Run: `python3 -m pytest tests/test_audit.py::test_log_event_writes_row_with_context -v`
Expected: FAIL — `app.audit` module doesn't exist.

- [ ] **Step 3: Create app/audit.py**

```python
"""
app/audit.py — S2 security audit trail seam.

log_event() is the ONLY place that writes AuditLog. It captures request context
(real client IP via S1 ProxyFix, user-agent, agency_id, acting user), inserts
one append-only row, and hands the row to app.alerts.maybe_alert for the alert
decision. A failing alert must NEVER break the caller's request — alert dispatch
is wrapped in try/except.

See docs/superpowers/specs/2026-06-10-s2-audit-log-breach-alerting-design.md
"""
import logging
from flask import request, has_request_context
from flask_login import current_user
from app.extensions import db
from app.models import AuditLog
from app.alerts import maybe_alert

_log = logging.getLogger(__name__)


def log_event(action, *, category, detail=None, user=None, customer_id=None,
              severity="info", record_count=None, agency_id_override=None):
    """Write one audit row + maybe alert. Safe outside a request context."""
    ip = ua = None
    if has_request_context():
        ip = request.remote_addr
        ua = (request.user_agent.string or "")[:256] or None

    # Resolve acting user + agency. Prefer explicit user, then current_user.
    acting = user
    if acting is None and has_request_context():
        try:
            if current_user.is_authenticated:
                acting = current_user
        except Exception:
            acting = None

    user_id = getattr(acting, "id", None)
    agency_id = agency_id_override
    if agency_id is None:
        agency_id = getattr(acting, "agency_id", None)

    row = AuditLog(
        user_id=user_id,
        action=action,
        detail=detail,
        category=category,
        severity=severity,
        record_count=record_count,
        ip_address=ip,
        user_agent=ua,
        agency_id=agency_id,
    )
    db.session.add(row)
    db.session.commit()

    # Alerting must never break the caller.
    try:
        maybe_alert(row)
    except Exception:
        _log.exception("maybe_alert failed for audit row %s", row.id)

    return row
```

- [ ] **Step 4: Create a minimal app/alerts.py stub so the import resolves**

Create `app/alerts.py` (full rules come in Task 3; stub first so audit.py imports):

```python
"""app/alerts.py — S2 breach alerting (rules + email). See Task 3."""


def maybe_alert(row):
    """Decide + dispatch alert email. Stub — implemented in Task 3."""
    return None
```

- [ ] **Step 5: Run to confirm PASS**

Run: `python3 -m pytest tests/test_audit.py::test_log_event_writes_row_with_context -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/audit.py app/alerts.py tests/test_audit.py
git commit -m "feat(s2): log_event() audit seam + alerts stub

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: app/alerts.py — 2 trigger rules + de-duped email (TDD)

**Files:**
- Modify: `app/alerts.py`
- Modify: `tests/test_audit.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_audit.py`:

```python
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
    assert sent == []  # exports log-only, never alert


def test_429_flood_throttled_to_one_email(app, db, monkeypatch):
    from app import audit, alerts
    alerts._reset_throttle()  # test helper to clear in-process throttle state
    sent = []
    monkeypatch.setattr("app.alerts.send_email",
                        lambda to, subject, text, **k: sent.append(1) or True)
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "7.7.7.7"}):
        for _ in range(10):
            audit.log_event("rate_limit_blocked", category="security",
                            detail="429 on /auth/google", agency_id_override=1)
    # FLOOD_COUNT=5 reached, but throttle → exactly ONE email despite 10 events
    assert len(sent) == 1


def test_login_success_does_not_alert(app, db, monkeypatch):
    from app import audit
    sent = []
    monkeypatch.setattr("app.alerts.send_email",
                        lambda to, subject, text, **k: sent.append(1) or True)
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "5.5.5.5"}):
        audit.log_event("login_success", category="auth", agency_id_override=1)
    assert sent == []
```

- [ ] **Step 2: Run to confirm FAIL**

Run: `python3 -m pytest tests/test_audit.py -k "alert or flood or export or login" -v`
Expected: FAIL — stub `maybe_alert` sends nothing; `_reset_throttle` missing.

- [ ] **Step 3: Implement app/alerts.py**

Replace `app/alerts.py` with:

```python
"""
app/alerts.py — S2 breach alerting: 2 trigger rules + de-duped plain-English
email. The SINGLE place alert rules live. No DB writes. No time-of-day logic
(Founders agents work all hours — off-hours alerting was deliberately removed).

Triggers:
  1. Non-domain / failed login (action in login_failed/login_nondomain).
  2. 429 flood (>= FLOOD_COUNT rate_limit_blocked from one source in FLOOD_WINDOW).
Exports are LOG-ONLY (never alert).
"""
import time
import logging
from collections import defaultdict, deque
from flask import current_app
from app.mailer import send_email

_log = logging.getLogger(__name__)

FLOOD_COUNT = 5            # 429s from one source...
FLOOD_WINDOW = 300         # ...within this many seconds → flood
ALERT_THROTTLE_WINDOW = 300  # max one email per (trigger, source) per this window

# In-process state (per gunicorn worker — acceptable; worst case ~2x emails).
_flood_hits = defaultdict(deque)     # source_key -> deque[timestamps]
_last_alert_at = {}                  # (trigger, source_key) -> last-sent epoch


def _reset_throttle():
    """Test helper — clear in-process state."""
    _flood_hits.clear()
    _last_alert_at.clear()


def _throttled(trigger, source_key):
    """True if we already alerted this (trigger, source) within the window."""
    now = time.time()
    last = _last_alert_at.get((trigger, source_key), 0)
    if now - last < ALERT_THROTTLE_WINDOW:
        return True
    _last_alert_at[(trigger, source_key)] = now
    return False


def _source_key(row):
    return row.ip_address or (f"user:{row.user_id}" if row.user_id else "unknown")


def maybe_alert(row):
    """Apply the 2 trigger rules; on a match (and not throttled), send email."""
    if row.category == "auth" and row.action in ("login_failed", "login_nondomain"):
        _send("login", row, _compose_login(row))
        return

    if row.category == "security" and row.action == "rate_limit_blocked":
        key = _source_key(row)
        hits = _flood_hits[key]
        now = time.time()
        hits.append(now)
        while hits and now - hits[0] > FLOOD_WINDOW:
            hits.popleft()
        if len(hits) >= FLOOD_COUNT:
            _send("flood", row, _compose_flood(row, len(hits)))
        return

    # exports + everything else: log-only, no alert.
    return


def _send(trigger, row, message):
    key = _source_key(row)
    if _throttled(trigger, key):
        return
    subject, text = message
    try:
        to = current_app.config.get("MAIL_FROM") or ""
        if to:
            send_email(to, subject, text)
    except Exception:
        _log.exception("alert email send failed")


def _compose_login(row):
    subject = "🔔 Founders Portal Security Alert — login attempt blocked"
    text = (
        "What happened:  A login attempt was blocked.\n"
        f"Who / where:    {row.detail or 'unknown'} — from IP {row.ip_address or 'unknown'}"
        f" — {row.user_agent or 'unknown device'}.\n"
        f"When:           {row.created_at} UTC.\n"
        "Access granted? NO — the portal blocked it (only @foundersinsuranceagency.com can get in).\n\n"
        "What it means & what to do: An outsider may be probing the login. No action\n"
        "needed — it was already blocked. If you see many of these from the same IP,\n"
        "that IP is worth blocking at the firewall (see the Incident Response Runbook)."
    )
    return subject, text


def _compose_flood(row, count):
    subject = "🔔 Founders Portal Security Alert — rate-limit flood"
    text = (
        "What happened:  One source is hammering the portal (possible bot/attack).\n"
        f"Who / where:    IP {row.ip_address or 'unknown'} — {count}+ blocked requests in a few minutes.\n"
        f"When:           {row.created_at} UTC.\n"
        "Access granted? NO — S1's rate limiter is auto-blocking it.\n\n"
        "What it means & what to do: Automated abuse or a DoS attempt. It's already\n"
        "being blocked. If it persists, block that IP at the firewall (see the\n"
        "Incident Response Runbook)."
    )
    return subject, text
```

- [ ] **Step 4: Run to confirm PASS**

Run: `python3 -m pytest tests/test_audit.py -k "alert or flood or export or login" -v`
Expected: ALL PASS.

- [ ] **Step 5: Run full audit test file + full suite**

Run: `python3 -m pytest tests/test_audit.py -q && python3 -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/alerts.py tests/test_audit.py
git commit -m "feat(s2): alert rules — nondomain/failed login + 429 flood, de-duped email

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Auth hooks (TDD)

**Files:**
- Modify: `app/auth.py`
- Modify: `tests/test_audit.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit.py`:

```python
def test_auth_callback_logs_nondomain(app, db, monkeypatch):
    """A non-domain login attempt is logged as login_nondomain with the email."""
    import inspect
    import app.auth as auth_mod
    src = inspect.getsource(auth_mod.callback)
    assert 'log_event("login_nondomain"' in src or "log_event('login_nondomain'" in src
    # logout + success hooks present too
    assert "login_success" in inspect.getsource(auth_mod.callback)
    assert "log_event" in inspect.getsource(auth_mod.logout)
```

- [ ] **Step 2: Run to confirm FAIL**

Run: `python3 -m pytest tests/test_audit.py::test_auth_callback_logs_nondomain -v`
Expected: FAIL — hooks not added yet.

- [ ] **Step 3: Add hooks to app/auth.py**

In `app/auth.py`, add the import at the top with the other app imports:
```python
from app.audit import log_event
```

In `callback()`, the non-domain branch currently is:
```python
    if domain != ALLOWED_DOMAIN:
        return render_template('login.html',
            error='Access restricted to @foundersinsuranceagency.com accounts.')
```
Change it to:
```python
    if domain != ALLOWED_DOMAIN:
        log_event("login_nondomain", category="auth", severity="alert",
                  detail=f"attempted {email}", agency_id_override=1)
        return render_template('login.html',
            error='Access restricted to @foundersinsuranceagency.com accounts.')
```

After the successful `login_user(user, remember=True)` line in `callback()`, add:
```python
    log_event("login_success", category="auth", user=user)
```

In `logout()`, before `logout_user()`, add:
```python
    log_event("logout", category="auth", user=current_user)
```
(`current_user` is valid here — the route is `@login_required`.)

- [ ] **Step 4: Run to confirm PASS + full suite**

Run: `python3 -m pytest tests/test_audit.py::test_auth_callback_logs_nondomain -v && python3 -m pytest -q`
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add app/auth.py tests/test_audit.py
git commit -m "feat(s2): auth hooks — log login_success/nondomain/logout

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 429 + data-access + export + admin + upload hooks

These are thin one-liners. Group them; one commit. Verify via source-presence assertions (behavioral tests for each route would require heavy auth/session mocking disproportionate to a one-line hook — the seam itself is already behavior-tested in Tasks 2-3).

**Files:**
- Modify: `app/security.py`, `app/customers.py`, `app/labels.py`, `app/agent_settings.py`, `app/upload.py`
- Modify: `tests/test_audit.py`

- [ ] **Step 1: Write the failing presence test**

Append to `tests/test_audit.py`:

```python
def test_hooks_present_in_routes():
    import inspect
    import app.customers as c, app.labels as l, app.agent_settings as s, app.upload as u
    assert "customer_view" in inspect.getsource(c)
    assert "customer_export_csv" in inspect.getsource(c)
    assert "labels_pdf_download" in inspect.getsource(l)
    assert "agent_role_change" in inspect.getsource(s)
    # upload migrated to log_event
    assert "log_event" in inspect.getsource(u)


def test_security_429_handler_logs():
    import inspect
    import app.security as sec
    assert "rate_limit_blocked" in inspect.getsource(sec)
```

- [ ] **Step 2: Run to confirm FAIL**

Run: `python3 -m pytest tests/test_audit.py -k "hooks_present or 429_handler" -v`
Expected: FAIL.

- [ ] **Step 3a: security.py — 429 handler**

In `app/security.py`, inside `init_security(app)` after `limiter.init_app(app)`, register a 429 handler that logs. Add:
```python
    @app.errorhandler(429)
    def _ratelimit_logged(e):
        try:
            from app.audit import log_event
            log_event("rate_limit_blocked", category="security", severity="warning",
                      detail=f"429 on {request.path}", agency_id_override=1)
        except Exception:
            pass
        return ("Too Many Requests", 429)
```
(`request` is already imported in security.py.)

- [ ] **Step 3b: customers.py — profile view + CSV export**

Import at top: `from app.audit import log_event`.

In the GET view function for `/customers/<int:customer_id>` (around line 466), AFTER the access check passes and the customer is loaded (just before `return render_template(...)`), add:
```python
    log_event("customer_view", category="data_access",
              detail=f"viewed customer #{customer.id}", customer_id=customer.id)
```

In the `/customers/export` route (around line 290), just before the `return Response(...)`/`send_file` with the CSV, add (use the actual row count variable in scope — the list of rows being written; name it `rows` or the existing variable):
```python
    log_event("customer_export_csv", category="export",
              detail="customer CSV export", record_count=len(export_rows))
```
(Use whatever the in-scope list of exported customers is named; if it's a query, materialize a count. Adjust `export_rows` to the real variable.)

- [ ] **Step 3c: labels.py — PDF download**

Import `from app.audit import log_event`. In `/birthday-labels/download` (line ~192), before returning the PDF response, add:
```python
    log_event("labels_pdf_download", category="export",
              detail="birthday labels PDF", record_count=label_count)
```
(Use the real count variable — the number of labels/customers in the PDF; adjust `label_count`.)

- [ ] **Step 3d: agent_settings.py — role/contract change**

Import `from app.audit import log_event`. In `settings_agent()`, right before `db.session.commit()` (after the contract loop), add:
```python
        log_event("agent_role_change", category="admin", severity="warning",
                  detail=f"updated settings/contracts for {agent.display_name} (#{agent.id})")
```

- [ ] **Step 3e: upload.py — migrate 2 existing AuditLog writes**

Import `from app.audit import log_event`. Replace the two hand-rolled `AuditLog(...)` writes (lines ~296 and ~770) with:
```python
    log_event("carrier_upload", category="business",
              detail=f"{carrier} | {filename} | {len(records)} records ({new_count} new, {updated_count} updated)")
```
Remove the now-redundant `db.session.add(log)` / `db.session.add(AuditLog(...))` lines (log_event commits its own row). Leave the surrounding upload logic untouched.

- [ ] **Step 4: Run presence tests + FULL suite (upload tests must still pass)**

Run: `python3 -m pytest tests/test_audit.py -k "hooks_present or 429_handler" -v && python3 -m pytest -q`
Expected: PASS; full suite green (the existing upload/characterization tests confirm the migration didn't break upload logging).

- [ ] **Step 5: Commit**

```bash
git add app/security.py app/customers.py app/labels.py app/agent_settings.py app/upload.py tests/test_audit.py
git commit -m "feat(s2): hooks — 429, customer_view, exports, role-change, migrate upload logs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Admin viewer /admin/audit-log (TDD)

**Files:**
- Modify: `app/routes.py` (add the route, admin-only)
- Create: `app/templates/audit_log.html`
- Modify: `tests/test_audit.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_audit.py`:

```python
def _login(client, app, db, is_admin):
    """Create a user + log them in via Flask-Login session."""
    from app.models import User, Agency
    from app.extensions import db as _db
    with app.app_context():
        ag = Agency(name="T"); _db.session.add(ag); _db.session.commit()
        u = User(email="x@foundersinsuranceagency.com", name="X",
                 is_admin=is_admin, agency_id=ag.id)
        _db.session.add(u); _db.session.commit()
        uid = u.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
    return uid


def test_audit_viewer_admin_200(app, db):
    client = app.test_client()
    _login(client, app, db, is_admin=True)
    resp = client.get("/admin/audit-log")
    assert resp.status_code == 200


def test_audit_viewer_nonadmin_403(app, db):
    client = app.test_client()
    _login(client, app, db, is_admin=False)
    resp = client.get("/admin/audit-log")
    assert resp.status_code == 403
```

- [ ] **Step 2: Run to confirm FAIL**

Run: `python3 -m pytest tests/test_audit.py -k "viewer" -v`
Expected: FAIL — route 404.

- [ ] **Step 3: Add the route to app/routes.py**

In `app/routes.py` (which holds `main` routes), add (follow the existing admin route pattern with `abort(403)`):

```python
@main.route("/admin/audit-log")
@login_required
def admin_audit_log():
    if not current_user.is_admin:
        abort(403)
    from app.models import AuditLog
    q = AuditLog.query.filter_by(agency_id=current_user.agency_id)
    # filters
    cat = request.args.get("category")
    sev = request.args.get("severity")
    if cat:
        q = q.filter(AuditLog.category == cat)
    if sev:
        q = q.filter(AuditLog.severity == sev)
    page = request.args.get("page", 1, type=int)
    logs = q.order_by(AuditLog.created_at.desc()).paginate(page=page, per_page=50, error_out=False)
    return render_template("audit_log.html", logs=logs, cat=cat, sev=sev)
```

Ensure `abort`, `request`, `render_template`, `login_required`, `current_user` are imported in routes.py (they are — verify; add any missing).

- [ ] **Step 4: Create app/templates/audit_log.html**

```html
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h1 style="color:var(--ivory-bright)">Audit Log</h1>
  <form method="get" style="display:flex;gap:12px;margin:16px 0;">
    <select name="category" onchange="this.form.submit()">
      <option value="">All categories</option>
      {% for c in ["auth","data_access","export","admin","security","business"] %}
        <option value="{{ c }}" {{ 'selected' if cat==c }}>{{ c }}</option>
      {% endfor %}
    </select>
    <select name="severity" onchange="this.form.submit()">
      <option value="">All severities</option>
      {% for s in ["info","warning","alert"] %}
        <option value="{{ s }}" {{ 'selected' if sev==s }}>{{ s }}</option>
      {% endfor %}
    </select>
  </form>
  <table class="data-table">
    <thead><tr>
      <th>Time (UTC)</th><th>User</th><th>Action</th><th>Category</th>
      <th>Severity</th><th>IP</th><th>Detail</th><th>Count</th>
    </tr></thead>
    <tbody>
      {% for r in logs.items %}
      <tr {% if r.severity=='alert' %}style="background:color-mix(in srgb, var(--gold) 12%, transparent)"{% endif %}>
        <td>{{ r.created_at }}</td>
        <td>{{ r.user.display_name if r.user else '—' }}</td>
        <td>{{ r.action }}</td>
        <td>{{ r.category or '' }}</td>
        <td>{{ r.severity or '' }}</td>
        <td>{{ r.ip_address or '' }}</td>
        <td style="max-width:340px">{{ r.detail or '' }}</td>
        <td>{{ r.record_count if r.record_count is not none else '' }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% if logs.pages > 1 %}
  <div style="margin-top:12px;">
    {% if logs.has_prev %}<a href="?page={{ logs.prev_num }}&category={{ cat or '' }}&severity={{ sev or '' }}">← Prev</a>{% endif %}
    <span style="margin:0 12px">Page {{ logs.page }} / {{ logs.pages }}</span>
    {% if logs.has_next %}<a href="?page={{ logs.next_num }}&category={{ cat or '' }}&severity={{ sev or '' }}">Next →</a>{% endif %}
  </div>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 5: Run viewer tests + full suite**

Run: `python3 -m pytest tests/test_audit.py -k "viewer" -v && python3 -m pytest -q`
Expected: PASS (admin 200, non-admin 403); full suite green.

- [ ] **Step 6: Commit**

```bash
git add app/routes.py app/templates/audit_log.html tests/test_audit.py
git commit -m "feat(s2): admin /admin/audit-log viewer (filters + pagination, admin-only)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Admin nav entry

**Files:**
- Modify: `app/templates/base.html` (admin block ~line 712-723)

- [ ] **Step 1: Add the nav link**

In `app/templates/base.html`, inside the `{% if current_user.is_admin %}` admin nav block (near the "Agent Settings" link ~line 723), add a link to the audit log following the exact markup of the adjacent admin nav items (match the `<span class="nav-dot"></span>` pattern):

```html
          <a href="{{ url_for('main.admin_audit_log') }}" class="nav-item {{ 'active' if request.endpoint == 'main.admin_audit_log' }}">
            <span class="nav-dot"></span>Audit Log
          </a>
```
(Match the surrounding items' exact classes/structure — copy the Agent Settings `<a>` and change href/label.)

- [ ] **Step 2: Verify it renders (smoke)**

Run: `RATELIMIT_ENABLED=0 python3 -c "
from app import create_app
app = create_app()
print('admin_audit_log' in [r.endpoint for r in app.url_map.iter_rules()])
"`
Expected: `True` (route exists for the nav link to resolve).

- [ ] **Step 3: Full suite**

Run: `python3 -m pytest -q`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add app/templates/base.html
git commit -m "feat(s2): admin nav link to audit log

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Full regression + smoke

**Files:** none (verification)

- [ ] **Step 1: Full suite**

Run: `python3 -m pytest -q`
Expected: all pass (188 baseline + new audit tests).

- [ ] **Step 2: Smoke — log_event end-to-end without a request**

Run: `RATELIMIT_ENABLED=0 python3 -c "
from app import create_app
from app.extensions import db
app = create_app()
with app.app_context():
    db.create_all()
    from app.audit import log_event
    r = log_event('login_success', category='auth', agency_id_override=1)
    print('row id', r.id, 'category', r.category, 'severity', r.severity)
"`
Expected: prints a row id, category auth, severity info (no crash, no alert).

- [ ] **Step 3: Commit (if any fixups needed)** — otherwise skip.

---

## Task 9: Incident Response Runbook (WITH Tim)

**Files:**
- Create: `docs/INCIDENT_RESPONSE_RUNBOOK.md`

This is drafted INTERACTIVELY with Tim (he explicitly asked to talk through "what do I actually do"). The controller pauses here and works through it with Tim conversationally, then writes the file. Content outline (fill with Tim's real answers):

- [ ] **Step 1: Draft with Tim** — walk through, per alert type (login-blocked, 429-flood) and per scenario (suspected compromised agent account, suspicious export seen in the log):
  - What the alert means (plain English).
  - Triage: was access granted? (email says).
  - Lockdown actions, concrete: revoke a user's Google session (Workspace admin console → Users → the user → Sign out / reset password), block an IP (nginx `deny` or VPS firewall — give the exact command), force ALL portal re-logins (rotate `SECRET_KEY` in VPS `.env` + restart → every session invalidated), disable a portal account.
  - Using `/admin/audit-log` to scope the extent (filter by user/IP, read what they touched, note record_count on exports).
  - HIPAA/PHI note: PHI exposure may carry breach-reporting obligations — flag it, don't give legal advice.
  - Who to call / escalation.

- [ ] **Step 2: Write `docs/INCIDENT_RESPONSE_RUNBOOK.md`** with the agreed content.

- [ ] **Step 3: Commit**

```bash
git add docs/INCIDENT_RESPONSE_RUNBOOK.md
git commit -m "docs(s2): incident response runbook (what to do when an alert fires)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Docs — mark implemented + CLAUDE.md + deploy notes

**Files:**
- Modify: spec Status line, CLAUDE.md (Build Status + START HERE)

- [ ] **Step 1: Spec status** → `✅ Implemented (local) — pending VPS deploy + verification`.

- [ ] **Step 2: CLAUDE.md** — add an S2 Build Status entry (house style) summarizing: log_event seam, 2 alert triggers (nondomain/failed login + 429 flood) email via Brevo, exports log-only with record_count, /admin/audit-log viewer, migration 025, runbook. Update START HERE: S2 done (local) → deploy → **S3 encryption-at-rest is next** (see [[s3-encryption-preview]]). Note migration head now 025.

- [ ] **Step 3: Commit.**

- [ ] **Step 4: Deploy checklist (VPS, deploy session — NOT local impl):**
```bash
git push origin main
# VPS:
cd /var/www/founders-portal && git pull \
  && ./venv/bin/pip install -r requirements.txt \
  && flask db upgrade \      # migration 025 — DOES run this time
  && systemctl restart founders-portal
```
**Backup DB first (there IS a migration this time).** Then verify on live: trigger a non-domain login (sign in with a personal gmail) → alert email arrives at admin@; visit `/admin/audit-log` as admin → see the rows incl. your login + the blocked attempt with IP; confirm a normal agent gets 403 on the viewer.

---

## Self-Review

**Spec coverage** (spec §3–§8 → tasks):
- §3.1 log_event seam → Task 2. ✓
- §3.2 alerts.py 2 rules + de-dup + email → Task 3. ✓
- §4 model + migration 025 (incl. record_count) → Task 1. ✓
- §5 trigger rules (2; exports no-alert) → Task 3 (tests assert export does NOT alert, 429 throttled to one). ✓
- §6 plain-English email (what/who/when/granted/what-to-do) → Task 3 `_compose_*`. ✓
- §7.1 viewer → Task 6; §7.2 all hook points → Tasks 4–5; §7.3 tests → Tasks 2–6 test steps. ✓
- §8 runbook → Task 9 (with Tim). ✓
- Nav → Task 7. Deploy (migration 025 → flask db upgrade + DB backup) → Task 10. ✓

**Placeholder scan:** the only intentional "fill-in-with-real-variable" spots are Task 5 export hooks (`export_rows`/`label_count`) — flagged explicitly with "use the real in-scope variable" because the exact name must be read from the file at implementation time; not a vague placeholder, a precise instruction. Runbook content (Task 9) is intentionally interactive-with-Tim, not pre-written.

**Type/name consistency:** `log_event(action, *, category, detail, user, customer_id, severity, record_count, agency_id_override)` identical across Tasks 2,4,5. Canonical action strings (login_success/login_failed/login_nondomain/logout/rate_limit_blocked/customer_view/customer_export_csv/labels_pdf_download/agent_role_change/carrier_upload) match the spec §2. `maybe_alert`, `_reset_throttle`, `_source_key`, `FLOOD_COUNT/WINDOW`, `ALERT_THROTTLE_WINDOW` consistent between Task 3 impl and its tests.

**Known test-design note:** route-hook tasks (4,5) use source-presence assertions rather than full behavioral HTTP tests, because exercising those routes needs heavy OAuth/session/file-fixture mocking disproportionate to a one-line hook — and the seam's behavior (writes row, triggers/suppresses alert correctly) is fully behavior-tested in Tasks 2–3. The viewer (Task 6) IS behavior-tested (200/403) since that's real new logic. This is a deliberate, stated trade.
