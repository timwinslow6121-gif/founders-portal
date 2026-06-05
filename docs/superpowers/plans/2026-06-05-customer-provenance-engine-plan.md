# Customer Field Provenance Engine Implementation Plan (Sub-project A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `app/customer_provenance.py` — a per-field source/trust/history + precedence engine for `Customer`, mirroring `app/plan_provenance.py` — plus migration 022 and an idempotent backfill that migrates the `manually_edited` flag into per-field provenance.

**Architecture:** Provenance metadata lives in a new `customers.field_provenance` JSON (Text) column; the customer's real typed columns stay the authoritative filterable values. The engine is the single seam: all `_meta`/`_conflicts` reads/writes go through it. Trust order `human_verified > agent_entered > carrier_import > empty`; human edits never overwritten by imports; a differing import flags a conflict for review. No consumer wiring (imports/UI) is in scope — that's Sub-projects B/C/D.

**Tech Stack:** Python 3.10, Flask-SQLAlchemy, Flask-Migrate/Alembic, pytest SQLite-in-memory (conftest fixtures: `app`, `db_session`, `agency`, `agent_user`, `customer`).

**Reference spec:** `docs/superpowers/specs/2026-06-05-customer-provenance-engine-design.md`. Mirror the proven `app/plan_provenance.py` (esp. its `_conflicts`-as-a-LIST shape, `_flag_conflict` dedup, `resolve_conflict`).

---

## File Structure

- **Create** `app/customer_provenance.py` — the engine (reads, human writes, import precedence, conflicts). One responsibility: customer field provenance.
- **Modify** `app/models.py` — add `Customer.field_provenance` (Text) + `Customer.has_unresolved_conflicts` (Boolean, indexed).
- **Create** `migrations/versions/022_customer_provenance.py` — the two columns, chained off 021.
- **Create** `scripts/backfill_customer_provenance.py` — idempotent backfill seeding provenance for existing customers.
- **Create** `tests/test_customer_provenance.py` — engine unit tests (SQLite).
- **Create** `tests/test_backfill_customer_provenance.py` — backfill logic tests.

Values stored in `_meta` are plain scalars (string/ISO-date-string), NOT the `{amount,period,unit,display}` shape plan benefits use. `_conflicts` is a LIST (mirroring plan_provenance), one open conflict per field.

---

### Task 1: Migration 022 + ORM columns

**Files:**
- Modify: `app/models.py`
- Create: `migrations/versions/022_customer_provenance.py`
- Test: `tests/test_customer_provenance.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_customer_provenance.py`:
```python
"""
tests/test_customer_provenance.py

Tests for the customer field-provenance engine: precedence, human writes, conflict
lifecycle, round-trip. SQLite in-memory via conftest fixtures. Mirrors
tests/test_plan_provenance.py.
"""
from datetime import date


def test_provenance_columns_exist(db_session, app, agency):
    from app.extensions import db
    from app.models import Customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
                     field_provenance=None, has_unresolved_conflicts=False)
        db.session.add(c)
        db.session.commit()
        assert c.field_provenance is None
        assert c.has_unresolved_conflicts is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_customer_provenance.py::test_provenance_columns_exist -v`
Expected: FAIL — `TypeError: 'field_provenance' is an invalid keyword argument` (column missing).

- [ ] **Step 3: Add ORM columns**

In `app/models.py`, in `class Customer`, immediately after the line:
```python
    manually_edited   = db.Column(db.Boolean, default=False, nullable=False)
```
add:
```python
    # Field-level provenance engine (migration 022) — see app/customer_provenance.py
    field_provenance         = db.Column(db.Text)               # JSON: per-field _meta + _conflicts
    has_unresolved_conflicts = db.Column(db.Boolean, default=False, nullable=False, index=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_customer_provenance.py::test_provenance_columns_exist -v`
Expected: PASS.

- [ ] **Step 5: Write the Alembic migration**

Create `migrations/versions/022_customer_provenance.py`:
```python
"""Customer field-provenance: field_provenance + has_unresolved_conflicts

Revision ID: 022
Revises: 021
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customers", sa.Column("field_provenance", sa.Text(), nullable=True))
    op.add_column("customers", sa.Column("has_unresolved_conflicts", sa.Boolean(),
                                         nullable=False, server_default=sa.false()))
    op.create_index("ix_customers_has_unresolved_conflicts", "customers",
                    ["has_unresolved_conflicts"])


def downgrade():
    op.drop_index("ix_customers_has_unresolved_conflicts", table_name="customers")
    op.drop_column("customers", "has_unresolved_conflicts")
    op.drop_column("customers", "field_provenance")
```

- [ ] **Step 6: Verify migration imports + chains**

Run: `python3 -c "import importlib.util; s=importlib.util.spec_from_file_location('m022','migrations/versions/022_customer_provenance.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('revision', m.revision, 'down', m.down_revision)"`
Expected: `revision 022 down 021`

- [ ] **Step 7: Run full suite (no regression)**

Run: `python3 -m pytest -q`
Expected: all green (prior count + 1).

- [ ] **Step 8: Commit**

```bash
git add app/models.py migrations/versions/022_customer_provenance.py tests/test_customer_provenance.py
git commit -m "feat(customers): migration 022 — field_provenance + has_unresolved_conflicts columns"
```

---

### Task 2: Engine core — load/save, constants, reads

**Files:**
- Create: `app/customer_provenance.py`
- Test: `tests/test_customer_provenance.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_customer_provenance.py`:
```python
def test_constants_and_empty_reads(db_session, app, agency):
    from app.commission.member_fact import MemberFact  # noqa: F401 (ensure app imports clean)
    from app import customer_provenance as cp
    from app.models import Customer
    from app.extensions import db

    assert cp.TRUST_ORDER == {"carrier_import": 1, "agent_entered": 2, "human_verified": 3}
    assert "mbi" in cp.PROVENANCE_FIELDS and "zip_code" in cp.PROVENANCE_FIELDS
    assert "id" not in cp.PROVENANCE_FIELDS and "full_name" not in cp.PROVENANCE_FIELDS

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B")
        db.session.add(c); db.session.flush()
        assert cp.get_field(c, "zip_code") is None
        assert cp.trust_of(c, "zip_code") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_customer_provenance.py::test_constants_and_empty_reads -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.customer_provenance'`.

- [ ] **Step 3: Create the engine core**

Create `app/customer_provenance.py`:
```python
"""
app/customer_provenance.py

Per-field provenance + precedence for Customer, the sibling of app/plan_provenance.py
(shared pattern, not shared code). The single seam: ALL reads/writes of per-field
_meta/_conflicts go through this module; nothing else touches customers.field_provenance.

Storage: customers.field_provenance is a JSON blob:
  {
    "_meta": { field: {value, source, trust, updated_at, updated_by, history:[...] } },
    "_conflicts": [ {field, existing:{value,source,by,at}, incoming:{value,source,at},
                     flagged_at, resolved, resolved_by, resolved_at, resolution} ]
  }
Customer field values are PLAIN SCALARS (strings / ISO date strings), not the
{amount,period,unit} shape plan benefits use.

Trust order: human_verified > agent_entered > carrier_import > empty.
See docs/superpowers/specs/2026-06-05-customer-provenance-engine-design.md.
"""
import json
from datetime import datetime, date

PROVENANCE_FIELDS = [
    "mbi", "humana_id", "first_name", "last_name", "dob", "gender",
    "phone_primary", "phone_secondary", "email", "address1", "city",
    "state", "zip_code", "county", "medicaid_level", "medicaid_id",
]

TRUST_ORDER = {"carrier_import": 1, "agent_entered": 2, "human_verified": 3}

# source strings (trust tier in parens): agent_edit(agent_entered),
# aj_verified(human_verified), bob_import/commission_import/healthsherpa(carrier_import)


def _now():
    return datetime.utcnow().isoformat(timespec="seconds")


def _load(customer):
    if not customer.field_provenance:
        return {}
    try:
        return json.loads(customer.field_provenance)
    except (json.JSONDecodeError, TypeError):
        return {}


def _save(customer, data):
    customer.field_provenance = json.dumps(data)


def _to_scalar(value):
    """Normalize a field value to a JSON-serializable scalar for storage/compare."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def get_field(customer, field):
    """Full provenance record for a field, or None."""
    rec = _load(customer).get("_meta", {}).get(field)
    return rec if rec else None


def trust_of(customer, field):
    rec = get_field(customer, field)
    return rec.get("trust") if rec else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_customer_provenance.py::test_constants_and_empty_reads -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/customer_provenance.py tests/test_customer_provenance.py
git commit -m "feat(customers): provenance engine core — load/save, constants, reads"
```

---

### Task 3: Human writes — set_human_value

**Files:**
- Modify: `app/customer_provenance.py`
- Test: `tests/test_customer_provenance.py`

`set_human_value` writes the real column AND the metadata, appends history, sets `manually_edited=True`. `verify=False` → `agent_entered`; `verify=True` → `human_verified`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_customer_provenance.py`:
```python
def test_set_human_value_writes_column_and_meta(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.models import Customer
    from app.extensions import db

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B")
        db.session.add(c); db.session.flush()

        cp.set_human_value(c, "zip_code", "28205", agent_user)
        db.session.flush()

        assert c.zip_code == "28205"                  # real column written
        rec = cp.get_field(c, "zip_code")
        assert rec["value"] == "28205"
        assert rec["trust"] == "agent_entered"
        assert rec["source"] == "agent_edit"
        assert rec["updated_by"] == agent_user.name
        assert len(rec["history"]) == 1
        assert c.manually_edited is True

        # verify=True -> human_verified (AJ)
        cp.set_human_value(c, "zip_code", "28202", agent_user, note="fixed typo", verify=True)
        db.session.flush()
        assert c.zip_code == "28202"
        rec = cp.get_field(c, "zip_code")
        assert rec["trust"] == "human_verified"
        assert rec["source"] == "aj_verified"
        assert len(rec["history"]) == 2
        assert rec["history"][-1]["note"] == "fixed typo"


def test_set_human_value_dob_serializes(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.models import Customer
    from app.extensions import db
    from datetime import date

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B")
        db.session.add(c); db.session.flush()
        cp.set_human_value(c, "dob", date(1956, 8, 28), agent_user)
        db.session.flush()
        assert c.dob == date(1956, 8, 28)             # column holds a real date
        assert cp.get_field(c, "dob")["value"] == "1956-08-28"   # meta holds ISO string
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_customer_provenance.py -k set_human_value -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'set_human_value'`.

- [ ] **Step 3: Implement**

Append to `app/customer_provenance.py`:
```python
def _set_column(customer, field, value):
    """Write the real typed column. dob is the only date field; others are strings."""
    if field == "dob" and isinstance(value, str) and value:
        # accept ISO string or pass-through date
        try:
            value = date.fromisoformat(value)
        except ValueError:
            pass
    setattr(customer, field, value)


def set_human_value(customer, field, value, user, note=None, verify=False):
    """Apply a human edit (agent) or verification (verify=True -> AJ).

    Writes the real column AND _meta, appends history, sets manually_edited=True.
    `value` may be a scalar or a date; stored as a scalar in _meta.
    """
    if field not in PROVENANCE_FIELDS:
        raise ValueError(f"{field} is not a provenance-tracked field")

    _set_column(customer, field, value)
    scalar = _to_scalar(value)

    data = _load(customer)
    meta = data.setdefault("_meta", {})
    prev = meta.get(field, {}).get("value")
    history = meta.get(field, {}).get("history", [])
    history.append({"at": _now(), "by": getattr(user, "name", None),
                    "from": prev, "to": scalar, "note": note})
    meta[field] = {
        "value": scalar,
        "source": "aj_verified" if verify else "agent_edit",
        "trust": "human_verified" if verify else "agent_entered",
        "updated_at": _now(),
        "updated_by": getattr(user, "name", None),
        "history": history,
    }
    _save(customer, data)
    customer.manually_edited = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_customer_provenance.py -k set_human_value -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add app/customer_provenance.py tests/test_customer_provenance.py
git commit -m "feat(customers): set_human_value — column + provenance + history, sets manually_edited"
```

---

### Task 4: Import precedence — set_import_value

**Files:**
- Modify: `app/customer_provenance.py`
- Test: `tests/test_customer_provenance.py`

The precedence engine. Returns an action; never overwrites human values (flags a conflict instead).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_customer_provenance.py`:
```python
def _fresh(db, agency):
    from app.models import Customer
    c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B")
    db.session.add(c); db.session.flush()
    return c


def test_import_writes_empty_field(db_session, app, agency):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        action = cp.set_import_value(c, "zip_code", "28205", "bob_import")
        db.session.flush()
        assert action == "written"
        assert c.zip_code == "28205"
        assert cp.trust_of(c, "zip_code") == "carrier_import"


def test_import_skips_blank_incoming(db_session, app, agency):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        assert cp.set_import_value(c, "zip_code", "", "bob_import") == "skipped"
        assert cp.set_import_value(c, "zip_code", None, "bob_import") == "skipped"
        assert c.zip_code is None
        assert cp.get_field(c, "zip_code") is None


def test_import_confirms_same_value(db_session, app, agency):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_import_value(c, "zip_code", "28205", "bob_import"); db.session.flush()
        action = cp.set_import_value(c, "zip_code", "28205", "commission_import")
        assert action == "confirmed"
        assert c.zip_code == "28205"


def test_import_overwrites_other_carrier_value(db_session, app, agency):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_import_value(c, "zip_code", "28205", "bob_import"); db.session.flush()
        action = cp.set_import_value(c, "zip_code", "28202", "commission_import")
        assert action == "written"           # carrier-tier: newer carrier wins
        assert c.zip_code == "28202"


def test_import_conflicts_with_agent_value(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "zip_code", "28205", agent_user); db.session.flush()
        action = cp.set_import_value(c, "zip_code", "28202", "bob_import")
        db.session.flush()
        assert action == "conflict_flagged"
        assert c.zip_code == "28205"                       # human value preserved
        assert c.has_unresolved_conflicts is True
        conflicts = cp.list_conflicts(c)
        assert len(conflicts) == 1
        assert conflicts[0]["field"] == "zip_code"
        assert conflicts[0]["incoming"]["value"] == "28202"


def test_import_conflict_is_idempotent(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "zip_code", "28205", agent_user); db.session.flush()
        cp.set_import_value(c, "zip_code", "28202", "bob_import"); db.session.flush()
        cp.set_import_value(c, "zip_code", "28202", "bob_import"); db.session.flush()
        assert len(cp.list_conflicts(c)) == 1          # one open conflict per field
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_customer_provenance.py -k import_ -v`
Expected: FAIL — `set_import_value` / `list_conflicts` not defined.

- [ ] **Step 3: Implement set_import_value + _flag_conflict + list_conflicts**

Append to `app/customer_provenance.py`:
```python
def _is_blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def _flag_conflict(data, customer, field, existing, incoming_scalar, source):
    """Append one open conflict per field (idempotent — mirrors plan_provenance)."""
    conflicts = data.setdefault("_conflicts", [])
    for c in conflicts:
        if c["field"] == field and not c.get("resolved"):
            return
    conflicts.append({
        "field": field,
        "existing": {
            "value": existing.get("value"),
            "source": existing.get("source"),
            "by": existing.get("updated_by"),
            "at": existing.get("updated_at"),
        },
        "incoming": {"value": incoming_scalar, "source": source, "at": _now()},
        "flagged_at": _now(),
        "resolved": False, "resolved_by": None, "resolved_at": None, "resolution": None,
    })


def set_import_value(customer, field, value, source):
    """Apply an import-sourced value using precedence. Returns:
    'skipped' | 'written' | 'confirmed' | 'conflict_flagged'.

    Never overwrites an agent_entered/human_verified value (flags a conflict).
    A differing carrier-tier value is overwritten (newer carrier wins).
    """
    if field not in PROVENANCE_FIELDS:
        raise ValueError(f"{field} is not a provenance-tracked field")
    if _is_blank(value):
        return "skipped"

    scalar = _to_scalar(value)
    data = _load(customer)
    meta = data.setdefault("_meta", {})
    existing = meta.get(field)

    def _write(action, prev=None):
        history = (existing or {}).get("history", [])
        history.append({"at": _now(), "by": None, "from": prev, "to": scalar,
                        "note": f"import:{source}"})
        meta[field] = {
            "value": scalar, "source": source, "trust": "carrier_import",
            "updated_at": _now(), "updated_by": None, "history": history,
        }
        _set_column(customer, field, value)
        _save(customer, data)
        return action

    if existing is None:
        return _write("written")

    prev = existing.get("value")
    same = (prev == scalar)
    trust = existing.get("trust")

    if same:
        existing["updated_at"] = _now()
        _save(customer, data)
        return "confirmed"

    if trust in ("agent_entered", "human_verified"):
        _flag_conflict(data, customer, field, existing, scalar, source)
        _save(customer, data)
        customer.has_unresolved_conflicts = True
        return "conflict_flagged"

    # carrier_import tier and differs -> newer carrier wins
    return _write("written", prev=prev)


def list_conflicts(customer, unresolved_only=True):
    conflicts = _load(customer).get("_conflicts", [])
    if unresolved_only:
        return [c for c in conflicts if not c.get("resolved")]
    return conflicts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_customer_provenance.py -k import_ -v`
Expected: PASS (all 6).

- [ ] **Step 5: Commit**

```bash
git add app/customer_provenance.py tests/test_customer_provenance.py
git commit -m "feat(customers): set_import_value precedence engine + conflict flagging"
```

---

### Task 5: Conflict resolution — resolve_conflict

**Files:**
- Modify: `app/customer_provenance.py`
- Test: `tests/test_customer_provenance.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_customer_provenance.py`:
```python
def test_resolve_conflict_keep_current(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "zip_code", "28205", agent_user); db.session.flush()
        cp.set_import_value(c, "zip_code", "28202", "bob_import"); db.session.flush()

        cp.resolve_conflict(c, "zip_code", "keep_current", agent_user); db.session.flush()
        assert c.zip_code == "28205"                       # kept
        assert cp.trust_of(c, "zip_code") == "human_verified"
        assert c.has_unresolved_conflicts is False
        assert cp.list_conflicts(c) == []


def test_resolve_conflict_take_incoming(db_session, app, agency, agent_user):
    from app import customer_provenance as cp
    from app.extensions import db
    with app.app_context():
        c = _fresh(db, agency)
        cp.set_human_value(c, "zip_code", "28205", agent_user); db.session.flush()
        cp.set_import_value(c, "zip_code", "28202", "bob_import"); db.session.flush()

        cp.resolve_conflict(c, "zip_code", "take_incoming", agent_user); db.session.flush()
        assert c.zip_code == "28202"                       # took carrier value
        assert cp.trust_of(c, "zip_code") == "human_verified"  # a resolution is a human decision
        assert c.has_unresolved_conflicts is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_customer_provenance.py -k resolve_conflict -v`
Expected: FAIL — `resolve_conflict` not defined.

- [ ] **Step 3: Implement**

Append to `app/customer_provenance.py`:
```python
def resolve_conflict(customer, field, choose, user, note=None):
    """Resolve a field conflict. choose in {'keep_current', 'take_incoming'}.

    The surviving value is written as human_verified (a resolution is a human
    decision). Marks the conflict resolved and recomputes has_unresolved_conflicts.
    """
    if choose not in ("keep_current", "take_incoming"):
        raise ValueError("choose must be 'keep_current' or 'take_incoming'")

    data = _load(customer)
    meta = data.setdefault("_meta", {})
    rec = meta.get(field, {})
    current = rec.get("value")

    # find the open conflict for this field
    conflict = next((c for c in data.get("_conflicts", [])
                     if c["field"] == field and not c.get("resolved")), None)
    incoming = conflict["incoming"]["value"] if conflict else None

    surviving = current if choose == "keep_current" else incoming

    history = rec.get("history", [])
    history.append({"at": _now(), "by": getattr(user, "name", None),
                    "from": current, "to": surviving,
                    "note": note or f"conflict resolved ({choose})"})
    meta[field] = {
        "value": surviving, "source": "aj_verified", "trust": "human_verified",
        "updated_at": _now(), "updated_by": getattr(user, "name", None),
        "history": history,
    }
    _set_column(customer, field, surviving)

    for c in data.get("_conflicts", []):
        if c["field"] == field and not c.get("resolved"):
            c["resolved"] = True
            c["resolved_by"] = getattr(user, "name", None)
            c["resolved_at"] = _now()
            c["resolution"] = choose
    _save(customer, data)
    remaining = [c for c in data.get("_conflicts", []) if not c.get("resolved")]
    customer.has_unresolved_conflicts = bool(remaining)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_customer_provenance.py -k resolve_conflict -v`
Expected: PASS (both).

- [ ] **Step 5: Run the whole engine suite + full suite**

Run: `python3 -m pytest tests/test_customer_provenance.py -v && python3 -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add app/customer_provenance.py tests/test_customer_provenance.py
git commit -m "feat(customers): resolve_conflict — keep_current/take_incoming, recompute flag"
```

---

### Task 6: Backfill script + tests

**Files:**
- Create: `scripts/backfill_customer_provenance.py`
- Test: `tests/test_backfill_customer_provenance.py`

Seeds provenance for existing customers. `manually_edited=True` → all populated tracked fields as `agent_entered` (protect everything a human touched). Else → `carrier_import`. Idempotent (skips fields that already have provenance). Factored so the per-customer logic is unit-testable without a live DB run.

- [ ] **Step 1: Write the failing test**

Create `tests/test_backfill_customer_provenance.py`:
```python
"""
tests/test_backfill_customer_provenance.py

Tests the backfill seeding logic for the customer provenance engine.
"""
from datetime import date


def test_backfill_manually_edited_seeds_all_as_agent_entered(db_session, app, agency):
    from app.extensions import db
    from app.models import Customer
    from app import customer_provenance as cp
    from scripts.backfill_customer_provenance import seed_customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Mitchell", last_name="Thoma",
                     full_name="Mitchell Thoma", mbi="9ABC", zip_code="28205",
                     email="m@x.com", manually_edited=True, source="bob")
        db.session.add(c); db.session.flush()

        seed_customer(c)
        db.session.flush()

        # both an identity field (mbi) and a contact field (zip) are protected
        assert cp.trust_of(c, "mbi") == "agent_entered"
        assert cp.trust_of(c, "zip_code") == "agent_entered"
        assert cp.trust_of(c, "email") == "agent_entered"
        # an unpopulated field gets no provenance
        assert cp.get_field(c, "county") is None


def test_backfill_plain_customer_seeds_carrier_import(db_session, app, agency):
    from app.extensions import db
    from app.models import Customer
    from app import customer_provenance as cp
    from scripts.backfill_customer_provenance import seed_customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
                     zip_code="28202", manually_edited=False, source="bob")
        db.session.add(c); db.session.flush()
        seed_customer(c)
        db.session.flush()
        assert cp.trust_of(c, "zip_code") == "carrier_import"
        rec = cp.get_field(c, "zip_code")
        assert rec["source"] == "bob"


def test_backfill_is_idempotent(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer
    from app import customer_provenance as cp
    from scripts.backfill_customer_provenance import seed_customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
                     zip_code="28202", manually_edited=False, source="bob")
        db.session.add(c); db.session.flush()
        # a field already has provenance (e.g. an agent edit) -> backfill must not clobber it
        cp.set_human_value(c, "zip_code", "28205", agent_user); db.session.flush()

        seed_customer(c); db.session.flush()
        assert cp.trust_of(c, "zip_code") == "agent_entered"   # untouched by backfill
        assert c.zip_code == "28205"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_backfill_customer_provenance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.backfill_customer_provenance'`.

- [ ] **Step 3: Implement the backfill**

Create `scripts/backfill_customer_provenance.py`:
```python
"""
scripts/backfill_customer_provenance.py

One-time, idempotent backfill seeding per-field provenance for existing customers.

- manually_edited=True  -> every populated tracked field seeded as agent_entered
  (protect everything a human touched; a later carrier mismatch flags a conflict).
- manually_edited=False -> every populated tracked field seeded as carrier_import.
- source recorded from customer.source where present, else 'bob'.
- Idempotent: a field that already has provenance is skipped.

Run on VPS:  ./venv/bin/python3 scripts/backfill_customer_provenance.py
"""
from app import customer_provenance as cp


def _seed_source(customer):
    return (getattr(customer, "source", None) or "bob")


def seed_customer(customer):
    """Seed provenance for one customer's populated tracked fields (idempotent).
    Returns the number of fields seeded."""
    data = cp._load(customer)
    meta = data.setdefault("_meta", {})
    trust = "agent_entered" if customer.manually_edited else "carrier_import"
    src = "agent_edit" if customer.manually_edited else _seed_source(customer)
    seeded = 0
    for field in cp.PROVENANCE_FIELDS:
        if field in meta:           # already has provenance -> skip (idempotent)
            continue
        raw = getattr(customer, field, None)
        if cp._is_blank(raw):
            continue
        meta[field] = {
            "value": cp._to_scalar(raw),
            "source": src,
            "trust": trust,
            "updated_at": cp._now(),
            "updated_by": None,
            "history": [{"at": cp._now(), "by": None, "from": None,
                         "to": cp._to_scalar(raw), "note": "provenance backfill"}],
        }
        seeded += 1
    cp._save(customer, data)
    return seeded


def main():
    from app import create_app
    from app.extensions import db
    from app.models import Customer

    app = create_app()
    with app.app_context():
        total_customers = 0
        total_fields = 0
        for c in Customer.query.all():
            n = seed_customer(c)
            if n:
                total_customers += 1
                total_fields += n
        db.session.commit()
        print(f"Backfilled provenance: {total_fields} fields across "
              f"{total_customers} customers.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_backfill_customer_provenance.py -v`
Expected: PASS (all 3).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill_customer_provenance.py tests/test_backfill_customer_provenance.py
git commit -m "feat(customers): idempotent provenance backfill (manually_edited -> agent_entered)"
```

---

### Task 7: Engine public surface + full-suite green

**Files:**
- Modify: `app/customer_provenance.py`
- Test: full suite

- [ ] **Step 1: Add `__all__`**

At the top of `app/customer_provenance.py`, after the imports, add:
```python
__all__ = [
    "PROVENANCE_FIELDS", "TRUST_ORDER",
    "get_field", "trust_of",
    "set_human_value", "set_import_value",
    "list_conflicts", "resolve_conflict",
]
```

- [ ] **Step 2: Confirm imports clean**

Run: `python3 -c "from app.customer_provenance import set_human_value, set_import_value, resolve_conflict, list_conflicts, get_field, trust_of, PROVENANCE_FIELDS, TRUST_ORDER; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Run the entire suite**

Run: `python3 -m pytest -q`
Expected: all green. Record the count.

- [ ] **Step 4: Commit**

```bash
git add app/customer_provenance.py
git commit -m "feat(customers): export customer_provenance public surface"
```

---

## Self-Review

**1. Spec coverage:**
- New module `customer_provenance.py`, seam principle (spec Architecture) → Tasks 2–7. ✓
- `field_provenance` + `has_unresolved_conflicts` columns + migration 022 (spec Storage) → Task 1. ✓
- JSON `_meta` + `_conflicts` (list), scalar values (spec Storage) → Task 2 (_load/_save/_to_scalar), Task 4 (_conflicts list). ✓
- Trust order human_verified>agent_entered>carrier_import>empty (spec Trust model) → Task 2 TRUST_ORDER, enforced in Task 4. ✓
- `get_field`, `trust_of` (spec API reads) → Task 2. ✓
- `set_human_value` verify flag, writes column+meta, manually_edited=True (spec API) → Task 3. ✓
- `set_import_value` actions skipped/written/confirmed/conflict_flagged + precedence (spec API + precedence table) → Task 4. ✓
- `list_conflicts`, `resolve_conflict` keep_current/take_incoming (spec API conflicts) → Tasks 4, 5. ✓
- PROVENANCE_FIELDS exact set (spec) → Task 2. ✓
- Migration 022 + idempotent backfill, manually_edited→agent_entered for ALL populated fields (spec Migration & backfill, updated) → Tasks 1, 6. ✓
- Testing: precedence incl. incoming-blank→skipped, human writes, conflict lifecycle, round-trip, backfill (spec Testing) → Tasks 3–6. ✓
- Boundaries: no import wiring, no UI, no plan_provenance edits (spec Boundaries) → nothing in the plan touches imports/UI/plan_provenance. ✓

**2. Placeholder scan:** No TBD/TODO. Every code step is complete. The backfill reuses engine internals (`cp._load/_save/_to_scalar/_is_blank/_now`) deliberately — they're module-internal helpers the script legitimately shares; documented inline.

**3. Type consistency:** `set_human_value(customer, field, value, user, note, verify)`, `set_import_value(customer, field, value, source)`, `resolve_conflict(customer, field, choose, user, note)` consistent across tasks and tests. `_conflicts` is a list everywhere. Action strings (`written/confirmed/conflict_flagged/skipped`) consistent between Task 4 impl and tests. `trust` values consistent. `_set_column`/`_to_scalar`/`_is_blank` defined in Tasks 3/2/4 and reused consistently (note: `_is_blank` is introduced in Task 4 but used by the Task 6 backfill — Task 6 runs after Task 4, so it exists; if executing strictly in order this is fine).

**Ordering note for executor:** `_is_blank` and `_set_column` are defined in Tasks 3–4 and reused by the Task 6 backfill. Execute tasks in order. If a reviewer runs Task 6 in isolation, ensure Tasks 2–4's helpers are present in `app/customer_provenance.py` first.
