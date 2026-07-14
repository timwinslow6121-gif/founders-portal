# Plan Snapshot Per-Plan-Type Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/carriers/<plan_id>` from a generic key-value dump into a type-aware condensed-SOB reference card that renders only the benefits relevant to each plan type (Part C / PDP / Medigap / DVH / Hospital Indemnity), in the Founders theme.

**Architecture:** A single `plan_detail.html` template driven by a Python config (`app/plan_sections.py`) that maps each `plan_type` → the ordered benefit groups/fields to show. Benefit values are read from the existing flat `Plan.details_json` dict (via `_parse_details`) plus static/derived helpers (Medigap grid, OOP-cap-by-year). Two compound benefits (OTC, Dental) render via shared Jinja macros. Medigap covered-gaps come from a hardcoded CMS grid; DVH/Medigap premiums display "age-rated". A small set of new benefit keys is added to the existing admin edit form. No money paths touched — benefit metadata only.

**Tech Stack:** Flask 3 / Jinja2 templates, vanilla CSS using base.html `--var` tokens + the global `.plan-type-tag` classes, PostgreSQL (no schema change — all in `details_json`).

## Global Constraints

- Plan-type values are lowercase-canonical: `mapd`, `ma`, `pdp`, `medigap`, `dvh`, `gtl` (Hospital Indemnity plans are carrier GTL/Wellabe; `plan_type` for HI = `gtl`). Part C = `ma` + `mapd`.
- Founders theme only: use `var(--gold)` (blue #266EA5), `var(--green)`, `var(--ivory)`, `var(--slate)`, `var(--surface)`, `var(--border)`, `var(--radius)`; must render in light AND dark. Reuse the global `.plan-type-tag tag-<type>` classes (already in base.html).
- No KPI cards. The only headline stat is member count. Everything else is benefit line-items.
- Render ONLY fields relevant to the plan's type — never emit an empty "—" row for a field that doesn't apply to that type.
- DVH + Medigap premiums are age-rated/per-person → show the literal string "Age-rated (per quote)", never a single premium figure.
- Benefit values live in the FLAT `Plan.details_json` dict (keys like `otc_allowance`, `dental_note`), read via `app/carriers.py::_parse_details`. Editing reuses the existing admin `plan_form.html` form + `BENEFIT_KEYS` list in `app/carriers.py`. Do NOT introduce the nested `_meta` provenance structure for this page.
- Existing member-count logic in `plan_detail` (count by `Policy.plan_id`, unlimited `.count()`, capped row list) is CORRECT — keep it.
- Run the suite with `python3 -m pytest -q`. Full suite must stay green (currently 607 passing).

---

### Task 1: Plan-type section config + helpers (`app/plan_sections.py`)

**Files:**
- Create: `app/plan_sections.py`
- Test: `tests/test_plan_sections.py`

**Interfaces:**
- Produces:
  - `coverage_category(plan_type) -> str` — one of `part_c|pdp|medigap|dvh|hospital_indemnity|other`.
  - `sections_for(plan) -> list[dict]` — ordered groups for a plan, each `{"title": str, "rows": [(label, key)], "blocks": [str]}` where `blocks` names special mini-blocks (`"otc"`, `"dental"`) and `rows` are `(display_label, details_json_key)` pairs. Only groups/rows relevant to the plan's type are included; the MAPD drugs group is included only when `plan.plan_type == "mapd"`.
  - `oop_cap_for_year(year) -> str|None` — `{2025:"$2,000",2026:"$2,100",2027:"$2,400"}.get(year)`.
  - `MEDIGAP_GRID: dict[str, dict[str,str]]` — static CMS letter→benefit coverage.
  - `medigap_coverage(letter) -> list[(benefit, coverage)]` — rows for a letter, or `[]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_sections.py
from app.plan_sections import (coverage_category, sections_for,
                               oop_cap_for_year, medigap_coverage)


class _Plan:
    def __init__(self, plan_type, year=2026, plan_letter=None):
        self.plan_type = plan_type
        self.year = year
        self.plan_letter = plan_letter


def test_coverage_category_groups_part_c():
    assert coverage_category("mapd") == "part_c"
    assert coverage_category("ma") == "part_c"
    assert coverage_category("pdp") == "pdp"
    assert coverage_category("medigap") == "medigap"
    assert coverage_category("dvh") == "dvh"
    assert coverage_category("gtl") == "hospital_indemnity"
    assert coverage_category("weird") == "other"


def test_mapd_includes_drugs_group_but_ma_does_not():
    mapd_titles = [g["title"] for g in sections_for(_Plan("mapd"))]
    ma_titles = [g["title"] for g in sections_for(_Plan("ma"))]
    assert "Drugs" in mapd_titles
    assert "Drugs" not in ma_titles
    # both are Part C so both have Costs + Medical services
    assert "Costs" in mapd_titles and "Costs" in ma_titles


def test_pdp_sections_have_no_medical_group():
    titles = [g["title"] for g in sections_for(_Plan("pdp"))]
    assert "Drugs" in titles
    assert "Medical services" not in titles


def test_part_c_has_otc_and_dental_blocks():
    extras = [g for g in sections_for(_Plan("mapd")) if g["title"] == "Extras"][0]
    assert "otc" in extras["blocks"]
    assert "dental" in extras["blocks"]


def test_oop_cap_by_year():
    assert oop_cap_for_year(2025) == "$2,000"
    assert oop_cap_for_year(2026) == "$2,100"
    assert oop_cap_for_year(2027) == "$2,400"
    assert oop_cap_for_year(2099) is None


def test_medigap_grid_plan_g_covers_part_b_deductible_no():
    rows = dict(medigap_coverage("G"))
    # Plan G covers everything EXCEPT the Part B deductible
    assert rows["Part A deductible"] == "Yes"
    assert rows["Part B deductible"] == "No"
    assert rows["Part B excess charges"] == "Yes"


def test_medigap_unknown_letter_empty():
    assert medigap_coverage("Z") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_plan_sections.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.plan_sections'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/plan_sections.py
"""Per-plan-type section config for the condensed-SOB plan snapshot page.

sections_for(plan) returns the ordered benefit groups to render for that plan's
type. Each group: {"title", "rows": [(label, details_json_key)], "blocks": [names]}.
Only relevant groups/rows are returned per type — the template never renders an
empty row for a field that doesn't apply. See
docs/superpowers/specs/2026-07-13-plan-snapshot-per-type-redesign.md
"""

_PART_C = {"ma", "mapd"}


def coverage_category(plan_type):
    pt = (plan_type or "").lower()
    if pt in _PART_C:
        return "part_c"
    if pt == "pdp":
        return "pdp"
    if pt in ("medigap", "ms"):
        return "medigap"
    if pt in ("dvh", "dental"):
        return "dvh"
    if pt in ("gtl", "hospital_indemnity", "hi"):
        return "hospital_indemnity"
    return "other"


# Part C groups. Rows are (display_label, details_json_key). Keys map to the flat
# Plan.details_json dict + a few real Plan columns surfaced by the route as details.
_PART_C_COSTS = [
    ("Monthly premium", "monthly_premium"),
    ("Medical deductible", "medical_deductible"),
    ("Annual out-of-pocket max", "annual_oopm"),
    ("Part-B giveback", "part_b_giveback"),
]
_PART_C_MEDICAL = [
    ("PCP copay", "pcp_copay"),
    ("Specialist copay", "specialist_copay"),
    ("Outpatient hospital", "outpatient_hospital"),
    ("Inpatient hospital", "inpatient_hospital"),
    ("X-ray / MRI / CT", "imaging"),
    ("PT / OT / ST", "therapy"),
    ("ER copay", "er_copay"),
    ("Urgent care", "urgent_care_copay"),
    ("Ambulance (ground)", "ambulance_ground"),
    ("Ambulance (air)", "ambulance_air"),
    ("SNF (days 1-20)", "snf"),
]
_PART_C_EXTRAS = [
    ("Gym", "gym"),
    ("Transportation", "transportation"),
    ("Vision", "vision_allowance"),
    ("Hearing", "hearing_allowance"),
]
_PART_C_DRUGS = [
    ("Rx deductible", "drug_deductible"),
    ("Tier 1", "drug_tier1"),
    ("Tier 2", "drug_tier2"),
    ("Tier 3", "drug_tier3"),
    ("Tier 4", "drug_tier4"),
    ("Tier 5", "drug_tier5"),
]
_PDP_ROWS = [
    ("Monthly premium", "monthly_premium"),
    ("Annual Rx deductible", "drug_deductible"),
    ("Preferred pharmacies", "preferred_pharmacy_note"),
]
_PDP_DRUGS = [
    ("Tier 1", "drug_tier1"), ("Tier 2", "drug_tier2"), ("Tier 3", "drug_tier3"),
    ("Tier 4", "drug_tier4"), ("Tier 5", "drug_tier5"),
]
_DVH_ROWS = [
    ("Annual benefit max", "annual_max"),
    ("Deductible", "dvh_deductible"),
    ("Vision", "vision_allowance"),
    ("Hearing", "hearing_allowance"),
    ("Waiting periods", "waiting_periods"),
]
_MEDIGAP_ROWS = [
    ("Household discount", "household_discount"),
    ("Rate type", "rate_type"),
]
_HI_BASE = [
    ("Hospital confinement (daily)", "hi_hospital_confinement"),
    ("Max benefit period (days)", "hi_max_days"),
    ("Observation / short stay", "hi_observation"),
    ("ER (injury)", "hi_er"),
    ("Mental health (daily)", "hi_mental_health"),
    ("SNF (daily)", "hi_snf"),
]


def sections_for(plan):
    cat = coverage_category(plan.plan_type)
    if cat == "part_c":
        groups = [
            {"title": "Costs", "rows": _PART_C_COSTS, "blocks": []},
            {"title": "Medical services", "rows": _PART_C_MEDICAL, "blocks": []},
            {"title": "Extras", "rows": _PART_C_EXTRAS, "blocks": ["otc", "dental"]},
        ]
        if (plan.plan_type or "").lower() == "mapd":
            groups.append({"title": "Drugs", "rows": _PART_C_DRUGS, "blocks": []})
        return groups
    if cat == "pdp":
        return [
            {"title": "Costs", "rows": _PDP_ROWS, "blocks": []},
            {"title": "Drugs", "rows": _PDP_DRUGS, "blocks": []},
        ]
    if cat == "medigap":
        return [{"title": "Plan", "rows": _MEDIGAP_ROWS, "blocks": ["medigap_grid"]}]
    if cat == "dvh":
        return [{"title": "Benefits", "rows": _DVH_ROWS, "blocks": ["dental"]}]
    if cat == "hospital_indemnity":
        return [{"title": "Base benefits", "rows": _HI_BASE, "blocks": ["hi_riders"]}]
    return [{"title": "Details", "rows": [], "blocks": []}]


_OOP_CAP = {2025: "$2,000", 2026: "$2,100", 2027: "$2,400"}


def oop_cap_for_year(year):
    return _OOP_CAP.get(year)


# Static CMS Medigap standardized benefit grid. Fixed data — same all carriers, all
# years. "Yes"/"No"/"50%"/"75%"/"100%" per the medicare.gov compare-plan-benefits chart.
_B = ["Part A coinsurance & hospital (365 days)", "Part B coinsurance/copay",
      "Blood (first 3 pints)", "Part A hospice coinsurance",
      "Skilled nursing facility coinsurance", "Part A deductible",
      "Part B deductible", "Part B excess charges", "Foreign travel emergency"]
MEDIGAP_GRID = {
    "A": ["Yes", "Yes", "Yes", "Yes", "No", "No", "No", "No", "No"],
    "B": ["Yes", "Yes", "Yes", "Yes", "No", "Yes", "No", "No", "No"],
    "C": ["Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "No", "80%"],
    "D": ["Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "No", "No", "80%"],
    "F": ["Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "80%"],
    "G": ["Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "No", "Yes", "80%"],
    "K": ["Yes", "50%", "50%", "50%", "50%", "50%", "No", "No", "No"],
    "L": ["Yes", "75%", "75%", "75%", "75%", "75%", "No", "No", "No"],
    "M": ["Yes", "Yes", "Yes", "Yes", "Yes", "50%", "No", "No", "80%"],
    "N": ["Yes", "Yes*", "Yes", "Yes", "Yes", "Yes", "No", "No", "80%"],
}


def medigap_coverage(letter):
    row = MEDIGAP_GRID.get((letter or "").upper())
    if not row:
        return []
    return list(zip(_B, row))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_plan_sections.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add app/plan_sections.py tests/test_plan_sections.py
git commit -m "feat: per-plan-type section config + medigap grid + oop-cap helper"
```

---

### Task 2: Route passes section config + derived values to the template

**Files:**
- Modify: `app/carriers.py` (the `plan_detail` route, ~line 228-264; add new keys to `BENEFIT_KEYS` ~line 73)
- Test: `tests/test_plan_detail_route.py`

**Interfaces:**
- Consumes: `app.plan_sections.sections_for`, `coverage_category`, `oop_cap_for_year`, `medigap_coverage`.
- Produces: `plan_detail` now passes to the template: `sections` (from `sections_for(plan)`), `category` (`coverage_category`), `oop_cap` (`oop_cap_for_year(plan.year)`), `medigap_rows` (`medigap_coverage(plan.plan_letter)`), and merges real Plan columns into the `details` dict under the keys the config expects (`monthly_premium`, `annual_oopm`, `pcp_copay`, `specialist_copay`, `er_copay`, `drug_tier1..5`, `drug_deductible`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_detail_route.py
import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, User, Plan


@pytest.fixture
def ctx():
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False, WTF_CSRF_ENABLED=False,
                      LOGIN_DISABLED=True)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(email="a@foundersinsuranceagency.com", name="A", is_admin=True,
                 agency_id=ag.id, role="admin")
        db.session.add(u); db.session.flush()
        p = Plan(agency_id=ag.id, carrier="Humana", cms_plan_id="H1036-335",
                 year=2026, plan_name="Gold Plus HMO", plan_type="mapd",
                 status="current", monthly_premium=0.0, pcp_copay="$0")
        db.session.add(p); db.session.commit()
        with app.test_request_context():
            from flask_login import login_user
            login_user(u)
        yield app, ag.id, u.id, p.id
        db.session.remove(); db.drop_all()


def test_plan_detail_passes_sections(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    # bypass login_required + current_user by using LOGIN_DISABLED + a stub user
    client = app.test_client()
    # inject current_user via a request context is complex; instead call the view fn
    from app import carriers
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        # render_template is exercised; assert it returns 200-ish HTML containing the CMS id
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp
    assert "H1036-335" in html
    assert "Costs" in html            # Part C group rendered
    assert "Drug" in html             # MAPD drugs group present
```

Note: if driving the view function directly proves awkward with login, use the app test client with `LOGIN_DISABLED=True` and a `@app.before_request` shim that sets `flask_login.current_user`; keep the assertions (200 status, `H1036-335`, `Costs`, `Drug` in body).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_plan_detail_route.py -q`
Expected: FAIL (template has no "Costs" group yet / route doesn't pass `sections`)

- [ ] **Step 3: Add new BENEFIT_KEYS + wire the route**

In `app/carriers.py`, extend `BENEFIT_KEYS` (the list feeding the admin form + details_json) with the new keys the config references:

```python
# add to BENEFIT_KEYS (keep existing entries):
    "medical_deductible",
    "part_b_giveback",
    "outpatient_hospital",
    "imaging",
    "therapy",
    "ambulance_ground", "ambulance_air",
    "otc_usage", "otc_retailers",          # OTC structured extras (amount stays otc_allowance)
    "dental_deductible",
    "dental_prev_innet", "dental_prev_oon",
    "dental_basic_innet", "dental_basic_oon",
    "dental_major_innet", "dental_major_oon",
    "annual_max", "dvh_deductible", "waiting_periods",
    "preferred_pharmacy_note",
    "household_discount", "rate_type",
    "hi_hospital_confinement", "hi_max_days", "hi_observation",
    "hi_er", "hi_mental_health", "hi_snf", "hi_riders",
    "vision_allowance", "hearing_allowance",
```

In the `plan_detail` route, after `details = _parse_details(plan.details_json)` and before `render_template`, merge Plan columns into `details` for the keys the config reads directly, and compute the section context:

```python
    from app.plan_sections import (sections_for, coverage_category,
                                   oop_cap_for_year, medigap_coverage)

    # Surface real Plan columns under the keys the section config expects, WITHOUT
    # clobbering anything already set in details_json (details_json wins if present).
    _col_display = {
        "monthly_premium": (f"${plan.monthly_premium:,.2f}"
                            if plan.monthly_premium is not None else None),
        "annual_oopm": (f"${plan.annual_oopm:,.0f}" if plan.annual_oopm else None),
        "pcp_copay": plan.pcp_copay, "specialist_copay": plan.specialist_copay,
        "er_copay": plan.er_copay,
        "drug_tier1": plan.drug_tier1, "drug_tier2": plan.drug_tier2,
        "drug_tier3": plan.drug_tier3, "drug_tier4": plan.drug_tier4,
        "drug_tier5": plan.drug_tier5,
    }
    for k, v in _col_display.items():
        if not details.get(k) and v:
            details[k] = v

    category = coverage_category(plan.plan_type)
    sections = sections_for(plan)
    oop_cap = oop_cap_for_year(plan.year)
    medigap_rows = medigap_coverage(getattr(plan, "plan_letter", None))
```

Add these to the `render_template("plan_detail.html", ...)` call:

```python
        sections=sections, category=category, oop_cap=oop_cap,
        medigap_rows=medigap_rows,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_plan_detail_route.py -q`
Expected: PASS (after Task 3 the template renders "Costs"/"Drug"; if running Task 2 before 3, relax to assert status 200 + `H1036-335`, then re-assert groups after Task 3)

- [ ] **Step 5: Commit**

```bash
git add app/carriers.py tests/test_plan_detail_route.py
git commit -m "feat: plan_detail passes per-type section config + derived values"
```

---

### Task 3: Rewrite `plan_detail.html` — type-aware benefit sheet + mini-block macros

**Files:**
- Modify: `app/templates/plan_detail.html` (replace the generic detail-grid + Medical Benefits blocks with the config-driven sheet; keep the header + member-count + lifecycle chain + move commission/aliases/IDs into a collapsed admin footer)

**Interfaces:**
- Consumes (from Task 2): `plan`, `member_count`, `members_truncated`, `row_cap`, `customers_on_plan`, `details` (flat dict), `sections`, `category`, `oop_cap`, `medigap_rows`, `predecessors`.

- [ ] **Step 1: Add mini-block macros at the top of the template**

Below `{% block content %}`, define reusable macros:

```jinja
{% macro benefit_row(label, key, details) %}
  {% set v = details.get(key) %}
  {% if v %}
  <div class="kv-row"><span class="kv-label">{{ label }}</span><span class="kv-value">{{ v }}</span></div>
  {% endif %}
{% endmacro %}

{% macro otc_block(details) %}
  {% set amt = details.get('otc_allowance') %}
  {% if amt %}
  <div class="benefit-block">
    <div class="bb-title">OTC / flex card</div>
    <div class="bb-body">
      <span class="bb-amount">{{ amt }}</span>
      {% if details.get('otc_usage') %}<span class="bb-tag">{{ details.get('otc_usage') }}</span>{% endif %}
      {% if details.get('otc_retailers') %}<span class="bb-note">{{ details.get('otc_retailers') }}</span>{% endif %}
    </div>
  </div>
  {% endif %}
{% endmacro %}

{% macro dental_block(details) %}
  {% set has = details.get('dental_prev_innet') or details.get('dental_major_innet') or details.get('dental_allowance') %}
  {% if has %}
  <div class="benefit-block">
    <div class="bb-title">Dental{% if details.get('dental_deductible') %} · deductible {{ details.get('dental_deductible') }}{% endif %}</div>
    <table class="bb-matrix">
      <tr><th></th><th>In-network</th><th>Out-of-network</th></tr>
      <tr><td>Preventive</td><td>{{ details.get('dental_prev_innet') or '—' }}</td><td>{{ details.get('dental_prev_oon') or '—' }}</td></tr>
      <tr><td>Basic</td><td>{{ details.get('dental_basic_innet') or '—' }}</td><td>{{ details.get('dental_basic_oon') or '—' }}</td></tr>
      <tr><td>Major</td><td>{{ details.get('dental_major_innet') or '—' }}</td><td>{{ details.get('dental_major_oon') or '—' }}</td></tr>
    </table>
    {% if details.get('dental_note') %}<div class="bb-note">{{ details.get('dental_note') }}</div>{% endif %}
  </div>
  {% endif %}
{% endmacro %}

{% macro medigap_block(medigap_rows) %}
  {% if medigap_rows %}
  <div class="benefit-block">
    <div class="bb-title">What this plan covers</div>
    <table class="bb-matrix">
      {% for benefit, cov in medigap_rows %}
      <tr><td>{{ benefit }}</td><td style="text-align:right">{{ cov }}</td></tr>
      {% endfor %}
    </table>
  </div>
  {% endif %}
{% endmacro %}

{% macro hi_riders_block(details) %}
  {% if details.get('hi_riders') %}
  <div class="benefit-block">
    <div class="bb-title">Riders (added)</div>
    <div class="bb-note">{{ details.get('hi_riders') }}</div>
  </div>
  {% endif %}
{% endmacro %}
```

- [ ] **Step 2: Replace the benefit body with the config-driven sheet**

Remove the old `<div class="detail-grid">` (Plan details / Benefits snapshot / Commission details) and the hardcoded "Medical Benefits" SOB block. Replace with:

```jinja
{# Age-rated note for Medigap/DVH #}
{% if category in ('medigap', 'dvh') %}
  <div class="detail-card" style="margin-bottom:16px">
    <div class="kv-row"><span class="kv-label">Monthly premium</span><span class="kv-value">Age-rated (per quote)</span></div>
  </div>
{% endif %}

{% for group in sections %}
<div class="detail-card" style="margin-bottom:16px">
  <h3>{{ group.title }}</h3>
  {% for label, key in group.rows %}
    {{ benefit_row(label, key, details) }}
  {% endfor %}
  {% if 'otc' in group.blocks %}{{ otc_block(details) }}{% endif %}
  {% if 'dental' in group.blocks %}{{ dental_block(details) }}{% endif %}
  {% if 'medigap_grid' in group.blocks %}{{ medigap_block(medigap_rows) }}{% endif %}
  {% if 'hi_riders' in group.blocks %}{{ hi_riders_block(details) }}{% endif %}
  {% if group.title in ('Drugs',) and oop_cap %}
    <div class="kv-row"><span class="kv-label">Annual OOP cap ({{ plan.year }})</span><span class="kv-value">{{ oop_cap }}</span></div>
  {% endif %}
</div>
{% endfor %}
```

- [ ] **Step 3: Move commission + technical fields into a collapsed admin footer**

After the sections loop, add (admin-only):

```jinja
{% if current_user.is_admin %}
<details class="detail-card" style="margin-bottom:16px">
  <summary style="cursor:pointer;font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--slate)">Admin &amp; commission details</summary>
  <div style="margin-top:12px">
    <div class="kv-row"><span class="kv-label">Commission type</span><span class="kv-value">{{ {"pmpm":"Per Member Per Month","percent_premium":"% of Premium","flat_annual":"Flat Annual"}.get(plan.comm_type, plan.comm_type) }}</span></div>
    <div class="kv-row"><span class="kv-label">Initial</span><span class="kv-value">{% if plan.comm_initial %}${{ "%.2f"|format(plan.comm_initial) }}{% else %}—{% endif %}</span></div>
    <div class="kv-row"><span class="kv-label">Renewal</span><span class="kv-value">{% if plan.comm_renewal %}${{ "%.2f"|format(plan.comm_renewal) }}{% else %}—{% endif %}</span></div>
    {% if plan.external_id %}<div class="kv-row"><span class="kv-label">External ID</span><span class="kv-value" style="font-family:monospace;font-size:11px">{{ plan.external_id }}</span></div>{% endif %}
    {% if plan.plan_name_aliases %}<div class="kv-row"><span class="kv-label">BOB aliases</span><span class="kv-value" style="font-size:11px">{{ plan.plan_name_aliases }}</span></div>{% endif %}
    <div class="kv-row"><span class="kv-label">Service area</span><span class="kv-value">{{ plan.service_area or '—' }}</span></div>
    {% if current_user.is_admin %}<div style="margin-top:10px"><a href="{{ url_for('carriers.plan_edit', plan_id=plan.id) }}" class="btn-secondary" style="font-size:11px">Edit plan / benefits</a></div>{% endif %}
  </div>
</details>
{% endif %}
```

- [ ] **Step 4: Add the mini-block CSS to the `{% block styles %}` section**

```css
.benefit-block { margin-top:10px; padding:10px 12px; background:var(--surface-low); border:1px solid var(--border); border-radius:10px; }
.bb-title { font-size:12px; font-weight:700; color:var(--ivory-bright); margin-bottom:6px; }
.bb-body { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.bb-amount { font-size:15px; font-weight:800; color:var(--gold); }
.bb-tag { font-size:11px; font-weight:700; padding:2px 8px; border-radius:10px; background:color-mix(in srgb, var(--green) 16%, transparent); color:var(--green); }
.bb-note { font-size:11px; color:var(--slate); }
.bb-matrix { width:100%; border-collapse:collapse; font-size:12px; margin-top:4px; }
.bb-matrix th { text-align:right; font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:var(--slate); padding:2px 6px; }
.bb-matrix th:first-child { text-align:left; }
.bb-matrix td { padding:3px 6px; border-top:1px solid var(--border); color:var(--ivory); }
.bb-matrix td:not(:first-child) { text-align:right; font-variant-numeric:tabular-nums; }
```

- [ ] **Step 5: Run the route test + full suite**

Run: `python3 -m pytest tests/test_plan_detail_route.py -q && python3 -m pytest -q`
Expected: PASS (route test green; full suite still 607+ passing)

- [ ] **Step 6: Commit**

```bash
git add app/templates/plan_detail.html
git commit -m "feat: type-aware condensed-SOB plan_detail template + benefit mini-blocks"
```

---

### Task 4: Add the new benefit fields to the admin edit form (`plan_form.html`)

**Files:**
- Modify: `app/templates/plan_form.html` (add inputs for the new keys so agents/admins can fill them; grouped by section)
- Verify: `app/carriers.py` `plan_edit`/`plan_new` already serialize `BENEFIT_KEYS` from the form into details_json — confirm the new keys are picked up (they are, because Task 2 added them to `BENEFIT_KEYS` and the form serializer loops that list).

**Interfaces:**
- Consumes: `BENEFIT_KEYS` (extended in Task 2). The form serializer in `app/carriers.py` reads `request.form.get(k)` for each `k in BENEFIT_KEYS`.

- [ ] **Step 1: Confirm the serializer loops BENEFIT_KEYS**

Run: `grep -n "BENEFIT_KEYS" app/carriers.py`
Expected: a loop like `for k in BENEFIT_KEYS: ... request.form.get(k)` in the save path. If the form saves via an explicit field list instead, add the new keys there. (Read the save block; wire whichever pattern exists.)

- [ ] **Step 2: Add grouped inputs to plan_form.html**

Add a "Structured benefits (snapshot page)" fieldset with text inputs named exactly as the new keys, e.g.:

```html
<fieldset>
  <legend>Snapshot benefits (optional; shown on the plan page by type)</legend>
  <label>OTC usage <input name="otc_usage" value="{{ details.get('otc_usage','') }}" placeholder="online only / in-store (CVS)"></label>
  <label>OTC retailers <input name="otc_retailers" value="{{ details.get('otc_retailers','') }}"></label>
  <label>Dental deductible <input name="dental_deductible" value="{{ details.get('dental_deductible','') }}"></label>
  <label>Dental preventive (in-net) <input name="dental_prev_innet" value="{{ details.get('dental_prev_innet','') }}" placeholder="100%"></label>
  <label>Dental preventive (OON) <input name="dental_prev_oon" value="{{ details.get('dental_prev_oon','') }}"></label>
  <label>Dental basic (in-net) <input name="dental_basic_innet" value="{{ details.get('dental_basic_innet','') }}"></label>
  <label>Dental basic (OON) <input name="dental_basic_oon" value="{{ details.get('dental_basic_oon','') }}"></label>
  <label>Dental major (in-net) <input name="dental_major_innet" value="{{ details.get('dental_major_innet','') }}" placeholder="50%"></label>
  <label>Dental major (OON) <input name="dental_major_oon" value="{{ details.get('dental_major_oon','') }}"></label>
  <label>Medical deductible <input name="medical_deductible" value="{{ details.get('medical_deductible','') }}"></label>
  <label>Part-B giveback <input name="part_b_giveback" value="{{ details.get('part_b_giveback','') }}"></label>
  <label>Outpatient hospital <input name="outpatient_hospital" value="{{ details.get('outpatient_hospital','') }}"></label>
  <label>Imaging (X-ray/MRI/CT) <input name="imaging" value="{{ details.get('imaging','') }}"></label>
  <label>Therapy (PT/OT/ST) <input name="therapy" value="{{ details.get('therapy','') }}"></label>
  <label>Ambulance ground <input name="ambulance_ground" value="{{ details.get('ambulance_ground','') }}"></label>
  <label>Ambulance air <input name="ambulance_air" value="{{ details.get('ambulance_air','') }}"></label>
  <label>Vision allowance <input name="vision_allowance" value="{{ details.get('vision_allowance','') }}"></label>
  <label>Hearing allowance <input name="hearing_allowance" value="{{ details.get('hearing_allowance','') }}"></label>
  <label>Preferred pharmacy note <input name="preferred_pharmacy_note" value="{{ details.get('preferred_pharmacy_note','') }}"></label>
  <label>Annual max (DVH) <input name="annual_max" value="{{ details.get('annual_max','') }}"></label>
  <label>DVH deductible <input name="dvh_deductible" value="{{ details.get('dvh_deductible','') }}"></label>
  <label>Waiting periods <input name="waiting_periods" value="{{ details.get('waiting_periods','') }}"></label>
  <label>Household discount (Medigap) <input name="household_discount" value="{{ details.get('household_discount','') }}"></label>
  <label>Rate type (Medigap) <input name="rate_type" value="{{ details.get('rate_type','') }}" placeholder="attained-age"></label>
  <label>HI hospital confinement (daily) <input name="hi_hospital_confinement" value="{{ details.get('hi_hospital_confinement','') }}"></label>
  <label>HI max days <input name="hi_max_days" value="{{ details.get('hi_max_days','') }}"></label>
  <label>HI observation <input name="hi_observation" value="{{ details.get('hi_observation','') }}"></label>
  <label>HI ER (injury) <input name="hi_er" value="{{ details.get('hi_er','') }}"></label>
  <label>HI mental health (daily) <input name="hi_mental_health" value="{{ details.get('hi_mental_health','') }}"></label>
  <label>HI SNF (daily) <input name="hi_snf" value="{{ details.get('hi_snf','') }}"></label>
  <label>HI riders (added) <input name="hi_riders" value="{{ details.get('hi_riders','') }}" placeholder="Ambulance $200; Cancer $10,000"></label>
</fieldset>
```

Ensure the form's route provides `details = _parse_details(plan.details_json)` to the template (it already does for edit; confirm `plan_new` passes an empty `details={}`).

- [ ] **Step 3: Manual round-trip test (write a test)**

```python
# add to tests/test_plan_detail_route.py
def test_new_benefit_keys_are_saved(ctx):
    app, agency_id, uid, pid = ctx
    from app.carriers import BENEFIT_KEYS
    for k in ["otc_usage", "dental_major_innet", "hi_riders", "annual_max",
              "imaging", "therapy", "ambulance_air", "part_b_giveback"]:
        assert k in BENEFIT_KEYS
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_plan_detail_route.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/templates/plan_form.html tests/test_plan_detail_route.py
git commit -m "feat: admin form inputs for the new snapshot benefit fields"
```

---

### Task 5: Visual verification + deploy

**Files:** none (verification + deploy)

- [ ] **Step 1: Headless-render each plan type**

Render `plan_detail.html` for one plan of each type (mapd, ma, pdp, medigap, dvh, gtl) with representative `details`, and screenshot in light + dark (reuse the render-to-standalone-HTML + local http.server + Playwright pattern used for the carriers-list redesign). Confirm: only relevant groups show, no empty "—" spam, OTC/Dental mini-blocks render, Medigap grid renders, DVH/Medigap show "Age-rated (per quote)", admin footer collapses.

- [ ] **Step 2: Full suite green**

Run: `python3 -m pytest -q`
Expected: 607+ passing.

- [ ] **Step 3: Commit any tweaks, then deploy**

```bash
git add -A && git commit -m "polish: plan snapshot per-type visual tweaks"
git push origin main
# VPS (no migration — details_json only):
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100 \
  'cd /var/www/founders-portal && git pull && systemctl restart founders-portal && sleep 3 && systemctl is-active founders-portal'
```

- [ ] **Step 4: Live-verify** login 200 + open one plan of each type on prod; confirm the page renders correctly per type.

---

## Notes for the executor
- **No DB migration** — every new benefit field lives in `Plan.details_json` (a `Text` column that already exists). Migration head stays 036.
- **Don't touch** the member-count logic, the commission math, or any money path — this is benefit-display metadata only.
- **HI riders** ship as a single free-text `hi_riders` field this pass (agent types "Ambulance $200; Cancer $10,000"). A structured rider-catalog picker (per the spec's seed list) is a follow-up enhancement — do not build it now (YAGNI).
- **Part C benefit backfill from CMS PBP files** (`pbp-benefits-2026/`) is the optional spec phase 6 — NOT in this plan. Ship the page + manual entry first.
