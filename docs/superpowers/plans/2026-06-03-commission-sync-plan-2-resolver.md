# Commission Sync — Plan 2: resolve_customer() Service + Crosswalk + Migration 020 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the carrier-agnostic `resolve_customer(fact)` service that turns a `MemberFact` into a resolved `(Customer, Policy)` — via the crosswalk → MBI → suggest-link → stub resolution order — and route BOTH the commission path and the existing BOB upload path through it, so there is one identity codepath.

**Architecture:** A new module `app/commission/resolver.py` owns identity resolution, the crosswalk (`Policy` lookup by `(carrier, member_id)`), stub creation, carrier-switch terming + new AOR interval, the `rapid_disenroll` flag, and the suggest-link queue. Migration 020 adds `customers.stub`, `customers.source`, `policies.rapid_disenroll`, `policies.commission_split_flag`, **`policies.customer_id` (FK→customers, the real Policy↔Customer link)**, and a new `match_suggestions` table. The existing `_upsert_customer_from_policy` in `upload.py` is refactored to build a `MemberFact` and delegate to the resolver — pinned first by characterization tests so BOB behavior cannot regress.

**KEY ARCHITECTURAL CHANGE (decided during planning):** Policy and Customer were historically NOT linked by FK — the app joined them by MBI at query time (`Policy.mbi == Customer.mbi` in `app/customers.py:get_customer_policies`). This breaks for no-MBI carriers (BCBS) and is the root reason commission-created customers are invisible. Plan 2 adds a real `policies.customer_id` FK, backfills existing policies by MBI, has the resolver set it on every policy, and makes `get_customer_policies` FK-first (MBI fallback retained). This is what makes the crosswalk reliable for BCBS.

**Tech Stack:** Python 3.10, Flask-SQLAlchemy, Flask-Migrate/Alembic, pytest with SQLite-in-memory (conftest fixtures: `app`, `db_session`, `agency`, `agent_user`, `admin_user`, `customer`).

**Reference spec:** `docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md` (§2 resolver, §3 data model). Plan 1 delivered `app/commission/member_fact.py` (`MemberFact`, `RowClass`) and `app/commission/normalizers.py`.

---

## File Structure

- **Create** `migrations/versions/020_commission_sync.py` — migration 020 (5 columns incl. `policies.customer_id` + MBI backfill + match_suggestions table).
- **Modify** `app/models.py` — add ORM columns (`Customer.stub`, `Customer.source`, `Policy.rapid_disenroll`, `Policy.commission_split_flag`, `Policy.customer_id` FK) + new `MatchSuggestion` model.
- **Create** `app/commission/resolver.py` — `resolve_customer(fact, *, agency_id, agent_id, batch_id=None, source) -> ResolveResult`; helpers for crosswalk, stub, carrier-switch, rapid_disenroll, suggest-link.
- **Create** `tests/test_commission_resolver.py` — resolver unit tests (SQLite).
- **Create** `tests/test_bob_upsert_characterization.py` — pins current BOB `_upsert_customer_from_policy` behavior BEFORE refactor.
- **Modify** `app/upload.py` — `_upsert_customer_from_policy` builds a `MemberFact` and delegates to `resolve_customer`; preserve `manually_edited` guard and BCBS end_date=None rule.
- **Modify** `app/customers.py` — `get_customer_policies` becomes FK-first (`Policy.customer_id == customer.id`) with the existing MBI/Humana join retained as fallback, so commission-created (esp. BCBS no-MBI) policies appear on the profile.

The resolver does NOT parse files (Plan 1) and does NOT write `PolicyPayment`/handle duplicate-statement guard (Plan 4). It only resolves identity + lifecycle and returns what happened.

---

### Task 1: Migration 020 + ORM columns + MatchSuggestion model

**Files:**
- Create: `migrations/versions/020_commission_sync.py`
- Modify: `app/models.py`
- Test: `tests/test_commission_resolver.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_commission_resolver.py`:
```python
"""
tests/test_commission_resolver.py

Tests for the commission→customer resolver: crosswalk, MBI reuse, stub-once,
carrier-switch interval, rapid_disenroll, suggest-link. SQLite in-memory via
conftest fixtures.
"""
import pytest
from datetime import date


def test_new_orm_columns_and_match_suggestion_model(db_session, app, agency):
    from app.models import Customer, Policy, MatchSuggestion
    from app.extensions import db

    with app.app_context():
        c = Customer(
            agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
            stub=True, source="commission_import",
        )
        db.session.add(c)
        db.session.flush()
        p = Policy(
            agency_id=agency.id, carrier="BCBS", member_id="106815011",
            rapid_disenroll=True, commission_split_flag="no_contract",
            customer_id=c.id,
        )
        db.session.add(p)
        db.session.flush()
        ms = MatchSuggestion(
            agency_id=agency.id, suggested_customer_id=c.id,
            confidence="name_dob", status="pending",
            source_member_fact_json="{}",
        )
        db.session.add(ms)
        db.session.commit()

        assert c.stub is True
        assert c.source == "commission_import"
        assert p.rapid_disenroll is True
        assert p.commission_split_flag == "no_contract"
        assert p.customer_id == c.id
        assert ms.status == "pending"
        assert ms.confidence == "name_dob"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_new_orm_columns_and_match_suggestion_model -v`
Expected: FAIL — `TypeError` (unexpected kwarg `stub`) or `ImportError` (no `MatchSuggestion`). The conftest `db_session` fixture runs `db.create_all()`, so once the ORM columns/model exist the SQLite schema is created from the models (no Alembic needed for the test).

- [ ] **Step 3a: Add ORM columns to existing models**

In `app/models.py`, in `class Customer`, after the line
```python
    manually_edited   = db.Column(db.Boolean, default=False, nullable=False)
```
add:
```python
    # Commission-sync provenance (migration 020)
    stub              = db.Column(db.Boolean, default=False, nullable=False)
    source            = db.Column(db.String(32))   # commission_import | bob | healthsherpa | manual
```

In `app/models.py`, in `class Policy`, after the line
```python
    commission_type = db.Column(db.String(16))
```
add:
```python
    # Commission-sync flags + the real Customer link (migration 020)
    rapid_disenroll = db.Column(db.Boolean, default=False, nullable=False)
    commission_split_flag = db.Column(db.String(24))  # None | no_contract | provenance_conditional
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True, index=True)
```

- [ ] **Step 3b: Add the MatchSuggestion model**

In `app/models.py`, after the `CustomerAorHistory` class (find `class CustomerAorHistory` and add this AFTER its full definition ends), add:
```python
class MatchSuggestion(db.Model):
    """
    A possible identity link the resolver is NOT confident enough to apply
    automatically (e.g. a no-MBI carrier-switch enrollment that name+DOB-matches
    an existing customer). Surfaced for human confirm in the merge UI. Never an
    auto-merge.
    """
    __tablename__ = "match_suggestions"

    id          = db.Column(db.Integer, primary_key=True)
    agency_id   = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=True, index=True)

    # The stub customer that was created for the unmatched fact (so no payment is lost)
    stub_customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), index=True)
    # The existing customer we think it might really be
    suggested_customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), index=True)

    confidence  = db.Column(db.String(16))   # name_dob | name_only
    status      = db.Column(db.String(16), default="pending", index=True)  # pending|confirmed|rejected

    source_member_fact_json = db.Column(db.Text)

    created_at  = db.Column(db.DateTime, server_default=db.func.now())
    resolved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    resolved_at = db.Column(db.DateTime)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_new_orm_columns_and_match_suggestion_model -v`
Expected: PASS (the model-driven SQLite schema now has the columns/table).

- [ ] **Step 5: Write the Alembic migration (for real Postgres deploy)**

Create `migrations/versions/020_commission_sync.py`:
```python
"""Commission sync: stub/source on customers, flags on policies, match_suggestions

Revision ID: 020
Revises: 019
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customers", sa.Column("stub", sa.Boolean(), nullable=False,
                                         server_default=sa.false()))
    op.add_column("customers", sa.Column("source", sa.String(32), nullable=True))

    op.add_column("policies", sa.Column("rapid_disenroll", sa.Boolean(), nullable=False,
                                        server_default=sa.false()))
    op.add_column("policies", sa.Column("commission_split_flag", sa.String(24), nullable=True))
    op.add_column("policies", sa.Column("customer_id", sa.Integer(),
                                        sa.ForeignKey("customers.id"), nullable=True))
    op.create_index("ix_policies_customer_id", "policies", ["customer_id"])

    # Backfill the new FK from the existing MBI join (the old implicit link).
    # Humana policies have mbi='' historically — only match real MBIs.
    op.execute("""
        UPDATE policies p
        SET customer_id = c.id
        FROM customers c
        WHERE p.customer_id IS NULL
          AND p.mbi IS NOT NULL AND p.mbi <> ''
          AND c.mbi = p.mbi
          AND c.agency_id = p.agency_id
    """)
    # Humana link via humana_id = policy.member_id (Humana stores member id, mbi blank).
    op.execute("""
        UPDATE policies p
        SET customer_id = c.id
        FROM customers c
        WHERE p.customer_id IS NULL
          AND p.carrier = 'Humana'
          AND c.humana_id = p.member_id
          AND c.agency_id = p.agency_id
    """)

    op.create_table(
        "match_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=True),
        sa.Column("stub_customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("suggested_customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("confidence", sa.String(16), nullable=True),
        sa.Column("status", sa.String(16), nullable=True, server_default="pending"),
        sa.Column("source_member_fact_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_match_suggestions_agency_id", "match_suggestions", ["agency_id"])
    op.create_index("ix_match_suggestions_status", "match_suggestions", ["status"])
    op.create_index("ix_match_suggestions_stub_customer_id", "match_suggestions", ["stub_customer_id"])
    op.create_index("ix_match_suggestions_suggested_customer_id", "match_suggestions", ["suggested_customer_id"])


def downgrade():
    op.drop_table("match_suggestions")
    op.drop_index("ix_policies_customer_id", table_name="policies")
    op.drop_column("policies", "customer_id")
    op.drop_column("policies", "commission_split_flag")
    op.drop_column("policies", "rapid_disenroll")
    op.drop_column("customers", "source")
    op.drop_column("customers", "stub")
```

- [ ] **Step 6: Verify migration imports cleanly (syntax/chain check)**

Run: `python3 -c "import importlib.util, sys; spec=importlib.util.spec_from_file_location('m020','migrations/versions/020_commission_sync.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('revision', m.revision, 'down', m.down_revision)"`
Expected: `revision 020 down 019`

- [ ] **Step 7: Run full suite (no regression from model changes)**

Run: `python3 -m pytest -q`
Expected: PASS (68 + 1 new = 69).

- [ ] **Step 8: Commit**

```bash
git add app/models.py migrations/versions/020_commission_sync.py tests/test_commission_resolver.py
git commit -m "feat(commission): migration 020 — stub/source, policy flags, match_suggestions"
```

---

### Task 2: ResolveResult + crosswalk match (existing policy by carrier+member_id)

**Files:**
- Create: `app/commission/resolver.py`
- Test: `tests/test_commission_resolver.py`

The crosswalk is the deterministic monthly re-link: a `MemberFact` whose `(carrier, carrier_member_id)` matches an existing `Policy` reuses that policy's customer — no new stub.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_resolver.py`:
```python
def _seed_customer_with_policy(db, agency, agent, *, carrier, member_id, mbi=None,
                               first="Jane", last="Doe"):
    from app.models import Customer, Policy
    c = Customer(agency_id=agency.id, first_name=first, last_name=last,
                 full_name=f"{first} {last}", mbi=mbi, primary_agent_id=agent.id,
                 source="bob")
    db.session.add(c)
    db.session.flush()
    p = Policy(agency_id=agency.id, carrier=carrier, member_id=member_id, mbi=mbi,
              full_name=f"{first} {last}", status="active", agent_id=agent.id,
              customer_id=c.id)
    db.session.add(p)
    db.session.flush()
    return c, p


def test_crosswalk_reuses_existing_customer(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        c, p = _seed_customer_with_policy(
            db, agency, agent_user, carrier="BCBS", member_id="106815011",
            first="Brenda", last="Allen",
        )
        fact = MemberFact(
            carrier="BCBS", full_name="Allen,Brenda M", first_name="Brenda",
            last_name="Allen", carrier_member_id="106815011",
            row_class=RowClass.RENEWAL, amount=28.91,
        )
        result = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                                  source="commission_import")

        assert result.customer.id == c.id          # reused, not new
        assert result.created_customer is False
        assert result.match_path == "crosswalk"
        assert result.customer.stub is False        # existing real customer untouched
```

NOTE: `Policy.customer_id` was ADDED in Task 1 (migration 020). Planning confirmed it did not exist before — the app previously joined Policy↔Customer by MBI. Task 1 added the FK + backfilled it, so by the time this task runs `Policy.customer_id` exists and the crosswalk relies on it directly. (Quick confirm if desired: `python3 -c "from app.models import Policy; print('customer_id' in [c.name for c in Policy.__table__.columns])"` → should print `True`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_crosswalk_reuses_existing_customer -v`
Expected: FAIL — `ModuleNotFoundError: app.commission.resolver`.

- [ ] **Step 3: Implement the crosswalk**

The crosswalk returns `Customer.query.get(policy.customer_id)` for the matched policy (the FK added in Task 1).

Create `app/commission/resolver.py`:
```python
"""
app/commission/resolver.py

The ONE identity codepath for both commission upload and BOB upload. Turns a
MemberFact into a resolved (Customer, Policy) with lifecycle side effects
(carrier-switch terming, new AOR interval, rapid_disenroll flag) and, when it
cannot confidently match, a stub + a MatchSuggestion for human confirm.

Resolution order: crosswalk (Policy by carrier+member_id) → MBI → suggest-link →
stub. See docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md §2.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List

from app.extensions import db
from app.models import Customer, Policy
from app.commission.member_fact import MemberFact, RowClass


@dataclass
class ResolveResult:
    customer: Optional[Customer] = None
    policy: Optional[Policy] = None
    created_customer: bool = False
    created_policy: bool = False
    match_path: str = ""           # crosswalk | mbi | suggest_link | stub
    actions: List[str] = field(default_factory=list)


def _crosswalk(fact: MemberFact, agency_id: int):
    """Return existing Policy matched by (carrier, carrier_member_id), else None."""
    cid = (fact.carrier_member_id or "").strip()
    if not cid:
        return None
    return (Policy.query
            .filter_by(agency_id=agency_id, carrier=fact.carrier, member_id=cid)
            .first())


def resolve_customer(fact: MemberFact, *, agency_id: int, agent_id: Optional[int],
                     batch_id: Optional[int] = None, source: str = "commission_import"
                     ) -> ResolveResult:
    result = ResolveResult()

    # 1. Crosswalk — deterministic monthly re-link
    policy = _crosswalk(fact, agency_id)
    if policy is not None:
        customer = Customer.query.get(policy.customer_id) if policy.customer_id else None
        if customer is not None:
            result.customer = customer
            result.policy = policy
            result.match_path = "crosswalk"
            return result

    # later steps (MBI, suggest-link, stub) added in subsequent tasks
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_crosswalk_reuses_existing_customer -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/resolver.py tests/test_commission_resolver.py
git commit -m "feat(commission): resolver crosswalk — reuse customer by carrier+member_id"
```

---

### Task 3: MBI / humana_id match path

**Files:**
- Modify: `app/commission/resolver.py`
- Test: `tests/test_commission_resolver.py`

When the crosswalk misses but the fact has an MBI, reuse the existing customer by MBI (or `humana_id` for Humana) and attach a new Policy.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_resolver.py`:
```python
def test_mbi_match_reuses_customer_and_creates_policy(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        # existing customer with MBI but NO Aetna policy yet
        c = Customer(agency_id=agency.id, first_name="Bobby", last_name="Aderhold",
                     full_name="Bobby Aderhold", mbi="6CM1RV8NW05",
                     primary_agent_id=agent_user.id, source="bob")
        db.session.add(c)
        db.session.flush()

        fact = MemberFact(
            carrier="Aetna", full_name="ADERHOLD R,BOBBY", first_name="Bobby",
            last_name="Aderhold", mbi="6CM1RV8NW05", carrier_member_id="NG101350365000",
            plan_contract="H3146", plan_pbp="006", row_class=RowClass.RENEWAL, amount=28.92,
            effective_date=date(2026, 5, 1),
        )
        result = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                                  source="commission_import")

        assert result.customer.id == c.id
        assert result.match_path == "mbi"
        assert result.created_customer is False
        assert result.created_policy is True
        assert result.policy.carrier == "Aetna"
        assert result.policy.member_id == "NG101350365000"
        assert result.policy.customer_id == c.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_mbi_match_reuses_customer_and_creates_policy -v`
Expected: FAIL — `match_path` is "" and `result.policy` is None (MBI path not implemented).

- [ ] **Step 3: Implement the MBI path + a policy-creation helper**

In `app/commission/resolver.py`, add this helper above `resolve_customer`:
```python
def _attach_policy(fact: MemberFact, customer: Customer, agency_id: int,
                   agent_id: Optional[int]) -> Policy:
    """Create a Policy for this fact linked to the given customer."""
    p = Policy(
        agency_id=agency_id,
        carrier=fact.carrier,
        member_id=(fact.carrier_member_id or fact.mbi or "").strip(),
        mbi=fact.mbi,
        first_name=fact.first_name,
        last_name=fact.last_name,
        full_name=fact.full_name,
        plan_type=fact.plan_type,
        effective_date=fact.effective_date,
        term_date=fact.term_date,
        status="active",
        agent_id=agent_id,
        customer_id=customer.id,
    )
    db.session.add(p)
    db.session.flush()
    return p


def _match_by_mbi(fact: MemberFact, agency_id: int):
    """Return existing Customer by MBI (or humana_id for Humana), else None."""
    if fact.carrier == "Humana" and fact.mbi:
        c = Customer.query.filter_by(humana_id=fact.mbi, agency_id=agency_id).first()
        if c:
            return c
    if fact.mbi:
        return Customer.query.filter_by(mbi=fact.mbi, agency_id=agency_id).first()
    return None
```

Then in `resolve_customer`, REPLACE the comment line `# later steps ...` and the final `return result` with:
```python
    # 2. MBI / humana_id match
    customer = _match_by_mbi(fact, agency_id)
    if customer is not None:
        result.customer = customer
        result.policy = _attach_policy(fact, customer, agency_id, agent_id)
        result.created_policy = True
        result.match_path = "mbi"
        return result

    # later steps (suggest-link, stub) added in subsequent tasks
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_mbi_match_reuses_customer_and_creates_policy -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/resolver.py tests/test_commission_resolver.py
git commit -m "feat(commission): resolver MBI/humana_id match path + policy attach"
```

---

### Task 4: Stub creation (no match, no MBI) — stub-once guarantee

**Files:**
- Modify: `app/commission/resolver.py`
- Test: `tests/test_commission_resolver.py`

When nothing matches and there is no basis for a suggest-link, create a stub customer + policy. Re-running the same fact must hit the crosswalk (Task 2) and NOT create a second stub.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_resolver.py`:
```python
def test_stub_created_once_then_crosswalk_relinks(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        fact = MemberFact(
            carrier="BCBS", full_name="Newby,Sam", first_name="Sam", last_name="Newby",
            carrier_member_id="106999999", mbi=None,
            row_class=RowClass.ENROLLMENT, amount=0.0, effective_date=date(2026, 4, 1),
        )
        # First upload → stub created
        r1 = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                              source="commission_import")
        assert r1.created_customer is True
        assert r1.match_path == "stub"
        assert r1.customer.stub is True
        assert r1.customer.source == "commission_import"
        db.session.commit()

        # Second upload of the SAME fact → crosswalk re-link, NO new stub
        r2 = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                              source="commission_import")
        assert r2.created_customer is False
        assert r2.match_path == "crosswalk"
        assert r2.customer.id == r1.customer.id

        # Exactly one customer + one policy exist for this member
        assert Customer.query.filter_by(agency_id=agency.id).count() == 1
        assert Policy.query.filter_by(agency_id=agency.id, member_id="106999999").count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_stub_created_once_then_crosswalk_relinks -v`
Expected: FAIL — `r1.match_path` is "" / `r1.customer` is None (stub path not implemented).

- [ ] **Step 3: Implement the stub path**

In `app/commission/resolver.py`, add this helper above `resolve_customer`:
```python
def _create_stub(fact: MemberFact, agency_id: int, agent_id: Optional[int],
                 source: str) -> Customer:
    """Create a stub Customer from whatever the fact provides."""
    humana_id = fact.mbi if fact.carrier == "Humana" else None
    c = Customer(
        agency_id=agency_id,
        mbi=fact.mbi if fact.carrier != "Humana" else None,
        humana_id=humana_id,
        first_name=fact.first_name or "",
        last_name=fact.last_name or "",
        full_name=fact.full_name or f"{fact.first_name} {fact.last_name}".strip(),
        primary_agent_id=agent_id,
        stub=True,
        source=source,
    )
    db.session.add(c)
    db.session.flush()
    return c
```

Then in `resolve_customer`, REPLACE the `# later steps (suggest-link, stub) ...` comment and the final `return result` with:
```python
    # 4. Stub — nothing matched; create stub customer + policy (at most once per member,
    #    because next time the crosswalk in step 1 will find this policy).
    customer = _create_stub(fact, agency_id, agent_id, source)
    result.customer = customer
    result.created_customer = True
    result.policy = _attach_policy(fact, customer, agency_id, agent_id)
    result.created_policy = True
    result.match_path = "stub"
    return result
```

(The suggest-link path is inserted BEFORE this stub block in Task 6.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_stub_created_once_then_crosswalk_relinks -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/resolver.py tests/test_commission_resolver.py
git commit -m "feat(commission): resolver stub path with stub-once guarantee"
```

---

### Task 5: AOR interval + carrier-switch terming + rapid_disenroll

**Files:**
- Modify: `app/commission/resolver.py`
- Test: `tests/test_commission_resolver.py`

After a customer/policy is resolved, apply lifecycle: open an AOR interval for ENROLLMENT/RENEWAL; on a carrier switch (customer has an active policy on a DIFFERENT carrier and this fact is ENROLLMENT) term the old policy + open a new interval; set `rapid_disenroll` when `term_date - effective_date < 90d`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_commission_resolver.py`:
```python
def test_rapid_disenroll_flag_set_when_under_90_days(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        fact = MemberFact(
            carrier="Devoted", full_name="Elizabeth Bolder", first_name="Elizabeth",
            last_name="Bolder", carrier_member_id="DS97W3", mbi="1X57MJ7FA64",
            row_class=RowClass.CHARGEBACK, amount=-347.0,
            effective_date=date(2026, 1, 1), term_date=date(2026, 3, 31),  # < 90d
        )
        r = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                             source="commission_import")
        assert r.policy.rapid_disenroll is True
        assert "rapid_disenroll" in r.actions


def test_carrier_switch_terms_old_policy_and_opens_new_interval(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy, CustomerAorHistory
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        # Existing customer on Humana (active), with MBI
        c = Customer(agency_id=agency.id, first_name="Dorothy", last_name="Smith",
                     full_name="Dorothy Smith", mbi="9ZZ9ZZ9ZZ99",
                     primary_agent_id=agent_user.id, source="bob")
        db.session.add(c); db.session.flush()
        old = Policy(agency_id=agency.id, carrier="Humana", member_id="PID123",
                     mbi="9ZZ9ZZ9ZZ99", status="active", agent_id=agent_user.id,
                     customer_id=c.id, effective_date=date(2025, 1, 1))
        db.session.add(old); db.session.flush()

        # New BCBS enrollment for same human (MBI present in this test so it links)
        fact = MemberFact(
            carrier="BCBS", full_name="Smith,Dorothy", first_name="Dorothy",
            last_name="Smith", carrier_member_id="106800000", mbi="9ZZ9ZZ9ZZ99",
            row_class=RowClass.ENROLLMENT, amount=0.0, effective_date=date(2026, 1, 1),
        )
        r = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                             source="commission_import")

        assert r.customer.id == c.id
        db.session.refresh(old)
        assert old.status == "termed"                  # old carrier policy termed
        assert "carrier_switch" in r.actions
        # a new AOR interval opened for BCBS
        intervals = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="BCBS").all()
        assert len(intervals) == 1
        assert intervals[0].end_date is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_commission_resolver.py -k "rapid_disenroll or carrier_switch" -v`
Expected: FAIL — `actions` empty, `rapid_disenroll` not set, old policy still "active".

- [ ] **Step 3: Implement lifecycle**

In `app/commission/resolver.py`, update imports at top:
```python
from app.models import Customer, Policy, CustomerAorHistory
```
Add these helpers above `resolve_customer`:
```python
def _apply_rapid_disenroll(policy: Policy, fact: MemberFact, result: ResolveResult):
    eff, term = fact.effective_date, fact.term_date
    if eff and term and (term - eff).days < 90:
        policy.rapid_disenroll = True
        result.actions.append("rapid_disenroll")


def _apply_carrier_switch(fact: MemberFact, customer: Customer, new_policy: Policy,
                          agency_id: int, agent_id, result: ResolveResult):
    """If customer has an active policy on a different carrier and this is an
    ENROLLMENT, term the old policy. (Same-carrier renewals are not switches.)"""
    if fact.row_class != RowClass.ENROLLMENT:
        return
    others = (Policy.query
              .filter(Policy.agency_id == agency_id,
                      Policy.customer_id == customer.id,
                      Policy.carrier != fact.carrier,
                      Policy.status == "active")
              .all())
    for old in others:
        old.status = "termed"
        old.new_carrier = fact.carrier
        if not old.term_date and fact.effective_date:
            old.term_date = fact.effective_date
        result.actions.append("carrier_switch")


def _open_aor_interval(fact: MemberFact, customer: Customer, agency_id: int,
                       agent_id, batch_id, result: ResolveResult):
    """Open an AOR interval if one doesn't already exist for this
    customer+carrier+effective_date. BCBS term_date is a renewal date — never an end_date."""
    if not fact.effective_date:
        return
    existing = CustomerAorHistory.query.filter_by(
        customer_id=customer.id, carrier=fact.carrier, effective_date=fact.effective_date,
    ).first()
    if existing:
        return
    end_date = None if fact.carrier == "BCBS" else fact.term_date
    aor = CustomerAorHistory(
        agency_id=agency_id, customer_id=customer.id, agent_id=agent_id,
        carrier=fact.carrier, plan_name=None, effective_date=fact.effective_date,
        end_date=end_date, source=result.match_path or "commission_import",
        import_batch_id=batch_id,
    )
    db.session.add(aor)
    result.actions.append("aor_interval")
```

Then, in `resolve_customer`, apply lifecycle to EVERY non-crosswalk resolution that produced a policy. Refactor so the MBI, suggest-link, and stub branches each call a shared finalizer. Simplest: before each `return result` in the MBI and stub branches (NOT the crosswalk branch, which is an existing policy/interval), insert:
```python
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result)
```
Place those three lines immediately BEFORE `return result` in the MBI branch and the stub branch. (The crosswalk branch returns early without lifecycle, since the policy + interval already exist from the prior import.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_commission_resolver.py -k "rapid_disenroll or carrier_switch" -v`
Expected: PASS (both)

- [ ] **Step 5: Run the resolver suite to confirm no regression**

Run: `python3 -m pytest tests/test_commission_resolver.py -v`
Expected: PASS (all resolver tests so far)

- [ ] **Step 6: Commit**

```bash
git add app/commission/resolver.py tests/test_commission_resolver.py
git commit -m "feat(commission): resolver AOR intervals, carrier-switch terming, rapid_disenroll"
```

---

### Task 6: Suggest-link path (no MBI, name+DOB near-match → MatchSuggestion)

**Files:**
- Modify: `app/commission/resolver.py`
- Test: `tests/test_commission_resolver.py`

When there's no crosswalk and no MBI, but the fact's name+DOB matches an existing customer, create the stub AND enqueue a `MatchSuggestion` (never auto-merge). Runs BEFORE the plain stub fallback.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_resolver.py`:
```python
def test_suggest_link_creates_stub_and_suggestion_no_automerge(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, MatchSuggestion
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        # Existing full customer with name + DOB but no BCBS policy / no MBI overlap
        existing = Customer(agency_id=agency.id, first_name="Mark", last_name="Brown",
                            full_name="Mark Brown", dob=date(1950, 4, 2),
                            primary_agent_id=agent_user.id, source="bob")
        db.session.add(existing); db.session.flush()

        # New BCBS enrollment, NO MBI, name+DOB match → suggest, do NOT merge
        fact = MemberFact(
            carrier="BCBS", full_name="Brown,Mark", first_name="Mark", last_name="Brown",
            dob=date(1950, 4, 2), carrier_member_id="106777777", mbi=None,
            row_class=RowClass.ENROLLMENT, amount=0.0, effective_date=date(2026, 1, 1),
        )
        r = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                             source="commission_import")

        # A NEW stub was created (payment not lost), distinct from the existing customer
        assert r.created_customer is True
        assert r.customer.id != existing.id
        assert r.customer.stub is True
        assert r.match_path == "suggest_link"
        assert "match_suggestion" in r.actions

        # A pending MatchSuggestion links the stub to the existing customer
        ms = MatchSuggestion.query.filter_by(agency_id=agency.id, status="pending").first()
        assert ms is not None
        assert ms.suggested_customer_id == existing.id
        assert ms.stub_customer_id == r.customer.id
        assert ms.confidence == "name_dob"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_suggest_link_creates_stub_and_suggestion_no_automerge -v`
Expected: FAIL — `match_path` is "stub", no `MatchSuggestion` row.

- [ ] **Step 3: Implement the suggest-link path**

In `app/commission/resolver.py`, update imports:
```python
import json
from app.models import Customer, Policy, CustomerAorHistory, MatchSuggestion
```
Add this helper above `resolve_customer`:
```python
def _find_name_dob_match(fact: MemberFact, agency_id: int):
    """Return (customer, confidence) for a name+DOB near-match, else (None, None).
    Only fires when DOB is present (BCBS rows have no DOB, so they won't match
    until DOB exists from a prior BOB record/edit)."""
    fn = (fact.first_name or "").strip().lower()
    ln = (fact.last_name or "").strip().lower()
    if not fn or not ln or not fact.dob:
        return None, None
    c = (Customer.query
         .filter(Customer.agency_id == agency_id,
                 db.func.lower(Customer.first_name) == fn,
                 db.func.lower(Customer.last_name) == ln,
                 Customer.dob == fact.dob)
         .first())
    if c:
        return c, "name_dob"
    return None, None
```

Then in `resolve_customer`, INSERT this block immediately BEFORE the `# 4. Stub` block:
```python
    # 3. Suggest-link — no crosswalk, no MBI, but a name+DOB near-match exists.
    #    Create a stub (so no payment is lost) AND a MatchSuggestion for human confirm.
    candidate, confidence = _find_name_dob_match(fact, agency_id)
    if candidate is not None:
        customer = _create_stub(fact, agency_id, agent_id, source)
        result.customer = customer
        result.created_customer = True
        result.policy = _attach_policy(fact, customer, agency_id, agent_id)
        result.created_policy = True
        result.match_path = "suggest_link"
        ms = MatchSuggestion(
            agency_id=agency_id,
            stub_customer_id=customer.id,
            suggested_customer_id=candidate.id,
            confidence=confidence,
            status="pending",
            source_member_fact_json=json.dumps({
                "carrier": fact.carrier, "carrier_member_id": fact.carrier_member_id,
                "full_name": fact.full_name, "dob": fact.dob.isoformat() if fact.dob else None,
            }),
        )
        db.session.add(ms)
        result.actions.append("match_suggestion")
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result)
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_suggest_link_creates_stub_and_suggestion_no_automerge -v`
Expected: PASS

- [ ] **Step 5: Run the full resolver suite**

Run: `python3 -m pytest tests/test_commission_resolver.py -v`
Expected: PASS (all). Confirm the plain-stub test still passes (a fact with no name+DOB match still falls through to stub).

- [ ] **Step 6: Commit**

```bash
git add app/commission/resolver.py tests/test_commission_resolver.py
git commit -m "feat(commission): resolver suggest-link path (stub + MatchSuggestion, no auto-merge)"
```

---

### Task 7: Characterization tests pinning current BOB _upsert behavior

**Files:**
- Test: `tests/test_bob_upsert_characterization.py`

Before refactoring `_upsert_customer_from_policy`, lock its observable behavior so the refactor cannot regress BOB import. These tests describe what it does TODAY.

- [ ] **Step 1: Write the characterization tests**

Create `tests/test_bob_upsert_characterization.py`:
```python
"""
tests/test_bob_upsert_characterization.py

Pins the CURRENT observable behavior of _upsert_customer_from_policy BEFORE it is
refactored to delegate to resolve_customer(). If a test here breaks during the
refactor, the refactor changed BOB behavior — investigate, don't just update.
"""
from datetime import date


def test_bob_creates_customer_by_mbi(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer
    from app.upload import _upsert_customer_from_policy

    with app.app_context():
        rec = {
            "carrier": "UHC", "mbi": "8NP5GM6TK40",
            "first_name": "Ricky", "last_name": "Sweatt", "full_name": "Ricky Sweatt",
            "dob": date(1948, 3, 1), "phone": "7045550100",
            "address1": "1 Main St", "city": "Charlotte", "state": "NC",
            "zip_code": "28202", "county": "Mecklenburg",
            "plan_name": "UHC DSNP", "effective_date": date(2026, 1, 1),
        }
        _upsert_customer_from_policy(rec, agent_user.id, None, agency.id)
        db.session.commit()
        c = Customer.query.filter_by(mbi="8NP5GM6TK40", agency_id=agency.id).first()
        assert c is not None
        assert c.first_name == "Ricky"
        assert c.primary_agent_id == agent_user.id


def test_bob_does_not_overwrite_manually_edited_pii(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer
    from app.upload import _upsert_customer_from_policy

    with app.app_context():
        c = Customer(agency_id=agency.id, mbi="MBIEDIT01", first_name="Original",
                     last_name="Name", full_name="Original Name", phone_primary="111",
                     manually_edited=True, primary_agent_id=agent_user.id)
        db.session.add(c); db.session.commit()

        rec = {"carrier": "UHC", "mbi": "MBIEDIT01", "first_name": "Changed",
               "last_name": "Different", "phone": "999", "effective_date": date(2026, 1, 1)}
        _upsert_customer_from_policy(rec, agent_user.id, None, agency.id)
        db.session.commit()
        db.session.refresh(c)
        # manually_edited → PII preserved
        assert c.first_name == "Original"
        assert c.phone_primary == "111"


def test_bob_humana_matches_by_humana_id(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer
    from app.upload import _upsert_customer_from_policy

    with app.app_context():
        rec = {"carrier": "Humana", "mbi": None, "member_id": "HUM12345",
               "first_name": "Anna", "last_name": "Lee", "full_name": "Anna Lee",
               "effective_date": date(2026, 1, 1)}
        _upsert_customer_from_policy(rec, agent_user.id, None, agency.id)
        db.session.commit()
        c = Customer.query.filter_by(humana_id="HUM12345", agency_id=agency.id).first()
        assert c is not None


def test_bob_bcbs_aor_end_date_is_none(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, CustomerAorHistory
    from app.upload import _upsert_customer_from_policy

    with app.app_context():
        rec = {"carrier": "BCBS", "mbi": None, "first_name": "Bob", "last_name": "Cee",
               "full_name": "Bob Cee", "effective_date": date(2026, 1, 1),
               "term_date": date(2026, 12, 31)}
        _upsert_customer_from_policy(rec, agent_user.id, None, agency.id)
        db.session.commit()
        c = Customer.query.filter_by(agency_id=agency.id, last_name="Cee").first()
        aor = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="BCBS").first()
        assert aor is not None
        assert aor.end_date is None     # BCBS term_date never becomes an AOR end_date
```

- [ ] **Step 2: Run characterization tests against CURRENT code (must pass as-is)**

Run: `python3 -m pytest tests/test_bob_upsert_characterization.py -v`
Expected: PASS (all 4) — they describe current behavior, so they pass before any refactor. If any FAILS now, the test's assumption about current behavior is wrong — fix the test to match what the code actually does (inspect `_upsert_customer_from_policy`), do NOT change the code in this task.

- [ ] **Step 3: Commit**

```bash
git add tests/test_bob_upsert_characterization.py
git commit -m "test(bob): characterization tests pinning _upsert_customer_from_policy behavior"
```

---

### Task 8: Refactor _upsert_customer_from_policy to delegate to resolve_customer

**Files:**
- Modify: `app/upload.py`
- Test: `tests/test_bob_upsert_characterization.py` (must stay green), `tests/test_commission_resolver.py`

Build a `rec → MemberFact` adapter and route BOB upsert through the resolver, preserving the `manually_edited` PII guard and BCBS rule. The characterization tests (Task 7) are the safety net.

- [ ] **Step 1: Add a rec→MemberFact adapter to the resolver**

In `app/commission/resolver.py`, add:
```python
def member_fact_from_bob_rec(rec: dict) -> MemberFact:
    """Adapt a BOB upload `rec` dict to a MemberFact so BOB upload can route
    through the same resolver. BOB rows are enrollments/renewals (never the
    commission chargeback rows), so row_class defaults to RENEWAL unless there's
    no prior policy — the resolver's lifecycle handles interval opening."""
    carrier = rec.get("carrier", "")
    return MemberFact(
        carrier=carrier,
        full_name=rec.get("full_name") or f"{rec.get('first_name','')} {rec.get('last_name','')}".strip(),
        first_name=rec.get("first_name") or "",
        last_name=rec.get("last_name") or "",
        mbi=(rec.get("mbi") or None),
        carrier_member_id=(rec.get("member_id") or None),
        dob=rec.get("dob"),
        effective_date=rec.get("effective_date"),
        term_date=rec.get("term_date"),
        plan_type=rec.get("plan_type"),
        row_class=RowClass.RENEWAL,
        amount=0.0,
    )
```

NOTE: The resolver currently CREATES customers but does not copy full PII (phone/address/etc.) onto them the way BOB's `_upsert` does, nor does it apply the `manually_edited` guard or update existing-customer contact fields. To preserve BOB behavior, the BOB path must still apply PII updates AFTER resolution. So the refactor keeps `_upsert_customer_from_policy` as the BOB entry point but delegates IDENTITY to the resolver, then applies BOB's PII rules to the resolved customer. See Step 3.

- [ ] **Step 2: Run characterization tests (still green before refactor)**

Run: `python3 -m pytest tests/test_bob_upsert_characterization.py -v`
Expected: PASS (unchanged).

- [ ] **Step 3: Refactor `_upsert_customer_from_policy`**

In `app/upload.py`, add near the top imports:
```python
from app.commission.resolver import resolve_customer, member_fact_from_bob_rec
```
Replace the body of `_upsert_customer_from_policy` (the function defined at line 24) with a version that delegates identity resolution then applies BOB PII rules. Replace the WHOLE function with:
```python
def _upsert_customer_from_policy(rec: dict, agent_id: int, batch_id: int, agency_id: int) -> None:
    """
    Create or update a Customer from a parsed BOB policy row.

    Identity resolution (crosswalk → MBI → name+DOB → stub) is delegated to the
    shared resolve_customer() service so BOB and commission upload share ONE
    identity codepath. BOB-specific PII rules are applied here afterward:
    - manually_edited customers keep their contact/address fields.
    - BCBS AOR end_date stays None (handled inside the resolver's interval logic).
    """
    fact = member_fact_from_bob_rec(rec)
    result = resolve_customer(fact, agency_id=agency_id, agent_id=agent_id,
                              batch_id=batch_id, source="bob")
    customer = result.customer
    if customer is None:
        return

    now = datetime.utcnow()
    full_name = rec.get("full_name") or f"{rec.get('first_name', '')} {rec.get('last_name', '')}".strip()
    address_parts = [rec.get("address1"), rec.get("city"), rec.get("state"), rec.get("zip_code")]
    carrier_address = ", ".join(p for p in address_parts if p)

    # A BOB row is authoritative carrier data → clear the stub flag if set.
    if customer.stub:
        customer.stub = False
    customer.last_carrier_sync = now
    customer.carrier_address = carrier_address
    mbi = rec.get("mbi") or None
    humana_id = rec.get("member_id") if rec.get("carrier") == "Humana" else None
    if mbi and not customer.mbi:
        customer.mbi = mbi
    if humana_id and not customer.humana_id:
        customer.humana_id = humana_id

    if not customer.manually_edited:
        customer.first_name = rec.get("first_name") or customer.first_name
        customer.last_name = rec.get("last_name") or customer.last_name
        customer.full_name = full_name or customer.full_name
        customer.dob = rec.get("dob") or customer.dob
        customer.phone_primary = rec.get("phone") or customer.phone_primary
        customer.address1 = rec.get("address1") or customer.address1
        customer.city = rec.get("city") or customer.city
        customer.state = rec.get("state") or customer.state
        customer.zip_code = rec.get("zip_code") or customer.zip_code
        customer.county = rec.get("county") or customer.county

    # Agent ownership transfer: close previous agent's open AOR row for this carrier.
    if customer.primary_agent_id and customer.primary_agent_id != agent_id:
        open_aor = CustomerAorHistory.query.filter_by(
            customer_id=customer.id, agent_id=customer.primary_agent_id,
            carrier=rec.get("carrier", ""), end_date=None,
        ).first()
        if open_aor:
            open_aor.end_date = now.date()
    customer.primary_agent_id = agent_id
```

IMPORTANT preservation notes for the implementer:
- The resolver already opens the AOR interval (Task 5 `_open_aor_interval`) with BCBS end_date=None and dedups by customer+carrier+effective_date — so DELETE the old AOR-insert block that used to live at the end of this function (it's now the resolver's job). The characterization test `test_bob_bcbs_aor_end_date_is_none` proves the interval is still correct.
- Do NOT keep the old identity-matching code (MBI/humana/name lookups) in this function — that is now the resolver's job. If you leave it in, you get double-creation.
- The `plan_name` on the AOR interval: BOB's old code set `plan_name=rec.get("plan_name")`. The resolver's `_open_aor_interval` currently sets `plan_name=None`. If the characterization tests don't assert plan_name, this is acceptable; if you want parity, pass plan_name through MemberFact (optional, only if a test requires it).

- [ ] **Step 4: Run characterization tests (the safety net)**

Run: `python3 -m pytest tests/test_bob_upsert_characterization.py -v`
Expected: PASS (all 4). If any fail, the refactor changed BOB behavior — fix the resolver/adapter until they pass again. Do NOT weaken the characterization tests.

- [ ] **Step 5: Run the entire suite**

Run: `python3 -m pytest -q`
Expected: PASS. In particular the existing BOB/agency-scoping tests (`tests/test_agency_scoping.py`) must stay green.

- [ ] **Step 6: Commit**

```bash
git add app/upload.py app/commission/resolver.py
git commit -m "refactor(bob): route _upsert_customer_from_policy through resolve_customer"
```

---

### Task 9: Make get_customer_policies FK-first (so commission/BCBS policies appear)

**Files:**
- Modify: `app/customers.py`
- Test: `tests/test_commission_resolver.py`

The customer profile lists policies via `get_customer_policies`, which joins by MBI. A commission-created BCBS policy has no MBI, so it links to its customer ONLY through the new `customer_id` FK. Make the function FK-first, keeping the MBI/Humana join as fallback for legacy policies whose FK backfill may have missed them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_resolver.py`:
```python
def test_get_customer_policies_finds_fk_linked_bcbs_no_mbi(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy
    from app.customers import get_customer_policies

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Sam", last_name="Newby",
                     full_name="Sam Newby", mbi=None, stub=True,
                     source="commission_import", primary_agent_id=agent_user.id)
        db.session.add(c); db.session.flush()
        p = Policy(agency_id=agency.id, carrier="BCBS", member_id="106999999",
                   mbi=None, status="active", agent_id=agent_user.id, customer_id=c.id,
                   full_name="Sam Newby")
        db.session.add(p); db.session.commit()

        policies = get_customer_policies(c)
        assert any(pol.carrier == "BCBS" and pol.member_id == "106999999"
                   for pol in policies)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_get_customer_policies_finds_fk_linked_bcbs_no_mbi -v`
Expected: FAIL — the no-MBI BCBS policy isn't found (current code only joins by MBI, and `customer.mbi` is None).

- [ ] **Step 3: Make get_customer_policies FK-first**

In `app/customers.py`, the `get_customer_policies(customer)` function currently starts (around line 41) with an MBI-only query. Modify it so the FK link is checked FIRST and merged with the existing MBI/Humana results without duplicating. Replace the function's policy-collection logic: at the very start of building `policies`, add a FK query and track seen policy ids. Concretely, change the beginning of the function body from:
```python
    policies = []
    agency_id = customer.agency_id

    if customer.mbi:
        policies = Policy.query.filter_by(
            mbi=customer.mbi, agency_id=agency_id
        ).order_by(Policy.carrier).all()
```
to:
```python
    policies = []
    agency_id = customer.agency_id

    # FK-first: policies explicitly linked to this customer (works for no-MBI carriers).
    policies = Policy.query.filter_by(
        customer_id=customer.id, agency_id=agency_id
    ).order_by(Policy.carrier).all()
    seen_ids = {p.id for p in policies}

    # MBI join (legacy link) — add any not already found via FK.
    if customer.mbi:
        for p in Policy.query.filter_by(mbi=customer.mbi, agency_id=agency_id).all():
            if p.id not in seen_ids:
                policies.append(p)
                seen_ids.add(p.id)
```
IMPORTANT: the rest of the function (the Humana phone+DOB fallback, the dedup-by-carrier logic, the return) must continue to work. Read the full function first. If it later references `seen_ids` or assumes `policies` came only from MBI, reconcile — the goal is: FK policies + MBI policies + Humana-fallback policies, no duplicate Policy.id. If the existing code already builds its own dedup set under a different name, integrate with it rather than introducing a parallel `seen_ids`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_resolver.py::test_get_customer_policies_finds_fk_linked_bcbs_no_mbi -v`
Expected: PASS

- [ ] **Step 5: Run the full suite (profile/customer tests must stay green)**

Run: `python3 -m pytest -q`
Expected: PASS. Pay attention to any existing customer-profile tests — the FK-first change must not drop MBI-linked policies.

- [ ] **Step 6: Commit**

```bash
git add app/customers.py tests/test_commission_resolver.py
git commit -m "feat(customers): get_customer_policies FK-first so commission/BCBS policies appear"
```

---

### Task 10: Full-suite green + resolver public surface

**Files:**
- Modify: `app/commission/resolver.py`
- Test: full suite

- [ ] **Step 1: Confirm the resolver's public surface**

Ensure `app/commission/resolver.py` exposes exactly: `resolve_customer`, `ResolveResult`, `member_fact_from_bob_rec`. Add a module-level `__all__`:
```python
__all__ = ["resolve_customer", "ResolveResult", "member_fact_from_bob_rec"]
```

- [ ] **Step 2: Run the entire suite**

Run: `python3 -m pytest -q`
Expected: PASS (Plan 1 normalizer tests + resolver tests + BOB characterization + existing suites). Record the count.

- [ ] **Step 3: Commit**

```bash
git add app/commission/resolver.py
git commit -m "feat(commission): export resolver public surface"
```

---

## Self-Review

**1. Spec coverage (Plan 2 = spec §2 resolver + §3 data model):**
- Migration 020: stub/source/rapid_disenroll/commission_split_flag + match_suggestions + **policies.customer_id FK with MBI backfill** (spec §3, extended during planning) → Task 1. ✓
- **Policy↔Customer FK link + FK-first profile join** (root-cause fix for invisible/BCBS policies) → Task 1 + Task 9. ✓
- Crosswalk by (carrier, member_id) (spec §2 path 1) → Task 2. ✓
- MBI/humana_id reuse (spec §2 path 2) → Task 3. ✓
- Suggest-link → MatchSuggestion, no auto-merge (spec §2 path 3) → Task 6. ✓
- Stub-once (spec §2 path 4 + decision #2/#3) → Task 4. ✓
- Carrier-switch term + new interval (spec decision #7) → Task 5. ✓
- rapid_disenroll <90d (spec decision #8) → Task 5. ✓
- One identity codepath / BOB routes through resolver (spec architecture, decision: MemberFact for both) → Tasks 7–8. ✓
- manually_edited guard + BCBS end_date=None preserved (spec Database Rules) → Tasks 7 (pin) + 8 (preserve). ✓
- NOT in this plan (correctly deferred): PolicyPayment writes, duplicate-statement guard, split/auth math, import-modal tabs, UHC (Plans 4–6). ✓

**2. Placeholder scan:** No TBD/TODO. Every code step shows full code. Task 2 Step 3 and Task 8 Step 3 contain conditional guidance (verify Policy.customer_id; preserve PII) with the exact code to write — these are real instructions, not placeholders. The BLOCKED instruction in Task 2 is a genuine safety gate (the crosswalk depends on the Policy↔Customer link existing).

**3. Type consistency:** `MemberFact` fields used (carrier, carrier_member_id, mbi, dob, effective_date, term_date, row_class, plan_type, first_name, last_name, full_name, amount) all exist in Plan 1's dataclass. `ResolveResult` fields (customer, policy, created_customer, created_policy, match_path, actions) consistent across Tasks 2–8. `match_path` values (crosswalk/mbi/suggest_link/stub) consistent. `RowClass.ENROLLMENT` used in carrier-switch + suggest-link. Model attrs (Customer.stub/source/humana_id/mbi/manually_edited/primary_agent_id, Policy.customer_id/carrier/member_id/status/term_date/new_carrier/rapid_disenroll, CustomerAorHistory.effective_date/end_date/carrier, MatchSuggestion.stub_customer_id/suggested_customer_id/confidence/status) match Task 1's definitions and the existing models read during planning.

**Resolved during planning:** The original draft assumed `Policy.customer_id` existed — verification showed it did NOT (Policy↔Customer was an MBI-only query-time join, the root cause of invisible commission customers and BCBS fragility). Plan revised: Task 1 ADDS the FK + backfills it by MBI; Task 9 makes the profile join FK-first. The crosswalk now rests on a real FK, not the absent one.

**Remaining execution note:** Task 1's migration backfill uses Postgres `UPDATE ... FROM` syntax (production is Postgres 16). The SQLite test path does NOT run the Alembic migration (conftest uses `db.create_all()` from models), so the backfill SQL is exercised only on deploy — review it carefully at deploy time. The ORM-column test (Task 1) covers the schema; the backfill is deploy-only.
