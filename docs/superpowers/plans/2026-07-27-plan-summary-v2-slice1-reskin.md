# Plan-Summary v2 — Slice 1 (Re-skin + Consumer/Pro toggle + Agent Quick-Info) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-skin the plan-detail page (`/carriers/<id>`) to the Gemini mockup look — type-adaptive KPI cards for all 5 plan types (no N/A), a Consumer/Pro view toggle (both rendered server-side, JS show/hide + localStorage), re-styled benefit sections, a gradient Top-Extra-Benefits card, and an Agent Quick-Info Pro panel showing commission at the **viewing agent's own** split — all from existing `Plan.details_json` + `plan_sections.py`, no migration.

**Architecture:** Add a pure per-type KPI config + helpers to `app/plan_sections.py` (alongside `sections_for`). The `plan_detail` route in `app/carriers.py` computes the viewing agent's split (their `AgentCarrierContract.split_rate` for the plan's carrier, falling back to `0.55`), the Agent-Quick-Info commission numbers, and passes both a `kpis` list and a `quick_info` dict to the template. `plan_detail.html` is re-skinned into two server-rendered wrappers (`.consumer-view` / `.pro-view`); a small vanilla-JS toggle shows one and persists the choice to `localStorage['fp-plan-view']`. The Agent Quick-Info panel is rendered into the DOM **only when `current_user` is an agent/admin** (it always is in this portal — the gate is `is_agent_context`, true for any logged-in user) and **only inside** `.pro-view`, so a customer-facing Consumer screen never shows commission.

**Tech Stack:** Flask 3.0, Jinja2, vanilla JS, Founders theme CSS tokens (`base.html :root`). Tests: pytest (SQLite in-memory, matching `tests/test_plan_detail_route.py` + `tests/test_plan_sections.py`).

## Global Constraints

- **No migration, no new data model.** Everything renders from existing `Plan` columns + `Plan.details_json` (via the route's existing `details` dict) + `plan_sections.py`. — copied from spec.
- **No N/A cards.** Each of the 5 types (`part_c` = MA + MAPD, `pdp`, `medigap`, `dvh`, `hospital_indemnity`) gets its own KPI set; a KPI whose value is missing is **omitted**, never shown as "N/A" or "—". — spec Section 2.
- **No fabricated data.** KPI/benefit values come only from `details`/`Plan` columns. The Part-B premium is the single labeled constant `PART_B_PREMIUM_2026 = 185.00` in `plan_sections.py` (rendered "+ $185.00/mo Part B (2026)"), NOT stored per-plan, NOT invented. — spec Section 2.
- **Commission = the viewing agent's own rate.** Split is `AgentCarrierContract.split_rate` for `agent_id=current_user.id, carrier=plan.carrier`, fallback `0.55`. Two agents see two numbers; no other agent's numbers ever appear. — spec Section 4.
- **Role gate:** the Agent Quick-Info panel (commission) is rendered into the DOM **only for a logged-in agent/admin** and **only inside `.pro-view`** — never in the customer-facing Consumer source. — spec Sections 1 & 4.
- **Consumer is the default view.** `localStorage['fp-plan-view']` persists the choice; JS applies the saved choice on load. — spec Section 1.
- **Founders theme tokens only** (`--surface`, `--gold` [=blue], `--green`, `--ivory`, `--slate`, `--border`, `--radius`; light + dark). Translate the mockup's blue/slate to these tokens. Text color is `var(--ivory)`/`var(--slate)`, never `var(--ink)`. — spec Section 3 + CLAUDE.md color rules.
- **The visual IS the deliverable:** headless-browser screenshot verification (light + dark) + opus whole-branch review before deploy. — spec Section 5.

---

### Task 1: Per-type KPI config + Part-B constant in `plan_sections.py`

Add a pure function `kpis_for(plan, details)` returning the ordered list of headline KPI cards for that plan's type, plus the `PART_B_PREMIUM_2026` constant and a Top-Extra-Benefits collector. This is pure Python (no Flask), fully unit-testable like the existing `sections_for`.

**Files:**
- Modify: `app/plan_sections.py` (add constant + `kpis_for` + `top_extra_benefits` below the existing config, before `sections_for` or after — keep `sections_for`/`medigap_coverage` untouched)
- Test: `tests/test_plan_sections.py` (add cases)

**Interfaces:**
- Consumes: nothing new (reads `plan.plan_type`, `plan.year`, and a `details` dict already assembled by the route).
- Produces:
  - `PART_B_PREMIUM_2026: float = 185.00`
  - `kpis_for(plan, details) -> list[dict]` where each dict is
    `{"label": str, "value": str, "kind": "plain"|"premium"|"gradient", "note": str|None, "items": list[str]|None}`.
    `kind="gradient"` is the single Top-Extra-Benefits card (Part C only) whose `items` is a list of benefit strings; `kind="premium"` carries the Part-B `note`; `kind="plain"` is a simple label/value card. **A KPI whose value would be empty is omitted** (Part-B premium note is only added to the premium card; the premium card itself is only emitted if a premium value exists — for `$0.00` premiums the value IS present so the card shows "$0.00").
  - `top_extra_benefits(details) -> list[str]` — the OTC / Dental / Eyewear lines for the gradient card, each omitted when its source key is empty.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_plan_sections.py`:

```python
from app.plan_sections import kpis_for, top_extra_benefits, PART_B_PREMIUM_2026


def _plan(plan_type, year=2026, plan_letter=None):
    return _Plan(plan_type, year=year, plan_letter=plan_letter)


def test_part_b_constant_present():
    assert PART_B_PREMIUM_2026 == 185.00


def test_top_extra_benefits_omits_missing():
    d = {"otc_allowance": "$45/quarter", "dental_allowance": "$2,000",
         "vision_allowance": None}
    items = top_extra_benefits(d)
    assert any("$45/quarter" in i for i in items)
    assert any("$2,000" in i for i in items)
    assert all("None" not in i for i in items)          # no None leakage
    assert len(items) == 2                                # eyewear omitted


def test_kpis_part_c_mapd_has_premium_moop_gradient():
    d = {"monthly_premium": "$0.00", "annual_oopm": "$4,500",
         "otc_allowance": "$45/quarter"}
    kinds = [k["kind"] for k in kpis_for(_plan("mapd"), d)]
    assert "premium" in kinds
    assert "gradient" in kinds                            # Top Extra Benefits card
    prem = [k for k in kpis_for(_plan("mapd"), d) if k["kind"] == "premium"][0]
    assert "185.00" in (prem["note"] or "")              # Part-B transparency note
    assert prem["value"] == "$0.00"                       # $0 premium still shows


def test_kpis_omit_missing_no_na_cards():
    # A Part C plan with NO oopm value must not emit a MOOP card at all
    d = {"monthly_premium": "$12.00"}
    labels = [k["label"] for k in kpis_for(_plan("mapd"), d)]
    assert not any("out-of-pocket" in l.lower() for l in labels)
    assert all(k["value"] for k in kpis_for(_plan("mapd"), d))  # never empty


def test_kpis_pdp_has_premium_and_rx_deductible():
    d = {"monthly_premium": "$8.00", "drug_deductible": "$545"}
    labels = [k["label"].lower() for k in kpis_for(_plan("pdp"), d)]
    assert any("premium" in l for l in labels)
    assert any("deductible" in l for l in labels)
    # PDP gets no gradient Top-Extra-Benefits card
    assert all(k["kind"] != "gradient" for k in kpis_for(_plan("pdp"), d))


def test_kpis_medigap_premium_is_age_rated_note():
    d = {}
    kpis = kpis_for(_plan("medigap", plan_letter="G"), d)
    prem = [k for k in kpis if "premium" in k["label"].lower()][0]
    assert "age-rated" in (prem["value"] + (prem["note"] or "")).lower()


def test_kpis_dvh_has_annual_max_when_present_else_omitted():
    with_max = kpis_for(_plan("dvh"), {"annual_max": "$3,000"})
    assert any("annual" in k["label"].lower() for k in with_max)
    without = kpis_for(_plan("dvh"), {})
    assert without == [] or all(k["value"] for k in without)


def test_kpis_hospital_indemnity_base_benefit():
    d = {"hi_hospital_confinement": "$300/day"}
    kpis = kpis_for(_plan("gtl"), d)
    assert any("$300/day" in k["value"] for k in kpis)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_plan_sections.py -q`
Expected: FAIL — `ImportError: cannot import name 'kpis_for'` (and the other new names).

- [ ] **Step 3: Implement the KPI config**

Append to `app/plan_sections.py` (after `_HI_BASE`, before or after `sections_for` — placement doesn't matter, keep existing code intact):

```python
# Single labeled constant — the standard Medicare Part B premium for the year.
# NOT stored per-plan, NOT invented. Update yearly.
PART_B_PREMIUM_2026 = 185.00


def top_extra_benefits(details):
    """The OTC / Dental / Eyewear lines for the Part C gradient card.
    Each line is omitted when its source value is empty — no fabricated rows."""
    out = []
    otc = details.get("otc_allowance")
    if otc:
        out.append(f"{otc} OTC credit")
    dental = details.get("dental_allowance")
    if dental:
        out.append(f"{dental} Dental allowance")
    vision = details.get("vision_allowance")
    if vision:
        out.append(f"{vision} Eyewear allowance")
    return out


def _card(label, value, kind="plain", note=None, items=None):
    return {"label": label, "value": value, "kind": kind, "note": note,
            "items": items}


def kpis_for(plan, details):
    """Ordered headline KPI cards for this plan's type. A card whose value is
    missing is OMITTED (never rendered as N/A). See spec Section 2."""
    cat = coverage_category(plan.plan_type)
    kpis = []

    if cat == "part_c":
        premium = details.get("monthly_premium")
        if premium:
            note = f"+ ${PART_B_PREMIUM_2026:,.2f}/mo Part B ({plan.year})"
            kpis.append(_card("Monthly premium", premium, kind="premium", note=note))
        moop = details.get("annual_oopm")
        if moop:
            kpis.append(_card("Annual out-of-pocket max", moop))
        extras = top_extra_benefits(details)
        if extras:
            kpis.append(_card("Top extra benefits", "", kind="gradient", items=extras))
        return kpis

    if cat == "pdp":
        premium = details.get("monthly_premium")
        if premium:
            kpis.append(_card("Monthly premium", premium))
        ded = details.get("drug_deductible")
        if ded:
            kpis.append(_card("Annual Rx deductible", ded))
        return kpis

    if cat == "medigap":
        # Medigap is age-rated — there is no single stored premium.
        kpis.append(_card("Monthly premium", "Age-rated",
                          note="See quote — premium depends on age"))
        return kpis

    if cat == "dvh":
        amax = details.get("annual_max")
        if amax:
            kpis.append(_card("Annual benefit max", amax))
        ded = details.get("dvh_deductible")
        if ded:
            kpis.append(_card("Deductible", ded))
        return kpis

    if cat == "hospital_indemnity":
        base = details.get("hi_hospital_confinement")
        if base:
            kpis.append(_card("Hospital confinement (daily)", base))
        days = details.get("hi_max_days")
        if days:
            kpis.append(_card("Max benefit period", f"{days} days"))
        return kpis

    return kpis
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_plan_sections.py -q`
Expected: PASS (all new + existing tests).

- [ ] **Step 5: Commit**

```bash
git add app/plan_sections.py tests/test_plan_sections.py
git commit -m "feat: per-type KPI config + Part-B constant for plan-summary v2 slice 1"
```

---

### Task 2: Route passes KPIs, viewing-agent split, and Agent Quick-Info to the template

The `plan_detail` route computes the viewing agent's split for the plan's carrier, derives the Agent-Quick-Info commission numbers, builds the `kpis` list via `kpis_for`, and passes them (plus an `is_agent_context` flag) to the template. Split lookup: `AgentCarrierContract.split_rate` for `agent_id=current_user.id, carrier=plan.carrier`; fallback `0.55`.

**Files:**
- Modify: `app/carriers.py` — `plan_detail` (route body, currently ends at the `render_template("plan_detail.html", ...)` call around lines 288–355)
- Test: `tests/test_plan_detail_route.py` (add cases)

**Interfaces:**
- Consumes: `kpis_for` from Task 1; `AgentCarrierContract` from `app.models`.
- Produces (new `render_template` context keys the template in Task 3/4 reads):
  - `kpis: list[dict]` (from `kpis_for(plan, details)`)
  - `is_agent_context: bool` (any authenticated user — True here; the DOM-gate for commission)
  - `quick_info: dict | None` — present only when `is_agent_context`; shape:
    `{"split_rate": float, "split_pct": str, "comm_initial": float|None, "comm_renewal": float|None, "hra_bonus": float|None, "agent_take_initial": float|None, "agent_take_renewal": float|None, "projected_annual": float|None}`.
    `agent_take_* = comm_* * split_rate` (None if the rate is None); `projected_annual = agent_take_renewal * 12` if `comm_type == "pmpm"` and `agent_take_renewal` is set, else None. Display-only, nothing stored.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_plan_detail_route.py`. Extend the `ctx` fixture's plan to carry commission fields, and add a helper to seed a contract:

```python
from app.models import AgentCarrierContract


def _capture_context(app, uid, pid, monkeypatch):
    from app import carriers
    captured = {}
    real = carriers.render_template

    def fake(template_name, **context):
        captured.update(context)
        return real(template_name, **context)

    monkeypatch.setattr(carriers, "render_template", fake)
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        carriers.plan_detail(pid)
    return captured


def test_route_passes_kpis_and_agent_context(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    captured = _capture_context(app, uid, pid, monkeypatch)
    assert isinstance(captured.get("kpis"), list)
    assert captured.get("is_agent_context") is True
    assert captured.get("quick_info") is not None


def test_quick_info_uses_viewing_agents_own_split(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    # Give the viewing agent a 0.525 Humana contract; plan.carrier == "Humana"
    with app.app_context():
        db.session.add(AgentCarrierContract(
            agency_id=agency_id, agent_id=uid, carrier="Humana",
            split_rate=0.525, is_active=True))
        # also set plan commission rates
        p = db.session.get(Plan, pid)
        p.comm_type = "pmpm"; p.comm_initial = 100.0; p.comm_renewal = 50.0
        p.hra_bonus = 25.0
        db.session.commit()
    captured = _capture_context(app, uid, pid, monkeypatch)
    qi = captured["quick_info"]
    assert qi["split_rate"] == 0.525
    assert round(qi["agent_take_initial"], 2) == 52.5    # 100 * 0.525
    assert round(qi["agent_take_renewal"], 2) == 26.25   # 50 * 0.525
    assert round(qi["projected_annual"], 2) == 315.0     # 26.25 * 12
    assert qi["hra_bonus"] == 25.0


def test_quick_info_falls_back_to_default_split(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    with app.app_context():
        p = db.session.get(Plan, pid)
        p.comm_initial = 100.0; p.comm_renewal = 50.0
        db.session.commit()
    # No contract row seeded → default 0.55
    captured = _capture_context(app, uid, pid, monkeypatch)
    assert captured["quick_info"]["split_rate"] == 0.55
    assert round(captured["quick_info"]["agent_take_initial"], 2) == 55.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_plan_detail_route.py -q`
Expected: FAIL — `KeyError: 'kpis'` / `quick_info` is None (route doesn't pass them yet).

- [ ] **Step 3: Implement the route changes**

In `app/carriers.py`, update the `plan_detail` function. Add the import at the top of the function's `from app.plan_sections import ...` line, then compute the new context just before `return render_template(...)`:

Change the import line (currently `from app.plan_sections import (sections_for, coverage_category, oop_cap_for_year, medigap_coverage)`) to also import `kpis_for`:

```python
    from app.plan_sections import (sections_for, coverage_category,
                                   oop_cap_for_year, medigap_coverage, kpis_for)
```

Add, after `medigap_rows = medigap_coverage(...)` and before the `return`:

```python
    kpis = kpis_for(plan, details)

    # Agent Quick-Info (Pro view) — commission at the VIEWING agent's OWN split.
    # Every portal user is an authenticated agent/admin, so is_agent_context is True;
    # the flag exists so the template can DOM-gate commission out of the Consumer view.
    is_agent_context = current_user.is_authenticated
    quick_info = None
    if is_agent_context:
        from app.models import AgentCarrierContract
        contract = (AgentCarrierContract.query
                    .filter_by(agent_id=current_user.id, carrier=plan.carrier,
                               agency_id=current_user.agency_id)
                    .first())
        split = contract.split_rate if contract else 0.55
        ci, cr = plan.comm_initial, plan.comm_renewal
        take_i = (ci * split) if ci is not None else None
        take_r = (cr * split) if cr is not None else None
        projected = (take_r * 12) if (take_r is not None
                                      and plan.comm_type == "pmpm") else None
        quick_info = {
            "split_rate": split,
            "split_pct": f"{split * 100:.1f}%".rstrip("0").rstrip("."),
            "comm_initial": ci, "comm_renewal": cr, "hra_bonus": plan.hra_bonus,
            "agent_take_initial": take_i, "agent_take_renewal": take_r,
            "projected_annual": projected,
        }
```

Then add `kpis=kpis, is_agent_context=is_agent_context, quick_info=quick_info,` to the `render_template("plan_detail.html", ...)` call's keyword args.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_plan_detail_route.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/carriers.py tests/test_plan_detail_route.py
git commit -m "feat: plan_detail passes KPIs + viewing-agent Quick-Info commission"
```

---

### Task 3: Re-skin the template — KPI cards, Consumer/Pro toggle, re-styled sections

Rebuild `plan_detail.html` into the mockup look: a Consumer/Pro toggle in the header, a type-adaptive KPI card row (including the gradient Top-Extra-Benefits card), and the existing benefit sections re-styled. Both views are rendered server-side; JS shows one. **This task does NOT render the Agent Quick-Info panel** — that is Task 4 (so a reviewer can gate each independently). The Pro wrapper exists but is empty of commission in this task.

**Files:**
- Modify: `app/templates/plan_detail.html` (styles block + content block; keep the existing macros `benefit_row`/`otc_block`/`dental_block`/`medigap_block`/`hi_riders_block`, the plan chain, the member list, and the admin edit link)
- Test: `tests/test_plan_detail_route.py` (add a render-smoke assertion)

**Interfaces:**
- Consumes: `kpis`, `is_agent_context` (Task 2); `sections`, `details`, `category`, `oop_cap`, `medigap_rows`, `plan`, `member_count`, `customers_on_plan` (existing).
- Produces: DOM with `.consumer-view` and `.pro-view` wrappers, a `[data-plan-view]` toggle, and per-KPI cards keyed by `kind`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_plan_detail_route.py`:

```python
def test_template_renders_toggle_and_kpi_and_views(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    with app.app_context():
        p = db.session.get(Plan, pid)
        p.annual_oopm = 4500.0
        # seed a details_json OTC value so the gradient card appears
        import json
        p.details_json = json.dumps({"otc_allowance": "$45/quarter"})
        db.session.commit()
    from app import carriers
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert 'data-plan-view' in html            # the toggle
    assert 'consumer-view' in html
    assert 'pro-view' in html
    assert 'fp-plan-view' in html              # localStorage key referenced in JS
    assert 'Top extra benefits' in html or 'OTC' in html  # gradient card content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest "tests/test_plan_detail_route.py::test_template_renders_toggle_and_kpi_and_views" -q`
Expected: FAIL — `assert 'data-plan-view' in html` fails (template not re-skinned yet).

- [ ] **Step 3: Add KPI + toggle CSS to the styles block**

In `app/templates/plan_detail.html`'s `{% block styles %}`, append (keep all existing styles):

```css
/* --- Plan-summary v2 slice 1 re-skin --- */
.plan-view-toggle { display:inline-flex; gap:2px; background:var(--surface-low);
  border:1px solid var(--border); border-radius:var(--radius-pill); padding:3px; }
.plan-view-toggle button { border:none; background:transparent; cursor:pointer;
  font-size:12px; font-weight:600; color:var(--slate); padding:5px 14px;
  border-radius:var(--radius-pill); transition:all .15s; }
.plan-view-toggle button.active { background:var(--surface); color:var(--gold);
  box-shadow:var(--shadow-sm); }

.kpi-row { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));
  gap:16px; margin-bottom:20px; }
.kpi-card { background:var(--surface); border:1px solid var(--border);
  border-radius:var(--radius); padding:20px 22px; display:flex; flex-direction:column;
  gap:6px; min-height:120px; }
.kpi-label { font-size:11px; font-weight:700; letter-spacing:.14em;
  text-transform:uppercase; color:var(--slate); }
.kpi-value { font-family:var(--font-serif); font-size:1.8rem; font-weight:300;
  color:var(--ivory); line-height:1.1; }
.kpi-note { font-size:11px; color:var(--slate); margin-top:auto;
  background:var(--surface-low); border:1px solid var(--border);
  border-radius:var(--radius-sm); padding:6px 8px; }
.kpi-card.gradient { background:linear-gradient(135deg, var(--gold), var(--green));
  border:none; color:#fff; }
.kpi-card.gradient .kpi-label { color:rgba(255,255,255,.85); }
.kpi-card.gradient ul { list-style:none; margin:6px 0 0; padding:0;
  display:flex; flex-direction:column; gap:8px; }
.kpi-card.gradient li { font-size:13px; font-weight:500; color:#fff;
  display:flex; align-items:center; gap:8px; }
.kpi-card.gradient li::before { content:""; width:8px; height:8px; border-radius:2px;
  background:rgba(255,255,255,.45); flex:none; }

@media (max-width: 640px) { .kpi-row { grid-template-columns:1fr; } }
```

- [ ] **Step 4: Add the toggle to the header + the KPI row + view wrappers**

In the content block: after the `<div class="page-header">...</div>` header (and the plan-lifecycle chain), replace the current single member-count card + age-rated note + `{% for group in sections %}` block with the toggle, KPI row, and two view wrappers. Add the toggle control into the header's right-side action `<div>` (next to Edit plan):

```html
    <div class="plan-view-toggle" data-plan-view>
      <button type="button" data-view="consumer" class="active">Consumer</button>
      <button type="button" data-view="pro">Pro</button>
    </div>
```

Then, where the top-stats/sections currently live, render the KPI row + wrappers:

```html
{# Type-adaptive KPI cards — no N/A card ever (route omits empties) #}
{% if kpis %}
<div class="kpi-row">
  {% for k in kpis %}
    {% if k.kind == 'gradient' %}
    <div class="kpi-card gradient">
      <span class="kpi-label">{{ k.label }}</span>
      <ul>{% for item in k['items'] %}<li>{{ item }}</li>{% endfor %}</ul>
    </div>
    {% else %}
    <div class="kpi-card">
      <span class="kpi-label">{{ k.label }}</span>
      <span class="kpi-value">{{ k.value }}</span>
      {% if k.note %}<div class="kpi-note">{{ k.note }}</div>{% endif %}
    </div>
    {% endif %}
  {% endfor %}
</div>
{% endif %}

{# Member count — the sole headline stat, kept from the prior design #}
<div class="detail-card" style="margin-bottom:16px;display:flex;align-items:baseline;gap:14px">
  <span class="member-count" style="margin:0">{{ member_count }}</span>
  <span class="member-sub">active member{{ 's' if member_count != 1 }} on this plan
    {%- if members_truncated %} · showing first {{ row_cap }}{% endif %}</span>
  {% if customers_on_plan %}
  <a href="#members" style="margin-left:auto;font-size:12px;color:var(--gold);text-decoration:none">View members ↓</a>
  {% endif %}
</div>

{# Consumer view = the customer-safe benefit sections #}
<div class="consumer-view">
  {% for group in sections %}
  <div class="detail-card" style="margin-bottom:16px">
    <h3>{{ group.title }}</h3>
    {% for label, key in group.rows %}{{ benefit_row(label, key, details) }}{% endfor %}
    {% if 'otc' in group.blocks %}{{ otc_block(details) }}{% endif %}
    {% if 'dental' in group.blocks %}{{ dental_block(details) }}{% endif %}
    {% if 'medigap_grid' in group.blocks %}{{ medigap_block(medigap_rows) }}{% endif %}
    {% if 'hi_riders' in group.blocks %}{{ hi_riders_block(details) }}{% endif %}
    {% if group.title in ('Drugs',) and oop_cap %}
      <div class="kv-row"><span class="kv-label">Annual OOP cap ({{ plan.year }})</span><span class="kv-value">{{ oop_cap }}</span></div>
    {% endif %}
  </div>
  {% endfor %}
</div>

{# Pro view = same sections + (Task 4) the Agent Quick-Info panel. Hidden by default. #}
<div class="pro-view" hidden>
  {# Agent Quick-Info panel is injected here in Task 4 #}
  {% for group in sections %}
  <div class="detail-card" style="margin-bottom:16px">
    <h3>{{ group.title }}</h3>
    {% for label, key in group.rows %}{{ benefit_row(label, key, details) }}{% endfor %}
    {% if 'otc' in group.blocks %}{{ otc_block(details) }}{% endif %}
    {% if 'dental' in group.blocks %}{{ dental_block(details) }}{% endif %}
    {% if 'medigap_grid' in group.blocks %}{{ medigap_block(medigap_rows) }}{% endif %}
    {% if 'hi_riders' in group.blocks %}{{ hi_riders_block(details) }}{% endif %}
    {% if group.title in ('Drugs',) and oop_cap %}
      <div class="kv-row"><span class="kv-label">Annual OOP cap ({{ plan.year }})</span><span class="kv-value">{{ oop_cap }}</span></div>
    {% endif %}
  </div>
  {% endfor %}
</div>
```

Remove the now-superseded `{% if category in ('medigap','dvh') %}` age-rated card (the Medigap KPI card carries the age-rated note now) and the old standalone `{% for group in sections %}` block that this replaces.

- [ ] **Step 5: Add the toggle JS at the end of the content block**

Before `{% endblock %}`, add:

```html
<script>
(function () {
  var KEY = 'fp-plan-view';
  var consumer = document.querySelector('.consumer-view');
  var pro = document.querySelector('.pro-view');
  var toggle = document.querySelector('[data-plan-view]');
  if (!consumer || !pro || !toggle) return;
  function apply(view) {
    var isPro = view === 'pro';
    consumer.hidden = isPro;
    pro.hidden = !isPro;
    toggle.querySelectorAll('button').forEach(function (b) {
      b.classList.toggle('active', b.dataset.view === view);
    });
  }
  toggle.querySelectorAll('button').forEach(function (b) {
    b.addEventListener('click', function () {
      var v = b.dataset.view;
      try { localStorage.setItem(KEY, v); } catch (e) {}
      apply(v);
    });
  });
  var saved = 'consumer';
  try { saved = localStorage.getItem(KEY) || 'consumer'; } catch (e) {}
  apply(saved);
})();
</script>
```

- [ ] **Step 6: Run the render test + full plan-detail suite**

Run: `python3 -m pytest tests/test_plan_detail_route.py -q`
Expected: PASS (new render test + all existing).

- [ ] **Step 7: Commit**

```bash
git add app/templates/plan_detail.html tests/test_plan_detail_route.py
git commit -m "feat: re-skin plan-detail — KPI cards + Consumer/Pro toggle + gradient card"
```

---

### Task 4: Agent Quick-Info commission panel (Pro view, role-gated)

Render the Agent Quick-Info panel inside `.pro-view`, **only when `is_agent_context`**. It shows commission at the viewing agent's own split from `quick_info` (Task 2). This replaces the old collapsed admin-footer as the home for commission; keep the admin edit link but drop the commission rows from that footer to avoid duplication.

**Files:**
- Modify: `app/templates/plan_detail.html` (inject the panel at the top of `.pro-view`; trim the old admin `<details>` commission rows)
- Test: `tests/test_plan_detail_route.py` (role-gate + own-rate render assertions)

**Interfaces:**
- Consumes: `quick_info`, `is_agent_context` (Task 2).
- Produces: a `.quick-info` panel present in the Pro DOM for agent context; **absent** when `is_agent_context` is false.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_plan_detail_route.py`:

```python
def test_quick_info_panel_renders_agents_own_numbers(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    with app.app_context():
        db.session.add(AgentCarrierContract(
            agency_id=agency_id, agent_id=uid, carrier="Humana",
            split_rate=0.525, is_active=True))
        p = db.session.get(Plan, pid)
        p.comm_type = "pmpm"; p.comm_initial = 100.0; p.comm_renewal = 50.0
        db.session.commit()
    from app import carriers
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert 'quick-info' in html
    assert '52.5%' in html            # the viewing agent's own split
    assert '$52.50' in html           # agent take on initial (100 * 0.525)


def test_quick_info_panel_absent_without_agent_context(ctx, monkeypatch):
    """When is_agent_context is False, the commission panel must NOT be in the DOM."""
    app, agency_id, uid, pid = ctx
    from app import carriers
    real = carriers.render_template

    def fake(template_name, **context):
        context = dict(context)
        context["is_agent_context"] = False
        context["quick_info"] = None
        return real(template_name, **context)

    monkeypatch.setattr(carriers, "render_template", fake)
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert 'quick-info' not in html   # role-gated out of the DOM entirely
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest "tests/test_plan_detail_route.py::test_quick_info_panel_renders_agents_own_numbers" "tests/test_plan_detail_route.py::test_quick_info_panel_absent_without_agent_context" -q`
Expected: FAIL — `assert 'quick-info' in html` fails (panel not rendered yet).

- [ ] **Step 3: Add Quick-Info panel CSS**

In `{% block styles %}` append:

```css
.quick-info { background:var(--surface); border:1px solid var(--gold);
  border-radius:var(--radius); padding:20px 24px; margin-bottom:16px; }
.quick-info h3 { font-size:11px; font-weight:700; letter-spacing:.16em;
  text-transform:uppercase; color:var(--gold); margin:0 0 14px; }
.qi-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px,1fr));
  gap:14px; }
.qi-cell .qi-num { font-family:var(--font-serif); font-size:1.4rem; font-weight:300;
  color:var(--ivory); line-height:1; }
.qi-cell .qi-lbl { font-size:11px; color:var(--slate); margin-top:4px; }
```

- [ ] **Step 4: Inject the panel at the top of `.pro-view`**

Replace the `{# Agent Quick-Info panel is injected here in Task 4 #}` comment in `.pro-view` with:

```html
  {% if is_agent_context and quick_info %}
  <div class="quick-info">
    <h3>Agent quick-info — your commission</h3>
    <div class="qi-grid">
      <div class="qi-cell">
        <div class="qi-num">{{ quick_info.split_pct }}</div>
        <div class="qi-lbl">Your agency split</div>
      </div>
      {% if quick_info.comm_initial is not none %}
      <div class="qi-cell">
        <div class="qi-num">${{ "%.2f"|format(quick_info.agent_take_initial) }}</div>
        <div class="qi-lbl">Your take — new (of ${{ "%.2f"|format(quick_info.comm_initial) }})</div>
      </div>
      {% endif %}
      {% if quick_info.comm_renewal is not none %}
      <div class="qi-cell">
        <div class="qi-num">${{ "%.2f"|format(quick_info.agent_take_renewal) }}</div>
        <div class="qi-lbl">Your take — renewal (of ${{ "%.2f"|format(quick_info.comm_renewal) }})</div>
      </div>
      {% endif %}
      {% if quick_info.projected_annual is not none %}
      <div class="qi-cell">
        <div class="qi-num">${{ "%.2f"|format(quick_info.projected_annual) }}</div>
        <div class="qi-lbl">Projected annual (renewal × 12)</div>
      </div>
      {% endif %}
      {% if quick_info.hra_bonus is not none %}
      <div class="qi-cell">
        <div class="qi-num">${{ "%.2f"|format(quick_info.hra_bonus) }}</div>
        <div class="qi-lbl">HRA bonus</div>
      </div>
      {% endif %}
    </div>
  </div>
  {% endif %}
```

- [ ] **Step 5: Trim the old admin footer's commission rows**

In the existing `{% if current_user.is_admin %}<details class="detail-card">...` block, remove the "Commission type / Initial / Renewal" `kv-row`s (now shown in Quick-Info) but KEEP External ID / BOB aliases / Service area / Edit link. If the resulting `<details>` would be near-empty, keep only the non-commission admin metadata rows.

- [ ] **Step 6: Run the full plan-detail suite**

Run: `python3 -m pytest tests/test_plan_detail_route.py tests/test_plan_sections.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/templates/plan_detail.html tests/test_plan_detail_route.py
git commit -m "feat: Agent Quick-Info commission panel (Pro view, role-gated, own split)"
```

---

### Task 5: Full-suite regression + headless-browser screenshot verification

Prove the whole suite is green, then render each of the 5 plan types in a real browser (light + dark) to confirm the visual — the deliverable — and confirm the toggle + role-gate behave. No new production code; this task produces the verification evidence for the opus review.

**Files:**
- No production changes (verification only). May add a throwaway seed script under the scratchpad, not committed.

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: screenshot evidence + a green full suite.

- [ ] **Step 1: Run the full test suite**

Run: `python3 -m pytest -q`
Expected: PASS — all tests (the prior baseline was 690; the new tests raise it). Record the count.

- [ ] **Step 2: Launch the app and screenshot each plan type (light + dark)**

Use the `run` skill (or the existing local dev server pattern) to serve the app against a test DB seeded with one plan of each type (`mapd`, `pdp`, `medigap`, `dvh`, `gtl`), each with representative `details_json` (OTC/dental/vision for the Part C gradient card; annual_max for DVH; hi_hospital_confinement for GTL). Then with the playwright browser tools:
  - Navigate to `/carriers/<id>` for each type.
  - Screenshot Consumer view and Pro view (click the toggle) — verify: correct KPI set per type, NO "N/A" card anywhere, the gradient Top-Extra-Benefits card on Part C, the Agent Quick-Info panel only in Pro.
  - Toggle the theme (or set `data-theme`) and re-screenshot in dark — verify legibility (no invisible text, gradient readable).
  - Confirm `localStorage['fp-plan-view']` persists across reload.

Expected: every type renders cleanly, no N/A cards, both themes legible, toggle persists, Quick-Info Pro-only.

- [ ] **Step 3: Verify the role-gate in rendered source**

Confirm (via the `test_quick_info_panel_absent_without_agent_context` test already in the suite, plus a manual view-source spot check of the Consumer view) that the string `quick-info` and any commission dollar figure do NOT appear in the Consumer-view DOM path — commission is Pro-only and agent-context-only.

- [ ] **Step 4: Commit any verification notes**

```bash
git add -A
git commit -m "test: full-suite green + headless screenshot verification for plan-summary slice 1" --allow-empty
```

---

## Self-Review

**1. Spec coverage:**
- Section 1 (Consumer/Pro toggle, server-renders-both + JS show/hide + localStorage, default Consumer, role-gate) → Task 3 (toggle + wrappers + JS) + Task 4 (role-gate). ✅
- Section 2 (type-adaptive KPI cards, all 5 types, no N/A, Part-B constant, gradient Top-Extra-Benefits) → Task 1 (`kpis_for` + `PART_B_PREMIUM_2026` + `top_extra_benefits`) + Task 3 (render). ✅
- Section 3 (re-styled benefit body, Founders tokens, member count sole stat) → Task 3. ✅ (The mockup's Days-1-6 hospitalization bar is explicitly a nice-to-have "if data present"; no such structured field exists in `details_json`, so it is omitted — consistent with "no fabricated data." Noted, not built.)
- Section 4 (Agent Quick-Info, viewing agent's own split, new/renewal/HRA/take/projected, no cross-agent leak, admin sees own/default) → Task 2 (compute) + Task 4 (render). ✅
- Section 5 (5-type render, toggle+persist, role-gate DOM-absence, light+dark, headless screenshots) → Tasks 1–4 tests + Task 5 verification. ✅
- Files (plan_sections.py, carriers.py plan_detail, plan_detail.html, CSS block) → all covered. ✅
- No migration → confirmed; nothing touches models/migrations. ✅

**2. Placeholder scan:** No "TBD/TODO/handle edge cases/similar to Task N" — every step has real code. The one `{# injected here in Task 4 #}` comment in Task 3 is a real placeholder token that Task 4 Step 4 explicitly replaces (intentional cross-task handoff, not a plan gap). ✅

**3. Type consistency:** `kpis_for(plan, details)`, `top_extra_benefits(details)`, `PART_B_PREMIUM_2026`, and the card dict shape `{label,value,kind,note,items}` are identical across Tasks 1→3. `quick_info` keys (`split_rate`, `split_pct`, `comm_initial`, `comm_renewal`, `hra_bonus`, `agent_take_initial`, `agent_take_renewal`, `projected_annual`) are identical across Tasks 2→4. `is_agent_context` used consistently. ✅
