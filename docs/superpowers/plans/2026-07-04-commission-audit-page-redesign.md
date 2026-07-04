# Commission Audit Page Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Commission Audit page layout to the approved mockup — 3 compact KPI cards, uniform carrier chips with a click-popover (agent ✓/○ + upload date), and a compact single-row upload — all lean (upload-tracking only, no earnings).

**Architecture:** Almost entirely CSS/markup in `commission.html` plus a small vanilla popover JS; ONE backend change adds an `uploaded_at` field to the existing `per_agent_upload_status` helper. The upload behavior/JS from 2026-07-03 (staging, AJAX, results) is UNCHANGED — only its container CSS is restyled.

**Tech Stack:** Flask, Jinja2, vanilla JS (no new deps), pytest.

**Spec:** `docs/superpowers/specs/2026-07-04-commission-audit-page-redesign-design.md`

## Global Constraints

- **Lean:** show ONLY upload-tracking data (what's in / when / for what / what's left). NO dollar/earnings KPI, NO "still missing" summary line.
- Text colors `var(--ivory)`/`var(--slate)`/`var(--green)`/`var(--ivory-bright)` (navy headings) — NEVER `var(--ink)` (that's the background token → invisible text).
- No `|safe` on agent names / any data; JS interpolation via `textContent`, never innerHTML-with-data.
- Admin-only page; `per_agent_upload_status` stays agency-scoped.
- Founders theme tokens (base.html): blue `--gold` (#266EA5), green `--green`, navy `--ivory-bright`, `--radius:14px`, `--radius-sm:8px`, `--slate` muted. Works light + dark via tokens; responsive (KPI cards + chips wrap; popover stays in viewport).
- Do NOT change upload/parse/ingest behavior or the 2026-07-03 staging/AJAX/results JS — only restyle its containers.
- `prefers-reduced-motion` respected on the popover (fade via a token or none; no motion that ignores the setting).
- No migration, no new deps.

---

### Task 1: `per_agent_upload_status` gains `uploaded_at` (per-agent upload date)

**Files:**
- Modify: `app/commission/recap.py` (`per_agent_upload_status`)
- Test: `tests/test_commission_upload_ux.py`

**Interfaces:**
- Consumes: `CommissionLineItem.created_at`, existing helper query.
- Produces: each agent dict gains `"uploaded_at": <datetime|None>` (max `created_at` across that agent's line items for the carrier+period; None if not uploaded). Existing keys `{agent_id, agent_name, uploaded}` unchanged.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_commission_upload_ux.py
def test_per_agent_upload_status_includes_uploaded_at(ctx):
    from datetime import date, datetime
    from app.extensions import db
    from app.models import (User, AgentCarrierContract, CommissionStatement,
                            CommissionLineItem)
    from app.commission.recap import per_agent_upload_status
    app, agency_id = ctx
    a1 = User(email="b@x.com", name="Brian Freeman", agency_id=agency_id, role="agent")
    a2 = User(email="m@x.com", name="Mike Lauzurique", agency_id=agency_id, role="agent")
    db.session.add_all([a1, a2]); db.session.flush()
    for a in (a1, a2):
        db.session.add(AgentCarrierContract(agency_id=agency_id, agent_id=a.id,
                                            carrier="BCBS", is_active=True))
    st = CommissionStatement(agency_id=agency_id, carrier="BCBS",
                             statement_date=date(2026, 6, 1), period_label="June 2026")
    db.session.add(st); db.session.flush()
    li = CommissionLineItem(agency_id=agency_id, statement_id=st.id, carrier="BCBS",
                            period_label="June 2026", agent_id=a1.id, member_name="X",
                            raw_amount=10.0, classification="agent_commission",
                            source_ref="bcbs::p1::Sheet1::1")
    db.session.add(li); db.session.commit()

    rows = per_agent_upload_status(agency_id, "BCBS", "June 2026")
    by_name = {r["agent_name"]: r for r in rows}
    assert by_name["Brian Freeman"]["uploaded"] is True
    # uploaded_at is an ISO string (not a datetime) so the template can embed it in
    # JSON and the JS new Date() parse is reliable cross-browser.
    assert isinstance(by_name["Brian Freeman"]["uploaded_at"], str)
    assert "2026-" in by_name["Brian Freeman"]["uploaded_at"]
    assert by_name["Mike Lauzurique"]["uploaded"] is False
    assert by_name["Mike Lauzurique"]["uploaded_at"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_upload_ux.py::test_per_agent_upload_status_includes_uploaded_at -v`
Expected: FAIL — `KeyError: 'uploaded_at'`.

- [ ] **Step 3: Add `uploaded_at` to the helper**

In `per_agent_upload_status` (recap.py): after building `uploaded_ids`, also build a
`uploaded_at_by_agent` map (max line-item `created_at` per agent for this carrier+period),
and add `uploaded_at` to each output dict.

Replace the `uploaded_ids` block + the output loop with:

```python
    from sqlalchemy import func
    uploaded_ids = set()
    uploaded_at_by_agent = {}
    if stmt_ids:
        rows = (CommissionLineItem.query
                .filter(CommissionLineItem.agency_id == agency_id,
                        CommissionLineItem.statement_id.in_(stmt_ids),
                        CommissionLineItem.agent_id.isnot(None))
                .with_entities(CommissionLineItem.agent_id,
                               func.max(CommissionLineItem.created_at))
                .group_by(CommissionLineItem.agent_id).all())
        for aid, last_at in rows:
            uploaded_ids.add(aid)
            uploaded_at_by_agent[aid] = last_at
    out = []
    for c in expected:
        u = db.session.get(User, c.agent_id)
        at = uploaded_at_by_agent.get(c.agent_id)
        out.append({"agent_id": c.agent_id,
                    "agent_name": (u.name if u else f"Agent {c.agent_id}"),
                    "uploaded": c.agent_id in uploaded_ids,
                    # ISO string (or None) — the template embeds it in JSON and the JS
                    # parses it with new Date(); an ISO string is reliable cross-browser
                    # (Flask's tojson would otherwise emit an HTTP-date string).
                    "uploaded_at": at.isoformat() if at else None})
    out.sort(key=lambda r: r["agent_name"])
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_upload_ux.py::test_per_agent_upload_status_includes_uploaded_at -v`
Expected: PASS. Then `python3 -m pytest -q` — the existing per-agent tests still pass (the new key is additive).

- [ ] **Step 5: Commit**

```bash
git add app/commission/recap.py tests/test_commission_upload_ux.py
git commit -m "feat: per_agent_upload_status includes uploaded_at (per-agent upload date)"
```

---

### Task 2: KPI strip → three compact cards, left-aligned

**Files:**
- Modify: `app/templates/commission.html` — the `.ca-strip` CSS (~128-134) + its markup (~488-506)
- Test: render-verify (documented) — template CSS/markup only.

**Interfaces:**
- Consumes: `overview.statement_count`, `overview.carriers_uploaded`, `overview.carriers_expected`, `overview.total_quarantined` (all existing).

- [ ] **Step 1: Replace the `.ca-strip` CSS with compact-card CSS**

In the template `<style>`, replace the `.ca-strip*` rules (~128-134) with:

```css
.ca-kpis { display:flex; gap:12px; flex-wrap:wrap; margin:0 0 22px; }
.ca-kpi { background:var(--surface); border:1px solid var(--border); border-radius:14px;
          box-shadow:var(--shadow-sm); padding:16px 22px; min-width:150px; }
.ca-kpi .n { font-size:30px; font-weight:800; color:var(--ivory-bright); line-height:1; }
.ca-kpi .l { font-size:11px; font-weight:600; letter-spacing:.06em; text-transform:uppercase;
             color:var(--slate); margin-top:6px; }
.ca-kpi .n.blue { color:var(--gold); }
.ca-kpi .n.green { color:var(--green); }
.ca-kpi a { color:inherit; text-decoration:none; }
```

- [ ] **Step 2: Replace the KPI markup**

Replace the `.ca-strip` block (~488-506) with three compact cards:

```html
<div class="ca-kpis">
  <div class="ca-kpi">
    <div class="n">{{ overview.statement_count }}</div>
    <div class="l">Statements uploaded</div>
  </div>
  <div class="ca-kpi">
    <div class="n {{ 'green' if overview.carriers_uploaded == overview.carriers_expected else 'blue' }}">
      {{ overview.carriers_uploaded }} / {{ overview.carriers_expected }}</div>
    <div class="l">Carriers received</div>
  </div>
  <div class="ca-kpi">
    {% if overview.total_quarantined %}
    <a href="{{ url_for('commission.commission_quarantine_workbench', period=selected_period) }}">
      <div class="n" style="color:var(--gold);">{{ overview.total_quarantined }}</div>
      <div class="l">Payments to review →</div></a>
    {% else %}
    <div class="n green">0</div>
    <div class="l">Payments to review</div>
    {% endif %}
  </div>
</div>
```

- [ ] **Step 3: Render-verify + suite**

Load `/admin/commissions` as admin (test client or manual); confirm 3 tidy cards, no full-width bar. Confirm `python3 -m pytest -q` still green (template-only). Document how verified. Confirm no `var(--ink)` on text.

- [ ] **Step 4: Commit**

```bash
git add app/templates/commission.html
git commit -m "feat: KPI strip -> three compact left-aligned cards (was full-width bar)"
```

---

### Task 3: Carrier row → uniform chips + click-popover (agent ✓/○ + date)

**Files:**
- Modify: `app/templates/commission.html` — the `.ca-checklist`/`.ca-chip-group`/`<details>` CSS (~135-145) + markup (~508-531) + add popover JS to the `<script>` block
- Test: render-verify (documented) — the data is Task-1 tested; the popover is JS/CSS.

**Interfaces:**
- Consumes: `overview.checklist` entries with `carrier`, `uploaded`, and (for per-agent carriers) `agents: [{agent_name, uploaded, uploaded_at}]` (Task 1 added `uploaded_at`).

- [ ] **Step 1: Replace the checklist CSS (chips + popover, drop the `<details>` pill)**

Replace the `.ca-checklist`/`.ca-chip-group`/`.ca-chip`-related rules (~135-145) with:

```css
.ca-checklist { display:flex; flex-wrap:wrap; gap:8px; margin:0 0 26px; position:relative; }
.ca-chip { display:inline-flex; align-items:center; gap:6px; padding:6px 13px;
           border-radius:var(--radius-pill); font-size:13px; font-weight:600;
           border:1px solid var(--border); background:var(--surface); color:var(--slate);
           font-family:inherit; }
.ca-chip.in { color:var(--green-dim); background:color-mix(in srgb, var(--green) 12%, var(--surface));
              border-color:color-mix(in srgb, var(--green) 40%, transparent); }
.ca-chip.clickable { cursor:pointer; }
.ca-chip.clickable:hover { border-color:var(--gold); }
.ca-chip .cnt { font-size:11px; font-weight:600; opacity:.7; }
.ca-chip .car { font-size:10px; opacity:.55; }
.ca-pop { position:absolute; z-index:30; margin-top:6px; background:var(--surface);
          border:1px solid var(--border); border-radius:12px; box-shadow:var(--shadow-float);
          padding:12px 14px; min-width:220px; }
.ca-pop h4 { margin:0 0 8px; font-size:11px; font-weight:700; letter-spacing:.06em;
             text-transform:uppercase; color:var(--ivory-bright); }
.ca-pop .row { display:flex; align-items:center; justify-content:space-between;
               font-size:13px; padding:3px 0; }
.ca-pop .row.up { color:var(--green-dim); } .ca-pop .row.miss { color:var(--slate); }
.ca-pop .row .d { font-size:11px; color:var(--slate); }
```

- [ ] **Step 2: Replace the checklist markup (chips, no `<details>`)**

Replace the checklist loop (~508-531) with uniform chips; per-agent carriers become a
clickable `<button>` chip carrying its agents as JSON in a data attribute for the JS
popover (autoescaped via `tojson`):

```html
<div class="ca-checklist" id="caChecklist">
  {% for c in overview.checklist %}
    {% if c.agents %}
      {% set up = c.agents|selectattr('uploaded')|list|length %}
      <button type="button" class="ca-chip clickable {{ 'in' if c.uploaded else '' }}"
              aria-expanded="false"
              data-carrier="{{ c.carrier }}"
              data-agents="{{ c.agents|tojson|forceescape }}">
        {{ '✓' if c.uploaded else '○' }} {{ c.carrier }}
        <span class="cnt">{{ up }}/{{ c.agents|length }}</span> <span class="car">▾</span>
      </button>
    {% else %}
      <span class="ca-chip {{ 'in' if c.uploaded else '' }}">
        {{ '✓' if c.uploaded else '○' }} {{ c.carrier }}</span>
    {% endif %}
  {% endfor %}
</div>
```

- [ ] **Step 3: Add the popover JS (open/close/position/Esc/outside, one-at-a-time)**

In the template `<script>` block, add (vanilla; renders agent rows via textContent — the
`data-agents` JSON is parsed, dates formatted client-side):

```javascript
(function(){
  var checklist = document.getElementById('caChecklist');
  if (!checklist) return;
  var openPop = null, openChip = null;
  function fmtDate(iso){
    if(!iso) return '—';
    try { var d=new Date(iso); return d.toLocaleDateString(undefined,{month:'short',day:'numeric'}); }
    catch(e){ return '—'; }
  }
  function closePop(){ if(openPop){openPop.remove();} if(openChip){openChip.setAttribute('aria-expanded','false');}
                       openPop=null; openChip=null; }
  checklist.querySelectorAll('.ca-chip.clickable').forEach(function(chip){
    chip.addEventListener('click', function(e){
      e.stopPropagation();
      if(openChip===chip){ closePop(); return; }   // toggle
      closePop();
      var agents; try { agents = JSON.parse(chip.getAttribute('data-agents')); } catch(_){ agents=[]; }
      var pop = document.createElement('div'); pop.className='ca-pop';
      var up = agents.filter(function(a){return a.uploaded;}).length;
      var h = document.createElement('h4');
      h.textContent = chip.getAttribute('data-carrier') + ' · ' + up + ' of ' + agents.length + ' agents uploaded';
      pop.appendChild(h);
      agents.forEach(function(a){
        var row=document.createElement('div'); row.className='row '+(a.uploaded?'up':'miss');
        var nm=document.createElement('span'); nm.textContent=(a.uploaded?'✓ ':'○ ')+a.agent_name;
        var dt=document.createElement('span'); dt.className='d'; dt.textContent=fmtDate(a.uploaded_at);
        row.appendChild(nm); row.appendChild(dt); pop.appendChild(row);
      });
      // position under the chip, within the checklist's relative box
      pop.style.left = chip.offsetLeft + 'px';
      pop.style.top  = (chip.offsetTop + chip.offsetHeight) + 'px';
      checklist.appendChild(pop);
      chip.setAttribute('aria-expanded','true');
      openPop=pop; openChip=chip;
    });
  });
  document.addEventListener('click', function(e){ if(openPop && !openPop.contains(e.target)) closePop(); });
  document.addEventListener('keydown', function(e){ if(e.key==='Escape') closePop(); });
})();
```

- [ ] **Step 4: Render-verify (browser or test client)**

Confirm: chips are uniform height (no stretched capsules, no `<details>`); a per-agent chip
is a `<button>` with `data-agents`; clicking it (in a real browser) opens a floating popover
listing agents ✓/○ + date that does NOT push the row taller; Esc / click-outside closes it;
one open at a time. At minimum: GET `/admin/commissions` as admin returns 200 and contains
`class="ca-chip clickable"` + `data-agents` (no `<details`). Document how verified. Confirm
no `var(--ink)` text, agent data only via textContent/tojson (no `|safe`).

- [ ] **Step 5: Suite + commit**

Run: `python3 -m pytest -q` (template/JS change; confirm nothing broke).
```bash
git add app/templates/commission.html
git commit -m "feat: carrier chips + click-popover (agent status + upload date) — replaces broken expanding pills"
```

---

### Task 4: Upload box → compact single-row drop-zone

**Files:**
- Modify: `app/templates/commission.html` — the `.ca-upload`/`.ca-drop`/`.ca-uprow` CSS (~146-160) + the upload markup (~533-560) — restyle to a compact row; keep the input/JS ids intact.
- Test: render-verify (documented) — behavior unchanged (2026-07-03 JS untouched).

**Interfaces:**
- Consumes: `default_upload_month`, `default_upload_month_iso`; the existing `caDrop`/`caFile`/`caStaging`/`caResults`/`caSubmit` ids + their JS (UNCHANGED).

- [ ] **Step 1: Restyle the drop-zone to a compact horizontal row**

Replace the `.ca-drop` (and related) CSS (~151-160) so the drop-zone is a slim row, not a
tall centered box:

```css
.ca-drop { display:flex; align-items:center; gap:14px; cursor:pointer;
           border:1.5px dashed var(--outline-var); border-radius:12px;
           padding:14px 18px; background:var(--surface-low); }
.ca-drop:hover, .ca-drop.drag-over { border-color:var(--gold); background:var(--surface-mid); }
.ca-drop svg { opacity:.5; flex:none; }
.ca-drop .ca-drop-body { flex:1; text-align:left; }
.ca-drop-text { font-size:14px; color:var(--ivory); font-weight:500; }
.ca-drop-sub { font-size:12px; color:var(--slate); margin-top:2px; }
```

- [ ] **Step 2: Restructure the upload markup into one compact row**

Rework the upload form so the drop-zone, the month picker, and the submit sit in ONE row
(the drop label flexes; the month + button sit at the right). Keep EVERY id + name +
`multiple` + the staging/results containers exactly as they are (the JS binds to them).
Example:

```html
<div class="ca-upload">
  <form method="POST" action="{{ url_for('commission.commission_upload') }}" enctype="multipart/form-data">
    <div style="display:flex; align-items:center; gap:14px; flex-wrap:wrap;">
      <label class="ca-drop" id="caDrop" style="flex:1; min-width:280px;">
        <input type="file" name="file" id="caFile" accept=".xlsx,.xls,.csv" multiple hidden>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" stroke-width="1.6"><path d="M12 16V4m0 0L7 9m5-5l5 5"/><path d="M4 17v2a1 1 0 001 1h14a1 1 0 001-1v-2"/></svg>
        <div class="ca-drop-body">
          <div class="ca-drop-text" id="caDropText">Drop files here or <span class="link-text">click to browse</span></div>
          <div class="ca-drop-sub">CSV, XLSX, XLS · drop or select many · carrier + agent auto-detected</div>
        </div>
      </label>
      <div>
        <label class="ca-flabel">Attribute to <span style="color:var(--green);font-weight:600;">· {{ default_upload_month }}</span></label>
        <input type="month" name="statement_month" value="{{ default_upload_month_iso }}" class="ca-month">
      </div>
      <button type="button" class="ca-submit" id="caSubmit">Upload &amp; Parse<span id="caCount"></span></button>
    </div>
    <ul id="caStaging" class="ca-staging"></ul>
    <div id="caResults" class="ca-results" hidden></div>
    <p style="font-size:11px;color:var(--slate);margin:10px 0 0;">
      Commissions pay one month behind, so this defaults to <strong>{{ default_upload_month }}</strong> — change it only if a file is for a different month.
    </p>
  </form>
</div>
```
⚠️ CRITICAL: preserve the EXACT ids/names the 2026-07-03 JS binds to: `caDrop`, `caFile`
(name `file`, `multiple`), `caDropText`, `caSubmit`, `caCount`, `caStaging`, `caResults`, and
`statement_month`. If any id was renamed the staging/AJAX/results break. Read the current
`<script>` first and match every selector.

- [ ] **Step 3: Tighten the staging/results row CSS (compact)**

Ensure `.ca-staging`/`.ca-results` rows are thin/compact (small padding, one line each),
consistent with the new density. Keep colors `var(--ivory)`/`var(--slate)`, ok/err greens/reds.

- [ ] **Step 4: Render + behavior verify**

GET `/admin/commissions` (admin) returns 200; the upload box is now a compact row (drop +
month + button on one line); `id="caFile"` has `multiple`; `caStaging`/`caResults`/`caSubmit`
present. In a browser: staging a file still lists it, remove works, Upload & Parse still
fetches + renders inline (the JS is unchanged — this proves the ids still bind). Document
how verified.

- [ ] **Step 5: Suite + commit**

Run: `python3 -m pytest -q`.
```bash
git add app/templates/commission.html
git commit -m "feat: compact single-row upload box (drop + month + button in one row)"
```

---

### Task 5: Deploy + browser-verify (operational, with Tim)

**Files:** none.

- [ ] **Step 1: Full suite green**

Run: `python3 -m pytest -q`. Expected: all green.

- [ ] **Step 2: UI/whole-page review**

Dispatch a review (the diff is template-heavy) focused on: no `var(--ink)` text; agent data
only via `textContent`/`tojson` (no `|safe`); popover accessibility (button + aria-expanded +
Esc); light+dark token use; the upload JS ids preserved (staging/AJAX still bind). Triage.

- [ ] **Step 3: Merge + deploy**

Documented: merge to main, VPS `git pull`, restart, confirm cycled + login 200 +
`/admin/commissions` 200, no errors. No migration.

- [ ] **Step 4: Live browser-verify with Tim**

On `/admin/commissions`: 3 tidy KPI cards; carrier chips uniform; clicking BCBS opens a
floating popover with agent ✓/○ + upload dates that does NOT balloon the row; Esc/outside
closes; compact upload row; stage + multi-upload still works inline; light + dark both clean;
responsive (narrow window: cards + chips wrap, popover stays in view).

---

## Self-review notes (for the executor)
- The ONLY backend change is Task 1 (`uploaded_at` field). Tasks 2-4 are template CSS/markup
  + the popover JS. The 2026-07-03 upload JS must remain byte-identical in behavior — Task 4
  only restyles its containers; DO NOT touch the staging/AJAX/results script.
- Watch the Task-4 id preservation (the #1 breakage risk): every id the existing `<script>`
  queries must survive the markup restructure.
- After deploy: add the redesign to the /roadmap board; update CLAUDE.md START HERE +
  session-handoff. The sidebar/rename overhaul is already logged in BACKLOG.
