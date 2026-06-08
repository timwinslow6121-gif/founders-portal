# Customer Inline Edit UI Implementation Plan (Sub-project B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add inline click-to-edit for customer fields + a "painfully obvious" conflict-resolution cell to the customer profile, writing through the Sub-project A provenance engine — plus the engine's rejected-value memory so resolved conflicts don't re-nag.

**Architecture:** First enhance `app/customer_provenance.py` (rejected-value memory: `set_human_value` clears it, `resolve_conflict` records it, `set_import_value` suppresses re-flagging it → new `'suppressed'` action). Then add two AJAX routes in `app/customers.py` (`/field` save, `/resolve-conflict`) gated by the existing `_is_current_aor`/admin rule. Then update `customer_profile.html` to render fields as click-to-edit (clean by default) and conflicts as a red Option-A cell with inline Keep mine / Use carrier's. Mirrors the profile's existing inline-AJAX pattern (FormData + fetch POST, no CSRF token).

**Tech Stack:** Python 3.10, Flask, Flask-SQLAlchemy, vanilla JS (FormData + fetch), Jinja2; pytest SQLite + Flask test client (fixtures: `app`, `db_session`, `agency`, `agent_user`, `admin_user`, `customer`).

**Reference spec:** `docs/superpowers/specs/2026-06-05-customer-edit-ui-design.md`. Engine: `app/customer_provenance.py` (Sub-project A). Conventions: existing inline routes in `app/customers.py` (e.g. `customer_link_pharmacy` ~584) + the fetch JS in `customer_profile.html` ~507.

---

## File Structure

- **Modify** `app/customer_provenance.py` — rejected-value memory (`resolve_conflict`, `set_import_value`, `set_human_value`).
- **Modify** `tests/test_customer_provenance.py` — engine-enhancement tests.
- **Modify** `app/customers.py` — two new routes: `customer_set_field`, `customer_resolve_conflict`.
- **Create** `tests/test_customer_edit.py` — route + permission tests.
- **Modify** `app/templates/customer_profile.html` — inline-edit fields + conflict cell + JS.

No migration (reuses A's `field_provenance`/`has_unresolved_conflicts`; `rejected_values` is a key inside the existing JSON blob).

---

### Task 1: Engine — rejected-value memory

**Files:**
- Modify: `app/customer_provenance.py`
- Test: `tests/test_customer_provenance.py`

Three additive changes: `resolve_conflict('keep_current')` records the rejected incoming value; `set_import_value` returns `'suppressed'` for an already-rejected value; `set_human_value` clears the field's `rejected_values`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_customer_provenance.py`:
```python
def test_keep_current_records_rejected_then_suppresses_reimport(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "email", "m@old.com", agent_user); db.session.flush()
        cp.set_import_value(c, "email", "mark@gmail.com", "bob_import"); db.session.flush()
        # agent keeps their value -> the carrier value is now "rejected"
        cp.resolve_conflict(c, "email", "keep_current", agent_user); db.session.flush()

        # SAME carrier value comes again next import -> suppressed, no new conflict
        action = cp.set_import_value(c, "email", "mark@gmail.com", "bob_import")
        db.session.flush()
        assert action == "suppressed"
        assert cp.list_conflicts(c) == []
        assert c.has_unresolved_conflicts is False
        assert c.email == "m@old.com"


def test_new_different_value_still_flags_after_rejection(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "email", "m@old.com", agent_user); db.session.flush()
        cp.set_import_value(c, "email", "mark@gmail.com", "bob_import"); db.session.flush()
        cp.resolve_conflict(c, "email", "keep_current", agent_user); db.session.flush()

        # a DIFFERENT new carrier value -> still flags (genuinely new info)
        action = cp.set_import_value(c, "email", "mark@newjob.com", "bob_import")
        db.session.flush()
        assert action == "conflict_flagged"
        assert len(cp.list_conflicts(c)) == 1


def test_take_incoming_records_no_rejection(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "email", "m@old.com", agent_user); db.session.flush()
        cp.set_import_value(c, "email", "mark@gmail.com", "bob_import"); db.session.flush()
        cp.resolve_conflict(c, "email", "take_incoming", agent_user); db.session.flush()
        # agent took the carrier value; the field is now mark@gmail.com (human_verified)
        assert c.email == "mark@gmail.com"
        rec = cp.get_field(c, "email")
        assert rec.get("rejected_values", []) == []


def test_fresh_human_edit_clears_rejected_values(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "email", "m@old.com", agent_user); db.session.flush()
        cp.set_import_value(c, "email", "mark@gmail.com", "bob_import"); db.session.flush()
        cp.resolve_conflict(c, "email", "keep_current", agent_user); db.session.flush()
        assert cp.get_field(c, "email").get("rejected_values") == ["mark@gmail.com"]

        # agent re-edits the field -> rejected list cleared
        cp.set_human_value(c, "email", "m@new.com", agent_user); db.session.flush()
        assert cp.get_field(c, "email").get("rejected_values", []) == []
        # and now that previously-rejected value would flag again
        action = cp.set_import_value(c, "email", "mark@gmail.com", "bob_import")
        assert action == "conflict_flagged"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_customer_provenance.py -k "rejected or suppress or take_incoming_records or fresh_human_edit_clears" -v`
Expected: FAIL — `set_import_value` returns `conflict_flagged` (not `suppressed`); `rejected_values` key absent.

- [ ] **Step 3: Implement in `app/customer_provenance.py`**

Change 3a — `set_human_value` clears `rejected_values`. In `set_human_value`, the `meta[field] = {...}` dict assignment does NOT currently include `rejected_values`; since it rebuilds the record, the key is naturally dropped. Confirm by adding an explicit empty default so intent is clear — change the `meta[field] = {` block to include:
```python
    meta[field] = {
        "value": scalar,
        "source": "aj_verified" if verify else "agent_edit",
        "trust": "human_verified" if verify else "agent_entered",
        "updated_at": _now(),
        "updated_by": getattr(user, "name", None),
        "history": history,
        "rejected_values": [],
    }
```

Change 3b — `set_import_value` suppresses already-rejected values. In `set_import_value`, in the conflict branch (where `trust in ("agent_entered", "human_verified")`), BEFORE calling `_flag_conflict`, check the rejected list. Replace:
```python
    if trust in ("agent_entered", "human_verified"):
        _flag_conflict(data, customer, field, existing, scalar, source)
        _save(customer, data)
        customer.has_unresolved_conflicts = True
        return "conflict_flagged"
```
with:
```python
    if trust in ("agent_entered", "human_verified"):
        rejected = existing.get("rejected_values", [])
        if scalar in rejected:
            # agent already rejected this exact carrier value — don't re-nag
            existing.setdefault("history", []).append(
                {"at": _now(), "by": None, "from": existing.get("value"),
                 "to": scalar, "note": f"import:{source} suppressed (previously rejected)"})
            _save(customer, data)
            return "suppressed"
        _flag_conflict(data, customer, field, existing, scalar, source)
        _save(customer, data)
        customer.has_unresolved_conflicts = True
        return "conflict_flagged"
```

Change 3c — `resolve_conflict` records the rejected value on `keep_current`. In `resolve_conflict`, after computing `surviving` and BEFORE rebuilding `meta[field]`, capture the rejected value. The rejected value on `keep_current` is the conflict's incoming value; on `take_incoming` nothing is rejected. Modify the `meta[field] = {...}` block in `resolve_conflict` to carry `rejected_values`:
```python
    prior_rejected = rec.get("rejected_values", [])
    if choose == "keep_current" and incoming is not None and incoming not in prior_rejected:
        prior_rejected = prior_rejected + [incoming]

    history = rec.get("history", [])
    history.append({"at": _now(), "by": getattr(user, "name", None),
                    "from": current, "to": surviving,
                    "note": note or f"conflict resolved ({choose})"})
    meta[field] = {
        "value": surviving, "source": "aj_verified", "trust": "human_verified",
        "updated_at": _now(), "updated_by": getattr(user, "name", None),
        "history": history,
        "rejected_values": prior_rejected,
    }
```
(Leave the conflict-marking loop and `has_unresolved_conflicts` recompute below it unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_customer_provenance.py -k "rejected or suppress or take_incoming_records or fresh_human_edit_clears" -v`
Expected: PASS (all 4).

- [ ] **Step 5: Run the whole provenance suite (no regression)**

Run: `python3 -m pytest tests/test_customer_provenance.py -v`
Expected: all green (prior 13 + 4 new). The earlier resolve_conflict tests must still pass (they don't assert on rejected_values, so the added key is harmless).

- [ ] **Step 6: Commit**

```bash
git add app/customer_provenance.py tests/test_customer_provenance.py
git commit -m "feat(customers): provenance rejected-value memory (suppress re-flag of already-rejected import value)"
```

---

### Task 2: Route — save a single field via set_human_value

**Files:**
- Modify: `app/customers.py`
- Test: `tests/test_customer_edit.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_customer_edit.py`:
```python
"""
tests/test_customer_edit.py

Route + permission tests for inline customer field editing and conflict resolution.
"""
from datetime import date


def _login(client, app, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def _make_customer(db, agency, agent):
    from app.models import Customer
    c = Customer(agency_id=agency.id, first_name="Mitchell", last_name="Thoma",
                 full_name="Mitchell Thoma", primary_agent_id=agent.id, source="bob")
    db.session.add(c); db.session.commit()
    return c


def test_current_aor_agent_can_save_field(client, app, agency, agent_user, db_session):
    from app.extensions import db
    from app.models import Customer
    from app import customer_provenance as cp
    with app.app_context():
        c = _make_customer(db, agency, agent_user)
        cid = c.id
    _login(client, app, agent_user.id)
    r = client.post(f"/customers/{cid}/field",
                    data={"field": "mbi", "value": "1AB2C34DE56"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    with app.app_context():
        c = Customer.query.get(cid)
        assert c.mbi == "1AB2C34DE56"
        assert cp.trust_of(c, "mbi") == "agent_entered"


def test_save_field_rejects_untracked_field(client, app, agency, agent_user, db_session):
    from app.extensions import db
    with app.app_context():
        c = _make_customer(db, agency, agent_user); cid = c.id
    _login(client, app, agent_user.id)
    r = client.post(f"/customers/{cid}/field",
                    data={"field": "deal_stage", "value": "Active"})
    assert r.status_code == 400


def test_save_field_unknown_customer_404(client, app, agency, agent_user, db_session):
    _login(client, app, agent_user.id)
    r = client.post("/customers/999999/field", data={"field": "mbi", "value": "X"})
    assert r.status_code == 404


def test_former_aor_agent_cannot_save_field(client, app, agency, db_session):
    from app.extensions import db
    from app.models import User, Customer
    with app.app_context():
        owner = User(email="owner@t.com", name="Owner", agency_id=agency.id)
        other = User(email="other@t.com", name="Other", agency_id=agency.id)
        db.session.add_all([owner, other]); db.session.flush()
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
                     primary_agent_id=owner.id, source="bob")
        db.session.add(c); db.session.commit()
        cid = c.id; other_id = other.id
    _login(client, app, other_id)   # not the AOR agent, not admin
    r = client.post(f"/customers/{cid}/field", data={"field": "mbi", "value": "X"})
    assert r.status_code in (403, 404)   # not visible OR not writable
```

NOTE on the former-AOR test: `_customer_query` may scope the customer out entirely for a non-AOR non-admin (→ 404) OR return it as former-AOR read-only (→ 403). Both are correct "can't edit" outcomes; the test accepts either. Confirm which by reading `_customer_query`/`_is_current_aor`; if a non-AOR agent can't see the customer at all, 404 is the path.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_customer_edit.py -k save_field -v`
Expected: FAIL — route `/customers/<id>/field` doesn't exist (404 for all, including the success case).

- [ ] **Step 3: Implement the route**

In `app/customers.py`, add the import near the top (with the other app imports):
```python
from app import customer_provenance as cp
```
Add this route (place it near the other inline customer routes, e.g. after `customer_link_pharmacy`):
```python
@customers_bp.route("/customers/<int:customer_id>/field", methods=["POST"])
@login_required
def customer_set_field(customer_id):
    """Inline-save a single provenance-tracked field via the provenance engine."""
    customer = _customer_query(include_former=True).filter_by(id=customer_id).first_or_404()
    if not (current_user.is_admin or _is_current_aor(customer)):
        return jsonify({"ok": False, "error": "not authorized to edit this customer"}), 403

    field = (request.form.get("field") or "").strip()
    if field not in cp.PROVENANCE_FIELDS:
        return jsonify({"ok": False, "error": f"{field} is not an editable field"}), 400

    value = (request.form.get("value") or "").strip() or None
    cp.set_human_value(customer, field, value, current_user)
    db.session.commit()
    return jsonify({"ok": True, "field": field,
                    "value": getattr(customer, field) if not isinstance(getattr(customer, field), (date,)) else getattr(customer, field).isoformat(),
                    "trust": cp.trust_of(customer, field)})
```
NOTE: ensure `jsonify` and `request` are imported in customers.py (they are used elsewhere — confirm with `grep -n "from flask import" app/customers.py`). `date` is needed for the dob serialization in the JSON response — add `from datetime import date` if not already imported (check first).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_customer_edit.py -k save_field -v`
Expected: PASS. The former-AOR test passes whether the gate yields 403 or the scope yields 404.

- [ ] **Step 5: Commit**

```bash
git add app/customers.py tests/test_customer_edit.py
git commit -m "feat(customers): inline field-save route via set_human_value (AOR-gated)"
```

---

### Task 3: Route — resolve a conflict

**Files:**
- Modify: `app/customers.py`
- Test: `tests/test_customer_edit.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_customer_edit.py`:
```python
def test_resolve_conflict_route_keep_current(client, app, agency, agent_user, db_session):
    from app.extensions import db
    from app.models import Customer
    from app import customer_provenance as cp
    with app.app_context():
        c = _make_customer(db, agency, agent_user)
        cp.set_human_value(c, "email", "m@old.com", agent_user)
        cp.set_import_value(c, "email", "mark@gmail.com", "bob_import")
        db.session.commit()
        cid = c.id
    _login(client, app, agent_user.id)
    r = client.post(f"/customers/{cid}/resolve-conflict",
                    data={"field": "email", "choose": "keep_current"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["has_unresolved_conflicts"] is False
    with app.app_context():
        c = Customer.query.get(cid)
        assert c.email == "m@old.com"
        assert cp.list_conflicts(c) == []


def test_resolve_conflict_route_bad_choice_400(client, app, agency, agent_user, db_session):
    from app.extensions import db
    with app.app_context():
        c = _make_customer(db, agency, agent_user); cid = c.id
    _login(client, app, agent_user.id)
    r = client.post(f"/customers/{cid}/resolve-conflict",
                    data={"field": "email", "choose": "bogus"})
    assert r.status_code == 400


def test_resolve_conflict_route_former_aor_blocked(client, app, agency, db_session):
    from app.extensions import db
    from app.models import User, Customer
    from app import customer_provenance as cp
    with app.app_context():
        owner = User(email="o2@t.com", name="Owner2", agency_id=agency.id)
        other = User(email="x2@t.com", name="Other2", agency_id=agency.id)
        db.session.add_all([owner, other]); db.session.flush()
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
                     primary_agent_id=owner.id, source="bob")
        db.session.add(c); db.session.commit()
        cid = c.id; other_id = other.id
    _login(client, app, other_id)
    r = client.post(f"/customers/{cid}/resolve-conflict",
                    data={"field": "email", "choose": "keep_current"})
    assert r.status_code in (403, 404)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_customer_edit.py -k resolve_conflict_route -v`
Expected: FAIL — route doesn't exist.

- [ ] **Step 3: Implement the route**

In `app/customers.py`, add after `customer_set_field`:
```python
@customers_bp.route("/customers/<int:customer_id>/resolve-conflict", methods=["POST"])
@login_required
def customer_resolve_conflict(customer_id):
    """Resolve a field conflict (keep_current | take_incoming) via the engine."""
    customer = _customer_query(include_former=True).filter_by(id=customer_id).first_or_404()
    if not (current_user.is_admin or _is_current_aor(customer)):
        return jsonify({"ok": False, "error": "not authorized"}), 403

    field = (request.form.get("field") or "").strip()
    choose = (request.form.get("choose") or "").strip()
    if choose not in ("keep_current", "take_incoming"):
        return jsonify({"ok": False, "error": "invalid choice"}), 400
    if field not in cp.PROVENANCE_FIELDS:
        return jsonify({"ok": False, "error": "invalid field"}), 400

    cp.resolve_conflict(customer, field, choose, current_user)
    db.session.commit()
    val = getattr(customer, field)
    return jsonify({"ok": True, "field": field,
                    "value": val.isoformat() if isinstance(val, date) else val,
                    "has_unresolved_conflicts": bool(customer.has_unresolved_conflicts)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_customer_edit.py -k resolve_conflict_route -v`
Expected: PASS (all 3).

- [ ] **Step 5: Run the whole edit-route file + full suite**

Run: `python3 -m pytest tests/test_customer_edit.py -v && python3 -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add app/customers.py tests/test_customer_edit.py
git commit -m "feat(customers): resolve-conflict route (keep_current/take_incoming, AOR-gated)"
```

---

### Task 4: Profile template — inline edit fields + clean default + history affordance

**Files:**
- Modify: `app/templates/customer_profile.html`
- Test: manual render check (template smoke via the route test below)

This task makes the Contact Info + identity fields click-to-edit for editable users. It passes a `can_edit` flag and per-field provenance to the template.

- [ ] **Step 1: Pass edit context from the profile route**

In `app/customers.py`, in `customer_profile` (the GET route ~465), before `return render_template(...)`, add:
```python
    can_edit = current_user.is_admin or _is_current_aor(customer)
    field_conflicts = {c["field"]: c for c in cp.list_conflicts(customer)}
```
and add `can_edit=can_edit, field_conflicts=field_conflicts` to the `render_template("customer_profile.html", ...)` call.

- [ ] **Step 2: Add a reusable editable-field macro + conflict cell to the template**

In `app/templates/customer_profile.html`, near the top of the file (after `{% extends %}`/`{% block %}` opening, before the content), add a Jinja macro:
```jinja
{% macro editable_field(customer, field, label, value, can_edit, field_conflicts) %}
  {% set conflict = field_conflicts.get(field) %}
  {% if conflict %}
    <div class="detail-row conflict-cell" data-field="{{ field }}" style="display:block; background:#FBE3E0; border-left:4px solid #C0392B; border-radius:4px; padding:10px 12px; margin:6px 0;">
      <div style="color:#C0392B; font-weight:700;">&#9888; {{ label }} — needs review</div>
      <div style="font-size:13px; margin-top:6px; color:var(--ivory);">
        Your value: <b>{{ conflict.existing.value or '—' }}</b>
        &nbsp;|&nbsp; {{ conflict.incoming.source }} says: <b>{{ conflict.incoming.value or '—' }}</b>
      </div>
      {% if can_edit %}
      <div style="margin-top:8px; display:flex; gap:8px;">
        <button class="resolve-btn" data-field="{{ field }}" data-choose="keep_current"
                style="font-size:12px; border:1px solid #C0392B; color:#C0392B; background:transparent; border-radius:6px; padding:3px 10px; cursor:pointer;">Keep mine</button>
        <button class="resolve-btn" data-field="{{ field }}" data-choose="take_incoming"
                style="font-size:12px; background:#C0392B; color:#fff; border:none; border-radius:6px; padding:3px 10px; cursor:pointer;">Use {{ conflict.incoming.source }}'s</button>
      </div>
      {% endif %}
    </div>
  {% else %}
    <div class="detail-row">
      <span class="detail-label">{{ label }}</span>
      <span class="detail-value editable-field" data-field="{{ field }}"
            {% if can_edit %}data-editable="1"{% endif %}>{{ value or '—' }}</span>
    </div>
  {% endif %}
{% endmacro %}
```

- [ ] **Step 3: Replace the Contact Info detail rows with macro calls**

In the Contact Info card (`<div class="card-body">` ~311-327), REPLACE the existing `detail-row` lines for phone/email/address/county/medicaid with macro calls (keep Lead source, Pharmacy, SMS Consent as-is — they're not provenance fields). Replace lines for phone_primary, phone_secondary, email, address1, city, state, zip_code, county, medicaid_level with:
```jinja
        {{ editable_field(customer, "phone_primary", "Phone", customer.phone_primary, can_edit, field_conflicts) }}
        {{ editable_field(customer, "phone_secondary", "Alt phone", customer.phone_secondary, can_edit, field_conflicts) }}
        {{ editable_field(customer, "email", "Email", customer.email, can_edit, field_conflicts) }}
        {{ editable_field(customer, "address1", "Address", customer.address1, can_edit, field_conflicts) }}
        {{ editable_field(customer, "city", "City", customer.city, can_edit, field_conflicts) }}
        {{ editable_field(customer, "state", "State", customer.state, can_edit, field_conflicts) }}
        {{ editable_field(customer, "zip_code", "ZIP", customer.zip_code, can_edit, field_conflicts) }}
        {{ editable_field(customer, "county", "County", customer.county, can_edit, field_conflicts) }}
        {{ editable_field(customer, "medicaid_level", "Medicaid", customer.medicaid_level, can_edit, field_conflicts) }}
```
Also add MBI + DOB as editable fields wherever identity fields are shown (e.g. add a small "Identity" block in the same card or near the header). Add:
```jinja
        {{ editable_field(customer, "mbi", "MBI", customer.mbi, can_edit, field_conflicts) }}
        {{ editable_field(customer, "dob", "DOB", customer.dob.isoformat() if customer.dob else '', can_edit, field_conflicts) }}
```
(If the existing top-of-profile MBI display at ~161 should stay as a read-only summary, leave it; the editable MBI lives in the card. Avoid two *editable* MBIs — only one editable instance.)

- [ ] **Step 4: Add the inline-edit + resolve JS**

In `customer_profile.html`, inside the existing `<script>` block (before `</script>` at ~525), append:
```javascript
// --- Inline field editing (click-to-edit, saves via set_human_value) ---
function _flash(el, color) { el.style.outline = '2px solid ' + color; setTimeout(function(){ el.style.outline=''; }, 1200); }

document.querySelectorAll('.editable-field[data-editable="1"]').forEach(function(span) {
  span.style.cursor = 'pointer';
  span.title = 'Click to edit';
  span.addEventListener('click', function() {
    if (span.querySelector('input')) return;  // already editing
    var field = span.dataset.field;
    var current = (span.textContent || '').trim();
    if (current === '—') current = '';
    var input = document.createElement('input');
    input.type = (field === 'dob') ? 'date' : 'text';
    input.value = current;
    input.style.width = '90%';
    span.textContent = '';
    span.appendChild(input);
    input.focus();
    function save() {
      var fd = new FormData();
      fd.append('field', field);
      fd.append('value', input.value);
      fetch('{{ url_for("customers.customer_set_field", customer_id=customer.id) }}',
            {method:'POST', body:fd})
        .then(function(r){ return r.json(); })
        .then(function(j){
          span.textContent = (j.ok && j.value) ? j.value : (current || '—');
          _flash(span, j.ok ? 'var(--gold)' : '#C0392B');
        })
        .catch(function(){ span.textContent = current || '—'; });
    }
    input.addEventListener('blur', save);
    input.addEventListener('keydown', function(e){ if (e.key === 'Enter') input.blur(); if (e.key === 'Escape') span.textContent = current || '—'; });
  });
});

// --- Conflict resolution buttons ---
document.querySelectorAll('.resolve-btn').forEach(function(btn) {
  btn.addEventListener('click', function() {
    var field = btn.dataset.field;
    var choose = btn.dataset.choose;
    var fd = new FormData();
    fd.append('field', field);
    fd.append('choose', choose);
    fetch('{{ url_for("customers.customer_resolve_conflict", customer_id=customer.id) }}',
          {method:'POST', body:fd})
      .then(function(r){ return r.json(); })
      .then(function(j){ if (j.ok) window.location.reload(); });
  });
});
```
NOTE: resolution does a full reload (simplest correct refresh — the conflict cell becomes a normal field). Inline-edit updates in place without reload.

- [ ] **Step 5: Add a route-level template smoke test**

Append to `tests/test_customer_edit.py`:
```python
def test_profile_renders_conflict_cell_and_editable_fields(client, app, agency, agent_user, db_session):
    from app.extensions import db
    from app.models import Customer
    from app import customer_provenance as cp
    with app.app_context():
        c = _make_customer(db, agency, agent_user)
        cp.set_human_value(c, "email", "m@old.com", agent_user)
        cp.set_import_value(c, "email", "mark@gmail.com", "bob_import")
        db.session.commit()
        cid = c.id
    _login(client, app, agent_user.id)
    html = client.get(f"/customers/{cid}").data.decode()
    assert "needs review" in html              # conflict cell rendered
    assert "mark@gmail.com" in html            # incoming value shown
    assert 'data-choose="keep_current"' in html  # resolve buttons present
    assert 'data-editable="1"' in html         # editable fields present for AOR agent


def test_profile_no_edit_controls_for_former_aor(client, app, agency, db_session):
    from app.extensions import db
    from app.models import User, Customer
    with app.app_context():
        owner = User(email="o3@t.com", name="Owner3", agency_id=agency.id)
        viewer = User(email="v3@t.com", name="Viewer3", is_admin=True, agency_id=agency.id)
        db.session.add_all([owner, viewer]); db.session.flush()
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
                     primary_agent_id=owner.id, source="bob")
        db.session.add(c); db.session.commit()
        cid = c.id; vid = viewer.id
    # admin viewer CAN edit (admin always can) -> sanity that can_edit drives controls
    _login(client, app, vid)
    html = client.get(f"/customers/{cid}").data.decode()
    assert 'data-editable="1"' in html   # admin sees edit controls
```

- [ ] **Step 6: Run the smoke tests + full suite**

Run: `python3 -m pytest tests/test_customer_edit.py -v && python3 -m pytest -q`
Expected: all green. If a template smoke assertion fails, inspect the rendered HTML — the macro may need placement adjustment, but do NOT weaken the assertions (they verify the real feature renders).

- [ ] **Step 7: Commit**

```bash
git add app/customers.py app/templates/customer_profile.html tests/test_customer_edit.py
git commit -m "feat(customers): inline-edit fields + Option-A conflict cell on profile"
```

---

### Task 5: Full-suite green + manual REPL smoke

**Files:**
- Test: full suite + a quick end-to-end check

- [ ] **Step 1: Run the entire suite**

Run: `python3 -m pytest -q`
Expected: all green. Record the count.

- [ ] **Step 2: End-to-end smoke (edit a field → matches; create a conflict → resolve → suppressed on re-import)**

Run:
```bash
python3 -c "
import os; os.environ.setdefault('DATABASE_URL','sqlite:///:memory:'); os.environ.setdefault('SECRET_KEY','t'); os.environ.setdefault('TESTING','1')
from app import create_app; from app.extensions import db
from app.models import Agency, User, Customer
from app import customer_provenance as cp
app=create_app(); app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', TESTING=True, WTF_CSRF_ENABLED=False, SERVER_NAME=None)
with app.app_context():
    db.create_all(); ag=Agency(name='F'); db.session.add(ag); db.session.flush()
    u=User(email='a@t.com', name='Agent', agency_id=ag.id); db.session.add(u); db.session.flush()
    c=Customer(agency_id=ag.id, first_name='Mitchell', last_name='Thoma', full_name='Mitchell Thoma', primary_agent_id=u.id, source='bob'); db.session.add(c); db.session.flush()
    cp.set_human_value(c,'mbi','9XY8Z76WV54',u); db.session.commit()
    print('edit: mbi=%s trust=%s' % (c.mbi, cp.trust_of(c,'mbi')))
    cp.set_human_value(c,'email','m@old.com',u)
    print('import differ ->', cp.set_import_value(c,'email','x@new.com','bob_import'))
    cp.resolve_conflict(c,'email','keep_current',u); db.session.commit()
    print('after resolve: email=%s conflicts=%d' % (c.email, len(cp.list_conflicts(c))))
    print('re-import same rejected ->', cp.set_import_value(c,'email','x@new.com','bob_import'))
" 2>&1 | grep -vE "Warning|warn"
```
Expected output: `edit: mbi=9XY8Z76WV54 trust=agent_entered`, `import differ -> conflict_flagged`, `after resolve: email=m@old.com conflicts=0`, `re-import same rejected -> suppressed`.

- [ ] **Step 3: Commit (empty if nothing changed)**

```bash
git commit --allow-empty -m "test(customers): Sub-project B suite green + e2e smoke verified"
```

---

## Self-Review

**1. Spec coverage:**
- Inline click-to-edit per tracked field, writes via set_human_value (spec Editing model) → Task 4 (template+JS) + Task 2 (route). ✓
- Clean daily view, no provenance chrome normally (spec normal state) → Task 4 macro renders plain detail-row when no conflict. ✓
- Option-A conflict cell: red fill, both values, source, Keep mine/Use carrier's inline (spec conflict state) → Task 4 macro conflict branch. ✓
- Two routes /field + /resolve-conflict, AOR/admin gated (spec Routes + Permission) → Tasks 2, 3. ✓
- Former-AOR read-only (no pencil/buttons) (spec Permission) → Task 4 macro `can_edit` gating + Task 2/3 403 tests. ✓
- Engine rejected-value memory: resolve records, set_import_value suppresses, set_human_value clears, new 'suppressed' action (spec Engine enhancement incl. point 4) → Task 1. ✓
- No new migration (spec) → confirmed, nothing adds a migration. ✓
- Testing: engine enhancement, field-save route, resolve route, template smoke (spec Testing) → Tasks 1–4. ✓
- Boundaries: no B2/C/D, no customer_new.html change → nothing in the plan touches those. ✓

**2. Placeholder scan:** No TBD/TODO. All code shown. Task 4 Step 3 references existing template lines (the engineer must read the Contact Info card first) — that's a real instruction with the exact replacement Jinja given, not a placeholder. NOTE lines give exact fallbacks (e.g. "confirm jsonify imported"), not vague directives.

**3. Type consistency:** Route names `customers.customer_set_field` / `customers.customer_resolve_conflict` used consistently in routes + template JS `url_for`. `cp.set_human_value/set_import_value/resolve_conflict/list_conflicts/trust_of/PROVENANCE_FIELDS` match the A engine. `field_conflicts` dict (field→conflict) built in Task 4 Step 1, consumed by the macro in Step 2 — the conflict shape (`conflict.existing.value`, `conflict.incoming.value`, `conflict.incoming.source`) matches `_flag_conflict`'s record structure from Sub-project A. Action string `'suppressed'` consistent between Task 1 impl + tests. `choose` values `keep_current|take_incoming` consistent across route, template buttons, engine.

**Risk flagged for execution:** Task 4 Step 3 edits a long existing template by replacing specific detail-rows. The implementer MUST read the current Contact Info card (~306-327) and the top-of-profile MBI line (~161) first, and ensure only ONE *editable* MBI instance exists (the read-only summary at top may stay). The template smoke test (Task 4 Step 5) guards that conflict cells + editable markers render, but does not guard against a duplicated MBI — the implementer should visually confirm.
