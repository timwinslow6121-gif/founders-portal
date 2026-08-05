# Provider Intake-Form v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine the Network Snapshot intake model: replace the single whole-provider `bills_ppo_oon` flag with an as-needed **per-specific-Plan** flag layer (`provider_plans`: status in/out + `bills_oon` yes/no/unknown) that surfaces on that plan's page; add an optional `Provider.group` affiliation field; and expand the type-suggestion list with category grouping.

**Architecture:** New `provider_plans` join (provider×plan flag) + `Provider.group` column + drop `Provider.bills_ppo_oon` (migration 042 — the `providers` table is EMPTY on prod, clean drop). `Provider` gets `plan_flags`/`set_plan_flag`/`remove_plan_flag` helpers mirroring the `carrier_names`/`set_carriers` pattern. `providers_for_plan` gains plan-layer precedence: a provider's status for a plan = its `provider_plans` row if present, else the carrier-level default; plays-nice (`bills_oon`) shows only from a plan-specific row on a PPO plan. The management form adds the `group` field, a grouped type datalist, and an as-needed plan-flags section (select a plan + status + bills_oon → adds a row; existing flags listed + removable).

**Tech Stack:** Flask 3.0, Flask-SQLAlchemy, Flask-Migrate (Alembic), Jinja2, vanilla JS, Founders theme tokens. Tests: pytest (SQLite in-memory).

## Global Constraints

- **Two-layer model:** carrier-level `provider_carriers` (broad in-network default, unchanged) + NEW per-plan `provider_plans` (as-needed override). Precedence: **plan-specific flag wins over carrier default**. — spec Section 1.
- **`provider_plans`** columns: `id`, `provider_id` (FK providers.id CASCADE), `plan_id` (FK plans.id CASCADE), `agency_id` (FK, scoping), `status` (`in_network`|`out_of_network`), `bills_oon` (`yes`|`no`|`unknown`); unique `(provider_id, plan_id)`. — spec Section 1.
- **`Provider.bills_ppo_oon` is DROPPED** (retired); the `providers` table is empty on prod → clean `op.drop_column`, no data preservation. Build confirms 0 rows before the drop as a safety check. — spec Section 1 (updated).
- **`Provider.group`** = optional `String(256)` affiliation field. — spec Section 2.
- **`bills_oon` shown only when `is_ppo`** (`plan_subtype=='ppo'`) AND from a plan-specific row. — spec Section 1.
- **Multi-tenant scoping:** every `Provider`/`provider_plans` query filters `agency_id=current_user.agency_id` (or the passed agency_id). — spec + CLAUDE.md.
- **Edit gate unchanged:** `can_edit_shared_data` server-side on new/edit + plan-flag add/remove; delete admin-only. — spec Section 3.
- **Migration = 042** (head is 041, verified).
- **Type suggestions grouped best-effort; full flat list is the requirement** if `<datalist>` grouping proves browser-flaky. — spec Section 2.
- Founders theme tokens, light+dark; text `var(--ivory)`/`var(--slate)` never `var(--ink)`; provider/group/notes autoescaped (no `|safe`). — spec Section 4.
- Headless screenshot verification + full suite green. — spec Section 4.

---

### Task 1: `provider_plans` table + `Provider.group` + drop `bills_ppo_oon` + model helpers + migration 042

**Files:**
- Modify: `app/models.py` (new `provider_plans` Table; `Provider.group` col; remove `bills_ppo_oon` col; add `plan_flags` property + `set_plan_flag`/`remove_plan_flag`; keep `carrier_names`/`set_carriers`)
- Create: `migrations/versions/042_provider_plans.py`
- Test: `tests/test_providers.py` (extend)

**Interfaces:**
- Consumes: existing `Provider`, `provider_carriers`, `Plan`.
- Produces:
  - `provider_plans` Table: `id` (PK), `provider_id` (FK providers.id CASCADE), `plan_id` (FK plans.id CASCADE), `agency_id` (FK agencies.id), `status` (String16), `bills_oon` (String16), unique `(provider_id, plan_id)`.
  - `Provider.group` (String256, nullable). `bills_ppo_oon` removed.
  - `Provider.plan_flags` → list of dicts `[{"plan_id", "status", "bills_oon"}, ...]`.
  - `Provider.set_plan_flag(plan_id, status, bills_oon, agency_id)` → upsert one row (replace if exists).
  - `Provider.remove_plan_flag(plan_id)` → delete the row for that plan.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_providers.py` (the fixture already builds an Agency + admin User; add a Plan):

```python
def test_provider_group_column(ctx):
    app, agency_id, uid = ctx
    with app.app_context():
        p = Provider(agency_id=agency_id, name="Dr. Tuttle", group="Novant",
                     created_by_id=uid)
        db.session.add(p); db.session.commit()
        assert Provider.query.filter_by(name="Dr. Tuttle").first().group == "Novant"


def test_provider_bills_ppo_oon_removed():
    # the whole-provider flag is retired; the column/attr should be gone
    from app.models import Provider
    assert not hasattr(Provider, "bills_ppo_oon") or "bills_ppo_oon" not in Provider.__table__.columns


def test_plan_flag_upsert_and_remove(ctx):
    app, agency_id, uid = ctx
    from app.models import Plan
    with app.app_context():
        pl = Plan(agency_id=agency_id, carrier="Devoted", cms_plan_id="H1234-001",
                  year=2026, plan_name="Devoted Choice (PPO)", plan_type="mapd",
                  plan_subtype="ppo", status="current")
        db.session.add(pl); db.session.flush()
        p = Provider(agency_id=agency_id, name="NE Digestive", county="Cabarrus",
                     created_by_id=uid)
        db.session.add(p); db.session.flush()
        p.set_plan_flag(pl.id, "out_of_network", "no", agency_id)
        db.session.commit()
        flags = p.plan_flags
        assert len(flags) == 1
        assert flags[0]["plan_id"] == pl.id
        assert flags[0]["status"] == "out_of_network"
        assert flags[0]["bills_oon"] == "no"
        # upsert replaces
        p.set_plan_flag(pl.id, "in_network", "yes", agency_id)
        db.session.commit()
        assert len(p.plan_flags) == 1 and p.plan_flags[0]["status"] == "in_network"
        # remove
        p.remove_plan_flag(pl.id); db.session.commit()
        assert p.plan_flags == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_providers.py -q`
Expected: FAIL — `group` unknown / `set_plan_flag` missing.

- [ ] **Step 3: Update the model**

In `app/models.py`, add the join table near `provider_carriers`:

```python
provider_plans = db.Table(
    "provider_plans",
    db.Column("id", db.Integer, primary_key=True),
    db.Column("provider_id", db.Integer, db.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
    db.Column("plan_id", db.Integer, db.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
    db.Column("agency_id", db.Integer, db.ForeignKey("agencies.id"), nullable=False),
    db.Column("status", db.String(16)),        # in_network | out_of_network
    db.Column("bills_oon", db.String(16)),      # yes | no | unknown
    db.UniqueConstraint("provider_id", "plan_id", name="uq_provider_plan"),
)
```

In the `Provider` class: **remove** the `bills_ppo_oon` column line; **add** `group = db.Column(db.String(256))` (after `phone`); and add the helpers:

```python
    group         = db.Column(db.String(256))          # affiliation / umbrella (Atrium/Novant)

    # (keep carrier_names / set_carriers unchanged)

    @property
    def plan_flags(self):
        """Per-plan flags: [{'plan_id','status','bills_oon'}, ...]."""
        rows = db.session.execute(
            provider_plans.select().where(provider_plans.c.provider_id == self.id)
        ).all()
        return [{"plan_id": r.plan_id, "status": r.status, "bills_oon": r.bills_oon}
                for r in rows]

    def plan_flag_for(self, plan_id):
        """The single flag dict for plan_id, or None."""
        for f in self.plan_flags:
            if f["plan_id"] == plan_id:
                return f
        return None

    def set_plan_flag(self, plan_id, status, bills_oon, agency_id):
        """Upsert (replace) the provider's flag for plan_id."""
        if self.id is None:
            db.session.add(self); db.session.flush()
        db.session.execute(
            provider_plans.delete().where(
                (provider_plans.c.provider_id == self.id) &
                (provider_plans.c.plan_id == plan_id))
        )
        db.session.execute(provider_plans.insert().values(
            provider_id=self.id, plan_id=plan_id, agency_id=agency_id,
            status=status, bills_oon=(bills_oon or "unknown")))

    def remove_plan_flag(self, plan_id):
        db.session.execute(
            provider_plans.delete().where(
                (provider_plans.c.provider_id == self.id) &
                (provider_plans.c.plan_id == plan_id))
        )
```

Also update the `Provider` docstring to describe the per-plan model.

- [ ] **Step 4: Create migration 042**

`migrations/versions/042_provider_plans.py`, `revision="042"`, `down_revision="041"`:

```python
"""provider_plans + Provider.group; drop bills_ppo_oon

Revision ID: 042
Revises: 041
"""
from alembic import op
import sqlalchemy as sa

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("providers", sa.Column("group", sa.String(length=256), nullable=True))
    op.create_table(
        "provider_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("bills_oon", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "plan_id", name="uq_provider_plan"),
    )
    op.create_index("ix_provider_plans_plan_id", "provider_plans", ["plan_id"])
    op.create_index("ix_provider_plans_provider_id", "provider_plans", ["provider_id"])
    op.drop_column("providers", "bills_ppo_oon")


def downgrade():
    op.add_column("providers", sa.Column("bills_ppo_oon", sa.String(length=16), nullable=True))
    op.drop_index("ix_provider_plans_provider_id", table_name="provider_plans")
    op.drop_index("ix_provider_plans_plan_id", table_name="provider_plans")
    op.drop_table("provider_plans")
    op.drop_column("providers", "group")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_providers.py -q`
Expected: PASS. Validate the migration in isolation (stamp 041 → upgrade → 042 on a scratch SQLite DB — known pre-existing mig-005 chain issue, isolate like prior migrations). ⚠ Note: `op.drop_column` on SQLite requires batch mode; if the isolated upgrade errors on the drop under SQLite, wrap it: `with op.batch_alter_table("providers") as b: b.drop_column("bills_ppo_oon")` (and the add_column likewise) — Postgres (prod) handles plain `op.drop_column` fine, but make the migration SQLite-safe with batch ops for both the add and drop so the isolated validation passes.

- [ ] **Step 6: Commit**

```bash
git add app/models.py migrations/versions/042_provider_plans.py tests/test_providers.py
git commit -m "feat: provider_plans (per-plan flags) + Provider.group + drop bills_ppo_oon (migration 042)"
```

---

### Task 2: providers blueprint — group field, grouped types, plan-flags add/remove

**Files:**
- Modify: `app/providers.py`
- Modify: `app/templates/providers_form.html`, `app/templates/providers_list.html`
- Test: `tests/test_providers.py` (extend)

**Interfaces:**
- Consumes: `Provider.group`, `set_plan_flag`/`remove_plan_flag`/`plan_flags` (Task 1); `Plan` (for the picker).
- Produces: `provider_new`/`provider_edit` persist `group` + plan flags; new routes `provider_add_plan_flag` (POST `/providers/<id>/plan-flag`) + `provider_remove_plan_flag` (POST `/providers/<id>/plan-flag/<plan_id>/delete`); a grouped `TYPE_SUGGESTIONS` structure.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_providers.py`:

```python
def test_provider_new_persists_group(ctx):
    app, agency_id, uid = ctx
    from app import providers
    with app.test_request_context("/providers/new", method="POST", data={
            "name": "Atrium Health", "provider_type": "Provider group",
            "group": "", "county": "Mecklenburg", "carriers": ["Devoted"]}):
        _login(app, uid)
        providers.provider_new()
    with app.app_context():
        p = Provider.query.filter_by(name="Atrium Health").first()
        assert p is not None and p.provider_type == "Provider group"


def test_add_and_remove_plan_flag_route(ctx):
    app, agency_id, uid = ctx
    from app import providers
    from app.models import Plan
    with app.app_context():
        pl = Plan(agency_id=agency_id, carrier="Devoted", cms_plan_id="H1234-001",
                  year=2026, plan_name="Devoted Choice (PPO)", plan_type="mapd",
                  plan_subtype="ppo", status="current")
        db.session.add(pl); db.session.flush()
        p = Provider(agency_id=agency_id, name="NE Digestive", county="Cabarrus",
                     created_by_id=uid)
        db.session.add(p); db.session.commit()
        pid, plid = p.id, pl.id
    with app.test_request_context(f"/providers/{pid}/plan-flag", method="POST",
            data={"plan_id": str(plid), "status": "out_of_network", "bills_oon": "no"}):
        _login(app, uid)
        providers.provider_add_plan_flag(pid)
    with app.app_context():
        assert db.session.get(Provider, pid).plan_flag_for(plid)["status"] == "out_of_network"
    with app.test_request_context(f"/providers/{pid}/plan-flag/{plid}/delete", method="POST"):
        _login(app, uid)
        providers.provider_remove_plan_flag(pid, plid)
    with app.app_context():
        assert db.session.get(Provider, pid).plan_flags == []


def test_plan_flag_add_blocked_for_non_editor(ctx):
    app, agency_id, uid = ctx
    from app import providers
    from app.models import User, Plan
    from werkzeug.exceptions import Forbidden
    with app.app_context():
        agent = User(email="ag2@foundersinsuranceagency.com", name="Ag2",
                     is_admin=False, agency_id=agency_id, role="agent")
        db.session.add(agent); db.session.flush()
        p = Provider(agency_id=agency_id, name="X", created_by_id=uid)
        db.session.add(p); db.session.commit()
        aid, pid = agent.id, p.id
    with app.test_request_context(f"/providers/{pid}/plan-flag", method="POST",
                                  data={"plan_id": "1", "status": "in_network"}):
        _login(app, aid)
        with pytest.raises(Forbidden):
            providers.provider_add_plan_flag(pid)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_providers.py -q`
Expected: FAIL — `provider_add_plan_flag` missing / group not handled.

- [ ] **Step 3: Update the blueprint**

In `app/providers.py`:
- Replace `BILLS_PPO_OON`/flat `TYPE_SUGGESTIONS` with grouped types + the per-plan bills options:

```python
PLAN_STATUS = ["in_network", "out_of_network"]
BILLS_OON = ["yes", "no", "unknown"]

# Category-grouped type suggestions (browse aid; free text still allowed).
TYPE_GROUPS = [
    ("Specialties", ["Family medicine", "Cardiology", "Gastroenterology", "Dermatology",
                     "OB/GYN", "Urology", "Nephrology", "Pulmonology", "ENT", "Podiatry",
                     "Oncology", "Orthopedics"]),
    ("Facilities & centers", ["Hospital", "Surgical center", "Urgent care", "Rehab center",
                              "Skilled nursing facility", "Imaging / radiology", "Lab"]),
    ("Groups & systems", ["Provider group"]),
    ("Ancillary & equipment", ["DME", "Home health", "Hospice", "Physical therapy",
                               "Behavioral / mental health", "Optometry / ophthalmology",
                               "Audiology", "Chiropractic", "Dentist"]),
]
```

- `provider_new`/`provider_edit`: drop the `bills_ppo_oon=` handling; add `group=request.form.get("group", "").strip() or None`. Pass `type_groups=TYPE_GROUPS` to the template (and, for edit, the agency's plans + existing `plan_flags` + a plan-id→plan lookup for labels). Provide the agency plans list for the picker:

```python
    from app.models import Plan
    plans = (Plan.query.filter_by(agency_id=current_user.agency_id, status="current")
             .order_by(Plan.carrier, Plan.plan_name).all())
```

- Add the two plan-flag routes (gated + agency-scoped):

```python
@providers_bp.route("/providers/<int:provider_id>/plan-flag", methods=["POST"])
@login_required
def provider_add_plan_flag(provider_id):
    _can_edit()
    p = Provider.query.filter_by(id=provider_id,
                                 agency_id=current_user.agency_id).first_or_404()
    plan_id = int(request.form.get("plan_id") or 0)
    from app.models import Plan
    plan = Plan.query.filter_by(id=plan_id, agency_id=current_user.agency_id).first()
    if not plan:
        flash("Pick a plan.", "error")
        return redirect(url_for("providers.provider_edit", provider_id=provider_id))
    p.set_plan_flag(plan_id, request.form.get("status", "in_network"),
                    request.form.get("bills_oon") or "unknown", current_user.agency_id)
    db.session.commit()
    flash("Plan flag saved.", "success")
    return redirect(url_for("providers.provider_edit", provider_id=provider_id))


@providers_bp.route("/providers/<int:provider_id>/plan-flag/<int:plan_id>/delete", methods=["POST"])
@login_required
def provider_remove_plan_flag(provider_id, plan_id):
    _can_edit()
    p = Provider.query.filter_by(id=provider_id,
                                 agency_id=current_user.agency_id).first_or_404()
    p.remove_plan_flag(plan_id); db.session.commit()
    flash("Plan flag removed.", "success")
    return redirect(url_for("providers.provider_edit", provider_id=provider_id))
```

- Update the `render_template("providers_form.html", ...)` calls: remove `bills_opts`, add `type_groups=TYPE_GROUPS`, `plans=plans` (edit only, or both), and on edit pass `plan_flags=p.plan_flags` + `plans_by_id={pl.id: pl for pl in plans}` + `plan_status=PLAN_STATUS`, `bills_oon=BILLS_OON`.

- [ ] **Step 4: Update the templates**

`providers_form.html`:
- Add a **Group** text field after Name: `<label>Group / affiliation<br><input class="form-input" name="group" value="{{ provider.group if provider else '' }}"></label>`.
- Replace the flat datalist with a **grouped** one (label options per category — degrades to a filterable flat list):

```html
<datalist id="type-suggest">
  {% for cat, items in type_groups %}
  <option value="" disabled>—— {{ cat }} ——</option>
  {% for t in items %}<option value="{{ t }}">{% endfor %}
  {% endfor %}
</datalist>
```

- **Remove** the whole `<fieldset>Bills a PPO out-of-network</fieldset>` block.
- On EDIT only, add a **Plan flags** section BELOW the main form (its own small forms so it posts independently):

```html
{% if provider %}
<h2 style="font-size:14px;margin-top:24px">Plan-specific flags</h2>
<p style="font-size:12px;color:var(--slate)">Flag this provider on the specific plans where it matters (in/out of network; for PPO plans, whether they'll bill out-of-network).</p>
{% for f in plan_flags %}
  {% set pl = plans_by_id.get(f.plan_id) %}
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
    <span>{{ pl.carrier if pl else '?' }} — {{ pl.display_id if pl else f.plan_id }} — {{ pl.plan_name if pl else '' }}
      · <strong>{{ 'In-network' if f.status=='in_network' else 'Out-of-network' }}</strong>
      {% if f.bills_oon and f.bills_oon != 'unknown' %} · bills OON: {{ f.bills_oon }}{% endif %}</span>
    <form method="post" action="{{ url_for('providers.provider_remove_plan_flag', provider_id=provider.id, plan_id=f.plan_id) }}">
      <button class="btn-secondary" style="font-size:11px;color:var(--status-error)">Remove</button></form>
  </div>
{% endfor %}
<form method="post" action="{{ url_for('providers.provider_add_plan_flag', provider_id=provider.id) }}" style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
  <select name="plan_id" class="form-input" required style="max-width:340px">
    <option value="">Pick a plan…</option>
    {% for pl in plans %}<option value="{{ pl.id }}">{{ pl.carrier }} — {{ pl.display_id }} — {{ pl.plan_name }}</option>{% endfor %}
  </select>
  <select name="status" class="form-input">{% for s in plan_status %}<option value="{{ s }}">{{ 'In-network' if s=='in_network' else 'Out-of-network' }}</option>{% endfor %}</select>
  <select name="bills_oon" class="form-input">{% for b in bills_oon %}<option value="{{ b }}">bills OON: {{ b }}</option>{% endfor %}</select>
  <button class="btn-primary" type="submit">Add plan flag</button>
</form>
{% endif %}
```

`providers_list.html`: show `group` as a muted sub-label under the name (`{% if p.group %}<span class="prov-meta">{{ p.group }}</span>{% endif %}`); remove the whole-provider plays-nice badge (it's per-plan now).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_providers.py -q`
Expected: PASS. Also `python3 -m pytest tests/test_plan_detail_route.py -q` (no regression yet — accessor still carrier-only until Task 3).

- [ ] **Step 6: Commit**

```bash
git add app/providers.py app/templates/providers_form.html app/templates/providers_list.html tests/test_providers.py
git commit -m "feat: provider form v2 — group field, grouped types, per-plan flag add/remove"
```

---

### Task 3: accessor plan-layer precedence + plan panel rendering

**Files:**
- Modify: `app/carriers.py` (`providers_for_plan`)
- Modify: `app/templates/plan_detail.html` (group sub-label; plays-nice from plan-flag)
- Test: `tests/test_plan_detail_route.py` (extend)

**Interfaces:**
- Consumes: `Provider.plan_flag_for` (Task 1).
- Produces: `providers_for_plan(plan, agency_id)` unchanged shape `{"in_network", "not_in_network", "is_ppo"}`, BUT the in/not split now honors a plan-specific flag over the carrier default, and each provider in the payload carries its resolved `bills_oon` for this plan (attach as an attribute the template reads, e.g. set `p._bills_oon` on the instance, or return richer dicts). Use dicts to avoid mutating ORM instances: each grouped entry is `{"provider": p, "bills_oon": <str|None>}`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_plan_detail_route.py`:

```python
def test_plan_flag_overrides_carrier_default(ctx):
    app, agency_id, uid, pid = ctx  # ctx plan carrier "Humana", make it the flagged plan
    from app.carriers import providers_for_plan
    from app.models import Plan, Provider
    with app.app_context():
        plan = db.session.get(Plan, pid)
        # provider accepts Humana at carrier level → would be in-network by default
        p = Provider(agency_id=agency_id, name="NE Digestive", county="Cabarrus", created_by_id=uid)
        db.session.add(p); db.session.flush(); p.set_carriers(["Humana"])
        # but a plan-specific OUT flag on THIS plan must override → not_in_network
        p.set_plan_flag(pid, "out_of_network", "unknown", agency_id)
        db.session.commit()
        res = providers_for_plan(plan, agency_id)
    innames = {e["provider"].name for lst in res["in_network"].values() for e in lst}
    outnames = {e["provider"].name for lst in res["not_in_network"].values() for e in lst}
    assert "NE Digestive" in outnames and "NE Digestive" not in innames


def test_plan_flag_bills_oon_surfaced(ctx):
    app, agency_id, uid, pid = ctx
    from app.carriers import providers_for_plan
    from app.models import Plan, Provider
    with app.app_context():
        plan = db.session.get(Plan, pid); plan.plan_subtype = "ppo"
        p = Provider(agency_id=agency_id, name="Kann Family", county="Cabarrus", created_by_id=uid)
        db.session.add(p); db.session.flush(); p.set_carriers(["Humana"])
        p.set_plan_flag(pid, "in_network", "yes", agency_id)
        db.session.commit()
        res = providers_for_plan(plan, agency_id)
    entry = [e for lst in res["in_network"].values() for e in lst if e["provider"].name == "Kann Family"][0]
    assert entry["bills_oon"] == "yes"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_plan_detail_route.py -k plan_flag -q`
Expected: FAIL — payload entries aren't dicts / no override.

- [ ] **Step 3: Update the accessor**

Rewrite `providers_for_plan` in `app/carriers.py`:

```python
def providers_for_plan(plan, agency_id):
    """Network-snapshot payload for a plan. A provider's in/out for THIS plan =
    its plan-specific flag if one exists, else the carrier-level default. Each
    grouped entry is {"provider": p, "bills_oon": <str|None>} (bills_oon only from
    a plan-specific flag). Agency-scoped."""
    from app.models import Provider
    provs = (Provider.query.filter_by(agency_id=agency_id)
             .order_by(Provider.county, Provider.name).all())
    is_ppo = (plan.plan_subtype or "").lower() == "ppo"
    in_net, not_net = {}, {}
    for p in provs:
        flag = p.plan_flag_for(plan.id)
        if flag is not None:
            in_network = flag["status"] == "in_network"
            bills_oon = flag["bills_oon"] if is_ppo else None
        else:
            in_network = plan.carrier in p.carrier_names
            bills_oon = None
        entry = {"provider": p, "bills_oon": bills_oon}
        bucket = in_net if in_network else not_net
        bucket.setdefault(p.county or "—", []).append(entry)
    return {"in_network": in_net, "not_in_network": not_net, "is_ppo": is_ppo}
```

- [ ] **Step 4: Update the plan panel template**

In `plan_detail.html` the network panel loops must now read `entry.provider` + `entry.bills_oon` (was the bare provider `p` and `p.bills_ppo_oon`). Update the in-network loop:

```html
{% for county, entries in providers.in_network.items() %}
<div class="net-county">{{ county }}</div>
{% for e in entries %}{% set p = e.provider %}
<div class="net-row">{{ p.name }}{% if p.group %} <span class="net-meta">· {{ p.group }}</span>{% endif %}{% if p.provider_type %} <span class="net-meta">· {{ p.provider_type }}</span>{% endif %}{% if p.phone %} <span class="net-meta">· {{ p.phone }}</span>{% endif %}
  {% if providers.is_ppo and e.bills_oon %}
    · {% if e.bills_oon == 'yes' %}<span class="oon-yes">✓ bills OON</span>
    {% elif e.bills_oon == 'no' %}<span class="oon-no">✗ won't bill OON — customer pays upfront</span>
    {% else %}<span class="oon-unknown">? OON billing unknown</span>{% endif %}
  {% endif %}
</div>
{% endfor %}
{% endfor %}
```

And the not-in-network loop reads `e.provider` too:

```html
{% for county, entries in providers.not_in_network.items() %}
<div class="net-county">{{ county }}</div>
{% for e in entries %}{% set p = e.provider %}
<div class="net-row"><span class="oon-no">✗</span> {{ p.name }}{% if p.group %} <span class="net-meta">· {{ p.group }}</span>{% endif %}{% if p.provider_type %} <span class="net-meta">· {{ p.provider_type }}</span>{% endif %} <span class="net-meta">· not in network on {{ plan.carrier }}</span></div>
{% endfor %}
{% endfor %}
```

(The empty-state condition `{% if providers.in_network %}` is unchanged — still keyed on the dict being non-empty.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_plan_detail_route.py -q`
Expected: PASS (new + existing — the existing network-panel render tests must be updated if they asserted on the old bare-provider structure; update them to the `entry.provider` shape where needed).

- [ ] **Step 6: Commit**

```bash
git add app/carriers.py app/templates/plan_detail.html tests/test_plan_detail_route.py
git commit -m "feat: plan panel honors per-plan flags (override carrier default) + group sub-label + per-plan bills_oon"
```

---

### Task 4: Full-suite regression + headless screenshot verification

**Files:** no production changes (verification only).

- [ ] **Step 1: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS (prior baseline 767 adjusted for changed/added tests). Record the count.

- [ ] **Step 2: Headless screenshot verification**

Serve the app against a seeded scratch DB (reuse the preview-server pattern) with: a Devoted PPO plan + a Humana HMO plan; providers where one has a plan-specific OUT flag on the PPO (overriding carrier-accepted), one has a plan-specific bills_oon=yes on the PPO, one with a `group` set. With playwright:
  - **Providers edit form:** the Group field renders; the grouped type datalist shows category labels; the Plan-specific-flags section lists existing flags + the add-flag row (plan select + status + bills_oon). Screenshot.
  - **Plan page (PPO) Pro view:** a carrier-accepted provider flagged OUT on this plan shows in the not-in-network section (override works); a provider with bills_oon=yes shows ✓ bills OON; group renders as a sub-label. Screenshot light + dark.
  - **List page:** group sub-label shows; no whole-provider plays-nice badge.

Expected: all render correctly; override + per-plan bills_oon + group all visible; both themes legible.

- [ ] **Step 3: Commit verification note (optional, empty allowed)**

```bash
git commit --allow-empty -m "test: full suite + headless verification for provider intake-form v2"
```

---

## Self-Review

**1. Spec coverage:**
- Section 1 (two-layer model, provider_plans, precedence, drop bills_ppo_oon clean) → Task 1 (model/migration) + Task 3 (accessor precedence). ✅
- Section 2 (group field, grouped expanded types) → Task 1 (group col) + Task 2 (form + type groups). ✅
- Section 3 (form plan-flags section, list group sub-label, panel plan-flag-aware) → Task 2 (form/list) + Task 3 (panel). ✅
- Section 4 (testing incl. override precedence, PPO bills_oon, gate, grouped datalist, screenshots) → Tasks 1–4. ✅
- Global constraints (precedence, provider_plans shape, clean drop w/ 0-row check, group, is_ppo gate, agency scoping, edit gate unchanged, mig 042, grouped-best-effort, theme, screenshots) → each mapped. ✅

**2. Placeholder scan:** No TBD/TODO. The SQLite batch-op note (Step 5 Task 1) is a concrete instruction, not a placeholder. The picker is a concrete `<select>` (not a vague "typeahead"). ✅

**3. Type consistency:** `set_plan_flag(plan_id, status, bills_oon, agency_id)`, `remove_plan_flag(plan_id)`, `plan_flag_for(plan_id)`, `plan_flags` (list of dicts) consistent across Tasks 1→2→3. Accessor payload entries are `{"provider", "bills_oon"}` dicts consistent Tasks 3 (accessor) → Task 3 (template) → Task 4. `provider_plans` columns consistent. Migration `revision="042"`, `down_revision="041"`. The template change from bare-provider to `entry.provider` is applied in BOTH the in-network and not-in-network loops (a mismatch would 500) — Task 3 Step 4 does both. ✅
