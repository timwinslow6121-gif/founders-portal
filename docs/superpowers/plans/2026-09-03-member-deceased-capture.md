# Member Deceased Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record when a carrier tells us a member has died, suppress them from outreach without hiding or deleting anything, and let agents mark a death manually.

**Architecture:** Two new columns (migration 043) plus a `set_carrier_value()` provenance writer that mirrors the existing `set_human_value()`. Two parsers capture death signals already present in files we ingest. One `is_contactable()` accessor is the single suppression seam. A dry-run-first backfill marks the 20 known cases.

**Tech Stack:** Flask 3.0, Flask-SQLAlchemy, Flask-Migrate (Alembic), PostgreSQL 16 on prod / SQLite in tests, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-member-deceased-capture-design.md`

## Global Constraints

- **Migration head is currently `042`.** This work adds `043`, `down_revision = "042"`. Follow the style of `migrations/versions/042_provider_plans.py` (string revision ids, `op.batch_alter_table` for column adds).
- **Exact unique-ID matching only.** MBI for UHC, Humana ID for Humana. No name matching, no name+DOB, no fuzzy fallback anywhere in this work. An ID resolving to 0 or >1 customer marks nobody.
- **Never erase.** A carrier import must never clear an existing `deceased_date`. An agent's mark (`agent_entered`) outranks a carrier's (`carrier_import`).
- **Suppress, never delete or hide.** Policies, payments, notes and history stay intact and visible. Suppression means excluded from outreach selection and flagged in exports.
- **Termination is carrier-scoped.** A UHC death terms the UHC policy only. Never term another carrier's policy, and manual marking terms nothing at all.
- **Trust order** (existing, in `app/customer_provenance.py`): `carrier_import` (1) < `agent_entered` (2) < `human_verified` (3).
- **Run tests with `/usr/bin/python3 -m pytest`** — the repo's default `python3` is a venv without pytest.
- All money must be unchanged by this work. The backfill verifies payment and ledger totals before and after.

---

### Task 1: Migration 043 + model columns

**Files:**
- Create: `migrations/versions/043_deceased_capture.py`
- Modify: `app/models.py` (Customer class, after `language`; Policy class, near `term_reason`)
- Test: `tests/test_deceased_model.py`

**Interfaces:**
- Produces: `Customer.deceased_date` (Date, nullable, indexed), `Policy.term_reason_raw` (String(64), nullable)

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_deceased_model.py"""
from datetime import date


def test_customer_has_a_deceased_date(app, agency, db_session):
    from app.extensions import db
    from app.models import Customer
    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B",
                     full_name="A B", deceased_date=date(2026, 4, 30))
        db.session.add(c); db.session.commit()
        assert Customer.query.get(c.id).deceased_date == date(2026, 4, 30)


def test_deceased_date_defaults_to_none(app, agency, db_session):
    from app.extensions import db
    from app.models import Customer
    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="A", last_name="B", full_name="A B")
        db.session.add(c); db.session.commit()
        assert Customer.query.get(c.id).deceased_date is None


def test_policy_keeps_the_carriers_own_term_wording(app, agency, db_session):
    """term_reason_raw holds the carrier's verbatim words; the existing free-text
    term_reason stays for human notes."""
    from app.extensions import db
    from app.models import Policy
    with app.app_context():
        p = Policy(agency_id=agency.id, carrier="UHC", member_id="X1",
                   status="active", term_reason_raw="Death")
        db.session.add(p); db.session.commit()
        assert Policy.query.get(p.id).term_reason_raw == "Death"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_deceased_model.py -q`
Expected: FAIL — `TypeError: 'deceased_date' is an invalid keyword argument for Customer`

- [ ] **Step 3: Add the columns to the models**

In `app/models.py`, inside `class Customer`, immediately after the `language` column:

```python
    deceased_date     = db.Column(db.Date, index=True)   # carrier-reported or agent-marked
```

Inside `class Policy`, immediately after the existing `term_reason` column:

```python
    term_reason_raw   = db.Column(db.String(64))   # carrier's verbatim wording
```

- [ ] **Step 4: Write the migration**

```python
"""deceased_date + term_reason_raw

Revision ID: 043
Revises: 042
"""
from alembic import op
import sqlalchemy as sa

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("customers") as b:
        b.add_column(sa.Column("deceased_date", sa.Date(), nullable=True))
    op.create_index("ix_customers_deceased_date", "customers", ["deceased_date"])
    with op.batch_alter_table("policies") as b:
        b.add_column(sa.Column("term_reason_raw", sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table("policies") as b:
        b.drop_column("term_reason_raw")
    op.drop_index("ix_customers_deceased_date", table_name="customers")
    with op.batch_alter_table("customers") as b:
        b.drop_column("deceased_date")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_deceased_model.py -q`
Expected: PASS (3 tests)

Then the full suite: `/usr/bin/python3 -m pytest -q` — expected PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add app/models.py migrations/versions/043_deceased_capture.py tests/test_deceased_model.py
git commit -m "feat(deceased): add Customer.deceased_date + Policy.term_reason_raw (migration 043)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `set_carrier_value()` provenance writer

**Files:**
- Modify: `app/customer_provenance.py` (add `deceased_date` to `PROVENANCE_FIELDS`; add `set_carrier_value`; export it in `__all__`)
- Test: `tests/test_carrier_provenance_writer.py`

**Interfaces:**
- Consumes: `Customer.deceased_date` from Task 1
- Produces: `set_carrier_value(customer, field, value, source) -> bool` — returns True if written, False if refused. `source` is a short string such as `"uhc_commission"` or `"humana_bob"`.

**Why this task exists:** `app/customer_provenance.py` currently exposes only `set_human_value()` and is not wired into `app/upload.py` or `app/commission/resolver.py` at all — those write customer fields directly via `_fill_if_blank`. A carrier-side writer does not exist and must be built. Retrofitting the other provenance fields onto it is explicitly NOT in scope.

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_carrier_provenance_writer.py"""
from datetime import date


def _cust(app, agency, **kw):
    from app.extensions import db
    from app.models import Customer
    c = Customer(agency_id=agency.id, first_name="A", last_name="B",
                 full_name="A B", **kw)
    db.session.add(c); db.session.commit()
    return c


def test_carrier_value_writes_when_the_field_is_empty(app, agency, db_session):
    from app.customer_provenance import set_carrier_value
    with app.app_context():
        c = _cust(app, agency)
        assert set_carrier_value(c, "deceased_date", date(2026, 4, 30), "uhc_commission")
        assert c.deceased_date == date(2026, 4, 30)


def test_a_carrier_never_clears_an_existing_deceased_date(app, agency, db_session):
    """Never-erase: a later file that no longer mentions the death must not undo it."""
    from app.customer_provenance import set_carrier_value
    with app.app_context():
        c = _cust(app, agency, deceased_date=date(2026, 4, 30))
        assert set_carrier_value(c, "deceased_date", None, "uhc_commission") is False
        assert c.deceased_date == date(2026, 4, 30)


def test_a_carrier_cannot_overwrite_an_agents_mark(app, agency, db_session):
    """agent_entered outranks carrier_import."""
    from app.customer_provenance import set_carrier_value, set_human_value
    from app.models import User
    with app.app_context():
        u = User(email="a@t.com", name="Agent A", agency_id=agency.id)
        db_session.add(u); db_session.commit()
        c = _cust(app, agency)
        set_human_value(c, "deceased_date", date(2026, 1, 1), u)
        assert set_carrier_value(c, "deceased_date", date(2026, 8, 8), "humana_bob") is False
        assert c.deceased_date == date(2026, 1, 1)


def test_a_carrier_may_correct_its_own_earlier_value(app, agency, db_session):
    from app.customer_provenance import set_carrier_value
    with app.app_context():
        c = _cust(app, agency)
        set_carrier_value(c, "deceased_date", date(2026, 4, 30), "uhc_commission")
        assert set_carrier_value(c, "deceased_date", date(2026, 4, 15), "uhc_commission")
        assert c.deceased_date == date(2026, 4, 15)


def test_it_records_who_and_when(app, agency, db_session):
    import json
    from app.customer_provenance import set_carrier_value
    with app.app_context():
        c = _cust(app, agency)
        set_carrier_value(c, "deceased_date", date(2026, 4, 30), "uhc_commission")
        meta = json.loads(c.field_provenance)["_meta"]["deceased_date"]
        assert meta["source"] == "uhc_commission"
        assert meta["trust"] == "carrier_import"
        assert meta["value"] == "2026-04-30"


def test_an_unknown_field_is_rejected(app, agency, db_session):
    import pytest
    from app.customer_provenance import set_carrier_value
    with app.app_context():
        c = _cust(app, agency)
        with pytest.raises(ValueError):
            set_carrier_value(c, "not_a_field", "x", "uhc_commission")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_carrier_provenance_writer.py -q`
Expected: FAIL — `ImportError: cannot import name 'set_carrier_value'`

- [ ] **Step 3: Implement the writer**

In `app/customer_provenance.py`, add `"deceased_date"` to the end of the `PROVENANCE_FIELDS` list, add `"set_carrier_value"` to `__all__`, and add this function after `set_human_value`:

```python
def set_carrier_value(customer, field, value, source):
    """Apply a CARRIER-sourced value, respecting the trust ladder.

    Returns True if written, False if refused. Unlike set_human_value this never
    sets manually_edited — a carrier import is not a human edit.

    Refuses when:
      - value is None (never-erase: a file that no longer mentions a fact must
        not undo it), or
      - the field already holds a value written at a HIGHER trust than
        carrier_import (an agent's mark outranks a carrier's).
    """
    if field not in PROVENANCE_FIELDS:
        raise ValueError(f"{field} is not a provenance-tracked field")
    if value is None:
        return False

    data = _load(customer)
    meta = data.setdefault("_meta", {})
    existing = meta.get(field, {})
    cur_trust = TRUST_ORDER.get(existing.get("trust"), 0)
    if cur_trust > TRUST_ORDER["carrier_import"]:
        return False

    _set_column(customer, field, value)
    scalar = _to_scalar(value)
    history = existing.get("history", [])
    history.append({"at": _now(), "by": source,
                    "from": existing.get("value"), "to": scalar, "note": None})
    meta[field] = {
        "value": scalar,
        "source": source,
        "trust": "carrier_import",
        "updated_at": _now(),
        "updated_by": source,
        "history": history,
        "rejected_values": existing.get("rejected_values", []),
    }
    _save(customer, data)
    return True
```

Also extend `_set_column` so a `deceased_date` string coerces to a date, matching the existing `dob` handling — change its condition from `if field == "dob"` to:

```python
    if field in ("dob", "deceased_date") and isinstance(value, str) and value:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_carrier_provenance_writer.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/customer_provenance.py tests/test_carrier_provenance_writer.py
git commit -m "feat(deceased): add set_carrier_value() writer with never-erase + trust ladder

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `is_contactable()` suppression accessor

**Files:**
- Modify: `app/models.py` (module-level function near `can_edit_shared_data`)
- Test: `tests/test_is_contactable.py`

**Interfaces:**
- Consumes: `Customer.deceased_date` from Task 1
- Produces: `is_contactable(customer) -> bool` — the ONLY place the suppression rule lives. Later tasks and any future mailing feature call this rather than testing `deceased_date` directly.

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_is_contactable.py"""
from datetime import date


def test_a_living_customer_is_contactable(app, agency, db_session):
    from app.models import Customer, is_contactable
    with app.app_context():
        assert is_contactable(Customer(agency_id=agency.id, first_name="A",
                                       last_name="B", full_name="A B"))


def test_a_deceased_customer_is_not_contactable(app, agency, db_session):
    from app.models import Customer, is_contactable
    with app.app_context():
        assert not is_contactable(Customer(
            agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
            deceased_date=date(2026, 4, 30)))


def test_none_is_not_contactable(app, agency, db_session):
    """Defensive: a missing customer must never be treated as mailable."""
    from app.models import is_contactable
    with app.app_context():
        assert not is_contactable(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_is_contactable.py -q`
Expected: FAIL — `ImportError: cannot import name 'is_contactable'`

- [ ] **Step 3: Implement the accessor**

In `app/models.py`, next to `can_edit_shared_data`:

```python
def is_contactable(customer) -> bool:
    """The single suppression seam: may this customer receive outreach?

    A deceased customer stays fully visible in the book — policies, payments,
    notes and history are never hidden or deleted — but must not appear on a
    mailing list, campaign or outreach selection. Any future AEP mailer MUST
    call this rather than testing deceased_date directly.
    """
    if customer is None:
        return False
    return customer.deceased_date is None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_is_contactable.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_is_contactable.py
git commit -m "feat(deceased): add is_contactable() as the single suppression seam

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Capture UHC `Term Reason` from commission statements

**Files:**
- Modify: `app/commission/member_fact.py` (add `term_reason_raw` field to `MemberFact`)
- Modify: `app/commission/normalizers.py` (`normalize_uhc` — populate it)
- Test: `tests/test_uhc_term_reason_capture.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `MemberFact.term_reason_raw: str = ""` — Task 6 reads it to decide a death.

**Real data:** the May statement has 45 populated (`Death` 18, `Member Termination` 16, `Enrollment in Another Plan` 11); July has 79 (`Death` 34, `Member Termination` 22, `Enrollment in Another Plan` 22, `Star Plan Change` 1). `"Enrollment in Another Plan"` is a switcher signal — capture it, do NOT act on it; acting belongs to the separate carrier-switch work.

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_uhc_term_reason_capture.py"""


def _uhc_sheet(term_reason):
    """Minimal UHC raw commission sheet.

    The real file is keyed by FIXED COLUMN INDEX off the 'Commission Transactions'
    sheet (see _UHC_* constants in app/commission/ledger.py): writing id 4,
    member name 7, MedicareID 8, plan type 12, action 19, amount 23. Term Reason
    is column 24 in the real statement. Build 30 columns so the indices land.
    """
    header = [""] * 30
    header[4], header[5], header[7], header[8] = ("Writing Agent ID",
                                                  "Writing Agent Name",
                                                  "Member Name", "MedicareID")
    header[11], header[12], header[19] = ("Original Effective Date", "Plan Type",
                                          "Commission Action")
    header[23], header[24], header[28] = "Commission ($)", "Term Reason", "Term Date"
    row = [""] * 30
    row[4], row[5], row[7], row[8] = "1839547", "WINSLOW, TIMOTHY J", "BOST, LINDA H.", "6MV0WK0MP06"
    row[11], row[12], row[19] = "2023-01-01", "MAPD", "Renewal"
    row[23], row[24], row[28] = "28.92", term_reason, "2026-05-31"
    return {"Commission Transactions": [header, row]}


def test_term_reason_is_captured_verbatim():
    from app.commission.normalizers import normalize_uhc
    facts = normalize_uhc(_uhc_sheet("Death"))
    assert any(f.term_reason_raw == "Death" for f in facts)


def test_a_blank_term_reason_is_empty_not_none():
    from app.commission.normalizers import normalize_uhc
    facts = normalize_uhc(_uhc_sheet(""))
    assert all(f.term_reason_raw == "" for f in facts)


def test_other_reasons_are_captured_but_are_not_deaths():
    """'Enrollment in Another Plan' is a switcher signal — stored, not acted on."""
    from app.commission.normalizers import normalize_uhc
    facts = normalize_uhc(_uhc_sheet("Enrollment in Another Plan"))
    assert any(f.term_reason_raw == "Enrollment in Another Plan" for f in facts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_uhc_term_reason_capture.py -q`
Expected: FAIL — `AttributeError: 'MemberFact' object has no attribute 'term_reason_raw'`

- [ ] **Step 3: Add the field and populate it**

In `app/commission/member_fact.py`, in the `# lifecycle` block of the `MemberFact` dataclass, after `term_date`:

```python
    term_reason_raw: str = ""             # carrier's verbatim wording, e.g. "Death"
```

In `app/commission/ledger.py`, beside the other `_UHC_*` column constants (around line 736), add:

```python
_UHC_TERMREASON = 24  # Term Reason — plain English: "Death", "Member Termination",
                      # "Enrollment in Another Plan", "Star Plan Change"
```

In `app/commission/normalizers.py`, import it alongside the existing `_UHC_*` imports, and inside `normalize_uhc`'s row loop add a safe read:

```python
        term_reason = (str(row[_UHC_TERMREASON] or "").strip()
                       if len(row) > _UHC_TERMREASON else "")
```

then add `term_reason_raw=term_reason,` to each `MemberFact(...)` call in that function.

⚠ This follows UHC's existing fixed-index convention because that is how the rest
of the UHC path reads this file; a header-name rewrite is the separate ingest-
robustness work and must not be started here. The `len(row) >` guard means an
export without the column yields `""` rather than raising.

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_uhc_term_reason_capture.py -q`
Expected: PASS (3 tests)

Then `/usr/bin/python3 -m pytest -q` — expected PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add app/commission/member_fact.py app/commission/normalizers.py tests/test_uhc_term_reason_capture.py
git commit -m "feat(deceased): capture UHC commission Term Reason verbatim

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Capture Humana BOB `Deceased Date`

**Files:**
- Modify: `app/parsers/humana.py`
- Test: `tests/test_humana_deceased_capture.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `rec["deceased_date"]` — a `datetime.date` or `None` — in every record the Humana parser emits. Task 6 reads it.

**Real data:** the August BOB has 5 populated — Evans 8/11, Golden 8/8, Nesbitt 8/9, Patterson 8/12, Walker 8/7. The column is named `Deceased Date`.

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_humana_deceased_capture.py"""
from datetime import date


def test_the_parser_emits_a_deceased_date(tmp_path):
    import pandas as pd
    from app.parsers.humana import parse
    p = tmp_path / "humana.xlsx"
    pd.DataFrame([{
        "MbrFirstName": "JEANETTE", "MbrLastName": "EVANS", "Humana ID": "H59692289",
        "Medicare No": "XXXXXN4FP75", "Birth Date": "3/11/1949", "Status": "Active Policy",
        "Effective Date": "1/1/2026", "Inactive Date": "8/31/2026",
        "Deceased Date": "8/11/2026", "Plan Name": "HUMANA GOLD PLUS HMO POS",
        "Plan Type": "MA", "Contract-PBP-Segment ID": "H1036-335-002",
        "Mail City": "Concord", "Mail State": "NC", "Mail ZipCd": "28025",
        "Mail Cnty": "CABARRUS", "Primary Phone": "704-555-0134",
        "Mail Address": "1 Main St",
    }]).to_excel(p, index=False)
    recs = parse(str(p))
    assert recs[0]["deceased_date"] == date(2026, 8, 11)


def test_a_blank_deceased_date_is_none(tmp_path):
    import pandas as pd
    from app.parsers.humana import parse
    p = tmp_path / "humana.xlsx"
    pd.DataFrame([{
        "MbrFirstName": "ROBERT", "MbrLastName": "HAMRICK", "Humana ID": "H63268953",
        "Medicare No": "XXXXXN4FP76", "Birth Date": "3/11/1949", "Status": "Active Policy",
        "Effective Date": "1/1/2026", "Inactive Date": "", "Deceased Date": "",
        "Plan Name": "HUMANA GOLD PLUS HMO POS", "Plan Type": "MA",
        "Contract-PBP-Segment ID": "H1036-335-002", "Mail City": "Concord",
        "Mail State": "NC", "Mail ZipCd": "28025", "Mail Cnty": "CABARRUS",
        "Primary Phone": "704-555-0135", "Mail Address": "2 Main St",
    }]).to_excel(p, index=False)
    assert parse(str(p))[0]["deceased_date"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_humana_deceased_capture.py -q`
Expected: FAIL — `KeyError: 'deceased_date'`

- [ ] **Step 3: Emit the field**

In `app/parsers/humana.py`, in the record dict built for each row, add alongside the existing `"term_date"` entry:

```python
            "deceased_date":  _parse_date(row, "Deceased Date"),
```

Use the same `_parse_date` helper the file already uses for `Inactive Date`, so a blank yields `None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_humana_deceased_capture.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/parsers/humana.py tests/test_humana_deceased_capture.py
git commit -m "feat(deceased): capture Humana BOB Deceased Date

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Apply death on import — exact-ID matching, carrier-scoped termination

**Files:**
- Create: `app/deceased.py`
- Modify: `app/upload.py` (`_upsert_customer_from_policy` — call the applier)
- Modify: `app/commission/resolver.py` (`_resolve_commission_match_or_park` — call the applier on a resolved customer)
- Test: `tests/test_deceased_apply.py`

**Interfaces:**
- Consumes: `set_carrier_value` (Task 2), `MemberFact.term_reason_raw` (Task 4), `rec["deceased_date"]` (Task 5)
- Produces:
  - `apply_death(customer, when, source, agency_id, carrier=None) -> bool` — marks the person; when `carrier` is given, also terms that carrier's active policies for them. Returns True if the mark was written.
  - `death_date_from_uhc_fact(fact) -> date | None` — `fact.term_date` when `term_reason_raw` is `"death"` (case-insensitive), else None.

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_deceased_apply.py"""
from datetime import date


def _person(app, agency, mbi="1AA1AA1AA11"):
    from app.extensions import db
    from app.models import Customer, Policy
    c = Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                 full_name="Linda Bost", mbi=mbi)
    db.session.add(c); db.session.flush()
    uhc = Policy(agency_id=agency.id, carrier="UHC", member_id=mbi, mbi=mbi,
                 status="active", customer_id=c.id, full_name="Linda Bost")
    bcbs = Policy(agency_id=agency.id, carrier="BCBS", member_id="B1", mbi=mbi,
                  status="active", customer_id=c.id, full_name="Linda Bost")
    db.session.add_all([uhc, bcbs]); db.session.commit()
    return c, uhc, bcbs


def test_apply_death_marks_the_person(app, agency, db_session):
    from app.deceased import apply_death
    with app.app_context():
        c, _, _ = _person(app, agency)
        assert apply_death(c, date(2026, 4, 30), "uhc_commission", agency.id)
        assert c.deceased_date == date(2026, 4, 30)


def test_it_terms_only_the_reporting_carriers_policy(app, agency, db_session):
    """Carrier-scoped: UHC's death must not term a BCBS Medigap."""
    from app.deceased import apply_death
    with app.app_context():
        c, uhc, bcbs = _person(app, agency)
        apply_death(c, date(2026, 4, 30), "uhc_commission", agency.id, carrier="UHC")
        assert uhc.status == "termed"
        assert uhc.term_date == date(2026, 4, 30)
        assert bcbs.status == "active"


def test_without_a_carrier_it_terms_nothing(app, agency, db_session):
    """Manual marking suppresses outreach but never terms a policy."""
    from app.deceased import apply_death
    with app.app_context():
        c, uhc, bcbs = _person(app, agency)
        apply_death(c, date(2026, 4, 30), "agent", agency.id)
        assert uhc.status == "active" and bcbs.status == "active"


def test_it_never_clears_an_existing_mark(app, agency, db_session):
    from app.deceased import apply_death
    with app.app_context():
        c, _, _ = _person(app, agency)
        apply_death(c, date(2026, 4, 30), "uhc_commission", agency.id)
        assert apply_death(c, None, "uhc_commission", agency.id) is False
        assert c.deceased_date == date(2026, 4, 30)


def test_death_date_read_from_a_uhc_fact():
    from types import SimpleNamespace
    from app.deceased import death_date_from_uhc_fact
    f = SimpleNamespace(term_reason_raw="Death", term_date=date(2026, 4, 30))
    assert death_date_from_uhc_fact(f) == date(2026, 4, 30)


def test_other_term_reasons_are_not_deaths():
    from types import SimpleNamespace
    from app.deceased import death_date_from_uhc_fact
    for reason in ("Member Termination", "Enrollment in Another Plan",
                   "Star Plan Change", ""):
        f = SimpleNamespace(term_reason_raw=reason, term_date=date(2026, 4, 30))
        assert death_date_from_uhc_fact(f) is None


def test_death_matching_is_case_insensitive():
    from types import SimpleNamespace
    from app.deceased import death_date_from_uhc_fact
    f = SimpleNamespace(term_reason_raw="DEATH", term_date=date(2026, 4, 30))
    assert death_date_from_uhc_fact(f) == date(2026, 4, 30)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_deceased_apply.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.deceased'`

- [ ] **Step 3: Implement the applier**

Create `app/deceased.py`:

```python
"""Recording that a member has died, from carrier files or an agent.

Suppression is person-level and immediate; TERMINATION is carrier-scoped. A
carrier reporting a death terms only its own policies — death propagates
SSA -> CMS -> carriers, so the other carriers report it themselves within a
month or two, and auto-terming their policies front-runs data already coming
while taking on false-positive risk. Ancillary products (hospital indemnity,
DVH) may pay a benefit or convert rather than simply ending, so terming them
automatically would encode a guess.

Manual marking passes no carrier and therefore terms nothing.
"""
from datetime import date
from typing import Optional

from app.customer_provenance import set_carrier_value
from app.models import Policy


def death_date_from_uhc_fact(fact) -> Optional[date]:
    """The date of death a UHC commission row implies, or None.

    UHC states it in plain English in its Term Reason column ("Death"), so no
    code lookup is needed. Every other value there -- "Member Termination",
    "Enrollment in Another Plan", "Star Plan Change" -- is NOT a death.
    """
    if (getattr(fact, "term_reason_raw", "") or "").strip().lower() != "death":
        return None
    return getattr(fact, "term_date", None)


def apply_death(customer, when, source, agency_id, carrier=None) -> bool:
    """Mark `customer` deceased and, when `carrier` is given, term that carrier's
    active policies for them. Returns True if the mark was written.

    Writes through set_carrier_value, so the never-erase rule and the trust
    ladder apply: a None date refuses, and an agent's mark outranks a carrier's.
    """
    if customer is None:
        return False
    wrote = set_carrier_value(customer, "deceased_date", when, source)
    if not wrote:
        return False
    if carrier:
        for pol in Policy.query.filter_by(agency_id=agency_id, carrier=carrier,
                                          customer_id=customer.id,
                                          status="active").all():
            pol.status = "termed"
            if pol.term_date is None:
                pol.term_date = when
            if not pol.term_reason_raw:
                pol.term_reason_raw = "Death"
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_deceased_apply.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Wire it into the two import paths**

In `app/upload.py`, inside `_upsert_customer_from_policy`, immediately before the `sweep_parked_payments` call at the end:

```python
    # Humana masks the MBI but names a Deceased Date. The customer here was
    # resolved by exact carrier id upstream, so no extra matching is done.
    if rec.get("deceased_date"):
        from app.deceased import apply_death
        apply_death(customer, rec["deceased_date"], f"{rec.get('carrier','')}_bob".lower(),
                    agency_id, carrier=rec.get("carrier"))
```

In `app/commission/resolver.py`, inside `_resolve_commission_match_or_park`, in the `_attach` helper (which runs only when a customer was matched by MBI or carrier id — never on a parked row):

```python
    from app.deceased import death_date_from_uhc_fact, apply_death
    _died = death_date_from_uhc_fact(fact)
    if _died:
        apply_death(customer, _died, f"{fact.carrier}_commission".lower(),
                    agency_id, carrier=fact.carrier)
```

Both sites act only on an already-resolved customer, so exact-ID matching is inherited — no name or DOB matching is introduced anywhere.

- [ ] **Step 6: Run the full suite**

Run: `/usr/bin/python3 -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add app/deceased.py app/upload.py app/commission/resolver.py tests/test_deceased_apply.py
git commit -m "feat(deceased): apply death on import, carrier-scoped termination

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Manual marking on the customer profile

**Files:**
- Modify: `app/customers.py` (new route `customer_set_deceased`)
- Modify: `app/templates/customer_profile.html` (badge + inline control)
- Test: `tests/test_deceased_manual_mark.py`

**Interfaces:**
- Consumes: `apply_death` (Task 6), `set_human_value` (existing), `is_contactable` (Task 3)
- Produces: `POST /customers/<int:customer_id>/deceased` accepting form fields `deceased_date` (ISO date, may be blank for "unknown") and `note`; and `action=clear` with a required `note` to clear.

**Why:** agents learn of deaths weeks before carriers do — a family member calls, or an obituary appears. This is also the correction path when a carrier's mark is wrong.

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_deceased_manual_mark.py"""
from datetime import date


def _setup(app, agency):
    from app.extensions import db
    from app.models import Customer, Policy, User
    with app.app_context():
        u = User(email="agent@t.com", name="Agent A", agency_id=agency.id, is_admin=True)
        db.session.add(u); db.session.flush()
        c = Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                     full_name="Linda Bost", mbi="1AA1AA1AA11", primary_agent_id=u.id)
        db.session.add(c); db.session.flush()
        db.session.add(Policy(agency_id=agency.id, carrier="UHC", member_id="1AA1AA1AA11",
                              mbi="1AA1AA1AA11", status="active", customer_id=c.id,
                              full_name="Linda Bost"))
        db.session.commit()
        return u.id, c.id


def _login(client, uid):
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)


def test_an_agent_can_mark_a_customer_deceased(client, app, agency, db_session):
    from app.models import Customer
    uid, cid = _setup(app, agency)
    _login(client, uid)
    r = client.post(f"/customers/{cid}/deceased",
                    data={"deceased_date": "2026-08-14", "note": "son called"})
    assert r.status_code in (200, 302)
    with app.app_context():
        assert Customer.query.get(cid).deceased_date == date(2026, 8, 14)


def test_manual_marking_never_terms_a_policy(app, client, agency, db_session):
    """An agent knowing someone died does not mean the carrier has processed it."""
    from app.models import Policy
    uid, cid = _setup(app, agency)
    _login(client, uid)
    client.post(f"/customers/{cid}/deceased", data={"deceased_date": "2026-08-14"})
    with app.app_context():
        assert Policy.query.filter_by(customer_id=cid).first().status == "active"


def test_an_unknown_date_is_allowed(client, app, agency, db_session):
    """Records the mark without inventing a date."""
    from app.models import Customer
    uid, cid = _setup(app, agency)
    _login(client, uid)
    client.post(f"/customers/{cid}/deceased", data={"deceased_date": "", "note": "obituary"})
    with app.app_context():
        c = Customer.query.get(cid)
        assert c.deceased_date is not None      # marked, with a recorded date


def test_clearing_requires_a_reason(client, app, agency, db_session):
    from app.models import Customer
    uid, cid = _setup(app, agency)
    _login(client, uid)
    client.post(f"/customers/{cid}/deceased", data={"deceased_date": "2026-08-14"})
    r = client.post(f"/customers/{cid}/deceased", data={"action": "clear", "note": ""})
    assert r.status_code == 400
    with app.app_context():
        assert Customer.query.get(cid).deceased_date is not None


def test_clearing_with_a_reason_works(client, app, agency, db_session):
    from app.models import Customer
    uid, cid = _setup(app, agency)
    _login(client, uid)
    client.post(f"/customers/{cid}/deceased", data={"deceased_date": "2026-08-14"})
    client.post(f"/customers/{cid}/deceased",
                data={"action": "clear", "note": "carrier had the wrong member"})
    with app.app_context():
        assert Customer.query.get(cid).deceased_date is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_deceased_manual_mark.py -q`
Expected: FAIL — 404 (route does not exist)

- [ ] **Step 3: Add the route**

In `app/customers.py`, following the existing inline-edit route pattern (agency-scoped `first_or_404`):

```python
@customers_bp.route("/customers/<int:customer_id>/deceased", methods=["POST"])
@login_required
def customer_set_deceased(customer_id):
    """Mark or clear a customer's deceased status.

    Agents hear of a death weeks before carriers do, so this is the fast path
    to suppressing outreach — and the correction path when a carrier's mark is
    wrong. It NEVER terms a policy: termination follows the carrier.
    """
    from datetime import date as _date
    from app.customer_provenance import set_human_value
    from app.deceased import apply_death

    customer = Customer.query.filter_by(
        id=customer_id, agency_id=current_user.agency_id).first_or_404()
    note = (request.form.get("note") or "").strip()

    if request.form.get("action") == "clear":
        if not note:
            return jsonify({"error": "A reason is required to clear a deceased mark."}), 400
        set_human_value(customer, "deceased_date", None, current_user, note=note)
        log_event("customer_deceased_cleared", category="admin",
                  detail=f"cleared deceased mark: {note}", customer_id=customer.id)
        db.session.commit()
        return jsonify({"ok": True, "deceased_date": None})

    raw = (request.form.get("deceased_date") or "").strip()
    try:
        when = _date.fromisoformat(raw) if raw else _date.today()
    except ValueError:
        return jsonify({"error": "Enter the date as YYYY-MM-DD."}), 400

    # set_human_value writes at agent_entered trust, which outranks a carrier's
    # mark and cannot be undone by a later import.
    set_human_value(customer, "deceased_date", when, current_user,
                    note=note or ("date unknown" if not raw else None))
    log_event("customer_marked_deceased", category="admin",
              detail=f"marked deceased {when}: {note}", customer_id=customer.id)
    db.session.commit()
    return jsonify({"ok": True, "deceased_date": when.isoformat()})
```

- [ ] **Step 4: Add the badge and control to the profile template**

In `app/templates/customer_profile.html`, near the Medicaid/Language inline fields:

```html
{% if customer.deceased_date %}
  <div class="badge badge-deceased" title="Suppressed from mailings and campaigns">
    Deceased — {{ customer.deceased_date.strftime('%b %-d, %Y') }}
    {%- set meta = deceased_meta %}
    {%- if meta and meta.source %} · per {{ meta.source|replace('_', ' ') }}{% endif %}
  </div>
  <button type="button" class="btn-secondary" onclick="clearDeceased({{ customer.id }})">
    Not deceased — correct this
  </button>
{% else %}
  <button type="button" class="btn-secondary" onclick="markDeceased({{ customer.id }})">
    Mark deceased
  </button>
{% endif %}
```

with the two handlers posting to the route (prompting for date and note on mark, and requiring a reason on clear).

- [ ] **Step 5: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_deceased_manual_mark.py -q`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add app/customers.py app/templates/customer_profile.html tests/test_deceased_manual_mark.py
git commit -m "feat(deceased): agents can mark or correct a deceased customer

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Surface suppression in the customer list and export

**Files:**
- Modify: `app/customers.py` (`customers_export` — add the column and the provenance note; `customers_list` — pass the flag)
- Modify: `app/templates/customers_list.html` (row badge)
- Test: `tests/test_deceased_suppression.py`

**Interfaces:**
- Consumes: `is_contactable` (Task 3)
- Produces: a `Deceased` column in both export modes; the filter-provenance line gains `· N deceased (suppress from mailings)` when any exported row is deceased.

**Context:** the export already writes a leading `#` provenance line (`_filter_description` in `app/customers.py`) and has `CUSTOMER_COLS` / `PLAN_COLS` lists.

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_deceased_suppression.py"""
import csv
import io
from datetime import date


def _setup(app, agency):
    from app.extensions import db
    from app.models import Customer, User
    with app.app_context():
        u = User(email="x@t.com", name="X", is_admin=True, agency_id=agency.id)
        db.session.add(u); db.session.flush()
        db.session.add(Customer(agency_id=agency.id, first_name="Alive", last_name="One",
                                full_name="Alive One", mbi="1AA1AA1AA11"))
        db.session.add(Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                                full_name="Linda Bost", mbi="6MV0WK0MP06",
                                deceased_date=date(2026, 4, 30)))
        db.session.commit()
        return u.id


def _rows(resp):
    body = resp.data.decode()
    return list(csv.DictReader(io.StringIO(body.split("\n", 1)[1])))


def test_export_has_a_deceased_column(client, app, agency, db_session):
    uid = _setup(app, agency)
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
    rows = _rows(client.get("/customers/export"))
    assert "Deceased" in rows[0]
    by_name = {r["Name"]: r for r in rows}
    assert by_name["Linda Bost"]["Deceased"] == "2026-04-30"
    assert by_name["Alive One"]["Deceased"] == ""


def test_the_provenance_line_counts_the_deceased(client, app, agency, db_session):
    """A file that leaves the building must say it contains people not to mail."""
    uid = _setup(app, agency)
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
    first = client.get("/customers/export").data.decode().splitlines()[0]
    assert "1 deceased" in first


def test_no_deceased_note_when_none_are_deceased(client, app, agency, db_session):
    from app.extensions import db
    from app.models import Customer, User
    with app.app_context():
        u = User(email="y@t.com", name="Y", is_admin=True, agency_id=agency.id)
        db.session.add(u); db.session.flush()
        db.session.add(Customer(agency_id=agency.id, first_name="Alive", last_name="One",
                                full_name="Alive One", mbi="1AA1AA1AA11"))
        db.session.commit()
        uid = u.id
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
    first = client.get("/customers/export").data.decode().splitlines()[0]
    assert "deceased" not in first.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_deceased_suppression.py -q`
Expected: FAIL — `KeyError: 'Deceased'`

- [ ] **Step 3: Add the column and the note**

In `app/customers.py`, append `"Deceased"` to the end of the `CUSTOMER_COLS` list, and in `_customer_cells` append the matching value:

```python
        c.deceased_date.isoformat() if c.deceased_date else "",
```

In `_filter_description`, add a `deceased` keyword argument and include it in the returned line when non-zero:

```python
    if deceased:
        parts.append(f"{deceased} deceased (suppress from mailings)")
```

and at the call site count them from the rows already gathered:

```python
    deceased = sum(1 for c in rows if c.deceased_date)
```

- [ ] **Step 4: Add the list badge**

In `app/templates/customers_list.html`, in the name cell:

```html
{% if c.deceased_date %}<span class="badge badge-deceased">Deceased</span>{% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_deceased_suppression.py -q`
Expected: PASS (3 tests)

Then `/usr/bin/python3 -m pytest -q` — expected PASS. Note `tests/test_customer_export.py` asserts on the export's columns; if it fails, its expectations need the new column added, not the feature changed.

- [ ] **Step 6: Commit**

```bash
git add app/customers.py app/templates/customers_list.html tests/test_deceased_suppression.py
git commit -m "feat(deceased): surface deceased in the customer list and export

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Backfill the 20 known deceased

**Files:**
- Create: `scripts/backfill_deceased.py`
- Test: `tests/test_backfill_deceased.py`

**Interfaces:**
- Consumes: `apply_death`, `death_date_from_uhc_fact` (Task 6)
- Produces: a dry-run-by-default script; `--apply` writes.

**Expected result: 20 customers** — 15 UHC (from the May and July commission statements; 18 distinct MBIs exist across all UHC files including the April/May per-agent books, 3 of which resolve to no customer) and 5 Humana (August BOB). Sources on disk:
- `docs/Commission DL/_organized/2026-05_cycle/raw/UHC/statement-2813549-20260501 (4).xlsx`
- `docs/Commission DL/_organized/2026-07_cycle/Founders_Commission_July_2026/statement-2813549-20260701 (1).xlsx`
- `docs/Carrier BOB DL/Aug 2026 period/Humana/Active Policies (1).xlsx`

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_backfill_deceased.py"""
from datetime import date


def test_an_mbi_matching_one_customer_is_marked(app, agency, db_session):
    from app.extensions import db
    from app.models import Customer
    from scripts.backfill_deceased import resolve_one
    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                     full_name="Linda Bost", mbi="6MV0WK0MP06")
        db.session.add(c); db.session.commit()
        got, why = resolve_one(agency.id, mbi="6MV0WK0MP06")
        assert got is not None and got.id == c.id and why == ""


def test_an_unmatched_id_marks_nobody(app, agency, db_session):
    from scripts.backfill_deceased import resolve_one
    with app.app_context():
        got, why = resolve_one(agency.id, mbi="NOSUCHMBI99")
        assert got is None and "no customer" in why


def test_an_ambiguous_id_marks_nobody(app, agency, db_session):
    """0 or >1 must refuse — marking the wrong person erases a living customer."""
    from app.extensions import db
    from app.models import Customer
    from scripts.backfill_deceased import resolve_one
    with app.app_context():
        for n in ("A", "B"):
            db.session.add(Customer(agency_id=agency.id, first_name=n, last_name="X",
                                    full_name=f"{n} X", mbi="DUP1DUP1DU1"))
        db.session.commit()
        got, why = resolve_one(agency.id, mbi="DUP1DUP1DU1")
        assert got is None and "2 customers" in why


def test_it_never_matches_on_a_name(app, agency, db_session):
    """No name or DOB fallback anywhere — an ID miss is a refusal, full stop."""
    from app.extensions import db
    from app.models import Customer
    from scripts.backfill_deceased import resolve_one
    with app.app_context():
        db.session.add(Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                                full_name="Linda Bost", mbi="OTHERMBI001"))
        db.session.commit()
        got, _ = resolve_one(agency.id, mbi="6MV0WK0MP06")
        assert got is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_backfill_deceased.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.backfill_deceased'`

- [ ] **Step 3: Write the script**

Create `scripts/backfill_deceased.py` with a module docstring explaining the sources and the 20 expected, plus:

```python
def resolve_one(agency_id, *, mbi=None, humana_id=None):
    """Return (customer, reason). EXACT unique-ID only — no name or DOB fallback.

    0 or >1 matches returns (None, reason): marking the wrong person deceased
    would erase a living customer from their agent's book, silently.
    """
    from app.models import Customer
    q = Customer.query.filter_by(agency_id=agency_id)
    if mbi:
        q = q.filter(Customer.mbi == mbi)
    elif humana_id:
        q = q.filter(Customer.humana_id == humana_id)
    else:
        return None, "no id supplied"
    rows = q.all()
    if len(rows) == 1:
        return rows[0], ""
    return None, ("no customer" if not rows else f"{len(rows)} customers share this id")
```

and a `main(apply)` that reads the three files, resolves each death row, calls `apply_death(...)` with the appropriate carrier, prints a per-row report plus refusals, and verifies payment and ledger totals are unchanged. Dry run unless `--apply`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_backfill_deceased.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Full suite + commit**

Run: `/usr/bin/python3 -m pytest -q` — expected PASS.

```bash
git add scripts/backfill_deceased.py tests/test_backfill_deceased.py
git commit -m "feat(deceased): backfill script for the 20 known deceased members

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Deploy and run (human-gated)**

```bash
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100
cd /var/www/founders-portal && git pull
export PGPASSWORD=$(grep DATABASE_URL .env | sed -E "s|.*://[^:]+:([^@]+)@.*|\1|")
pg_dump -U founders_user -h localhost founders_portal > /root/founders_pre_deceased_$(date +%Y%m%d_%H%M%S).sql
flask db upgrade                      # 042 -> 043
PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_deceased.py
# review the dry run — expect 20 marked, 3 refused (UHC MBIs with no customer)
PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_deceased.py --apply
systemctl restart founders-portal
```

Verify after: payment and ledger totals unchanged, `/auth/login` returns 200, and a re-run of the dry run reports 0 to mark (idempotent).

---

## Out of scope

- **Aetna `Term Reason Code`** — codes are unlabeled (`92`×79, `13`×41, `T014`×8, `8`×5, `T090`×1) with no description column; decoding needs AJ or Aetna.
- **BCBS / HealthSpring / Devoted** — no death signal in any file we receive.
- **Acting on `"Enrollment in Another Plan"`** — captured in Task 4, acted on by the separate carrier-switch work.
- **A review queue** for unmatched death rows and deceased customers still holding another carrier's active policy. The backfill prints both; a UI for them is a follow-up.

After this ships the portal knows about deaths for **UHC and Humana only** — roughly 85% of the book by member count. That is an improvement, not a guarantee, and should be described that way.
