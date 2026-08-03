# Commission Edit — Contract-Rate Visibility & Mismatch Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the agent's contract rate everywhere AJ edits a commission split, preview the resulting dollars as he types, and require one confirmation click before saving an amount that pays a non-100% agent 100%.

**Architecture:** A single cached lookup `contract_rate_for(agent_id, carrier, agency_id)` in `app/commission/recap.py` becomes the one source of the rate. `fidelity_row()` carries it in the row JSON (never per-row markup — the Fidelity table is ~4k rows and a DOM-size regression was already fixed once in merge 50a7f4a). The server route rejects an off-contract save unless the form sends `confirm_off_contract=1`, so the guard holds for AJAX, the no-JS fallback, and a stale form alike. `edit_line_split()` is NOT changed — it still stores `split_rate = 1.0`, because Anjana Patel's non-Cannon-Pharmacy 100% arrangement depends on that convention.

**Tech Stack:** Python 3.10, Flask 3.0, Flask-SQLAlchemy, Jinja2 templates, vanilla JS (no framework), pytest.

## Global Constraints

- **No migration.** This adds no columns and no models.
- **Do not change** `split_breakdown()`, `resolve_quarantine_line()`, or `edit_line_split()`'s storage semantics. Changing `split_rate = 1.0` would silently re-interpret every existing `manually_adjusted` row, including Anjana's legitimate ones.
- **Never fabricate a rate.** When an agent has no active contract for the carrier, the rate is `None` and the UI says "no contract on file". The `0.55` fallback that exists in `commission_line_resolve` must NOT be copied into the new helper.
- **Confirm-and-proceed, never block.** An off-contract save must remain possible in one extra click — Anjana's rows are exactly this shape every month.
- **Agency scoping:** every `AgentCarrierContract` and `CommissionLineItem` query filters on `agency_id`. Missing it is a cross-tenant data leak.
- **Vanilla JS only.** No React/Vue. Match the existing inline-`<script>` style in the templates.
- **Tests run with:** `python3 -m pytest -q` from the repo root. Current suite: **731 passing**.

---

### Task 1: `contract_rate_for()` — the single rate lookup

**Files:**
- Modify: `app/commission/recap.py` (add helper near `fidelity_row`, line ~474)
- Test: `tests/test_commission_recap.py`

**Interfaces:**
- Consumes: `app.models.AgentCarrierContract` (fields `agent_id`, `carrier`, `is_active`, `agency_id`, `split_rate`)
- Produces: `contract_rate_for(agent_id, carrier, agency_id, cache=None) -> float | None` — returns the agent's active split rate for that carrier, or `None` when there is no contract. `cache` is an optional dict the caller passes to batch lookups across many rows.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_commission_recap.py`:

```python
def test_contract_rate_for_returns_rate_and_none(app_ctx):
    """The rate lookup is the ONE place a contract rate is resolved. It must
    return None -- never a fabricated default -- when no contract exists, so
    the UI can say 'no contract on file' instead of implying 0.55."""
    from app.extensions import db
    from app.models import User, AgentCarrierContract
    from app.commission.recap import contract_rate_for
    app, agency_id = app_ctx

    mike = User(email="mike@x.com", name="Mike Lauzurique",
                agency_id=agency_id, role="agent")
    db.session.add(mike); db.session.flush()
    db.session.add(AgentCarrierContract(agent_id=mike.id, carrier="UHC",
                                        agency_id=agency_id, is_active=True,
                                        split_rate=0.525))
    db.session.flush()

    assert contract_rate_for(mike.id, "UHC", agency_id) == 0.525
    # carrier with no contract -> None, NOT 0.55
    assert contract_rate_for(mike.id, "Humana", agency_id) is None
    # no agent at all -> None
    assert contract_rate_for(None, "UHC", agency_id) is None


def test_contract_rate_for_uses_cache(app_ctx):
    """A caller passing a cache must not re-query per row -- the Fidelity view
    serializes ~4k rows and a per-row query would reintroduce the N+1 the
    50a7f4a perf fix removed."""
    from app.extensions import db
    from app.models import User, AgentCarrierContract
    from app.commission.recap import contract_rate_for
    app, agency_id = app_ctx

    u = User(email="a@x.com", name="A Agent", agency_id=agency_id, role="agent")
    db.session.add(u); db.session.flush()
    db.session.add(AgentCarrierContract(agent_id=u.id, carrier="UHC",
                                        agency_id=agency_id, is_active=True,
                                        split_rate=0.5))
    db.session.flush()

    cache = {}
    assert contract_rate_for(u.id, "UHC", agency_id, cache) == 0.5
    assert (u.id, "uhc") in cache
    # poison the cache; a cached hit must be returned without re-querying
    cache[(u.id, "uhc")] = 0.99
    assert contract_rate_for(u.id, "UHC", agency_id, cache) == 0.99
```

If `tests/test_commission_recap.py` has no `app_ctx` fixture, add this one at the top of the file (it mirrors `tests/test_commission_upload_ux.py`):

```python
@pytest.fixture
def app_ctx():
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_recap.py -q -k contract_rate_for`
Expected: FAIL with `ImportError: cannot import name 'contract_rate_for'`

- [ ] **Step 3: Write minimal implementation**

Add to `app/commission/recap.py`, immediately above `def fidelity_row(`:

```python
def contract_rate_for(agent_id, carrier, agency_id, cache=None):
    """The agent's active split rate for this carrier, or None if none exists.

    THE single place a contract rate is resolved for display. Returns None
    rather than a default: a fabricated 0.55 shown next to a real amount is
    worse than an honest "no contract on file", because AJ would reasonably
    trust it. (commission_line_resolve has a 0.55 fallback for its own MATH --
    that is deliberate there and must not be copied here.)

    `cache` is an optional dict, keyed (agent_id, carrier.lower()), so a caller
    serializing many rows resolves each pair once.
    """
    if not agent_id or not carrier:
        return None
    key = (agent_id, carrier.strip().lower())
    if cache is not None and key in cache:
        return cache[key]
    from app.models import AgentCarrierContract
    c = (AgentCarrierContract.query
         .filter_by(agent_id=agent_id, carrier=carrier, is_active=True,
                    agency_id=agency_id)
         .first())
    rate = c.split_rate if c else None
    if cache is not None:
        cache[key] = rate
    return rate
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_recap.py -q -k contract_rate_for`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/commission/recap.py tests/test_commission_recap.py
git commit -m "feat: contract_rate_for() — one source for an agent's carrier rate"
```

---

### Task 2: Carry the rate in `fidelity_row()`

**Files:**
- Modify: `app/commission/recap.py:474-510` (`fidelity_row`), and `fidelity_view` (same file, ~line 513) to pass a shared cache
- Test: `tests/test_commission_recap.py`

**Interfaces:**
- Consumes: `contract_rate_for(agent_id, carrier, agency_id, cache)` from Task 1
- Produces: `fidelity_row(li, agent_names=None, rate_cache=None)` — the returned dict gains two keys: `contract_rate` (`float | None`) and `off_contract` (`bool`, True when the row's stored `split_rate` differs from the contract by more than 0.0005 **and** a contract exists)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_commission_recap.py`:

```python
def test_fidelity_row_exposes_contract_rate_and_off_contract_flag(app_ctx):
    """The Fidelity table builds its edit form in JS from this row dict, so the
    rate must travel in JSON -- rendering it per row would re-inflate the ~4k-row
    DOM that merge 50a7f4a shrank."""
    from app.extensions import db
    from app.models import (User, AgentCarrierContract, Agency,
                            CommissionStatement, CommissionLineItem)
    from app.commission.recap import fidelity_row
    from datetime import date
    app, agency_id = app_ctx

    mike = User(email="m@x.com", name="Mike Lauzurique",
                agency_id=agency_id, role="agent")
    db.session.add(mike); db.session.flush()
    db.session.add(AgentCarrierContract(agent_id=mike.id, carrier="UHC",
                                        agency_id=agency_id, is_active=True,
                                        split_rate=0.525))
    stmt = CommissionStatement(agency_id=agency_id, carrier="UHC",
                               period_label="July 2026", filename="u.xlsx",
                               statement_date=date(2026, 7, 1))
    db.session.add(stmt); db.session.flush()

    on = CommissionLineItem(agency_id=agency_id, statement_id=stmt.id,
                            carrier="UHC", source_ref="uhc::0::1",
                            agent_id=mike.id, raw_amount=4.59, split_rate=0.525,
                            classification="agent_commission",
                            member_name="ON, CONTRACT")
    off = CommissionLineItem(agency_id=agency_id, statement_id=stmt.id,
                             carrier="UHC", source_ref="uhc::0::2",
                             agent_id=mike.id, raw_amount=4.59, split_rate=1.0,
                             classification="agent_commission",
                             member_name="OFF, CONTRACT")
    db.session.add_all([on, off]); db.session.flush()

    r_on = fidelity_row(on)
    assert r_on["contract_rate"] == 0.525
    assert r_on["off_contract"] is False

    r_off = fidelity_row(off)
    assert r_off["contract_rate"] == 0.525
    assert r_off["off_contract"] is True, "stored 1.0 vs contract 0.525"


def test_fidelity_row_no_contract_is_not_off_contract(app_ctx):
    """No contract on file means we cannot judge the rate -- report None and do
    NOT flag the row, or every unattributed line screams false alarm."""
    from app.extensions import db
    from app.models import User, CommissionStatement, CommissionLineItem
    from app.commission.recap import fidelity_row
    from datetime import date
    app, agency_id = app_ctx

    u = User(email="n@x.com", name="No Contract", agency_id=agency_id, role="agent")
    db.session.add(u); db.session.flush()
    stmt = CommissionStatement(agency_id=agency_id, carrier="UHC",
                               period_label="July 2026", filename="u.xlsx",
                               statement_date=date(2026, 7, 1))
    db.session.add(stmt); db.session.flush()
    li = CommissionLineItem(agency_id=agency_id, statement_id=stmt.id,
                            carrier="UHC", source_ref="uhc::0::3",
                            agent_id=u.id, raw_amount=10.0, split_rate=1.0,
                            classification="agent_commission",
                            member_name="NO, CONTRACT")
    db.session.add(li); db.session.flush()

    r = fidelity_row(li)
    assert r["contract_rate"] is None
    assert r["off_contract"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_recap.py -q -k fidelity_row_exposes`
Expected: FAIL with `KeyError: 'contract_rate'`

- [ ] **Step 3: Write minimal implementation**

In `app/commission/recap.py`, change the `fidelity_row` signature and add the two keys.

Change the `def` line from:

```python
def fidelity_row(li, agent_names=None):
```

to:

```python
def fidelity_row(li, agent_names=None, rate_cache=None):
```

Then, immediately before the `return {` statement, insert:

```python
    # The agent's contracted rate for this carrier, so the edit form can show it
    # and flag a stored rate that contradicts it. None = no contract on file;
    # a row is never flagged off-contract on a rate we cannot verify.
    contract_rate = contract_rate_for(li.agent_id, li.carrier, li.agency_id,
                                      rate_cache)
    off_contract = (contract_rate is not None
                    and li.split_rate is not None
                    and abs((li.split_rate or 0.0) - contract_rate) > 0.0005)
```

And add these two entries inside the returned dict, right after `"split_rate": li.split_rate,`:

```python
        "contract_rate": contract_rate,
        "off_contract": off_contract,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_recap.py -q -k "fidelity_row_exposes or no_contract_is_not"`
Expected: 2 passed

- [ ] **Step 5: Pass a shared cache from the table builder**

In `fidelity_view` (same file), find the loop that calls `fidelity_row(...)` for each line item. Create one cache before the loop and pass it in. For example, if the code reads:

```python
        rows.append(fidelity_row(li, agent_names))
```

change it to:

```python
        rows.append(fidelity_row(li, agent_names, rate_cache))
```

and add, before that loop begins:

```python
    rate_cache = {}   # (agent_id, carrier) -> rate; resolved once per pair, not per row
```

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 735 passed (731 + 4 new)

- [ ] **Step 7: Commit**

```bash
git add app/commission/recap.py tests/test_commission_recap.py
git commit -m "feat: fidelity_row carries contract_rate + off_contract flag"
```

---

### Task 3: Server-side off-contract guard

**Files:**
- Modify: `app/commission/routes.py:1591-1632` (`commission_line_edit`)
- Test: `tests/test_commission_audit_undo.py`

**Interfaces:**
- Consumes: `contract_rate_for` (Task 1); the existing `edit_line_split(li, agent_amount, override_amount, agent_id, user_id)`
- Produces: `commission_line_edit` rejects an off-contract save with HTTP 400 and `{"ok": false, "error": ..., "needs_confirm": true, "contract_rate": <float>}` unless the request includes `confirm_off_contract=1`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_commission_audit_undo.py`:

```python
def test_edit_off_contract_requires_confirmation(client_admin):
    """A save that pays a 52.5% agent 100% must not go through silently. This is
    the guard for the 2026-08-01/03 incidents: AJ typed the commission base into
    a form that stores it as the FINAL payout, and nothing warned him."""
    app, agency_id, client, line_id = client_admin      # 4.85 row, agent @ 0.525

    res = client.post(f"/admin/commissions/line/{line_id}/edit",
                      data={"agent_id": "1", "agent_amount": "4.85",
                            "override_amount": "0.00"},
                      headers={"X-Requested-With": "XMLHttpRequest",
                               "Accept": "application/json"})
    assert res.status_code == 400
    body = res.get_json()
    assert body["ok"] is False
    assert body["needs_confirm"] is True
    assert "52.5" in body["error"] or "0.525" in body["error"]


def test_edit_off_contract_succeeds_with_confirmation(client_admin):
    """Confirm-and-proceed, never block: Anjana Patel's non-Cannon-Pharmacy 100%
    is exactly this shape every month and must stay ONE extra click."""
    from app.models import CommissionLineItem
    app, agency_id, client, line_id = client_admin

    res = client.post(f"/admin/commissions/line/{line_id}/edit",
                      data={"agent_id": "1", "agent_amount": "4.85",
                            "override_amount": "0.00",
                            "confirm_off_contract": "1"},
                      headers={"X-Requested-With": "XMLHttpRequest",
                               "Accept": "application/json"})
    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    li = CommissionLineItem.query.get(line_id)
    assert li.split_rate == 1.0          # storage convention unchanged


def test_edit_on_contract_needs_no_confirmation(client_admin):
    """An amount consistent with the contract saves in one click, as today."""
    app, agency_id, client, line_id = client_admin   # raw 4.85, contract 0.525
    # 4.85 * 0.525 = 2.546 -> 2.55 to the agent, 2.30 to Founders
    res = client.post(f"/admin/commissions/line/{line_id}/edit",
                      data={"agent_id": "1", "agent_amount": "2.55",
                            "override_amount": "2.30"},
                      headers={"X-Requested-With": "XMLHttpRequest",
                               "Accept": "application/json"})
    assert res.status_code == 200
    assert res.get_json()["ok"] is True
```

Add this fixture to the same file if one does not already exist:

```python
@pytest.fixture
def client_admin():
    """An admin-logged-in test client plus one UHC line item (raw 4.85) whose
    agent is contracted at 0.525."""
    from app import create_app
    from app.extensions import db
    from app.models import (Agency, User, AgentCarrierContract,
                            CommissionStatement, CommissionLineItem)
    from datetime import date
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False, WTF_CSRF_ENABLED=False)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        admin = User(id=1, email="admin@foundersinsuranceagency.com",
                     name="AJ Admin", agency_id=ag.id, role="admin",
                     is_admin=True)
        db.session.add(admin); db.session.flush()
        db.session.add(AgentCarrierContract(agent_id=admin.id, carrier="UHC",
                                            agency_id=ag.id, is_active=True,
                                            split_rate=0.525))
        stmt = CommissionStatement(agency_id=ag.id, carrier="UHC",
                                   period_label="July 2026", filename="u.xlsx",
                                   statement_date=date(2026, 7, 1))
        db.session.add(stmt); db.session.flush()
        li = CommissionLineItem(agency_id=ag.id, statement_id=stmt.id,
                                carrier="UHC", source_ref="uhc::0::1",
                                agent_id=admin.id, raw_amount=4.85,
                                split_rate=0.525,
                                classification="agent_commission",
                                member_name="TEST, MEMBER")
        db.session.add(li); db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(admin.id)
            sess["_fresh"] = True
        yield app, ag.id, client, li.id
        db.session.remove(); db.drop_all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_audit_undo.py -q -k off_contract`
Expected: FAIL — the first test gets 200 instead of 400 (no guard exists yet)

- [ ] **Step 3: Write minimal implementation**

In `app/commission/routes.py`, inside `commission_line_edit`, insert this block **after** the `agent_amount` / `override_amount` parsing (`except ValueError: return _fail("Enter valid amounts.")`) and **before** the `edit_line_split(...)` call:

```python
    # Off-contract guard. edit_line_split stores agent_amount as the FINAL payout
    # (split_rate=1.0), so an entry equal to the whole line pays the agent 100%.
    # That is CORRECT for Anjana Patel (she keeps 100% on non-Cannon-Pharmacy
    # customers) and WRONG everywhere else -- and the two are indistinguishable
    # without asking. Require one explicit confirmation rather than blocking.
    from app.commission.recap import contract_rate_for
    contract_rate = contract_rate_for(agent.id, li.carrier, current_user.agency_id)
    combined = round((li.raw_amount or 0.0) + sum(
        (s.raw_amount or 0.0) for s in CommissionLineItem.query.filter_by(
            statement_id=li.statement_id, agency_id=current_user.agency_id,
            source_ref=f"{li.source_ref}::ovr").all()), 2)
    confirmed = request.form.get("confirm_off_contract") in ("1", "true", "on")
    if contract_rate is not None and not confirmed and abs(combined) >= 0.005:
        expected_agent = round(combined * contract_rate, 2)
        if abs(round(agent_amount, 2) - expected_agent) > 0.005:
            msg = (f"{agent.display_name}'s {li.carrier} contract is "
                   f"{contract_rate * 100:g}%, which pays "
                   f"${expected_agent:,.2f} of ${combined:,.2f}. "
                   f"This saves ${agent_amount:,.2f} to the agent and "
                   f"${override_amount:,.2f} to Founders.")
            if wants_json:
                return jsonify(ok=False, error=msg, needs_confirm=True,
                               contract_rate=contract_rate,
                               expected_agent=expected_agent), 400
            flash(msg + " Re-submit with confirmation to save anyway.", "error")
            return redirect(back)
```

`CommissionLineItem` is already imported at the top of `routes.py`; confirm it is in scope in this function and add it to the local imports if not.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_audit_undo.py -q -k off_contract`
Expected: 3 passed

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 738 passed

- [ ] **Step 6: Commit**

```bash
git add app/commission/routes.py tests/test_commission_audit_undo.py
git commit -m "feat: commission edit requires confirmation for an off-contract split"
```

---

### Task 4: Rate + live preview on the Fidelity edit form

**Files:**
- Modify: `app/templates/commission_fidelity.html:299-345` (the `openEditorFor` JS builder and its save handler)

**Interfaces:**
- Consumes: `row.contract_rate` / `row.off_contract` from `fidelity_row()` (Task 2); the 400 + `needs_confirm` response from Task 3
- Produces: no new server interface — UI only

- [ ] **Step 1: Carry the rate onto the row element**

In `commission_fidelity.html`, find where each `<tr>` is rendered with its `data-` attributes (`data-raw`, `data-agent-id`, `data-agent-amt`, …) and add two more, alongside the existing ones:

```html
data-contract-rate="{{ '' if r.contract_rate is none else r.contract_rate }}"
data-off-contract="{{ '1' if r.off_contract else '' }}"
```

- [ ] **Step 2: Show the rate and a live preview in the editor**

In the `openEditorFor(row)` function, after the existing `var agentId=...` line, add:

```javascript
    var contractRate=row.getAttribute('data-contract-rate');
    contractRate = (contractRate === '' || contractRate === null) ? null : parseFloat(contractRate);
```

Then in `form.innerHTML`, insert a rate line and a preview span. Replace the existing first line:

```javascript
      '<span class="fd-ef-lbl">Correct the split for <strong></strong> (must total '+fmt(raw)+'):</span>'+
```

with:

```javascript
      '<span class="fd-ef-lbl">Correct the split for <strong></strong> (must total '+fmt(raw)+'):</span>'+
      '<span class="fd-ef-rate"></span>'+
```

and add, immediately after the `.fd-ef-sum` span:

```javascript
      '<span class="fd-ef-preview"></span>'+
```

- [ ] **Step 3: Populate the rate line and preview**

After the existing `var sumEl=..., saveBtn=..., errEl=...` declarations, add:

```javascript
    var rateEl=form.querySelector('.fd-ef-rate'),
        prevEl=form.querySelector('.fd-ef-preview');

    function rateLabel(){
      var name = agentSel2.options[agentSel2.selectedIndex];
      name = name ? name.text : 'this agent';
      if(contractRate === null || isNaN(contractRate)){
        return name + ' — no contract on file for this carrier';
      }
      return name + ' — contract ' + (contractRate*100).toFixed(1).replace(/\.0$/,'') + '%';
    }

    // Show the OUTCOME in dollars, not the convention. That is what makes the
    // edit form (two boxes = exact dollars) self-describing next to the resolve
    // form (one box = split at contract), without a label AJ has to interpret.
    function preview(){
      rateEl.textContent = rateLabel();
      var a=parseFloat(ag.value)||0, o=parseFloat(ov.value)||0, t=a+o;
      if(Math.abs(t)<0.005){ prevEl.textContent=''; prevEl.className='fd-ef-preview'; return; }
      var pct = Math.round((a/t)*1000)/10;
      var txt = '→ agent gets '+fmt(a)+' of '+fmt(t)+' ('+pct+'%)';
      var off = (contractRate !== null && !isNaN(contractRate) &&
                 Math.abs(a - Math.round(t*contractRate*100)/100) > 0.005);
      prevEl.textContent = txt + (off ? '  ⚠ not their contract rate' : '');
      prevEl.className = 'fd-ef-preview' + (off ? ' warn' : '');
    }
    ag.addEventListener('input', preview);
    ov.addEventListener('input', preview);
    agentSel2.addEventListener('change', preview);
    preview();
```

- [ ] **Step 4: Handle the confirmation round-trip in the save handler**

In the `saveBtn` click handler, the `body` is built with `URLSearchParams`. Add a module-scoped flag and resend on confirmation. Immediately before `var body=new URLSearchParams();` add:

```javascript
      var confirmOff = form.getAttribute('data-confirmed') === '1';
```

and after `body.set('override_amount', ov.value||'0');` add:

```javascript
      if(confirmOff) body.set('confirm_off_contract','1');
```

Then in the `.then(function(j){ ... })` handler, replace the existing failure branch:

```javascript
          if(!j.ok){ errEl.textContent=j.error||'Could not save.'; saveBtn.disabled=false; return; }
```

with:

```javascript
          if(!j.ok){
            if(j.needs_confirm){
              // One explicit click turns a silent mistake into a decision.
              if(window.confirm(j.error + '\n\nSave anyway?')){
                form.setAttribute('data-confirmed','1');
                saveBtn.disabled=false;
                saveBtn.click();
                return;
              }
              errEl.textContent='Not saved.'; saveBtn.disabled=false; return;
            }
            errEl.textContent=j.error||'Could not save.'; saveBtn.disabled=false; return;
          }
```

- [ ] **Step 5: Style the new elements**

In the same template's `{% block styles %}`, add:

```css
  .fd-ef-rate{font-size:12px;color:var(--slate);margin-right:10px;white-space:nowrap}
  .fd-ef-preview{font-size:12px;color:var(--slate);margin-left:8px}
  .fd-ef-preview.warn{color:#C0392B;font-weight:600}
  tr[data-off-contract="1"] .js-agent-amt::after{content:" ⚠";color:#C0392B}
```

- [ ] **Step 6: Verify in a browser**

Start the app locally (`python3 -m flask run`), open a UHC statement's Fidelity view, click **Edit** on a row, and confirm:
1. The agent's name and contract rate render next to the picker.
2. Typing in "Agent $" updates the preview line with the dollar outcome and percentage.
3. Entering the full line amount for a non-100% agent shows the ⚠ warning and, on Save, prompts once before persisting.
4. A row already stored off-contract shows the ⚠ marker in the table without opening the editor.

- [ ] **Step 7: Commit**

```bash
git add app/templates/commission_fidelity.html
git commit -m "feat: Fidelity edit form shows contract rate, live preview, confirm on mismatch"
```

---

### Task 5: Rate + preview on the three server-rendered forms

**Files:**
- Modify: `app/templates/commission_quarantine.html:149-160`
- Modify: `app/templates/commission_quarantine_workbench.html:250-262`
- Modify: `app/templates/commission_review.html:~155-168`

**Interfaces:**
- Consumes: `contract_rate_for` (Task 1), exposed to these templates by their routes
- Produces: none (UI only)

- [ ] **Step 1: Expose the rate to the templates**

Each of these three views renders rows from a builder in `app/commission/recap.py` (`quarantined_line_items`, `quarantine_workbench`, `period_quarantine`). In each builder's per-row dict, add the same two keys used in Task 2, reusing one cache per call:

```python
        "contract_rate": contract_rate_for(li.agent_id, li.carrier,
                                           li.agency_id, rate_cache),
```

Declare `rate_cache = {}` once at the top of each builder function, before its row loop.

- [ ] **Step 2: Render the rate beside each agent picker**

In all three templates, immediately after the `</select>` that closes the `agent_id` picker inside the **edit** form, add:

```html
              <span class="ef-rate" data-rate="{{ '' if r.contract_rate is none else r.contract_rate }}">
                {%- if r.contract_rate is none -%}
                  no contract on file
                {%- else -%}
                  contract {{ (r.contract_rate * 100) | round(1) }}%
                {%- endif -%}
              </span>
```

- [ ] **Step 3: Add the live preview**

In each template's existing inline `<script>` (the workbench already has one for the resolve form's preview), append a block that mirrors the Fidelity preview for the edit forms:

```javascript
  // Edit forms take TWO amounts (exact dollars). Show the resulting split so the
  // convention is visible in dollars rather than implied by the number of boxes.
  (function () {
    function fmt(n){ return '$' + n.toLocaleString('en-US',{minimumFractionDigits:2, maximumFractionDigits:2}); }
    document.querySelectorAll('form.edit-form').forEach(function (f) {
      var ag=f.querySelector('[name=agent_amount]'), ov=f.querySelector('[name=override_amount]'),
          rateEl=f.querySelector('.ef-rate');
      if(!ag || !ov) return;
      var prev=document.createElement('span');
      prev.className='ef-preview';
      f.insertBefore(prev, f.querySelector('button[type=submit]'));
      function upd(){
        var rate=rateEl ? parseFloat(rateEl.getAttribute('data-rate')) : NaN;
        var a=parseFloat(ag.value)||0, o=parseFloat(ov.value)||0, t=a+o;
        if(Math.abs(t)<0.005){ prev.textContent=''; prev.className='ef-preview'; return; }
        var off = !isNaN(rate) && Math.abs(a - Math.round(t*rate*100)/100) > 0.005;
        prev.textContent='→ agent '+fmt(a)+' of '+fmt(t)+(off?'  ⚠ not their contract rate':'');
        prev.className='ef-preview'+(off?' warn':'');
      }
      ag.addEventListener('input',upd); ov.addEventListener('input',upd); upd();
    });
  })();
```

- [ ] **Step 4: Add a hidden confirmation field for the no-JS path**

In each of the three **edit** forms, before the submit button, add:

```html
              <input type="hidden" name="confirm_off_contract" value="" class="ef-confirm">
```

and in the script from Step 3, set it when the user accepts the warning on submit:

```javascript
      f.addEventListener('submit', function (e) {
        var rate=rateEl ? parseFloat(rateEl.getAttribute('data-rate')) : NaN;
        var a=parseFloat(ag.value)||0, o=parseFloat(ov.value)||0, t=a+o;
        if(isNaN(rate) || Math.abs(t)<0.005) return;
        if(Math.abs(a - Math.round(t*rate*100)/100) <= 0.005) return;
        if(!window.confirm('That pays the agent '+fmt(a)+' of '+fmt(t)+
                           ', not their contract rate. Save anyway?')){
          e.preventDefault(); return;
        }
        var h=f.querySelector('.ef-confirm'); if(h) h.value='1';
      });
```

- [ ] **Step 5: Style**

Add to each template's `{% block styles %}`:

```css
  .ef-rate{font-size:12px;color:var(--slate);margin:0 8px;white-space:nowrap}
  .ef-preview{font-size:12px;color:var(--slate);margin:0 8px}
  .ef-preview.warn{color:#C0392B;font-weight:600}
```

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 738 passed (no new tests here — these are template changes covered by Task 3's server guard)

- [ ] **Step 7: Commit**

```bash
git add app/templates/commission_quarantine.html \
        app/templates/commission_quarantine_workbench.html \
        app/templates/commission_review.html \
        app/commission/recap.py
git commit -m "feat: show contract rate + split preview on quarantine/review edit forms"
```

---

### Task 6: Verify against real production data

**Files:**
- Create: `scripts/check_off_contract_rows.py`

**Interfaces:**
- Consumes: `contract_rate_for` (Task 1)
- Produces: a read-only report; no writes

- [ ] **Step 1: Write the reporting script**

```python
"""READ-ONLY: list every line item whose stored split_rate disagrees with the
agent's contract for that carrier.

Run before and after deploying the edit-form guard. Known-legitimate rows will
still appear -- Anjana Patel keeps 100% on non-Cannon-Pharmacy customers and
Betty Marlowe is paid a flat $100/application plus hourly direct from Brian --
so this is a REVIEW list, not a defect list. See BACKLOG.md 'split_rate=1.0 is
an OVERLOADED marker'.

    ./venv/bin/python3 scripts/check_off_contract_rows.py
"""
import sys
from collections import defaultdict

from app import create_app
from app.models import CommissionLineItem, CommissionStatement, User
from app.commission.recap import contract_rate_for
from app.commission.ledger import split_breakdown


def main():
    app = create_app()
    with app.app_context():
        users = {u.id: u.name for u in User.query.all()}
        cache = {}
        groups = defaultdict(lambda: {"n": 0, "delta": 0.0})
        for li in CommissionLineItem.query.filter(
                CommissionLineItem.agent_id.isnot(None),
                CommissionLineItem.split_rate.isnot(None)).all():
            rate = contract_rate_for(li.agent_id, li.carrier, li.agency_id, cache)
            if rate is None or abs((li.split_rate or 0) - rate) <= 0.0005:
                continue
            st = CommissionStatement.query.get(li.statement_id)
            paid, _ = split_breakdown(li)
            should = (li.raw_amount or 0) * rate
            key = (li.carrier, st.period_label if st else "?",
                   users.get(li.agent_id, "?"), li.split_rate, rate)
            groups[key]["n"] += 1
            groups[key]["delta"] += (paid - should)

        if not groups:
            print("No rows disagree with their agent's contract rate.")
            return 0
        print("%-10s %-13s %-20s %7s %8s %5s %10s"
              % ("carrier", "period", "agent", "stored", "contract", "rows", "delta"))
        total = 0.0
        for key in sorted(groups, key=lambda k: -abs(groups[k]["delta"])):
            car, per, nm, stored, rate = key
            d = groups[key]
            total += d["delta"]
            print("%-10s %-13s %-20s %7s %8s %5d %10.2f"
                  % (car, per, nm[:20], stored, rate, d["n"], d["delta"]))
        print("%-58s %10.2f" % ("TOTAL (review, not all errors)", total))
        return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it against production**

```bash
scp -i ~/.ssh/id_ed25519 scripts/check_off_contract_rows.py \
    root@23.187.248.100:/var/www/founders-portal/scripts/
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100 \
  'cd /var/www/founders-portal && PYTHONPATH=/var/www/founders-portal \
   ./venv/bin/python3 scripts/check_off_contract_rows.py'
```

Expected: Anjana Patel's rows and the `$0.00` cosmetic rows appear; **no** Mike, Rebekah or PARTD rows (those were corrected on 2026-08-01/03). Any new name is a genuine finding.

- [ ] **Step 3: Commit**

```bash
git add scripts/check_off_contract_rows.py
git commit -m "chore: read-only report of rows whose split_rate disagrees with contract"
```

---

### Task 7: Deploy and live-verify

**Files:** none (deployment)

- [ ] **Step 1: Confirm the suite is green**

Run: `python3 -m pytest -q`
Expected: 738 passed

- [ ] **Step 2: Merge and push**

```bash
git checkout main && git merge --no-ff <branch> && git push origin main
```

- [ ] **Step 3: Deploy (no migration)**

```bash
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100 \
  'cd /var/www/founders-portal && git pull && \
   ./venv/bin/pip install -r requirements.txt && \
   systemctl restart founders-portal'
```

- [ ] **Step 4: Confirm the restart actually cycled**

```bash
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100 \
  'systemctl show founders-portal -p ActiveEnterTimestamp && \
   systemctl is-active founders-portal && \
   curl -s -o /dev/null -w "login:%{http_code}\n" \
     https://portal.foundersinsuranceagency.com/auth/login && \
   journalctl -u founders-portal --since "2 minutes ago" -p err --no-pager | tail -5'
```

Expected: the timestamp is later than before the restart, service `active`, login `200`, no error entries.

- [ ] **Step 5: Live-verify in the browser**

On a real UHC statement's Fidelity view: the contract rate renders in the edit form, the preview updates while typing, an off-contract save prompts once and then persists, and an already-off-contract row shows ⚠ in the table.

- [ ] **Step 6: Re-run the report**

Run the Task 6 script again on production and confirm the output is unchanged (the guard changes future saves; it does not rewrite history).

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §3.1 Surface the rate | 1, 2, 5 |
| §3.2 Live preview on the edit form | 4, 5 |
| §3.3 Mismatch warning + server guard | 3, 4, 5 |
| §3.4 `edit_line_split` unchanged | enforced by Global Constraints; asserted in Task 3 Step 1 |
| §4 All four affected surfaces | 4 (Fidelity), 5 (quarantine, workbench, review) |
| §5.1 rate `None`, never fabricated | Task 1 Step 1 |
| §5.2 off-contract rejected without confirm | Task 3 |
| §5.3 on-contract needs no confirm | Task 3 |
| §5.4 Anjana's case still one click | Task 3 Step 1 (`..._succeeds_with_confirmation`) |
| §5.5 ledger/regression unchanged | Full-suite runs in Tasks 2, 3, 5 |
| §5.6 Fidelity DOM does not regress | Task 2 (rate in JSON) + Task 4 Step 1 (two `data-` attrs, no new markup) |
| §6 Rollout | Task 7 |

**Placeholder scan:** none — every code step contains the literal code to write.

**Type consistency:** `contract_rate_for(agent_id, carrier, agency_id, cache=None) -> float | None` is defined in Task 1 and used with that exact signature in Tasks 2, 3, 5 and 6. The row keys `contract_rate` and `off_contract` are introduced in Task 2 and consumed under those names in Tasks 4 and 5. The request field `confirm_off_contract` is defined in Task 3 and sent in Tasks 4 and 5.
