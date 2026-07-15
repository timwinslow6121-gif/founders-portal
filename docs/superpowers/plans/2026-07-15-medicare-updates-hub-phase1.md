# Medicare Updates Hub — Phase 1 (Curated Intel) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the behind-login "Medicare Updates" hub where any agent posts typed, carrier-tagged carrier-intel updates (commission changes, network updates, training dates…), optionally linked to a Plan so the hub shows "affects N active members," with type/carrier filtering and admin pin/delete.

**Architecture:** A `CarrierUpdate` model + `updates_bp` blueprint + `updates.html` hub, mirroring the existing `RoadmapItem`/`roadmap.py` shared-board pattern (any agent posts; owner-editable; admin pins/deletes) and the `AgencyNotice` visibility/presentation pattern. A small plan-search endpoint feeds the post form's plan picker. The plan-link member count reuses the `Policy.plan_id` key the carrier pages use, read defensively.

**Tech Stack:** Flask 3, Flask-SQLAlchemy, Flask-Migrate (Alembic), Jinja2, vanilla JS/CSS. PostgreSQL (prod) / SQLite (tests). NO new dependencies in Phase 1 (feedparser is Phase 2 only).

**Spec:** `docs/superpowers/specs/2026-07-15-medicare-updates-hub-design.md`

## Global Constraints

- **Update types are exactly** `commission` / `network` / `carrier_notice` / `training` / `important_date` / `general` (allowlist). Presentation map (icon+accent) lives in ONE place in `app/updates.py`.
- **Any agent posts**; everyone sees the shared board. **Own posts editable by the poster; delete + pin are admin-only.** Non-admin non-owner → `abort(403)`.
- **Multi-tenant:** `carrier_updates.agency_id` NOT NULL + indexed; every query agency-scoped to `current_user.agency_id`.
- **Admin routes** `abort(403)` BEFORE any DB lookup.
- **Autoescape** title/body (agent-entered) — no `|safe`.
- **Plan-link count is the AGENCY active count** (`Policy.plan_id == plan_id, status='active', agency_id`) — same key/grain as the carrier list — read **defensively** (a failure shows the post without the count, never errors the page).
- **No-500 validation:** blank title/body, invalid update_type/carrier, malformed date → re-render with flash, HTTP 200, never a 500.
- **Migration head is currently 037** — this adds **038** (`down_revision="037"`).
- **Blueprint registration** uses the exact 3-line pattern in `app/__init__.py`.
- **Deploy is done by the assistant over SSH**; DB backup before `flask db upgrade`; `flask db` needs `FLASK_APP=wsgi.py`. Times EST/EDT.
- **Tests use the real harness:** fixtures `db_session, app, client, agency, admin_user, agent_user` (users are ROWS; use `.id`). Copy the `_login(client, uid)` helper from `tests/test_roadmap.py` (pops `g._login_user`, sets `session["_user_id"]`). All DB work inside `with app.app_context():`.

---

## File Structure

- **Modify** `app/models.py` — add `CarrierUpdate` model (+ `visible_for` classmethod, `UPDATE_TYPES`) near `AgencyNotice`.
- **Create** `migrations/versions/038_carrier_updates.py` — the table.
- **Create** `app/updates.py` — `UPDATE_PRESENTATION` map, `plan_affect(plan_id, agency_id)` count helper, and `updates_bp` (hub + post/edit/delete/pin + plan-search).
- **Modify** `app/__init__.py` — register `updates_bp`.
- **Create** `app/templates/updates.html` — the hub (filter bar + feed).
- **Create** `app/templates/update_form.html` — post/edit form with plan picker.
- **Modify** `app/templates/base.html` — nav "Medicare Updates" link (agent + admin).
- **Create** `scripts/seed_carrier_updates.py` — idempotent example seed.
- **Test** `tests/test_updates.py` — model + helper + routes + permissions.

---

### Task 1: `CarrierUpdate` model + migration 038

**Files:**
- Modify: `app/models.py` (near `AgencyNotice`)
- Create: `migrations/versions/038_carrier_updates.py`
- Test: `tests/test_updates.py`

**Interfaces:**
- Produces: `CarrierUpdate` model with columns `id, agency_id, update_type, carrier, title, body, plan_id, event_date, is_pinned, is_active, show_until, posted_by_id, created_at, updated_at`; `UPDATE_TYPES` tuple; classmethod `visible_for(agency_id, today, *, update_type=None, carrier=None) -> list` ordered `is_pinned` desc then `created_at` desc, filtered active + (show_until NULL or >= today) + optional type/carrier.

- [ ] **Step 1: Write the failing test**

Create `tests/test_updates.py`:

```python
from datetime import date, timedelta
from app.models import CarrierUpdate, Agency
from app.extensions import db


def _mk(agency_id, **kw):
    u = CarrierUpdate(agency_id=agency_id,
                      update_type=kw.get("update_type", "general"),
                      carrier=kw.get("carrier"),
                      title=kw.get("title", "T"),
                      body=kw.get("body", "B"),
                      plan_id=kw.get("plan_id"),
                      event_date=kw.get("event_date"),
                      is_pinned=kw.get("is_pinned", False),
                      is_active=kw.get("is_active", True),
                      show_until=kw.get("show_until"))
    db.session.add(u); db.session.commit()
    return u


def test_visible_for_filters_orders(db_session, app, agency):
    with app.app_context():
        today = date(2026, 7, 15)
        other = Agency(name="Other"); db.session.add(other); db.session.commit()
        _mk(agency.id, title="pinned", is_pinned=True)
        _mk(agency.id, title="normal")
        _mk(agency.id, title="inactive", is_active=False)
        _mk(agency.id, title="expired", show_until=today - timedelta(days=1))
        _mk(agency.id, title="humana_comm", update_type="commission", carrier="Humana")
        _mk(other.id, title="other_agency", is_pinned=True)

        rows = CarrierUpdate.visible_for(agency.id, today)
        titles = [r.title for r in rows]
        assert titles[0] == "pinned"                 # pinned first
        assert "inactive" not in titles and "expired" not in titles
        assert "other_agency" not in titles          # agency isolation
        # type + carrier filter
        f = CarrierUpdate.visible_for(agency.id, today, update_type="commission", carrier="Humana")
        assert [r.title for r in f] == ["humana_comm"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_updates.py::test_visible_for_filters_orders -v`
Expected: FAIL — `ImportError: cannot import name 'CarrierUpdate'`.

- [ ] **Step 3: Add the model**

In `app/models.py`, after the `AgencyNotice` class, add:

```python
class CarrierUpdate(db.Model):
    """A curated Medicare/carrier intelligence post on the behind-login Updates hub
    (see app/updates.py + docs/superpowers/specs/2026-07-15-medicare-updates-hub-design.md).
    Any agent posts; everyone sees the shared board; owner edits own; admin pins/deletes.
    Optional plan_id links a post to a Plan → the hub shows 'affects N active members'."""
    __tablename__ = "carrier_updates"

    id           = db.Column(db.Integer, primary_key=True)
    agency_id    = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    agency       = db.relationship("Agency", foreign_keys=[agency_id])

    update_type  = db.Column(db.String(24), nullable=False, default="general")
    carrier      = db.Column(db.String(64))                       # optional tag
    title        = db.Column(db.String(200), nullable=False)
    body         = db.Column(db.Text, nullable=False)
    plan_id      = db.Column(db.Integer, db.ForeignKey("plans.id", ondelete="SET NULL"))
    plan         = db.relationship("Plan", foreign_keys=[plan_id])
    event_date   = db.Column(db.Date)                            # for training/important-date
    is_pinned    = db.Column(db.Boolean, nullable=False, default=False)
    is_active    = db.Column(db.Boolean, nullable=False, default=True)
    show_until   = db.Column(db.Date)                            # optional auto-hide

    posted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    posted_by    = db.relationship("User", foreign_keys=[posted_by_id])
    created_at   = db.Column(db.DateTime, server_default=db.func.now())
    updated_at   = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    UPDATE_TYPES = ("commission", "network", "carrier_notice",
                    "training", "important_date", "general")

    @classmethod
    def visible_for(cls, agency_id, today, *, update_type=None, carrier=None):
        q = cls.query.filter(cls.agency_id == agency_id,
                             cls.is_active.is_(True),
                             db.or_(cls.show_until.is_(None), cls.show_until >= today))
        if update_type:
            q = q.filter(cls.update_type == update_type)
        if carrier:
            q = q.filter(cls.carrier == carrier)
        return q.order_by(cls.is_pinned.desc(), cls.created_at.desc()).all()

    def __repr__(self):
        return f"<CarrierUpdate #{self.id} {self.update_type} {self.title!r}>"
```

- [ ] **Step 4: Create the migration**

Create `migrations/versions/038_carrier_updates.py`:

```python
"""carrier updates (medicare updates hub, phase 1)

Revision ID: 038
Revises: 037
"""
from alembic import op
import sqlalchemy as sa

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "carrier_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("update_type", sa.String(length=24), nullable=False, server_default="general"),
        sa.Column("carrier", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("show_until", sa.Date(), nullable=True),
        sa.Column("posted_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_carrier_updates_agency_id", "carrier_updates", ["agency_id"])


def downgrade():
    op.drop_index("ix_carrier_updates_agency_id", table_name="carrier_updates")
    op.drop_table("carrier_updates")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_updates.py::test_visible_for_filters_orders -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/models.py migrations/versions/038_carrier_updates.py tests/test_updates.py
git commit -m "feat: CarrierUpdate model + migration 038 (medicare updates hub)"
```

---

### Task 2: presentation map + plan-affect helper

**Files:**
- Create: `app/updates.py`
- Test: `tests/test_updates.py` (append)

**Interfaces:**
- Consumes: `CarrierUpdate` (Task 1), `Policy` (models).
- Produces:
  - `UPDATE_PRESENTATION = {type: {"label":..., "icon":..., "accent":...}}` for all 6 types.
  - `plan_affect(plan_id, agency_id) -> dict | None` — `{"plan_id","plan_name","count"}` (agency active-member count via `Policy.plan_id`), or `None` if plan_id is falsy / plan missing / on any error (DEFENSIVE — never raises).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_updates.py`:

```python
from app.updates import UPDATE_PRESENTATION, plan_affect


def test_presentation_covers_all_types():
    from app.models import CarrierUpdate
    assert set(UPDATE_PRESENTATION) == set(CarrierUpdate.UPDATE_TYPES)
    for v in UPDATE_PRESENTATION.values():
        assert "label" in v and "icon" in v and "accent" in v


def test_plan_affect_counts_active_members(db_session, app, agency):
    from app.models import Plan, Policy
    from app.extensions import db
    with app.app_context():
        p = Plan(agency_id=agency.id, carrier="Humana", plan_name="Gold Plus HMO",
                 year=2026, plan_type="mapd", status="current",
                 needs_review=False, is_commissionable=True, has_unresolved_conflicts=False)
        db.session.add(p); db.session.commit()
        for i, st in enumerate(["active", "active", "termed"]):
            db.session.add(Policy(agency_id=agency.id, carrier="Humana",
                                  member_id=f"M{i}", plan_id=p.id, status=st))
        db.session.commit()
        res = plan_affect(p.id, agency.id)
        assert res["count"] == 2 and res["plan_name"] == "Gold Plus HMO"
        assert plan_affect(None, agency.id) is None
        assert plan_affect(999999, agency.id) is None   # missing plan → None, no raise
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_updates.py -k "presentation or plan_affect" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.updates'`.

- [ ] **Step 3: Create `app/updates.py` (map + helper; blueprint added Task 3)**

```python
"""Medicare Updates Hub — curated carrier-intel posts behind login.
Holds the update-type presentation map, the plan-affect count helper, and (added in the
routes task) the updates_bp blueprint.
See docs/superpowers/specs/2026-07-15-medicare-updates-hub-design.md."""
from app.extensions import db
from app.models import CarrierUpdate, Plan, Policy

# update_type -> presentation. ONE place; template + tests agree.
UPDATE_PRESENTATION = {
    "commission":     {"label": "Commission change", "icon": "dollar",    "accent": "commission"},
    "network":        {"label": "Network update",    "icon": "network",   "accent": "network"},
    "carrier_notice": {"label": "Carrier notice",    "icon": "carrier",   "accent": "carrier"},
    "training":       {"label": "Training & webinar","icon": "training",  "accent": "training"},
    "important_date": {"label": "Important date",     "icon": "calendar",  "accent": "date"},
    "general":        {"label": "General news",       "icon": "info",      "accent": "general"},
}


def plan_affect(plan_id, agency_id):
    """For a post's optional plan_id, return {plan_id, plan_name, count} where count is the
    AGENCY active-member count for that plan (same key/grain as the carrier pages), or None
    if plan_id is falsy / the plan is missing / on any error. Defensive: never raises."""
    if not plan_id:
        return None
    try:
        plan = Plan.query.filter_by(id=plan_id, agency_id=agency_id).first()
        if plan is None:
            return None
        count = (Policy.query
                 .filter(Policy.plan_id == plan_id,
                         Policy.status == "active",
                         Policy.agency_id == agency_id)
                 .count())
        return {"plan_id": plan.id, "plan_name": plan.plan_name, "count": count}
    except Exception:
        return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_updates.py -k "presentation or plan_affect" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/updates.py tests/test_updates.py
git commit -m "feat: update presentation map + defensive plan-affect count helper"
```

---

### Task 3: `updates_bp` blueprint (hub + post/edit/delete/pin + plan-search)

**Files:**
- Modify: `app/updates.py` (append blueprint)
- Modify: `app/__init__.py` (register)
- Create: `app/templates/updates.html`
- Create: `app/templates/update_form.html`
- Test: `tests/test_updates.py` (append)

**Interfaces:**
- Consumes: `CarrierUpdate` (T1), `UPDATE_PRESENTATION` + `plan_affect` (T2), `Plan` (models).
- Produces: `updates_bp` with routes `updates_hub` (`GET /updates`), `update_new` (`GET/POST /updates/new`), `update_edit` (`GET/POST /updates/<int:uid>/edit`), `update_delete` (`POST /updates/<int:uid>/delete`), `update_pin` (`POST /updates/<int:uid>/pin`), `plan_search` (`GET /updates/plan-search?q=`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_updates.py`. Copy the `_login` helper from `tests/test_roadmap.py` (top of file) into this test file if not already present.

```python
def _admin(client, admin_user):
    _login(client, admin_user.id)

def test_hub_renders_for_agent(client, app, agency, agent_user):
    _login(client, agent_user.id)
    with app.app_context():
        _mk(agency.id, title="Humana killed Gold Plus", update_type="commission", carrier="Humana")
    r = client.get("/updates")
    assert r.status_code == 200
    assert b"Humana killed Gold Plus" in r.data

def test_any_agent_can_post(client, app, agency, agent_user):
    _login(client, agent_user.id)
    r = client.post("/updates/new", data={
        "update_type": "network", "carrier": "Humana",
        "title": "Tryon Medical added for 2026", "body": "Big for Union county.",
        "event_date": "", "plan_id": "", "show_until": ""}, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from app.models import CarrierUpdate
        u = CarrierUpdate.query.filter_by(title="Tryon Medical added for 2026").first()
        assert u and u.update_type == "network" and u.posted_by_id == agent_user.id

def test_blank_title_rerenders_not_500(client, app, agency, agent_user):
    _login(client, agent_user.id)
    r = client.post("/updates/new", data={"update_type": "general", "title": "", "body": "x"})
    assert r.status_code == 200 and b"Title" in r.data

def test_bad_type_rejected(client, app, agency, agent_user):
    _login(client, agent_user.id)
    client.post("/updates/new", data={"update_type": "spam", "title": "X", "body": "y"})
    with app.app_context():
        from app.models import CarrierUpdate
        assert CarrierUpdate.query.filter_by(title="X").first() is None

def test_owner_can_edit_nonowner_cannot(client, app, agency, agent_user, admin_user):
    _login(client, agent_user.id)
    with app.app_context():
        u = _mk(agency.id, title="mine"); u.posted_by_id = agent_user.id
        from app.extensions import db; db.session.commit(); uid = u.id
    # owner edits ok
    assert client.post(f"/updates/{uid}/edit", data={
        "update_type": "general", "title": "mine v2", "body": "b"}).status_code in (200, 302)
    # a DIFFERENT non-admin agent cannot
    with app.app_context():
        from app.models import User; from app.extensions import db
        other = User(email="o@test.com", name="Other", is_admin=False, agency_id=agency.id)
        db.session.add(other); db.session.commit(); oid = other.id
    _login(client, oid)
    assert client.post(f"/updates/{uid}/edit", data={
        "update_type": "general", "title": "hijack", "body": "b"}).status_code == 403

def test_delete_and_pin_admin_only(client, app, agency, agent_user, admin_user):
    with app.app_context():
        u = _mk(agency.id, title="pinnable"); uid = u.id
    _login(client, agent_user.id)
    assert client.post(f"/updates/{uid}/delete").status_code == 403
    assert client.post(f"/updates/{uid}/pin").status_code == 403
    _login(client, admin_user.id)
    assert client.post(f"/updates/{uid}/pin").status_code in (200, 302)
    assert client.post(f"/updates/{uid}/delete").status_code in (200, 302)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_updates.py -k "hub or agent or blank or bad_type or owner or admin_only" -v`
Expected: FAIL — 404s (routes don't exist).

- [ ] **Step 3: Append the blueprint to `app/updates.py`**

Add imports at the top of `app/updates.py`:

```python
from datetime import date, datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, abort, jsonify)
from flask_login import current_user, login_required
```

Append to `app/updates.py`:

```python
updates_bp = Blueprint("updates", __name__)

_VALID_TYPES = set(CarrierUpdate.UPDATE_TYPES)
_CARRIERS = ["Humana", "UHC", "Aetna", "BCBS", "Devoted", "HealthSpring", "Wellabe", "GTL"]


def _parse_form(form):
    """(data, error). Cleans fields; error is a message or None."""
    title = (form.get("title") or "").strip()
    body = (form.get("body") or "").strip()
    utype = (form.get("update_type") or "").strip()
    carrier = (form.get("carrier") or "").strip() or None
    if not title:
        return None, "Title is required."
    if not body:
        return None, "Message body is required."
    if utype not in _VALID_TYPES:
        return None, "Please choose a valid update type."
    if carrier and carrier not in _CARRIERS:
        return None, "Unknown carrier."
    def _date(name):
        raw = (form.get(name) or "").strip()
        if not raw:
            return None, None
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date(), None
        except ValueError:
            return None, f"{name} must be a valid date."
    event_date, e1 = _date("event_date")
    if e1:
        return None, e1
    show_until, e2 = _date("show_until")
    if e2:
        return None, e2
    plan_id = None
    raw_pid = (form.get("plan_id") or "").strip()
    if raw_pid:
        try:
            plan_id = int(raw_pid)
        except ValueError:
            return None, "Invalid plan selection."
    return {"title": title, "body": body, "update_type": utype, "carrier": carrier,
            "event_date": event_date, "show_until": show_until, "plan_id": plan_id}, None


def _form_ctx(update=None, form=None):
    return dict(update=update, form=form or {}, types=CarrierUpdate.UPDATE_TYPES,
                presentation=UPDATE_PRESENTATION, carriers=_CARRIERS)


@updates_bp.route("/updates")
@login_required
def updates_hub():
    aid = current_user.agency_id
    utype = request.args.get("type") or None
    carrier = request.args.get("carrier") or None
    if utype not in _VALID_TYPES:
        utype = None
    updates = CarrierUpdate.visible_for(aid, date.today(), update_type=utype, carrier=carrier)
    affects = {u.id: plan_affect(u.plan_id, aid) for u in updates}
    return render_template("updates.html", updates=updates, affects=affects,
                           presentation=UPDATE_PRESENTATION, types=CarrierUpdate.UPDATE_TYPES,
                           carriers=_CARRIERS, sel_type=utype, sel_carrier=carrier)


@updates_bp.route("/updates/new", methods=["GET", "POST"])
@login_required
def update_new():
    if request.method == "POST":
        data, error = _parse_form(request.form)
        if error:
            flash(error, "error")
            return render_template("update_form.html", **_form_ctx(form=request.form))
        u = CarrierUpdate(agency_id=current_user.agency_id,
                          posted_by_id=current_user.id, **data)
        db.session.add(u); db.session.commit()
        flash("Update posted.", "success")
        return redirect(url_for("updates.updates_hub"))
    return render_template("update_form.html", **_form_ctx())


@updates_bp.route("/updates/<int:uid>/edit", methods=["GET", "POST"])
@login_required
def update_edit(uid):
    u = CarrierUpdate.query.filter_by(id=uid, agency_id=current_user.agency_id).first_or_404()
    if not (current_user.is_admin or u.posted_by_id == current_user.id):
        abort(403)
    if request.method == "POST":
        data, error = _parse_form(request.form)
        if error:
            flash(error, "error")
            return render_template("update_form.html", **_form_ctx(update=u, form=request.form))
        for k, v in data.items():
            setattr(u, k, v)
        db.session.commit()
        flash("Update saved.", "success")
        return redirect(url_for("updates.updates_hub"))
    return render_template("update_form.html", **_form_ctx(update=u))


@updates_bp.route("/updates/<int:uid>/delete", methods=["POST"])
@login_required
def update_delete(uid):
    if not current_user.is_admin:
        abort(403)
    u = CarrierUpdate.query.filter_by(id=uid, agency_id=current_user.agency_id).first_or_404()
    db.session.delete(u); db.session.commit()
    flash("Update deleted.", "success")
    return redirect(url_for("updates.updates_hub"))


@updates_bp.route("/updates/<int:uid>/pin", methods=["POST"])
@login_required
def update_pin(uid):
    if not current_user.is_admin:
        abort(403)
    u = CarrierUpdate.query.filter_by(id=uid, agency_id=current_user.agency_id).first_or_404()
    u.is_pinned = not u.is_pinned
    db.session.commit()
    return redirect(url_for("updates.updates_hub"))


@updates_bp.route("/updates/plan-search")
@login_required
def plan_search():
    """JSON plan picker for the post form: match carrier/plan_name/cms_plan_id."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    like = f"%{q}%"
    rows = (Plan.query
            .filter(Plan.agency_id == current_user.agency_id,
                    db.or_(Plan.plan_name.ilike(like), Plan.cms_plan_id.ilike(like),
                           Plan.carrier.ilike(like)))
            .order_by(Plan.plan_name).limit(15).all())
    return jsonify([{"id": p.id,
                     "label": f"{p.carrier} · {p.plan_name}" + (f" ({p.cms_plan_id})" if p.cms_plan_id else "")}
                    for p in rows])
```

- [ ] **Step 4: Register the blueprint**

In `app/__init__.py`, after `from app.notices import notices_bp` add `from app.updates import updates_bp`, and after `app.register_blueprint(notices_bp)` add:

```python
    app.register_blueprint(updates_bp)
```

- [ ] **Step 5: Create the templates**

Create `app/templates/updates.html` (extends base; Founders tokens; filter bar + feed). Include a `{% block styles %}` with `.upd-accent-commission {…}` etc. accent classes using existing tokens (`--gold` is the blue accent, `--green`, `--slate`; use `#C0392B` literal for alert-ish accents — base.html has no `--blue`). Card renders: type icon+label, carrier pill (if set), title, body, `posted_by` + `created_at`, the `affects[u.id]` line if present (`Affects {{ a.plan_name }} · {{ a.count }} active members →` linking to `/carriers/{{ a.plan_id }}`), `event_date` if set, and admin pin/delete + owner/admin edit buttons. Pinned cards show a 📌. Filter bar posts `?type=&carrier=` (submit-on-change), preserving `sel_type`/`sel_carrier`.

```html
{% extends "base.html" %}
{% block content %}
<div style="max-width:900px;margin:0 auto;">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px;">
    <h1 style="font-family:var(--serif);color:var(--ivory-bright);margin:0;">Medicare Updates</h1>
    <a href="{{ url_for('updates.update_new') }}" class="btn btn-primary">+ Post an update</a>
  </div>

  <form method="get" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;">
    <select name="type" onchange="this.form.submit()">
      <option value="">All types</option>
      {% for t in types %}<option value="{{ t }}" {{ 'selected' if sel_type==t else '' }}>{{ presentation[t].label }}</option>{% endfor %}
    </select>
    <select name="carrier" onchange="this.form.submit()">
      <option value="">All carriers</option>
      {% for c in carriers %}<option value="{{ c }}" {{ 'selected' if sel_carrier==c else '' }}>{{ c }}</option>{% endfor %}
    </select>
  </form>

  {% for u in updates %}
    {% set p = presentation.get(u.update_type, presentation['general']) %}
    {% set a = affects.get(u.id) %}
    <div class="card upd-card upd-accent-{{ p.accent }}" style="margin-bottom:12px;">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
        {% if u.is_pinned %}<span title="Pinned">📌</span>{% endif %}
        <span class="badge">{{ p.label }}</span>
        {% if u.carrier %}<span class="badge">{{ u.carrier }}</span>{% endif %}
        {% if u.event_date %}<span style="color:var(--slate);font-size:12.5px;">{{ u.event_date.strftime('%b %-d, %Y') }}</span>{% endif %}
      </div>
      <div style="font-weight:800;color:var(--ivory-bright);margin-top:6px;">{{ u.title }}</div>
      <div style="color:var(--ivory);font-size:14px;margin-top:4px;white-space:pre-wrap;">{{ u.body }}</div>
      {% if a %}
        <a href="{{ url_for('carriers.plan_detail', plan_id=a.plan_id) }}"
           style="display:inline-block;margin-top:8px;font-weight:700;color:var(--gold);font-size:13px;">
          Affects {{ a.plan_name }} · {{ a.count }} active member{{ '' if a.count == 1 else 's' }} →</a>
      {% endif %}
      <div style="color:var(--slate);font-size:12px;margin-top:8px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
        <span>{{ u.posted_by.name if u.posted_by else 'Someone' }} · {{ u.created_at.strftime('%b %-d') if u.created_at else '' }}</span>
        {% if current_user.is_admin or (u.posted_by_id == current_user.id) %}
          <a href="{{ url_for('updates.update_edit', uid=u.id) }}">Edit</a>{% endif %}
        {% if current_user.is_admin %}
          <form method="post" action="{{ url_for('updates.update_pin', uid=u.id) }}" style="display:inline;margin:0;">
            <button class="linklike" type="submit">{{ 'Unpin' if u.is_pinned else 'Pin' }}</button></form>
          <form method="post" action="{{ url_for('updates.update_delete', uid=u.id) }}" onsubmit="return confirm('Delete this update?');" style="display:inline;margin:0;">
            <button class="linklike" type="submit">Delete</button></form>
        {% endif %}
      </div>
    </div>
  {% else %}
    <p style="color:var(--slate);">No updates yet. Be the first to post carrier news the team should know.</p>
  {% endfor %}
</div>
{% block styles %}
<style>
  .upd-card{border-left:4px solid var(--slate);}
  .upd-accent-commission{border-left-color:var(--green);}
  .upd-accent-network{border-left-color:var(--gold);}
  .upd-accent-carrier{border-left-color:#7C5CBF;}
  .upd-accent-training{border-left-color:#2AA9A0;}
  .upd-accent-date{border-left-color:#C0392B;}
  .upd-accent-general{border-left-color:var(--slate);}
  .linklike{background:none;border:0;color:var(--gold);cursor:pointer;font:inherit;padding:0;}
</style>
{% endblock %}
{% endblock %}
```

Create `app/templates/update_form.html` — the post/edit form. Type select, carrier select (with a blank "— none —"), title, body, optional `event_date`, optional `show_until`, and a **plan picker**: a text input that queries `/updates/plan-search?q=` on keyup and lets the user pick a result, storing the chosen id in a hidden `plan_id` input (show the current plan when editing). Flash messages rendered at top. Use the same field/label style as `admin_notice_form.html`.

```html
{% extends "base.html" %}
{% block content %}
<div style="max-width:640px;margin:0 auto;">
  <h1 style="font-family:var(--serif);color:var(--ivory-bright);">{{ "Edit update" if update else "Post an update" }}</h1>
  {% with msgs = get_flashed_messages(with_categories=true) %}
    {% for cat, m in msgs %}<div class="badge" style="display:block;margin:8px 0;">{{ m }}</div>{% endfor %}
  {% endwith %}
  {% macro val(f, d='') %}{{ (form.get(f) if form else None) or (update[f] if update else None) or d }}{% endmacro %}
  <form method="post" class="card" style="display:flex;flex-direction:column;gap:14px;">
    <label>Type
      <select name="update_type">
        {% set cur = (form.get('update_type') if form else None) or (update.update_type if update else 'general') %}
        {% for t in types %}<option value="{{ t }}" {{ 'selected' if t==cur else '' }}>{{ presentation[t].label }}</option>{% endfor %}
      </select></label>
    <label>Carrier (optional)
      <select name="carrier">
        {% set cc = (form.get('carrier') if form else None) or (update.carrier if update else '') %}
        <option value="">— none —</option>
        {% for c in carriers %}<option value="{{ c }}" {{ 'selected' if c==cc else '' }}>{{ c }}</option>{% endfor %}
      </select></label>
    <label>Title <input type="text" name="title" maxlength="200" value="{{ val('title') }}"></label>
    <label>Message <textarea name="body" rows="4">{{ val('body') }}</textarea></label>
    <label>Affects a specific plan? (optional — search)
      <input type="text" id="planSearch" autocomplete="off"
             placeholder="type a plan name or CMS id…"
             value="{{ update.plan.plan_name if update and update.plan else '' }}">
      <input type="hidden" name="plan_id" id="planId" value="{{ update.plan_id if update and update.plan_id else '' }}">
      <div id="planResults" style="border:1px solid var(--border);border-radius:8px;display:none;"></div>
    </label>
    <label>Event date (optional — training/webinar/important date)
      <input type="date" name="event_date" value="{{ update.event_date.isoformat() if update and update.event_date else (form.get('event_date') if form else '') }}"></label>
    <label>Show until (optional — auto-hides after)
      <input type="date" name="show_until" value="{{ update.show_until.isoformat() if update and update.show_until else (form.get('show_until') if form else '') }}"></label>
    <div style="display:flex;gap:10px;">
      <button class="btn btn-primary" type="submit">Save</button>
      <a href="{{ url_for('updates.updates_hub') }}" class="btn btn-secondary">Cancel</a>
    </div>
  </form>
</div>
<script>
  const ps=document.getElementById('planSearch'), pid=document.getElementById('planId'), pr=document.getElementById('planResults');
  let t; ps.addEventListener('input', ()=>{ clearTimeout(t); pid.value=''; t=setTimeout(async()=>{
    const q=ps.value.trim(); if(q.length<2){pr.style.display='none';return;}
    const res=await fetch('{{ url_for("updates.plan_search") }}?q='+encodeURIComponent(q));
    const rows=await res.json(); pr.innerHTML=''; pr.style.display=rows.length?'block':'none';
    rows.forEach(r=>{ const d=document.createElement('div'); d.textContent=r.label;
      d.style.cssText='padding:7px 10px;cursor:pointer;'; d.onclick=()=>{ps.value=r.label;pid.value=r.id;pr.style.display='none';};
      pr.appendChild(d); }); }, 200); });
</script>
{% endblock %}
```

- [ ] **Step 6: Run to verify it passes**

Run: `python3 -m pytest tests/test_updates.py -v`
Expected: PASS (all model + helper + route/permission tests).

- [ ] **Step 7: Commit**

```bash
git add app/updates.py app/__init__.py app/templates/updates.html app/templates/update_form.html tests/test_updates.py
git commit -m "feat: updates_bp hub + post/edit/delete/pin + plan picker"
```

---

### Task 4: nav link + seed + full suite

**Files:**
- Modify: `app/templates/base.html` (nav, near the "Roadmap"/"Notices" links)
- Create: `scripts/seed_carrier_updates.py`
- Test: run the full suite

**Interfaces:**
- Consumes: `CarrierUpdate` (T1), `updates_bp` route names (T3).

- [ ] **Step 1: Add the nav link (agent + admin)**

In `app/templates/base.html`, add a "Medicare Updates" nav-item in BOTH the admin nav section (near the "Notices"/"Roadmap" links) AND the agent nav section (the agent block has its own "Tools"/"Alerts" groups — place it near "Carriers & Plans" or "SMS Templates"). Match the surrounding `.nav-item` markup:

```html
        <a href="{{ url_for('updates.updates_hub') }}" class="nav-item {% if request.endpoint and request.endpoint.startswith('updates.') %}active{% endif %}">
          <span class="nav-dot"></span>Medicare Updates
        </a>
```

(Search base.html for the existing admin "Notices" link and the agent "Carriers & Plans" link to place both copies correctly.)

- [ ] **Step 2: Create the seed script**

```python
"""Seed 1-2 example Medicare Updates (idempotent on agency_id+title).
Run: FLASK_APP=wsgi.py PYTHONPATH=. ./venv/bin/python3 scripts/seed_carrier_updates.py [--apply]"""
import sys
from app import create_app
from app.extensions import db
from app.models import CarrierUpdate, Plan

SEEDS = [
    {"update_type": "network", "carrier": "Humana",
     "title": "Humana added Tryon Medical Partners for 2026",
     "body": "Tryon Medical is in-network on Humana's 2026 MA plans — worth mentioning to "
             "clients who see Tryon providers.", "plan_hint": None},
    {"update_type": "commission", "carrier": "Humana",
     "title": "Example: a top plan going non-commissionable",
     "body": "Placeholder example — edit or delete. Shows how a commission-change post links "
             "to the affected plan so you see how many members it hits.",
     "plan_hint": "Gold Plus"},
]


def main(apply):
    app = create_app()
    with app.app_context():
        aid = app.config.get("DEFAULT_AGENCY_ID", 1)
        created = 0
        for s in SEEDS:
            if CarrierUpdate.query.filter_by(agency_id=aid, title=s["title"]).first():
                print(f"skip (exists): {s['title']}"); continue
            plan_id = None
            if s.get("plan_hint"):
                pl = Plan.query.filter(Plan.agency_id == aid,
                                       Plan.plan_name.ilike(f"%{s['plan_hint']}%")).first()
                plan_id = pl.id if pl else None
            print(f"{'CREATE' if apply else 'would create'}: [{s['update_type']}] {s['title']}"
                  f"{' (plan '+str(plan_id)+')' if plan_id else ''}")
            if apply:
                db.session.add(CarrierUpdate(
                    agency_id=aid, update_type=s["update_type"], carrier=s["carrier"],
                    title=s["title"], body=s["body"], plan_id=plan_id, is_active=True))
                created += 1
        if apply:
            db.session.commit()
        print(f"done. created={created} (apply={apply})")


if __name__ == "__main__":
    main("--apply" in sys.argv)
```

- [ ] **Step 3: Dry-run the seed locally**

Run: `PYTHONPATH=. python3 scripts/seed_carrier_updates.py`
Expected: prints "would create" for both, `created=0`. (If no local DB, verify it imports cleanly + report — matches the notices seed precedent.)

- [ ] **Step 4: Run the FULL suite**

Run: `python3 -m pytest -q`
Expected: PASS (baseline 629 + the new tests), no regressions.

- [ ] **Step 5: Commit**

```bash
git add app/templates/base.html scripts/seed_carrier_updates.py
git commit -m "feat: Medicare Updates nav link + idempotent example seed"
```

---

## Deployment (assistant runs after the whole-branch review)

1. Merge branch to main.
2. Back up prod DB: `PGPASSWORD=<from .env> pg_dump -U founders_user -h localhost founders_portal > /root/founders_pre_updates_$(date +%Y%m%d_%H%M%S).sql`.
3. `cd /var/www/founders-portal && git pull && FLASK_APP=wsgi.py ./venv/bin/flask db upgrade` (037→038) `&& systemctl restart founders-portal`.
4. Seed: `FLASK_APP=wsgi.py PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_carrier_updates.py --apply`.
5. Verify: `/updates` 200 for an agent, renders the feed + filter bar; posting works; a plan-linked post shows the live "affects N members" count matching the plan page; non-admin can't pin/delete (403); restart cycled.

## Self-Review

**Spec coverage:** model + migration (T1) ✓; presentation map + defensive plan-affect (T2) ✓; hub + typed/carrier filter + any-agent post + owner-edit/admin-delete/pin + plan picker (T3) ✓; nav + seed + suite (T4) ✓. Autoescape (no `|safe`) ✓. Agency-scoped + admin-before-lookup ✓. No-500 validation ✓. Six types exactly ✓. NO new dependency (feedparser is Phase 2) ✓. Phase 2 (RSS) correctly NOT in this plan ✓.

**Placeholder scan:** the templates say "follow admin_notice_form.html style" but include the FULL markup — no placeholder. Accent colors are concrete hex/tokens. Plan-picker JS is complete.

**Type consistency:** `visible_for(agency_id, today, *, update_type, carrier)` (T1) called with those kwargs in the hub (T3) ✓. `plan_affect(plan_id, agency_id) -> {plan_id,plan_name,count}|None` (T2) consumed as `affects.get(u.id)` in the template (T3) ✓. `UPDATE_PRESENTATION` keys == `UPDATE_TYPES` (asserted in T2 test) ✓. Route names `updates.updates_hub/update_new/update_edit/update_delete/update_pin/plan_search` consistent across blueprint, templates, nav, tests ✓. `carriers.plan_detail` is the existing plan-page route the affect-line links to (verified present in app/carriers.py) ✓.
