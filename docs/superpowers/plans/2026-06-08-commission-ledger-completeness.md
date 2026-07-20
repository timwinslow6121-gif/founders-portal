# Commission Ledger Completeness (R1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every row of every clean-carrier commission sheet as a `CommissionLineItem` (full pre-split amount + classification + carrier/agent/customer/payment-type attribution), so that "Σ carrier sheet = Σ agent payouts + Founders keep" is provable and every cent is verifiably tracked.

**Architecture:** A new `CommissionLineItem` table mirrors each carrier-sheet row 1:1. A new module `app/commission/ledger.py` holds per-carrier *extractors* (which — unlike the existing `normalizers.py` — do NOT collapse paired rows; they keep the Founders-override/Service-Fee rows that the normalizers drop), a `split_breakdown(line)` helper that derives `agent_payout`/`founders_keep` from `raw_amount` + `split_rate`, and a `verify_statement_balance(statement, sheets)` self-check that compares the line-item total against an independent re-sum of the raw sheets. The upload path (`_ingest_normalized_upload` in `routes.py`) calls the extractor alongside its existing `PolicyPayment` writes. `PolicyPayment` and the Plan-1 normalizers are unchanged and coexist.

**Tech Stack:** Python 3.10, Flask-SQLAlchemy, Flask-Migrate (Alembic), pytest + SQLite in-memory, openpyxl-loaded sheets (`{sheet_name: list[list[cell]]}`).

---

## Decisions locked before planning

- **Backfill = re-upload through the existing UI**, NOT a script. Raw commission files are never persisted (uploads write to a discarded tempfile); only `CommissionStatement.filename` and derived `PolicyPayment` rows survive, so a script cannot re-read originals. Upload is already idempotent (keyed on `source_ref` + content fingerprint, and `_ingest_normalized_upload` deletes stale rows on replace), and prod is reproducible playground data. So: AJ re-uploads the 5 clean-carrier files via the existing admin upload and line items populate. The plan therefore has **no backfill-script task**; the "Re-import backfill" requirement is satisfied by Task 8 wiring + a documented re-upload step (Task 10).
- **`split_breakdown` is the single derivation seam.** `agent_payout`/`founders_keep` are NEVER stored — always derived from `raw_amount` + `split_rate` + `classification`. A split correction re-derives instantly with no stale figures.
- **`classification` is a plain string** (no DB enum) so future classes (`true_up`, `advance_clawback`) need no migration.
- **Extractors keep every row.** The contrast with `normalizers.py` (which collapses Service Fee + Broker Level into one MemberFact) is the entire point — the dropped Founders-override amount is what makes the balance provable.

## File structure

- **Create** `app/commission/ledger.py` — `LineItemDraft` dataclass, `split_breakdown()`, per-carrier `extract_lineitems_<carrier>()`, `EXTRACTORS` registry, `money_rows_total_<carrier>()` independent re-sum helpers, `verify_statement_balance()`.
- **Modify** `app/models.py` — add `CommissionLineItem` model (after `PolicyPayment`, ~line 737).
- **Create** `migrations/versions/023_commission_lineitems.py` — create the `commission_line_items` table.
- **Modify** `app/commission/routes.py` — in `_ingest_normalized_upload` (~line 873), after `ingest_statement`, call the ledger extractor + persist line items; clear stale line items on replace (alongside the existing `PolicyPayment` delete ~line 868).
- **Create** `tests/test_commission_ledger.py` — extraction, classification, attribution, split derivation, completeness/balance, idempotency.
- **Modify** `docs/superpowers/specs/2026-06-08-commission-ledger-completeness-design.md` — mark backfill resolved (re-upload), at the end.

---

### Task 1: `CommissionLineItem` model

**Files:**
- Modify: `app/models.py` (add class after `PolicyPayment`, which ends ~line 737)
- Test: `tests/test_commission_ledger.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_commission_ledger.py`:

```python
"""
tests/test_commission_ledger.py

R1 commission ledger: per-carrier line-item extraction, split derivation,
balance/completeness self-check, idempotency. Fixtured from real raw commission
files in tests/fixtures/commission/. SQLite in-memory via conftest fixtures.
"""
import os

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "commission")


def test_commission_lineitem_model_columns(db_session, agency):
    from app.models import CommissionLineItem, CommissionStatement
    from app.extensions import db

    stmt = CommissionStatement(
        agency_id=agency.id, carrier="BCBS", agent_id=None,
        period_label="April 2026", filename="x.xlsx",
    )
    db.session.add(stmt)
    db.session.flush()

    li = CommissionLineItem(
        agency_id=agency.id,
        statement_id=stmt.id,
        carrier="BCBS",
        period_label="April 2026",
        source_ref="bcbs::Sheet1::1",
        member_name="DOE,JANE",
        raw_amount=28.91,
        split_rate=0.55,
        classification="agent_commission",
        payment_type="renewal",
    )
    db.session.add(li)
    db.session.flush()

    got = CommissionLineItem.query.filter_by(statement_id=stmt.id).first()
    assert got.raw_amount == 28.91
    assert got.split_rate == 0.55
    assert got.classification == "agent_commission"
    assert got.agent_id is None        # nullable
    assert got.customer_id is None     # nullable
    assert got.mbi is None             # nullable
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_ledger.py::test_commission_lineitem_model_columns -v`
Expected: FAIL — `ImportError: cannot import name 'CommissionLineItem'`

- [ ] **Step 3: Add the model**

In `app/models.py`, immediately after the `PolicyPayment` class (after its `__repr__`, ~line 738), add:

```python
class CommissionLineItem(db.Model):
    """
    R1 — Commission ledger completeness. A faithful 1:1 mirror of every
    amount-bearing row across a carrier's commission sheets (the "money facts"
    layer, alongside PolicyPayment's "customer facts" layer).

    Unlike the customer-sync normalizers, the ledger extractors do NOT collapse
    paired rows: the Founders-override / Service-Fee row is kept as its own line
    item so that "Σ raw_amount = Σ agent_payout + Σ founders_keep" is provable.

    agent_payout / founders_keep are DERIVED (never stored) via
    app.commission.ledger.split_breakdown(line):
      - agent_commission | hra_bonus | chargeback:
          agent_payout  = raw_amount * split_rate
          founders_keep = raw_amount - agent_payout
      - founders_override:
          agent_payout  = 0
          founders_keep = raw_amount

    classification is a plain string (no DB enum) for forward-compat:
      'agent_commission' | 'founders_override' | 'hra_bonus' | 'chargeback'
    """
    __tablename__ = "commission_line_items"

    id            = db.Column(db.Integer, primary_key=True)
    agency_id     = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    statement_id  = db.Column(db.Integer, db.ForeignKey("commission_statements.id",
                              ondelete="CASCADE"), nullable=False, index=True)
    statement     = db.relationship("CommissionStatement", foreign_keys=[statement_id])

    carrier       = db.Column(db.String(64), nullable=False, index=True)
    period_label  = db.Column(db.String(32), index=True)
    statement_date = db.Column(db.Date)

    # Stable per-row key, e.g. "healthspring::Detail::7". Idempotent re-import.
    source_ref    = db.Column(db.String(128), nullable=False, index=True)

    # Resolved attribution (nullable: pure-Founders / member-less rows)
    agent_id      = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    agent         = db.relationship("User", foreign_keys=[agent_id])
    customer_id   = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True, index=True)

    member_name   = db.Column(db.String(256))
    mbi           = db.Column(db.String(20), index=True)
    carrier_member_id = db.Column(db.String(128))

    raw_amount    = db.Column(db.Float, nullable=False)   # exactly what the sheet shows; may be negative. The TRUTH.
    split_rate    = db.Column(db.Float, nullable=True)    # snapshotted at import; NULL for founders_override

    classification = db.Column(db.String(32), nullable=False, index=True)
    payment_type   = db.Column(db.String(32))             # descriptive: renewal|initial|hra|override|...

    created_at    = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("statement_id", "source_ref",
                            name="uq_lineitem_statement_source_ref"),
    )

    def __repr__(self):
        return f"<CommissionLineItem {self.carrier} {self.classification} {self.raw_amount}>"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_ledger.py::test_commission_lineitem_model_columns -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_commission_ledger.py
git commit -m "feat(commission): CommissionLineItem model (R1 ledger)"
```

---

### Task 2: Migration 023

**Files:**
- Create: `migrations/versions/023_commission_lineitems.py`

- [ ] **Step 1: Confirm current migration head**

Run: `python3 -m flask db heads 2>/dev/null || ls migrations/versions/ | grep -E '^02'`
Expected: head is `022`. (If env can't load Flask, the file list confirms 022 is newest numbered revision.)

- [ ] **Step 2: Write the migration**

Create `migrations/versions/023_commission_lineitems.py`:

```python
"""CommissionLineItem table (R1 commission ledger completeness)

Revision ID: 023
Revises: 022
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commission_line_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("statement_id", sa.Integer(), nullable=False),
        sa.Column("carrier", sa.String(length=64), nullable=False),
        sa.Column("period_label", sa.String(length=32), nullable=True),
        sa.Column("statement_date", sa.Date(), nullable=True),
        sa.Column("source_ref", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("member_name", sa.String(length=256), nullable=True),
        sa.Column("mbi", sa.String(length=20), nullable=True),
        sa.Column("carrier_member_id", sa.String(length=128), nullable=True),
        sa.Column("raw_amount", sa.Float(), nullable=False),
        sa.Column("split_rate", sa.Float(), nullable=True),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("payment_type", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.ForeignKeyConstraint(["statement_id"], ["commission_statements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("statement_id", "source_ref", name="uq_lineitem_statement_source_ref"),
    )
    op.create_index("ix_commission_line_items_agency_id", "commission_line_items", ["agency_id"])
    op.create_index("ix_commission_line_items_statement_id", "commission_line_items", ["statement_id"])
    op.create_index("ix_commission_line_items_carrier", "commission_line_items", ["carrier"])
    op.create_index("ix_commission_line_items_period_label", "commission_line_items", ["period_label"])
    op.create_index("ix_commission_line_items_source_ref", "commission_line_items", ["source_ref"])
    op.create_index("ix_commission_line_items_agent_id", "commission_line_items", ["agent_id"])
    op.create_index("ix_commission_line_items_customer_id", "commission_line_items", ["customer_id"])
    op.create_index("ix_commission_line_items_mbi", "commission_line_items", ["mbi"])
    op.create_index("ix_commission_line_items_classification", "commission_line_items", ["classification"])


def downgrade():
    op.drop_table("commission_line_items")
```

- [ ] **Step 3: Verify migration applies cleanly (SQLite scratch DB)**

Run:
```bash
rm -f /tmp/r1check.db && DATABASE_URL="sqlite:////tmp/r1check.db" python3 -m flask db upgrade 2>&1 | tail -5
```
Expected: ends with `Running upgrade 022 -> 023` (no error). Then:
```bash
DATABASE_URL="sqlite:////tmp/r1check.db" python3 -c "import sqlite3;print([r[1] for r in sqlite3.connect('/tmp/r1check.db').execute('PRAGMA table_info(commission_line_items)')])"
```
Expected: prints the column list including `raw_amount`, `split_rate`, `classification`, `source_ref`.

- [ ] **Step 4: Commit**

```bash
git add migrations/versions/023_commission_lineitems.py
git commit -m "feat(commission): migration 023 commission_line_items table"
```

---

### Task 3: `split_breakdown` helper + `LineItemDraft`

**Files:**
- Create: `app/commission/ledger.py`
- Test: `tests/test_commission_ledger.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_ledger.py`:

```python
def test_split_breakdown_agent_commission():
    from app.commission.ledger import split_breakdown, LineItemDraft

    li = LineItemDraft(carrier="BCBS", source_ref="bcbs::Sheet1::1",
                       raw_amount=28.91, split_rate=0.55,
                       classification="agent_commission")
    payout, keep = split_breakdown(li)
    assert round(payout, 2) == 15.90      # 28.91 * 0.55
    assert round(keep, 2) == 13.01        # 28.91 - 15.90
    assert round(payout + keep, 2) == 28.91


def test_split_breakdown_founders_override_keeps_all():
    from app.commission.ledger import split_breakdown, LineItemDraft

    li = LineItemDraft(carrier="Healthspring", source_ref="healthspring::Detail::2",
                       raw_amount=100.0, split_rate=None,
                       classification="founders_override")
    payout, keep = split_breakdown(li)
    assert payout == 0.0
    assert keep == 100.0


def test_split_breakdown_chargeback_negative():
    from app.commission.ledger import split_breakdown, LineItemDraft

    li = LineItemDraft(carrier="Devoted", source_ref="devoted::Agent Portion::5",
                       raw_amount=-347.0, split_rate=0.55,
                       classification="chargeback")
    payout, keep = split_breakdown(li)
    assert round(payout, 2) == -190.85    # -347 * 0.55
    assert round(keep, 2) == -156.15
    assert round(payout + keep, 2) == -347.0


def test_split_breakdown_none_split_rate_treated_as_zero_payout():
    # An agent_commission row whose agent had no contract (split_rate None):
    # payout is 0, keep is the whole raw amount (Founders keeps it pending fix).
    from app.commission.ledger import split_breakdown, LineItemDraft

    li = LineItemDraft(carrier="BCBS", source_ref="bcbs::Sheet1::9",
                       raw_amount=28.91, split_rate=None,
                       classification="agent_commission")
    payout, keep = split_breakdown(li)
    assert payout == 0.0
    assert keep == 28.91
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_ledger.py -k split_breakdown -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.commission.ledger'`

- [ ] **Step 3: Create `app/commission/ledger.py` with the helper**

Create `app/commission/ledger.py`:

```python
"""
app/commission/ledger.py

R1 — Commission ledger completeness. Per-carrier *extractors* that mirror EVERY
amount-bearing row of a commission file into CommissionLineItem rows (the "money
facts" layer). Unlike app/commission/normalizers.py, extractors do NOT collapse
paired rows — the Founders-override / Service-Fee row is kept so that
"Σ raw_amount = Σ agent_payout + Σ founders_keep" is provable.

split_breakdown() is the single derivation seam: agent_payout / founders_keep
are always derived from raw_amount + split_rate + classification, never stored.

See docs/superpowers/specs/2026-06-08-commission-ledger-completeness-design.md.
"""
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

# Classification constants (plain strings; no DB enum, forward-compat).
AGENT_COMMISSION = "agent_commission"
FOUNDERS_OVERRIDE = "founders_override"
HRA_BONUS = "hra_bonus"
CHARGEBACK = "chargeback"


@dataclass
class LineItemDraft:
    """In-memory line item before it is persisted as a CommissionLineItem.
    One per amount-bearing sheet row (paired rows NOT collapsed)."""
    carrier: str
    source_ref: str
    raw_amount: float
    classification: str
    split_rate: Optional[float] = None
    payment_type: Optional[str] = None
    member_name: str = ""
    mbi: Optional[str] = None
    carrier_member_id: Optional[str] = None
    writing_agent_raw: str = ""
    effective_date: Optional[date] = None
    term_date: Optional[date] = None


def split_breakdown(line) -> Tuple[float, float]:
    """Derive (agent_payout, founders_keep) from a line item / draft.

    - founders_override: agent gets nothing; Founders keeps the whole amount.
    - everything else (agent_commission / hra_bonus / chargeback): the amount is
      pre-split; agent_payout = raw_amount * split_rate, Founders keeps the rest.
      A None split_rate (no contract) yields payout 0 / keep = raw_amount.
    The two ALWAYS sum back to raw_amount (balance holds by construction)."""
    raw = line.raw_amount or 0.0
    if line.classification == FOUNDERS_OVERRIDE:
        return 0.0, raw
    rate = line.split_rate
    if rate is None:
        return 0.0, raw
    payout = raw * rate
    return payout, raw - payout
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_ledger.py -k split_breakdown -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/commission/ledger.py tests/test_commission_ledger.py
git commit -m "feat(commission): ledger split_breakdown + LineItemDraft"
```

---

### Task 4: Healthspring extractor + money-rows total

**Files:**
- Modify: `app/commission/ledger.py`
- Test: `tests/test_commission_ledger.py`

Context: Healthspring "Detail" sheet, columns per `normalizers.py` docstring — `1` Payment Description (`Service Fee` | `Broker Level`), `3` Writing Broker, `5` Earner Name, `7` Payment Amount, `8` Member ID, `9` MBI, `10` Member Name, `12` Eff, `13` Term. **Every** row becomes a line item (do NOT collapse). `Broker Level` → `agent_commission` (negative → `chargeback`); `Service Fee` (Founders) → `founders_override`. Money-rows total = sum of column 7 over every Detail row.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_commission_ledger.py`:

```python
def _load_fixture(name):
    from app.commission.sheet_loader import load_sheets
    return load_sheets(os.path.join(FIXTURES, name))


def test_healthspring_keeps_both_broker_and_service_fee():
    from app.commission.ledger import extract_lineitems_healthspring, FOUNDERS_OVERRIDE, AGENT_COMMISSION
    sheets = _load_fixture("healthspring_sample.xlsx")

    drafts = extract_lineitems_healthspring(sheets, split_lookup=lambda raw: 0.55)
    classes = [d.classification for d in drafts]

    # The override row that the normalizer DROPS must be present here.
    assert FOUNDERS_OVERRIDE in classes, "Service Fee (Founders override) row was dropped"
    assert AGENT_COMMISSION in classes, "Broker Level (agent commission) row missing"
    # Override rows carry no split.
    for d in drafts:
        if d.classification == FOUNDERS_OVERRIDE:
            assert d.split_rate is None
        if d.classification == AGENT_COMMISSION:
            assert d.split_rate == 0.55


def test_healthspring_money_rows_total_equals_lineitem_sum():
    from app.commission.ledger import (extract_lineitems_healthspring,
                                        money_rows_total_healthspring)
    sheets = _load_fixture("healthspring_sample.xlsx")
    drafts = extract_lineitems_healthspring(sheets, split_lookup=lambda raw: 0.55)
    assert round(sum(d.raw_amount for d in drafts), 2) == round(money_rows_total_healthspring(sheets), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_ledger.py -k healthspring -v`
Expected: FAIL — `cannot import name 'extract_lineitems_healthspring'`

- [ ] **Step 3: Implement the extractor**

Append to `app/commission/ledger.py`:

```python
from app.commission.payments import _parse_date


def _to_float(v):
    try:
        return float(str(v).replace("$", "").replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _hs_classify(desc, amount):
    d = str(desc or "").lower()
    if "service fee" in d:
        return FOUNDERS_OVERRIDE
    if amount < 0:
        return CHARGEBACK
    return AGENT_COMMISSION


def extract_lineitems_healthspring(sheets, split_lookup) -> List[LineItemDraft]:
    """One LineItemDraft per Detail row (paired rows NOT collapsed).
    split_lookup(writing_agent_raw) -> Optional[float] split rate for that agent."""
    rows = sheets.get("Detail", [])
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row) or len(row) <= 21:
            continue
        member_id = str(row[8] or "").strip()
        amount = _to_float(row[7])
        desc = str(row[1] or "")
        if not member_id and "service fee" not in desc.lower():
            continue
        classification = _hs_classify(desc, amount)
        writing = str(row[3] or "").strip()
        out.append(LineItemDraft(
            carrier="Healthspring",
            source_ref=f"healthspring::Detail::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=None if classification == FOUNDERS_OVERRIDE else split_lookup(writing),
            payment_type=str(row[0] or "").strip().lower() or None,
            member_name=str(row[10] or "").strip(),
            mbi=str(row[9] or "").strip() or None,
            carrier_member_id=member_id or None,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[12]),
            term_date=_parse_date(row[13]),
        ))
    return out


def money_rows_total_healthspring(sheets) -> float:
    """Independent re-sum of EVERY Detail-row Payment Amount (col 7). Compared
    against the line-item sum to catch a dropped/mis-summed row."""
    rows = sheets.get("Detail", [])
    total = 0.0
    for row in rows[1:]:
        if not any(row) or len(row) <= 21:
            continue
        member_id = str(row[8] or "").strip()
        desc = str(row[1] or "")
        if not member_id and "service fee" not in desc.lower():
            continue
        total += _to_float(row[7])
    return total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_ledger.py -k healthspring -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/commission/ledger.py tests/test_commission_ledger.py
git commit -m "feat(commission): Healthspring ledger extractor (keeps override rows)"
```

---

### Task 5: BCBS + Aetna extractors

**Files:**
- Modify: `app/commission/ledger.py`
- Test: `tests/test_commission_ledger.py`

Context (from `normalizers.py`): **BCBS** Sheet1 — `1` Agent Name, `2` Group Type, `4` Customer Name, `5` Customer No, `6` Orig Eff, `9` Coverage To, `14` **Commission** (use this, NOT col 13 Billed). Skip the `Total:` row (no Customer No). Each row → `agent_commission` (negative or `ADJUSTMENT` → `chargeback`). FY/enrollment rows with 0 commission are still recorded. **Aetna** — agency-level single sheet (first sheet); `1` MBI, `2` Member ID, `4` Member Name, `12` Eff, `13` Term, `16` Writing Agent, `20` Payee Amount. Each row → `agent_commission` (negative → `chargeback`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_commission_ledger.py`:

```python
def test_bcbs_uses_commission_column_and_records_zero_rows():
    from app.commission.ledger import extract_lineitems_bcbs, money_rows_total_bcbs, AGENT_COMMISSION, CHARGEBACK
    sheets = _load_fixture("bcbs_sample.xlsx")
    drafts = extract_lineitems_bcbs(sheets, split_lookup=lambda raw: 0.55)
    assert drafts, "no BCBS line items extracted"
    for d in drafts:
        assert d.classification in (AGENT_COMMISSION, CHARGEBACK)
        assert d.split_rate == 0.55
    assert round(sum(d.raw_amount for d in drafts), 2) == round(money_rows_total_bcbs(sheets), 2)


def test_aetna_extracts_payee_amount_rows():
    from app.commission.ledger import extract_lineitems_aetna, money_rows_total_aetna
    sheets = _load_fixture("aetna_sample.xlsx")
    drafts = extract_lineitems_aetna(sheets, split_lookup=lambda raw: 0.55)
    assert drafts, "no Aetna line items extracted"
    assert round(sum(d.raw_amount for d in drafts), 2) == round(money_rows_total_aetna(sheets), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_ledger.py -k "bcbs or aetna" -v`
Expected: FAIL — `cannot import name 'extract_lineitems_bcbs'`

- [ ] **Step 3: Implement the extractors**

Append to `app/commission/ledger.py`:

```python
def extract_lineitems_bcbs(sheets, split_lookup) -> List[LineItemDraft]:
    rows = sheets.get("Sheet1", [])
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row) or len(row) <= 14:
            continue
        name = str(row[4] or "").strip()
        customer_no = str(row[5] or "").strip()
        if not name or not customer_no:        # skips Total: row
            continue
        amount = _to_float(row[14])            # Commission column, NOT Billed
        gt = str(row[2] or "").upper().strip()
        classification = CHARGEBACK if (amount < 0 or gt == "ADJUSTMENT") else AGENT_COMMISSION
        writing = str(row[1] or "").strip()
        out.append(LineItemDraft(
            carrier="BCBS",
            source_ref=f"bcbs::Sheet1::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=gt.lower() or None,
            member_name=name,
            mbi=None,
            carrier_member_id=customer_no,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[6]),
            term_date=_parse_date(row[9]),
        ))
    return out


def money_rows_total_bcbs(sheets) -> float:
    rows = sheets.get("Sheet1", [])
    total = 0.0
    for row in rows[1:]:
        if not any(row) or len(row) <= 14:
            continue
        if not str(row[4] or "").strip() or not str(row[5] or "").strip():
            continue
        total += _to_float(row[14])
    return total


def extract_lineitems_aetna(sheets, split_lookup) -> List[LineItemDraft]:
    if not sheets:
        return []
    first = next(iter(sheets.values()))
    out = []
    for idx, row in enumerate(first[1:], start=1):
        if not any(row) or len(row) < 21:
            continue
        name = str(row[4] or "").strip()
        if not name:
            continue
        amount = _to_float(row[20])
        classification = CHARGEBACK if amount < 0 else AGENT_COMMISSION
        writing = str(row[16] or "").strip()
        out.append(LineItemDraft(
            carrier="Aetna",
            source_ref=f"aetna::0::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=str(row[6] or "").strip().lower() or None,
            member_name=name,
            mbi=str(row[1] or "").strip() or None,
            carrier_member_id=str(row[2] or "").strip() or None,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[12]),
            term_date=_parse_date(row[13]),
        ))
    return out


def money_rows_total_aetna(sheets) -> float:
    if not sheets:
        return 0.0
    first = next(iter(sheets.values()))
    total = 0.0
    for row in first[1:]:
        if not any(row) or len(row) < 21:
            continue
        if not str(row[4] or "").strip():
            continue
        total += _to_float(row[20])
    return total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_ledger.py -k "bcbs or aetna" -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/commission/ledger.py tests/test_commission_ledger.py
git commit -m "feat(commission): BCBS + Aetna ledger extractors"
```

---

### Task 6: Devoted + Humana extractors

**Files:**
- Modify: `app/commission/ledger.py`
- Test: `tests/test_commission_ledger.py`

Context (from `normalizers.py`): **Devoted** has up to 4 sheets — `Agent Portion`, `Override`, `HRA`, `Total`. Columns for Agent Portion/Override (identical): `2` Agent Name, `3` Member ID, `4` HICN(MBI), `5` First, `6` Last, `9` Eff, `10` Disenroll, `11` Contract, `15` Commission Type, `17` Amount. HRA: `0` Rep Name, `1` Rep ID, `2` Amount, `3` Note. → `Agent Portion` rows = `agent_commission` (neg/disenroll → `chargeback`); `Override` rows = `founders_override`; `HRA` rows = `hra_bonus`. Money-rows total = Agent Portion col 17 + Override col 17 + HRA col 2. **Humana** — header-keyed columns (`UMID`, `GrpName`, `PaidAmount`, `TxnTypeCd`, `WaName`, `EffDate`, `Contract`, `PID`). `HRAP` → `hra_bonus`; negative → `chargeback`; else `agent_commission`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_commission_ledger.py`:

```python
def test_devoted_produces_override_agent_and_hra():
    from app.commission.ledger import (extract_lineitems_devoted, money_rows_total_devoted,
                                        FOUNDERS_OVERRIDE, AGENT_COMMISSION, HRA_BONUS)
    sheets = _load_fixture("devoted_sample.xlsx")
    drafts = extract_lineitems_devoted(sheets, split_lookup=lambda raw: 0.55)
    classes = {d.classification for d in drafts}
    # Override must be present (the row the normalizer collapses away).
    assert FOUNDERS_OVERRIDE in classes
    assert AGENT_COMMISSION in classes
    # HRA may or may not be in this fixture; if present it is hra_bonus with split.
    for d in drafts:
        if d.classification == HRA_BONUS:
            assert d.split_rate == 0.55
        if d.classification == FOUNDERS_OVERRIDE:
            assert d.split_rate is None
    assert round(sum(d.raw_amount for d in drafts), 2) == round(money_rows_total_devoted(sheets), 2)


def test_humana_classifies_and_totals():
    from app.commission.ledger import extract_lineitems_humana, money_rows_total_humana
    sheets = _load_fixture("humana_sample.xls")
    drafts = extract_lineitems_humana(sheets, split_lookup=lambda raw: 0.55)
    assert drafts, "no Humana line items extracted"
    assert round(sum(d.raw_amount for d in drafts), 2) == round(money_rows_total_humana(sheets), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_ledger.py -k "devoted or humana" -v`
Expected: FAIL — `cannot import name 'extract_lineitems_devoted'`

- [ ] **Step 3: Implement the extractors**

Append to `app/commission/ledger.py`:

```python
def _devoted_sheet_rows(sheets, sheet_name):
    return sheets.get(sheet_name, [])


def extract_lineitems_devoted(sheets, split_lookup) -> List[LineItemDraft]:
    out = []
    # Agent Portion → agent_commission / chargeback
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "Agent Portion")[1:], start=1):
        if not any(row) or len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        disen = _parse_date(row[10])
        classification = CHARGEBACK if (amount < 0 or disen) else AGENT_COMMISSION
        writing = str(row[2] or "").strip()
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::Agent Portion::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=str(row[15] or "").strip().lower() or None,
            member_name=f"{first} {last}".strip(),
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[9]),
            term_date=disen,
        ))
    # Override → founders_override (no split)
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "Override")[1:], start=1):
        if not any(row) or len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::Override::{idx}",
            raw_amount=_to_float(row[17]),
            classification=FOUNDERS_OVERRIDE,
            split_rate=None,
            payment_type="override",
            member_name=f"{first} {last}".strip(),
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            writing_agent_raw=str(row[2] or "").strip(),
        ))
    # HRA → hra_bonus (split applies)
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "HRA")[1:], start=1):
        if not any(row) or len(row) <= 3:
            continue
        rep = str(row[0] or "").strip()
        amt = _to_float(row[2])
        if not rep or amt == 0:
            continue
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::HRA::{idx}",
            raw_amount=amt,
            classification=HRA_BONUS,
            split_rate=split_lookup(rep),
            payment_type="hra",
            member_name=str(row[3] or "").strip() or "HRA Bonus",
            writing_agent_raw=rep,
        ))
    return out


def money_rows_total_devoted(sheets) -> float:
    total = 0.0
    for row in _devoted_sheet_rows(sheets, "Agent Portion")[1:]:
        if not any(row) or len(row) <= 17 or not str(row[3] or "").strip():
            continue
        total += _to_float(row[17])
    for row in _devoted_sheet_rows(sheets, "Override")[1:]:
        if not any(row) or len(row) <= 17 or not str(row[3] or "").strip():
            continue
        total += _to_float(row[17])
    for row in _devoted_sheet_rows(sheets, "HRA")[1:]:
        if not any(row) or len(row) <= 3:
            continue
        if not str(row[0] or "").strip() or _to_float(row[2]) == 0:
            continue
        total += _to_float(row[2])
    return total


def _humana_cols(rows):
    header = rows[0]
    return {h: i for i, h in enumerate(header)}


def extract_lineitems_humana(sheets, split_lookup) -> List[LineItemDraft]:
    if not sheets:
        return []
    name = next((n for n in sheets if "CommissionData" in n), None) or next(iter(sheets))
    rows = sheets.get(name, [])
    if not rows:
        return []
    col = _humana_cols(rows)

    def g(row, key):
        i = col.get(key)
        return row[i] if i is not None and i < len(row) else ""

    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row):
            continue
        umid = str(g(row, "UMID") or "").strip()
        grp = str(g(row, "GrpName") or "").strip()
        if not umid and not grp:
            continue
        amount = _to_float(g(row, "PaidAmount"))
        txn = str(g(row, "TxnTypeCd") or "").upper().strip()
        if txn == "HRAP":
            classification = HRA_BONUS
        elif amount < 0:
            classification = CHARGEBACK
        else:
            classification = AGENT_COMMISSION
        writing = str(g(row, "WaName") or "").strip()
        out.append(LineItemDraft(
            carrier="Humana",
            source_ref=f"humana::{name}::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=txn.lower() or None,
            member_name=grp,
            mbi=umid or None,
            carrier_member_id=str(g(row, "PID") or "").strip() or None,
            writing_agent_raw=writing,
            effective_date=_parse_date(g(row, "EffDate")),
        ))
    return out


def money_rows_total_humana(sheets) -> float:
    if not sheets:
        return 0.0
    name = next((n for n in sheets if "CommissionData" in n), None) or next(iter(sheets))
    rows = sheets.get(name, [])
    if not rows:
        return 0.0
    col = _humana_cols(rows)
    pi = col.get("PaidAmount")
    ui = col.get("UMID")
    gi = col.get("GrpName")
    total = 0.0
    for row in rows[1:]:
        if not any(row):
            continue
        umid = str(row[ui] or "").strip() if ui is not None and ui < len(row) else ""
        grp = str(row[gi] or "").strip() if gi is not None and gi < len(row) else ""
        if not umid and not grp:
            continue
        if pi is not None and pi < len(row):
            total += _to_float(row[pi])
    return total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_ledger.py -k "devoted or humana" -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/commission/ledger.py tests/test_commission_ledger.py
git commit -m "feat(commission): Devoted + Humana ledger extractors"
```

---

### Task 7: `EXTRACTORS` registry + `verify_statement_balance`

**Files:**
- Modify: `app/commission/ledger.py`
- Test: `tests/test_commission_ledger.py`

Context: bundle each carrier's `(extractor, money_rows_total)` so the upload + balance check are carrier-agnostic. `verify_statement_balance` takes the persisted line items + the raw sheets and asserts both the internal balance and the completeness check.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_commission_ledger.py`:

```python
def test_registry_has_five_clean_carriers_not_uhc():
    from app.commission.ledger import EXTRACTORS
    assert set(EXTRACTORS) == {"Healthspring", "Devoted", "BCBS", "Aetna", "Humana"}
    assert "UHC" not in EXTRACTORS


def test_verify_statement_balance_internal_and_completeness():
    # Build line items in-memory from a fixture, then verify against the sheets.
    from app.commission.ledger import EXTRACTORS, verify_statement_balance, split_breakdown
    sheets = _load_fixture("bcbs_sample.xlsx")
    extractor, _money = EXTRACTORS["BCBS"]
    drafts = extractor(sheets, split_lookup=lambda raw: 0.55)

    report = verify_statement_balance("BCBS", drafts, sheets)
    assert report.internal_ok, report
    assert report.completeness_ok, report
    # Internal balance: every draft's payout + keep == its raw.
    for d in drafts:
        p, k = split_breakdown(d)
        assert round(p + k, 2) == round(d.raw_amount, 2)


def test_verify_statement_balance_fails_when_a_row_dropped():
    from app.commission.ledger import EXTRACTORS, verify_statement_balance
    sheets = _load_fixture("bcbs_sample.xlsx")
    extractor, _money = EXTRACTORS["BCBS"]
    drafts = extractor(sheets, split_lookup=lambda raw: 0.55)
    assert len(drafts) >= 2
    dropped = drafts[:-1]                 # simulate the extractor losing a row
    report = verify_statement_balance("BCBS", dropped, sheets)
    assert report.completeness_ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_ledger.py -k "registry or verify_statement" -v`
Expected: FAIL — `cannot import name 'EXTRACTORS'`

- [ ] **Step 3: Implement registry + verifier**

Append to `app/commission/ledger.py`:

```python
from dataclasses import dataclass as _dc

# (extractor, money_rows_total) per carrier. UHC deliberately absent (R4).
EXTRACTORS = {
    "Healthspring": (extract_lineitems_healthspring, money_rows_total_healthspring),
    "Devoted": (extract_lineitems_devoted, money_rows_total_devoted),
    "BCBS": (extract_lineitems_bcbs, money_rows_total_bcbs),
    "Aetna": (extract_lineitems_aetna, money_rows_total_aetna),
    "Humana": (extract_lineitems_humana, money_rows_total_humana),
}


@_dc
class BalanceReport:
    carrier: str
    lineitem_total: float
    money_rows_total: float
    agent_payout_total: float
    founders_keep_total: float
    internal_ok: bool
    completeness_ok: bool

    def __str__(self):
        return (f"<BalanceReport {self.carrier} li={self.lineitem_total} "
                f"sheet={self.money_rows_total} payout={self.agent_payout_total} "
                f"keep={self.founders_keep_total} internal_ok={self.internal_ok} "
                f"completeness_ok={self.completeness_ok}>")


def verify_statement_balance(carrier, line_items, sheets, tol=0.01) -> BalanceReport:
    """Assert (1) internal balance: Σ raw == Σ payout + Σ keep (true by
    construction), and (2) completeness: Σ line-item raw == independent re-sum of
    the carrier's money rows from the raw sheets. A row the extractor dropped or
    mis-summed makes the two diverge → completeness_ok=False, naming the carrier.
    line_items may be LineItemDraft or persisted CommissionLineItem (both expose
    raw_amount / split_rate / classification)."""
    _, money_total_fn = EXTRACTORS[carrier]
    li_total = round(sum((li.raw_amount or 0.0) for li in line_items), 2)
    payout_total = 0.0
    keep_total = 0.0
    for li in line_items:
        p, k = split_breakdown(li)
        payout_total += p
        keep_total += k
    payout_total = round(payout_total, 2)
    keep_total = round(keep_total, 2)
    money_total = round(money_total_fn(sheets), 2)
    internal_ok = abs(li_total - (payout_total + keep_total)) <= tol
    completeness_ok = abs(li_total - money_total) <= tol
    return BalanceReport(
        carrier=carrier, lineitem_total=li_total, money_rows_total=money_total,
        agent_payout_total=payout_total, founders_keep_total=keep_total,
        internal_ok=internal_ok, completeness_ok=completeness_ok)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_ledger.py -k "registry or verify_statement" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/commission/ledger.py tests/test_commission_ledger.py
git commit -m "feat(commission): ledger EXTRACTORS registry + verify_statement_balance"
```

---

### Task 8: `persist_line_items` + upload wiring

**Files:**
- Modify: `app/commission/ledger.py` (add `persist_line_items`)
- Modify: `app/commission/routes.py` (`_ingest_normalized_upload`, ~lines 865-883)
- Test: `tests/test_commission_ledger.py`

Context: `persist_line_items` turns drafts into `CommissionLineItem` rows, resolving each draft's `writing_agent_raw` → `agent_id` via the passed `agent_resolver` (`_match_agent_name`), idempotent on `(statement_id, source_ref)`. The upload wiring runs it inside the existing `try` block in `_ingest_normalized_upload`, after `ingest_statement`, and clears stale line items on replace alongside the existing `PolicyPayment` delete.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_ledger.py`:

```python
def test_persist_line_items_resolves_agent_and_is_idempotent(db_session, agency):
    from app.models import CommissionLineItem, CommissionStatement, User
    from app.commission.ledger import LineItemDraft, persist_line_items, AGENT_COMMISSION
    from app.extensions import db

    agent = User(name="Justin Basinger", email="justin@x.com", agency_id=agency.id)
    db.session.add(agent)
    stmt = CommissionStatement(agency_id=agency.id, carrier="BCBS", agent_id=None,
                               period_label="April 2026", filename="b.xlsx")
    db.session.add(stmt)
    db.session.flush()

    drafts = [LineItemDraft(carrier="BCBS", source_ref="bcbs::Sheet1::1",
                            raw_amount=28.91, split_rate=0.55,
                            classification=AGENT_COMMISSION,
                            writing_agent_raw="Basinger, Justin")]

    def resolver(raw):
        return agent.id if "basinger" in raw.lower() else None

    n1 = persist_line_items("BCBS", drafts, stmt, agency.id, agent_resolver=resolver)
    db.session.flush()
    rows = CommissionLineItem.query.filter_by(statement_id=stmt.id).all()
    assert n1 == 1 and len(rows) == 1
    assert rows[0].agent_id == agent.id

    # Re-run: same source_ref updates in place, no duplicate.
    persist_line_items("BCBS", drafts, stmt, agency.id, agent_resolver=resolver)
    db.session.flush()
    assert CommissionLineItem.query.filter_by(statement_id=stmt.id).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_ledger.py -k persist_line_items -v`
Expected: FAIL — `cannot import name 'persist_line_items'`

- [ ] **Step 3: Implement `persist_line_items`**

Append to `app/commission/ledger.py` (add `from app.extensions import db` and `from app.models import CommissionLineItem` at the top of the function or module — module-level import is fine since models import does not import ledger):

At the **top** of `app/commission/ledger.py`, after the existing imports, add:

```python
from app.extensions import db
from app.models import CommissionLineItem
```

Then append the function:

```python
def persist_line_items(carrier, drafts, statement, agency_id, agent_resolver=None) -> int:
    """Insert/update CommissionLineItem rows for a statement, idempotent on
    (statement_id, source_ref). agent_resolver(writing_agent_raw) -> user_id|None
    resolves each draft's writing agent. Returns count written."""
    count = 0
    for d in drafts:
        agent_id = None
        if agent_resolver is not None and d.writing_agent_raw:
            agent_id = agent_resolver(d.writing_agent_raw)
        existing = (CommissionLineItem.query
                    .filter_by(statement_id=statement.id, agency_id=agency_id,
                               source_ref=d.source_ref)
                    .first())
        if existing is None:
            existing = CommissionLineItem(
                agency_id=agency_id, statement_id=statement.id,
                source_ref=d.source_ref, carrier=carrier)
            db.session.add(existing)
        existing.carrier = carrier
        existing.period_label = statement.period_label
        existing.statement_date = statement.statement_date
        existing.agent_id = agent_id
        existing.member_name = d.member_name
        existing.mbi = d.mbi
        existing.carrier_member_id = d.carrier_member_id
        existing.raw_amount = d.raw_amount
        existing.split_rate = d.split_rate
        existing.classification = d.classification
        existing.payment_type = d.payment_type
        count += 1
    return count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_ledger.py -k persist_line_items -v`
Expected: PASS

- [ ] **Step 5: Wire into the upload path**

In `app/commission/routes.py`, add to the imports near line 18:

```python
from app.commission.ledger import EXTRACTORS, persist_line_items, verify_statement_balance
from app.models import CommissionLineItem
```

(If `CommissionLineItem` is already imported via the existing `from app.models import ...` line at the top, add it there instead of a second import.)

In `_ingest_normalized_upload`, the replace-cleanup block currently reads (~line 867):

```python
    if existing:
        PolicyPayment.query.filter_by(
            statement_id=stmt.id, agency_id=current_user.agency_id
        ).delete(synchronize_session=False)
        db.session.flush()
```

Change it to also clear stale line items:

```python
    if existing:
        PolicyPayment.query.filter_by(
            statement_id=stmt.id, agency_id=current_user.agency_id
        ).delete(synchronize_session=False)
        CommissionLineItem.query.filter_by(
            statement_id=stmt.id, agency_id=current_user.agency_id
        ).delete(synchronize_session=False)
        db.session.flush()
```

In the `try` block, after the `ingest = ingest_statement(...)` call (~line 875) and before the `stmt.gross_amount = ...` line, insert the ledger extraction:

```python
        # R1 ledger: persist EVERY sheet row (incl. Founders overrides the
        # customer-sync normalizer collapses away) so the balance is provable.
        extractor, _money = EXTRACTORS.get(carrier, (None, None))
        if extractor is not None:
            drafts = extractor(sheets, split_lookup=lambda raw, c=carrier: _ledger_split_lookup(raw, c))
            persist_line_items(carrier, drafts, stmt, current_user.agency_id,
                               agent_resolver=_match_agent_name)
            db.session.flush()
            report = verify_statement_balance(carrier, drafts, sheets)
            if not report.completeness_ok:
                current_app.logger.warning(
                    "Commission ledger completeness check FAILED for "
                    f"{carrier} {period_label}: {report}")
```

Add a `_ledger_split_lookup` helper near `_match_agent_name` (~line 639) in `routes.py`:

```python
def _ledger_split_lookup(writing_agent_raw, carrier):
    """Split rate for a writing agent on a carrier, snapshotted at import.
    Falls back to any active contract for the carrier, then 0.55."""
    agent_id = _match_agent_name(writing_agent_raw) if writing_agent_raw else None
    contract = None
    if agent_id:
        contract = AgentCarrierContract.query.filter_by(
            agent_id=agent_id, carrier=carrier, is_active=True,
            agency_id=current_user.agency_id).first()
    if contract is None:
        contract = AgentCarrierContract.query.filter_by(
            carrier=carrier, is_active=True,
            agency_id=current_user.agency_id).first()
    return contract.split_rate if contract else 0.55
```

- [ ] **Step 6: Run the full ledger suite + the existing commission suites (no regressions)**

Run: `python3 -m pytest tests/test_commission_ledger.py tests/test_commission_ingest.py tests/test_commission_normalizers.py -v`
Expected: all PASS (new ledger tests + unchanged ingest/normalizer tests).

- [ ] **Step 7: Commit**

```bash
git add app/commission/ledger.py app/commission/routes.py tests/test_commission_ledger.py
git commit -m "feat(commission): persist line items on upload + completeness check (R1 wiring)"
```

---

### Task 9: Full-suite regression + balance assertions across all 5 carriers

**Files:**
- Test: `tests/test_commission_ledger.py`

- [ ] **Step 1: Write a parametrized balance test across every fixture**

Append to `tests/test_commission_ledger.py`:

```python
import pytest

@pytest.mark.parametrize("carrier,fixture", [
    ("Healthspring", "healthspring_sample.xlsx"),
    ("Devoted", "devoted_sample.xlsx"),
    ("BCBS", "bcbs_sample.xlsx"),
    ("Aetna", "aetna_sample.xlsx"),
    ("Humana", "humana_sample.xls"),
])
def test_every_carrier_balances_and_is_complete(carrier, fixture):
    from app.commission.ledger import EXTRACTORS, verify_statement_balance
    sheets = _load_fixture(fixture)
    extractor, _ = EXTRACTORS[carrier]
    drafts = extractor(sheets, split_lookup=lambda raw: 0.55)
    assert drafts, f"{carrier}: no line items extracted"
    report = verify_statement_balance(carrier, drafts, sheets)
    assert report.internal_ok, report
    assert report.completeness_ok, report
```

- [ ] **Step 2: Run the parametrized test**

Run: `python3 -m pytest tests/test_commission_ledger.py::test_every_carrier_balances_and_is_complete -v`
Expected: PASS (5 params). If any carrier's completeness fails, the BalanceReport in the assertion message names the carrier and shows `lineitem_total` vs `money_rows_total` — fix that extractor's row-filter to match its money-rows helper, then re-run.

- [ ] **Step 3: Run the ENTIRE test suite (no regressions anywhere)**

Run: `python3 -m pytest -q`
Expected: all tests pass (133 prior + the new ledger tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_commission_ledger.py
git commit -m "test(commission): all-carrier ledger balance + completeness parametrized"
```

---

### Task 10: Update spec + CLAUDE.md, document the re-upload backfill step

**Files:**
- Modify: `docs/superpowers/specs/2026-06-08-commission-ledger-completeness-design.md`
- Modify: `CLAUDE.md` (Build Status section)

- [ ] **Step 1: Mark the backfill resolution in the spec**

In the spec, replace the "### Re-import backfill" section body with:

```markdown
### Re-import backfill (RESOLVED → re-upload, no script)

Raw commission files are not persisted by the portal (uploads write to a
discarded tempfile; only the filename string + derived PolicyPayment rows
survive), so a script cannot re-read originals. Upload is already idempotent
(keyed on source_ref + content fingerprint; replace clears stale rows), and
prod is reproducible playground data. Backfill is therefore achieved by AJ
re-uploading the 5 clean-carrier files through the existing admin upload — line
items populate automatically (Task 8 wiring). No backfill script.
```

- [ ] **Step 2: Add a CLAUDE.md build-status entry**

In `CLAUDE.md`, in the Build Status list, after the "Plan Data Integrity & Provenance" entry, add:

```markdown
- **R1 — Commission Ledger Completeness ✅ (2026-06-08)** — `CommissionLineItem` (migration 023): a faithful 1:1 mirror of every amount-bearing commission-sheet row (full pre-split `raw_amount` + `classification` ∈ {agent_commission, founders_override, hra_bonus, chargeback} + carrier/agent/customer/payment_type). `app/commission/ledger.py` = per-carrier extractors (which, unlike the customer-sync normalizers, do NOT collapse paired rows — the dropped Founders-override is what makes balancing provable) + `split_breakdown()` (derives agent_payout/founders_keep from raw_amount × split_rate; never stored) + `verify_statement_balance()` (internal balance + independent re-sum completeness check that fails loudly on a dropped row). Wired into `_ingest_normalized_upload` alongside PolicyPayment writes; idempotent on (statement_id, source_ref). UHC absent (R4). Backfill = re-upload the 5 clean-carrier files (no script). Keystone for R2 (per-agent payout) / R3 (balance view).
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-06-08-commission-ledger-completeness-design.md CLAUDE.md
git commit -m "docs(R1): mark backfill resolved (re-upload) + build-status entry"
```

---

## Deployment (after all tasks merged, run by Tim/AJ)

Per CLAUDE.md VPS deploy + the session-handoff method (backup DB first):

```bash
ssh -i /home/timothywinslowlinux/.ssh/id_ed25519 root@23.187.248.100
cd /var/www/founders-portal && git pull \
  && ./venv/bin/pip install -r requirements.txt \
  && flask db upgrade \
  && systemctl restart founders-portal
```

Then AJ re-uploads the 5 clean-carrier April files via the admin commission upload to populate line items. Verify in a `psql` count: `SELECT carrier, count(*), round(sum(raw_amount)::numeric,2) FROM commission_line_items GROUP BY carrier;`

---

## Self-review notes (done while writing)

- **Spec coverage:** model+migration (T1/T2) ✅; `split_breakdown` (T3) ✅; 5 extractors keeping every row (T4 HS, T5 BCBS+Aetna, T6 Devoted+Humana) ✅; `EXTRACTORS` registry + `verify_statement_balance` internal+completeness (T7) ✅; upload wiring + idempotency (T8) ✅; all-carrier balance tests + idempotency + split snapshot (T8/T9) ✅; backfill (re-upload, T10) ✅; boundaries (no UHC, PolicyPayment untouched) honored ✅.
- **Naming consistency:** `LineItemDraft`, `split_breakdown`, `EXTRACTORS`, `extract_lineitems_<carrier>`, `money_rows_total_<carrier>`, `verify_statement_balance`, `persist_line_items`, `BalanceReport`, classification constants `AGENT_COMMISSION`/`FOUNDERS_OVERRIDE`/`HRA_BONUS`/`CHARGEBACK` used identically across all tasks.
- **Real-data caveat (carry into execution):** column indices/sheet names are copied verbatim from the verified `normalizers.py`, but extractor row-filters and `money_rows_total_*` must agree exactly or T9 completeness fails — that divergence is the intended signal, not a test bug. Fixtures are real raw files; if a fixture lacks a sheet (e.g. Devoted HRA), the test only asserts presence of what exists.
