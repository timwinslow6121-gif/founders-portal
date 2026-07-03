# Commission Upload UX Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the admin Commission Audit upload flow easier for AJ — one themed banner, two clearly-labeled month controls (upload defaults to last month), multi-file drag/select with a staging list, per-agent BCBS upload status, and inline (no-redirect) per-file import results (good ones import, bad ones rejected with a reason).

**Architecture:** The upload becomes AJAX: `commission_upload` processes a LIST of files (each in its own savepoint), returns JSON (per-file results + refreshed overview), and vanilla JS renders results + repaints the checklist in place — reusing the `commission_line_edit` JSON pattern and the existing drop-zone JS. The current single-file body is extracted into `_process_one_file(...) -> dict`; `_ingest_normalized_upload` is converted to return a result dict instead of flash+redirect.

**Tech Stack:** Python 3.10, Flask, Jinja2, vanilla JS (no new deps), pytest.

**Spec:** `docs/superpowers/specs/2026-07-03-commission-upload-ux-overhaul-design.md`

## Global Constraints

- **Everything inline — no redirect, no page reload** for the upload flow. Uploads post via `fetch()`; the route returns JSON; JS renders results in the DOM.
- Admin-only (`current_user.is_admin`); agency-scope every query.
- Text colors `var(--ivory)`/`var(--slate)` only — NEVER `var(--ink)` (background token). No `|safe` on filenames/error text (autoescape / textContent).
- Reuse: `commission_line_edit` (routes.py:1364) JSON+XHR-detection pattern; the existing `caDrop`/`caFile` drop-zone JS (commission.html:523-530); `PER_AGENT_CARRIERS` + `file_scoped_prefix` (ledger.py); `AgentCarrierContract(carrier,is_active,id_value)`; `commission_audit_overview` (recap.py:579).
- Per-file failure must NOT block other files: each file processed in `db.session.begin_nested()` (savepoint); on error, rollback that savepoint only.
- Back-compat: a non-XHR POST to `commission_upload` still redirects+flashes (JS-off fallback).
- No new migration.

---

### Task 1: Fix the double success banner + theme the alert

**Files:**
- Modify: `app/templates/commission.html:196-200` (remove the duplicate flash block)
- Modify: `app/templates/base.html` (theme the `.alert` classes — near the existing `<style>` or the flash render at :906)
- Test: manual render-verify (documented) — this is a template-only change with no logic.

**Interfaces:**
- Consumes: nothing. Produces: a single themed flash render.

- [ ] **Step 1: Remove the duplicate flash block from commission.html**

Delete lines 196-200 of `app/templates/commission.html` (the `{% with messages = get_flashed_messages(with_categories=true) %}…{% endwith %}` block). `base.html:906` already renders flashes once for every page.

- [ ] **Step 2: Theme the `.alert` classes in base.html**

Find where `.alert` is styled (search `base.html` for `.alert`). Ensure the classes render on-theme (Founders palette). Add/adjust in base.html's `<style>`:

```css
.alert { border-radius: 12px; padding: 12px 16px; margin: 0 0 16px; font-size: 14px;
         border: 1px solid transparent; }
.alert-success { background: color-mix(in srgb, var(--green) 12%, var(--surface));
                 color: var(--ivory); border-color: color-mix(in srgb, var(--green) 40%, transparent); }
.alert-error   { background: color-mix(in srgb, #c0392b 10%, var(--surface));
                 color: var(--ivory); border-color: color-mix(in srgb, #c0392b 35%, transparent); }
.alert-warning { background: color-mix(in srgb, var(--gold) 12%, var(--surface));
                 color: var(--ivory); border-color: color-mix(in srgb, var(--gold) 40%, transparent); }
```
(If `.alert-*` classes already exist, adjust to these tokens rather than duplicating. Confirm text uses `var(--ivory)`, never `var(--ink)`.)

- [ ] **Step 3: Verify no `get_flashed_messages` remains in commission.html**

Run: `grep -c "get_flashed_messages" app/templates/commission.html`
Expected: `0`.

- [ ] **Step 4: Render-verify**

Trigger any flash (e.g. a delete) and confirm exactly ONE banner appears, themed. Document how verified. Confirm the full suite still passes: `python3 -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add app/templates/commission.html app/templates/base.html
git commit -m "fix: single themed success banner on commission audit (was double-rendered)"
```

---

### Task 2: Upload month defaults to last month (current − 1) + relabel both month controls

**Files:**
- Modify: `app/commission/routes.py:801-812` (compute `default_upload_month`/`_iso`, pass to template)
- Modify: `app/templates/commission.html:463-471` (relabel viewing picker) + `:511-519` (relabel + default upload month)
- Test: `tests/test_commission_upload_ux.py` (new)

**Interfaces:**
- Consumes: nothing. Produces: template context `default_upload_month` (e.g. "June 2026"), `default_upload_month_iso` (e.g. "2026-06").

- [ ] **Step 1: Write the failing test**

```python
# tests/test_commission_upload_ux.py
from datetime import date


def test_previous_month_helper():
    from app.commission.routes import _previous_month
    # July 2026 -> June 2026
    assert _previous_month(date(2026, 7, 15)) == ("June 2026", "2026-06")
    # January -> previous December of prior year
    assert _previous_month(date(2026, 1, 3)) == ("December 2025", "2025-12")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_upload_ux.py::test_previous_month_helper -v`
Expected: FAIL — `ImportError: cannot import name '_previous_month'`.

- [ ] **Step 3: Add the helper + wire into the view**

In `app/commission/routes.py`, add near the top-level helpers:

```python
def _previous_month(today=None):
    """(label, iso) for the month BEFORE `today` — commissions pay a month behind,
    so the upload attribution defaults here. e.g. July -> ('June 2026', '2026-06')."""
    from datetime import date as _date
    today = today or _date.today()
    year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    d = _date(year, month, 1)
    return d.strftime("%B %Y"), d.strftime("%Y-%m")
```

In the `commission_admin` view render (routes.py ~801-812), compute and pass:

```python
    default_upload_month, default_upload_month_iso = _previous_month()
```
Add `default_upload_month=default_upload_month, default_upload_month_iso=default_upload_month_iso,`
to the `render_template("commission.html", ...)` kwargs.

- [ ] **Step 4: Relabel the two month controls in commission.html**

Viewing picker (line ~464): change the label from `Month` to `Viewing`:
```html
  <label style="font-size:12px;color:var(--slate);text-transform:uppercase;letter-spacing:.04em;">Viewing</label>
```

Upload month (lines ~513-519): use the previous-month default + a clearer label:
```html
      <div>
        <label class="ca-flabel">Attribute this statement to
          <span style="color:var(--green);font-weight:600;">· {{ default_upload_month }}</span></label>
        <input type="month" name="statement_month" value="{{ default_upload_month_iso }}" class="ca-month">
      </div>
```
And the helper `<p>` (line ~518): "Commissions pay one month behind, so this defaults to **{{ default_upload_month }}** — change it only if this file is for a different month."

- [ ] **Step 5: Run test to verify it passes + suite**

Run: `python3 -m pytest tests/test_commission_upload_ux.py -v` then `python3 -m pytest -q`.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/commission/routes.py app/templates/commission.html tests/test_commission_upload_ux.py
git commit -m "feat: upload month defaults to last month (pay-behind) + relabel viewing vs attribute month"
```

---

### Task 3: Per-agent upload status helper (#4 data layer)

**Files:**
- Modify: `app/commission/recap.py` (add `per_agent_upload_status`)
- Test: `tests/test_commission_upload_ux.py`

**Interfaces:**
- Consumes: `AgentCarrierContract`, `CommissionStatement`, `CommissionLineItem`, `User`, `PER_AGENT_CARRIERS`.
- Produces: `per_agent_upload_status(agency_id, carrier, period_label) -> list[dict]` where each dict is `{"agent_id": int, "agent_name": str, "uploaded": bool}`, sorted by name. Returns `[]` for a carrier NOT in `PER_AGENT_CARRIERS`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_commission_upload_ux.py
import pytest
from datetime import date


@pytest.fixture
def ctx():
    from app import create_app
    from app.extensions import db
    from app.models import Agency
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        yield app, ag.id
        db.session.remove(); db.drop_all()


def test_per_agent_upload_status(ctx):
    from app.extensions import db
    from app.models import (User, AgentCarrierContract, CommissionStatement,
                            CommissionLineItem)
    from app.commission.recap import per_agent_upload_status
    app, agency_id = ctx
    # two agents with active BCBS contracts (expected); only one has uploaded rows
    a1 = User(email="a1@x.com", name="Brian Freeman", agency_id=agency_id, role="agent")
    a2 = User(email="a2@x.com", name="Mike Lauzurique", agency_id=agency_id, role="agent")
    db.session.add_all([a1, a2]); db.session.flush()
    for a in (a1, a2):
        db.session.add(AgentCarrierContract(agency_id=agency_id, agent_id=a.id,
                                            carrier="BCBS", is_active=True))
    st = CommissionStatement(agency_id=agency_id, carrier="BCBS",
                             statement_date=date(2026, 6, 1), period_label="June 2026")
    db.session.add(st); db.session.flush()
    # only Brian has a line item this period
    db.session.add(CommissionLineItem(agency_id=agency_id, statement_id=st.id,
                                      carrier="BCBS", period_label="June 2026",
                                      agent_id=a1.id, member_name="X", raw_amount=10.0,
                                      classification="agent_commission", source_ref="bcbs::p1::Sheet1::1"))
    db.session.commit()

    rows = per_agent_upload_status(agency_id, "BCBS", "June 2026")
    by_name = {r["agent_name"]: r["uploaded"] for r in rows}
    assert by_name == {"Brian Freeman": True, "Mike Lauzurique": False}
    # a non-per-agent carrier returns []
    assert per_agent_upload_status(agency_id, "Humana", "June 2026") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_upload_ux.py::test_per_agent_upload_status -v`
Expected: FAIL — `ImportError: cannot import name 'per_agent_upload_status'`.

- [ ] **Step 3: Implement the helper**

Add to `app/commission/recap.py`:

```python
def per_agent_upload_status(agency_id, carrier, period_label):
    """For a PER_AGENT carrier, which contracted agents have uploaded this period.
    Returns [{'agent_id','agent_name','uploaded'}] sorted by name; [] for a
    carrier that isn't per-agent (agency-wide carriers are one file — carrier-level
    status is correct for them)."""
    from app.commission.ledger import PER_AGENT_CARRIERS
    if carrier not in PER_AGENT_CARRIERS:
        return []
    from app.models import (AgentCarrierContract, CommissionStatement,
                            CommissionLineItem, User)
    expected = (AgentCarrierContract.query
                .filter_by(agency_id=agency_id, carrier=carrier, is_active=True).all())
    # agents that actually have line items for this carrier+period
    stmt_ids = [s.id for s in CommissionStatement.query
                .filter_by(agency_id=agency_id, carrier=carrier,
                           period_label=period_label).all()]
    uploaded_ids = set()
    if stmt_ids:
        for (aid,) in (CommissionLineItem.query
                       .filter(CommissionLineItem.agency_id == agency_id,
                               CommissionLineItem.statement_id.in_(stmt_ids),
                               CommissionLineItem.agent_id.isnot(None))
                       .with_entities(CommissionLineItem.agent_id).distinct().all()):
            uploaded_ids.add(aid)
    out = []
    for c in expected:
        u = db.session.get(User, c.agent_id)
        out.append({"agent_id": c.agent_id,
                    "agent_name": (u.name if u else f"Agent {c.agent_id}"),
                    "uploaded": c.agent_id in uploaded_ids})
    out.sort(key=lambda r: r["agent_name"])
    return out
```

(Confirm `db` is imported in recap.py; it is — the file already queries.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_upload_ux.py::test_per_agent_upload_status -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/commission/recap.py tests/test_commission_upload_ux.py
git commit -m "feat: per_agent_upload_status helper (which contracted agents uploaded a per-agent carrier)"
```

---

### Task 4: Surface per-agent status in the carrier checklist (#4 UI)

**Files:**
- Modify: `app/commission/recap.py` `commission_audit_overview` (~579-644) — attach per-agent status to per-agent carriers in the checklist
- Modify: `app/templates/commission.html:493-500` (render the expandable per-agent sub-list)
- Test: `tests/test_commission_upload_ux.py`

**Interfaces:**
- Consumes: `per_agent_upload_status` (Task 3).
- Produces: each checklist entry gains `"agents": [{agent_name, uploaded}] | None` (None/absent for non-per-agent carriers).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_commission_upload_ux.py
def test_overview_checklist_has_per_agent_for_bcbs(ctx):
    from app.extensions import db
    from app.models import User, AgentCarrierContract
    from app.commission.recap import commission_audit_overview
    app, agency_id = ctx
    a1 = User(email="b@x.com", name="Brian Freeman", agency_id=agency_id, role="agent")
    db.session.add(a1); db.session.flush()
    db.session.add(AgentCarrierContract(agency_id=agency_id, agent_id=a1.id,
                                        carrier="BCBS", is_active=True))
    db.session.commit()
    ov = commission_audit_overview(agency_id, "June 2026")
    bcbs = next((c for c in ov["checklist"] if c["carrier"] == "BCBS"), None)
    assert bcbs is not None
    assert bcbs.get("agents") is not None
    assert any(a["agent_name"] == "Brian Freeman" for a in bcbs["agents"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_upload_ux.py::test_overview_checklist_has_per_agent_for_bcbs -v`
Expected: FAIL — `bcbs.get("agents")` is None (not attached yet).

- [ ] **Step 3: Attach per-agent status in the overview builder**

In `commission_audit_overview` (recap.py), where `checklist` is built (~line 639), enrich each entry:

```python
    from app.commission.ledger import PER_AGENT_CARRIERS
    checklist = []
    for d, up in sorted(seen.items()):
        entry = {"carrier": d, "uploaded": up}
        if d in PER_AGENT_CARRIERS:
            entry["agents"] = per_agent_upload_status(agency_id, d, period_label)
        checklist.append(entry)
```

- [ ] **Step 4: Render the expandable sub-list in commission.html**

Replace the checklist loop (lines ~495-499) so per-agent carriers show a `<details>` breakdown:

```html
  {% for c in overview.checklist %}
  {% if c.agents %}
  <details class="ca-chip-group">
    <summary class="ca-chip {{ 'in' if c.uploaded else 'out' }}">
      {{ '✓' if c.uploaded else '○' }} {{ c.carrier }}
      <span style="color:var(--slate);font-size:11px;">
        ({{ c.agents|selectattr('uploaded')|list|length }}/{{ c.agents|length }})</span>
    </summary>
    <div class="ca-agent-list">
      {% for a in c.agents %}
      <span class="ca-agent {{ 'in' if a.uploaded else 'out' }}">
        {{ '✓' if a.uploaded else '○' }} {{ a.agent_name }}</span>
      {% endfor %}
    </div>
  </details>
  {% else %}
  <span class="ca-chip {{ 'in' if c.uploaded else 'out' }}">
    {{ '✓' if c.uploaded else '○' }} {{ c.carrier }}</span>
  {% endif %}
  {% endfor %}
```
Add minimal CSS for `.ca-agent-list`/`.ca-agent` in the template `<style>` (text `var(--ivory)`/`var(--slate)`; green check = in, muted = out; no `var(--ink)` on text).

- [ ] **Step 5: Run test + render-verify**

Run: `python3 -m pytest tests/test_commission_upload_ux.py -q` then `python3 -m pytest -q`.
Render-verify the BCBS chip expands to show agents ✓/○. Document how verified.

- [ ] **Step 6: Commit**

```bash
git add app/commission/recap.py app/templates/commission.html tests/test_commission_upload_ux.py
git commit -m "feat: per-agent ✓/○ breakdown under per-agent carriers in the upload checklist"
```

---

### Task 5: Extract per-file processing to return a result dict (backend refactor)

**Files:**
- Modify: `app/commission/routes.py` — extract `_process_one_file(...)` from the current `commission_upload` body; convert `_ingest_normalized_upload` to return a result dict.
- Test: `tests/test_commission_upload_ux.py`

**Interfaces:**
- Consumes: the existing detect/normalize/ingest/legacy logic.
- Produces:
  - `_process_one_file(filename, file_bytes, statement_month, agency_id, actor) -> dict`
    returning on success `{"filename","ok":True,"carrier","scope","rows","gross","period"}`
    and on failure `{"filename","ok":False,"error":<str>,"fix":<str|None>}`. Never raises,
    never flashes, never redirects. `scope` = agent name for per-agent carriers, else the carrier.
  - `_ingest_normalized_upload(...)` returns the same success/failure dict (not a redirect).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_commission_upload_ux.py
def test_process_one_file_rejects_unreadable_with_reason(ctx):
    from app.commission.routes import _process_one_file
    app, agency_id = ctx
    with app.test_request_context():
        res = _process_one_file("junk.xlsx", b"not a real workbook", "2026-06",
                                 agency_id, actor=None)
    assert res["ok"] is False
    assert res["filename"] == "junk.xlsx"
    assert res["error"]                       # a human-readable reason
```

(A full happy-path ingest test needs real fixtures + DB users; the route-level test in Task 6 covers the good+bad mix end-to-end. This task's test pins the failure-returns-a-dict contract — the key refactor guarantee.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_upload_ux.py::test_process_one_file_rejects_unreadable_with_reason -v`
Expected: FAIL — `ImportError: cannot import name '_process_one_file'`.

- [ ] **Step 3: Extract `_process_one_file` + make ingest return a dict**

Refactor: move the body of `commission_upload` (from `file_bytes = file.read()` through the parse/ingest/flash logic) into `_process_one_file(filename, file_bytes, statement_month, agency_id, actor)`. Replace every `flash(msg,"error"); return redirect(...)` with `return {"filename": filename, "ok": False, "error": msg, "fix": <fix-or-None>}`. Replace the success flash+redirect with `return {"filename": filename, "ok": True, "carrier":…, "scope":…, "rows":…, "gross":…, "period":…}`. Wrap the whole body in a broad `try/except Exception as e: return {…ok:False, error:str(e)…}` so it NEVER raises. Convert `_ingest_normalized_upload` the same way (it already computes carrier/rows/gross — return them in the dict instead of flashing). Use the specific messages already present (`BcbsColumnError` text, unsupported-carrier reason) as the `error`, and set `fix` for the known ones (e.g. BcbsColumnError → "check the column names / re-export from Tidewater").

The `statement_month` form value is now a PARAMETER (not read from `request.form` inside), so the function is testable and the loop can pass it once.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_upload_ux.py::test_process_one_file_rejects_unreadable_with_reason -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite (the refactor touches the upload path)**

Run: `python3 -m pytest -q`
Expected: green. Existing commission-upload tests that asserted flash/redirect behavior may need updating to the dict contract — update them to assert the returned dict, noting each in the report (do NOT weaken; the behavior moved from flash to return-value).

- [ ] **Step 6: Commit**

```bash
git add app/commission/routes.py tests/test_commission_upload_ux.py
git commit -m "refactor: _process_one_file returns a result dict (ok/carrier/rows OR error/fix), not flash+redirect"
```

---

### Task 6: Multi-file loop + JSON response (backend, #5)

**Files:**
- Modify: `app/commission/routes.py` `commission_upload` — loop `getlist("file")`, per-file savepoint, return JSON (XHR) or redirect (back-compat)
- Test: `tests/test_commission_upload_ux.py`

**Interfaces:**
- Consumes: `_process_one_file` (Task 5), the refreshed `commission_audit_overview`.
- Produces: `commission_upload` returns, for an XHR/JSON request, `jsonify(results=[dict], summary={"imported":n,"rejected":m})`. A non-XHR request keeps the redirect+flash behavior.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_commission_upload_ux.py
def _admin(db, agency_id):
    from app.models import User
    u = User(email="admin@x.com", name="AJ", is_admin=True, agency_id=agency_id, role="admin")
    db.session.add(u); db.session.flush(); return u


def test_upload_multi_file_partial_success_json(ctx):
    import io
    from app.extensions import db
    app, agency_id = ctx
    admin = _admin(db, agency_id); db.session.commit()
    client = app.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(admin.id); s["_fresh"] = True
    # two "files": both unreadable junk -> both rejected (no real fixtures needed to
    # prove the loop + JSON contract + per-file isolation).
    data = {
        "statement_month": "2026-06",
        "file": [(io.BytesIO(b"junkA"), "a.xlsx"), (io.BytesIO(b"junkB"), "b.xlsx")],
    }
    resp = client.post("/admin/commissions/upload", data=data,
                       content_type="multipart/form-data",
                       headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["summary"]["rejected"] == 2
    assert body["summary"]["imported"] == 0
    assert len(body["results"]) == 2
    assert all(r["ok"] is False and r["error"] for r in body["results"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_upload_ux.py::test_upload_multi_file_partial_success_json -v`
Expected: FAIL — the route still handles a single `file` + redirects (no JSON, no `results`).

- [ ] **Step 3: Rewrite `commission_upload` as a multi-file loop returning JSON**

```python
@commission_bp.route("/admin/commissions/upload", methods=["POST"])
@login_required
def commission_upload():
    if not current_user.is_admin:
        abort(403)
    files = [f for f in request.files.getlist("file") if f and f.filename]
    statement_month = request.form.get("statement_month", "").strip()
    is_xhr = (request.headers.get("X-Requested-With") == "XMLHttpRequest"
              or "application/json" in (request.headers.get("Accept") or ""))
    if not files:
        if is_xhr:
            return jsonify(results=[], summary={"imported": 0, "rejected": 0},
                           error="No file selected."), 400
        flash("No file selected.", "error")
        return redirect(url_for("commission.commission_admin"))

    results = []
    for f in files:
        fname = f.filename
        try:
            data = f.read()
        except Exception as e:
            results.append({"filename": fname, "ok": False,
                            "error": f"Could not read upload: {e}", "fix": None})
            continue
        nested = db.session.begin_nested()   # per-file savepoint
        try:
            res = _process_one_file(fname, data, statement_month,
                                    current_user.agency_id, current_user)
            if res.get("ok"):
                nested.commit()
            else:
                nested.rollback()
            results.append(res)
        except Exception as e:              # defensive — _process_one_file shouldn't raise
            nested.rollback()
            results.append({"filename": fname, "ok": False, "error": str(e), "fix": None})
    db.session.commit()

    summary = {"imported": sum(1 for r in results if r.get("ok")),
               "rejected": sum(1 for r in results if not r.get("ok"))}
    if is_xhr:
        return jsonify(results=results, summary=summary)
    # non-XHR back-compat: flash a summary + redirect
    for r in results:
        flash((f"✓ {r.get('scope','')} {r['filename']}: {r.get('rows',0)} rows"
               if r.get("ok") else f"✗ {r['filename']}: {r['error']}"),
              "success" if r.get("ok") else "error")
    return redirect(url_for("commission.commission_admin"))
```

NOTE: `_process_one_file` handles its OWN statement upsert/commit-within-savepoint via the ingest logic; the savepoint here guarantees a failed file leaves no partial rows. Confirm `_ingest_normalized_upload`/legacy path don't call `db.session.commit()` mid-function in a way that breaks the savepoint — if they do, change them to `db.session.flush()` and let the route's `nested.commit()`/final `commit()` own the transaction. (This is the one integration risk; verify during implementation and adjust.)

- [ ] **Step 4: Run test to verify it passes + suite**

Run: `python3 -m pytest tests/test_commission_upload_ux.py::test_upload_multi_file_partial_success_json -v` then `python3 -m pytest -q`.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/commission/routes.py tests/test_commission_upload_ux.py
git commit -m "feat: commission_upload processes multiple files (per-file savepoint) and returns JSON results"
```

---

### Task 7: Frontend — multi-file staging + AJAX submit + inline results (#3 + inline render)

**Files:**
- Modify: `app/templates/commission.html` — `multiple` on the input; staging-list container; results container; extend the `<script>` for staging (add/remove/accumulate), fetch submit, and render.
- Test: browser render-verify (documented) — the JS behavior; the JSON contract is covered by Task 6.

**Interfaces:**
- Consumes: the JSON from `commission_upload` (Task 6); `default_upload_month_iso` (Task 2).
- Produces: the inline upload UX.

- [ ] **Step 1: Make the input multiple + add staging/results containers**

In the upload form (commission.html ~504-517): add `multiple` to `<input type="file" name="file" …>` (remove `required` — validation is JS-side now since it's AJAX). After the drop `<label>`, add:
```html
    <ul id="caStaging" class="ca-staging"></ul>
    <div id="caResults" class="ca-results" hidden></div>
```
Change the submit button to `type="button" id="caSubmit"` with label `Upload &amp; Parse` and a `<span id="caCount"></span>`.

- [ ] **Step 2: Extend the JS — staging (accumulate + remove)**

Replace/extend the existing `<script>` (lines ~523-530). Keep an in-memory `let staged = []` array of `File`s. On `change`/`drop`, push new files (dedupe by name+size), re-render the staging list. Each staging row shows the full filename + a `✕` button that removes it from `staged` and re-renders. Update `#caCount` (e.g. "(3 files)") and disable `#caSubmit` when `staged.length === 0`. Use `textContent` for filenames (never innerHTML — no `|safe`/injection).

- [ ] **Step 3: Extend the JS — AJAX submit + inline results**

On `#caSubmit` click: build `FormData`, append each `staged` file as `file`, append `statement_month` (read the `<input type="month">`), `fetch(uploadUrl, {method:'POST', body: fd, headers:{'X-Requested-With':'XMLHttpRequest'}})`. On the JSON response: render `#caResults` (unhide) with a row per `results[]` — green `✓ {scope} {filename} — {rows} rows, ${gross} → {period}` / red `✗ {filename} — {error}{ fix ? '  Fix: '+fix : '' }` (all via `textContent`/DOM nodes). Remove SUCCEEDED files from `staged` (leave failed ones for a fix-retry), re-render staging. Then refresh the checklist + trust strip: simplest reliable approach — `fetch` the current page URL, parse out the `.ca-strip`/`.ca-checklist` fragments and swap them in (or, if simpler, reload just those via a small `?fragment=overview` GET). Pick the approach that avoids a full navigation. Show a subtle "Uploading…" state on the button while the fetch is in flight.

- [ ] **Step 4: Browser render-verify (Playwright or manual)**

Verify: dropping 3 files stages 3 rows with full names + ✕; removing one drops it + updates the count; clicking Upload & Parse posts once (no navigation), renders the per-file ✓/✗ list inline, and the checklist repaints. Document exactly how verified (this is the acceptance oracle for the inline constraint). Confirm no `var(--ink)` text, filenames via textContent.

- [ ] **Step 5: Run the full suite (no server-side change here, but confirm nothing broke)**

Run: `python3 -m pytest -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add app/templates/commission.html
git commit -m "feat: inline multi-file staging + AJAX upload with per-file results (no redirect)"
```

---

### Task 8: Deploy + browser-verify (operational, with Tim)

**Files:** none.

- [ ] **Step 1: Full suite green**

Run: `python3 -m pytest -q`. Expected: all green.

- [ ] **Step 2: Opus whole-branch review (upload/money path)**

Dispatch the final review on opus — focus on the savepoint/transaction correctness (a failed file leaves NO rows; a good file commits), the JSON contract, agency-scoping, and XSS (filenames/errors rendered safely). Triage findings.

- [ ] **Step 3: Merge + deploy**

Documented for the deploy session: merge to main, VPS `git pull`, restart, confirm cycled + login 200 + `/admin/commissions` 200, no errors. No migration.

- [ ] **Step 4: Live browser-verify with real files**

With Tim: multi-select the June BCBS files → all import inline, per-agent checklist shows each agent ✓ (and any still-missing as ○), no redirect. Drop a deliberately-broken file alongside good ones → good import, bad rejected with its reason. Confirm the single themed banner + the last-month default.

---

## Self-review notes (for the executor)
- **Opus whole-branch review required** (upload/money path). Focus: transaction isolation (savepoint per file — a rejected file must leave zero rows; verify `_ingest_normalized_upload`/legacy don't commit mid-savepoint), the good+bad-mix correctness, XSS on filenames/error text (textContent, no `|safe`), agency scoping in `per_agent_upload_status` + the loop.
- The **one integration risk** is Task 6 Step 3's note: the ingest functions may `commit()` mid-body; if so, switch them to `flush()` so the route owns the transaction/savepoint. Verify during Task 5/6.
- After deploy: update CLAUDE.md START HERE, `BACKLOG.md`, the session-handoff.
