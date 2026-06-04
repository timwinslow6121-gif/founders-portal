# Commission Sync — Plan 4: Wire Route → Resolver + Payments + Duplicate Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make commission upload actually create customers: for the 5 clean-split carriers, the route runs `NORMALIZERS[carrier]` → `resolve_customer()` per MemberFact (creating Customer/Policy/AOR) and writes a `PolicyPayment` linked to the resolved policy — in one pass — plus a fingerprint-based duplicate-statement guard (block-by-default + explicit Replace, update-in-place) so a month can never be double-paid.

**Architecture:** A new module `app/commission/ingest.py` holds `ingest_statement(...)` — the single per-file pipeline: normalize → per-fact resolve + write payment → compute statement totals → return a structured result. The `commission_upload` route calls it for the 5 normalized carriers (Healthspring, Devoted, BCBS, Aetna, Humana) and keeps the legacy `PARSERS`/`build_payments` path for UHC (Plan 6). A fingerprint helper detects duplicate statements. PolicyPayment writes are update-in-place (match existing row by `source_ref`/identity, update; don't delete-reinsert).

**Tech Stack:** Python 3.10, Flask, Flask-SQLAlchemy, pytest SQLite-in-memory (fixtures: `app`, `db_session`, `agency`, `agent_user`, `admin_user`).

**Reference spec:** `docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md` (§4 pipeline + duplicate guard). Builds on Plan 1 (`normalizers.NORMALIZERS`, `MemberFact`) and Plan 2 (`resolver.resolve_customer`, `Policy.customer_id`).

**Scope (locked with user):** Wire resolver + write payments from MemberFact + fingerprint duplicate guard (block/replace, update-in-place). LEAVE the existing split/authorization + rate-discrepancy logic in `commission_upload` AS-IS (it already works). Anjana provenance flag, no-contract→hold-row tab, import-modal tabs, and UHC normalizer are Plans 5/6 — NOT here.

---

## File Structure

- **Create** `app/commission/ingest.py` — `ingest_statement(statement, carrier, agent_id, agency_id, sheets) -> IngestResult`; `compute_fingerprint(facts)`; `write_payment_from_fact(...)`. One responsibility: the normalize→resolve→pay pipeline for a single statement.
- **Create** `tests/test_commission_ingest.py` — pipeline tests (SQLite, fixtured from the real raw files already in `tests/fixtures/commission/`).
- **Modify** `app/commission/routes.py` — `commission_upload`: for the 5 normalized carriers, call `ingest_statement`; add the fingerprint duplicate guard (block by default + `?replace=1` / form field to override); keep UHC on the legacy path.
- **Add a small adapter** in `app/commission/payments.py` OR `ingest.py`: a `PolicyPayment` writer that takes a `MemberFact` + resolved `policy` (rather than the old `item` dict).

The resolver (Plan 2) is unchanged. The normalizers (Plan 1) are unchanged. UHC's legacy `extract_uhc`/`build_payments` stays.

---

### Task 1: PolicyPayment writer from a MemberFact (update-in-place)

**Files:**
- Create: `app/commission/ingest.py`
- Test: `tests/test_commission_ingest.py`

A payment row is written from a `MemberFact` + the resolved `Policy`. Update-in-place: identify an existing row for this statement by `(statement_id, carrier_member_id or mbi, commission_action)`; update it if present, else insert. (No delete-reinsert — preserves row identity across re-uploads.)

- [ ] **Step 1: Write the failing test**

Create `tests/test_commission_ingest.py`:
```python
"""
tests/test_commission_ingest.py

Tests for the commission ingest pipeline: write payments from MemberFact (update-
in-place), fingerprint, and the normalize→resolve→pay flow. SQLite in-memory.
"""
import os
from datetime import date

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "commission")


def _statement(db, agency, carrier="Devoted"):
    from app.models import CommissionStatement
    s = CommissionStatement(agency_id=agency.id, carrier=carrier,
                            statement_date=date(2026, 5, 1), period_label="May 2026")
    db.session.add(s)
    db.session.flush()
    return s


def test_write_payment_from_fact_inserts_then_updates(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy, PolicyPayment
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.ingest import write_payment_from_fact

    with app.app_context():
        stmt = _statement(db, agency)
        cust = Customer(agency_id=agency.id, first_name="X", last_name="Y", full_name="X Y")
        db.session.add(cust); db.session.flush()
        pol = Policy(agency_id=agency.id, carrier="Devoted", member_id="DGFY27",
                     status="active", customer_id=cust.id)
        db.session.add(pol); db.session.flush()

        fact = MemberFact(carrier="Devoted", full_name="Rene Barger", first_name="Rene",
                          last_name="Barger", carrier_member_id="DGFY27",
                          row_class=RowClass.ENROLLMENT, amount=260.25,
                          effective_date=date(2026, 4, 1))

        p1 = write_payment_from_fact(fact, stmt, pol, agency.id, agent_user.id)
        db.session.flush()
        assert p1.paid_amount == 260.25
        assert p1.policy_id == pol.id
        assert p1.is_chargeback is False
        assert PolicyPayment.query.filter_by(statement_id=stmt.id).count() == 1

        # Same fact again (re-upload) → UPDATE in place, not a 2nd row
        fact.amount = 270.00
        p2 = write_payment_from_fact(fact, stmt, pol, agency.id, agent_user.id)
        db.session.flush()
        assert p2.id == p1.id
        assert p2.paid_amount == 270.00
        assert PolicyPayment.query.filter_by(statement_id=stmt.id).count() == 1


def test_write_payment_flags_chargeback_on_negative(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.ingest import write_payment_from_fact

    with app.app_context():
        stmt = _statement(db, agency)
        cust = Customer(agency_id=agency.id, first_name="C", last_name="B", full_name="C B")
        db.session.add(cust); db.session.flush()
        pol = Policy(agency_id=agency.id, carrier="Devoted", member_id="DS97W3",
                     status="active", customer_id=cust.id)
        db.session.add(pol); db.session.flush()
        fact = MemberFact(carrier="Devoted", full_name="Elizabeth Bolder",
                          first_name="Elizabeth", last_name="Bolder",
                          carrier_member_id="DS97W3", row_class=RowClass.CHARGEBACK,
                          amount=-347.0)
        p = write_payment_from_fact(fact, stmt, pol, agency.id, agent_user.id)
        db.session.flush()
        assert p.paid_amount == -347.0
        assert p.is_chargeback is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_commission_ingest.py -k write_payment -v`
Expected: FAIL — `ModuleNotFoundError: app.commission.ingest`.

- [ ] **Step 3: Implement the writer**

Create `app/commission/ingest.py`:
```python
"""
app/commission/ingest.py

The single per-statement commission pipeline: normalize a carrier file into
MemberFacts, resolve each to a Customer/Policy/AOR (Plan 2 resolver), and write a
PolicyPayment linked to the resolved policy — in one pass. Plus a statement
fingerprint for duplicate detection.

See docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md §4.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from app.extensions import db
from app.models import PolicyPayment
from app.commission.member_fact import MemberFact, RowClass
from app.commission.resolver import resolve_customer
from app.commission.payments import _norm


def _payment_key(fact: MemberFact):
    """Stable identity of a payment row within a statement."""
    return (fact.carrier_member_id or fact.mbi or _norm(fact.full_name) or "").strip()


def write_payment_from_fact(fact: MemberFact, statement, policy, agency_id: int,
                            agent_id: Optional[int]) -> PolicyPayment:
    """Insert or update (in place) a PolicyPayment for this fact within the statement."""
    key = _payment_key(fact)
    action = fact.row_class  # canonical: enrollment|renewal|chargeback|non_customer
    norm_name = _norm(fact.full_name)

    existing = (PolicyPayment.query
                .filter_by(statement_id=statement.id, agency_id=agency_id,
                           commission_action=action)
                .filter((PolicyPayment.carrier_member_id == (fact.carrier_member_id or None)) |
                        (PolicyPayment.mbi == (fact.mbi or None)) |
                        (PolicyPayment.member_name_normalized == norm_name))
                .first()) if key else None

    if existing is None:
        existing = PolicyPayment(
            agency_id=agency_id,
            statement_id=statement.id,
            carrier=fact.carrier,
            period_label=statement.period_label,
            statement_date=statement.statement_date,
            member_name=fact.full_name,
            commission_action=action,
            paid_amount=0.0,
        )
        db.session.add(existing)

    existing.agent_id = agent_id
    existing.member_name = fact.full_name
    existing.member_name_normalized = norm_name
    existing.mbi = fact.mbi
    existing.carrier_member_id = fact.carrier_member_id
    existing.policy_id = policy.id if policy is not None else None
    existing.match_confidence = "exact" if (fact.mbi or fact.carrier_member_id) else "name"
    existing.commission_action = action
    existing.paid_amount = fact.amount
    existing.is_chargeback = fact.amount < 0
    existing.effective_date = fact.effective_date
    existing.term_date = fact.term_date
    existing.plan_name = None
    return existing
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_commission_ingest.py -k write_payment -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add app/commission/ingest.py tests/test_commission_ingest.py
git commit -m "feat(commission): write_payment_from_fact — update-in-place payment writer"
```

---

### Task 2: Statement fingerprint for duplicate detection

**Files:**
- Modify: `app/commission/ingest.py`
- Test: `tests/test_commission_ingest.py`

The fingerprint = `(carrier, period_label, member_row_count, sum_of_amounts rounded)`. Used to detect an exact re-upload of an already-imported statement.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_ingest.py`:
```python
def test_compute_fingerprint_is_stable_and_sensitive(db_session, app, agency):
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.ingest import compute_fingerprint

    facts = [
        MemberFact(carrier="Devoted", full_name="A B", carrier_member_id="1",
                   row_class=RowClass.ENROLLMENT, amount=100.0),
        MemberFact(carrier="Devoted", full_name="C D", carrier_member_id="2",
                   row_class=RowClass.RENEWAL, amount=28.92),
    ]
    fp1 = compute_fingerprint("Devoted", "May 2026", facts)
    fp2 = compute_fingerprint("Devoted", "May 2026", list(facts))
    assert fp1 == fp2                       # stable / order-independent on same data

    # A changed amount → different fingerprint
    facts2 = [facts[0], MemberFact(carrier="Devoted", full_name="C D",
              carrier_member_id="2", row_class=RowClass.RENEWAL, amount=99.99)]
    assert compute_fingerprint("Devoted", "May 2026", facts2) != fp1

    # A different period → different fingerprint
    assert compute_fingerprint("Devoted", "June 2026", facts) != fp1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_ingest.py -k fingerprint -v`
Expected: FAIL — `ImportError: cannot import name 'compute_fingerprint'`.

- [ ] **Step 3: Implement**

Append to `app/commission/ingest.py`:
```python
def compute_fingerprint(carrier: str, period_label: str, facts: List[MemberFact]) -> str:
    """A stable, order-independent signature of a statement's content. Used to
    detect an exact re-upload. Sensitive to row count, the set of member ids, and
    the summed amount — so a corrected re-pull (different totals) is NOT mistaken
    for an exact duplicate."""
    total = round(sum(f.amount for f in facts), 2)
    ids = sorted((f.carrier_member_id or f.mbi or _norm(f.full_name) or "") for f in facts)
    import hashlib
    h = hashlib.sha256()
    h.update(f"{carrier}|{period_label}|{len(facts)}|{total}|{'|'.join(ids)}".encode())
    return h.hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_ingest.py -k fingerprint -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/ingest.py tests/test_commission_ingest.py
git commit -m "feat(commission): compute_fingerprint for duplicate-statement detection"
```

---

### Task 3: ingest_statement — the normalize→resolve→pay pipeline

**Files:**
- Modify: `app/commission/ingest.py`
- Test: `tests/test_commission_ingest.py`

`ingest_statement` ties it together: normalize the file, then for each customer-bearing fact (ENROLLMENT/RENEWAL/CHARGEBACK) resolve identity + write a payment; NON_CUSTOMER facts (HRA bonuses) get a payment row but no customer. Returns a structured `IngestResult` (counts + the fingerprint + gross).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_ingest.py`:
```python
def test_ingest_statement_devoted_creates_customers_and_payments(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy, PolicyPayment, CommissionStatement
    from app.commission.sheet_loader import load_sheets
    from app.commission.ingest import ingest_statement

    with app.app_context():
        sheets = load_sheets(os.path.join(FIXTURES, "devoted_sample.xlsx"))
        stmt = CommissionStatement(agency_id=agency.id, carrier="Devoted",
                                   statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(stmt); db.session.flush()

        result = ingest_statement(stmt, "Devoted", agent_user.id, agency.id, sheets)
        db.session.commit()

        # Customers were created from the commission file (the core bug fix)
        assert Customer.query.filter_by(agency_id=agency.id).count() > 0
        # Payments written, linked to policies
        payments = PolicyPayment.query.filter_by(statement_id=stmt.id).all()
        assert len(payments) > 0
        # The Bolder chargeback is present and negative
        bolder = [p for p in payments if p.carrier_member_id == "DS97W3"]
        assert bolder and bolder[0].is_chargeback is True
        # result reports what happened
        assert result.payments_written == len(payments)
        assert result.customers_created > 0
        assert result.fingerprint


def test_ingest_statement_is_idempotent(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy, PolicyPayment, CommissionStatement
    from app.commission.sheet_loader import load_sheets
    from app.commission.ingest import ingest_statement

    with app.app_context():
        sheets = load_sheets(os.path.join(FIXTURES, "devoted_sample.xlsx"))
        stmt = CommissionStatement(agency_id=agency.id, carrier="Devoted",
                                   statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(stmt); db.session.flush()

        ingest_statement(stmt, "Devoted", agent_user.id, agency.id, sheets)
        db.session.commit()
        c1 = Customer.query.filter_by(agency_id=agency.id).count()
        p1 = PolicyPayment.query.filter_by(statement_id=stmt.id).count()
        pol1 = Policy.query.filter_by(agency_id=agency.id).count()

        # Re-ingest the SAME sheets into the SAME statement → no duplication
        ingest_statement(stmt, "Devoted", agent_user.id, agency.id, sheets)
        db.session.commit()
        assert Customer.query.filter_by(agency_id=agency.id).count() == c1
        assert PolicyPayment.query.filter_by(statement_id=stmt.id).count() == p1
        assert Policy.query.filter_by(agency_id=agency.id).count() == pol1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_commission_ingest.py -k ingest_statement -v`
Expected: FAIL — `ImportError: cannot import name 'ingest_statement'`.

- [ ] **Step 3: Implement**

Append to `app/commission/ingest.py`:
```python
@dataclass
class IngestResult:
    fingerprint: str = ""
    facts_total: int = 0
    customers_created: int = 0
    stubs_created: int = 0
    payments_written: int = 0
    chargebacks: int = 0
    match_suggestions: int = 0
    carrier_switches: int = 0
    gross: float = 0.0
    actions: List[str] = field(default_factory=list)


# Carriers whose files are handled by the new normalize→resolve pipeline.
# UHC stays on the legacy parser until Plan 6 (lumped LOA split).
from app.commission.normalizers import NORMALIZERS


def ingest_statement(statement, carrier: str, agent_id, agency_id: int, sheets) -> IngestResult:
    """Normalize a carrier file → resolve each fact → write payments. One pass."""
    result = IngestResult()
    normalizer = NORMALIZERS.get(carrier)
    if normalizer is None:
        return result

    facts = normalizer(sheets)
    result.facts_total = len(facts)
    result.fingerprint = compute_fingerprint(carrier, statement.period_label, facts)
    result.gross = round(sum(f.amount for f in facts), 2)

    for fact in facts:
        if fact.row_class == RowClass.NON_CUSTOMER:
            # bonus/non-customer row → payment only, no identity resolution
            write_payment_from_fact(fact, statement, None, agency_id, agent_id)
            result.payments_written += 1
            if fact.amount < 0:
                result.chargebacks += 1
            continue

        res = resolve_customer(fact, agency_id=agency_id, agent_id=agent_id,
                               source="commission_import")
        if res.created_customer:
            result.customers_created += 1
            if res.customer is not None and res.customer.stub:
                result.stubs_created += 1
        if "match_suggestion" in res.actions:
            result.match_suggestions += 1
        if "carrier_switch" in res.actions:
            result.carrier_switches += 1

        write_payment_from_fact(fact, statement, res.policy, agency_id, agent_id)
        result.payments_written += 1
        if fact.amount < 0:
            result.chargebacks += 1

    db.session.flush()
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_commission_ingest.py -k ingest_statement -v`
Expected: PASS (both). The idempotency test is the critical one — re-ingest must not duplicate customers/policies/payments (resolver crosswalk + write-in-place guarantee it).

- [ ] **Step 5: Run the whole ingest file + full suite**

Run: `python3 -m pytest tests/test_commission_ingest.py -v && python3 -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add app/commission/ingest.py tests/test_commission_ingest.py
git commit -m "feat(commission): ingest_statement pipeline — normalize→resolve→pay in one pass"
```

---

### Task 4: Wire commission_upload route to ingest_statement (5 carriers) + fingerprint guard

**Files:**
- Modify: `app/commission/routes.py`
- Test: `tests/test_commission_ingest.py` (route-level, using the Flask test client)

For the 5 normalized carriers, the route calls `ingest_statement` instead of `build_payments`, and applies the fingerprint duplicate guard. UHC keeps the legacy path. The existing split/auth/rate-discrepancy logic is UNCHANGED.

- [ ] **Step 1: Read the current route + add a fingerprint column decision**

Read `commission_upload` in `app/commission/routes.py` (around lines 620–792). The statement model has no fingerprint column; store the fingerprint in the existing `CommissionStatement` by reusing a column or adding one. DECISION: add `CommissionStatement.content_fingerprint` (String, nullable) via a tiny migration 021, so the duplicate guard can compare against prior uploads. Confirm migration 020 is the current head:
`ls migrations/versions/ | grep -E "^02"` → should show `020_commission_sync.py`.

- [ ] **Step 2: Write the failing migration + ORM column test**

Append to `tests/test_commission_ingest.py`:
```python
def test_statement_has_content_fingerprint_column(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionStatement
    from datetime import date as _d
    with app.app_context():
        s = CommissionStatement(agency_id=agency.id, carrier="Devoted",
                                statement_date=_d(2026, 5, 1), period_label="May 2026",
                                content_fingerprint="abc123")
        db.session.add(s); db.session.commit()
        assert s.content_fingerprint == "abc123"
```

- [ ] **Step 3: Run it, confirm fail**

Run: `python3 -m pytest tests/test_commission_ingest.py -k content_fingerprint -v`
Expected: FAIL — `TypeError: unexpected keyword argument 'content_fingerprint'`.

- [ ] **Step 4: Add ORM column + migration 021**

In `app/models.py`, in `class CommissionStatement`, after the `status` column add:
```python
    content_fingerprint = db.Column(db.String(64), index=True)  # duplicate-upload detection
```
Create `migrations/versions/021_statement_fingerprint.py`:
```python
"""CommissionStatement.content_fingerprint for duplicate-upload detection

Revision ID: 021
Revises: 020
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("commission_statements",
                  sa.Column("content_fingerprint", sa.String(64), nullable=True))
    op.create_index("ix_commission_statements_content_fingerprint",
                    "commission_statements", ["content_fingerprint"])


def downgrade():
    op.drop_index("ix_commission_statements_content_fingerprint",
                  table_name="commission_statements")
    op.drop_column("commission_statements", "content_fingerprint")
```
Run: `python3 -m pytest tests/test_commission_ingest.py -k content_fingerprint -v` → PASS.

- [ ] **Step 5: Write a route-level duplicate-guard test**

Append to `tests/test_commission_ingest.py`:
```python
def _login(client, app, agency):
    """Log in as an admin user for route tests (mirrors existing route-test pattern)."""
    from app.extensions import db
    from app.models import User
    with app.app_context():
        u = User(email="aj@test.com", name="AJ", is_admin=True, agency_id=agency.id)
        db.session.add(u); db.session.commit()
        uid = u.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
    return uid


def test_route_blocks_exact_duplicate_then_allows_replace(client, app, agency, db_session):
    """Second upload of the same file is blocked unless replace is requested."""
    import io
    _login(client, app, agency)
    path = os.path.join(FIXTURES, "devoted_sample.xlsx")
    data1 = {"file": (open(path, "rb"), "devoted_sample.xlsx"),
             "statement_month": "2026-05"}
    r1 = client.post("/admin/commissions/upload", data=data1,
                     content_type="multipart/form-data", follow_redirects=True)
    assert r1.status_code == 200

    # Second identical upload WITHOUT replace → blocked (no new statement)
    from app.models import CommissionStatement
    with app.app_context():
        n_before = CommissionStatement.query.filter_by(agency_id=agency.id,
                                                       carrier="Devoted").count()
    data2 = {"file": (open(path, "rb"), "devoted_sample.xlsx"),
             "statement_month": "2026-05"}
    r2 = client.post("/admin/commissions/upload", data=data2,
                     content_type="multipart/form-data", follow_redirects=True)
    assert b"already" in r2.data.lower() or b"duplicate" in r2.data.lower()
    with app.app_context():
        n_after = CommissionStatement.query.filter_by(agency_id=agency.id,
                                                      carrier="Devoted").count()
    assert n_after == n_before   # blocked: no duplicate statement created
```
NOTE: confirm the real upload route URL. Inspect: `grep -n "commissions/upload\|def commission_upload" app/commission/routes.py`. Use the actual route path in the test. If the route requires CSRF, the test config disables it (`WTF_CSRF_ENABLED=False` in conftest). If admin gating uses something other than `is_admin`, adjust `_login`.

- [ ] **Step 6: Run it, confirm fail**

Run: `python3 -m pytest tests/test_commission_ingest.py -k duplicate -v`
Expected: FAIL — currently the route warns-and-overwrites (doesn't block), so a 2nd statement/overwrite happens and the assertion on block fails.

- [ ] **Step 7: Wire the route**

In `app/commission/routes.py`, in `commission_upload`, after `carrier = _detect_carrier(ws)` and the statement-period resolution, branch the pipeline. Add near the top of the file:
```python
from app.commission.ingest import ingest_statement, compute_fingerprint
from app.commission.sheet_loader import load_sheets
from app.commission.normalizers import NORMALIZERS
```
Then, in the route, AFTER `stmt_date`/`period_label` are known and AFTER the existing split/authorization block (keep all of that), REPLACE the legacy statement-build + `build_payments` section (the block from `existing = CommissionStatement.query.filter_by(...)` through the `build_payments(...)` call and its commit) with this carrier-branched logic:

```python
    NORMALIZED = set(NORMALIZERS.keys())  # Healthspring, Devoted, BCBS, Aetna, Humana

    if carrier in NORMALIZED:
        # New pipeline: normalize → resolve (create customers) → write payments.
        sheets = load_sheets_from_bytes(file_bytes, file.filename)
        facts = NORMALIZERS[carrier](sheets)
        fingerprint = compute_fingerprint(carrier, period_label, facts)

        # Duplicate guard: block an exact re-upload unless replace requested.
        replace = request.form.get("replace") == "1"
        dup = CommissionStatement.query.filter_by(
            agency_id=current_user.agency_id, carrier=carrier,
            content_fingerprint=fingerprint).first()
        if dup is not None and not replace:
            flash(
                f"This looks like the {carrier} {dup.period_label} statement already "
                f"imported on {dup.statement_date:%b %d, %Y} "
                f"({len(facts)} members, ${result_gross_preview(facts):,.2f}). "
                f"No payments were created. Re-submit with 'Replace existing' to overwrite.",
                "warning")
            return redirect(url_for("commission.commission_admin"))

        existing = CommissionStatement.query.filter_by(
            carrier=carrier, agent_id=agent_id, period_label=period_label,
            agency_id=current_user.agency_id).first()
        stmt = existing or CommissionStatement(
            carrier=carrier, agent_id=agent_id, agency_id=current_user.agency_id)
        if not existing:
            db.session.add(stmt)
        stmt.statement_date = stmt_date
        stmt.period_label = period_label
        stmt.split_rate = agent_split
        stmt.filename = file.filename
        stmt.uploaded_by_id = current_user.id
        stmt.content_fingerprint = fingerprint
        db.session.flush()

        ingest = ingest_statement(stmt, carrier, agent_id, current_user.agency_id, sheets)

        # Statement totals from the normalized facts (gross = sum of positive amounts).
        stmt.gross_amount = round(sum(f.amount for f in facts if f.amount > 0), 2)
        stmt.bonus_amount = 0.0
        stmt.expected_amount = round(stmt.gross_amount * agent_split, 2)
        stmt.paid_amount = stmt.expected_amount  # no summary row → assume expected
        stmt.difference = 0.0
        stmt.status = "verified"
        db.session.commit()

        flash(
            f"✓ {carrier} {period_label} — {ingest.payments_written} payments, "
            f"{ingest.customers_created} customers created "
            f"({ingest.stubs_created} stubs), {ingest.chargebacks} chargebacks"
            + (f", {ingest.match_suggestions} match suggestions" if ingest.match_suggestions else "")
            + ".", "success")
        return redirect(url_for("commission.commission_admin"))

    # --- Legacy path (UHC etc.): existing extract_*/build_payments flow unchanged ---
```
KEEP the entire existing legacy block below this for UHC. The legacy block starts at the old `existing = CommissionStatement.query.filter_by(... period_label ...)` — move it under the `else`/after the `if carrier in NORMALIZED: ... return`.

Add two small helpers near the top of routes.py:
```python
def load_sheets_from_bytes(file_bytes, filename):
    """Write bytes to a temp path and load via sheet_loader (handles xlsx/xls/SpreadsheetML)."""
    import tempfile, os as _os
    suffix = ".xlsx" if (filename or "").lower().endswith("xlsx") else ".xls"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
        tf.write(file_bytes)
        tmp = tf.name
    try:
        from app.commission.sheet_loader import load_sheets
        return load_sheets(tmp)
    finally:
        _os.unlink(tmp)


def result_gross_preview(facts):
    return round(sum(f.amount for f in facts if f.amount > 0), 2)
```
NOTE: `sheet_loader.load_sheets` takes a path; the route has bytes. The helper bridges that. (If preferred, add a `load_sheets_bytes` to sheet_loader instead — but the temp-file helper keeps Plan 1 untouched.)

- [ ] **Step 8: Run the duplicate-guard test + full suite**

Run: `python3 -m pytest tests/test_commission_ingest.py -v && python3 -m pytest -q`
Expected: all green. The duplicate test now blocks the 2nd upload; the resolver tests, BOB characterization, normalizer tests all stay green.

- [ ] **Step 9: Manual smoke (optional but recommended)**

Run a quick REPL check that a real Devoted file ingests end-to-end:
```bash
python3 -c "
import os; os.environ.setdefault('DATABASE_URL','sqlite:///:memory:'); os.environ.setdefault('SECRET_KEY','t'); os.environ.setdefault('TESTING','1')
from app import create_app; from app.extensions import db
from app.models import Agency, User, Customer, PolicyPayment, CommissionStatement
from app.commission.sheet_loader import load_sheets
from app.commission.ingest import ingest_statement
from datetime import date
app=create_app(); app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', TESTING=True, SERVER_NAME=None)
with app.app_context():
    db.create_all()
    ag=Agency(name='T'); db.session.add(ag); db.session.flush()
    u=User(email='a@b.c', name='Rebekah Long', is_admin=True, agency_id=ag.id); db.session.add(u); db.session.flush()
    sheets=load_sheets('tests/fixtures/commission/devoted_sample.xlsx')
    s=CommissionStatement(agency_id=ag.id, carrier='Devoted', statement_date=date(2026,5,1), period_label='May 2026'); db.session.add(s); db.session.flush()
    r=ingest_statement(s,'Devoted',u.id,ag.id,sheets); db.session.commit()
    print('customers=%d payments=%d stubs=%d chargebacks=%d gross=%.2f' % (Customer.query.count(), PolicyPayment.query.count(), r.stubs_created, r.chargebacks, r.gross))
" 2>&1 | grep -v Warning
```
Expected: nonzero customers + payments, some chargebacks, a gross figure.

- [ ] **Step 10: Commit**

```bash
git add app/commission/routes.py app/models.py migrations/versions/021_statement_fingerprint.py tests/test_commission_ingest.py
git commit -m "feat(commission): wire upload route to ingest pipeline + fingerprint duplicate guard"
```

---

### Task 5: Full-suite green + verify no UHC regression

**Files:**
- Test: full suite

- [ ] **Step 1: Run the entire suite**

Run: `python3 -m pytest -q`
Expected: all green. Record the count.

- [ ] **Step 2: Confirm UHC still uses the legacy path**

Inspect: `grep -n "NORMALIZED\|ingest_statement\|build_payments\|extract_uhc" app/commission/routes.py`
Confirm: UHC (not in `NORMALIZERS`) flows through the legacy `build_payments` branch; the 5 normalized carriers use `ingest_statement`. There should be exactly one `ingest_statement` call (the normalized branch) and the legacy `build_payments` call still present for UHC.

- [ ] **Step 3: Commit (if any cleanup)**

```bash
git add -A
git commit -m "test(commission): confirm Plan 4 suite green, UHC on legacy path" --allow-empty
```

---

## Self-Review

**1. Spec coverage (Plan 4 = spec §4 pipeline + duplicate guard, scoped with user):**
- Normalize→resolve→pay in one pass, commission upload CREATES customers (the core bug) → Tasks 1, 3, 4. ✓
- PolicyPayment written from MemberFact, linked to resolved policy, update-in-place (spec decision: update-in-place not delete-reinsert) → Task 1. ✓
- Fingerprint duplicate guard, block-by-default + explicit Replace (spec duplicate guard) → Tasks 2, 4. ✓
- Idempotent re-upload (no duplicate customer/policy/payment) → Task 3 idempotency test. ✓
- NON_CUSTOMER (HRA) rows → payment only, no customer (spec row taxonomy) → Task 3. ✓
- Existing split/auth/rate-discrepancy preserved (scope decision) → Task 4 keeps that block, only replaces the statement-build/build_payments section. ✓
- UHC stays legacy (spec: UHC is Plan 6) → Task 4 carrier branch + Task 5 verify. ✓
- NOT in this plan (deferred): import-modal tabs UI, Anjana provenance flag, no-contract→hold-row tab, replace-mode update-in-place across statements with superseded marking (basic block+replace is here; the richer superseded-row handling is a later refinement), UHC. ✓

**2. Placeholder scan:** No TBD/TODO. All code shown. Task 4 contains route-editing instructions with exact code; the "move legacy block under else" instruction references real existing code the implementer must read (Step 1/Step 7) — that's a real instruction, not a placeholder, but it IS the riskiest edit (see risk note).

**3. Type consistency:** `MemberFact` fields (carrier, carrier_member_id, mbi, full_name, row_class, amount, effective_date, term_date) match Plan 1. `RowClass.NON_CUSTOMER/CHARGEBACK` used consistently. `resolve_customer(...)` signature + `ResolveResult` fields (created_customer, customer.stub, actions, policy) match Plan 2. `PolicyPayment` fields (statement_id, carrier_member_id, mbi, member_name_normalized, commission_action, paid_amount, is_chargeback, policy_id, match_confidence) match the model read during planning. `CommissionStatement.content_fingerprint` added in Task 4. `compute_fingerprint(carrier, period_label, facts)` signature consistent between Tasks 2, 3, 4.

**Risks flagged for execution:**
- **Task 4 Step 7 is the load-bearing edit** — surgically replacing part of a long route function while preserving the split/auth block above and the UHC legacy block below. The implementer MUST read the whole `commission_upload` function first and place the carrier branch correctly. The route-level duplicate test + full suite are the safety net. If the legacy UHC path breaks, that test surface is thin (no UHC fixture in this plan) — the implementer should at minimum confirm the UHC branch still parses via the existing `PARSERS`/`build_payments` code unchanged.
- **`commission_action` value mismatch:** the NEW pipeline writes `commission_action = fact.row_class` (values: enrollment/renewal/chargeback/non_customer), while the LEGACY `build_payments` writes canonical values from `_norm_action` (initial/renewal/hra_bonus/chargeback/advance/other). The Payment Ledger UI may filter/badge on these strings. This is acceptable divergence for now (different carriers, different value sets) but the implementer should NOTE it — a later plan may need to unify the taxonomy for ledger display. Not a blocker; flagged.
- **Fingerprint vs period:** the duplicate guard blocks on `content_fingerprint` match within the agency+carrier. A legitimately different month has different facts → different fingerprint → not blocked. Confirmed by the fingerprint test (different period → different fp).
