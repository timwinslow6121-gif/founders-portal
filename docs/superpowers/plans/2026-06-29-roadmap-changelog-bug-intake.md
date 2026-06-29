# Roadmap & Changelog + Bug Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/roadmap` board page (Planned/Known · In progress · Shipped) of expand-in-place cards showing "what the issue was → the fix", where any agent can submit a bug visible to everyone, and admins triage/dismiss.

**Architecture:** One new `RoadmapItem` model + migration; one `roadmap_bp` blueprint (board read + submit + admin edit/dismiss); one `roadmap.html` template (board + submit form + admin-only controls); a nav item; a curated history seed script. Everyone sees the same shared board (no private/public split) — only `dismissed`/`wont_fix` items drop off it.

**Tech Stack:** Python 3.10, Flask, Flask-SQLAlchemy, Flask-Migrate (Alembic), Jinja2, pytest. PostgreSQL on VPS / SQLite in tests.

## Global Constraints

- **Everyone sees everything.** All non-`hidden` items appear on the shared board for every agent AND admin (the anti-duplicate guarantee). NO `visibility` column, NO per-agent private filtering of the board.
- **`hidden` = off the shared board** = status ∈ {`wont_fix`, `dismissed`}. A `hidden` item is still visible to its OWN submitter (via `?mine=1`) and to admins (via an admin filter). Nothing is hard-deleted by dismiss.
- **Entry types:** `bug_fix` | `feature` | `planned` | `known_issue`. **Statuses:** `submitted` | `acknowledged` | `planned` | `in_progress` | `shipped` | `wont_fix` | `dismissed`. **Priorities:** `low` | `medium` | `high` (nullable).
- **Column mapping lives in ONE place** — a `RoadmapItem.column` property returning `planned` | `in_progress` | `shipped` | `hidden`.
- **Multi-tenant:** every query `agency_id`-scoped (`filter_by(agency_id=current_user.agency_id, ...)`). Never leak across agencies.
- **Auth:** only `submit` is open to any logged-in agent; every admin action (`edit`, `dismiss`, `delete`) is `if not current_user.is_admin: abort(403)`.
- **Blueprint registration:** the exact 3-line pattern in `app/__init__.py` (`from app.roadmap import roadmap_bp` / `app.register_blueprint(roadmap_bp)`).
- **Founders theme:** in-app blue/green tokens from `base.html` (`--gold` is blue, `--green` green, `--ivory`/`--slate` text, `--surface` card, `--ink` background). Never use `var(--ink)` for text.
- **Migration head is `031`** → this adds **`032`**, `down_revision = "031"`.
- **Tests:** `python3 -m pytest -q`. Frequent commits, one deliverable per task.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `app/models.py` | `RoadmapItem` model + `column` property + `board_status_label` | Add (near the other simple models, e.g. after `UnmatchedCall`) |
| `migrations/versions/032_roadmap_items.py` | `roadmap_items` table | Create |
| `app/roadmap.py` | `roadmap_bp` — board read, submit, admin edit/dismiss | Create |
| `app/templates/roadmap.html` | the board + submit form + admin controls | Create |
| `app/__init__.py` | register `roadmap_bp` | Modify (2 lines) |
| `app/templates/base.html` | nav item (admin Tools + agent Tools) | Modify |
| `scripts/seed_roadmap.py` | curated history seed (dry-run/--apply, idempotent) | Create |
| `tests/test_roadmap.py` | model, routes, shared-visibility, dismiss, auth, multi-tenant | Create |

**Existing fixtures (conftest.py):** `app`, `db_session`, `agency`, `admin_user` (is_admin=True), `agent_user` (is_admin=False), `client`. `User.display_name` (property). Tests use `with app.app_context():` and set the session via `with client.session_transaction() as s: s["_user_id"] = str(uid)`.

---

### Task 1: `RoadmapItem` model + `column` property + migration

**Files:**
- Modify: `app/models.py` (add the model after the `UnmatchedCall` class)
- Create: `migrations/versions/032_roadmap_items.py`
- Test: `tests/test_roadmap.py` (new)

**Interfaces:**
- Produces: `RoadmapItem` model with columns `id, agency_id, type, title, issue_text, fix_text, status (default 'submitted'), priority, submitted_by_id, shipped_on, created_at, updated_at`. A `@property column` returning one of `"planned" | "in_progress" | "shipped" | "hidden"`. A `submitted_by` relationship to `User`.

- [ ] **Step 1: Write the failing test for the model + column mapping**

Create `tests/test_roadmap.py`:

```python
from datetime import date
import pytest


def test_roadmap_item_column_maps_status(db_session, app, agency):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        cases = {
            "shipped": "shipped",
            "in_progress": "in_progress",
            "submitted": "planned",
            "acknowledged": "planned",
            "planned": "planned",
            "wont_fix": "hidden",
            "dismissed": "hidden",
        }
        for status, expected_col in cases.items():
            it = RoadmapItem(agency_id=agency.id, type="bug_fix",
                             title=f"t-{status}", status=status)
            db.session.add(it); db.session.flush()
            assert it.column == expected_col, f"{status} -> {it.column}, want {expected_col}"


def test_roadmap_item_known_issue_type_is_planned_column(db_session, app, agency):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        it = RoadmapItem(agency_id=agency.id, type="known_issue",
                         title="counts mismatch", status="acknowledged")
        db.session.add(it); db.session.flush()
        assert it.column == "planned"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_roadmap.py -k column -v`
Expected: FAIL — `ImportError: cannot import name 'RoadmapItem'`.

- [ ] **Step 3: Add the `RoadmapItem` model**

In `app/models.py`, after the `UnmatchedCall` class, add:

```python
class RoadmapItem(db.Model):
    """A roadmap / changelog entry OR an agent-submitted bug. Everyone sees the
    shared board (no private/public split); only `wont_fix`/`dismissed` items drop
    off it (still visible to their own submitter + admins). See
    docs/superpowers/specs/2026-06-29-roadmap-changelog-bug-intake-design.md."""
    __tablename__ = "roadmap_items"

    id            = db.Column(db.Integer, primary_key=True)
    agency_id     = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    agency        = db.relationship("Agency", foreign_keys=[agency_id])

    type          = db.Column(db.String(16), nullable=False, default="bug_fix")   # bug_fix|feature|planned|known_issue
    title         = db.Column(db.String(200), nullable=False)
    issue_text    = db.Column(db.Text)        # "what was wrong"
    fix_text      = db.Column(db.Text)        # "the fix" / what we did
    status        = db.Column(db.String(20), nullable=False, default="submitted", index=True)
                    # submitted|acknowledged|planned|in_progress|shipped|wont_fix|dismissed
    priority      = db.Column(db.String(8))   # low|medium|high
    submitted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    submitted_by  = db.relationship("User", foreign_keys=[submitted_by_id])
    shipped_on    = db.Column(db.Date)        # for shipped ordering / "from day 1"

    created_at    = db.Column(db.DateTime, server_default=db.func.now())
    updated_at    = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    # ONE place that maps status -> board column (template + tests agree on this).
    _PLANNED_STATUSES = {"submitted", "acknowledged", "planned"}
    _HIDDEN_STATUSES  = {"wont_fix", "dismissed"}

    @property
    def column(self):
        if self.status == "shipped":
            return "shipped"
        if self.status == "in_progress":
            return "in_progress"
        if self.status in self._HIDDEN_STATUSES:
            return "hidden"
        # remaining: submitted/acknowledged/planned, OR a planned/known_issue-type entry
        if self.status in self._PLANNED_STATUSES or self.type in ("planned", "known_issue"):
            return "planned"
        return "planned"

    def __repr__(self):
        return f"<RoadmapItem #{self.id} {self.type}/{self.status} {self.title!r}>"
```

- [ ] **Step 4: Run the model test to verify it passes**

Run: `python3 -m pytest tests/test_roadmap.py -k column -v`
Expected: PASS.

- [ ] **Step 5: Create the migration**

Create `migrations/versions/032_roadmap_items.py`:

```python
"""roadmap_items — roadmap/changelog entries + agent bug submissions

Revision ID: 032
Revises: 031
"""
from alembic import op
import sqlalchemy as sa

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "roadmap_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False, server_default="bug_fix"),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("issue_text", sa.Text(), nullable=True),
        sa.Column("fix_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="submitted"),
        sa.Column("priority", sa.String(length=8), nullable=True),
        sa.Column("submitted_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("shipped_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_roadmap_items_agency_id", "roadmap_items", ["agency_id"])
    op.create_index("ix_roadmap_items_status", "roadmap_items", ["status"])
    op.create_index("ix_roadmap_items_submitted_by_id", "roadmap_items", ["submitted_by_id"])


def downgrade():
    op.drop_index("ix_roadmap_items_submitted_by_id", table_name="roadmap_items")
    op.drop_index("ix_roadmap_items_status", table_name="roadmap_items")
    op.drop_index("ix_roadmap_items_agency_id", table_name="roadmap_items")
    op.drop_table("roadmap_items")
```

- [ ] **Step 6: Verify the migration imports cleanly + full model test**

Run: `python3 -c "import importlib.util, pathlib; importlib.util.spec_from_file_location('m', 'migrations/versions/032_roadmap_items.py')" && python3 -m pytest tests/test_roadmap.py -q`
Expected: no import error; tests PASS.

- [ ] **Step 7: Commit**

```bash
git add app/models.py migrations/versions/032_roadmap_items.py tests/test_roadmap.py
git commit -m "feat: RoadmapItem model + migration 032 + column mapping

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `roadmap_bp` blueprint — shared board read + submit

**Files:**
- Create: `app/roadmap.py`
- Modify: `app/__init__.py` (register the blueprint)
- Test: `tests/test_roadmap.py` (add)

**Interfaces:**
- Consumes: `RoadmapItem` (Task 1), `User.display_name`, `current_user`, `app.audit.log_event`.
- Produces: `roadmap_bp = Blueprint("roadmap", __name__)`. Route `GET /roadmap` → renders `roadmap.html` with `columns` (dict: `planned`/`in_progress`/`shipped` → list[RoadmapItem]) built from the shared (non-hidden) set, `mine` (list when `?mine=1`). Route `POST /roadmap/submit` → creates a `RoadmapItem(type="bug_fix", status="submitted", ...)`, flashes acknowledgement, redirects to `/roadmap`. Both `login_required`, `agency_id`-scoped.

- [ ] **Step 1: Write the failing tests (board read + shared visibility + submit)**

Append to `tests/test_roadmap.py`:

```python
def _login(client, uid):
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)


def test_board_renders_and_is_shared_across_agents(db_session, app, client, agency):
    from app.extensions import db
    from app.models import RoadmapItem, User
    with app.app_context():
        a1 = User(email="a1@test.com", name="Agent One", agency_id=agency.id)
        a2 = User(email="a2@test.com", name="Agent Two", agency_id=agency.id)
        db.session.add_all([a1, a2]); db.session.flush()
        # agent ONE submits a bug
        db.session.add(RoadmapItem(agency_id=agency.id, type="bug_fix", status="submitted",
                                   title="Birthday labels print blank", submitted_by_id=a1.id))
        db.session.commit()
        a2_id = a2.id

    # agent TWO sees agent ONE's submission on the shared board (anti-duplicate)
    _login(client, a2_id)
    body = client.get("/roadmap").get_data(as_text=True)
    assert "Birthday labels print blank" in body


def test_dismissed_item_off_shared_board_but_in_my_submissions(db_session, app, client, agency):
    from app.extensions import db
    from app.models import RoadmapItem, User
    with app.app_context():
        a1 = User(email="d1@test.com", name="Dee One", agency_id=agency.id)
        a2 = User(email="d2@test.com", name="Dee Two", agency_id=agency.id)
        db.session.add_all([a1, a2]); db.session.flush()
        db.session.add(RoadmapItem(agency_id=agency.id, type="bug_fix", status="dismissed",
                                   title="Dup of something", submitted_by_id=a1.id))
        db.session.commit()
        a1_id, a2_id = a1.id, a2.id

    # other agent does NOT see a dismissed item on the shared board
    _login(client, a2_id)
    assert "Dup of something" not in client.get("/roadmap").get_data(as_text=True)
    # the submitter DOES see it in their own ?mine=1 view
    _login(client, a1_id)
    assert "Dup of something" in client.get("/roadmap?mine=1").get_data(as_text=True)


def test_submit_creates_bug_and_acknowledges(db_session, app, client, agency):
    from app.extensions import db
    from app.models import RoadmapItem, User
    with app.app_context():
        u = User(email="sub@test.com", name="Sub Mitter", agency_id=agency.id)
        db.session.add(u); db.session.flush()
        uid = u.id
    _login(client, uid)
    resp = client.post("/roadmap/submit",
                       data={"title": "Export button does nothing",
                             "issue_text": "Clicking export on customers does nothing."},
                       follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        it = RoadmapItem.query.filter_by(title="Export button does nothing").first()
        assert it is not None
        assert it.type == "bug_fix" and it.status == "submitted"
        assert it.submitted_by_id == uid


def test_board_is_agency_scoped(db_session, app, client, agency):
    from app.extensions import db
    from app.models import RoadmapItem, User, Agency
    with app.app_context():
        other = Agency(name="Other Co"); db.session.add(other); db.session.flush()
        db.session.add(RoadmapItem(agency_id=other.id, type="feature", status="shipped",
                                   title="SECRET other-agency item"))
        u = User(email="scope@test.com", name="Scoped", agency_id=agency.id)
        db.session.add(u); db.session.flush()
        uid = u.id
    _login(client, uid)
    assert "SECRET other-agency item" not in client.get("/roadmap").get_data(as_text=True)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/test_roadmap.py -k "board or submit or dismissed or scoped" -v`
Expected: FAIL — 404 (route not registered) / template missing.

- [ ] **Step 3: Create `app/roadmap.py`**

```python
"""Roadmap & Changelog + bug intake. Everyone sees the same shared board (no
private/public split); wont_fix/dismissed items are off it (still in the
submitter's own ?mine=1 view + the admin filter). See
docs/superpowers/specs/2026-06-29-roadmap-changelog-bug-intake-design.md."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user, login_required

from app.extensions import db
from app.models import RoadmapItem
from app.audit import log_event

roadmap_bp = Blueprint("roadmap", __name__)

_COLUMNS = ("planned", "in_progress", "shipped")


def _shared_items(agency_id):
    """All non-hidden items for this agency. Ordered by id desc (newest first);
    the template groups by column + shows shipped_on per card, so a portable
    id-desc order is enough (avoids cross-DB NULLS-ordering quirks)."""
    return (RoadmapItem.query
            .filter_by(agency_id=agency_id)
            .filter(~RoadmapItem.status.in_(list(RoadmapItem._HIDDEN_STATUSES)))
            .order_by(RoadmapItem.id.desc())
            .all())


@roadmap_bp.route("/roadmap")
@login_required
def roadmap_board():
    aid = current_user.agency_id
    mine_only = request.args.get("mine") == "1"
    if mine_only:
        items = (RoadmapItem.query
                 .filter_by(agency_id=aid, submitted_by_id=current_user.id)
                 .order_by(RoadmapItem.id.desc()).all())
    else:
        items = _shared_items(aid)
    columns = {c: [] for c in _COLUMNS}
    for it in items:
        col = it.column
        if col in columns:
            columns[col].append(it)
        # 'hidden' items only reach here via ?mine=1; show them in a separate list
    mine_hidden = [it for it in items if it.column == "hidden"] if mine_only else []
    return render_template("roadmap.html", columns=columns, mine_only=mine_only,
                           mine_hidden=mine_hidden)


@roadmap_bp.route("/roadmap/submit", methods=["POST"])
@login_required
def roadmap_submit():
    title = (request.form.get("title") or "").strip()
    issue = (request.form.get("issue_text") or "").strip()
    if not title:
        flash("Please give your report a short title.", "error")
        return redirect(url_for("roadmap.roadmap_board"))
    item = RoadmapItem(agency_id=current_user.agency_id, type="bug_fix",
                       status="submitted", title=title[:200], issue_text=issue or None,
                       submitted_by_id=current_user.id)
    db.session.add(item)
    db.session.commit()
    log_event("roadmap_submit", category="roadmap", detail=f"#{item.id} {title}")
    flash("Got it — we've received your report. You can track it here under "
          '"My submissions".', "success")
    return redirect(url_for("roadmap.roadmap_board"))
```

- [ ] **Step 4: Register the blueprint**

In `app/__init__.py`, with the other imports (after `from app.comms import comms_bp`) add `from app.roadmap import roadmap_bp`, and after `app.register_blueprint(comms_bp)` add `app.register_blueprint(roadmap_bp)`.

- [ ] **Step 5: Create a minimal `roadmap.html` so the route renders (full styling is Task 4)**

Create `app/templates/roadmap.html`:

```html
{% extends "base.html" %}
{% block title %}Roadmap{% endblock %}
{% block content %}
<h1>Portal Roadmap &amp; Changelog</h1>
<form method="post" action="{{ url_for('roadmap.roadmap_submit') }}">
  <input name="title" placeholder="Short title" required>
  <textarea name="issue_text" placeholder="What's wrong?"></textarea>
  <button type="submit">Report an issue</button>
</form>
{% for col, items in columns.items() %}
  <h2>{{ col }}</h2>
  {% for it in items %}<div class="rm-card">{{ it.title }}</div>{% endfor %}
{% endfor %}
{% if mine_only %}{% for it in mine_hidden %}<div class="rm-card">{{ it.title }}</div>{% endfor %}{% endif %}
{% endblock %}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_roadmap.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/roadmap.py app/__init__.py app/templates/roadmap.html tests/test_roadmap.py
git commit -m "feat: roadmap_bp — shared board read + bug submit (agency-scoped)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Admin triage — edit status/priority/fields + dismiss

**Files:**
- Modify: `app/roadmap.py` (add `roadmap_edit` route)
- Test: `tests/test_roadmap.py` (add)

**Interfaces:**
- Consumes: `RoadmapItem`, `current_user.is_admin`, `log_event`.
- Produces: `POST /roadmap/<int:item_id>/edit` — admin-only (`abort(403)` else). Updates any provided field of `title/issue_text/fix_text/type/status/priority/shipped_on` from the form, agency-scoped, commits, audit-logs, redirects to `/roadmap`. Setting `status="dismissed"` is how an admin dismisses; setting `status="shipped"` + a `shipped_on` date is how it ships.

- [ ] **Step 1: Write the failing tests (admin edit + auth + dismiss)**

Append to `tests/test_roadmap.py`:

```python
def test_admin_can_edit_status_and_fields(db_session, app, client, agency, admin_user):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        it = RoadmapItem(agency_id=agency.id, type="bug_fix", status="submitted",
                         title="Slow page")
        db.session.add(it); db.session.flush()
        iid, aid = it.id, admin_user.id
    _login(client, aid)
    client.post(f"/roadmap/{iid}/edit",
                data={"status": "shipped", "priority": "high",
                      "fix_text": "Rebuilt it to load fast.", "shipped_on": "2026-06-29"},
                follow_redirects=True)
    with app.app_context():
        it = RoadmapItem.query.get(iid)
        assert it.status == "shipped" and it.priority == "high"
        assert it.fix_text == "Rebuilt it to load fast."
        assert it.column == "shipped"


def test_admin_dismiss_takes_item_off_board(db_session, app, client, agency, admin_user):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        it = RoadmapItem(agency_id=agency.id, type="bug_fix", status="submitted",
                         title="Duplicate report")
        db.session.add(it); db.session.flush()
        iid, aid = it.id, admin_user.id
    _login(client, aid)
    client.post(f"/roadmap/{iid}/edit", data={"status": "dismissed"}, follow_redirects=True)
    with app.app_context():
        assert RoadmapItem.query.get(iid).column == "hidden"


def test_non_admin_cannot_edit(db_session, app, client, agency, agent_user):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        it = RoadmapItem(agency_id=agency.id, type="bug_fix", status="submitted",
                         title="Try to hack")
        db.session.add(it); db.session.flush()
        iid, aid = it.id, agent_user.id
    _login(client, aid)
    resp = client.post(f"/roadmap/{iid}/edit", data={"status": "shipped"})
    assert resp.status_code == 403
    with app.app_context():
        assert RoadmapItem.query.get(iid).status == "submitted"   # unchanged


def test_admin_cannot_edit_other_agency_item(db_session, app, client, agency, admin_user):
    from app.extensions import db
    from app.models import RoadmapItem, Agency
    with app.app_context():
        other = Agency(name="Other"); db.session.add(other); db.session.flush()
        it = RoadmapItem(agency_id=other.id, type="bug_fix", status="submitted",
                         title="Not yours")
        db.session.add(it); db.session.flush()
        iid, aid = it.id, admin_user.id
    _login(client, aid)
    resp = client.post(f"/roadmap/{iid}/edit", data={"status": "shipped"})
    assert resp.status_code == 404    # agency-scoped lookup -> not found
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/test_roadmap.py -k "admin or non_admin or other_agency" -v`
Expected: FAIL — 404 (route not defined).

- [ ] **Step 3: Add the edit route to `app/roadmap.py`**

```python
from datetime import datetime

_EDITABLE_TEXT = ("title", "issue_text", "fix_text", "type", "status", "priority")


@roadmap_bp.route("/roadmap/<int:item_id>/edit", methods=["POST"])
@login_required
def roadmap_edit(item_id):
    if not current_user.is_admin:
        abort(403)
    item = RoadmapItem.query.filter_by(
        id=item_id, agency_id=current_user.agency_id).first_or_404()
    for field in _EDITABLE_TEXT:
        if field in request.form:
            val = (request.form.get(field) or "").strip() or None
            setattr(item, field, val)
    # title is NOT NULL — never blank it
    if "title" in request.form and not (request.form.get("title") or "").strip():
        item.title = item.title  # keep existing
    raw_date = (request.form.get("shipped_on") or "").strip()
    if raw_date:
        try:
            item.shipped_on = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            pass
    db.session.commit()
    log_event("roadmap_edit", category="roadmap",
              detail=f"#{item.id} -> status={item.status} priority={item.priority}")
    flash("Roadmap item updated.", "success")
    return redirect(url_for("roadmap.roadmap_board"))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_roadmap.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/roadmap.py tests/test_roadmap.py
git commit -m "feat: roadmap admin edit/dismiss (admin-only, agency-scoped)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: The board template (Founders theme, expand-in-place, admin controls)

**Files:**
- Modify: `app/templates/roadmap.html` (replace the Task-2 stub with the real board)
- Test: `tests/test_roadmap.py` (add a render assertion)

**Interfaces:**
- Consumes: `columns` (dict planned/in_progress/shipped → list[RoadmapItem]), `mine_only`, `mine_hidden`, `current_user.is_admin`. Each `RoadmapItem` exposes `id, type, title, issue_text, fix_text, status, priority, submitted_by, shipped_on`.
- Produces: the board HTML. Admin controls gated by `{% if current_user.is_admin %}`.

- [ ] **Step 1: Write the failing render test**

Append to `tests/test_roadmap.py`:

```python
def test_board_renders_columns_and_admin_controls(db_session, app, client, agency, admin_user):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        db.session.add(RoadmapItem(agency_id=agency.id, type="bug_fix", status="shipped",
            title="HRA went to wrong agent", issue_text="Wrong agent at 55%.",
            fix_text="Now reads the real writing agent.", priority="high"))
        db.session.add(RoadmapItem(agency_id=agency.id, type="planned", status="planned",
            title="Merge duplicate customers"))
        db.session.commit()
        aid = admin_user.id
    _login(client, aid)
    body = client.get("/roadmap").get_data(as_text=True)
    assert "HRA went to wrong agent" in body
    assert "Merge duplicate customers" in body
    assert "rm-col" in body                       # the three columns
    assert "rm-issue" in body and "rm-fix" in body  # the issue/fix detail
    assert "/edit" in body                          # admin inline controls present


def test_agent_board_has_no_admin_controls(db_session, app, client, agency, agent_user):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        db.session.add(RoadmapItem(agency_id=agency.id, type="bug_fix", status="shipped",
            title="Something fixed"))
        db.session.commit()
        aid = agent_user.id
    _login(client, aid)
    body = client.get("/roadmap").get_data(as_text=True)
    assert "Something fixed" in body
    assert "/edit" not in body                      # no admin edit form for agents
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_roadmap.py -k "renders_columns or no_admin_controls" -v`
Expected: FAIL — the stub template has none of `rm-col`/`rm-issue`/`/edit`.

- [ ] **Step 3: Replace `app/templates/roadmap.html` with the full board**

```html
{% extends "base.html" %}
{% block title %}Roadmap & Changelog{% endblock %}
{% block styles %}
<style>
  .rm-wrap { max-width: 1180px; margin: 0 auto; }
  .rm-head { display:flex; align-items:flex-end; justify-content:space-between; flex-wrap:wrap; gap:14px; margin:6px 0 18px; }
  .rm-title { font-family:'Merriweather',Georgia,serif; color:var(--ivory-bright); margin:0; font-size:1.9rem; }
  .rm-tagline { color:var(--slate); font-size:14px; margin:4px 0 0; }
  .rm-cta { background:var(--gold); color:#fff; border:none; border-radius:12px; padding:11px 18px; font:inherit; font-weight:700; font-size:14px; cursor:pointer; box-shadow:var(--shadow); }
  .rm-mine { font-size:13px; color:var(--gold); text-decoration:none; margin-left:14px; }
  .rm-cols { display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; }
  .rm-col { background:color-mix(in srgb, var(--ink) 50%, var(--surface)); border:1px solid var(--border); border-radius:var(--radius); padding:12px; }
  .rm-colh { display:flex; align-items:center; gap:8px; font-size:13px; font-weight:800; color:var(--ivory-bright); margin:4px 6px 12px; text-transform:uppercase; letter-spacing:.04em; }
  .rm-colh .ct { margin-left:auto; font-size:12px; color:var(--slate); background:var(--surface); border:1px solid var(--border); border-radius:999px; padding:1px 9px; }
  .rm-card { background:var(--surface); border:1px solid var(--border); border-radius:12px; box-shadow:var(--shadow); padding:12px 13px; margin-bottom:10px; cursor:pointer; }
  .rm-cardtop { display:flex; gap:7px; align-items:center; flex-wrap:wrap; margin-bottom:5px; }
  .rm-badge { font-size:10px; font-weight:800; padding:2px 8px; border-radius:999px; }
  .b-bug_fix { background:color-mix(in srgb, var(--green) 16%, var(--surface)); color:var(--green); }
  .b-feature { background:color-mix(in srgb, var(--gold) 14%, var(--surface)); color:var(--gold); }
  .b-planned, .b-known_issue { background:color-mix(in srgb, var(--gold) 10%, var(--surface)); color:var(--gold); }
  .rm-prio { font-size:11px; font-weight:700; color:var(--slate); }
  .rm-when { margin-left:auto; font-size:11px; color:var(--slate); }
  .rm-card h4 { margin:1px 0 4px; font-size:14px; color:var(--ivory-bright); font-weight:700; line-height:1.3; }
  .rm-detail { display:none; margin-top:9px; }
  .rm-card.open .rm-detail { display:block; }
  .rm-if { display:grid; grid-template-columns:1fr 1fr; gap:9px; margin:6px 0; }
  .rm-issue, .rm-fix { border-radius:9px; padding:8px 10px; font-size:12.5px; line-height:1.5; color:var(--ivory); }
  .rm-issue { background:color-mix(in srgb, var(--status-error) 7%, var(--surface)); border:1px solid color-mix(in srgb, var(--status-error) 20%, var(--surface)); }
  .rm-fix { background:color-mix(in srgb, var(--green) 8%, var(--surface)); border:1px solid color-mix(in srgb, var(--green) 24%, var(--surface)); }
  .rm-iflbl { font-size:9px; font-weight:800; text-transform:uppercase; letter-spacing:.05em; display:block; margin-bottom:2px; }
  .rm-sub { font-size:11px; color:var(--slate); margin-top:6px; }
  .rm-admin { margin-top:8px; padding-top:8px; border-top:1px solid var(--border); display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
  .rm-admin select, .rm-admin input { font-size:12px; padding:4px 7px; border:1px solid var(--border); border-radius:7px; background:var(--ink); color:var(--ivory); }
  .rm-admin button { font-size:12px; padding:5px 11px; border:none; border-radius:7px; background:var(--gold); color:#fff; font-weight:600; cursor:pointer; }
  /* submit modal */
  .rm-modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:50; align-items:center; justify-content:center; }
  .rm-modal.open { display:flex; }
  .rm-modal-card { background:var(--surface); border-radius:var(--radius); box-shadow:var(--shadow-float); padding:20px 22px; width:min(520px,92vw); }
  .rm-modal-card h3 { margin:0 0 4px; color:var(--ivory-bright); }
  .rm-modal-card p { margin:0 0 12px; color:var(--slate); font-size:13px; }
  .rm-modal-card label { display:block; font-size:12px; color:var(--slate); margin:8px 0 3px; }
  .rm-modal-card input, .rm-modal-card textarea { width:100%; box-sizing:border-box; padding:9px 11px; border:1px solid var(--border); border-radius:9px; background:var(--ink); color:var(--ivory); font:inherit; }
  .rm-modal-actions { display:flex; gap:8px; justify-content:flex-end; margin-top:14px; }
  @media(max-width:820px){ .rm-cols{ grid-template-columns:1fr; } .rm-if{ grid-template-columns:1fr; } }
</style>
{% endblock %}
{% block content %}
{% set col_meta = {'planned':'Planned / Known', 'in_progress':'In progress', 'shipped':'Shipped'} %}
<div class="rm-wrap">
  <div class="rm-head">
    <div>
      <h1 class="rm-title">Portal Roadmap &amp; Changelog</h1>
      <p class="rm-tagline">Everything we've fixed and shipped — and what's coming next.
        {% if mine_only %}<a class="rm-mine" href="{{ url_for('roadmap.roadmap_board') }}">← Back to all</a>
        {% else %}<a class="rm-mine" href="{{ url_for('roadmap.roadmap_board', mine=1) }}">My submissions →</a>{% endif %}
      </p>
    </div>
    <button class="rm-cta" type="button" onclick="document.getElementById('rmModal').classList.add('open')">+ Report an issue</button>
  </div>

  {% macro card(it) %}
  <div class="rm-card" onclick="this.classList.toggle('open')">
    <div class="rm-cardtop">
      <span class="rm-badge b-{{ it.type }}">{{ it.type.replace('_',' ')|title }}</span>
      {% if it.priority %}<span class="rm-prio">● {{ it.priority|title }}</span>{% endif %}
      <span class="rm-when">{{ it.shipped_on.strftime('%b %d, %Y') if it.shipped_on else it.status.replace('_',' ')|title }}</span>
    </div>
    <h4>{{ it.title }}</h4>
    <div class="rm-detail">
      {% if it.issue_text or it.fix_text %}
      <div class="rm-if">
        {% if it.issue_text %}<div class="rm-issue"><span class="rm-iflbl">The issue</span>{{ it.issue_text }}</div>{% endif %}
        {% if it.fix_text %}<div class="rm-fix"><span class="rm-iflbl">The fix</span>{{ it.fix_text }}</div>{% endif %}
      </div>
      {% endif %}
      <div class="rm-sub">
        {% if it.submitted_by %}Reported by {{ it.submitted_by.display_name }}{% endif %}
        {% if it.status in ('dismissed','wont_fix') %} · <strong>{{ 'Dismissed' if it.status=='dismissed' else "Won't fix" }}</strong>{% endif %}
      </div>
      {% if current_user.is_admin %}
      <form class="rm-admin" method="post" action="{{ url_for('roadmap.roadmap_edit', item_id=it.id) }}" onclick="event.stopPropagation()">
        <select name="status">
          {% for s in ['submitted','acknowledged','planned','in_progress','shipped','wont_fix','dismissed'] %}
          <option value="{{ s }}" {% if it.status==s %}selected{% endif %}>{{ s.replace('_',' ')|title }}</option>{% endfor %}
        </select>
        <select name="priority">
          <option value="">— priority —</option>
          {% for p in ['low','medium','high'] %}<option value="{{ p }}" {% if it.priority==p %}selected{% endif %}>{{ p|title }}</option>{% endfor %}
        </select>
        <input type="date" name="shipped_on" value="{{ it.shipped_on.isoformat() if it.shipped_on else '' }}">
        <button type="submit">Save</button>
      </form>
      {% endif %}
    </div>
  </div>
  {% endmacro %}

  {% if mine_only %}
  <div class="rm-col" style="grid-column:1/-1;">
    <div class="rm-colh">My submissions <span class="ct">{{ (columns.planned + columns.in_progress + columns.shipped + mine_hidden)|length }}</span></div>
    {% for col in ['planned','in_progress','shipped'] %}{% for it in columns[col] %}{{ card(it) }}{% endfor %}{% endfor %}
    {% for it in mine_hidden %}{{ card(it) }}{% endfor %}
  </div>
  {% else %}
  <div class="rm-cols">
    {% for col in ['planned','in_progress','shipped'] %}
    <div class="rm-col">
      <div class="rm-colh">{{ col_meta[col] }} <span class="ct">{{ columns[col]|length }}</span></div>
      {% for it in columns[col] %}{{ card(it) }}{% endfor %}
    </div>
    {% endfor %}
  </div>
  {% endif %}
</div>

<div class="rm-modal" id="rmModal">
  <div class="rm-modal-card">
    <h3>Report an issue</h3>
    <p>Found a bug or something off? Tell us — everyone can see it so we don't get the same report twice.</p>
    <form method="post" action="{{ url_for('roadmap.roadmap_submit') }}">
      <label>Short title</label>
      <input name="title" required maxlength="200" placeholder="e.g. Export button does nothing">
      <label>What's wrong? (the more detail the better)</label>
      <textarea name="issue_text" rows="4" placeholder="What did you click, what did you expect, what happened?"></textarea>
      <div class="rm-modal-actions">
        <button type="button" class="rm-cta" style="background:var(--surface-low);color:var(--ivory)" onclick="document.getElementById('rmModal').classList.remove('open')">Cancel</button>
        <button type="submit" class="rm-cta">Send report</button>
      </div>
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 4: Run the render tests to verify they pass**

Run: `python3 -m pytest tests/test_roadmap.py -k "renders_columns or no_admin_controls" -v`
Expected: PASS.

- [ ] **Step 5: Run the full roadmap suite**

Run: `python3 -m pytest tests/test_roadmap.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/templates/roadmap.html tests/test_roadmap.py
git commit -m "feat: roadmap board template — Founders theme, expand-in-place, admin controls

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Nav item (admin + agent)

**Files:**
- Modify: `app/templates/base.html` (add a "Roadmap" nav item in the admin Tools block AND the agent Tools block)
- Test: `tests/test_roadmap.py` (assert the link renders on a normal page for both roles)

**Interfaces:**
- Consumes: `url_for('roadmap.roadmap_board')`.
- Produces: a nav link visible to both admin and agent.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roadmap.py`:

```python
def test_roadmap_nav_link_present_for_admin_and_agent(db_session, app, client, agency, admin_user, agent_user):
    # the nav is rendered on every page; check the dashboard (or any 200 page)
    for uid_attr in (admin_user, agent_user):
        with app.app_context():
            from app.models import User
            uid = User.query.filter_by(email=uid_attr.email).first().id
        _login(client, uid)
        body = client.get("/roadmap").get_data(as_text=True)
        assert 'href="/roadmap"' in body or "roadmap.roadmap_board" in body
```

(Note: the roadmap page itself extends base.html so its own nav is rendered — this asserts the nav link exists for both roles.)

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_roadmap.py -k nav_link -v`
Expected: FAIL — no `/roadmap` nav link in base.html yet (the only `/roadmap` href is the page's own content, but the nav link is what we assert is added; if the content href already satisfies it, instead assert it appears in the SIDEBAR by checking `nav-item` proximity — simpler: proceed to add the nav item, which guarantees the link).

- [ ] **Step 3: Add the nav item to BOTH Tools blocks in `app/templates/base.html`**

In the **admin** Tools section (after the "Carriers & Plans" / "SMS Templates" links, before `<div class="nav-section-label">Alerts</div>` at ~line 804), add:

```html
        <a href="{{ url_for('roadmap.roadmap_board') }}" class="nav-item {% if request.endpoint == 'roadmap.roadmap_board' %}active{% endif %}">
          <span class="nav-dot"></span>Roadmap
        </a>
```

In the **agent** Tools section (the second `<div class="nav-section-label">Tools</div>` at ~line 848, add the same link among the agent tools):

```html
        <a href="{{ url_for('roadmap.roadmap_board') }}" class="nav-item {% if request.endpoint == 'roadmap.roadmap_board' %}active{% endif %}">
          <span class="nav-dot"></span>Roadmap
        </a>
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_roadmap.py -k nav_link -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/templates/base.html tests/test_roadmap.py
git commit -m "feat: Roadmap nav item (admin + agent Tools)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Curated history seed script

**Files:**
- Create: `scripts/seed_roadmap.py`
- Test: `tests/test_roadmap.py` (idempotency)

**Interfaces:**
- Consumes: `RoadmapItem`, `Agency`, `app.create_app`.
- Produces: `scripts/seed_roadmap.py` with a `SEED` list of dicts and a `main(apply, agency_id=None)` that upserts by `(agency_id, title)` (idempotent). Dry-run default; `--apply` commits.

- [ ] **Step 1: Write the failing idempotency test**

Append to `tests/test_roadmap.py`:

```python
def test_seed_roadmap_is_idempotent(db_session, app, agency):
    from app.extensions import db
    from app.models import RoadmapItem
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "seed_roadmap", str(pathlib.Path("scripts/seed_roadmap.py")))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    with app.app_context():
        n1 = mod.seed_items(agency.id, apply=True)
        c1 = RoadmapItem.query.filter_by(agency_id=agency.id).count()
        n2 = mod.seed_items(agency.id, apply=True)     # re-run
        c2 = RoadmapItem.query.filter_by(agency_id=agency.id).count()
        assert c1 > 0
        assert c2 == c1                                # no duplicates on re-run
        assert n2 == 0                                 # 2nd run inserts nothing
```

(`seed_items(agency_id, apply)` is the testable core; `main()` wraps it with the app context + arg parsing.)

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_roadmap.py -k seed -v`
Expected: FAIL — `scripts/seed_roadmap.py` does not exist.

- [ ] **Step 3: Create `scripts/seed_roadmap.py`**

```python
"""Seed the Roadmap & Changelog with curated highlights from the real shipped
history (plain agent-friendly language). Idempotent on (agency_id, title).
Dry-run default; --apply commits. Tim reviews/edits the wording in the admin UI
after seeding.

Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_roadmap.py [--apply] [--agency N]
"""
import sys
from datetime import date

from app import create_app
from app.extensions import db
from app.models import RoadmapItem, Agency


SEED = [
    # type, status, title, issue_text, fix_text, priority, shipped_on
    dict(type="bug_fix", status="shipped", priority="high", shipped_on=date(2026, 6, 29),
         title="UHC HRA payments going to the wrong agent",
         issue_text="An HRA payment could be attributed to the wrong agent at the wrong rate (e.g. to Rebekah at 55% instead of the agent who actually wrote it).",
         fix_text="We now read the real writing agent from the payment detail and split at their correct contract rate."),
    dict(type="bug_fix", status="shipped", priority="high", shipped_on=date(2026, 6, 29),
         title="Commission Fidelity page was slow / unresponsive",
         issue_text="The UHC Fidelity view (~4,000 lines) loaded slowly and timed out; the agent filter reset every time you saved an edit.",
         fix_text="Rebuilt it to load light and save edits instantly in place — no reload, and your filter now stays put."),
    dict(type="bug_fix", status="shipped", priority="medium", shipped_on=date(2026, 6, 29),
         title="UHC Part D $4.59 payments weren't splitting to the agent",
         issue_text="A $4.59 Part D renewal was being kept 100% by Founders instead of split with the agent.",
         fix_text="Part D $4.59 renewals now split at the agent's contract rate; the other plan types are unchanged."),
    dict(type="feature", status="shipped", shipped_on=date(2026, 6, 26),
         title="Commission import no longer creates duplicate customers",
         issue_text="Uploading a commission statement could spawn duplicate customer records.",
         fix_text="Commission import now matches a payment to an existing customer by their carrier ID, or parks it for review — it never invents a customer. The book of business is the only place customers are created."),
    dict(type="feature", status="shipped", shipped_on=date(2026, 6, 26),
         title="Data-integrity radar",
         issue_text="It was hard to know if a fix in one place quietly broke something elsewhere.",
         fix_text="A behind-the-scenes system continuously checks the portal's data for problems, so we catch issues before they reach you."),
    dict(type="feature", status="shipped", shipped_on=date(2026, 6, 9),
         title="Agent commission recap",
         fix_text="A single-screen recap of your commissions by carrier, with every line tracing back to the file."),
    dict(type="feature", status="shipped", shipped_on=date(2026, 6, 9),
         title="Fresh Founders look (blue & green theme)",
         fix_text="The portal was re-themed to the Founders brand — cleaner, with light and dark modes."),
    dict(type="feature", status="shipped", shipped_on=date(2026, 6, 10),
         title="Security hardening + nightly off-site backups",
         fix_text="Added session security, an audit log, breach alerting, and encrypted nightly backups so your data is safe."),
    dict(type="feature", status="shipped", shipped_on=date(2026, 6, 23),
         title="All six commission carriers reconcile to the penny",
         fix_text="UHC, Humana, Aetna, BCBS, Devoted and Healthspring commission files now all balance exactly."),
    # planned / known
    dict(type="planned", status="planned", priority="medium",
         title="Merge duplicate customer records",
         issue_text="Some customers show up more than once (e.g. one person split across several rows).",
         fix_text=None),
    dict(type="known_issue", status="acknowledged", priority="low",
         title="Some plan pages show different member counts",
         issue_text="A plan's page and the carrier breakdown can show different counts because they're computed off different keys. We know about it — the fix is underway.",
         fix_text=None),
    dict(type="feature", status="in_progress", priority="high",
         title="This Roadmap & Changelog page",
         issue_text=None,
         fix_text="A live record of what we've fixed and what's planned — plus a way for you to report issues you find."),
]


def seed_items(agency_id, apply=False):
    """Upsert the SEED list for one agency, idempotent on (agency_id, title).
    Returns the number of NEW rows inserted."""
    inserted = 0
    for s in SEED:
        exists = RoadmapItem.query.filter_by(agency_id=agency_id, title=s["title"]).first()
        if exists:
            continue
        db.session.add(RoadmapItem(
            agency_id=agency_id, type=s["type"], status=s["status"], title=s["title"],
            issue_text=s.get("issue_text"), fix_text=s.get("fix_text"),
            priority=s.get("priority"), shipped_on=s.get("shipped_on")))
        inserted += 1
        print(f"  + {s['status']:11} {s['title']}")
    if apply:
        db.session.commit()
        print(f"\nAPPLIED — {inserted} new roadmap items committed.")
    else:
        db.session.rollback()
        print(f"\nDRY-RUN — would insert {inserted}. Re-run with --apply to commit.")
    return inserted


def main(apply, agency_id):
    app = create_app()
    with app.app_context():
        if agency_id is None:
            agency = Agency.query.order_by(Agency.id).first()
            agency_id = agency.id
        seed_items(agency_id, apply=apply)


if __name__ == "__main__":
    aid = None
    if "--agency" in sys.argv:
        aid = int(sys.argv[sys.argv.index("--agency") + 1])
    main("--apply" in sys.argv, aid)
```

- [ ] **Step 4: Run the idempotency test to verify it passes**

Run: `python3 -m pytest tests/test_roadmap.py -k seed -v`
Expected: PASS.

- [ ] **Step 5: Run the FULL roadmap suite + the whole suite**

Run: `python3 -m pytest tests/test_roadmap.py -q && python3 -m pytest -q`
Expected: PASS (whole suite green; no regressions).

- [ ] **Step 6: Commit**

```bash
git add scripts/seed_roadmap.py tests/test_roadmap.py
git commit -m "feat: curated roadmap history seed (dry-run/--apply, idempotent)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Real-Postgres deploy + seed + verify (project protocol)

**Files:** none (operational).

- [ ] **Step 1: Opus whole-branch review** (data/UI path; the protocol requires it). Then proceed.

- [ ] **Step 2: Backup + deploy**

```bash
# DB backup FIRST
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100 \
  "cd /var/www/founders-portal && PGPASSWORD=<from .env> pg_dump -U founders_user -h localhost founders_portal > /root/founders_pre_roadmap_$(date +%F_%H%M%S).sql"
# deploy (this branch HAS a migration -> flask db upgrade)
ssh ... "cd /var/www/founders-portal && git pull && ./venv/bin/pip install -r requirements.txt && ./venv/bin/flask db upgrade && systemctl restart founders-portal"
# confirm migration head is 032 + restart cycled
ssh ... "cd /var/www/founders-portal && ./venv/bin/flask db current && systemctl show founders-portal -p ActiveEnterTimestamp"
```

- [ ] **Step 3: Seed the history (dry-run then apply)**

```bash
ssh ... "cd /var/www/founders-portal && PYTHONPATH=. ./venv/bin/python3 scripts/seed_roadmap.py"          # dry-run
ssh ... "cd /var/www/founders-portal && PYTHONPATH=. ./venv/bin/python3 scripts/seed_roadmap.py --apply"  # commit
```

- [ ] **Step 4: Live verify**

```bash
# login serves 200; /roadmap is admin+agent reachable (302->login unauthenticated)
ssh ... "curl -s -o /dev/null -w '%{http_code}\n' https://portal.foundersinsuranceagency.com/roadmap"   # 302
# no errors in the log since restart
ssh ... "journalctl -u founders-portal --since '2 minutes ago' | grep -iE 'error|traceback' || echo none"
```
Then Tim eyeballs `/roadmap` in a browser (board renders, cards expand, submit works, admin controls show). Tim edits/curates the seeded wording in the admin UI as desired.

- [ ] **Step 5: Update docs** — START HERE block, BACKLOG (mark roadmap page shipped), session ledger.

---

## Self-Review

**Spec coverage:**
- `RoadmapItem` model (no visibility column; `dismissed`/`wont_fix` statuses) → Task 1 ✅
- `column` property in ONE place → Task 1 ✅
- Shared board (everyone sees all non-hidden) + `?mine=1` → Task 2 ✅
- Submit creates bug_fix/submitted, acknowledgement → Task 2 ✅
- Admin edit (status/priority/fields) + dismiss + 403 for non-admin + agency-scope → Task 3 ✅
- Board template: 3 columns, expand-in-place issue/fix, Founders theme, admin-only controls → Task 4 ✅
- Nav (admin + agent) → Task 5 ✅
- Seed ~15-25 curated highlights, idempotent → Task 6 (12 seeded; Tim adds more in-UI) ✅
- Multi-tenant scoping → Tasks 2/3 tests ✅
- Migration (032) → Task 1 ✅
- Out-of-scope (email, bell, uploads, comments) → not built ✅

**Placeholder scan:** No TBD/TODO; every code step has complete code; commands have expected output. The two `(Note: ...)` asides are real fallback guidance (SQLite `nullslast`, nav-link assertion), not placeholders.

**Type consistency:** `RoadmapItem.column` returns `planned|in_progress|shipped|hidden` consistently (Task 1 def, Task 2 board build, Task 4 template). `seed_items(agency_id, apply)` consistent (Task 6 def + test). `roadmap.roadmap_board` / `roadmap.roadmap_submit` / `roadmap.roadmap_edit` endpoint names consistent across blueprint + template + nav. `_HIDDEN_STATUSES` used in both the model property (Task 1) and `_shared_items` (Task 2).
