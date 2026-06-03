# Provenance Core Implementation Plan (Plan 1 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the provenance foundation — a helper module owning structured benefit values, per-field source/trust/history, and the CMS-vs-human precedence rules (the BCBS-incident preventer) — plus the migration adding provenance columns and the RBAC `role` field.

**Architecture:** A single pure-logic module `app/plan_provenance.py` is the *seam*: it owns all reads/writes of the `_meta` / `_conflicts` structure inside `Plan.details_json`, so a future relational table changes only this module. Benefit values are stored structured (`{amount, period, unit, display}`) to power both numeric filtering and reliable conflict comparison. Precedence rules live entirely in `set_cms_value()`. All logic is tested locally with SQLite in-memory (no VPS needed); only the migration runs on the VPS.

**Tech Stack:** Python 3.10, Flask-SQLAlchemy, Flask-Migrate (Alembic), pytest + pytest-flask. Tests use the existing `tests/conftest.py` fixtures (`app`, `db_session`, `agency`, `admin_user`, `agent_user`).

**Reference spec:** `docs/superpowers/specs/2026-06-02-plan-data-integrity-provenance-design.md`

---

## Conventions (read once before starting)

- **Run a single test:** `python -m pytest tests/test_plan_provenance.py::test_name -v`
- **Run the whole new file:** `python -m pytest tests/test_plan_provenance.py -v`
- **Tests import inside the function** (matches existing `tests/test_agency_scoping.py` style) and use the `app` + `db_session` fixtures.
- **`db` is imported from `app.extensions`** (`from app.extensions import db`).
- **The Plan model** is in `app/models.py` (class `Plan`, line ~296). It already has `details_json = db.Column(db.Text)`.
- **Do NOT run Alembic migrations locally** — there is no local venv/PostgreSQL. The migration file is written here and applied on the VPS in the final task. Tests use `db.create_all()` via the fixture, which reads the live model definitions, so model changes (Task 6) are exercised by tests without running the migration.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `app/plan_provenance.py` | Create | The seam: structured-value parse/format, `_meta`/`_conflicts` I/O, precedence rules, conflict + history logic. Pure functions over a `Plan`. |
| `tests/test_plan_provenance.py` | Create | Structured-value round-trips, precedence-rule tests (one per Section-4 row), auto-promotion, conflict lifecycle, year invariant, `can_edit_shared_data`. |
| `app/models.py` | Modify | Add `Plan.cms_synced_at`, `Plan.has_unresolved_conflicts`; `User.role`; `can_edit_shared_data()` helper. |
| `migrations/versions/019_plan_provenance.py` | Create | DB columns + role backfill. Applied on VPS only. |

---

## Task 1: Structured benefit value — parse & format

The atomic unit. A benefit value is `{amount, period, unit, display}`. We need to build one from raw CMS money strings and render its display. Pure functions, no DB.

**Files:**
- Create: `app/plan_provenance.py`
- Test: `tests/test_plan_provenance.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_provenance.py
"""
tests/test_plan_provenance.py

Tests for the plan provenance helper — structured values, precedence rules,
conflict lifecycle. Pure-logic tests; SQLite in-memory via conftest fixtures.
"""
import pytest


def test_make_value_money_with_period():
    from app.plan_provenance import make_value
    v = make_value(amount=2000, period="yr", unit="usd")
    assert v == {"amount": 2000, "period": "yr", "unit": "usd", "display": "$2,000/yr"}


def test_make_value_money_no_period():
    from app.plan_provenance import make_value
    v = make_value(amount=455, period=None, unit="usd")
    assert v["display"] == "$455"
    assert v["amount"] == 455
    assert v["period"] is None


def test_make_value_percent():
    from app.plan_provenance import make_value
    v = make_value(amount=18, period=None, unit="pct")
    assert v["display"] == "18%"
    assert v["unit"] == "pct"


def test_make_value_offered_no_amount():
    from app.plan_provenance import make_value
    v = make_value(amount=None, period="qtr", unit="usd")
    assert v["amount"] is None
    assert v["display"] == "Offered"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_plan_provenance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.plan_provenance'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/plan_provenance.py
"""
app/plan_provenance.py

Provenance helper — the single seam owning structured benefit values and the
_meta / _conflicts provenance structure inside Plan.details_json.

Storage today is JSON-in-details_json. A future relational plan_benefit_values
table would change ONLY this module; callers (sync scripts, edit routes,
templates) use these functions and never touch the raw structure.

See docs/superpowers/specs/2026-06-02-plan-data-integrity-provenance-design.md
"""

_PERIOD_DISPLAY = {
    "mo": "/mo", "qtr": "/qtr", "yr": "/yr",
    "2yr": "/2yr", "3yr": "/3yr", "period": "/period", None: "",
}


def make_value(amount, period=None, unit="usd", display=None):
    """Build a structured benefit value dict.

    amount: numeric value, or None for "offered but amount unknown".
    period: one of mo|qtr|yr|2yr|3yr|period|None.
    unit:   usd|pct|count|text.
    display: explicit display string; if None, it is derived.
    """
    if display is None:
        display = _format_display(amount, period, unit)
    return {"amount": amount, "period": period, "unit": unit, "display": display}


def _format_display(amount, period, unit):
    if amount is None:
        return "Offered"
    suffix = _PERIOD_DISPLAY.get(period, "")
    if unit == "usd":
        if amount == int(amount):
            return f"${int(amount):,}{suffix}"
        return f"${amount:,.2f}{suffix}"
    if unit == "pct":
        return f"{int(amount) if amount == int(amount) else amount}%{suffix}"
    if unit == "count":
        return f"{amount}{suffix}"
    return str(amount)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_plan_provenance.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add app/plan_provenance.py tests/test_plan_provenance.py
git commit -m "feat(provenance): structured benefit value make_value + display formatting"
```

---

## Task 2: Parse a raw CMS money string into a structured value

The sync scripts read strings like `"455.00"` and period codes like `"2"`. Convert those to structured values. Pure functions.

**Files:**
- Modify: `app/plan_provenance.py`
- Test: `tests/test_plan_provenance.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_plan_provenance.py
def test_parse_money_basic():
    from app.plan_provenance import parse_money
    assert parse_money("455.00") == 455
    assert parse_money("2000.00") == 2000
    assert parse_money("0.00") == 0


def test_parse_money_blank_is_none():
    from app.plan_provenance import parse_money
    assert parse_money("") is None
    assert parse_money(None) is None
    assert parse_money("   ") is None


def test_parse_money_decimal_preserved():
    from app.plan_provenance import parse_money
    assert parse_money("12.50") == 12.5


def test_period_code_to_token():
    from app.plan_provenance import period_code_to_token
    # CMS period codes: 1=mo, 2=qtr, 3=yr, 5=mo(alt), 7=yr(alt) per PBP dictionary
    assert period_code_to_token("2") == "qtr"
    assert period_code_to_token("3") == "yr"
    assert period_code_to_token("1") == "mo"
    assert period_code_to_token("") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_plan_provenance.py -k "parse_money or period_code" -v`
Expected: FAIL with `ImportError: cannot import name 'parse_money'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to app/plan_provenance.py

# CMS PBP period codes -> our period tokens. Codes vary by sub-section; this is
# the common mapping used across b13b/b16/b17. Unknown codes -> None (no suffix).
_PERIOD_CODE = {
    "1": "mo", "2": "qtr", "3": "yr",
    "5": "mo", "7": "yr",   # alternate code sets seen in b13b
}


def parse_money(raw):
    """'455.00' -> 455 ; '12.50' -> 12.5 ; '' / None / blank -> None."""
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return None
    return int(val) if val == int(val) else val


def period_code_to_token(code):
    """Map a CMS period code string to our period token, or None."""
    if code is None:
        return None
    return _PERIOD_CODE.get(str(code).strip(), None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_plan_provenance.py -k "parse_money or period_code" -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add app/plan_provenance.py tests/test_plan_provenance.py
git commit -m "feat(provenance): parse_money + period_code_to_token CMS parsers"
```

---

## Task 3: Read/write the `_meta` provenance map on a Plan

Now we touch a `Plan`. We store provenance under `details_json["_meta"][field]`. Add a `plan` fixture and low-level get/set helpers that own the JSON (de)serialization.

**Files:**
- Modify: `app/plan_provenance.py`
- Modify: `tests/test_plan_provenance.py` (add fixture)

- [ ] **Step 1: Add a `plan` fixture and write the failing test**

```python
# append to tests/test_plan_provenance.py

@pytest.fixture
def plan(db_session, agency):
    """A minimal Plan row for provenance tests."""
    from app.models import Plan
    from app.extensions import db
    p = Plan(
        agency_id=agency.id, carrier="UHC", plan_name="Test Plan",
        year=2026, plan_type="mapd", cms_plan_id="H5253-117",
    )
    db.session.add(p)
    db.session.commit()
    db.session.refresh(p)
    return p


def test_get_field_missing_returns_none(plan):
    from app.plan_provenance import get_field
    assert get_field(plan, "dental_allowance") is None


def test_set_and_get_human_value_roundtrip(plan, agent_user):
    from app.plan_provenance import set_human_value, get_field, make_value
    set_human_value(plan, "dental_allowance",
                    make_value(2000, "yr", "usd"),
                    user=agent_user, note="BCBS first look")
    rec = get_field(plan, "dental_allowance")
    assert rec["value"]["amount"] == 2000
    assert rec["value"]["display"] == "$2,000/yr"
    assert rec["source"] == "agent_edit"
    assert rec["trust"] == "agent_entered"
    assert rec["updated_by"] == "Agent"
    assert len(rec["history"]) == 1
    assert rec["history"][0]["to"] == "$2,000/yr"
    assert rec["history"][0]["note"] == "BCBS first look"


def test_field_value_returns_plain_value(plan, agent_user):
    from app.plan_provenance import set_human_value, field_value, make_value
    set_human_value(plan, "otc_allowance", make_value(45, "qtr", "usd"), user=agent_user)
    assert field_value(plan, "otc_allowance") == {
        "amount": 45, "period": "qtr", "unit": "usd", "display": "$45/qtr"
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_plan_provenance.py -k "get_field or human_value or field_value" -v`
Expected: FAIL with `ImportError: cannot import name 'get_field'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to app/plan_provenance.py
import json
from datetime import datetime


def _load(plan):
    """Return parsed details_json dict (always a dict)."""
    if not plan.details_json:
        return {}
    try:
        return json.loads(plan.details_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _save(plan, data):
    plan.details_json = json.dumps(data)


def _now():
    return datetime.utcnow().isoformat(timespec="seconds")


def get_field(plan, field):
    """Full provenance record for a field, or None if absent.

    Returns {value, source, trust, as_of, updated_at, updated_by, history}.
    """
    meta = _load(plan).get("_meta", {})
    rec = meta.get(field)
    return rec if rec else None


def field_value(plan, field):
    """Plain structured value for a field (what templates/filters call), or None."""
    rec = get_field(plan, field)
    return rec["value"] if rec else None


def set_human_value(plan, field, value, user, note=None, verify=False):
    """Apply a human edit (agent) or verification (verify=True -> AJ verified).

    Always applies immediately. Records attribution + appends history.
    """
    data = _load(plan)
    meta = data.setdefault("_meta", {})
    prev = meta.get(field, {}).get("value")
    prev_display = prev["display"] if prev else None
    source = "aj_verified" if verify else "agent_edit"
    trust = "human_verified" if verify else "agent_entered"
    history = meta.get(field, {}).get("history", [])
    history.append({
        "at": _now(),
        "by": getattr(user, "name", None),
        "from": prev_display,
        "to": value["display"],
        "note": note,
    })
    meta[field] = {
        "value": value,
        "source": source,
        "trust": trust,
        "as_of": str(plan.year),
        "updated_at": _now(),
        "updated_by": getattr(user, "name", None),
        "history": history,
    }
    _save(plan, data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_plan_provenance.py -k "get_field or human_value or field_value" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/plan_provenance.py tests/test_plan_provenance.py
git commit -m "feat(provenance): _meta read/write + set_human_value with attribution + history"
```

---

## Task 4: `set_cms_value` precedence rules — the BCBS preventer

This is the heart of the system. One function, one test per Section-4 precedence row. Build it test-first, rule by rule.

**Files:**
- Modify: `app/plan_provenance.py`
- Modify: `tests/test_plan_provenance.py`

- [ ] **Step 1: Write the failing tests (all six precedence cases)**

```python
# append to tests/test_plan_provenance.py

def test_cms_writes_to_empty_field(plan):
    from app.plan_provenance import set_cms_value, get_field, make_value
    action = set_cms_value(plan, "dental_allowance", make_value(2000, "yr", "usd"), "cms_pbp")
    assert action == "written"
    rec = get_field(plan, "dental_allowance")
    assert rec["source"] == "cms_pbp"
    assert rec["trust"] == "cms_authoritative"
    assert rec["value"]["amount"] == 2000


def test_cms_overwrites_first_look(plan, agent_user):
    from app.plan_provenance import set_cms_value, get_field, make_value, _load, _save
    # seed a carrier_first_look value directly
    data = _load(plan)
    data.setdefault("_meta", {})["dental_allowance"] = {
        "value": make_value(2000, "yr", "usd"), "source": "carrier_first_look",
        "trust": "unverified", "as_of": "2026", "updated_at": "x",
        "updated_by": None, "history": [],
    }
    _save(plan, data)
    action = set_cms_value(plan, "dental_allowance", make_value(1500, "yr", "usd"), "cms_pbp")
    assert action == "overwrote_firstlook"
    rec = get_field(plan, "dental_allowance")
    assert rec["value"]["amount"] == 1500
    assert rec["trust"] == "cms_authoritative"
    assert len(rec["history"]) == 1  # change logged


def test_cms_refreshes_prior_cms(plan):
    from app.plan_provenance import set_cms_value, get_field, make_value
    set_cms_value(plan, "pcp_copay", make_value(0, None, "usd"), "cms_pbp")
    action = set_cms_value(plan, "pcp_copay", make_value(5, None, "usd"), "cms_pbp")
    assert action == "refreshed"
    assert get_field(plan, "pcp_copay")["value"]["amount"] == 5


def test_cms_matching_agent_value_promotes_to_verified(plan, agent_user):
    from app.plan_provenance import set_cms_value, set_human_value, get_field, make_value
    set_human_value(plan, "specialist_copay", make_value(35, None, "usd"), user=agent_user)
    action = set_cms_value(plan, "specialist_copay", make_value(35, None, "usd"), "cms_pbp")
    assert action == "promoted_verified"
    rec = get_field(plan, "specialist_copay")
    assert rec["trust"] == "human_verified"


def test_cms_differing_from_agent_flags_conflict(plan, agent_user):
    from app.plan_provenance import set_cms_value, set_human_value, get_field, list_conflicts, make_value
    set_human_value(plan, "dental_allowance", make_value(2000, "yr", "usd"), user=agent_user)
    action = set_cms_value(plan, "dental_allowance", make_value(1500, "yr", "usd"), "cms_pbp")
    assert action == "conflict_flagged"
    # agent value is NOT overwritten
    assert get_field(plan, "dental_allowance")["value"]["amount"] == 2000
    conflicts = list_conflicts(plan)
    assert len(conflicts) == 1
    assert conflicts[0]["field"] == "dental_allowance"
    assert conflicts[0]["incoming"]["value"] == "$1,500/yr"
    assert plan.has_unresolved_conflicts is True


def test_cms_skips_human_verified(plan, agent_user):
    from app.plan_provenance import set_cms_value, set_human_value, get_field, make_value
    set_human_value(plan, "er_copay", make_value(150, None, "usd"), user=agent_user, verify=True)
    action = set_cms_value(plan, "er_copay", make_value(200, None, "usd"), "cms_pbp")
    assert action == "skipped_human"
    assert get_field(plan, "er_copay")["value"]["amount"] == 150  # unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_plan_provenance.py -k "cms_" -v`
Expected: FAIL with `ImportError: cannot import name 'set_cms_value'`

- [ ] **Step 3: Write the implementation**

```python
# append to app/plan_provenance.py

_CMS_TRUST = "cms_authoritative"


def _append_history(rec, by, frm, to, note):
    rec.setdefault("history", []).append(
        {"at": _now(), "by": by, "from": frm, "to": to, "note": note}
    )


def set_cms_value(plan, field, value, cms_source):
    """Apply a CMS-sourced value using the Section-4 precedence rules.

    Returns one of: 'written' | 'refreshed' | 'overwrote_firstlook'
                    | 'promoted_verified' | 'conflict_flagged' | 'skipped_human'.
    Maintains plan.cms_synced_at. Sets plan.has_unresolved_conflicts on conflict.
    """
    data = _load(plan)
    meta = data.setdefault("_meta", {})
    existing = meta.get(field)
    plan.cms_synced_at = datetime.utcnow()

    def _write(trust, source, action, history_note=None, prev_display=None):
        rec = existing or {}
        _append_history(rec, by=None, frm=prev_display,
                        to=value["display"], note=history_note)
        rec.update({
            "value": value, "source": source, "trust": trust,
            "as_of": str(plan.year), "updated_at": _now(),
            "updated_by": None,
        })
        meta[field] = rec
        _save(plan, data)
        return action

    if existing is None:
        # brand new field from CMS
        return _write(_CMS_TRUST, cms_source, "written")

    trust = existing.get("trust")
    prev_display = existing.get("value", {}).get("display")
    same = existing.get("value", {}).get("amount") == value.get("amount") and \
        existing.get("value", {}).get("display") == value.get("display")

    if trust == "human_verified":
        _save(plan, data)  # persist cms_synced_at bump only
        return "skipped_human"

    if trust == "agent_entered":
        if same:
            # CMS confirms the agent — lock as verified
            existing["trust"] = "human_verified"
            existing["source"] = "aj_verified"
            _append_history(existing, by=None, frm=prev_display,
                            to=value["display"], note="CMS confirmed agent value")
            existing["updated_at"] = _now()
            meta[field] = existing
            _save(plan, data)
            return "promoted_verified"
        # CMS disagrees with agent -> flag, do NOT overwrite
        _flag_conflict(data, plan, field, existing, value, cms_source)
        _save(plan, data)
        plan.has_unresolved_conflicts = True
        return "conflict_flagged"

    if trust == "unverified":  # carrier_first_look
        if same:
            return _write(_CMS_TRUST, cms_source, "refreshed", prev_display=prev_display)
        return _write(_CMS_TRUST, cms_source, "overwrote_firstlook", prev_display=prev_display)

    # prior CMS value -> refresh
    return _write(_CMS_TRUST, cms_source, "refreshed", prev_display=prev_display)


def _flag_conflict(data, plan, field, existing, incoming, cms_source):
    conflicts = data.setdefault("_conflicts", [])
    conflicts.append({
        "field": field,
        "existing": {
            "value": existing["value"]["display"],
            "source": existing.get("source"),
            "by": existing.get("updated_by"),
            "at": existing.get("updated_at"),
        },
        "incoming": {"value": incoming["display"], "source": cms_source, "at": _now()},
        "flagged_at": _now(),
        "resolved": False, "resolved_by": None, "resolved_at": None, "resolution": None,
    })


def list_conflicts(plan, unresolved_only=True):
    conflicts = _load(plan).get("_conflicts", [])
    if unresolved_only:
        return [c for c in conflicts if not c.get("resolved")]
    return conflicts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_plan_provenance.py -k "cms_" -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the WHOLE file to ensure nothing regressed**

Run: `python -m pytest tests/test_plan_provenance.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 6: Commit**

```bash
git add app/plan_provenance.py tests/test_plan_provenance.py
git commit -m "feat(provenance): set_cms_value precedence rules (BCBS conflict preventer)"
```

---

## Task 5: Conflict resolution lifecycle

AJ resolves a flagged conflict by choosing the surviving value. Clear the flag, recompute `has_unresolved_conflicts`.

**Files:**
- Modify: `app/plan_provenance.py`
- Modify: `tests/test_plan_provenance.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_plan_provenance.py

def test_resolve_conflict_clears_flag(plan, agent_user, admin_user):
    from app.plan_provenance import (
        set_cms_value, set_human_value, resolve_conflict,
        list_conflicts, get_field, make_value,
    )
    set_human_value(plan, "dental_allowance", make_value(2000, "yr", "usd"), user=agent_user)
    set_cms_value(plan, "dental_allowance", make_value(1500, "yr", "usd"), "cms_pbp")
    assert plan.has_unresolved_conflicts is True

    # AJ accepts the CMS value
    resolve_conflict(plan, "dental_allowance",
                     chosen=make_value(1500, "yr", "usd"),
                     user=admin_user, note="CMS approved value is correct")

    assert list_conflicts(plan) == []
    assert plan.has_unresolved_conflicts is False
    rec = get_field(plan, "dental_allowance")
    assert rec["value"]["amount"] == 1500
    assert rec["trust"] == "human_verified"  # AJ's choice is authoritative
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_plan_provenance.py::test_resolve_conflict_clears_flag -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_conflict'`

- [ ] **Step 3: Write the implementation**

```python
# append to app/plan_provenance.py

def resolve_conflict(plan, field, chosen, user, note=None):
    """AJ resolves a conflict by choosing the surviving value (human_verified).

    Marks the conflict resolved, writes the chosen value, recomputes
    plan.has_unresolved_conflicts.
    """
    data = _load(plan)
    # write the chosen value as human-verified
    meta = data.setdefault("_meta", {})
    prev = meta.get(field, {}).get("value", {}).get("display")
    history = meta.get(field, {}).get("history", [])
    history.append({"at": _now(), "by": getattr(user, "name", None),
                    "from": prev, "to": chosen["display"],
                    "note": note or "conflict resolved"})
    meta[field] = {
        "value": chosen, "source": "aj_verified", "trust": "human_verified",
        "as_of": str(plan.year), "updated_at": _now(),
        "updated_by": getattr(user, "name", None), "history": history,
    }
    # mark matching conflicts resolved
    for c in data.get("_conflicts", []):
        if c["field"] == field and not c.get("resolved"):
            c["resolved"] = True
            c["resolved_by"] = getattr(user, "name", None)
            c["resolved_at"] = _now()
            c["resolution"] = chosen["display"]
    _save(plan, data)
    # recompute flag
    remaining = [c for c in data.get("_conflicts", []) if not c.get("resolved")]
    plan.has_unresolved_conflicts = bool(remaining)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_plan_provenance.py::test_resolve_conflict_clears_flag -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/plan_provenance.py tests/test_plan_provenance.py
git commit -m "feat(provenance): resolve_conflict clears flag + recomputes plan state"
```

---

## Task 6: Model changes — Plan columns, User.role, can_edit_shared_data

Add the real columns the tests already rely on (`has_unresolved_conflicts`, `cms_synced_at`) and the RBAC `role` + helper. The `db.create_all()` fixture picks these up so prior tests keep working.

**Files:**
- Modify: `app/models.py` (Plan class ~line 296; User class ~line 29)
- Modify: `tests/test_plan_provenance.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_plan_provenance.py

def test_plan_has_provenance_columns(plan):
    # defaults
    assert plan.has_unresolved_conflicts in (False, None)
    assert plan.cms_synced_at is None


def test_can_edit_shared_data_by_role(db_session, agency):
    from app.models import User, can_edit_shared_data
    from app.extensions import db
    newbie = User(email="n@t.com", name="Newbie", is_admin=False, role="agent")
    senior = User(email="s@t.com", name="Senior", is_admin=False, role="senior_agent")
    boss = User(email="b@t.com", name="Boss", is_admin=True, role="agent")
    db.session.add_all([newbie, senior, boss])
    db.session.commit()
    assert can_edit_shared_data(newbie) is False
    assert can_edit_shared_data(senior) is True
    assert can_edit_shared_data(boss) is True   # is_admin supersedes role


def test_role_defaults_to_agent(db_session, agency):
    from app.models import User
    from app.extensions import db
    u = User(email="d@t.com", name="Default", is_admin=False)
    db.session.add(u)
    db.session.commit()
    assert u.role == "agent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_plan_provenance.py -k "provenance_columns or can_edit or role_defaults" -v`
Expected: FAIL — `AttributeError` on `has_unresolved_conflicts` / `role`, or `ImportError` for `can_edit_shared_data`

- [ ] **Step 3: Add columns to the Plan model**

In `app/models.py`, inside `class Plan`, after the `details_json` line (currently ~line 352), add:

```python
    # Provenance / integrity (spec 2026-06-02)
    cms_synced_at           = db.Column(db.DateTime, nullable=True)
    has_unresolved_conflicts = db.Column(db.Boolean, nullable=False, default=False, index=True)
```

- [ ] **Step 4: Add role to the User model**

In `app/models.py`, inside `class User`, after the `is_admin` column, add:

```python
    # RBAC: agent (read-only shared data) | senior_agent (edit) | admin
    role = db.Column(db.String(16), nullable=False, default="agent")
```

- [ ] **Step 5: Add the `can_edit_shared_data` helper**

At module level in `app/models.py` (after the `User` class), add:

```python
def can_edit_shared_data(user):
    """True if the user may edit agency-wide shared reference data (plans, etc.).

    is_admin always wins (single source of truth for admin); otherwise the role
    must be senior_agent or admin. See spec 2026-06-02 §7.
    """
    if user is None:
        return False
    if getattr(user, "is_admin", False):
        return True
    return getattr(user, "role", "agent") in ("senior_agent", "admin")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_plan_provenance.py -k "provenance_columns or can_edit or role_defaults" -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Run the WHOLE provenance test file + the existing suite (no regressions)**

Run: `python -m pytest tests/test_plan_provenance.py -v && python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add app/models.py tests/test_plan_provenance.py
git commit -m "feat(models): Plan provenance columns + User.role + can_edit_shared_data helper"
```

---

## Task 7: Year-invariant guard

The spec's hard invariant: provenance/conflict logic never compares across plan years. Since every helper operates on a single `Plan` (which is already a single `(carrier, cms_plan_id, year)` row), the invariant holds structurally. Add a regression test that proves two same-CMS-id plans in different years are fully independent.

**Files:**
- Modify: `tests/test_plan_provenance.py`

- [ ] **Step 1: Write the test**

```python
# append to tests/test_plan_provenance.py

def test_year_invariant_plans_are_independent(db_session, agency, agent_user):
    """A 2027 first-look must not touch the 2026 row, even same carrier+cms_plan_id."""
    from app.models import Plan
    from app.extensions import db
    from app.plan_provenance import set_cms_value, set_human_value, field_value, make_value

    p2026 = Plan(agency_id=agency.id, carrier="UHC", plan_name="NC-0015",
                 year=2026, plan_type="mapd", cms_plan_id="H5253-117")
    p2027 = Plan(agency_id=agency.id, carrier="UHC", plan_name="NC-0015",
                 year=2027, plan_type="mapd", cms_plan_id="H5253-117")
    db.session.add_all([p2026, p2027])
    db.session.commit()

    # 2026 gets a verified human value
    set_human_value(p2026, "dental_allowance", make_value(2000, "yr", "usd"),
                    user=agent_user, verify=True)
    # 2027 first-look CMS sync writes a different value
    set_cms_value(p2027, "dental_allowance", make_value(1500, "yr", "usd"), "cms_pbp")
    db.session.commit()

    # neither touched the other
    assert field_value(p2026, "dental_allowance")["amount"] == 2000
    assert field_value(p2027, "dental_allowance")["amount"] == 1500
    assert p2026.has_unresolved_conflicts in (False, None)
    assert p2027.has_unresolved_conflicts in (False, None)
```

- [ ] **Step 2: Run test to verify it passes** (no new code needed — structural invariant)

Run: `python -m pytest tests/test_plan_provenance.py::test_year_invariant_plans_are_independent -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_plan_provenance.py
git commit -m "test(provenance): year-invariant regression — same cms_plan_id different years independent"
```

---

## Task 8: Migration 019 (VPS-applied)

Write the Alembic migration. **Do not run locally** (no PostgreSQL). It is applied on the VPS in the deploy step.

**Files:**
- Create: `migrations/versions/019_plan_provenance.py`

- [ ] **Step 1: Write the migration file**

```python
# migrations/versions/019_plan_provenance.py
"""Plan provenance columns + User.role (RBAC foundation)

Revision ID: 019
Revises: 018
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("plans", sa.Column("cms_synced_at", sa.DateTime(), nullable=True))
    op.add_column("plans", sa.Column("has_unresolved_conflicts", sa.Boolean(),
                                     nullable=False, server_default=sa.false()))
    op.create_index("ix_plans_has_unresolved_conflicts", "plans",
                    ["has_unresolved_conflicts"])
    op.add_column("users", sa.Column("role", sa.String(16), nullable=False,
                                     server_default="agent"))
    # Backfill: existing admins -> 'admin'. Everyone else stays 'agent' (safe
    # read-only default). senior_agent promotions are done as an EXPLICIT,
    # VERIFIED post-migration step (Step 3 below) — NOT guessed here, because a
    # wrong match would grant shared-data edit rights to the wrong person.
    op.execute("UPDATE users SET role = 'admin' WHERE is_admin = true")


def downgrade():
    op.drop_column("users", "role")
    op.drop_index("ix_plans_has_unresolved_conflicts", table_name="plans")
    op.drop_column("plans", "has_unresolved_conflicts")
    op.drop_column("plans", "cms_synced_at")
```

- [ ] **Step 2: Commit (migration applied on VPS during deploy, not locally)**

```bash
git add migrations/versions/019_plan_provenance.py
git commit -m "feat(migration): 019 plan provenance columns + User.role with backfill"
```

- [ ] **Step 3: VPS apply (deploy step — run on the VPS, NOT in this environment)**

```bash
# On VPS:
cd /var/www/founders-portal && git pull \
  && ./venv/bin/pip install -r requirements.txt \
  && flask db upgrade \
  && systemctl restart founders-portal
```
Expected: `flask db upgrade` reports running revision 019.

- [ ] **Step 4: REQUIRED — verify roles + apply senior_agent promotions explicitly**

After upgrade, list every user and their role, then promote the four
senior_agents by their REAL emails (do NOT guess — confirm each address first):

```bash
# On VPS, inspect first:
sudo -u postgres psql founders_portal -c "SELECT id, name, email, is_admin, role FROM users ORDER BY id;"
```

Confirm: Brian, AJ, Tim W show `role='admin'` (from is_admin backfill). Then
promote the four senior_agents using their confirmed emails:

```bash
sudo -u postgres psql founders_portal -c "
  UPDATE users SET role='senior_agent'
  WHERE email IN (
    '<rebekah_real_email>', '<justin_real_email>',
    '<chris_real_email>',   '<mike_real_email>'
  );"
```

Re-run the SELECT and confirm: Anj P, Betty M remain `agent`; Alex is absent
(not provisioned). Any wrong assignment = someone can edit shared plan data who
shouldn't — verify before moving on.

---

## Final verification

- [ ] **Run the full provenance suite + whole test suite**

Run: `python -m pytest tests/test_plan_provenance.py -v && python -m pytest tests/ -v`
Expected: all PASS (provenance file ~20 tests; existing suite unaffected).

- [ ] **Update CLAUDE.md** with a one-line note under build status:

```
- **Plan Data Provenance (core) ✅** — app/plan_provenance.py is the seam owning
  structured benefit values + _meta/_conflicts; set_cms_value enforces CMS-vs-human
  precedence (first-looks yield to CMS, CMS never clobbers human_verified, CMS-vs-agent
  mismatch flags a conflict). Migration 019: plans.cms_synced_at, plans.has_unresolved_conflicts,
  users.role (agent|senior_agent|admin) + can_edit_shared_data(). Spec:
  docs/superpowers/specs/2026-06-02-plan-data-integrity-provenance-design.md.
  Next: Plan 2 (sync retrofit + OTC/meals from PBP b13).
```

```bash
git add CLAUDE.md && git commit -m "docs(claude): note plan provenance core complete"
```
