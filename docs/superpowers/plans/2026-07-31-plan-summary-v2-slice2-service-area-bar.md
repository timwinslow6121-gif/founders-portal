# Plan-Summary v2 — Slice 2 (Service-Area Bar) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a service-area bar to the top of the plan-detail page (`/carriers/<id>`) showing "📍 Available in NC · N counties" with an expandable county list for Part C/PDP plans (from CMS Landscape county data loaded into a new `plan_service_areas` table), and a simple "📍 Available statewide in NC" line for Medigap/DVH/HI — never a fabricated count.

**Architecture:** A new `PlanServiceArea` model (one row per plan+state+county) + migration 039. An idempotent seed script loads the county list from the CMS Landscape CSV, matched to DB plans by CMS contract+plan ID and year (following the existing `scripts/seed_plan_buckets.py` pattern: a testable `*_from_rows(rows, agency, apply)` core + a thin `main()`). The `plan_detail` route computes a `service_area` dict via a small agency-scoped accessor and passes it to the template. `plan_detail.html` renders the bar above the KPI row (shared across both Consumer/Pro views) with a vanilla-JS "View all" toggle. No client round-trip.

**Tech Stack:** Flask 3.0, Flask-SQLAlchemy, Flask-Migrate (Alembic), Jinja2, vanilla JS, Founders theme CSS tokens. Tests: pytest (SQLite in-memory, matching `tests/test_plan_detail_route.py` + `tests/test_seed_plan_buckets.py`).

## Global Constraints

- **No fabricated data.** A county count/list is shown ONLY when real `plan_service_areas` rows exist for the plan. Absent rows → the state-line fallback, never a zero or invented count. — spec Section 1.
- **State-line fallback wording:** `📍 {plan.service_area}` if `plan.service_area` is set, else `📍 Available statewide in NC` (Tim confirmed "statewide" is the house term). — spec Section 1 + user.
- **Multi-tenant scoping:** every `plan_service_areas` query filters `agency_id=current_user.agency_id`. — spec Section 3 + CLAUDE.md.
- **Migration number = 039** (current head is 038, verified). — build-time check done.
- **CMS IDs are dash-form** in the DB (`H5253-041`); the Landscape CSV has separate `Contract ID` (`H5253`) + `Plan ID` (`041`) columns. Parse/join accordingly. — spec grounding + `cms_plan_id_of` convention.
- **Skip non-county sentinels** when counting: a `County Name` of `All Counties` or blank is NOT a county. — spec Section 2.
- **Seed is idempotent:** re-running replaces a plan's rows (delete-then-insert scoped to that plan_id) — no duplicates; unique constraint `(plan_id, state, county)` backs it. — spec Section 2.
- **Bar is customer-safe** (geography only) → renders in BOTH Consumer and Pro views, placed once above the toggle/KPI row. — spec Section 1.
- **Founders theme tokens, light + dark**; county names are DB strings rendered with autoescape (no `|safe`). — spec Section 3.
- The visual IS a deliverable: **headless-browser screenshot verification** (Part C county bar + expanded list; Medigap state line; light + dark) + full suite green. — spec Section 3.

---

### Task 1: `PlanServiceArea` model + migration 039

**Files:**
- Modify: `app/models.py` (add the model near the other Plan-related models, e.g. after `Plan`)
- Create: `migrations/versions/039_*.py` (Alembic)
- Test: `tests/test_plan_service_areas.py` (new — model/table smoke)

**Interfaces:**
- Consumes: existing `Plan`, `Agency` models.
- Produces: `PlanServiceArea` with columns `id`, `plan_id` (FK plans.id, ondelete CASCADE, index), `agency_id` (FK agencies.id, index), `state` (String(32)), `county` (String(128)); table `plan_service_areas`; unique constraint `uq_plan_service_area` on `(plan_id, state, county)`. Later tasks query it by `plan_id` + `agency_id`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_plan_service_areas.py`:

```python
import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, Plan, PlanServiceArea


@pytest.fixture
def ctx():
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False, WTF_CSRF_ENABLED=False, LOGIN_DISABLED=True)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        p = Plan(agency_id=ag.id, carrier="UHC", cms_plan_id="H5253-041", year=2026,
                 plan_name="Patriot", plan_type="mapd", status="current")
        db.session.add(p); db.session.commit()
        yield app, ag.id, p.id
        db.session.remove(); db.drop_all()


def test_plan_service_area_rows_persist(ctx):
    app, agency_id, pid = ctx
    with app.app_context():
        db.session.add(PlanServiceArea(plan_id=pid, agency_id=agency_id,
                                       state="NC", county="Mecklenburg"))
        db.session.add(PlanServiceArea(plan_id=pid, agency_id=agency_id,
                                       state="NC", county="Cabarrus"))
        db.session.commit()
        rows = PlanServiceArea.query.filter_by(plan_id=pid, agency_id=agency_id).all()
        assert {r.county for r in rows} == {"Mecklenburg", "Cabarrus"}


def test_plan_service_area_unique_constraint(ctx):
    app, agency_id, pid = ctx
    with app.app_context():
        db.session.add(PlanServiceArea(plan_id=pid, agency_id=agency_id,
                                       state="NC", county="Mecklenburg"))
        db.session.commit()
        db.session.add(PlanServiceArea(plan_id=pid, agency_id=agency_id,
                                       state="NC", county="Mecklenburg"))
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_plan_service_areas.py -q`
Expected: FAIL — `ImportError: cannot import name 'PlanServiceArea'`.

- [ ] **Step 3: Add the model**

In `app/models.py`, add after the `Plan` model:

```python
class PlanServiceArea(db.Model):
    """One row per (plan, state, county) the plan is offered in — loaded from the
    CMS Landscape by scripts/seed_plan_service_areas.py. Drives the plan-detail
    service-area bar. Part C / PDP plans (with a CMS ID) get rows; Medigap/DVH/HI
    have no CMS ID and no rows (bar falls back to a state line)."""
    __tablename__ = "plan_service_areas"

    id        = db.Column(db.Integer, primary_key=True)
    plan_id   = db.Column(db.Integer, db.ForeignKey("plans.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    agency_id = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    state     = db.Column(db.String(32), nullable=False)
    county    = db.Column(db.String(128), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("plan_id", "state", "county", name="uq_plan_service_area"),
    )

    def __repr__(self):
        return f"<PlanServiceArea plan={self.plan_id} {self.state}/{self.county}>"
```

- [ ] **Step 4: Create the migration**

Run: `python3 -m flask db migrate -m "plan_service_areas table"` (or hand-write `migrations/versions/039_plan_service_areas.py` with `down_revision = "038"`).

Hand-written migration body (use this if autogenerate isn't available in the env):

```python
"""plan_service_areas table

Revision ID: 039
Revises: 038
"""
from alembic import op
import sqlalchemy as sa

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plan_service_areas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("county", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "state", "county", name="uq_plan_service_area"),
    )
    op.create_index("ix_plan_service_areas_plan_id", "plan_service_areas", ["plan_id"])
    op.create_index("ix_plan_service_areas_agency_id", "plan_service_areas", ["agency_id"])


def downgrade():
    op.drop_index("ix_plan_service_areas_agency_id", table_name="plan_service_areas")
    op.drop_index("ix_plan_service_areas_plan_id", table_name="plan_service_areas")
    op.drop_table("plan_service_areas")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_plan_service_areas.py -q`
Expected: PASS. Also `python3 -m flask db upgrade` runs clean against a scratch SQLite DB (migration is valid).

- [ ] **Step 6: Commit**

```bash
git add app/models.py migrations/versions/039_*.py tests/test_plan_service_areas.py
git commit -m "feat: PlanServiceArea model + migration 039 (service-area bar data)"
```

---

### Task 2: Seed script `scripts/seed_plan_service_areas.py`

Load each DB plan's counties from the CMS Landscape CSV. Testable core `seed_service_areas_from_rows(rows, agency_id, apply, states)` + thin `main()`, mirroring `scripts/seed_plan_buckets.py`.

**Files:**
- Create: `scripts/seed_plan_service_areas.py`
- Test: `tests/test_seed_plan_service_areas.py` (new)

**Interfaces:**
- Consumes: `Plan` (by `cms_plan_id` dash-form + `year`), `PlanServiceArea` (Task 1), `db`.
- Produces: `seed_service_areas_from_rows(rows, agency_id, apply=False, states=("NC",)) -> dict` returning a report `{"plans_matched": int, "counties_loaded": int, "plans_skipped_no_cms": int, "cms_not_in_csv": [cms_id,...]}`. Delete-then-insert per matched plan when `apply=True`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_seed_plan_service_areas.py`:

```python
import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, Plan, PlanServiceArea
from scripts.seed_plan_service_areas import seed_service_areas_from_rows


def _row(contract, plan, county, state="NC", year="2026"):
    return {"Contract Year": year, "State Territory Abbreviation": state,
            "County Name": county, "Contract ID": contract, "Plan ID": plan}


@pytest.fixture
def ctx():
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False, LOGIN_DISABLED=True)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        # A Part C plan that IS in the CSV, and a Medigap plan that is NOT (no cms id).
        db.session.add(Plan(agency_id=ag.id, carrier="UHC", cms_plan_id="H5253-041",
                            year=2026, plan_name="Patriot", plan_type="mapd", status="current"))
        db.session.add(Plan(agency_id=ag.id, carrier="Aetna", cms_plan_id=None,
                            plan_letter="G", year=2026, plan_name="Medigap Plan G",
                            plan_type="medigap", status="current"))
        db.session.commit()
        yield app, ag.id


def test_seed_loads_counties_and_skips_sentinel_and_noncarried(ctx):
    app, agency_id = ctx
    rows = [
        _row("H5253", "041", "Mecklenburg"),
        _row("H5253", "041", "Cabarrus"),
        _row("H5253", "041", "All Counties"),   # sentinel — must be skipped
        _row("H5253", "041", ""),                # blank — must be skipped
        _row("H9999", "001", "Wake"),            # not carried — must be skipped
    ]
    with app.app_context():
        report = seed_service_areas_from_rows(rows, agency_id, apply=True, states=("NC",))
        assert report["plans_matched"] == 1
        assert report["counties_loaded"] == 2          # Mecklenburg + Cabarrus only
        p = Plan.query.filter_by(cms_plan_id="H5253-041").first()
        got = {r.county for r in PlanServiceArea.query.filter_by(plan_id=p.id).all()}
        assert got == {"Mecklenburg", "Cabarrus"}


def test_seed_is_idempotent(ctx):
    app, agency_id = ctx
    rows = [_row("H5253", "041", "Mecklenburg"), _row("H5253", "041", "Cabarrus")]
    with app.app_context():
        seed_service_areas_from_rows(rows, agency_id, apply=True)
        seed_service_areas_from_rows(rows, agency_id, apply=True)   # second run
        p = Plan.query.filter_by(cms_plan_id="H5253-041").first()
        assert PlanServiceArea.query.filter_by(plan_id=p.id).count() == 2  # no dupes


def test_seed_dry_run_writes_nothing(ctx):
    app, agency_id = ctx
    rows = [_row("H5253", "041", "Mecklenburg")]
    with app.app_context():
        report = seed_service_areas_from_rows(rows, agency_id, apply=False)
        assert report["plans_matched"] == 1
        assert PlanServiceArea.query.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_seed_plan_service_areas.py -q`
Expected: FAIL — `ModuleNotFoundError: scripts.seed_plan_service_areas`.

- [ ] **Step 3: Write the seed script**

Create `scripts/seed_plan_service_areas.py`:

```python
"""Load each DB plan's service-area counties from the CMS Landscape CSV into
plan_service_areas (drives the plan-detail service-area bar). Matches DB plans by
CMS contract+plan ID (dash-form cms_plan_id, e.g. H5253-041) + year. Idempotent:
replaces a matched plan's county rows (delete-then-insert). Skips non-carried plans,
plans with no CMS ID (Medigap/DVH/HI), and the 'All Counties'/blank county sentinels.

Read-only unless --apply. Mirrors scripts/seed_plan_buckets.py.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_plan_service_areas.py \
      --agency 1 --file "docs/Medicare Landscape Files/CY2026_Landscape_202603/CY2026_Landscape_202603.csv" [--apply]
"""
import argparse
import csv

from app import create_app
from app.extensions import db
from app.models import Plan, PlanServiceArea

CMS_YEAR = 2026
_SENTINEL_COUNTIES = {"", "all counties"}


def seed_service_areas_from_rows(rows, agency_id, apply=False, states=("NC",)):
    """Build (contract, plan) -> {(state, county)} from CSV rows, then for each DB
    plan with a matching dash-form cms_plan_id + year, replace its county rows."""
    states_up = {s.strip().upper() for s in states}

    # contract+plan (dash-form) -> set[(state, county)]
    wanted = {}
    for row in rows:
        st = (row.get("State Territory Abbreviation") or "").strip().upper()
        if st not in states_up:
            continue
        county = (row.get("County Name") or "").strip()
        if county.lower() in _SENTINEL_COUNTIES:
            continue
        contract = (row.get("Contract ID") or "").strip()
        plan = (row.get("Plan ID") or "").strip()
        if not contract or not plan:
            continue
        cms_id = f"{contract}-{plan}"                 # dash-form, matches Plan.cms_plan_id
        wanted.setdefault(cms_id, set()).add((st, county))

    report = {"plans_matched": 0, "counties_loaded": 0,
              "plans_skipped_no_cms": 0, "cms_not_in_csv": []}

    plans = Plan.query.filter_by(agency_id=agency_id, year=CMS_YEAR).all()
    for p in plans:
        if not p.cms_plan_id:
            report["plans_skipped_no_cms"] += 1
            continue
        counties = wanted.get(p.cms_plan_id)
        if not counties:
            report["cms_not_in_csv"].append(p.cms_plan_id)
            continue
        report["plans_matched"] += 1
        report["counties_loaded"] += len(counties)
        if apply:
            PlanServiceArea.query.filter_by(plan_id=p.id).delete()
            for st, county in sorted(counties):
                db.session.add(PlanServiceArea(plan_id=p.id, agency_id=agency_id,
                                               state=st, county=county))
    if apply:
        db.session.commit()
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--states", default="NC", help="comma-separated state abbrevs")
    args = ap.parse_args()
    states = tuple(s.strip() for s in args.states.split(",") if s.strip())

    app = create_app()
    with app.app_context():
        with open(args.file, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        res = seed_service_areas_from_rows(rows, args.agency, apply=args.apply, states=states)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] plans_matched={res['plans_matched']} "
              f"counties_loaded={res['counties_loaded']} "
              f"skipped_no_cms={res['plans_skipped_no_cms']} "
              f"cms_not_in_csv={len(res['cms_not_in_csv'])}")
        if res["cms_not_in_csv"]:
            print("  CMS IDs in DB but not in CSV:", ", ".join(sorted(res["cms_not_in_csv"])[:40]))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_seed_plan_service_areas.py -q`
Expected: PASS (all 3).

- [ ] **Step 5: Commit**

```bash
git add scripts/seed_plan_service_areas.py tests/test_seed_plan_service_areas.py
git commit -m "feat: seed_plan_service_areas.py — load CMS Landscape counties per plan (idempotent)"
```

---

### Task 3: Route accessor — pass `service_area` dict to the template

Add an agency-scoped accessor and wire it into `plan_detail`.

**Files:**
- Modify: `app/carriers.py` (`plan_detail` + a small module-level helper)
- Test: `tests/test_plan_detail_route.py` (extend)

**Interfaces:**
- Consumes: `PlanServiceArea` (Task 1), the plan being viewed, `current_user.agency_id`.
- Produces: `service_area_for(plan, agency_id) -> dict`:
  - rows present → `{"mode": "counties", "state": <state with most counties>, "count": <int>, "counties": [<sorted county names>]}`
  - no rows → `{"mode": "state", "label": plan.service_area or "Available statewide in NC"}`
  Passed to `render_template("plan_detail.html", ..., service_area=<dict>)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_plan_detail_route.py` (the `ctx` fixture already seeds a `Humana H1036-335` mapd plan; add PlanServiceArea import):

```python
from app.models import PlanServiceArea


def test_service_area_counties_mode_when_rows_exist(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    with app.app_context():
        for c in ("Mecklenburg", "Cabarrus", "Union"):
            db.session.add(PlanServiceArea(plan_id=pid, agency_id=agency_id,
                                           state="NC", county=c))
        db.session.commit()
    from app import carriers
    captured = {}
    real = carriers.render_template
    def fake(t, **c):
        captured.update(c); return real(t, **c)
    monkeypatch.setattr(carriers, "render_template", fake)
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        carriers.plan_detail(pid)
    sa = captured["service_area"]
    assert sa["mode"] == "counties"
    assert sa["state"] == "NC"
    assert sa["count"] == 3
    assert sa["counties"] == ["Cabarrus", "Mecklenburg", "Union"]   # sorted


def test_service_area_state_mode_when_no_rows(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    from app import carriers
    captured = {}
    real = carriers.render_template
    def fake(t, **c):
        captured.update(c); return real(t, **c)
    monkeypatch.setattr(carriers, "render_template", fake)
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        carriers.plan_detail(pid)
    sa = captured["service_area"]
    assert sa["mode"] == "state"
    assert sa["label"] == "Available statewide in NC"   # plan.service_area is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_plan_detail_route.py -k service_area -q`
Expected: FAIL — `KeyError: 'service_area'`.

- [ ] **Step 3: Implement the accessor + wire it in**

In `app/carriers.py`, add a module-level helper (near `_parse_details`):

```python
def service_area_for(plan, agency_id):
    """Build the service-area bar payload for a plan. Counties from plan_service_areas
    (agency-scoped) when present, else a state-line fallback. Never fabricates a count."""
    from app.models import PlanServiceArea
    rows = (PlanServiceArea.query
            .filter_by(plan_id=plan.id, agency_id=agency_id)
            .all())
    if rows:
        # Group by state; pick the state with the most counties as the primary line.
        by_state = {}
        for r in rows:
            by_state.setdefault(r.state, []).append(r.county)
        state = max(by_state, key=lambda s: len(by_state[s]))
        counties = sorted(by_state[state])
        return {"mode": "counties", "state": state,
                "count": len(counties), "counties": counties}
    return {"mode": "state",
            "label": plan.service_area or "Available statewide in NC"}
```

Then in `plan_detail`, before the `return render_template(...)`, add:

```python
    service_area = service_area_for(plan, current_user.agency_id)
```

and add `service_area=service_area,` to the `render_template("plan_detail.html", ...)` kwargs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_plan_detail_route.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add app/carriers.py tests/test_plan_detail_route.py
git commit -m "feat: plan_detail passes service_area (county counts or state-line fallback)"
```

---

### Task 4: Render the bar in `plan_detail.html`

Add the bar above the KPI row (shared across both views), its CSS, and the "View all" toggle JS.

**Files:**
- Modify: `app/templates/plan_detail.html`
- Test: `tests/test_plan_detail_route.py` (add a render-smoke assertion)

**Interfaces:**
- Consumes: `service_area` (Task 3).
- Produces: DOM with a `.service-area-bar`; a `[data-service-area-toggle]` "View all" control + `.sa-counties` list when `mode == "counties"`; a plain line when `mode == "state"`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_plan_detail_route.py`:

```python
def test_template_renders_service_area_bar(ctx):
    app, agency_id, uid, pid = ctx
    with app.app_context():
        for c in ("Mecklenburg", "Cabarrus"):
            db.session.add(PlanServiceArea(plan_id=pid, agency_id=agency_id,
                                           state="NC", county=c))
        db.session.commit()
    from app import carriers
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert "service-area-bar" in html
    assert "2 counties" in html                 # count line
    assert "data-service-area-toggle" in html   # View all control
    assert "Mecklenburg" in html                # county in the (collapsed) list


def test_template_service_area_state_line(ctx):
    app, agency_id, uid, pid = ctx
    from app import carriers
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert "service-area-bar" in html
    assert "Available statewide in NC" in html
    assert "data-service-area-toggle" not in html   # no toggle without counties
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_plan_detail_route.py -k service_area_bar -q`
Expected: FAIL — `assert "service-area-bar" in html` fails.

- [ ] **Step 3: Add the bar CSS**

In `plan_detail.html`'s `{% block styles %}` append:

```css
.service-area-bar { display:flex; align-items:center; gap:8px; flex-wrap:wrap;
  background:var(--surface-low); border:1px solid var(--border);
  border-radius:var(--radius-sm); padding:8px 14px; margin-bottom:16px;
  font-size:13px; color:var(--ivory); }
.service-area-bar .sa-pin { color:var(--gold); }
.service-area-bar .sa-muted { color:var(--slate); }
.service-area-bar button.sa-toggle { border:none; background:transparent; cursor:pointer;
  color:var(--gold); font-size:12px; font-weight:600; padding:0; text-decoration:underline; }
.sa-counties { width:100%; margin-top:6px; font-size:12px; color:var(--slate);
  line-height:1.7; }
```

- [ ] **Step 4: Add the bar markup + toggle JS**

Place the bar in the content block ABOVE the Consumer/Pro toggle + KPI row (so it renders once, shared by both views). Insert right after the `page-header` block:

```html
{# Service-area bar — geography only (customer-safe); shared across both views #}
<div class="service-area-bar">
  <span class="sa-pin">📍</span>
  {% if service_area.mode == 'counties' %}
    <span>Available in <strong>{{ service_area.state }}</strong>
      <span class="sa-muted">· {{ service_area.count }} count{{ 'y' if service_area.count == 1 else 'ies' }}</span>
    </span>
    <button type="button" class="sa-toggle" data-service-area-toggle>View all</button>
    <div class="sa-counties" hidden>{{ service_area.counties | join(', ') }}</div>
  {% else %}
    <span>{{ service_area.label }}</span>
  {% endif %}
</div>
```

And add the toggle JS before `{% endblock %}` (alongside the existing plan-view toggle script):

```html
<script>
(function () {
  var btn = document.querySelector('[data-service-area-toggle]');
  var list = document.querySelector('.sa-counties');
  if (!btn || !list) return;
  btn.addEventListener('click', function () {
    var show = list.hidden;
    list.hidden = !show;
    btn.textContent = show ? 'Hide' : 'View all';
  });
})();
</script>
```

- [ ] **Step 5: Run the render tests + full plan-detail suite**

Run: `python3 -m pytest tests/test_plan_detail_route.py -q`
Expected: PASS (new + existing).

- [ ] **Step 6: Commit**

```bash
git add app/templates/plan_detail.html tests/test_plan_detail_route.py
git commit -m "feat: render service-area bar on plan-detail (county count + expandable list)"
```

---

### Task 5: Full-suite regression + headless screenshot verification

**Files:** no production changes (verification only; may add a throwaway seed under the scratchpad, not committed).

**Interfaces:** Consumes everything from Tasks 1–4.

- [ ] **Step 1: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS (prior baseline 704 + the new tests). Record the count.

- [ ] **Step 2: Headless screenshot verification**

Serve the app against a seeded scratch DB (reuse the slice-1 preview-server pattern) with: a Part C plan that has several `PlanServiceArea` rows (e.g. Mecklenburg/Cabarrus/Union) and a Medigap plan with none. With the playwright browser tools:
  - Navigate to the Part C plan → verify the bar shows "Available in NC · 3 counties" + "View all"; click it → county names expand; button flips to "Hide". Screenshot light + dark.
  - Navigate to the Medigap plan → verify "📍 Available statewide in NC", no "View all". Screenshot.
  - Confirm the bar renders in BOTH Consumer and Pro views (toggle) and doesn't break the slice-1 KPI row.

Expected: bar renders correctly per type, toggle works, both themes legible, no layout regression.

- [ ] **Step 3: Commit verification note (optional, empty allowed)**

```bash
git commit --allow-empty -m "test: full suite + headless verification for service-area bar"
```

---

## Self-Review

**1. Spec coverage:**
- Section 1 (bar rendering: counties mode + View all; state-line fallback; both views; no fabricated count) → Task 3 (accessor) + Task 4 (render). ✅
- Section 2 (new table + idempotent CMS seed, skip sentinels + non-carried, match by CMS ID+year) → Task 1 (model/migration) + Task 2 (seed). ✅
- Section 3 (route accessor + template + tests + headless verify) → Tasks 3–5. ✅
- Global constraints (no fabricated data, statewide fallback wording, agency scoping, mig 039, dash-form CMS IDs, sentinel skip, idempotent, customer-safe both-views, theme, screenshots) → each mapped to a task's steps/tests. ✅
- Files list (models+migration, seed, carriers.py, plan_detail.html, tests) → all covered. ✅
- Out-of-scope items (per-client match, county search, segment variation, editing UI, multi-state) → not built; multi-state handled minimally via "primary state" pick, explicitly. ✅

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N" — every step has real code. ✅

**3. Type consistency:** `seed_service_areas_from_rows(rows, agency_id, apply, states)` and `service_area_for(plan, agency_id)` signatures + the `service_area` dict shape (`mode`/`state`/`count`/`counties`/`label`) are identical across Tasks 2→3→4. `PlanServiceArea` column names (`plan_id`, `agency_id`, `state`, `county`) consistent across Tasks 1→2→3. Migration `down_revision="038"`, revision `"039"`. ✅
