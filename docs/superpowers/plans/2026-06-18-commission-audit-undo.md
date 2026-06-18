# Commission Audit Trail + Undo (Phase A, Plan 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every human action on a commission line item (resolve a quarantined row, edit its split) logged with who/when/before→after AND fully reversible, so a misclick is visible and undoable — the gap that lost AJ's work on 2026-06-17.

**Architecture:** A new append-only `CommissionLineItemRevision` table snapshots a line item's mutable money fields immediately BEFORE each change, plus records the new values and the acting user. `resolve_quarantine_line()` and a new `edit_line_split()` write a revision before mutating, and stop destroying the original (the pre-state lives in the revision). `undo_last_change()` restores a line (and its sibling override row) from the most recent un-undone revision. Each operation also calls the existing `log_event()` for agency-wide forensics. This is the trust foundation the rest of Phase A builds on.

**Tech Stack:** Python 3.10, Flask, Flask-SQLAlchemy, Flask-Migrate (Alembic), PostgreSQL 16 (prod) / SQLite (tests). Existing modules: `app/commission/ledger.py` (resolve logic), `app/commission/routes.py` (routes), `app/audit.py` (`log_event`), `app/models.py`.

## Global Constraints

- Every schema change requires an Alembic migration. NEVER `db.create_all()` in prod. Current migration head: **028**. This plan adds **029**.
- Every query MUST be agency-scoped: `.filter_by(agency_id=current_user.agency_id, ...)`. Missing agency_id = cross-tenant data leak.
- Commission editing/resolution is **ADMIN-only** (`current_user.is_admin` → else `abort(403)`).
- The ledger invariant is sacred: after ANY resolve/edit/undo, `agent_commission + founders_override == raw_amount` for the affected member rows, and `Σ raw_amount` for the statement is UNCHANGED. A change that alters Σ raw is a bug.
- Tests run locally: `python3 -m pytest -q`. Prove DB-mutating behavior against real shapes; the suite is SQLite — note any Postgres-only concern in the task.
- `log_event(action, *, category, detail=None, user=None, severity="info", ...)` is the ONLY writer of `AuditLog`; it is defensive (never raises into the caller).
- `split_breakdown(line)` derives `(agent_payout, founders_keep)`; never store them.

---

### Task 1: `CommissionLineItemRevision` model + migration 029

**Files:**
- Modify: `app/models.py` (add model after `CommissionLineItem`, ~line 808)
- Create: `migrations/versions/029_commission_line_item_revision.py`
- Test: `tests/test_commission_audit_undo.py`

**Interfaces:**
- Produces: `CommissionLineItemRevision` model with fields: `id`, `agency_id`, `line_item_id` (FK→commission_line_items.id, CASCADE), `statement_id`, `action` (str: `"resolve"|"edit"|"undo"`), `user_id` (FK→users.id), `before_json` (Text), `after_json` (Text), `sibling_source_ref` (str, nullable — the `::ovr` row this op created/changed), `undone` (Boolean default False), `created_at`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_commission_audit_undo.py
def test_revision_model_persists(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItemRevision
    with app.app_context():
        rev = CommissionLineItemRevision(
            agency_id=agency.id, line_item_id=1, statement_id=1,
            action="resolve", user_id=None,
            before_json='{"classification":"needs_manual_review"}',
            after_json='{"classification":"agent_commission"}',
            sibling_source_ref="uhc::0::5::ovr", undone=False)
        db.session.add(rev); db.session.commit()
        got = CommissionLineItemRevision.query.first()
        assert got.action == "resolve"
        assert got.undone is False
        assert got.sibling_source_ref == "uhc::0::5::ovr"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_audit_undo.py::test_revision_model_persists -v`
Expected: FAIL with `ImportError: cannot import name 'CommissionLineItemRevision'`

- [ ] **Step 3: Add the model**

In `app/models.py` immediately after the `CommissionLineItem` class (after its `__repr__`, ~line 808):

```python
class CommissionLineItemRevision(db.Model):
    """Append-only audit + undo record for a CommissionLineItem. One row per
    human change (resolve / edit / undo). before_json/after_json snapshot the
    line's mutable money fields so undo restores the EXACT prior state, and the
    full who/when/before->after history is always answerable. Never deleted."""
    __tablename__ = "commission_line_item_revisions"

    id            = db.Column(db.Integer, primary_key=True)
    agency_id     = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    line_item_id  = db.Column(db.Integer, db.ForeignKey("commission_line_items.id",
                              ondelete="CASCADE"), nullable=False, index=True)
    statement_id  = db.Column(db.Integer, db.ForeignKey("commission_statements.id",
                              ondelete="CASCADE"), nullable=False, index=True)
    action        = db.Column(db.String(16), nullable=False)   # resolve | edit | undo
    user_id       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    user          = db.relationship("User")
    before_json   = db.Column(db.Text)                          # mutable fields BEFORE the change
    after_json    = db.Column(db.Text)                          # mutable fields AFTER the change
    sibling_source_ref = db.Column(db.String(160))              # the ::ovr row this op created/changed, if any
    undone        = db.Column(db.Boolean, default=False, nullable=False)
    created_at    = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f"<CLIRevision {self.action} line={self.line_item_id} undone={self.undone}>"
```

- [ ] **Step 4: Create migration 029**

Create `migrations/versions/029_commission_line_item_revision.py`:

```python
"""commission_line_item_revisions table

Revision ID: 029
Revises: 028
"""
from alembic import op
import sqlalchemy as sa

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commission_line_item_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("line_item_id", sa.Integer(),
                  sa.ForeignKey("commission_line_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("statement_id", sa.Integer(),
                  sa.ForeignKey("commission_statements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("before_json", sa.Text()),
        sa.Column("after_json", sa.Text()),
        sa.Column("sibling_source_ref", sa.String(length=160)),
        sa.Column("undone", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_cli_rev_agency", "commission_line_item_revisions", ["agency_id"])
    op.create_index("ix_cli_rev_line", "commission_line_item_revisions", ["line_item_id"])
    op.create_index("ix_cli_rev_statement", "commission_line_item_revisions", ["statement_id"])


def downgrade():
    op.drop_index("ix_cli_rev_statement", table_name="commission_line_item_revisions")
    op.drop_index("ix_cli_rev_line", table_name="commission_line_item_revisions")
    op.drop_index("ix_cli_rev_agency", table_name="commission_line_item_revisions")
    op.drop_table("commission_line_item_revisions")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_audit_undo.py::test_revision_model_persists -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/models.py migrations/versions/029_commission_line_item_revision.py tests/test_commission_audit_undo.py
git commit -m "feat(commission): CommissionLineItemRevision model + migration 029 (audit/undo)"
```

---

### Task 2: Snapshot helper — capture a line's mutable state

**Files:**
- Modify: `app/commission/ledger.py` (add helper near `resolve_quarantine_line`, ~line 916)
- Test: `tests/test_commission_audit_undo.py`

**Interfaces:**
- Consumes: `CommissionLineItem` (the persisted model).
- Produces: `_snapshot_line(line) -> dict` returning the mutable money fields:
  `{"classification", "raw_amount", "split_rate", "agent_id", "payment_type"}`.

- [ ] **Step 1: Write the failing test**

```python
def test_snapshot_line_captures_mutable_fields(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItem
    from app.commission.ledger import _snapshot_line
    with app.app_context():
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::5", raw_amount=33.51, split_rate=None,
            classification="needs_manual_review", payment_type="New", agent_id=7)
        db.session.add(li); db.session.flush()
        snap = _snapshot_line(li)
        assert snap == {"classification": "needs_manual_review", "raw_amount": 33.51,
                        "split_rate": None, "agent_id": 7, "payment_type": "New"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_audit_undo.py::test_snapshot_line_captures_mutable_fields -v`
Expected: FAIL with `ImportError: cannot import name '_snapshot_line'`

- [ ] **Step 3: Add the helper**

In `app/commission/ledger.py`, immediately above `def resolve_quarantine_line` (~line 916):

```python
def _snapshot_line(line) -> dict:
    """The mutable money fields of a line item — the unit of undo. Captured
    before a resolve/edit so undo can restore the EXACT prior state."""
    return {
        "classification": line.classification,
        "raw_amount": line.raw_amount,
        "split_rate": line.split_rate,
        "agent_id": line.agent_id,
        "payment_type": line.payment_type,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_audit_undo.py::test_snapshot_line_captures_mutable_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/ledger.py tests/test_commission_audit_undo.py
git commit -m "feat(commission): _snapshot_line helper (undo unit)"
```

---

### Task 3: Record a revision when resolving — `resolve_quarantine_line` writes history

**Files:**
- Modify: `app/commission/ledger.py` (`resolve_quarantine_line`, ~line 916-961)
- Test: `tests/test_commission_audit_undo.py`

**Interfaces:**
- Consumes: `_snapshot_line` (Task 2), `CommissionLineItemRevision` (Task 1).
- Produces: `resolve_quarantine_line(line, agent_id, override_amount, split_rate, *, user_id=None)` — same behavior as before, PLUS writes ONE `CommissionLineItemRevision(action="resolve", before_json, after_json, sibling_source_ref)` capturing the pre-state. Still returns the override row (or None).

- [ ] **Step 1: Write the failing test**

```python
def test_resolve_writes_a_revision_with_before_state(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItem, CommissionLineItemRevision
    from app.commission.ledger import resolve_quarantine_line
    import json
    with app.app_context():
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::5", raw_amount=33.51, split_rate=None,
            classification="needs_manual_review", payment_type="New")
        db.session.add(li); db.session.flush()
        resolve_quarantine_line(li, agent_id=7, override_amount=4.59,
                                split_rate=0.55, user_id=3)
        db.session.commit()
        rev = CommissionLineItemRevision.query.filter_by(line_item_id=li.id).first()
        assert rev is not None
        assert rev.action == "resolve"
        assert rev.user_id == 3
        before = json.loads(rev.before_json)
        assert before["classification"] == "needs_manual_review"
        assert before["raw_amount"] == 33.51
        # the override sibling it created is recorded for undo
        assert rev.sibling_source_ref == "uhc::0::5::ovr"
        # invariant: agent remainder + override == original raw
        assert round(li.raw_amount + 4.59, 2) == 33.51
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_audit_undo.py::test_resolve_writes_a_revision_with_before_state -v`
Expected: FAIL (`resolve_quarantine_line() got an unexpected keyword argument 'user_id'` or no revision row)

- [ ] **Step 3: Modify `resolve_quarantine_line`**

Replace the signature line and add revision-writing. Current first line is:
`def resolve_quarantine_line(line, agent_id, override_amount, split_rate):`

Change to capture the before-state at the top and write a revision at the end:

```python
def resolve_quarantine_line(line, agent_id, override_amount, split_rate, *, user_id=None):
    """Resolve ONE quarantined (needs_manual_review) line item in place: split its
    lump amount into an agent_commission part (the remainder, which splits at
    `split_rate`) and a founders_override part (`override_amount`, 100% Founders).

    Records a CommissionLineItemRevision(action="resolve") snapshotting the
    pre-resolution state so the action is auditable + undoable. Faithful to the
    ledger invariant: the two new rows' raw_amounts sum back to the original
    raw_amount, so Σ raw is unchanged. Caller commits."""
    from app.models import CommissionLineItem, CommissionLineItemRevision
    import json
    before = _snapshot_line(line)
    raw = round(line.raw_amount or 0.0, 2)
    ov = round(override_amount or 0.0, 2)
    if abs(ov) > abs(raw):
        raise ValueError("override amount exceeds the line amount")

    commission_part = round(raw - ov, 2)
    line.classification = (CHARGEBACK if commission_part < 0 else AGENT_COMMISSION)
    line.agent_id = agent_id
    line.raw_amount = commission_part
    line.split_rate = split_rate
    line.payment_type = (line.payment_type or "")[:240] + " [resolved]"

    override_row = None
    ovr_ref = f"{line.source_ref}::ovr"
    existing_ovr = CommissionLineItem.query.filter_by(
        statement_id=line.statement_id, source_ref=ovr_ref).first()
    if abs(ov) >= 0.005:
        override_row = existing_ovr or CommissionLineItem(
            agency_id=line.agency_id, statement_id=line.statement_id,
            carrier=line.carrier, period_label=line.period_label,
            statement_date=line.statement_date, source_ref=ovr_ref,
            member_name=line.member_name, mbi=line.mbi,
            carrier_member_id=line.carrier_member_id)
        override_row.raw_amount = ov
        override_row.split_rate = None
        override_row.classification = FOUNDERS_OVERRIDE
        override_row.agent_id = None
        override_row.payment_type = "override [resolved]"
        if existing_ovr is None:
            db.session.add(override_row)
    elif existing_ovr is not None:
        db.session.delete(existing_ovr)

    db.session.add(CommissionLineItemRevision(
        agency_id=line.agency_id, line_item_id=line.id, statement_id=line.statement_id,
        action="resolve", user_id=user_id,
        before_json=json.dumps(before), after_json=json.dumps(_snapshot_line(line)),
        sibling_source_ref=(ovr_ref if abs(ov) >= 0.005 else None)))
    return override_row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_audit_undo.py::test_resolve_writes_a_revision_with_before_state -v`
Expected: PASS

- [ ] **Step 5: Run the existing ledger + uhc suites to confirm no regression**

Run: `python3 -m pytest tests/test_commission_ledger.py tests/test_uhc_pipeline.py -q`
Expected: PASS (existing callers pass no `user_id` — the new kwarg is optional)

- [ ] **Step 6: Commit**

```bash
git add app/commission/ledger.py tests/test_commission_audit_undo.py
git commit -m "feat(commission): resolve_quarantine_line records a revision (audit + undo seed)"
```

---

### Task 4: `undo_last_change` — restore a line from its latest revision

**Files:**
- Modify: `app/commission/ledger.py` (add after `resolve_quarantine_line`)
- Test: `tests/test_commission_audit_undo.py`

**Interfaces:**
- Consumes: `CommissionLineItemRevision` (Task 1), `_snapshot_line` (Task 2).
- Produces: `undo_last_change(line, *, user_id=None) -> bool` — finds the most recent
  un-undone revision for `line`, restores the line's mutable fields from its `before_json`,
  reverses the sibling `::ovr` row (delete if the resolve created it; the row had no override
  before), marks that revision `undone=True`, and writes a NEW `action="undo"` revision.
  Returns True if something was undone, False if no revision existed.

- [ ] **Step 1: Write the failing test**

```python
def test_undo_restores_exact_prior_state_and_removes_override(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItem
    from app.commission.ledger import resolve_quarantine_line, undo_last_change
    with app.app_context():
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::5", raw_amount=33.51, split_rate=None,
            classification="needs_manual_review", payment_type="New")
        db.session.add(li); db.session.flush()
        resolve_quarantine_line(li, agent_id=7, override_amount=4.59,
                                split_rate=0.55, user_id=3)
        db.session.commit()
        # sanity: it was resolved + an override sibling exists
        assert li.classification == "agent_commission"
        assert CommissionLineItem.query.filter_by(
            statement_id=1, source_ref="uhc::0::5::ovr").count() == 1

        ok = undo_last_change(li, user_id=3)
        db.session.commit()
        assert ok is True
        # line restored to EXACT prior state
        assert li.classification == "needs_manual_review"
        assert li.raw_amount == 33.51
        assert li.split_rate is None
        assert li.payment_type == "New"
        # the override sibling the resolve created is gone
        assert CommissionLineItem.query.filter_by(
            statement_id=1, source_ref="uhc::0::5::ovr").count() == 0


def test_undo_returns_false_when_nothing_to_undo(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItem
    from app.commission.ledger import undo_last_change
    with app.app_context():
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::9", raw_amount=10.0, split_rate=0.55,
            classification="agent_commission", payment_type="renewal")
        db.session.add(li); db.session.flush()
        assert undo_last_change(li, user_id=3) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_audit_undo.py -k undo -v`
Expected: FAIL with `ImportError: cannot import name 'undo_last_change'`

- [ ] **Step 3: Implement `undo_last_change`**

In `app/commission/ledger.py`, immediately after `resolve_quarantine_line`:

```python
def undo_last_change(line, *, user_id=None) -> bool:
    """Undo the most recent un-undone human change to `line`. Restores the line's
    mutable fields from that revision's before_json, reverses the sibling ::ovr
    row it created (delete if the override didn't exist before; restore if it did),
    marks the revision undone, and records an action="undo" revision. Returns True
    if a change was undone, False if there was nothing to undo. Caller commits."""
    from app.models import CommissionLineItem, CommissionLineItemRevision
    import json
    rev = (CommissionLineItemRevision.query
           .filter_by(line_item_id=line.id, undone=False)
           .filter(CommissionLineItemRevision.action != "undo")
           .order_by(CommissionLineItemRevision.id.desc())
           .first())
    if rev is None:
        return False

    before = json.loads(rev.before_json or "{}")
    after_undo_snapshot = _snapshot_line(line)   # for the undo revision's "before"
    # restore mutable fields
    for k, v in before.items():
        setattr(line, k, v)

    # reverse the sibling override row this revision created/changed
    if rev.sibling_source_ref:
        sib = CommissionLineItem.query.filter_by(
            statement_id=line.statement_id, source_ref=rev.sibling_source_ref).first()
        if sib is not None:
            # the resolve created this sibling (the row had no override before),
            # so undo removes it. (Edit-of-existing-override is handled by edit's
            # own revision pairing in Task 5.)
            db.session.delete(sib)

    rev.undone = True
    db.session.add(CommissionLineItemRevision(
        agency_id=line.agency_id, line_item_id=line.id, statement_id=line.statement_id,
        action="undo", user_id=user_id,
        before_json=json.dumps(after_undo_snapshot),
        after_json=json.dumps(_snapshot_line(line)),
        sibling_source_ref=rev.sibling_source_ref))
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_commission_audit_undo.py -k undo -v`
Expected: PASS (both)

- [ ] **Step 5: Commit**

```bash
git add app/commission/ledger.py tests/test_commission_audit_undo.py
git commit -m "feat(commission): undo_last_change restores a line from its latest revision"
```

---

### Task 5: `edit_line_split` — constrained per-row edit of agent/override (A5)

**Files:**
- Modify: `app/commission/ledger.py` (add after `undo_last_change`)
- Test: `tests/test_commission_audit_undo.py`

**Interfaces:**
- Consumes: `_snapshot_line` (Task 2), `CommissionLineItemRevision` (Task 1), `split_breakdown`.
- Produces: `edit_line_split(line, *, agent_amount, override_amount, agent_id, user_id=None)` —
  sets the line to `agent_amount` (classification agent_commission/chargeback by sign) and its
  `::ovr` sibling to `override_amount`, REQUIRING `round(agent_amount + override_amount, 2) ==
  round(original_combined, 2)` where original_combined is the line's current raw plus any
  existing sibling override. Raises `ValueError` if the two don't sum to the original combined
  (the invariant can never be broken by an edit). Records an `action="edit"` revision.

- [ ] **Step 1: Write the failing test**

```python
def test_edit_line_split_enforces_sum_invariant(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItem, CommissionLineItemRevision
    from app.commission.ledger import edit_line_split
    with app.app_context():
        # a row currently all agent_commission ($33.51), no override sibling
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::5", raw_amount=33.51, split_rate=0.55,
            classification="agent_commission", payment_type="renewal", agent_id=7)
        db.session.add(li); db.session.flush()

        # correct the split to 28.92 agent + 4.59 override (sums to 33.51)
        edit_line_split(li, agent_amount=28.92, override_amount=4.59,
                        agent_id=7, user_id=3)
        db.session.commit()
        assert li.raw_amount == 28.92
        ovr = CommissionLineItem.query.filter_by(
            statement_id=1, source_ref="uhc::0::5::ovr").first()
        assert ovr is not None and ovr.raw_amount == 4.59
        assert ovr.classification == "founders_override"
        rev = CommissionLineItemRevision.query.filter_by(
            line_item_id=li.id, action="edit").first()
        assert rev is not None

        # an edit that BREAKS the sum is rejected
        import pytest
        with pytest.raises(ValueError):
            edit_line_split(li, agent_amount=20.00, override_amount=4.59,
                            agent_id=7, user_id=3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_audit_undo.py::test_edit_line_split_enforces_sum_invariant -v`
Expected: FAIL with `ImportError: cannot import name 'edit_line_split'`

- [ ] **Step 3: Implement `edit_line_split`**

In `app/commission/ledger.py`, after `undo_last_change`:

```python
def edit_line_split(line, *, agent_amount, override_amount, agent_id, user_id=None):
    """Correct a line's agent-commission / founders-override split in place. The
    two amounts MUST sum to the line's current combined total (its raw plus any
    existing ::ovr sibling) — an edit can never change Σ raw or break the
    agent+override==combined invariant. Records an action="edit" revision. Caller
    commits. Raises ValueError if the amounts don't sum to the original combined."""
    from app.models import CommissionLineItem, CommissionLineItemRevision
    import json
    ovr_ref = f"{line.source_ref}::ovr"
    existing_ovr = CommissionLineItem.query.filter_by(
        statement_id=line.statement_id, source_ref=ovr_ref).first()
    original_combined = round((line.raw_amount or 0.0) +
                              (existing_ovr.raw_amount if existing_ovr else 0.0), 2)
    agent_amount = round(agent_amount or 0.0, 2)
    override_amount = round(override_amount or 0.0, 2)
    if round(agent_amount + override_amount, 2) != original_combined:
        raise ValueError(
            f"agent ${agent_amount} + override ${override_amount} must equal "
            f"the line total ${original_combined}")

    before = _snapshot_line(line)
    line.classification = (CHARGEBACK if agent_amount < 0 else AGENT_COMMISSION)
    line.raw_amount = agent_amount
    line.agent_id = agent_id
    if line.split_rate is None:
        line.split_rate = 0.55   # keep a split rate so the agent share derives

    if abs(override_amount) >= 0.005:
        ovr = existing_ovr or CommissionLineItem(
            agency_id=line.agency_id, statement_id=line.statement_id,
            carrier=line.carrier, period_label=line.period_label,
            statement_date=line.statement_date, source_ref=ovr_ref,
            member_name=line.member_name, mbi=line.mbi,
            carrier_member_id=line.carrier_member_id)
        ovr.raw_amount = override_amount
        ovr.split_rate = None
        ovr.classification = FOUNDERS_OVERRIDE
        ovr.agent_id = None
        ovr.payment_type = "override [edited]"
        if existing_ovr is None:
            db.session.add(ovr)
    elif existing_ovr is not None:
        db.session.delete(existing_ovr)

    db.session.add(CommissionLineItemRevision(
        agency_id=line.agency_id, line_item_id=line.id, statement_id=line.statement_id,
        action="edit", user_id=user_id,
        before_json=json.dumps(before), after_json=json.dumps(_snapshot_line(line)),
        sibling_source_ref=(ovr_ref if abs(override_amount) >= 0.005 else None)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_audit_undo.py::test_edit_line_split_enforces_sum_invariant -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/ledger.py tests/test_commission_audit_undo.py
git commit -m "feat(commission): edit_line_split — constrained agent/override edit (invariant-safe)"
```

---

### Task 6: Wire the resolve route to pass user_id + log_event + show success

**Files:**
- Modify: `app/commission/routes.py` (`commission_quarantine_resolve`, ~line 1235-1278)
- Test: `tests/test_uhc_pipeline.py` (extend the existing endpoint test)

**Interfaces:**
- Consumes: `resolve_quarantine_line(..., user_id=)` (Task 3), `log_event` (`app/audit.py`).
- Produces: the route passes `user_id=current_user.id` and calls
  `log_event("commission_resolve", category="commission", detail=..., severity="info")`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_uhc_pipeline.py`:

```python
def test_resolve_endpoint_records_revision(db_session, app, client, agency):
    """The resolve endpoint must persist a revision (audit + undo) for the action."""
    from app.extensions import db
    from app.models import (CommissionStatement, CommissionLineItem, User,
                            CommissionLineItemRevision, AgentCarrierContract)
    from datetime import date
    with app.app_context():
        admin = User(email="admin@test.com", name="Admin", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        stmt = CommissionStatement(agency_id=agency.id, carrier="UHC",
                                   statement_date=date(2026, 6, 1), period_label="June 2026")
        db.session.add(stmt); db.session.flush()
        li = CommissionLineItem(agency_id=agency.id, statement_id=stmt.id, carrier="UHC",
                                source_ref="uhc::0::5", raw_amount=33.51, split_rate=None,
                                classification="needs_manual_review", payment_type="New")
        db.session.add(li); db.session.commit()
        line_id, sid, aid = li.id, stmt.id, admin.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(aid)
    resp = client.post(f"/admin/commissions/line/{line_id}/resolve",
                       data={"agent_id": str(aid), "override_amount": "4.59"},
                       follow_redirects=False)
    assert resp.status_code in (302, 303)
    with app.app_context():
        assert CommissionLineItemRevision.query.filter_by(
            line_item_id=line_id, action="resolve").count() == 1
```

(If the existing route path differs, use the real path from `routes.py`; this test
documents the contract.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_uhc_pipeline.py::test_resolve_endpoint_records_revision -v`
Expected: FAIL (no revision row — route doesn't pass user_id yet, OR path mismatch)

- [ ] **Step 3: Update the route**

In `app/commission/routes.py`, in `commission_quarantine_resolve`, change the resolve call
and add a `log_event`. The current call is:
`resolve_quarantine_line(li, agent.id, override_amount, split_rate)`
Replace that line and its `db.session.commit()` block with:

```python
    try:
        resolve_quarantine_line(li, agent.id, override_amount, split_rate,
                                user_id=current_user.id)
        db.session.commit()
    except ValueError as e:
        db.session.rollback()
        flash(f"Could not resolve: {e}", "error")
        return redirect(back)
    from app.audit import log_event
    log_event("commission_resolve", category="commission",
              detail=f"{li.carrier} {li.member_name or 'line'} -> agent {agent.id} "
                     f"override ${override_amount:.2f}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_uhc_pipeline.py::test_resolve_endpoint_records_revision -v`
Expected: PASS

- [ ] **Step 5: Run the full commission suite**

Run: `python3 -m pytest tests/test_uhc_pipeline.py tests/test_commission_ledger.py tests/test_commission_audit_undo.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/commission/routes.py tests/test_uhc_pipeline.py
git commit -m "feat(commission): resolve route passes user_id + logs the action"
```

---

### Task 7: Undo + edit routes (admin-only)

**Files:**
- Modify: `app/commission/routes.py` (add two routes near `commission_quarantine_resolve`)
- Test: `tests/test_uhc_pipeline.py`

**Interfaces:**
- Consumes: `undo_last_change` (Task 4), `edit_line_split` (Task 5), `log_event`.
- Produces: `POST /admin/commissions/line/<int:line_id>/undo` and
  `POST /admin/commissions/line/<int:line_id>/edit` (admin-only, agency-scoped, flash + redirect back).

- [ ] **Step 1: Write the failing test**

```python
def test_undo_endpoint_reverts_a_resolve(db_session, app, client, agency):
    from app.extensions import db
    from app.models import CommissionStatement, CommissionLineItem, User
    from app.commission.ledger import resolve_quarantine_line
    from datetime import date
    with app.app_context():
        admin = User(email="admin2@test.com", name="Admin2", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        stmt = CommissionStatement(agency_id=agency.id, carrier="UHC",
                                   statement_date=date(2026, 6, 1), period_label="June 2026")
        db.session.add(stmt); db.session.flush()
        li = CommissionLineItem(agency_id=agency.id, statement_id=stmt.id, carrier="UHC",
                                source_ref="uhc::0::5", raw_amount=33.51, split_rate=None,
                                classification="needs_manual_review", payment_type="New")
        db.session.add(li); db.session.flush()
        resolve_quarantine_line(li, agent_id=admin.id, override_amount=4.59,
                                split_rate=0.55, user_id=admin.id)
        db.session.commit()
        line_id, aid = li.id, admin.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(aid)
    resp = client.post(f"/admin/commissions/line/{line_id}/undo", follow_redirects=False)
    assert resp.status_code in (302, 303)
    with app.app_context():
        from app.models import CommissionLineItem
        li2 = CommissionLineItem.query.get(line_id)
        assert li2.classification == "needs_manual_review"   # back to quarantine
        assert li2.raw_amount == 33.51
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_uhc_pipeline.py::test_undo_endpoint_reverts_a_resolve -v`
Expected: FAIL (404 — route doesn't exist)

- [ ] **Step 3: Add the routes**

In `app/commission/routes.py`, after `commission_quarantine_resolve`:

```python
@commission_bp.route("/admin/commissions/line/<int:line_id>/undo", methods=["POST"])
@login_required
def commission_line_undo(line_id):
    """Undo the most recent human change to a commission line (admin-only)."""
    if not current_user.is_admin:
        abort(403)
    from app.commission.ledger import undo_last_change
    from app.audit import log_event
    li = CommissionLineItem.query.filter_by(
        id=line_id, agency_id=current_user.agency_id).first_or_404()
    back = request.referrer or url_for("commission.commission_quarantine",
                                       stmt_id=li.statement_id)
    if undo_last_change(li, user_id=current_user.id):
        db.session.commit()
        log_event("commission_undo", category="commission",
                  detail=f"{li.carrier} {li.member_name or 'line'} #{li.id}")
        flash("Change undone.", "success")
    else:
        flash("Nothing to undo on that line.", "warning")
    return redirect(back)


@commission_bp.route("/admin/commissions/line/<int:line_id>/edit", methods=["POST"])
@login_required
def commission_line_edit(line_id):
    """Correct a line's agent/override split (admin-only, invariant-safe)."""
    if not current_user.is_admin:
        abort(403)
    from app.commission.ledger import edit_line_split
    from app.audit import log_event
    li = CommissionLineItem.query.filter_by(
        id=line_id, agency_id=current_user.agency_id).first_or_404()
    back = request.referrer or url_for("commission.commission_quarantine",
                                       stmt_id=li.statement_id)
    agent = User.query.filter_by(id=request.form.get("agent_id", type=int),
                                 agency_id=current_user.agency_id).first()
    try:
        agent_amount = float(request.form.get("agent_amount") or 0)
        override_amount = float(request.form.get("override_amount") or 0)
    except ValueError:
        flash("Enter valid amounts.", "error")
        return redirect(back)
    try:
        edit_line_split(li, agent_amount=agent_amount, override_amount=override_amount,
                        agent_id=(agent.id if agent else li.agent_id),
                        user_id=current_user.id)
        db.session.commit()
    except ValueError as e:
        db.session.rollback()
        flash(f"Could not edit: {e}", "error")
        return redirect(back)
    log_event("commission_edit", category="commission",
              detail=f"{li.carrier} {li.member_name or 'line'} #{li.id} "
                     f"-> agent ${agent_amount:.2f} / override ${override_amount:.2f}")
    flash("Split updated.", "success")
    return redirect(back)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_uhc_pipeline.py::test_undo_endpoint_reverts_a_resolve -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add app/commission/routes.py tests/test_uhc_pipeline.py
git commit -m "feat(commission): undo + edit routes (admin-only, logged)"
```

---

### Task 8: Surface the history + Undo/Edit controls in the quarantine UI

**Files:**
- Modify: `app/commission/recap.py` (add `line_revisions(line_id, agency_id)` helper)
- Modify: the quarantine template (find via `grep -rl quarantine app/templates/`)
- Test: `tests/test_uhc_pipeline.py`

**Interfaces:**
- Consumes: `CommissionLineItemRevision` (Task 1).
- Produces: `line_revisions(line_id, agency_id) -> list[CommissionLineItemRevision]` (newest first, agency-scoped); the quarantine/resolved rows render their history ("resolved by AJ 6/17: $28.92 + $4.59 [undo]") and an Undo button posting to the Task-7 route.

- [ ] **Step 1: Write the failing test**

```python
def test_line_revisions_returns_history_newest_first(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItem
    from app.commission.ledger import resolve_quarantine_line, undo_last_change
    from app.commission.recap import line_revisions
    with app.app_context():
        li = CommissionLineItem(agency_id=agency.id, statement_id=1, carrier="UHC",
                                source_ref="uhc::0::5", raw_amount=33.51, split_rate=None,
                                classification="needs_manual_review", payment_type="New")
        db.session.add(li); db.session.flush()
        resolve_quarantine_line(li, agent_id=7, override_amount=4.59, split_rate=0.55, user_id=3)
        db.session.flush()
        undo_last_change(li, user_id=3)
        db.session.commit()
        revs = line_revisions(li.id, agency.id)
        assert [r.action for r in revs] == ["undo", "resolve"]   # newest first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_uhc_pipeline.py::test_line_revisions_returns_history_newest_first -v`
Expected: FAIL with `ImportError: cannot import name 'line_revisions'`

- [ ] **Step 3: Add the helper**

In `app/commission/recap.py` (anywhere at module level):

```python
def line_revisions(line_id, agency_id):
    """Revision history for one commission line, newest first, agency-scoped.
    Drives the 'who changed this, when, before->after' display + Undo control."""
    from app.models import CommissionLineItemRevision
    return (CommissionLineItemRevision.query
            .filter_by(line_item_id=line_id, agency_id=agency_id)
            .order_by(CommissionLineItemRevision.id.desc())
            .all())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_uhc_pipeline.py::test_line_revisions_returns_history_newest_first -v`
Expected: PASS

- [ ] **Step 5: Add Undo control + history line to the quarantine template**

Find the template: `grep -rln "quarantine" app/templates/`. In the row-rendering loop for
resolved/quarantine lines, add (adapt variable names to the template's context):

```html
{% if line.classification != 'needs_manual_review' %}
  <form method="post" action="{{ url_for('commission.commission_line_undo', line_id=line.id) }}"
        style="display:inline">
    <button type="submit" class="btn btn-secondary btn-sm"
            onclick="return confirm('Undo this change?')">↶ Undo</button>
  </form>
{% endif %}
```

The route view must pass the revisions into the template context where it renders the line
list (use `line_revisions(line.id, current_user.agency_id)`); render the newest as
"{{ rev.action }} by {{ rev.user.name if rev.user else 'system' }} {{ rev.created_at.strftime('%-m/%-d') }}".

- [ ] **Step 6: Manually verify the page renders (no server error)**

Run: `python3 -m pytest tests/test_uhc_pipeline.py -k "quarantine_page or review_page" -q`
Expected: PASS (the existing render tests still pass with the new control)

- [ ] **Step 7: Commit**

```bash
git add app/commission/recap.py app/templates/ tests/test_uhc_pipeline.py
git commit -m "feat(commission): line revision history + Undo control in quarantine UI"
```

---

### Task 9: Deploy migration 029 + verify on real Postgres

**Files:** none (deployment task)

**Interfaces:** Consumes the whole plan.

- [ ] **Step 1: Full suite green locally**

Run: `python3 -m pytest -q`
Expected: PASS (all)

- [ ] **Step 2: Back up the VPS DB, then deploy**

```bash
ssh -i /home/timothywinslowlinux/.ssh/id_ed25519 root@23.187.248.100 \
  'cd /var/www/founders-portal && PGPASSWORD=$(grep DATABASE_URL .env | sed -E "s#.*://[^:]+:([^@]+)@.*#\1#") pg_dump -U founders_user -h localhost founders_portal > /root/founders_portal_pre_029_$(date +%Y%m%d_%H%M%S).sql && git pull && ./venv/bin/pip install -r requirements.txt && flask db upgrade && systemctl restart founders-portal && systemctl is-active founders-portal'
```

Expected: `active`, and `flask db upgrade` reports `028 -> 029`.

- [ ] **Step 3: Verify the table + a real resolve→undo round-trip on Postgres**

Write a throwaway script that, against the live DB, resolves a real quarantined June UHC
line, asserts a revision row exists, undoes it, asserts the line is back to
`needs_manual_review` and the `::ovr` sibling is gone, then leaves the line in its original
quarantined state. Run via `PYTHONPATH=/var/www/founders-portal ./venv/bin/python3`.
Expected: round-trip succeeds; line restored exactly; no orphan override row.

- [ ] **Step 4: Update BACKLOG + START HERE + handoff per the Session Protocol**

Mark Plan 1 (audit+undo) shipped; note Plans 2–4 of Phase A remain. Bump dates.

- [ ] **Step 5: Commit the docs**

```bash
git add BACKLOG.md CLAUDE.md
git commit -m "docs: commission audit+undo (Phase A Plan 1) shipped + deployed"
```

---

## Self-Review

**Spec coverage (Plan 1 scope = A4 + A5 + the resolve rewrite):**
- A4 (audit trail + undo): Tasks 1, 3, 4, 6, 7, 8 ✓
- A5 (constrained per-row edit, invariant-safe): Tasks 5, 7 ✓
- Resolve rewrite (stop destroying the original): Task 3 ✓ (before-state preserved in revision)
- Admin-only (spec A7/§8): Tasks 6, 7 gate on `current_user.is_admin` ✓
- Agency-scoped: all routes filter by `agency_id` ✓
- Invariant (agent+override==raw, Σraw unchanged): Tasks 3, 5 assert it ✓
- A2/A3/A6/A8/A9 are explicitly OTHER plans (2–4) — not in this plan. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code. Task 8's template edit names a `grep` to locate the exact file (the template path isn't knowable until run) but gives the exact HTML to insert — acceptable, not a placeholder.

**Type consistency:** `resolve_quarantine_line(..., user_id=)`, `undo_last_change(line, *, user_id=)`, `edit_line_split(line, *, agent_amount, override_amount, agent_id, user_id=)`, `_snapshot_line(line)->dict`, `line_revisions(line_id, agency_id)->list`, `CommissionLineItemRevision` fields — all consistent across tasks. Routes `/admin/commissions/line/<id>/{resolve,undo,edit}` consistent.

**Note for executor:** Task 6's test assumes the resolve route path `/admin/commissions/line/<id>/resolve`. The CURRENT route is `commission_quarantine_resolve` at a different path (`commission/routes.py:1235`). Confirm the real path from `routes.py` and either keep the existing path (update the test) or standardize on `/admin/commissions/line/<id>/resolve` (update the route + its template form action). Standardizing is cleaner (all three line ops share the `/line/<id>/<op>` shape) but verify no template references break.
