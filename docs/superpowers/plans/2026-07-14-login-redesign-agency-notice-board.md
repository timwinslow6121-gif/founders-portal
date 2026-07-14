# Login Redesign + Agency Notice Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the pestle-logo login with a Founders-themed split-screen whose left panel is a public-safe Agency Notice Board (auto-computed AEP countdown + admin-managed info/alert notices), backed by a new `AgencyNotice` model and an admin CRUD page.

**Architecture:** Two separately-testable units — a pure `next_aep(today)` helper and an `AgencyNotice` model with a single `visible_for()` classmethod — consumed by a rebuilt `login.html` (pre-auth, reads the default agency) and managed through a new `notices_bp` admin blueprint mirroring the existing `roadmap.py`. The OAuth flow is untouched; this is a template reskin + a read + a new admin surface.

**Tech Stack:** Flask 3, Flask-SQLAlchemy, Flask-Migrate (Alembic), Jinja2, vanilla CSS. PostgreSQL (prod) / SQLite (tests). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-14-login-redesign-agency-notice-board-design.md`

## Global Constraints

- **Public-safe content only** on the login board — no member names, dollar amounts, or internal operational specifics. The admin form shows an inline reminder of this.
- **Notice types are exactly `info` and `alert`** (allowlist). `info`→blue/info-icon, `alert`→rose/triangle-icon.
- **AEP countdown is auto-computed** server-side via `next_aep(today)`, NOT a DB row; always pinned first on the board.
- **Multi-tenant scoping:** `agency_notices.agency_id` is NOT NULL + indexed; every query is agency-scoped. The login page is pre-auth → it uses `current_app.config["DEFAULT_AGENCY_ID"]` (default 1), NOT `current_user`. Admin CRUD scopes to `current_user.agency_id`.
- **Admin routes** `abort(403)` BEFORE any DB lookup; non-admin never reaches data.
- **Autoescape everything** — notice `title`/`body` render WITHOUT `|safe` (they're admin-entered but shown pre-auth).
- **Defensive login read:** a failure fetching notices must NOT block the Google-SSO button from rendering.
- **Migration head is currently 036** — this adds **037** (`down_revision = "036"`).
- **Blueprint registration** uses the exact 3-line pattern in `app/__init__.py`.
- **Times EST/EDT** in any human-facing text; the DB stores UTC.
- **Deploy is done by the assistant over SSH**, never handed to Tim as commands. Back up the DB before `flask db upgrade`. `flask db` needs `FLASK_APP=wsgi.py`.

---

## File Structure

- **Create** `app/notices.py` — the `next_aep()` helper, the `NOTICE_PRESENTATION` type→icon/accent map, the board-read helper `board_notices(agency_id, today)`, AND the `notices_bp` admin blueprint (board read + AEP + type map + CRUD all live together — they change together).
- **Modify** `app/models.py` — add the `AgencyNotice` model (+ `visible_for` classmethod) near `RoadmapItem`.
- **Create** `migrations/versions/037_agency_notices.py` — the table.
- **Modify** `app/auth.py` — `login()` reads notices + AEP, passes to the template (defensively).
- **Modify** `app/__init__.py` — register `notices_bp`.
- **Rebuild** `app/templates/login.html` — the split-screen (notice board + SSO panel).
- **Create** `app/templates/admin_notices.html` — the admin list.
- **Create** `app/templates/admin_notice_form.html` — add/edit form.
- **Modify** `app/templates/base.html` — admin nav "Notices" link (near "Roadmap").
- **Create** `scripts/seed_agency_notices.py` — idempotent seed of the two starter notices.
- **Test** `tests/test_notices.py` — helper + model + routes.

---

### Task 1: `AgencyNotice` model + migration 037

**Files:**
- Modify: `app/models.py` (add class near `RoadmapItem`, ~line 1026)
- Create: `migrations/versions/037_agency_notices.py`
- Test: `tests/test_notices.py`

**Interfaces:**
- Produces: `AgencyNotice` model with columns `id, agency_id, notice_type, title, body, is_active, show_until, priority, created_at, created_by_id`; classmethod `AgencyNotice.visible_for(agency_id, today) -> list[AgencyNotice]` ordered by `priority` desc then `created_at` desc, filtered to `is_active AND (show_until IS NULL OR show_until >= today)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_notices.py`. (Check an existing test in `tests/` for the app/db fixture names — reuse the same `app`/`client`/`db_session` fixtures this suite already uses; the snippet below assumes a `db` session and an agency id of 1 exist, matching the pattern in `tests/test_roadmap.py`.)

```python
from datetime import date, timedelta
from app.models import AgencyNotice
from app.extensions import db


def _mk(agency_id=1, **kw):
    n = AgencyNotice(agency_id=agency_id,
                     notice_type=kw.get("notice_type", "info"),
                     title=kw.get("title", "T"),
                     body=kw.get("body", "B"),
                     is_active=kw.get("is_active", True),
                     show_until=kw.get("show_until"),
                     priority=kw.get("priority", 0))
    db.session.add(n); db.session.commit()
    return n


def test_visible_for_filters_and_orders(app):
    with app.app_context():
        today = date(2026, 7, 14)
        active = _mk(title="active", priority=5)
        _mk(title="inactive", is_active=False)
        _mk(title="expired", show_until=today - timedelta(days=1))
        future = _mk(title="future_exp", show_until=today + timedelta(days=1), priority=1)
        _mk(title="other_agency", agency_id=2, priority=99)

        rows = AgencyNotice.visible_for(1, today)
        titles = [r.title for r in rows]
        assert titles == ["active", "future_exp"]   # inactive/expired/other-agency excluded; priority desc
        assert active.id and future.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_notices.py::test_visible_for_filters_and_orders -v`
Expected: FAIL — `ImportError: cannot import name 'AgencyNotice'`.

- [ ] **Step 3: Add the model**

In `app/models.py`, after the `RoadmapItem` class, add:

```python
class AgencyNotice(db.Model):
    """A public-safe announcement shown on the pre-login Agency Notice Board.
    Admin-managed (see app/notices.py + docs/superpowers/specs/2026-07-14-login-
    redesign-agency-notice-board-design.md). NOTE: rendered PRE-AUTH, so content
    must be public-safe (no member names / dollar amounts / internal specifics).
    The AEP countdown is auto-computed, NOT a row here."""
    __tablename__ = "agency_notices"

    id           = db.Column(db.Integer, primary_key=True)
    agency_id    = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    agency       = db.relationship("Agency", foreign_keys=[agency_id])

    notice_type  = db.Column(db.String(16), nullable=False, default="info")  # info | alert
    title        = db.Column(db.String(200), nullable=False)
    body         = db.Column(db.Text, nullable=False)
    is_active    = db.Column(db.Boolean, nullable=False, default=True)
    show_until   = db.Column(db.Date)          # optional auto-hide date; NULL = no expiry
    priority     = db.Column(db.Integer, nullable=False, default=0)  # higher = earlier

    created_at   = db.Column(db.DateTime, server_default=db.func.now())
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_by   = db.relationship("User", foreign_keys=[created_by_id])

    NOTICE_TYPES = ("info", "alert")

    @classmethod
    def visible_for(cls, agency_id, today):
        """Notices to show on the login board for this agency, in display order.
        Active + not-yet-expired (show_until NULL or >= today), priority desc then newest."""
        return (cls.query
                .filter(cls.agency_id == agency_id,
                        cls.is_active.is_(True),
                        db.or_(cls.show_until.is_(None), cls.show_until >= today))
                .order_by(cls.priority.desc(), cls.created_at.desc())
                .all())

    def __repr__(self):
        return f"<AgencyNotice #{self.id} {self.notice_type} {self.title!r}>"
```

- [ ] **Step 4: Create the migration**

Create `migrations/versions/037_agency_notices.py`:

```python
"""agency notices (login notice board)

Revision ID: 037
Revises: 036
"""
from alembic import op
import sqlalchemy as sa

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agency_notices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("notice_type", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("show_until", sa.Date(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_agency_notices_agency_id", "agency_notices", ["agency_id"])


def downgrade():
    op.drop_index("ix_agency_notices_agency_id", table_name="agency_notices")
    op.drop_table("agency_notices")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_notices.py::test_visible_for_filters_and_orders -v`
Expected: PASS. (The test suite creates tables from models via the test fixture, so the model alone makes it green; the migration is for real Postgres.)

- [ ] **Step 6: Commit**

```bash
git add app/models.py migrations/versions/037_agency_notices.py tests/test_notices.py
git commit -m "feat: AgencyNotice model + migration 037 (login notice board)"
```

---

### Task 2: `next_aep()` helper + notice presentation map + board read

**Files:**
- Create: `app/notices.py`
- Test: `tests/test_notices.py` (append)

**Interfaces:**
- Consumes: `AgencyNotice.visible_for` (Task 1).
- Produces:
  - `next_aep(today) -> (days:int, year:int)` — days to next Oct 15 (0 on Oct 15), and that Oct 15's calendar year.
  - `NOTICE_PRESENTATION = {"info": {...}, "alert": {...}}` — each value has `accent` (CSS class suffix) + `icon` (svg key). Used by the template.
  - `board_notices(agency_id, today) -> list[AgencyNotice]` — thin wrapper over `visible_for` (single seam the login route calls).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_notices.py`:

```python
from datetime import date
from app.notices import next_aep, NOTICE_PRESENTATION


def test_next_aep_before_oct15():
    assert next_aep(date(2026, 7, 14)) == (93, 2026)

def test_next_aep_on_oct15():
    assert next_aep(date(2026, 10, 15)) == (0, 2026)

def test_next_aep_after_oct15_rolls_to_next_year():
    d, y = next_aep(date(2026, 11, 1))
    assert y == 2027
    assert d == (date(2027, 10, 15) - date(2026, 11, 1)).days

def test_notice_presentation_covers_types():
    assert set(NOTICE_PRESENTATION) == {"info", "alert"}
    for v in NOTICE_PRESENTATION.values():
        assert "accent" in v and "icon" in v
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_notices.py -k "aep or presentation" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.notices'`.

- [ ] **Step 3: Create `app/notices.py` (helper + map + read; blueprint added in Task 3)**

```python
"""Agency Notice Board — the public-safe board on the pre-login page.
Holds the AEP-countdown helper, the notice-type presentation map, the board
read, and (added in the admin task) the notices_bp CRUD blueprint.
See docs/superpowers/specs/2026-07-14-login-redesign-agency-notice-board-design.md."""
from datetime import date

from app.models import AgencyNotice

# notice_type -> presentation. ONE place; template + tests agree on this.
NOTICE_PRESENTATION = {
    "info":  {"accent": "info",  "icon": "info"},
    "alert": {"accent": "alert", "icon": "alert"},
}


def next_aep(today):
    """(days, year) until the next AEP start (Oct 15). days>=0 (0 on Oct 15);
    rolls to next year once Oct 15 has passed. year = calendar year of that Oct 15."""
    aep = date(today.year, 10, 15)
    if today > aep:
        aep = date(today.year + 1, 10, 15)
    return (aep - today).days, aep.year


def board_notices(agency_id, today=None):
    """Visible notices for the login board (thin seam over the model)."""
    return AgencyNotice.visible_for(agency_id, today or date.today())
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_notices.py -k "aep or presentation" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/notices.py tests/test_notices.py
git commit -m "feat: next_aep helper + notice presentation map + board read"
```

---

### Task 3: Admin CRUD blueprint (`notices_bp`)

**Files:**
- Modify: `app/notices.py` (append the blueprint)
- Modify: `app/__init__.py:27-38` (register)
- Create: `app/templates/admin_notices.html`
- Create: `app/templates/admin_notice_form.html`
- Test: `tests/test_notices.py` (append)

**Interfaces:**
- Consumes: `AgencyNotice` (Task 1), `NOTICE_PRESENTATION` (Task 2).
- Produces: blueprint `notices_bp` with routes `admin_notices` (`GET /admin/notices`), `admin_notice_new` (`GET/POST /admin/notices/new`), `admin_notice_edit` (`GET/POST /admin/notices/<int:id>/edit`), `admin_notice_delete` (`POST /admin/notices/<int:id>/delete`). All admin-only, agency-scoped.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_notices.py`. (Use this suite's helpers for an admin client and a non-admin client — check `tests/test_roadmap.py` for the exact login fixture; below assumes `admin_client` and `agent_client` fixtures like other admin-route tests.)

```python
def test_non_admin_forbidden(agent_client):
    assert agent_client.get("/admin/notices").status_code == 403

def test_admin_can_create_notice(admin_client, app):
    r = admin_client.post("/admin/notices/new", data={
        "notice_type": "alert", "title": "Portal maintenance",
        "body": "Brief downtime tonight.", "priority": "3", "show_until": "", "is_active": "on",
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from app.models import AgencyNotice
        n = AgencyNotice.query.filter_by(title="Portal maintenance").first()
        assert n and n.notice_type == "alert" and n.priority == 3 and n.show_until is None

def test_blank_title_rerenders_not_500(admin_client):
    r = admin_client.post("/admin/notices/new", data={
        "notice_type": "info", "title": "", "body": "x", "priority": "0", "is_active": "on"})
    assert r.status_code == 200          # re-render, not a 500
    assert b"Title" in r.data

def test_bad_notice_type_rejected(admin_client, app):
    admin_client.post("/admin/notices/new", data={
        "notice_type": "danger", "title": "Bad", "body": "x", "priority": "0", "is_active": "on"})
    with app.app_context():
        from app.models import AgencyNotice
        assert AgencyNotice.query.filter_by(title="Bad").first() is None

def test_delete_removes_notice(admin_client, app):
    admin_client.post("/admin/notices/new", data={
        "notice_type": "info", "title": "Temp", "body": "x", "priority": "0", "is_active": "on"})
    with app.app_context():
        from app.models import AgencyNotice
        nid = AgencyNotice.query.filter_by(title="Temp").first().id
    admin_client.post(f"/admin/notices/{nid}/delete")
    with app.app_context():
        from app.models import AgencyNotice
        assert AgencyNotice.query.get(nid) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_notices.py -k "admin or forbidden or blank or bad_notice or delete" -v`
Expected: FAIL — 404s (routes don't exist yet).

- [ ] **Step 3: Append the blueprint to `app/notices.py`**

Add these imports at the top of `app/notices.py` (with the existing ones):

```python
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, abort)
from flask_login import current_user, login_required
from app.extensions import db
```

Append at the end of `app/notices.py`:

```python
notices_bp = Blueprint("notices", __name__)

_VALID_TYPES = set(AgencyNotice.NOTICE_TYPES)


def _parse_form(form):
    """Return (data, error). data has cleaned fields; error is a message or None."""
    title = (form.get("title") or "").strip()
    body = (form.get("body") or "").strip()
    ntype = (form.get("notice_type") or "").strip()
    if not title:
        return None, "Title is required."
    if not body:
        return None, "Message body is required."
    if ntype not in _VALID_TYPES:
        return None, "Please choose a valid notice type."
    try:
        priority = int(form.get("priority") or 0)
    except ValueError:
        return None, "Priority must be a number."
    show_until_raw = (form.get("show_until") or "").strip()
    show_until = None
    if show_until_raw:
        try:
            show_until = datetime.strptime(show_until_raw, "%Y-%m-%d").date()
        except ValueError:
            return None, "Show-until must be a valid date."
    return {
        "title": title, "body": body, "notice_type": ntype,
        "priority": priority, "show_until": show_until,
        "is_active": form.get("is_active") == "on",
    }, None


@notices_bp.route("/admin/notices")
@login_required
def admin_notices():
    if not current_user.is_admin:
        abort(403)
    today = date.today()
    notices = (AgencyNotice.query
               .filter_by(agency_id=current_user.agency_id)
               .order_by(AgencyNotice.priority.desc(), AgencyNotice.created_at.desc())
               .all())
    return render_template("admin_notices.html", notices=notices, today=today,
                           presentation=NOTICE_PRESENTATION)


@notices_bp.route("/admin/notices/new", methods=["GET", "POST"])
@login_required
def admin_notice_new():
    if not current_user.is_admin:
        abort(403)
    if request.method == "POST":
        data, error = _parse_form(request.form)
        if error:
            flash(error, "error")
            return render_template("admin_notice_form.html", notice=None,
                                   form=request.form, types=AgencyNotice.NOTICE_TYPES)
        n = AgencyNotice(agency_id=current_user.agency_id,
                         created_by_id=current_user.id, **data)
        db.session.add(n); db.session.commit()
        flash("Notice added.", "success")
        return redirect(url_for("notices.admin_notices"))
    return render_template("admin_notice_form.html", notice=None,
                           form={}, types=AgencyNotice.NOTICE_TYPES)


@notices_bp.route("/admin/notices/<int:notice_id>/edit", methods=["GET", "POST"])
@login_required
def admin_notice_edit(notice_id):
    if not current_user.is_admin:
        abort(403)
    n = AgencyNotice.query.filter_by(
        id=notice_id, agency_id=current_user.agency_id).first_or_404()
    if request.method == "POST":
        data, error = _parse_form(request.form)
        if error:
            flash(error, "error")
            return render_template("admin_notice_form.html", notice=n,
                                   form=request.form, types=AgencyNotice.NOTICE_TYPES)
        for k, v in data.items():
            setattr(n, k, v)
        db.session.commit()
        flash("Notice updated.", "success")
        return redirect(url_for("notices.admin_notices"))
    return render_template("admin_notice_form.html", notice=n,
                           form={}, types=AgencyNotice.NOTICE_TYPES)


@notices_bp.route("/admin/notices/<int:notice_id>/delete", methods=["POST"])
@login_required
def admin_notice_delete(notice_id):
    if not current_user.is_admin:
        abort(403)
    n = AgencyNotice.query.filter_by(
        id=notice_id, agency_id=current_user.agency_id).first_or_404()
    db.session.delete(n); db.session.commit()
    flash("Notice deleted.", "success")
    return redirect(url_for("notices.admin_notices"))
```

- [ ] **Step 4: Register the blueprint**

In `app/__init__.py`, after the `from app.roadmap import roadmap_bp` line (~27) add `from app.notices import notices_bp`, and after `app.register_blueprint(roadmap_bp)` (~38) add:

```python
    app.register_blueprint(notices_bp)
```

- [ ] **Step 5: Create the two admin templates**

Create `app/templates/admin_notices.html` (extends base, Founders theme via tokens — follow `roadmap.html` for structure):

```html
{% extends "base.html" %}
{% block content %}
<div style="max-width:920px;margin:0 auto;">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px;">
    <h1 style="font-family:var(--serif);color:var(--ivory-bright);margin:0;">Login Notices</h1>
    <a href="{{ url_for('notices.admin_notice_new') }}" class="btn btn-primary">+ New notice</a>
  </div>
  <p style="color:var(--slate);font-size:13.5px;margin:-8px 0 18px;">
    These appear on the <strong>public login page</strong>. Keep them public-safe — no member names,
    dollar amounts, or internal details. The AEP countdown is automatic and always shown.
  </p>
  {% for n in notices %}
    {% set expired = n.show_until and n.show_until < today %}
    <div class="card" style="display:flex;gap:14px;align-items:flex-start;margin-bottom:12px;
         {% if not n.is_active or expired %}opacity:.6;{% endif %}">
      <span class="badge badge-{{ presentation[n.notice_type].accent if n.notice_type in presentation else 'info' }}">
        {{ n.notice_type }}</span>
      <div style="flex:1;min-width:0;">
        <div style="font-weight:800;color:var(--ivory-bright);">{{ n.title }}</div>
        <div style="color:var(--slate);font-size:13.5px;margin-top:3px;">{{ n.body }}</div>
        <div style="color:var(--slate);font-size:12px;margin-top:6px;">
          priority {{ n.priority }}
          {% if n.show_until %} · until {{ n.show_until.strftime('%b %-d, %Y') }}{% endif %}
          {% if not n.is_active %} · <strong>inactive</strong>{% endif %}
          {% if expired %} · <strong>expired</strong>{% endif %}
        </div>
      </div>
      <a href="{{ url_for('notices.admin_notice_edit', notice_id=n.id) }}" class="btn btn-secondary">Edit</a>
      <form method="post" action="{{ url_for('notices.admin_notice_delete', notice_id=n.id) }}"
            onsubmit="return confirm('Delete this notice?');" style="margin:0;">
        <button class="btn btn-secondary" type="submit">Delete</button>
      </form>
    </div>
  {% else %}
    <p style="color:var(--slate);">No notices yet. The AEP countdown still shows on the login page.</p>
  {% endfor %}
</div>
{% endblock %}
```

Create `app/templates/admin_notice_form.html`:

```html
{% extends "base.html" %}
{% block content %}
<div style="max-width:620px;margin:0 auto;">
  <h1 style="font-family:var(--serif);color:var(--ivory-bright);">
    {{ "Edit notice" if notice else "New notice" }}</h1>
  <p style="color:var(--slate);font-size:13px;">
    Shows on the <strong>public login page</strong> — no member names, dollar amounts, or internal details.</p>
  {% with msgs = get_flashed_messages(with_categories=true) %}
    {% for cat, m in msgs %}<div class="badge badge-{{ 'alert' if cat=='error' else 'info' }}"
      style="display:block;margin:8px 0;">{{ m }}</div>{% endfor %}
  {% endwith %}
  {% set v = notice or form %}
  {% macro val(field, default='') %}{{ (form.get(field) if form else None) or (notice[field] if notice else None) or default }}{% endmacro %}
  <form method="post" class="card" style="display:flex;flex-direction:column;gap:14px;">
    <label>Type
      <select name="notice_type">
        {% set cur = (form.get('notice_type') if form else None) or (notice.notice_type if notice else 'info') %}
        {% for t in types %}<option value="{{ t }}" {{ 'selected' if t==cur else '' }}>{{ t }}</option>{% endfor %}
      </select>
    </label>
    <label>Title <input type="text" name="title" maxlength="200" value="{{ val('title') }}"></label>
    <label>Message <textarea name="body" rows="3">{{ val('body') }}</textarea></label>
    <label>Priority (higher shows first)
      <input type="number" name="priority" value="{{ val('priority', 0) }}"></label>
    <label>Show until (optional — auto-hides after this date)
      <input type="date" name="show_until"
        value="{{ (form.get('show_until') if form else None) or (notice.show_until.isoformat() if notice and notice.show_until else '') }}"></label>
    <label style="display:flex;gap:8px;align-items:center;">
      <input type="checkbox" name="is_active"
        {{ 'checked' if (not notice) or (notice and notice.is_active) else '' }}> Active</label>
    <div style="display:flex;gap:10px;">
      <button class="btn btn-primary" type="submit">Save</button>
      <a href="{{ url_for('notices.admin_notices') }}" class="btn btn-secondary">Cancel</a>
    </div>
  </form>
</div>
{% endblock %}
```

Note on the `badge-info`/`badge-alert` classes: if base.html has no `badge-alert`, add two small rules in this task's `admin_notices.html`/`admin_notice_form.html` `{% block styles %}` (or inline): `.badge-info{background:color-mix(in srgb,var(--blue) 16%,transparent);color:var(--blue);}` and `.badge-alert{background:color-mix(in srgb,#C0392B 16%,transparent);color:#C0392B;}`. Check base.html first; reuse existing badge classes if present.

- [ ] **Step 6: Run to verify it passes**

Run: `python3 -m pytest tests/test_notices.py -v`
Expected: PASS (all model + helper + route tests).

- [ ] **Step 7: Commit**

```bash
git add app/notices.py app/__init__.py app/templates/admin_notices.html app/templates/admin_notice_form.html tests/test_notices.py
git commit -m "feat: /admin/notices CRUD (notices_bp)"
```

---

### Task 4: Wire the login route + admin nav link

**Files:**
- Modify: `app/auth.py:50-52` (the `login()` route) and `:125-126` (the error render)
- Modify: `app/templates/base.html` (admin nav, near the "Roadmap" link ~line 858)
- Test: `tests/test_notices.py` (append)

**Interfaces:**
- Consumes: `board_notices` + `next_aep` (Task 2), `NOTICE_PRESENTATION` (Task 2).
- Produces: `login.html` receives `notices`, `aep_days`, `aep_year`, `presentation`, `error`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_notices.py`:

```python
def test_login_page_shows_notices_and_aep_unauthenticated(client, app):
    with app.app_context():
        from app.models import AgencyNotice
        from app.extensions import db
        db.session.add(AgencyNotice(agency_id=1, notice_type="info",
            title="Beta Notice", body="In active development.", is_active=True, priority=1))
        db.session.commit()
    r = client.get("/auth/login")            # no auth
    assert r.status_code == 200
    assert b"Beta Notice" in r.data
    assert b"Countdown" in r.data            # AEP widget rendered
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_notices.py::test_login_page_shows_notices_and_aep_unauthenticated -v`
Expected: FAIL — page renders but lacks "Beta Notice"/"Countdown" (old template).

- [ ] **Step 3: Update `app/auth.py`**

Add imports near the top of `app/auth.py`:

```python
from datetime import date
from flask import current_app
from app.notices import board_notices, next_aep, NOTICE_PRESENTATION
```

Replace the `login()` route (lines ~50-52):

```python
@auth.route('/login')
def login():
    return _render_login()


def _render_login(error=None):
    """Login page with the public-safe notice board. The board read is defensive:
    a failure NEVER blocks the Google-SSO button (the board is enhancement, not a gate)."""
    today = date.today()
    aid = current_app.config.get("DEFAULT_AGENCY_ID", 1)  # pre-auth: no current_user
    try:
        notices = board_notices(aid, today)
    except Exception:
        current_app.logger.exception("notice board read failed; showing login without it")
        notices = []
    aep_days, aep_year = next_aep(today)
    return render_template('login.html', error=error, notices=notices,
                           aep_days=aep_days, aep_year=aep_year,
                           presentation=NOTICE_PRESENTATION)
```

And change the non-domain error render (line ~125-126) from `render_template('login.html', error=...)` to:

```python
        return _render_login(
            error='Access restricted to @foundersinsuranceagency.com accounts.')
```

- [ ] **Step 4: Add the admin nav link**

In `app/templates/base.html`, right after the "Roadmap" nav link block (~line 858-860, inside the `{% if current_user.is_admin %}` admin section), add:

```html
        <a href="{{ url_for('notices.admin_notices') }}" class="nav-item {% if request.endpoint and request.endpoint.startswith('notices.') %}active{% endif %}">
          <span class="nav-dot"></span>Notices
        </a>
```

- [ ] **Step 5: Run to verify it passes**

Run: `python3 -m pytest tests/test_notices.py::test_login_page_shows_notices_and_aep_unauthenticated -v`
Expected: still FAIL on the assertions until Task 5 rebuilds the template (the route now passes the data, but the OLD template ignores `notices`). That's expected — this test goes green in Task 5. Mark it `@pytest.mark.xfail(reason="template rebuilt in Task 5", strict=False)` OR simply note it and let Task 5 remove the marker. **Recommended:** add the xfail marker now, remove it in Task 5.

- [ ] **Step 6: Commit**

```bash
git add app/auth.py app/templates/base.html tests/test_notices.py
git commit -m "feat: login route reads notice board (defensive) + admin nav link"
```

---

### Task 5: Rebuild `login.html` (split-screen)

**Files:**
- Rebuild: `app/templates/login.html` (replace entirely)
- Modify: `tests/test_notices.py` (remove the xfail marker from Task 4's test)

**Interfaces:**
- Consumes: `notices`, `aep_days`, `aep_year`, `presentation`, `error` from the route (Task 4).

The visual reference is the approved artifact (login v2). The template is standalone (does NOT extend base.html) and loads fonts via the same Google Fonts `<link>` the current login uses. Use the Founders palette; the login panel is theme-aware (device default + a toggle), the notice-board stage stays dark by design.

- [ ] **Step 1: Replace `app/templates/login.html`**

Replace the ENTIRE file with the split-screen. Port the CSS/markup from the approved mockup at `/tmp/.../scratchpad/login_v2_mockup.html` (the assistant has it), adapting:
- Keep the existing `<head>` font `<link>` (Plus Jakarta Sans + Merriweather) and `<title>Founders Insurance — Agent Portal</title>`.
- Render the Google SSO button as a real link to the existing route: `<a href="{{ url_for('auth.google_login') }}" class="gbtn">…</a>` (NOT a JS stub — the mockup's `signIn()` sim is replaced by the real link).
- AEP card: `AEP {{ aep_year }} Countdown` + `{{ aep_days }} Days`.
- Notice loop:
  ```html
  {% for n in notices %}
    {% set p = presentation.get(n.notice_type, presentation['info']) %}
    <div class="widget {{ 'is-alert' if n.notice_type == 'alert' else '' }}">
      <span class="wic {{ p.accent }}">{{ ICON SVG for p.icon }}</span>
      <div class="wbody">
        <div class="wtitle"><span>{{ n.title }}</span></div>
        <div class="wtext">{{ n.body }}</div>
      </div>
    </div>
  {% else %}
    <div class="wtext" style="opacity:.7;">All clear — no active notices.</div>
  {% endfor %}
  ```
  (Two inline SVGs, keyed by `p.icon` — `info` and `alert`. No emoji-as-icon, no external icon CDN.)
- Logo mark: inline the Founders blue→green mark (the abstract "F" from the mockup) OR `<img src="{{ url_for('static', filename='img/founders-mark.svg') }}">`. NO pestle. **Confirm the file exists first** (`app/static/img/founders-mark.svg`); if it's the all-white login variant, use the inline blue/green "F" from the mockup instead.
- `{% if error %}` renders the error message inline on the login panel.
- Theme toggle + no-flash pre-paint script: mirror the pattern in base.html's `<head>` (read the saved `localStorage['fp-theme']` before first paint, apply `data-theme`), scoped so the login panel honors it. The notice stage stays dark regardless.
- Respect `prefers-reduced-motion`.

- [ ] **Step 2: Remove the xfail marker**

In `tests/test_notices.py`, delete the `@pytest.mark.xfail(...)` line above `test_login_page_shows_notices_and_aep_unauthenticated`.

- [ ] **Step 3: Run the login tests**

Run: `python3 -m pytest tests/test_notices.py -v`
Expected: PASS (all, including the login-page test now that the template renders `notices` + "Countdown").

- [ ] **Step 4: Visual verification (headless screenshot)**

Render the login page and screenshot it in BOTH themes + mobile width to confirm layout. Use the project's existing headless-screenshot approach (Playwright): navigate to `/auth/login` on a locally-running instance (or render the template with sample context to a static file and serve it), screenshot desktop-light, desktop-dark (toggle), and 375px-wide. Confirm: no pestle; notice board on the left with AEP pinned + the seeded notice; SSO button present; no horizontal scroll on mobile; readable contrast in both themes.

- [ ] **Step 5: Commit**

```bash
git add app/templates/login.html tests/test_notices.py
git commit -m "feat: rebuild login as Founders split-screen with notice board (retire pestle)"
```

---

### Task 6: Seed script + full-suite green

**Files:**
- Create: `scripts/seed_agency_notices.py`
- Test: run the whole suite

**Interfaces:**
- Consumes: `AgencyNotice` (Task 1).

- [ ] **Step 1: Create the seed script**

```python
"""Seed the two public-safe starter notices (idempotent on agency_id+title).
The AEP countdown is auto-computed, NOT seeded here.
Run: FLASK_APP=wsgi.py PYTHONPATH=. ./venv/bin/python3 scripts/seed_agency_notices.py [--apply]"""
import sys
from app import create_app
from app.extensions import db
from app.models import AgencyNotice

SEEDS = [
    {"notice_type": "alert", "priority": 5, "title": "Founders Portal maintenance",
     "body": "Founders Portal maintenance is performed periodically. The portal may be "
             "briefly unavailable during updates."},
    {"notice_type": "info", "priority": 1, "title": "Portal is in active development",
     "body": "The Founders Portal is in active development. Some features may not work exactly "
             "as expected — thanks for your patience. Spotted something off? Log it on the Roadmap board."},
]


def main(apply):
    app = create_app()
    with app.app_context():
        aid = app.config.get("DEFAULT_AGENCY_ID", 1)
        created = 0
        for s in SEEDS:
            exists = AgencyNotice.query.filter_by(agency_id=aid, title=s["title"]).first()
            if exists:
                print(f"skip (exists): {s['title']}")
                continue
            print(f"{'CREATE' if apply else 'would create'}: [{s['notice_type']}] {s['title']}")
            if apply:
                db.session.add(AgencyNotice(agency_id=aid, is_active=True, **s))
                created += 1
        if apply:
            db.session.commit()
        print(f"done. created={created} (apply={apply})")


if __name__ == "__main__":
    main("--apply" in sys.argv)
```

- [ ] **Step 2: Dry-run it locally**

Run: `PYTHONPATH=. python3 scripts/seed_agency_notices.py`
Expected: prints "would create" for both, `created=0`.

- [ ] **Step 3: Run the FULL suite**

Run: `python3 -m pytest -q`
Expected: PASS — the whole suite (baseline was 617; now higher with the new tests), no regressions.

- [ ] **Step 4: Commit**

```bash
git add scripts/seed_agency_notices.py
git commit -m "feat: idempotent seed for the two starter login notices"
```

---

## Deployment (assistant runs this after the whole-branch review, NOT a task the reviewer gates)

1. Merge the branch to main.
2. Back up the prod DB: `ssh` in, `PGPASSWORD=<from .env DATABASE_URL> pg_dump -U founders_user -h localhost founders_portal > /root/founders_pre_notices_$(date +%Y%m%d_%H%M%S).sql`.
3. `cd /var/www/founders-portal && git pull && ./venv/bin/pip install -r requirements.txt` (no new deps, harmless) `&& FLASK_APP=wsgi.py ./venv/bin/flask db upgrade` (036→037) `&& systemctl restart founders-portal`.
4. Seed: `FLASK_APP=wsgi.py PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_agency_notices.py --apply`.
5. Verify: `/auth/login` returns 200 and renders the board (AEP + 2 notices, no pestle); complete a real Google sign-in end-to-end to confirm the pre-auth read did NOT break auth; `/admin/notices` 200 for an admin, 403 for a read-only agent. Confirm restart cycled (ActiveEnterTimestamp advanced).

---

## Self-Review

**Spec coverage:** model (T1) ✓, `next_aep` + presentation map + board read (T2) ✓, admin CRUD with allowlist + blank-title guard + expiry (T3) ✓, login route defensive read + pre-auth default-agency + admin nav (T4) ✓, split-screen rebuild + empty state + theme + no pestle (T5) ✓, seed + rollout (T6 + deploy) ✓. Public-safe reminder appears in both admin templates ✓. Types limited to info/alert ✓.

**Placeholder scan:** the one soft spot is T5 Step 1 ("port the CSS from the mockup") — acceptable because the full mockup CSS exists as a concrete artifact the implementer is handed; the adaptations (real SSO link, notice loop, AEP interpolation, error, theme) are all spelled out with code. The icon SVGs are described as "two inline SVGs keyed by p.icon" — the mockup already contains both (info/alert triangle), so they're transcribed, not invented.

**Type consistency:** `visible_for(agency_id, today)` (T1) called by `board_notices` (T2) and the admin list (T3) — consistent. `next_aep` returns `(days, year)` used as `aep_days, aep_year` (T4) and `AEP {{ aep_year }}` / `{{ aep_days }}` (T5) — consistent. `NOTICE_PRESENTATION` keys `info`/`alert` match `AgencyNotice.NOTICE_TYPES` (T1) and the template loop (T5) — consistent. Route names `notices.admin_notices` etc. match the nav link (T4) and templates (T3) — consistent.
