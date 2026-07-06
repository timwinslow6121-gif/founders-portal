# Carrier ID Crosswalk (Humana-first) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist a `GrpNbr ↔ customer ↔ MBI` crosswalk so a Humana member linked once (via a new-enrollment MBI row) carries all future renewals to the same customer deterministically — ending the commission-stub inflation for Humana.

**Architecture:** Add a `carrier_id_crosswalk` table + a lookup/write-back step to the EXISTING `_resolve_commission_match_or_park` resolver (not a parallel matcher). Carry `GrpNbr` on the `MemberFact`. Seed the crosswalk from MBI-bearing history via a READ-ONLY file scan (never re-running ingest, so AJ's proven commission data is untouched). Clean up legacy Humana stubs via the existing audited `merge_customers`.

**Tech Stack:** Flask 3.0, Flask-SQLAlchemy, Flask-Migrate (Alembic), PostgreSQL 16 (prod) / SQLite (tests), pytest.

## Global Constraints

- Every query agency-scoped; never read `current_user` outside a request (pass `agency_id` explicitly — see the 2026-07-04 `_ledger_split_lookup` bug).
- No name-ONLY auto-merge in the live upload path, ever (the two-David-Whites rule). Name+eff+plan / last6 is used ONLY by the one-time seed + the human-confirm merge UI.
- The Humana MBI is stored in `customers.humana_id` (intentional — `_match_by_mbi` reads it there). Do NOT change this or the parser's ID reading.
- Migration head is currently `033`; new migration is `034`, `down_revision="033"`.
- Seeding is a READ-ONLY file scan that writes ONLY `carrier_id_crosswalk` rows — it must never call the ingest pipeline or touch `commission_line_items`/`policy_payments`/amounts.
- DB backup before any migration/apply; dry-run then real-Postgres `--apply`; confirm `systemctl restart` cycled; all times EST/EDT (DB is UTC).
- Opus whole-branch review on this data path before merge (it has caught a Postgres-only bug every prior round).

---

### Task 1: `carrier_id_crosswalk` model + migration 034

**Files:**
- Modify: `app/models.py` (add `CarrierIdCrosswalk` model near `Customer`)
- Create: `migrations/versions/034_carrier_id_crosswalk.py`
- Test: `tests/test_carrier_crosswalk.py`

**Interfaces:**
- Produces: `CarrierIdCrosswalk` model with columns `id, agency_id, carrier, carrier_key, key_kind, customer_id, mbi, confidence, source_note, created_at`; unique constraint `(agency_id, carrier, carrier_key)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_carrier_crosswalk.py
import pytest

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

def test_crosswalk_row_roundtrip_and_unique(ctx):
    from app.extensions import db
    from app.models import CarrierIdCrosswalk, Customer
    app, agency_id = ctx
    c = Customer(agency_id=agency_id, first_name="Sandra", last_name="Agner",
                 full_name="Sandra Agner")
    db.session.add(c); db.session.flush()
    row = CarrierIdCrosswalk(agency_id=agency_id, carrier="Humana",
                             carrier_key="00019275764K", key_kind="grpnbr",
                             customer_id=c.id, mbi=None, confidence="exact_id")
    db.session.add(row); db.session.flush()
    got = CarrierIdCrosswalk.query.filter_by(
        agency_id=agency_id, carrier="Humana", carrier_key="00019275764K").first()
    assert got is not None and got.customer_id == c.id
    # unique (agency_id, carrier, carrier_key)
    dup = CarrierIdCrosswalk(agency_id=agency_id, carrier="Humana",
                             carrier_key="00019275764K", key_kind="grpnbr",
                             customer_id=c.id, confidence="exact_id")
    db.session.add(dup)
    with pytest.raises(Exception):
        db.session.flush()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_carrier_crosswalk.py::test_crosswalk_row_roundtrip_and_unique -v`
Expected: FAIL with `ImportError: cannot import name 'CarrierIdCrosswalk'`

- [ ] **Step 3: Add the model**

```python
# app/models.py — add near the Customer model
class CarrierIdCrosswalk(db.Model):
    """Permanent (carrier, carrier_key) → customer equivalence. Lets a member
    linked ONCE (e.g. via a new-enrollment MBI row) carry all future renewals —
    which reuse the same carrier_key (Humana GrpNbr) but carry no MBI — to the
    same customer deterministically. See
    docs/superpowers/specs/2026-07-04-carrier-id-crosswalk-reconciliation-design.md."""
    __tablename__ = "carrier_id_crosswalk"
    id          = db.Column(db.Integer, primary_key=True)
    agency_id   = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    carrier     = db.Column(db.String(32), nullable=False, index=True)
    carrier_key = db.Column(db.String(64), nullable=False)   # Humana GrpNbr, BCBS Customer No, ...
    key_kind    = db.Column(db.String(24), nullable=False)   # 'grpnbr' | 'customer_no' | 'member_id'
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    mbi         = db.Column(db.String(20))                   # captured when known
    confidence  = db.Column(db.String(24), nullable=False, default="exact_id")
    source_note = db.Column(db.String(256))
    created_at  = db.Column(db.DateTime, server_default=db.func.now())
    __table_args__ = (
        db.UniqueConstraint("agency_id", "carrier", "carrier_key",
                            name="uq_crosswalk_agency_carrier_key"),
    )
```

- [ ] **Step 4: Create migration 034**

```python
# migrations/versions/034_carrier_id_crosswalk.py
"""add carrier_id_crosswalk

Revision ID: 034
Revises: 033
"""
from alembic import op
import sqlalchemy as sa

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "carrier_id_crosswalk",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("carrier", sa.String(length=32), nullable=False),
        sa.Column("carrier_key", sa.String(length=64), nullable=False),
        sa.Column("key_kind", sa.String(length=24), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("mbi", sa.String(length=20)),
        sa.Column("confidence", sa.String(length=24), nullable=False, server_default="exact_id"),
        sa.Column("source_note", sa.String(length=256)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("agency_id", "carrier", "carrier_key",
                            name="uq_crosswalk_agency_carrier_key"),
    )
    op.create_index("ix_carrier_id_crosswalk_agency_id", "carrier_id_crosswalk", ["agency_id"])
    op.create_index("ix_carrier_id_crosswalk_carrier", "carrier_id_crosswalk", ["carrier"])
    op.create_index("ix_carrier_id_crosswalk_customer_id", "carrier_id_crosswalk", ["customer_id"])

def downgrade():
    op.drop_table("carrier_id_crosswalk")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_carrier_crosswalk.py::test_crosswalk_row_roundtrip_and_unique -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/models.py migrations/versions/034_carrier_id_crosswalk.py tests/test_carrier_crosswalk.py
git commit -m "feat: carrier_id_crosswalk table (migration 034) — persistent GrpNbr↔customer↔MBI"
```

---

### Task 2: carry `GrpNbr` on the MemberFact

**Files:**
- Modify: `app/commission/member_fact.py` (add `member_group_key` field)
- Modify: `app/commission/normalizers.py` (`normalize_humana` reads GrpNbr)
- Test: `tests/test_commission_normalizers.py`

**Interfaces:**
- Consumes: `MemberFact` dataclass from Task 1's environment (unchanged), `normalize_humana`.
- Produces: `MemberFact.member_group_key: Optional[str] = None`, populated with the Humana `GrpNbr` column value by `normalize_humana`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_commission_normalizers.py — add
def test_normalize_humana_carries_grpnbr():
    from app.commission.normalizers import normalize_humana
    sheets = {"CommissionData_1": [
        ["GrpName", "GrpNbr", "PID", "UMID", "EffDate", "Contract", "TxnTypeCd", "PaidAmount"],
        ["AGNER SANDRA B", "00019275764K", "591236450", "", "2026-06-01", "H1036", "ARCM", 28.91],
    ]}
    facts = normalize_humana(sheets)
    assert len(facts) == 1
    assert facts[0].member_group_key == "00019275764K"
    assert facts[0].carrier_member_id == "591236450"   # PID, unchanged
    assert facts[0].mbi is None                          # renewal → no MBI, unchanged
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_normalizers.py::test_normalize_humana_carries_grpnbr -v`
Expected: FAIL with `AttributeError: 'MemberFact' object has no attribute 'member_group_key'`

- [ ] **Step 3: Add the field + populate it**

In `app/commission/member_fact.py`, in the `# identity` block of `MemberFact`, after `carrier_member_id`:

```python
    member_group_key: Optional[str] = None   # Humana GrpNbr — stable per-member crosswalk key
```

In `app/commission/normalizers.py`, in `normalize_humana`'s `out.append(MemberFact(...))`, add one kwarg (alongside the existing `carrier_member_id=...`):

```python
            member_group_key=str(g(row, "GrpNbr") or "").strip() or None,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_normalizers.py::test_normalize_humana_carries_grpnbr -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/member_fact.py app/commission/normalizers.py tests/test_commission_normalizers.py
git commit -m "feat: MemberFact.member_group_key; normalize_humana reads GrpNbr"
```

---

### Task 3: crosswalk lookup + write-back in the resolver

**Files:**
- Modify: `app/commission/resolver.py` (`_resolve_commission_match_or_park` + two small helpers)
- Test: `tests/test_commission_resolver.py`

**Interfaces:**
- Consumes: `CarrierIdCrosswalk` (Task 1), `MemberFact.member_group_key` (Task 2), existing `_match_by_mbi`, `_match_by_carrier_member_id`, `_attach` (local in `_resolve_commission_match_or_park`).
- Produces: `_crosswalk_lookup(fact, agency_id) -> Optional[Customer]` and `_crosswalk_write(fact, customer, agency_id, confidence)` in resolver.py; `_resolve_commission_match_or_park` tries the crosswalk FIRST and writes back on every ID match.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_commission_resolver.py — add (reuse the file's existing app/agency fixture;
# if it has one named differently, adapt the fixture name).
def test_grpnbr_crosswalk_links_renewal_after_seed(ctx):
    """A renewal (no MBI) with a GrpNbr already in the crosswalk resolves to that
    customer — the durable path. And an ID match WRITES the crosswalk for next time."""
    from app.extensions import db
    from app.models import Customer, CarrierIdCrosswalk
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer
    app, agency_id = ctx
    cust = Customer(agency_id=agency_id, first_name="Sandra", last_name="Agner",
                    full_name="Sandra Agner", humana_id="H73527562")
    db.session.add(cust); db.session.flush()
    # seed the crosswalk (as the seed script / a prior new-enrollment would)
    db.session.add(CarrierIdCrosswalk(agency_id=agency_id, carrier="Humana",
                   carrier_key="00019275764K", key_kind="grpnbr",
                   customer_id=cust.id, confidence="exact_id"))
    db.session.flush()
    # a renewal fact: no MBI, PID that won't match a policy, but the SAME GrpNbr
    fact = MemberFact(carrier="Humana", full_name="Sandra Agner",
                      first_name="Sandra", last_name="Agner", mbi=None,
                      carrier_member_id="591236450", member_group_key="00019275764K",
                      row_class=RowClass.RENEWAL, amount=28.91,
                      source_ref="humana::x::1")
    res = resolve_customer(fact, agency_id=agency_id, agent_id=None,
                           source="commission_import")
    assert res.customer is not None and res.customer.id == cust.id
    assert res.match_path == "crosswalk_key"

def test_mbi_match_writes_crosswalk(ctx):
    """A new-enrollment fact (has MBI) that matches by humana_id WRITES a crosswalk
    row keyed on its GrpNbr, so the member's later renewals ride it."""
    from app.extensions import db
    from app.models import Customer, CarrierIdCrosswalk
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer
    app, agency_id = ctx
    cust = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                    full_name="Eric Tillman", humana_id="6Q77JG7KE39")
    db.session.add(cust); db.session.flush()
    fact = MemberFact(carrier="Humana", full_name="Eric Tillman",
                      first_name="Eric", last_name="Tillman", mbi="6Q77JG7KE39",
                      carrier_member_id="827895454", member_group_key="00026457660K",
                      row_class=RowClass.NEW, amount=202.41, source_ref="humana::x::2")
    res = resolve_customer(fact, agency_id=agency_id, agent_id=None,
                           source="commission_import")
    assert res.customer.id == cust.id
    xw = CarrierIdCrosswalk.query.filter_by(agency_id=agency_id, carrier="Humana",
                                            carrier_key="00026457660K").first()
    assert xw is not None and xw.customer_id == cust.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_grpnbr_crosswalk_links_renewal_after_seed tests/test_commission_resolver.py::test_mbi_match_writes_crosswalk -v`
Expected: FAIL (`match_path == 'parked'`, no `crosswalk_key`; no crosswalk row written)

- [ ] **Step 3: Add the helpers + wire them in**

In `app/commission/resolver.py`, add two module-level helpers (near `_match_by_carrier_member_id`):

```python
def _crosswalk_lookup(fact: MemberFact, agency_id: int):
    """Customer for this fact's persistent carrier key (Humana GrpNbr), else None.
    no_autoflush: mirrors _crosswalk — must not autoflush a pending stub mid-import."""
    from app.models import CarrierIdCrosswalk
    key = (fact.member_group_key or "").strip()
    if not key:
        return None
    with db.session.no_autoflush:
        row = CarrierIdCrosswalk.query.filter_by(
            agency_id=agency_id, carrier=fact.carrier, carrier_key=key).first()
    return Customer.query.get(row.customer_id) if row else None


def _crosswalk_write(fact: MemberFact, customer, agency_id: int, confidence: str):
    """Upsert (carrier, GrpNbr) → customer so future renewals ride this link.
    Idempotent on the unique (agency_id, carrier, carrier_key)."""
    from app.models import CarrierIdCrosswalk
    key = (fact.member_group_key or "").strip()
    if not key or customer is None:
        return
    with db.session.no_autoflush:
        existing = CarrierIdCrosswalk.query.filter_by(
            agency_id=agency_id, carrier=fact.carrier, carrier_key=key).first()
    if existing is None:
        db.session.add(CarrierIdCrosswalk(
            agency_id=agency_id, carrier=fact.carrier, carrier_key=key,
            key_kind="grpnbr", customer_id=customer.id,
            mbi=(fact.mbi or None), confidence=confidence,
            source_note="auto:resolver"))
    elif existing.customer_id != customer.id:
        # do not silently repoint a confirmed link; leave as-is (safe)
        pass
```

In `_resolve_commission_match_or_park`, modify the `_attach` inner helper to write the crosswalk, and add the crosswalk lookup as the FIRST step. Change the `_attach` definition to record the path and write back:

```python
    def _attach(customer, match_path):
        result.customer = customer
        existing = _crosswalk(fact, agency_id)
        if existing is not None:
            existing.customer_id = existing.customer_id or customer.id
            result.policy = existing
        else:
            result.policy = _attach_policy(fact, customer, agency_id, agent_id)
            result.created_policy = True
        result.match_path = match_path
        # Every ID-based resolution (crosswalk_key, mbi, carrier_member_id) is an exact
        # deterministic match — write/refresh the crosswalk so renewals ride it.
        _crosswalk_write(fact, customer, agency_id, "exact_id")
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, customer, agency_id, agent_id, batch_id, result, source)
        return result
```

Then add the new step 0 immediately after `result = ResolveResult()` and before the existing `# 1. crosswalk` Policy step:

```python
    # 0. Persistent carrier-key crosswalk (Humana GrpNbr). The deterministic path
    #    that carries renewals (no MBI) to the member linked earlier.
    xw_customer = _crosswalk_lookup(fact, agency_id)
    if xw_customer is not None:
        return _attach(xw_customer, "crosswalk_key")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_grpnbr_crosswalk_links_renewal_after_seed tests/test_commission_resolver.py::test_mbi_match_writes_crosswalk -v`
Expected: PASS

- [ ] **Step 5: Run the full resolver suite (no regressions)**

Run: `python3 -m pytest tests/test_commission_resolver.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add app/commission/resolver.py tests/test_commission_resolver.py
git commit -m "feat: resolver GrpNbr crosswalk step + write-back (renewals ride the seeded link)"
```

---

### Task 4: read-only Humana crosswalk seed script

**Files:**
- Create: `scripts/seed_humana_crosswalk.py`
- Test: `tests/test_seed_humana_crosswalk.py`

**Interfaces:**
- Consumes: `CarrierIdCrosswalk` (Task 1), `normalize_humana` (Task 2), `_match_by_mbi` (resolver).
- Produces: `seed_from_facts(facts, agency_id, apply=False) -> dict` (counts: seeded/skipped/no_customer) — pure function over a list of `MemberFact`, so it's testable without a file. The CLI wraps it: reads Humana files (via `load_sheets`), normalizes, calls `seed_from_facts`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seed_humana_crosswalk.py
import pytest

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

def test_seed_links_mbi_bearing_facts_only(ctx):
    """Seed writes a crosswalk row ONLY for facts whose MBI matches an existing
    customer (guaranteed link). Renewal facts (no MBI) are skipped by the seed —
    they get linked at upload time via the seeded key. Never touches money tables."""
    from app.extensions import db
    from app.models import Customer, CarrierIdCrosswalk, CommissionLineItem
    from app.commission.member_fact import MemberFact, RowClass
    from scripts.seed_humana_crosswalk import seed_from_facts
    app, agency_id = ctx
    cust = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                    full_name="Eric Tillman", humana_id="6Q77JG7KE39")
    db.session.add(cust); db.session.flush()
    facts = [
        # new-enrollment: has MBI matching cust.humana_id → seed
        MemberFact(carrier="Humana", full_name="Eric Tillman", first_name="Eric",
                   last_name="Tillman", mbi="6Q77JG7KE39", carrier_member_id="827895454",
                   member_group_key="00026457660K", row_class=RowClass.NEW, amount=1.0,
                   source_ref="h::1"),
        # renewal: no MBI → skipped by seed
        MemberFact(carrier="Humana", full_name="Sandra Agner", first_name="Sandra",
                   last_name="Agner", mbi=None, carrier_member_id="591236450",
                   member_group_key="00019275764K", row_class=RowClass.RENEWAL, amount=1.0,
                   source_ref="h::2"),
    ]
    counts = seed_from_facts(facts, agency_id, apply=True)
    assert counts["seeded"] == 1
    assert counts["skipped_no_mbi_match"] == 1
    rows = CarrierIdCrosswalk.query.filter_by(agency_id=agency_id).all()
    assert len(rows) == 1 and rows[0].carrier_key == "00026457660K"
    # money tables untouched
    assert CommissionLineItem.query.count() == 0

def test_seed_dry_run_writes_nothing(ctx):
    from app.extensions import db
    from app.models import Customer, CarrierIdCrosswalk
    from app.commission.member_fact import MemberFact, RowClass
    from scripts.seed_humana_crosswalk import seed_from_facts
    app, agency_id = ctx
    cust = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                    full_name="Eric Tillman", humana_id="6Q77JG7KE39")
    db.session.add(cust); db.session.flush()
    facts = [MemberFact(carrier="Humana", full_name="Eric Tillman", first_name="Eric",
                        last_name="Tillman", mbi="6Q77JG7KE39",
                        member_group_key="00026457660K", row_class=RowClass.NEW,
                        amount=1.0, source_ref="h::1")]
    counts = seed_from_facts(facts, agency_id, apply=False)
    assert counts["seeded"] == 1               # counted
    assert CarrierIdCrosswalk.query.count() == 0   # but nothing written
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_seed_humana_crosswalk.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.seed_humana_crosswalk'`

- [ ] **Step 3: Write the seed script**

```python
# scripts/seed_humana_crosswalk.py
"""Read-only crosswalk seed for Humana. Reads raw Humana commission files, and for
every member row that carries an MBI matching an existing customer (guaranteed
link), writes a carrier_id_crosswalk row (GrpNbr↔customer↔MBI). NEVER runs the
ingest pipeline — writes ONLY carrier_id_crosswalk, so AJ's proven commission data
(amounts/splits/edits) is untouched. Renewal rows (no MBI) are skipped here; they
link at upload time via the key this seed creates.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_humana_crosswalk.py \
      --agency 1 --file "path/to/Humana.xls" [--apply]
Dry-run by default; --apply commits.
"""
import argparse
import sys

from app import create_app
from app.extensions import db
from app.models import CarrierIdCrosswalk
from app.commission.resolver import _match_by_mbi


def seed_from_facts(facts, agency_id, apply=False):
    counts = {"seeded": 0, "skipped_no_mbi_match": 0, "skipped_no_grpnbr": 0,
              "already": 0}
    for fact in facts:
        key = (fact.member_group_key or "").strip()
        if not key:
            counts["skipped_no_grpnbr"] += 1
            continue
        if not (fact.mbi or "").strip():
            counts["skipped_no_mbi_match"] += 1
            continue
        customer = _match_by_mbi(fact, agency_id)
        if customer is None:
            counts["skipped_no_mbi_match"] += 1
            continue
        existing = CarrierIdCrosswalk.query.filter_by(
            agency_id=agency_id, carrier="Humana", carrier_key=key).first()
        if existing is not None:
            counts["already"] += 1
            continue
        counts["seeded"] += 1
        if apply:
            db.session.add(CarrierIdCrosswalk(
                agency_id=agency_id, carrier="Humana", carrier_key=key,
                key_kind="grpnbr", customer_id=customer.id,
                mbi=(fact.mbi or None), confidence="exact_id",
                source_note="seed:humana"))
    if apply:
        db.session.commit()
    else:
        db.session.rollback()
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--file", action="append", required=True,
                    help="raw Humana commission file (repeatable)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_humana

    app = create_app()
    with app.app_context():
        all_facts = []
        for path in args.file:
            all_facts.extend(normalize_humana(load_sheets(path)))
        counts = seed_from_facts(all_facts, args.agency, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] Humana crosswalk seed for agency {args.agency}:")
        for k, v in counts.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_seed_humana_crosswalk.py -v`
Expected: PASS (both)

- [ ] **Step 5: Commit**

```bash
git add scripts/seed_humana_crosswalk.py tests/test_seed_humana_crosswalk.py
git commit -m "feat: read-only Humana crosswalk seed (writes only crosswalk, never ingest)"
```

---

### Task 5: legacy Humana stub cleanup script

**Files:**
- Create: `scripts/cleanup_humana_stubs.py`
- Test: `tests/test_cleanup_humana_stubs.py`

**Interfaces:**
- Consumes: `merge_customers(keeper_id, loser_ids, agency_id, actor)` (app/customers.py), `CarrierIdCrosswalk` (Task 1), `Customer`, `_match_by_mbi` (resolver).
- Produces: `plan_cleanup(agency_id) -> list[dict]` returning `{stub_id, keeper_id, grpnbr}` pairs. **Pairing predicate (definitive — do NOT depend on the seed writing stub rows):** a legacy stub (`stub=True`, `source='commission_import'`, carrier Humana via a Policy or `humana_id`) is paired to a keeper when the stub's own `humana_id` (the MBI the old importer stored there) has an active `carrier_id_crosswalk` row — i.e. that MBI's GrpNbr now resolves to a DIFFERENT real (`stub=False`) customer. Concretely: for each Humana stub, look up `_match_by_mbi`-style on the stub's `humana_id`/`mbi` against the crosswalk's `mbi` column; if a crosswalk row with that MBI points to a real customer ≠ the stub, that's the keeper. Only corroborated pairs returned; lonely stubs never listed. CLI `--apply` calls `merge_customers` for each.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cleanup_humana_stubs.py
import pytest

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

def test_plan_cleanup_pairs_stub_to_real_via_crosswalk(ctx):
    """A legacy stub whose MBI (stored in humana_id by the old importer) matches a
    crosswalk row pointing at a DIFFERENT real customer is a safe merge candidate;
    a stub whose MBI is not in the crosswalk is NOT listed."""
    from app.extensions import db
    from app.models import Customer, CarrierIdCrosswalk
    from scripts.cleanup_humana_stubs import plan_cleanup
    app, agency_id = ctx
    real = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                    full_name="Eric Tillman", humana_id="6Q77JG7KE39", stub=False)
    stub = Customer(agency_id=agency_id, first_name="Eric", last_name="Tillman",
                    full_name="Eric Tillman", humana_id="6Q77JG7KE39",
                    stub=True, source="commission_import")
    lonely = Customer(agency_id=agency_id, first_name="No", last_name="Match",
                      full_name="No Match", humana_id="ZZZ0000ZZ00",
                      stub=True, source="commission_import")
    db.session.add_all([real, stub, lonely]); db.session.flush()
    # crosswalk row carries the member's MBI and points to the REAL customer
    db.session.add(CarrierIdCrosswalk(agency_id=agency_id, carrier="Humana",
                   carrier_key="00026457660K", key_kind="grpnbr",
                   customer_id=real.id, mbi="6Q77JG7KE39", confidence="exact_id"))
    db.session.flush()
    pairs = plan_cleanup(agency_id)
    keeper_ids = {p["keeper_id"] for p in pairs}
    loser_ids = {p["stub_id"] for p in pairs}
    assert real.id in keeper_ids
    assert stub.id in loser_ids
    assert lonely.id not in loser_ids   # its MBI isn't in the crosswalk → not a candidate
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cleanup_humana_stubs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.cleanup_humana_stubs'`

- [ ] **Step 3: Write the cleanup script**

```python
# scripts/cleanup_humana_stubs.py
"""One-time cleanup: collapse legacy Humana commission stubs into their real
customer, using the carrier_id_crosswalk built by seed_humana_crosswalk.py. A stub
is merged ONLY when the crosswalk corroborates it maps to a DIFFERENT real
(stub=False) customer — lonely stubs are never touched. Uses the existing audited
merge_customers (fill-blanks-only, reattaches all children, refuses contradictions).

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/cleanup_humana_stubs.py \
      --agency 1 [--apply]
Dry-run by default.
"""
import argparse

from app import create_app
from app.extensions import db
from app.models import Customer, CarrierIdCrosswalk, User


def plan_cleanup(agency_id):
    """Return [{stub_id, keeper_id, grpnbr}] safe merges. A legacy Humana stub is
    paired to a keeper when the stub's MBI (stored in humana_id by the old importer)
    matches a Humana crosswalk row whose customer is a DIFFERENT real (stub=False)
    customer. Only corroborated pairs are returned; lonely stubs are never listed."""
    # map: MBI -> (real customer_id, GrpNbr) from crosswalk rows pointing at real customers
    real_by_mbi = {}
    for row in CarrierIdCrosswalk.query.filter_by(agency_id=agency_id, carrier="Humana"):
        if not (row.mbi or "").strip():
            continue
        cust = Customer.query.get(row.customer_id)
        if cust is not None and not cust.stub:
            real_by_mbi[row.mbi.strip()] = (cust.id, row.carrier_key)
    pairs = []
    stubs = Customer.query.filter_by(agency_id=agency_id, stub=True,
                                     source="commission_import").all()
    for stub in stubs:
        mbi = (stub.humana_id or stub.mbi or "").strip()
        if not mbi:
            continue
        hit = real_by_mbi.get(mbi)
        if hit and hit[0] != stub.id:
            pairs.append({"stub_id": stub.id, "keeper_id": hit[0], "grpnbr": hit[1]})
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        from app.customers import merge_customers
        actor = User.query.filter_by(agency_id=args.agency).first()
        pairs = plan_cleanup(args.agency)
        print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {len(pairs)} stub→real merges")
        for p in pairs:
            print(f"  stub {p['stub_id']} → keeper {p['keeper_id']} (GrpNbr {p['grpnbr']})")
            if args.apply:
                merge_customers(p["keeper_id"], [p["stub_id"]], args.agency, actor)
        if args.apply:
            db.session.commit()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cleanup_humana_stubs.py -v`
Expected: PASS (reconcile the pairing predicate with Task 4's seed output first, per the Step 1 note)

- [ ] **Step 5: Run the full commission + customers suites (no regressions)**

Run: `python3 -m pytest tests/test_commission_resolver.py tests/test_commission_normalizers.py tests/test_carrier_crosswalk.py tests/test_seed_humana_crosswalk.py tests/test_cleanup_humana_stubs.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/cleanup_humana_stubs.py tests/test_cleanup_humana_stubs.py
git commit -m "feat: one-time Humana stub cleanup via crosswalk + merge_customers (corroborated only)"
```

---

## Spec coverage notes
- **Component 4 (active-only BOB pre-filter) is NOT a task in this Humana-first plan.**
  The seed links only MBI-bearing rows, and 2,270/2,271 Humana MBI rows are ACTIVE (blank-MBI
  ⟺ inactive, proven) — so active-filtering is already implicit for the seed. An explicit
  active-filter belongs to the later carriers (BCBS/UHC/Devoted) where name+eff+plan matching
  against the BOB is used; it is deferred to that follow-on, not needed for Humana crosswalk.
- **Phase C (human-confirm merge UI)** reuses the existing `/admin/customers/duplicates` merge
  UI (shipped 2026-07-01/02); no new UI in this plan. Residual stubs not auto-cleaned by Task 5
  surface there for a human, and each confirm can later write a crosswalk row (a small follow-on).

## Post-build (controller, NOT a task — human-gated deploy)

After the whole-branch opus review passes:
1. DB backup on VPS (`pg_dump` with PGPASSWORD from .env).
2. `flask db upgrade` 033→034 on VPS; confirm head 034.
3. Deploy code; confirm `systemctl restart` cycled; login 200.
4. **Tim hands over the historical Humana files.** Run `seed_humana_crosswalk.py --dry-run` on each, review counts, then `--apply` (real Postgres).
5. Run `cleanup_humana_stubs.py --dry-run`, review the stub→real pairs WITH Tim, then `--apply`.
6. Re-check the integrity radar; ratchet `orphan_stub_customers` / `commission_import_stubs` / `duplicate_customers` baselines down by the amount cleaned.
7. Update START HERE + BACKLOG + session-handoff.
