# Plan-Summary v2 — Network Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-first, agency-shared tribal-knowledge directory (`Provider` + `provider_carriers`) with a Providers management page (`/providers`, modeled on Pharmacies) and a plan-page Pro-view panel that shows providers in-network with the viewed plan's carrier (grouped by county), the "plays nice / bills PPO OON" flag for PPO plans, and a collapsed "not in-network here" objection section.

**Architecture:** New `Provider` model + `provider_carriers` join (migration 041), mirroring the existing `Pharmacy`/`pharmacy_agents` pattern. A new `providers_bp` blueprint (`app/providers.py`) with list/add/edit/delete, edit gated on `can_edit_shared_data`. A pure accessor `providers_for_plan(plan, agency_id)` in `app/carriers.py` returns the in-network (grouped by county) + not-in-network sets + `is_ppo`. The plan-detail Pro view renders a Network panel from it. `can_edit_shared_data` is exposed as a Jinja global so templates can gate edit controls.

**Tech Stack:** Flask 3.0, Flask-SQLAlchemy, Flask-Migrate (Alembic), Jinja2, vanilla JS, Founders theme CSS tokens. Tests: pytest (SQLite in-memory, matching `tests/test_plan_detail_route.py`).

## Global Constraints

- **Provider-first model** (not per-PBP). A `Provider` has a set of accepted carriers (`provider_carriers`) + a `bills_ppo_oon` flag (`yes`|`no`|`unknown`). The plan page filters by the plan's carrier. — spec Section 1.
- **Agency-shared + multi-tenant scoping:** every Provider/provider_carriers query filters `agency_id=current_user.agency_id`. — spec + CLAUDE.md.
- **Edit gate = `can_edit_shared_data(current_user)`** (senior_agent + admin edit; regular agents view — no edit controls). Delete = admin-only. Enforced SERVER-SIDE (a non-editor POST → `abort(403)`), not only hidden in the template. — spec Section 2.
- **Plan panel is Pro-only** — rendered inside `.pro-view`, never the Consumer path (agent tribal knowledge, not customer-facing). — spec Section 3.
- **`not_in_network` = ALL agency providers not accepting the plan's carrier**, grouped by county (incl. a county with only out-of-network providers — the Kannapolis sole-clinic case). NOT scoped to in-network counties. — spec Section 3 (self-review fix).
- **`is_ppo` = `(plan.plan_subtype or "").lower() == "ppo"`** — drives whether the plays-nice flag is shown. — spec Section 3.
- **No fabricated data / honest empty state:** panel shows an empty-state note ("No providers recorded for {carrier} yet") when none accept the carrier. — spec Section 3.
- **Migration = 041** (current head is 040, verified).
- **Founders theme tokens, light + dark;** text `var(--ivory)`/`var(--slate)` never `var(--ink)`; provider names/notes autoescaped (no `|safe`). — spec Section 3.
- The visual IS a deliverable: **headless-browser screenshot verification** (panel with in-network + PPO plays-nice + expanded not-in-network; empty state; management list + form) + full suite green. — spec Section 4.

---

### Task 1: `Provider` model + `provider_carriers` join + migration 041

**Files:**
- Modify: `app/models.py` (join table near `pharmacy_agents` ~line 295; model near `Pharmacy`)
- Create: `migrations/versions/041_providers.py`
- Test: `tests/test_providers.py` (new — model smoke)

**Interfaces:**
- Consumes: `Agency`, `User` models.
- Produces:
  - `provider_carriers` join table: `provider_id` (FK providers.id, PK), `carrier` (String(64), PK).
  - `Provider` model, table `providers`: `id`; `agency_id` (FK agencies.id, index, not null); `name` (String(256), not null); `provider_type` (String(64)); `city` (String(128)); `county` (String(128), index); `phone` (String(32)); `bills_ppo_oon` (String(16), default `"unknown"`); `notes` (Text); `created_by_id` (FK users.id); `created_at`; `updated_at`. Relationship `carriers` = `db.relationship` via `secondary=provider_carriers` — **NOTE:** provider_carriers.carrier is a plain string column, not an FK to a carriers table, so model the accepted-carrier set with a straightforward association: expose a helper `carrier_names` (list of carrier strings) rather than a secondary relationship to a model. Use a direct query/association object. Concretely: define `provider_carriers` as above and give `Provider` a `carriers = db.relationship("ProviderCarrier", ...)` OR keep it a Table and query it. To keep it simple and testable, model it as a Table and add a `Provider.carrier_names` **property** that queries the join. (See Step 3 for the exact code.)

- [ ] **Step 1: Write the failing test**

Create `tests/test_providers.py`:

```python
import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, User, Provider


@pytest.fixture
def ctx():
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False, WTF_CSRF_ENABLED=False, LOGIN_DISABLED=True)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(email="a@foundersinsuranceagency.com", name="A", is_admin=True,
                 agency_id=ag.id, role="admin")
        db.session.add(u); db.session.commit()
        yield app, ag.id, u.id
        db.session.remove(); db.drop_all()


def test_provider_persists_with_carriers(ctx):
    app, agency_id, uid = ctx
    with app.app_context():
        p = Provider(agency_id=agency_id, name="NE Digestive", provider_type="gastro",
                     city="Kannapolis", county="Cabarrus", bills_ppo_oon="no",
                     created_by_id=uid)
        p.set_carriers(["Humana", "BCBS"])
        db.session.add(p); db.session.commit()
        got = Provider.query.filter_by(name="NE Digestive").first()
        assert got.county == "Cabarrus"
        assert got.bills_ppo_oon == "no"
        assert set(got.carrier_names) == {"Humana", "BCBS"}


def test_provider_set_carriers_replaces(ctx):
    app, agency_id, uid = ctx
    with app.app_context():
        p = Provider(agency_id=agency_id, name="X", created_by_id=uid)
        p.set_carriers(["Humana"]); db.session.add(p); db.session.commit()
        p.set_carriers(["UHC", "Aetna"]); db.session.commit()
        assert set(p.carrier_names) == {"UHC", "Aetna"}   # replaced, not appended
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_providers.py -q`
Expected: FAIL — `ImportError: cannot import name 'Provider'`.

- [ ] **Step 3: Add the join table + model**

In `app/models.py`, near `pharmacy_agents` (~line 295) add:

```python
provider_carriers = db.Table(
    "provider_carriers",
    db.Column("provider_id", db.Integer, db.ForeignKey("providers.id", ondelete="CASCADE"), primary_key=True),
    db.Column("carrier", db.String(64), primary_key=True),
)
```

Add the `Provider` model (near `Pharmacy`):

```python
class Provider(db.Model):
    """Agency-shared tribal-knowledge directory of local medical providers: which
    carriers each is IN-network with, and whether it'll bill a PPO out-of-network
    ("plays nice"). Drives the plan-detail Network Snapshot panel. Manually
    maintained by agents (NOT parsed from carrier directories)."""
    __tablename__ = "providers"

    id            = db.Column(db.Integer, primary_key=True)
    agency_id     = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    name          = db.Column(db.String(256), nullable=False)
    provider_type = db.Column(db.String(64))                      # gastro / family / dentist / ...
    city          = db.Column(db.String(128))
    county        = db.Column(db.String(128), index=True)
    phone         = db.Column(db.String(32))
    bills_ppo_oon = db.Column(db.String(16), default="unknown")   # yes | no | unknown
    notes         = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at    = db.Column(db.DateTime, server_default=db.func.now())
    updated_at    = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    @property
    def carrier_names(self):
        """List of carrier strings this provider is in-network with."""
        rows = db.session.execute(
            provider_carriers.select().where(provider_carriers.c.provider_id == self.id)
        ).all()
        return [r.carrier for r in rows]

    def set_carriers(self, carriers):
        """Replace the provider's accepted-carrier set with `carriers` (list of str)."""
        db.session.execute(
            provider_carriers.delete().where(provider_carriers.c.provider_id == self.id)
        )
        for c in sorted(set(x for x in carriers if x)):
            db.session.execute(
                provider_carriers.insert().values(provider_id=self.id, carrier=c)
            )

    def __repr__(self):
        return f"<Provider {self.name} ({self.county})>"
```

Note: `set_carriers` needs `self.id`, so callers must `db.session.add(p); db.session.flush()` before `set_carriers` on a new provider (the test does add-then-commit; adjust: call flush before set_carriers). To make the test's `p.set_carriers([...]); db.session.add(p); db.session.commit()` ordering work, have `set_carriers` tolerate a not-yet-flushed provider by flushing itself:

```python
    def set_carriers(self, carriers):
        if self.id is None:
            db.session.add(self)
            db.session.flush()
        db.session.execute(
            provider_carriers.delete().where(provider_carriers.c.provider_id == self.id)
        )
        for c in sorted(set(x for x in carriers if x)):
            db.session.execute(
                provider_carriers.insert().values(provider_id=self.id, carrier=c)
            )
```

- [ ] **Step 4: Create migration 041**

Create `migrations/versions/041_providers.py`:

```python
"""providers + provider_carriers tables

Revision ID: 041
Revises: 040
"""
from alembic import op
import sqlalchemy as sa

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("county", sa.String(length=128), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("bills_ppo_oon", sa.String(length=16), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_providers_agency_id", "providers", ["agency_id"])
    op.create_index("ix_providers_county", "providers", ["county"])
    op.create_table(
        "provider_carriers",
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("carrier", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("provider_id", "carrier"),
    )


def downgrade():
    op.drop_table("provider_carriers")
    op.drop_index("ix_providers_county", table_name="providers")
    op.drop_index("ix_providers_agency_id", table_name="providers")
    op.drop_table("providers")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_providers.py -q`
Expected: PASS. Also confirm the migration is syntactically valid (stamp to 040 on a scratch SQLite DB, `flask db upgrade` reaches 041 — note the from-scratch chain hits a known pre-existing migration-005 SQLite issue unrelated to this task; validate 041 in isolation the way migration 039 was).

- [ ] **Step 6: Commit**

```bash
git add app/models.py migrations/versions/041_providers.py tests/test_providers.py
git commit -m "feat: Provider model + provider_carriers join + migration 041 (network snapshot)"
```

---

### Task 2: `providers_bp` management blueprint + templates

CRUD modeled on `pharmacies_bp`, edit gated on `can_edit_shared_data`, delete admin-only.

**Files:**
- Create: `app/providers.py` (`providers_bp`)
- Modify: `app/__init__.py` (register blueprint — 3-line pattern; + expose `can_edit_shared_data` as a Jinja global)
- Create: `app/templates/providers_list.html`, `app/templates/providers_form.html`
- Modify: `app/templates/base.html` (Providers nav link under Tools)
- Test: `tests/test_providers.py` (extend — routes + gate)

**Interfaces:**
- Consumes: `Provider`, `provider_carriers`, `can_edit_shared_data`, the `CARRIERS` list (`from app.carriers import CARRIERS`).
- Produces: routes `providers.provider_list` (GET `/providers`), `providers.provider_new` (GET/POST `/providers/new`), `providers.provider_edit` (GET/POST `/providers/<id>/edit`), `providers.provider_delete` (POST `/providers/<id>/delete`). A module-level `_can_edit()` guard → `abort(403)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_providers.py`:

```python
def _login(app, uid):
    from flask_login import login_user
    from app.models import User
    login_user(db.session.get(User, uid))


def test_provider_list_renders_grouped(ctx):
    app, agency_id, uid = ctx
    with app.app_context():
        p = Provider(agency_id=agency_id, name="NE Digestive", county="Cabarrus",
                     created_by_id=uid); p.set_carriers(["Humana"])
        db.session.add(p); db.session.commit()
    client = app.test_client()
    with app.test_request_context():
        _login(app, uid)
    # LOGIN_DISABLED=True → current_user is a dummy; call the view directly instead:
    from app import providers
    with app.test_request_context("/providers"):
        _login(app, uid)
        resp = providers.provider_list()
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert "NE Digestive" in html
    assert "Cabarrus" in html


def test_provider_new_persists_carriers_and_flag(ctx):
    app, agency_id, uid = ctx
    from app import providers
    with app.test_request_context("/providers/new", method="POST", data={
            "name": "Kannapolis Family Med", "provider_type": "family",
            "city": "Kannapolis", "county": "Cabarrus", "bills_ppo_oon": "yes",
            "carriers": ["Humana", "UHC"]}):
        _login(app, uid)
        providers.provider_new()
    with app.app_context():
        p = Provider.query.filter_by(name="Kannapolis Family Med").first()
        assert p is not None
        assert p.bills_ppo_oon == "yes"
        assert set(p.carrier_names) == {"Humana", "UHC"}


def test_provider_edit_blocked_for_non_editor(ctx):
    app, agency_id, uid = ctx
    with app.app_context():
        # a plain agent (not senior/admin) — can_edit_shared_data False
        from app.models import User
        agent = User(email="agent@foundersinsuranceagency.com", name="Ag",
                     is_admin=False, agency_id=agency_id, role="agent")
        db.session.add(agent); db.session.flush()
        p = Provider(agency_id=agency_id, name="X", created_by_id=uid)
        db.session.add(p); db.session.commit()
        agent_id, pid = agent.id, p.id
    from app import providers
    from werkzeug.exceptions import Forbidden
    with app.test_request_context(f"/providers/{pid}/edit", method="POST",
                                  data={"name": "Y"}):
        _login(app, agent_id)
        with pytest.raises(Forbidden):
            providers.provider_edit(pid)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_providers.py -q`
Expected: FAIL — `ModuleNotFoundError: app.providers` (or import error).

- [ ] **Step 3: Write the blueprint**

Create `app/providers.py`:

```python
"""
app/providers.py

Agency-shared provider directory (tribal knowledge). Senior agents + admins edit
(can_edit_shared_data); all agents view. Delete is admin-only. Drives the
plan-detail Network Snapshot panel.
"""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort)
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Provider, can_edit_shared_data
from app.carriers import CARRIERS

providers_bp = Blueprint("providers", __name__)

BILLS_PPO_OON = ["yes", "no", "unknown"]
# Suggested specialties for the datalist (free text — not enforced).
TYPE_SUGGESTIONS = ["Family medicine", "Gastroenterology", "Cardiology",
                    "Dentist", "Orthopedics", "Dermatology", "Oncology",
                    "OB/GYN", "Pulmonology", "Nephrology", "Urology"]


def _can_edit():
    if not can_edit_shared_data(current_user):
        abort(403)


@providers_bp.route("/providers")
@login_required
def provider_list():
    provs = (Provider.query
             .filter_by(agency_id=current_user.agency_id)
             .order_by(Provider.county, Provider.name).all())
    # group by county for the template
    by_county = {}
    for p in provs:
        by_county.setdefault(p.county or "—", []).append(p)
    return render_template("providers_list.html",
                           by_county=by_county,
                           can_edit=can_edit_shared_data(current_user))


@providers_bp.route("/providers/new", methods=["GET", "POST"])
@login_required
def provider_new():
    _can_edit()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Provider name is required.", "error")
            return redirect(url_for("providers.provider_new"))
        p = Provider(
            agency_id=current_user.agency_id, name=name,
            provider_type=request.form.get("provider_type", "").strip() or None,
            city=request.form.get("city", "").strip() or None,
            county=request.form.get("county", "").strip() or None,
            phone=request.form.get("phone", "").strip() or None,
            bills_ppo_oon=(request.form.get("bills_ppo_oon") or "unknown"),
            notes=request.form.get("notes", "").strip() or None,
            created_by_id=current_user.id,
        )
        db.session.add(p); db.session.flush()
        p.set_carriers(request.form.getlist("carriers"))
        db.session.commit()
        flash(f"{p.name} added.", "success")
        return redirect(url_for("providers.provider_list"))
    return render_template("providers_form.html", provider=None,
                           carriers=CARRIERS, bills_opts=BILLS_PPO_OON,
                           type_suggestions=TYPE_SUGGESTIONS, selected_carriers=set())


@providers_bp.route("/providers/<int:provider_id>/edit", methods=["GET", "POST"])
@login_required
def provider_edit(provider_id):
    _can_edit()
    p = Provider.query.filter_by(id=provider_id,
                                 agency_id=current_user.agency_id).first_or_404()
    if request.method == "POST":
        p.name          = request.form.get("name", "").strip() or p.name
        p.provider_type = request.form.get("provider_type", "").strip() or None
        p.city          = request.form.get("city", "").strip() or None
        p.county        = request.form.get("county", "").strip() or None
        p.phone         = request.form.get("phone", "").strip() or None
        p.bills_ppo_oon = request.form.get("bills_ppo_oon") or "unknown"
        p.notes         = request.form.get("notes", "").strip() or None
        p.set_carriers(request.form.getlist("carriers"))
        db.session.commit()
        flash(f"{p.name} updated.", "success")
        return redirect(url_for("providers.provider_list"))
    return render_template("providers_form.html", provider=p,
                           carriers=CARRIERS, bills_opts=BILLS_PPO_OON,
                           type_suggestions=TYPE_SUGGESTIONS,
                           selected_carriers=set(p.carrier_names))


@providers_bp.route("/providers/<int:provider_id>/delete", methods=["POST"])
@login_required
def provider_delete(provider_id):
    if not current_user.is_admin:
        abort(403)
    p = Provider.query.filter_by(id=provider_id,
                                 agency_id=current_user.agency_id).first_or_404()
    p.set_carriers([])          # clear join rows
    db.session.delete(p); db.session.commit()
    flash("Provider deleted.", "success")
    return redirect(url_for("providers.provider_list"))
```

- [ ] **Step 4: Register the blueprint + expose `can_edit_shared_data` to templates**

In `app/__init__.py`, with the other blueprint registrations (~line 24/37):

```python
    from app.providers import providers_bp
    app.register_blueprint(providers_bp)
```

And expose the gate helper as a Jinja global (near the context_processor, one-time), so templates can gate edit controls:

```python
    from app.models import can_edit_shared_data
    app.jinja_env.globals["can_edit_shared_data"] = can_edit_shared_data
```

- [ ] **Step 5: Write the templates**

Create `app/templates/providers_list.html` (extends base, Founders theme; grouped by county; carrier chips; plays-nice badge; edit/add controls only when `can_edit`):

```html
{% extends "base.html" %}
{% block title %}Providers{% endblock %}
{% block styles %}
.prov-county { font-size:11px; font-weight:700; letter-spacing:.16em; text-transform:uppercase;
  color:var(--slate); margin:20px 0 8px; }
.prov-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius);
  padding:14px 18px; margin-bottom:10px; max-width:820px; }
.prov-name { font-weight:600; color:var(--ivory); }
.prov-meta { font-size:12px; color:var(--slate); margin-top:2px; }
.prov-chip { display:inline-block; font-size:11px; font-weight:600; padding:2px 8px; border-radius:var(--radius-pill);
  background:color-mix(in srgb, var(--gold) 12%, transparent); color:var(--gold); margin:3px 4px 0 0; }
.oon-yes { color:var(--green); font-weight:700; } .oon-no { color:var(--status-error); font-weight:700; }
.oon-unknown { color:var(--slate); }
{% endblock %}
{% block content %}
<div class="page-header" style="display:flex;justify-content:space-between;align-items:center">
  <div><h1 class="page-title">Providers</h1>
  <p class="page-sub">Shared network directory — which carriers each provider takes, and whether they'll bill a PPO out-of-network.</p></div>
  {% if can_edit %}<a href="{{ url_for('providers.provider_new') }}" class="btn-primary">+ Add provider</a>{% endif %}
</div>
{% for county, provs in by_county.items() %}
<div class="prov-county">{{ county }}</div>
{% for p in provs %}
<div class="prov-card">
  <div style="display:flex;justify-content:space-between">
    <div>
      <span class="prov-name">{{ p.name }}</span>
      {% if p.provider_type %}<span class="prov-meta"> · {{ p.provider_type }}</span>{% endif %}
      <div class="prov-meta">{{ p.city or '' }}{% if p.phone %} · {{ p.phone }}{% endif %}
        · Bills PPO OON:
        <span class="oon-{{ p.bills_ppo_oon }}">{{ {'yes':'✓ yes','no':'✗ no','unknown':'? unknown'}[p.bills_ppo_oon] }}</span>
      </div>
      <div>{% for c in p.carrier_names %}<span class="prov-chip">{{ c }}</span>{% endfor %}</div>
      {% if p.notes %}<div class="prov-meta" style="margin-top:4px">{{ p.notes }}</div>{% endif %}
    </div>
    {% if can_edit %}<a href="{{ url_for('providers.provider_edit', provider_id=p.id) }}" class="btn-secondary" style="height:fit-content">Edit</a>{% endif %}
  </div>
</div>
{% endfor %}
{% else %}
<p style="color:var(--slate)">No providers recorded yet.{% if can_edit %} <a href="{{ url_for('providers.provider_new') }}" style="color:var(--gold)">Add the first one</a>.{% endif %}</p>
{% endfor %}
{% endblock %}
```

Create `app/templates/providers_form.html` (add/edit form; carrier checkboxes; bills_ppo_oon radio; type datalist; delete for admin on edit):

```html
{% extends "base.html" %}
{% block title %}{{ 'Edit' if provider else 'Add' }} provider{% endblock %}
{% block content %}
<h1 class="page-title">{{ 'Edit' if provider else 'Add' }} provider</h1>
<form method="post" style="max-width:640px">
  <label>Name<br><input class="form-input" name="name" required value="{{ provider.name if provider else '' }}"></label><br><br>
  <label>Type<br><input class="form-input" name="provider_type" list="type-suggest" value="{{ provider.provider_type if provider else '' }}"></label>
  <datalist id="type-suggest">{% for t in type_suggestions %}<option value="{{ t }}">{% endfor %}</datalist><br><br>
  <label>City<br><input class="form-input" name="city" value="{{ provider.city if provider else '' }}"></label>
  <label>County<br><input class="form-input" name="county" value="{{ provider.county if provider else '' }}"></label><br><br>
  <label>Phone<br><input class="form-input" name="phone" value="{{ provider.phone if provider else '' }}"></label><br><br>
  <fieldset><legend>In-network with</legend>
    {% for c in carriers %}
    <label style="display:inline-block;margin-right:12px">
      <input type="checkbox" name="carriers" value="{{ c }}" {{ 'checked' if c in selected_carriers }}> {{ c }}
    </label>
    {% endfor %}
  </fieldset><br>
  <fieldset><legend>Bills a PPO out-of-network ("plays nice")</legend>
    {% for opt in bills_opts %}
    <label style="margin-right:12px"><input type="radio" name="bills_ppo_oon" value="{{ opt }}"
      {{ 'checked' if (provider.bills_ppo_oon if provider else 'unknown') == opt }}> {{ opt }}</label>
    {% endfor %}
  </fieldset><br>
  <label>Notes<br><textarea class="form-input" name="notes" rows="3">{{ provider.notes if provider else '' }}</textarea></label><br><br>
  <button class="btn-primary" type="submit">Save</button>
  <a href="{{ url_for('providers.provider_list') }}" class="btn-secondary">Cancel</a>
</form>
{% if provider and current_user.is_admin %}
<form method="post" action="{{ url_for('providers.provider_delete', provider_id=provider.id) }}"
      onsubmit="return confirm('Delete this provider?')" style="margin-top:16px">
  <button class="btn-secondary" style="color:var(--status-error)" type="submit">Delete provider</button>
</form>
{% endif %}
{% endblock %}
```

Add the nav link in `app/templates/base.html` under Tools (near the Pharmacies link ~line 849), visible to all agents:

```html
<a href="/providers" class="nav-item {% if '/providers' in request.path %}active{% endif %}">Providers</a>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_providers.py -q`
Expected: PASS (model + route + gate tests).

- [ ] **Step 7: Commit**

```bash
git add app/providers.py app/__init__.py app/templates/providers_list.html app/templates/providers_form.html app/templates/base.html tests/test_providers.py
git commit -m "feat: providers management page (/providers) — CRUD, can_edit_shared_data gate, nav"
```

---

### Task 3: `providers_for_plan` accessor + wire into `plan_detail`

**Files:**
- Modify: `app/carriers.py` (`providers_for_plan` helper + `plan_detail` context)
- Test: `tests/test_plan_detail_route.py` (extend)

**Interfaces:**
- Consumes: `Provider`, `provider_carriers` (Task 1).
- Produces: `providers_for_plan(plan, agency_id) -> dict`:
  - `{"in_network": {county: [Provider,...], ...}, "not_in_network": {county: [Provider,...], ...}, "is_ppo": bool}`
  - `in_network` = providers whose `carrier_names` include `plan.carrier`, grouped by county (sorted).
  - `not_in_network` = ALL agency providers whose `carrier_names` do NOT include `plan.carrier`, grouped by county.
  - `is_ppo` = `(plan.plan_subtype or "").lower() == "ppo"`.
  Passed to `render_template("plan_detail.html", ..., providers=<dict>)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_plan_detail_route.py` (import `Provider`):

```python
from app.models import Provider


def test_providers_for_plan_splits_in_and_not_in_network(ctx):
    app, agency_id, uid, pid = ctx  # ctx plan carrier = "Humana"
    from app.carriers import providers_for_plan
    from app.models import Plan
    with app.app_context():
        innet = Provider(agency_id=agency_id, name="Kann Family", county="Cabarrus", created_by_id=uid)
        db.session.add(innet); db.session.flush(); innet.set_carriers(["Humana", "BCBS"])
        outnet = Provider(agency_id=agency_id, name="NE Digestive", county="Cabarrus", created_by_id=uid)
        db.session.add(outnet); db.session.flush(); outnet.set_carriers(["BCBS"])  # NOT Humana
        db.session.commit()
        plan = db.session.get(Plan, pid)
        res = providers_for_plan(plan, agency_id)
    innet_names = {p.name for lst in res["in_network"].values() for p in lst}
    outnet_names = {p.name for lst in res["not_in_network"].values() for p in lst}
    assert "Kann Family" in innet_names
    assert "NE Digestive" in outnet_names        # sole clinic out-of-network still surfaces
    assert "NE Digestive" not in innet_names


def test_providers_for_plan_is_ppo_flag(ctx):
    app, agency_id, uid, pid = ctx
    from app.carriers import providers_for_plan
    from app.models import Plan
    with app.app_context():
        plan = db.session.get(Plan, pid)
        plan.plan_subtype = "ppo"; db.session.commit()
        assert providers_for_plan(plan, agency_id)["is_ppo"] is True
        plan.plan_subtype = "hmo"; db.session.commit()
        assert providers_for_plan(plan, agency_id)["is_ppo"] is False


def test_providers_for_plan_agency_scoped(ctx):
    app, agency_id, uid, pid = ctx
    from app.carriers import providers_for_plan
    from app.models import Plan, Agency
    with app.app_context():
        other = Agency(name="Other"); db.session.add(other); db.session.flush()
        p = Provider(agency_id=other.id, name="Leak", county="X", created_by_id=uid)
        db.session.add(p); db.session.flush(); p.set_carriers(["Humana"])
        db.session.commit()
        plan = db.session.get(Plan, pid)
        res = providers_for_plan(plan, agency_id)
    allnames = {pr.name for grp in (res["in_network"], res["not_in_network"]) for lst in grp.values() for pr in lst}
    assert "Leak" not in allnames                # other agency's provider never returned
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_plan_detail_route.py -k providers_for_plan -q`
Expected: FAIL — `ImportError: cannot import name 'providers_for_plan'`.

- [ ] **Step 3: Implement the accessor + wire in**

In `app/carriers.py`, add a module-level helper (near `service_area_for`):

```python
def providers_for_plan(plan, agency_id):
    """Network-snapshot payload for a plan: agency providers split into those
    in-network with the plan's carrier vs. not, each grouped by county, plus an
    is_ppo flag (drives the plays-nice display). Agency-scoped."""
    from app.models import Provider
    provs = (Provider.query.filter_by(agency_id=agency_id)
             .order_by(Provider.county, Provider.name).all())
    in_net, not_net = {}, {}
    for p in provs:
        bucket = in_net if plan.carrier in p.carrier_names else not_net
        bucket.setdefault(p.county or "—", []).append(p)
    return {"in_network": in_net, "not_in_network": not_net,
            "is_ppo": (plan.plan_subtype or "").lower() == "ppo"}
```

In `plan_detail`, before the `return render_template(...)`, add:

```python
    providers = providers_for_plan(plan, current_user.agency_id)
```

and add `providers=providers,` to the `render_template("plan_detail.html", ...)` kwargs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_plan_detail_route.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/carriers.py tests/test_plan_detail_route.py
git commit -m "feat: providers_for_plan accessor (in/not-in-network by county + is_ppo) wired into plan_detail"
```

---

### Task 4: Network panel in the Pro view of `plan_detail.html`

**Files:**
- Modify: `app/templates/plan_detail.html`
- Test: `tests/test_plan_detail_route.py` (render assertions)

**Interfaces:**
- Consumes: `providers` (Task 3), `is_agent_context`.
- Produces: a `.network-panel` inside `.pro-view` — in-network providers grouped by county; PPO plays-nice flags; a collapsed "not in-network here" section; empty state.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_plan_detail_route.py`:

```python
def test_network_panel_renders_in_pro_view(ctx):
    app, agency_id, uid, pid = ctx
    from app.models import Provider, Plan
    with app.app_context():
        plan = db.session.get(Plan, pid); plan.plan_subtype = "ppo"
        innet = Provider(agency_id=agency_id, name="Kann Family", county="Cabarrus",
                         bills_ppo_oon="no", created_by_id=uid)
        db.session.add(innet); db.session.flush(); innet.set_carriers(["Humana"])
        db.session.commit()
    from app import carriers
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert "network-panel" in html
    assert "Kann Family" in html
    assert "won't bill OON" in html or "won&#39;t bill OON" in html  # PPO plays-nice flag (no==won't)


def test_network_panel_empty_state(ctx):
    app, agency_id, uid, pid = ctx  # no providers seeded
    from app import carriers
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert "No providers recorded for" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_plan_detail_route.py -k network_panel -q`
Expected: FAIL — `assert "network-panel" in html` fails.

- [ ] **Step 3: Add the panel CSS**

In `plan_detail.html`'s `{% block styles %}` append (gate under agent context like the quick-info CSS to keep the class name out of the Consumer style path is NOT needed here — the panel is inside `.pro-view` which is already hidden in Consumer; but the empty-state text must only render when appropriate — handled in markup):

```css
.network-panel { background:var(--surface); border:1px solid var(--border);
  border-radius:var(--radius); padding:20px 24px; margin-bottom:16px; max-width:820px; }
.network-panel h3 { font-size:11px; font-weight:700; letter-spacing:.16em;
  text-transform:uppercase; color:var(--slate); margin:0 0 12px; }
.net-county { font-size:11px; font-weight:700; letter-spacing:.1em; text-transform:uppercase;
  color:var(--gold); margin:12px 0 4px; }
.net-row { padding:5px 0; border-bottom:1px solid color-mix(in srgb, var(--border) 50%, transparent);
  font-size:13px; color:var(--ivory); }
.net-meta { font-size:12px; color:var(--slate); }
.oon-yes { color:var(--green); font-weight:700; } .oon-no { color:var(--status-error); font-weight:700; }
.oon-unknown { color:var(--slate); }
.net-toggle { border:none; background:transparent; cursor:pointer; color:var(--gold);
  font-size:12px; font-weight:600; padding:0; text-decoration:underline; margin-top:10px; }
.net-empty { color:var(--slate); font-size:13px; }
{% endblock %}  {# NOTE: append BEFORE the existing {% endblock %}, do not add a second one #}
```

- [ ] **Step 4: Add the panel markup in `.pro-view`**

Inside `.pro-view`, after the Agent Quick-Info block (`{% if is_agent_context and quick_info %}...{% endif %}`), add:

```html
  {% if is_agent_context %}
  <div class="network-panel">
    <h3>Network — local providers ({{ plan.carrier }})</h3>
    {% if providers.in_network %}
      {% for county, provs in providers.in_network.items() %}
      <div class="net-county">{{ county }}</div>
      {% for p in provs %}
      <div class="net-row">{{ p.name }}{% if p.provider_type %} <span class="net-meta">· {{ p.provider_type }}</span>{% endif %}
        {% if p.phone %} <span class="net-meta">· {{ p.phone }}</span>{% endif %}
        {% if providers.is_ppo %}
          · {% if p.bills_ppo_oon == 'yes' %}<span class="oon-yes">✓ bills OON</span>
          {% elif p.bills_ppo_oon == 'no' %}<span class="oon-no">✗ won't bill OON — customer pays upfront</span>
          {% else %}<span class="oon-unknown">? OON billing unknown</span>{% endif %}
        {% endif %}
      </div>
      {% endfor %}
      {% endfor %}
    {% else %}
      <div class="net-empty">No providers recorded for {{ plan.carrier }} yet.{% if can_edit_shared_data(current_user) %}
        <a href="{{ url_for('providers.provider_list') }}" style="color:var(--gold)">Add them on the Providers page</a>.{% endif %}</div>
    {% endif %}

    {% if providers.not_in_network %}
    <button type="button" class="net-toggle" data-net-toggle>Show providers NOT in network here</button>
    <div class="net-notin" hidden>
      {% for county, provs in providers.not_in_network.items() %}
      <div class="net-county">{{ county }}</div>
      {% for p in provs %}
      <div class="net-row"><span class="oon-no">✗</span> {{ p.name }}{% if p.provider_type %} <span class="net-meta">· {{ p.provider_type }}</span>{% endif %} <span class="net-meta">· not in network on {{ plan.carrier }}</span></div>
      {% endfor %}
      {% endfor %}
    </div>
    {% endif %}
  </div>
  {% endif %}
```

- [ ] **Step 5: Add the not-in-network toggle JS**

Before the closing `{% endblock %}` of the content block (alongside the other toggle scripts):

```html
<script>
(function () {
  var btn = document.querySelector('[data-net-toggle]');
  var box = document.querySelector('.net-notin');
  if (!btn || !box) return;
  btn.addEventListener('click', function () {
    var show = box.hidden; box.hidden = !show;
    btn.textContent = show ? 'Hide providers not in network here'
                           : 'Show providers NOT in network here';
  });
})();
</script>
```

- [ ] **Step 6: Run tests + full plan-detail suite**

Run: `python3 -m pytest tests/test_plan_detail_route.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/templates/plan_detail.html tests/test_plan_detail_route.py
git commit -m "feat: Network Snapshot panel in plan-detail Pro view (in/not-in-network + PPO plays-nice + empty state)"
```

---

### Task 5: Full-suite regression + headless screenshot verification

**Files:** no production changes (verification only).

**Interfaces:** Consumes everything from Tasks 1–4.

- [ ] **Step 1: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS (prior baseline + new tests). Record the count.

- [ ] **Step 2: Headless screenshot verification**

Serve the app against a seeded scratch DB (reuse the earlier preview-server pattern) with: a couple of Providers (one in-network with the plan's carrier + `bills_ppo_oon='no'`, one out-of-network — the NE-Digestive case) and a PPO plan + an HMO plan. With the playwright browser tools:
  - **Providers page** (`/providers`): list groups by county, carrier chips + plays-nice badge render; the add form shows carrier checkboxes + the bills_ppo_oon radio + type datalist. Screenshot light + dark.
  - **Plan page (PPO)** Pro view: Network panel shows the in-network provider with the ✗ "won't bill OON" flag; the "Show providers NOT in network here" toggle expands to reveal NE Digestive. Screenshot.
  - **Plan page (HMO)** Pro view: plays-nice flag omitted (OON not relevant).
  - **Plan with no providers for its carrier:** the empty-state note renders.
  - Confirm the panel is in the **Pro** view only (not Consumer).

Expected: all render correctly, both themes legible, toggle works, gate hides edit controls for a viewer.

- [ ] **Step 3: Commit verification note (optional, empty allowed)**

```bash
git commit --allow-empty -m "test: full suite + headless verification for Network Snapshot"
```

---

## Self-Review

**1. Spec coverage:**
- Section 1 (Provider + provider_carriers, provider-first, bills_ppo_oon) → Task 1. ✅
- Section 2 (Providers management page, can_edit_shared_data gate, delete admin-only, nav) → Task 2. ✅
- Section 3 (providers_for_plan accessor: in-network grouped by county + not-in-network = ALL non-accepting providers + is_ppo; Pro-only panel; PPO plays-nice; collapsed not-in-network; empty state) → Task 3 (accessor) + Task 4 (panel). ✅
- Section 4 (testing: model/migration, accessor scoping, gate, panel Pro-only + empty state + PPO flag, headless) → Tasks 1–5. ✅
- Files list (models+migration, providers.py, templates, carriers.py, plan_detail.html, base.html, __init__.py, tests) → all covered. ✅
- Global constraints (provider-first, agency-scoped, edit gate server-side, Pro-only, not-in-network = all non-accepting, is_ppo derivation, honest empty state, mig 041, theme, screenshots) → each mapped. ✅

**2. Placeholder scan:** No TBD/TODO/"handle edge cases". The Task 1 interface note about the association-vs-relationship choice is resolved concretely in Step 3 (a Table + `carrier_names` property + `set_carriers`), not left open. ✅

**3. Type consistency:** `providers_for_plan(plan, agency_id)` returns `{"in_network", "not_in_network", "is_ppo"}` consistently across Tasks 3→4. `Provider.carrier_names` (property) and `set_carriers(list)` used consistently across Tasks 1→2→3. `bills_ppo_oon` values `yes`/`no`/`unknown` consistent across model, form, panel. Migration `revision="041"`, `down_revision="040"`. The nav link and `can_edit_shared_data` Jinja global are introduced in Task 2 and used in Task 4's empty-state — consistent. ✅
