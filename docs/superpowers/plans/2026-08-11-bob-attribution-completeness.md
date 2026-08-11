# BOB Attribution Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every BOB row either fully attributed (customer + plan) or visibly parked in a queue a human can resolve — so plan-linkage gaps stop regenerating every month.

**Architecture:** Two existing branches in `app/upload.py` that currently drop information start writing to a new `AttributionQueue` table instead. Resolution reuses existing surfaces: customer misses become a 5th category on the existing `/customers/unassigned` hub; plan misses get one new admin route modeled on the existing quarantine workbench. A shared count joins the existing `inject_counts` badge pattern, and a new integrity invariant holds the line at 0 via the CI ratchet.

**Tech Stack:** Python 3.10, Flask 3.0, Flask-SQLAlchemy, Flask-Migrate (Alembic), PostgreSQL 16 (prod) / SQLite (tests), Jinja2, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-08-11-bob-attribution-completeness-design.md`

## Global Constraints

- **Migration head is currently `042`.** The new migration MUST use `down_revision = "042"`. Keep a single linear head.
- **Every query MUST be agency-scoped** (`agency_id=...`). Missing `agency_id` is a data leak across tenants.
- **The jelly-bean rule: parsers NEVER create a `Plan`.** Only a human, via the CMS-backed create action, creates a bucket.
- **`cms_plan_id` is stored in DASH form** (`H5253-184`), never underscore. Underscore silently orphans a bucket from the sorter.
- **This feature touches `plan_id` and `customer_id` ONLY.** No money field is read or written. Ledger and payment totals must be identical to the penny before/after any backfill.
- **`Policy.plan_type` is known-unreliable** (holds carrier vocabulary). Never source a bucket's `plan_type` from it — use CMS.
- **Admin-only** for the plan queue routes: `abort(403)` before any lookup.
- Tests run with `python3 -m pytest -q` from the repo root. Suite is currently **789 passing**; it must stay green.
- Templates use existing Founders theme tokens (`var(--ivory)` for text, never `var(--ink)`).

---

### Task 1: The `AttributionQueue` model + migration 043

**Files:**
- Modify: `app/models.py` (append the model near the other queue-ish models)
- Create: `migrations/versions/043_attribution_queue.py`
- Test: `tests/test_attribution_queue.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `AttributionQueue` model with fields `id, agency_id, kind, policy_id, carrier, plan_name, plan_type, member_id, full_name, status, resolved_by_id, resolved_at, resolution_note, created_at`. Constants `KIND_NEEDS_CUSTOMER = "needs_customer"`, `KIND_NEEDS_PLAN = "needs_plan"`, `STATUS_OPEN = "open"`, `STATUS_RESOLVED = "resolved"`, `STATUS_DISMISSED = "dismissed"`. Unique constraint named `uq_attribution_queue_agency_kind_policy` on `(agency_id, kind, policy_id)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_attribution_queue.py
import pytest
from app.extensions import db
from app.models import (AttributionQueue, KIND_NEEDS_PLAN, KIND_NEEDS_CUSTOMER,
                        STATUS_OPEN)


def test_queue_row_roundtrips(app_ctx):
    q = AttributionQueue(agency_id=1, kind=KIND_NEEDS_PLAN, policy_id=101,
                         carrier="UHC", plan_name="UHC Dual Complete NC-S3",
                         status=STATUS_OPEN)
    db.session.add(q)
    db.session.commit()
    got = AttributionQueue.query.filter_by(agency_id=1, policy_id=101).one()
    assert got.kind == KIND_NEEDS_PLAN
    assert got.status == STATUS_OPEN
    assert got.created_at is not None


def test_same_policy_may_hold_both_kinds(app_ctx):
    """A row with NO customer AND no plan parks twice — deliberately."""
    db.session.add(AttributionQueue(agency_id=1, kind=KIND_NEEDS_PLAN,
                                    policy_id=202, status=STATUS_OPEN))
    db.session.add(AttributionQueue(agency_id=1, kind=KIND_NEEDS_CUSTOMER,
                                    policy_id=202, status=STATUS_OPEN))
    db.session.commit()
    assert AttributionQueue.query.filter_by(policy_id=202).count() == 2


def test_duplicate_same_kind_is_rejected(app_ctx):
    """Re-importing the same BOB must NOT pile up duplicates."""
    db.session.add(AttributionQueue(agency_id=1, kind=KIND_NEEDS_PLAN,
                                    policy_id=303, status=STATUS_OPEN))
    db.session.commit()
    db.session.add(AttributionQueue(agency_id=1, kind=KIND_NEEDS_PLAN,
                                    policy_id=303, status=STATUS_OPEN))
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()
```

Note: `app_ctx` is the existing app-context fixture in `tests/conftest.py`. If it is named differently there, use the existing name — do not add a new fixture.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_attribution_queue.py -v`
Expected: FAIL with `ImportError: cannot import name 'AttributionQueue'`

- [ ] **Step 3: Add the model**

```python
# app/models.py — append near the other operational models

KIND_NEEDS_CUSTOMER = "needs_customer"
KIND_NEEDS_PLAN = "needs_plan"
STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"
STATUS_DISMISSED = "dismissed"


class AttributionQueue(db.Model):
    """A BOB row that could not be fully attributed. Parked, never dropped.

    kind=needs_plan     -> the policy imported but find_plan_bucket missed.
    kind=needs_customer -> resolve_customer() returned no customer.

    Unique on (agency_id, kind, policy_id) so re-importing the same BOB is
    idempotent. A single policy MAY hold one row of EACH kind — that is the
    "no customer and no plan" case and must not be collapsed.
    """
    __tablename__ = "attribution_queue"
    __table_args__ = (
        db.UniqueConstraint("agency_id", "kind", "policy_id",
                            name="uq_attribution_queue_agency_kind_policy"),
    )

    id = db.Column(db.Integer, primary_key=True)
    agency_id = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False,
                          index=True)
    kind = db.Column(db.String(24), nullable=False, index=True)
    policy_id = db.Column(db.Integer, db.ForeignKey("policies.id", ondelete="CASCADE"),
                          nullable=True, index=True)
    # The raw values that failed to resolve — kept so the queue is readable
    # without re-reading the source file.
    carrier = db.Column(db.String(64))
    plan_name = db.Column(db.String(256))
    plan_type = db.Column(db.String(64))
    member_id = db.Column(db.String(64))
    full_name = db.Column(db.String(255))

    status = db.Column(db.String(16), nullable=False, default=STATUS_OPEN, index=True)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolution_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
```

- [ ] **Step 4: Create migration 043**

```python
# migrations/versions/043_attribution_queue.py
"""attribution queue for unresolved BOB rows

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
    op.create_table(
        "attribution_queue",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=True),
        sa.Column("carrier", sa.String(length=64), nullable=True),
        sa.Column("plan_name", sa.String(length=256), nullable=True),
        sa.Column("plan_type", sa.String(length=64), nullable=True),
        sa.Column("member_id", sa.String(length=64), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="open"),
        sa.Column("resolved_by_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_id", "kind", "policy_id",
                            name="uq_attribution_queue_agency_kind_policy"),
    )
    op.create_index("ix_attribution_queue_agency_id", "attribution_queue", ["agency_id"])
    op.create_index("ix_attribution_queue_kind", "attribution_queue", ["kind"])
    op.create_index("ix_attribution_queue_status", "attribution_queue", ["status"])
    op.create_index("ix_attribution_queue_policy_id", "attribution_queue", ["policy_id"])


def downgrade():
    op.drop_index("ix_attribution_queue_policy_id", table_name="attribution_queue")
    op.drop_index("ix_attribution_queue_status", table_name="attribution_queue")
    op.drop_index("ix_attribution_queue_kind", table_name="attribution_queue")
    op.drop_index("ix_attribution_queue_agency_id", table_name="attribution_queue")
    op.drop_table("attribution_queue")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_attribution_queue.py -v`
Expected: 3 PASS

- [ ] **Step 6: Verify the migration head stays linear**

Run: `python3 -c "import re,glob;;[print(f) for f in glob.glob('migrations/versions/*043*')]"`
Then confirm no OTHER migration already claims `down_revision = "042"`:
Run: `grep -l 'down_revision = "042"' migrations/versions/*.py`
Expected: exactly one file — the new `043_attribution_queue.py`

- [ ] **Step 7: Commit**

```bash
git add app/models.py migrations/versions/043_attribution_queue.py tests/test_attribution_queue.py
git commit -m "feat: AttributionQueue model + migration 043"
```

---

### Task 2: The enqueue seam (`app/attribution_queue.py`)

**Files:**
- Create: `app/attribution_queue.py`
- Test: `tests/test_attribution_queue.py` (append)

**Note:** `app/attribution.py` ALREADY EXISTS (it is the writing-ID→agent resolver). Do NOT overwrite it. The new module is `app/attribution_queue.py`.

**Interfaces:**
- Consumes: `AttributionQueue`, `KIND_NEEDS_PLAN`, `KIND_NEEDS_CUSTOMER`, `STATUS_OPEN` from Task 1.
- Produces:
  - `enqueue(agency_id, kind, *, policy_id=None, carrier=None, plan_name=None, plan_type=None, member_id=None, full_name=None) -> bool` — returns True if a new row was parked, False if one already existed. **Never raises into the caller.**
  - `open_count(agency_id) -> int` — total open rows across both kinds.
  - `open_counts_by_kind(agency_id) -> dict` — e.g. `{"needs_plan": 7, "needs_customer": 2}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_attribution_queue.py — append
from app.attribution_queue import enqueue, open_count, open_counts_by_kind


def test_enqueue_is_idempotent(app_ctx):
    assert enqueue(1, KIND_NEEDS_PLAN, policy_id=501, carrier="UHC",
                   plan_name="Some Plan") is True
    assert enqueue(1, KIND_NEEDS_PLAN, policy_id=501, carrier="UHC",
                   plan_name="Some Plan") is False
    assert AttributionQueue.query.filter_by(policy_id=501).count() == 1


def test_enqueue_never_raises_into_caller(app_ctx):
    """A queue failure must never break an import mid-batch."""
    assert enqueue(None, "bogus_kind", policy_id=None) is False


def test_counts(app_ctx):
    enqueue(1, KIND_NEEDS_PLAN, policy_id=601, plan_name="P")
    enqueue(1, KIND_NEEDS_CUSTOMER, policy_id=602, full_name="Jane Doe")
    assert open_count(1) == 2
    assert open_counts_by_kind(1) == {KIND_NEEDS_PLAN: 1, KIND_NEEDS_CUSTOMER: 1}
    assert open_count(2) == 0          # agency-scoped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_attribution_queue.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.attribution_queue'`

- [ ] **Step 3: Write the implementation**

```python
# app/attribution_queue.py
"""Park BOB rows that could not be fully attributed.

WHY: a plan-bucket miss used to append to a local list and emit a log summary
(app/upload.py:1081 — "do not pollute the quarantine modal, just log a summary").
A log line nobody reads is how 4,656 plan_id orphans accumulated. This module is
the durable replacement: a miss is PARKED, visible, and resolvable.

DEFENSIVE BY DESIGN: enqueue() never raises into its caller. It runs inside a BOB
import loop; a queue failure must never abort an import that is otherwise correct.
"""
from datetime import datetime

from flask import current_app

from app.extensions import db
from app.models import (AttributionQueue, KIND_NEEDS_CUSTOMER, KIND_NEEDS_PLAN,
                        STATUS_OPEN, STATUS_RESOLVED)

_VALID_KINDS = {KIND_NEEDS_CUSTOMER, KIND_NEEDS_PLAN}


def enqueue(agency_id, kind, *, policy_id=None, carrier=None, plan_name=None,
            plan_type=None, member_id=None, full_name=None) -> bool:
    """Park one unresolved row. True if newly parked, False if already queued
    or the call was invalid. NEVER raises into the caller."""
    if not agency_id or kind not in _VALID_KINDS:
        return False
    try:
        existing = AttributionQueue.query.filter_by(
            agency_id=agency_id, kind=kind, policy_id=policy_id,
            status=STATUS_OPEN).first()
        if existing is not None:
            return False
        db.session.add(AttributionQueue(
            agency_id=agency_id, kind=kind, policy_id=policy_id, carrier=carrier,
            plan_name=(plan_name or None), plan_type=(plan_type or None),
            member_id=(member_id or None), full_name=(full_name or None),
            status=STATUS_OPEN))
        db.session.flush()
        return True
    except Exception:                                    # noqa: BLE001
        db.session.rollback()
        try:
            current_app.logger.warning("attribution enqueue failed", exc_info=True)
        except Exception:                                # noqa: BLE001
            pass
        return False


def open_count(agency_id) -> int:
    """Total open (unresolved) queue rows for one agency. Never raises."""
    try:
        return AttributionQueue.query.filter_by(
            agency_id=agency_id, status=STATUS_OPEN).count()
    except Exception:                                    # noqa: BLE001
        return 0


def open_counts_by_kind(agency_id) -> dict:
    """{kind: count} of open rows for one agency. Never raises."""
    try:
        rows = (db.session.query(AttributionQueue.kind,
                                 db.func.count(AttributionQueue.id))
                .filter(AttributionQueue.agency_id == agency_id,
                        AttributionQueue.status == STATUS_OPEN)
                .group_by(AttributionQueue.kind).all())
        return {k: n for k, n in rows}
    except Exception:                                    # noqa: BLE001
        return {}


def resolve(entry_id, agency_id, user_id, note) -> bool:
    """Mark one queue row resolved. Agency-scoped. Never raises."""
    try:
        e = AttributionQueue.query.filter_by(id=entry_id, agency_id=agency_id).first()
        if e is None:
            return False
        e.status = STATUS_RESOLVED
        e.resolved_by_id = user_id
        e.resolved_at = datetime.utcnow()
        e.resolution_note = note
        return True
    except Exception:                                    # noqa: BLE001
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_attribution_queue.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add app/attribution_queue.py tests/test_attribution_queue.py
git commit -m "feat: attribution queue enqueue/count seam"
```

---

### Task 3: Wire the two dropping branches in `app/upload.py`

**Files:**
- Modify: `app/upload.py:255-257` (the plan-miss branch), `app/upload.py:360-362` (the customer-miss branch), and `app/upload.py:1081-1090` (delete the log-only summary)
- Test: `tests/test_bob_attribution_wiring.py`

**Interfaces:**
- Consumes: `enqueue`, `KIND_NEEDS_PLAN`, `KIND_NEEDS_CUSTOMER` from Task 2.
- Produces: no new public API. After this task, a BOB import with an unmatchable plan leaves exactly one `needs_plan` row.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bob_attribution_wiring.py
from app.extensions import db
from app.models import AttributionQueue, KIND_NEEDS_PLAN, STATUS_OPEN
from app.upload import _import_bob_row


def _rec(**over):
    base = {"carrier": "UHC", "member_id": "9ZZ9ZZ9ZZ99", "mbi": "9ZZ9ZZ9ZZ99",
            "first_name": "Test", "last_name": "Member",
            "full_name": "Test Member", "plan_name": "Totally Unknown Plan XYZ",
            "plan_type": "MAPD", "effective_date": None, "term_date": None,
            "dob": None, "phone": None, "county": None, "status": "active"}
    base.update(over)
    return base


def test_plan_miss_parks_one_row(app_ctx, bob_batch):
    """A plan the sorter cannot match must be PARKED, not just logged."""
    _import_bob_row(_rec(), bob_batch, 1, None, None, [], plan_year=2026,
                    plan_review=[])
    db.session.commit()
    rows = AttributionQueue.query.filter_by(kind=KIND_NEEDS_PLAN,
                                            status=STATUS_OPEN).all()
    assert len(rows) == 1
    assert rows[0].plan_name == "Totally Unknown Plan XYZ"
    assert rows[0].carrier == "UHC"


def test_reimport_does_not_duplicate(app_ctx, bob_batch):
    """Re-uploading the same BOB must not pile up queue rows."""
    for _ in range(2):
        _import_bob_row(_rec(), bob_batch, 1, None, None, [], plan_year=2026,
                        plan_review=[])
        db.session.commit()
    assert AttributionQueue.query.filter_by(kind=KIND_NEEDS_PLAN).count() == 1
```

`bob_batch` is a fixture creating an `ImportBatch` for agency 1 — add it to
`tests/conftest.py` if an equivalent does not already exist:

```python
@pytest.fixture
def bob_batch(app_ctx):
    from app.models import ImportBatch
    b = ImportBatch(agency_id=1, carrier="UHC", filename="test.xlsx", status="pending")
    db.session.add(b)
    db.session.commit()
    return b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bob_attribution_wiring.py -v`
Expected: FAIL — `assert len(rows) == 1` gets `0` (the miss is currently only logged)

- [ ] **Step 3: Park the plan miss**

Replace the plan-miss branch at `app/upload.py:255-257`:

```python
    from app.plan_bucket import find_plan_bucket
    _b = find_plan_bucket(rec["carrier"], rec, plan_year, bulk_agency_id)
    if _b["plan_id"] is None and rec.get("plan_name") and plan_review is not None:
        plan_review.append({"carrier": rec["carrier"], "plan_name": rec.get("plan_name"),
                            "plan_type": rec.get("plan_type")})
```

with:

```python
    from app.plan_bucket import find_plan_bucket
    _b = find_plan_bucket(rec["carrier"], rec, plan_year, bulk_agency_id)
    if _b["plan_id"] is None and plan_review is not None:
        # Keep the in-memory list for the upload flash summary, AND park the miss
        # durably. The old behaviour was log-only, which is how plan_id orphans
        # accumulated invisibly. Parked AFTER the policy exists (below) so we can
        # attach policy_id — see the enqueue call after the upsert.
        plan_review.append({"carrier": rec["carrier"], "plan_name": rec.get("plan_name"),
                            "plan_type": rec.get("plan_type")})
```

Then, immediately AFTER the policy has been created/updated and flushed (after the
`if existing:` / `else:` block completes and `policy` has an id — locate the point
where `_upsert_customer_from_policy` is called at `app/upload.py:342` and insert
BEFORE it):

```python
    # Park an unmatched plan bucket against the now-existing policy.
    if _b["plan_id"] is None:
        from app.attribution_queue import enqueue
        from app.models import KIND_NEEDS_PLAN
        _pid = existing.id if existing is not None else (policy.id if policy else None)
        enqueue(bulk_agency_id, KIND_NEEDS_PLAN, policy_id=_pid,
                carrier=rec.get("carrier"), plan_name=rec.get("plan_name"),
                plan_type=rec.get("plan_type"), member_id=rec.get("member_id"),
                full_name=rec.get("full_name"))
```

**Implementer note:** read the surrounding 40 lines first. The local variable holding
the just-written Policy may be named `existing` (update path) or a new local (create
path). Use whichever the code actually binds; do not invent a name.

- [ ] **Step 4: Park the customer miss**

At `app/upload.py:360-362`, replace:

```python
    customer = result.customer
    if customer is None:
        return
```

with:

```python
    customer = result.customer
    if customer is None:
        # The resolver could not produce a customer. Previously this returned
        # silently, leaving the policy with customer_id NULL and no trace — the
        # class that orphaned 2,182 + 505 policies in July 2026. Park it.
        from app.attribution_queue import enqueue
        from app.models import KIND_NEEDS_CUSTOMER
        enqueue(agency_id, KIND_NEEDS_CUSTOMER,
                policy_id=(result.policy.id if result.policy else None),
                carrier=rec.get("carrier"), member_id=rec.get("member_id"),
                full_name=rec.get("full_name"))
        return
```

- [ ] **Step 5: Replace the log-only summary**

At `app/upload.py:1081-1090`, replace the comment and log block with:

```python
        # Plan-bucket misses are now PARKED in the attribution queue (see
        # app/attribution_queue.py), not merely logged. The summary log stays for
        # operator visibility during an upload; the queue is the durable record.
        if plan_review:
            current_app.logger.info(
                "BOB import: %d rows had no matching plan bucket (parked in the "
                "attribution queue for resolution): %s" % (
                    len(plan_review),
                    ", ".join(sorted({r["plan_name"] or "(blank)" for r in plan_review}))))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_bob_attribution_wiring.py -v`
Expected: 2 PASS

- [ ] **Step 7: Run the FULL suite — this task edits a hot path**

Run: `python3 -m pytest -q`
Expected: 789+ passed, 0 failed

- [ ] **Step 8: Commit**

```bash
git add app/upload.py tests/test_bob_attribution_wiring.py tests/conftest.py
git commit -m "feat: park BOB plan and customer misses instead of dropping them"
```

---

### Task 4: CMS Landscape lookup helper

**Files:**
- Create: `app/cms_lookup.py`
- Test: `tests/test_cms_lookup.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `search_cms_plans(query, *, limit=20) -> list[dict]`, each dict having keys `cms_plan_id` (DASH form), `plan_name`, `plan_type` (one of `mapd|ma|pdp|medigap|dvh`), `carrier`, `states` (sorted list of state abbreviations), `contract`, `pbp`. Used by Task 6's create action.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cms_lookup.py
from app.cms_lookup import search_cms_plans, _cms_type_to_bucket_type


def test_type_mapping_is_cms_sourced():
    """MA-PD means DRUG COVERAGE. Getting this wrong mis-files members."""
    assert _cms_type_to_bucket_type("MA-PD") == "mapd"
    assert _cms_type_to_bucket_type("MA") == "ma"
    assert _cms_type_to_bucket_type("PDP") == "pdp"
    assert _cms_type_to_bucket_type("SNP") == "mapd"       # SNPs carry drug
    assert _cms_type_to_bucket_type("") == ""


def test_search_by_contract_pbp(tmp_path):
    csv = tmp_path / "landscape.csv"
    csv.write_text(
        "Contract Year,Contract Category Type,US Territory,State Territory Abbreviation,"
        "State Territory Name,County Name,Contract ID,Plan ID,Segment ID,ContractPlanID,"
        "ContractPlanSegmentID,Sanctioned Plan,Parent Organization Name,Contract Name,"
        "Organization Marketing Name,Organization Type,Plan Name,Plan Type\n"
        "2026,MA-PD,No,SC,South Carolina,Abbeville,H5619,152,0,H5619_152,H5619_152_0,No,"
        "Humana Inc.,ARCADIAN,Humana,Local CCP,Humana Gold Plus H5619-152 (HMO),HMO\n")
    out = search_cms_plans("H5619-152", path=str(csv))
    assert len(out) == 1
    assert out[0]["cms_plan_id"] == "H5619-152"        # DASH form, never underscore
    assert out[0]["plan_type"] == "mapd"               # from CMS, not from a policy
    assert out[0]["carrier"] == "Humana"
    assert out[0]["states"] == ["SC"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cms_lookup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.cms_lookup'`

- [ ] **Step 3: Write the implementation**

```python
# app/cms_lookup.py
"""Search the CMS CY2026 Landscape file for a plan, so a human creating a bucket
confirms a REAL plan instead of typing one into existence.

WHY CMS AND NOT THE POLICY: Policy.plan_type holds CARRIER vocabulary, not portal
vocabulary — UHC/Humana/HealthSpring parsers copy the carrier's `product` column, so
~94% of UHC actives read "MA" when only ~15 are truly MA-only. Sourcing a new
bucket's type from a policy would bake that parser bug into an authoritative-looking
record. CMS is the authority for what a plan IS.
"""
import csv
import os
from collections import defaultdict

DEFAULT_PATH = ("docs/Medicare Landscape Files/CY2026_Landscape_202603/"
                "CY2026_Landscape_202603.csv")

_ORG_TO_CARRIER = {
    "humana": "Humana", "unitedhealthcare": "UHC", "aetna medicare": "Aetna",
    "aetna": "Aetna", "blue cross and blue shield of north carolina": "BCBS",
    "healthspring": "Healthspring", "cigna": "Healthspring",
    "devoted health": "Devoted",
}


def _cms_type_to_bucket_type(cms_type: str) -> str:
    t = (cms_type or "").strip().upper()
    if t == "MA-PD":
        return "mapd"
    if t == "MA":
        return "ma"
    if t == "PDP":
        return "pdp"
    if t == "SNP":
        return "mapd"          # SNPs (D-SNP/C-SNP) always carry drug coverage
    return ""


def _carrier_of(org: str) -> str:
    o = (org or "").strip().lower()
    for key, label in _ORG_TO_CARRIER.items():
        if key in o:
            return label
    return (org or "").strip()


def search_cms_plans(query, *, limit=20, path=None):
    """Find plans whose CMS id or name matches `query`. Returns one dict per plan
    (deduped across the many county rows), with states aggregated."""
    q = (query or "").strip().upper()
    if not q:
        return []
    q_us = q.replace("-", "_")
    src = path or DEFAULT_PATH
    if not os.path.exists(src):
        return []
    agg = {}
    states = defaultdict(set)
    with open(src, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            cpid = (row.get("ContractPlanID") or "").strip().upper()
            name = (row.get("Plan Name") or "").strip()
            if not cpid:
                continue
            if q_us not in cpid and q not in name.upper():
                continue
            dash = cpid.replace("_", "-")
            states[dash].add((row.get("State Territory Abbreviation") or "").strip())
            if dash not in agg:
                agg[dash] = {
                    "cms_plan_id": dash,
                    "plan_name": name or dash,
                    "plan_type": _cms_type_to_bucket_type(
                        row.get("Contract Category Type")),
                    "carrier": _carrier_of(row.get("Organization Marketing Name")
                                           or row.get("Parent Organization Name")),
                    "contract": (row.get("Contract ID") or "").strip(),
                    "pbp": (row.get("Plan ID") or "").strip(),
                }
            if len(agg) >= limit and dash not in agg:
                break
    out = []
    for dash, rec in list(agg.items())[:limit]:
        rec["states"] = sorted(s for s in states[dash] if s)
        out.append(rec)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cms_lookup.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add app/cms_lookup.py tests/test_cms_lookup.py
git commit -m "feat: CMS Landscape lookup for human-confirmed bucket creation"
```

---

### Task 5: Customer misses become the 5th hub category

**Files:**
- Modify: `app/customers.py:1513-1554` (the `customers_unassigned` view)
- Modify: `app/templates/customers_unassigned.html` (add the tab + rows)
- Test: `tests/test_unassigned_unlinked_category.py`

**Interfaces:**
- Consumes: `AttributionQueue`, `KIND_NEEDS_CUSTOMER`, `STATUS_OPEN` from Task 1.
- Produces: `/customers/unassigned?cat=unlinked` listing open `needs_customer` rows. No new route.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_unassigned_unlinked_category.py
from app.extensions import db
from app.models import AttributionQueue, KIND_NEEDS_CUSTOMER, STATUS_OPEN


def test_unlinked_category_lists_parked_rows(admin_client, app_ctx):
    db.session.add(AttributionQueue(agency_id=1, kind=KIND_NEEDS_CUSTOMER,
                                    policy_id=None, carrier="UHC",
                                    full_name="Parked Person", status=STATUS_OPEN))
    db.session.commit()
    resp = admin_client.get("/customers/unassigned?cat=unlinked")
    assert resp.status_code == 200
    assert b"Parked Person" in resp.data


def test_unlinked_category_is_agency_scoped(admin_client, app_ctx):
    db.session.add(AttributionQueue(agency_id=999, kind=KIND_NEEDS_CUSTOMER,
                                    full_name="Other Agency Person",
                                    status=STATUS_OPEN))
    db.session.commit()
    resp = admin_client.get("/customers/unassigned?cat=unlinked")
    assert b"Other Agency Person" not in resp.data
```

`admin_client` is the existing logged-in-admin test client fixture. Use the existing
fixture name from `tests/conftest.py`; do not create a new one.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_unassigned_unlinked_category.py -v`
Expected: FAIL — `Parked Person` not in the response (the category does not exist)

- [ ] **Step 3: Add the category to the view**

In `app/customers.py`, inside `customers_unassigned`, after the existing
`elif cat == "interval":` branch, add:

```python
    elif cat == "unlinked":
        from app.models import AttributionQueue, KIND_NEEDS_CUSTOMER, STATUS_OPEN
        items = (AttributionQueue.query
                 .filter_by(agency_id=current_user.agency_id,
                            kind=KIND_NEEDS_CUSTOMER, status=STATUS_OPEN)
                 .order_by(AttributionQueue.created_at.desc())
                 .limit(500).all())
```

And add its count alongside the existing `counts` dict entries:

```python
    counts["unlinked"] = (AttributionQueue.query
                          .filter_by(agency_id=current_user.agency_id,
                                     kind=KIND_NEEDS_CUSTOMER,
                                     status=STATUS_OPEN).count())
```

**Implementer note:** read the existing `counts` construction first and match its
style exactly (it may build all counts in one place).

- [ ] **Step 4: Add the tab + row rendering to the template**

In `app/templates/customers_unassigned.html`, add a tab link beside the existing four:

```html
<a class="tab {{ 'active' if cat == 'unlinked' else '' }}"
   href="{{ url_for('customers.customers_unassigned', cat='unlinked') }}">
  Unlinked BOB rows {% if counts.unlinked %}({{ counts.unlinked }}){% endif %}
</a>
```

And a rows block guarded by `{% if cat == 'unlinked' %}`:

```html
{% if cat == 'unlinked' %}
<table class="data-table">
  <thead><tr><th>Name</th><th>Carrier</th><th>Member ID</th><th>Parked</th></tr></thead>
  <tbody>
  {% for e in items %}
    <tr>
      <td style="color:var(--ivory)">{{ e.full_name or '—' }}</td>
      <td>{{ e.carrier or '—' }}</td>
      <td>{{ e.member_id or '—' }}</td>
      <td>{{ e.created_at.strftime('%Y-%m-%d') if e.created_at else '—' }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_unassigned_unlinked_category.py -v`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add app/customers.py app/templates/customers_unassigned.html tests/test_unassigned_unlinked_category.py
git commit -m "feat: 5th 'unlinked' category on the unassigned hub"
```

---

### Task 6: The plan-link queue route + template

**Files:**
- Create: `app/plan_queue.py` (blueprint `plan_queue_bp`)
- Create: `app/templates/plan_queue.html`
- Modify: `app/__init__.py` (register the blueprint, 3-line pattern)
- Modify: `app/templates/base.html` (admin nav link)
- Test: `tests/test_plan_queue.py`

**Interfaces:**
- Consumes: `AttributionQueue`/`KIND_NEEDS_PLAN`/`STATUS_OPEN` (Task 1), `enqueue`/`resolve`/`open_counts_by_kind` (Task 2), `search_cms_plans` (Task 4).
- Produces: routes `GET /admin/plan-queue`, `POST /admin/plan-queue/map`, `POST /admin/plan-queue/create`. All admin-only.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_queue.py
from app.extensions import db
from app.models import (AttributionQueue, Plan, Policy, KIND_NEEDS_PLAN,
                        STATUS_OPEN, STATUS_RESOLVED)


def test_queue_requires_admin(agent_client, app_ctx):
    assert agent_client.get("/admin/plan-queue").status_code in (302, 403)


def test_map_links_policy_and_writes_alias(admin_client, app_ctx):
    """Mapping must ALSO teach the sorter, so the same name never re-queues."""
    plan = Plan(agency_id=1, carrier="UHC", cms_plan_id="H5253-184", year=2026,
                plan_name="Dual Complete NC-S3 D-SNP", plan_type="mapd",
                status="current", needs_review=False)
    pol = Policy(agency_id=1, carrier="UHC", member_id="1AA1AA1AA11",
                 status="active", plan_name="UHC Dual Complete NC-S3")
    db.session.add_all([plan, pol])
    db.session.commit()
    e = AttributionQueue(agency_id=1, kind=KIND_NEEDS_PLAN, policy_id=pol.id,
                         carrier="UHC", plan_name="UHC Dual Complete NC-S3",
                         status=STATUS_OPEN)
    db.session.add(e)
    db.session.commit()

    resp = admin_client.post("/admin/plan-queue/map",
                             data={"entry_id": e.id, "plan_id": plan.id},
                             follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(pol); db.session.refresh(plan); db.session.refresh(e)
    assert pol.plan_id == plan.id
    assert e.status == STATUS_RESOLVED
    assert "uhc dual complete nc-s3" in (plan.plan_name_aliases or "").lower()


def test_map_never_overwrites_an_existing_link(admin_client, app_ctx):
    plan_a = Plan(agency_id=1, carrier="UHC", cms_plan_id="H5253-117", year=2026,
                  plan_name="A", plan_type="mapd", status="current",
                  needs_review=False)
    plan_b = Plan(agency_id=1, carrier="UHC", cms_plan_id="H5253-037", year=2026,
                  plan_name="B", plan_type="mapd", status="current",
                  needs_review=False)
    db.session.add_all([plan_a, plan_b]); db.session.commit()
    pol = Policy(agency_id=1, carrier="UHC", member_id="2BB2BB2BB22",
                 status="active", plan_id=plan_a.id)
    db.session.add(pol); db.session.commit()
    e = AttributionQueue(agency_id=1, kind=KIND_NEEDS_PLAN, policy_id=pol.id,
                         carrier="UHC", plan_name="X", status=STATUS_OPEN)
    db.session.add(e); db.session.commit()

    admin_client.post("/admin/plan-queue/map",
                      data={"entry_id": e.id, "plan_id": plan_b.id},
                      follow_redirects=True)
    db.session.refresh(pol)
    assert pol.plan_id == plan_a.id          # unchanged — never overwrite
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_plan_queue.py -v`
Expected: FAIL with 404 (routes do not exist)

- [ ] **Step 3: Write the blueprint**

```python
# app/plan_queue.py
"""Admin queue for BOB rows whose plan bucket could not be resolved.

Two actions, both human-confirmed:
  MAP    — link to an EXISTING bucket, and append the failed string to
           Plan.plan_name_aliases so the sorter learns it and the same name never
           re-queues. This is what makes the queue CONVERGE rather than regenerate.
  CREATE — seed a bucket from the CMS Landscape file (never free-text), then link.

NEVER overwrites an existing Policy.plan_id — a wrong link is invisible (money still
ties) and sticky.
"""
from datetime import datetime

from flask import (Blueprint, flash, redirect, render_template, request, url_for,
                   abort)
from flask_login import current_user, login_required

from app.attribution_queue import resolve
from app.cms_lookup import search_cms_plans
from app.extensions import db
from app.models import (AttributionQueue, Plan, Policy, KIND_NEEDS_PLAN,
                        STATUS_OPEN, STATUS_RESOLVED)

plan_queue_bp = Blueprint("plan_queue", __name__)


def _admin_only():
    if not current_user.is_admin:
        abort(403)


@plan_queue_bp.route("/admin/plan-queue")
@login_required
def plan_queue():
    _admin_only()
    agency_id = current_user.agency_id
    entries = (AttributionQueue.query
               .filter_by(agency_id=agency_id, kind=KIND_NEEDS_PLAN,
                          status=STATUS_OPEN)
               .order_by(AttributionQueue.carrier, AttributionQueue.plan_name)
               .all())
    # Group by (carrier, plan_name): one DECISION per distinct plan name, not one
    # per policy. 40 rows on the same unknown plan is one thing to resolve.
    groups = {}
    for e in entries:
        groups.setdefault((e.carrier or "", e.plan_name or "(blank)"), []).append(e)
    buckets = (Plan.query.filter_by(agency_id=agency_id)
               .order_by(Plan.carrier, Plan.plan_name).all())
    cms_results = []
    q = (request.args.get("cms_q") or "").strip()
    if q:
        cms_results = search_cms_plans(q)
    return render_template("plan_queue.html", groups=groups, buckets=buckets,
                           cms_results=cms_results, cms_q=q)


@plan_queue_bp.route("/admin/plan-queue/map", methods=["POST"])
@login_required
def plan_queue_map():
    _admin_only()
    agency_id = current_user.agency_id
    entry_id = int(request.form.get("entry_id") or 0)
    plan_id = int(request.form.get("plan_id") or 0)
    entry = AttributionQueue.query.filter_by(id=entry_id, agency_id=agency_id).first()
    plan = Plan.query.filter_by(id=plan_id, agency_id=agency_id).first()
    if entry is None or plan is None:
        flash("Queue entry or plan not found.", "error")
        return redirect(url_for("plan_queue.plan_queue"))

    linked = _link_group(entry, plan, agency_id)
    _learn_alias(plan, entry.plan_name)
    resolve(entry.id, agency_id, current_user.id,
            f"mapped to plan {plan.id} ({plan.cms_plan_id or plan.plan_name})")
    db.session.commit()
    flash(f"Linked {linked} polic{'y' if linked == 1 else 'ies'} to "
          f"{plan.plan_name}.", "success")
    return redirect(url_for("plan_queue.plan_queue"))


@plan_queue_bp.route("/admin/plan-queue/create", methods=["POST"])
@login_required
def plan_queue_create():
    _admin_only()
    agency_id = current_user.agency_id
    entry_id = int(request.form.get("entry_id") or 0)
    cms_id = (request.form.get("cms_plan_id") or "").strip().upper().replace("_", "-")
    entry = AttributionQueue.query.filter_by(id=entry_id, agency_id=agency_id).first()
    if entry is None or not cms_id:
        flash("Queue entry or CMS plan not specified.", "error")
        return redirect(url_for("plan_queue.plan_queue"))

    hits = search_cms_plans(cms_id)
    match = next((h for h in hits if h["cms_plan_id"] == cms_id), None)
    if match is None:
        flash(f"{cms_id} not found in the CMS Landscape file.", "error")
        return redirect(url_for("plan_queue.plan_queue"))

    plan = Plan.query.filter_by(agency_id=agency_id, carrier=match["carrier"],
                                cms_plan_id=cms_id, year=2026).first()
    if plan is None:
        plan = Plan(agency_id=agency_id, carrier=match["carrier"],
                    cms_plan_id=cms_id, year=2026,
                    plan_name=match["plan_name"],
                    plan_type=match["plan_type"],     # CMS, never Policy.plan_type
                    status="current", needs_review=False)
        db.session.add(plan)
        db.session.flush()

    linked = _link_group(entry, plan, agency_id)
    _learn_alias(plan, entry.plan_name)
    resolve(entry.id, agency_id, current_user.id,
            f"created bucket {cms_id} from CMS and linked")
    db.session.commit()
    flash(f"Created {cms_id} and linked {linked} polic"
          f"{'y' if linked == 1 else 'ies'}.", "success")
    return redirect(url_for("plan_queue.plan_queue"))


def _link_group(entry, plan, agency_id) -> int:
    """Link every OPEN queue row sharing this (carrier, plan_name) — one human
    decision resolves all of them. NEVER overwrites an existing plan_id."""
    siblings = (AttributionQueue.query
                .filter_by(agency_id=agency_id, kind=KIND_NEEDS_PLAN,
                           status=STATUS_OPEN, carrier=entry.carrier,
                           plan_name=entry.plan_name).all())
    n = 0
    for s in siblings:
        if not s.policy_id:
            continue
        pol = Policy.query.filter_by(id=s.policy_id, agency_id=agency_id).first()
        if pol is None or pol.plan_id is not None:
            continue                      # SAFETY: never overwrite an existing link
        pol.plan_id = plan.id
        if not (pol.plan_name or "").strip():
            pol.plan_name = plan.plan_name
        n += 1
        if s.id != entry.id:
            s.status = STATUS_RESOLVED
            s.resolved_by_id = current_user.id
            s.resolved_at = datetime.utcnow()
            s.resolution_note = f"resolved with sibling entry {entry.id}"
    return n


def _learn_alias(plan, failed_name):
    """Teach the sorter the string that missed, so it self-heals next import."""
    nm = (failed_name or "").strip()
    if not nm:
        return
    existing = [a.strip() for a in (plan.plan_name_aliases or "").split(",")
                if a.strip()]
    if nm.lower() in {a.lower() for a in existing}:
        return
    if (plan.plan_name or "").strip().lower() == nm.lower():
        return
    existing.append(nm)
    plan.plan_name_aliases = ",".join(existing)
```

- [ ] **Step 4: Write the template**

```html
<!-- app/templates/plan_queue.html -->
{% extends "base.html" %}
{% block title %}Plan Link Queue{% endblock %}
{% block content %}
<div class="card">
  <h1 style="color:var(--ivory-bright)">Plan Link Queue</h1>
  <p style="color:var(--slate)">
    BOB rows whose plan could not be matched to a bucket. Resolving one name links
    every policy sharing it.
  </p>

  {% if not groups %}
    <p style="color:var(--green)">Nothing queued — every BOB row is attributed.</p>
  {% endif %}

  {% for (carrier, plan_name), entries in groups.items() %}
  <div class="card" style="margin-top:12px">
    <strong style="color:var(--ivory)">{{ carrier }} — {{ plan_name }}</strong>
    <span class="badge">{{ entries|length }} polic{{ 'y' if entries|length == 1 else 'ies' }}</span>

    <form method="POST" action="{{ url_for('plan_queue.plan_queue_map') }}"
          style="margin-top:8px">
      <input type="hidden" name="entry_id" value="{{ entries[0].id }}">
      <select name="plan_id" required>
        <option value="">— map to an existing bucket —</option>
        {% for b in buckets if b.carrier == carrier %}
          <option value="{{ b.id }}">{{ b.cms_plan_id or '—' }} · {{ b.plan_name }}</option>
        {% endfor %}
      </select>
      <button class="btn-primary" type="submit">Map</button>
    </form>

    <form method="POST" action="{{ url_for('plan_queue.plan_queue_create') }}"
          style="margin-top:8px">
      <input type="hidden" name="entry_id" value="{{ entries[0].id }}">
      <input type="text" name="cms_plan_id" placeholder="CMS id e.g. H5619-152" required>
      <button class="btn-secondary" type="submit">Create from CMS</button>
    </form>
  </div>
  {% endfor %}

  <form method="GET" style="margin-top:16px">
    <input type="text" name="cms_q" value="{{ cms_q }}" placeholder="Search CMS plans…">
    <button class="btn-secondary" type="submit">Search CMS</button>
  </form>
  {% if cms_results %}
  <table class="data-table">
    <thead><tr><th>CMS ID</th><th>Name</th><th>Type</th><th>Carrier</th><th>States</th></tr></thead>
    <tbody>
    {% for r in cms_results %}
      <tr><td>{{ r.cms_plan_id }}</td><td style="color:var(--ivory)">{{ r.plan_name }}</td>
          <td>{{ r.plan_type }}</td><td>{{ r.carrier }}</td>
          <td>{{ r.states|join(', ') }}</td></tr>
    {% endfor %}
    </tbody>
  </table>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 5: Register the blueprint and add the nav link**

In `app/__init__.py`, using the exact 3-line pattern:

```python
    from app.plan_queue import plan_queue_bp
    app.register_blueprint(plan_queue_bp)
```

In `app/templates/base.html`, inside the existing admin-only nav section:

```html
<a class="nav-item" href="{{ url_for('plan_queue.plan_queue') }}">Plan Link Queue</a>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_plan_queue.py -v`
Expected: 3 PASS

- [ ] **Step 7: Commit**

```bash
git add app/plan_queue.py app/templates/plan_queue.html app/__init__.py app/templates/base.html tests/test_plan_queue.py
git commit -m "feat: plan link queue with map-to-bucket and create-from-CMS"
```

---

### Task 7: Shared badge count + integrity invariant

**Files:**
- Modify: `app/__init__.py` (the `inject_counts` context processor)
- Modify: `app/integrity.py` (new invariant)
- Modify: `integrity_baseline.json`
- Test: `tests/test_attribution_invariant.py`

**Interfaces:**
- Consumes: `open_count` from Task 2, `AttributionQueue` from Task 1.
- Produces: template global `attribution_queue_count`; invariant named `unattributed_bob_rows`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_attribution_invariant.py
from app.extensions import db
from app.models import AttributionQueue, KIND_NEEDS_PLAN, STATUS_OPEN


def test_invariant_counts_open_rows(app_ctx):
    from app.integrity import run_invariant
    db.session.add(AttributionQueue(agency_id=1, kind=KIND_NEEDS_PLAN,
                                    policy_id=1, status=STATUS_OPEN))
    db.session.commit()
    count, _rows = run_invariant("unattributed_bob_rows")
    assert count == 1
```

**Implementer note:** `app/integrity.py` exposes invariants through an `@invariant`
registry. Read how existing tests in `tests/test_integrity_guards.py` invoke one and
use that exact accessor — if it is not `run_invariant`, use the real name.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_attribution_invariant.py -v`
Expected: FAIL — unknown invariant `unattributed_bob_rows`

- [ ] **Step 3: Add the invariant**

```python
# app/integrity.py — add beside the other data invariants
@invariant("unattributed_bob_rows", severity="high", domain="data",
           description="BOB rows parked in the attribution queue awaiting a human "
                       "(missing customer link or missing plan bucket).")
def _unattributed_bob_rows():
    from app.models import AttributionQueue, STATUS_OPEN
    q = AttributionQueue.query.filter(AttributionQueue.status == STATUS_OPEN)
    rows = [{"id": e.id,
             "label": f"{e.kind}: {e.carrier or '—'} {e.plan_name or e.full_name or '—'}",
             "url": None} for e in q.limit(10).all()]
    return q.count(), rows
```

- [ ] **Step 4: Add the badge count**

In `app/__init__.py`, inside `inject_counts`, matching the existing defensive pattern:

```python
        attribution_queue_count = 0
        if current_user.is_admin:
            try:
                from app.attribution_queue import open_count
                attribution_queue_count = open_count(current_user.agency_id)
            except Exception:
                attribution_queue_count = 0
```

and add `'attribution_queue_count': attribution_queue_count` to the returned dict.

- [ ] **Step 5: Set the baseline**

Run the audit to get the live number, then add the key to `integrity_baseline.json`:

```bash
python3 -c "import json;p='integrity_baseline.json';d=json.load(open(p));d['unattributed_bob_rows']=0;json.dump(d,open(p,'w'),indent=2,sort_keys=True)"
```

Expected: baseline starts at 0 for a fresh DB; the backfill in Task 8 will report the
real production number, and the baseline is ratcheted to that value at deploy time.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_attribution_invariant.py tests/test_integrity_guards.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/__init__.py app/integrity.py integrity_baseline.json tests/test_attribution_invariant.py
git commit -m "feat: shared attribution count badge + unattributed_bob_rows invariant"
```

---

### Task 8: Backfill script for existing debt

**Files:**
- Create: `scripts/backfill_attribution_queue.py`
- Test: `tests/test_backfill_attribution_queue.py`

**Interfaces:**
- Consumes: `enqueue` (Task 2), `AttributionQueue`/kinds (Task 1).
- Produces: a dry-run-by-default script that parks today's unlinked policies.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backfill_attribution_queue.py
from app.extensions import db
from app.models import AttributionQueue, Policy, KIND_NEEDS_PLAN
from scripts.backfill_attribution_queue import backfill


def test_backfill_parks_unlinked_and_is_idempotent(app_ctx):
    db.session.add(Policy(agency_id=1, carrier="UHC", member_id="3CC3CC3CC33",
                          status="active", plan_id=None, plan_name="Mystery Plan"))
    db.session.commit()
    assert backfill(agency_id=1, apply=True) == 1
    assert AttributionQueue.query.filter_by(kind=KIND_NEEDS_PLAN).count() == 1
    assert backfill(agency_id=1, apply=True) == 0        # idempotent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_backfill_attribution_queue.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the script**

```python
# scripts/backfill_attribution_queue.py
"""Park today's already-unlinked policies into the attribution queue, so the queue
starts populated with real work rather than only catching future imports.

Touches NO money field and does not change plan_id or customer_id — it only ENQUEUES.
Dry-run by default; --apply commits. Idempotent (a second run enqueues 0).

Run on the VPS:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
    scripts/backfill_attribution_queue.py [--apply]
"""
import sys

from app import create_app
from app.attribution_queue import enqueue
from app.extensions import db
from app.models import Customer, Policy, KIND_NEEDS_CUSTOMER, KIND_NEEDS_PLAN


def backfill(agency_id, apply=False) -> int:
    parked = 0
    unlinked = Policy.query.filter_by(agency_id=agency_id, plan_id=None).all()
    for p in unlinked:
        if enqueue(agency_id, KIND_NEEDS_PLAN, policy_id=p.id, carrier=p.carrier,
                   plan_name=p.plan_name, plan_type=p.plan_type,
                   member_id=p.member_id, full_name=p.full_name):
            parked += 1
    orphan_pols = Policy.query.filter_by(agency_id=agency_id, customer_id=None).all()
    for p in orphan_pols:
        if enqueue(agency_id, KIND_NEEDS_CUSTOMER, policy_id=p.id, carrier=p.carrier,
                   member_id=p.member_id, full_name=p.full_name):
            parked += 1
    if apply:
        db.session.commit()
    else:
        db.session.rollback()
    return parked


def main(apply):
    app = create_app()
    with app.app_context():
        agency_id = app.config.get("DEFAULT_AGENCY_ID", 1)
        print(f"{'APPLY' if apply else 'DRY-RUN'} — backfill attribution queue\n")
        n = backfill(agency_id, apply=apply)
        print(f"  parked: {n}")
        print("\nCOMMITTED." if apply else
              "\nDRY-RUN — nothing committed. Re-run with --apply to commit.")
        return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_backfill_attribution_queue.py -v`
Expected: 1 PASS

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all green (789 + the new tests)

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill_attribution_queue.py tests/test_backfill_attribution_queue.py
git commit -m "feat: backfill existing unlinked policies into the attribution queue"
```

---

## Deployment (human-gated — do NOT run as part of task execution)

1. **Back up the DB first:**
   `PGPASSWORD=<from .env> pg_dump -U founders_user -h localhost founders_portal > /root/founders_pre_mig043_$(date +%Y%m%d_%H%M%S).sql`
2. Deploy: `cd /var/www/founders-portal && git pull && ./venv/bin/pip install -r requirements.txt && flask db upgrade && systemctl restart founders-portal`
3. **Verify migration 042 → 043 applied on real Postgres**, and that `attribution_queue.id` is `SERIAL` (`nextval(...)`) — the classic SQLite-passes/Postgres-fails trap.
4. Run the backfill **dry-run first**, read the output, then `--apply`.
5. Ratchet `integrity_baseline.json` `unattributed_bob_rows` to the real post-backfill number, commit.
6. Confirm `systemctl restart` actually cycled (ActiveEnterTimestamp advanced), login 200, `/admin/plan-queue` 302-gated when logged out.
7. **Money check:** ledger and payment totals identical to the penny before/after.
