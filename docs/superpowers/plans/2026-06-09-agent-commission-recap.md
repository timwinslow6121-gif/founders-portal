# Agent Commission Recap (R2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A live, agent-facing single-screen commission recap built on the R1 ledger — headline KPIs, per-carrier cards with a click-to-drill-down "prove the math" view (summary-first + search + expandable groups), and a YTD comparison strip — published per-period by AJ (who enters UHC manually until R4) and notified to the agent.

**Architecture:** A pure-ish assembler (`app/commission/recap.py`) turns `(agent, agency, period)` into a `RecapView` data object from `CommissionLineItem` (commissions/line items, via R1's `split_breakdown`), `Policy` (lost members, % of book), and a new `AgentRecapPeriod` row (workflow state + AJ's manual UHC figure + optional prior-year baseline). Routes render a single Jinja template with the Founders Material-3 look; a JSON endpoint lazy-loads big-carrier group line items + search. A small `app/mailer.py` (factored from the labels.py SendGrid usage) sends the publish notification.

**Tech Stack:** Python 3.10, Flask-SQLAlchemy, Flask-Migrate (Alembic), Jinja2, vanilla JS, SendGrid, pytest + SQLite in-memory. Fonts Plus Jakarta Sans + Merriweather; palette from the Founders Kadence export.

---

## Decisions locked (from the approved spec + verification)

- **One source of truth:** per-carrier figures + line items derive LIVE from `CommissionLineItem`; `AgentRecapPeriod` stores only workflow state + `uhc_manual_amount` + optional `prior_year_total`.
- **New-vs-renewal is per-carrier text, NOT a clean flag.** The R1 ledger's `payment_type` is the carrier's native string: Devoted `initial - new`/`initial - not new`/`renewal - monthly`; Humana txn codes (`arcm`=renewal, `arcf`/`med2`/`iccf`/`icfa`=new); BCBS `fy`/`new`/`renew`; Aetna `renewal`/`pro-rata payment`/`pro-rata disenroll`; HealthSpring payment-type text. R2 needs a tested `is_new_enrollment(carrier, classification, payment_type)` helper with a per-carrier map. (Verified against live ledger 2026-06-09.)
- **Drill-down = Option C:** summary grouped by type (New / Chargebacks / Renewals) + persistent member search + groups expand to line items; big groups lazy-load via JSON. Reconciliation footer proves the total.
- **UHC:** AJ-entered figure shown as a carrier card tagged "entered by AJ." No UHC ledger extractor (R4).
- **Publish workflow:** draft (auto) → AJ sets UHC + publishes → agent notified (idempotent).
- **Visual:** scoped stylesheet using Founders tokens; only global change to `base.html` is adding the Google Fonts link + the nav item. Full re-theme is a later project.

## Data field reference (verified, do not re-derive)

- `CommissionLineItem`: `agency_id, statement_id, carrier, period_label, statement_date, source_ref, agent_id (nullable), customer_id (nullable), member_name, mbi, carrier_member_id, raw_amount, split_rate (nullable), classification ∈ {agent_commission,founders_override,hra_bonus,chargeback}, payment_type (carrier text)`.
- `app.commission.ledger.split_breakdown(line) -> (agent_payout, founders_keep)` — reuse for per-line payout.
- `Policy`: `carrier, member_id, agent_id (FK users), effective_date, term_date, status (active|termed|...), plan_name, mbi`. Lost members = Policy where `agent_id=agent, carrier=X, term_date in period, status='termed'`.
- `User`: `id, name, email, is_admin, role, agency_id`. `models.can_edit_shared_data(user)` exists; admin = `is_admin`.
- `commission_bp = Blueprint("commission", __name__)` in `app/commission/__init__.py`; routes use `/commissions` (agent) and `/admin/commissions` (admin).
- Email: `app/labels.py` uses `SendGridAPIClient` + `Mail`; config keys `SENDGRID_API_KEY`, `LABELS_FROM_EMAIL`. Factor a generic sender.
- Migration head = **023**; R2 = **024**.

## File structure

- **Modify** `app/models.py` — add `AgentRecapPeriod` model.
- **Create** `migrations/versions/024_agent_recap_period.py`.
- **Create** `app/commission/recap.py` — `is_new_enrollment`, `CARRIER_BRAND` map, `RecapView`/`CarrierBlock`/`LineRow` dataclasses, `build_recap(agent_id, agency_id, period_label)`, helpers for YTD/run-rate/lost-members.
- **Create** `app/mailer.py` — `send_email(to, subject, text, html=None)`.
- **Modify** `app/commission/routes.py` — agent + admin recap routes, publish action, set-UHC/prior-year action, JSON carrier-detail endpoint.
- **Create** `app/templates/commission/recap.html` — single-screen page + drill-down, scoped styles.
- **Modify** `app/templates/base.html` — add Google Fonts link + "My Commissions" nav item.
- **Create** `tests/test_commission_recap.py`.

---

### Task 1: `is_new_enrollment` per-carrier classifier

**Files:**
- Create: `app/commission/recap.py`
- Test: `tests/test_commission_recap.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_commission_recap.py`:

```python
"""
tests/test_commission_recap.py
R2 agent commission recap: per-carrier new-vs-renewal classification, the recap
assembler, publish workflow, access scoping. SQLite in-memory via conftest.
"""


def test_is_new_enrollment_per_carrier():
    from app.commission.recap import is_new_enrollment as nu

    # Devoted: both "initial - new" and "initial - not new" are new enrollments
    assert nu("Devoted", "agent_commission", "initial - new") is True
    assert nu("Devoted", "agent_commission", "initial - not new") is True
    assert nu("Devoted", "agent_commission", "renewal - monthly") is False
    # Humana transaction codes
    assert nu("Humana", "agent_commission", "arcf") is True
    assert nu("Humana", "agent_commission", "med2") is True
    assert nu("Humana", "agent_commission", "arcm") is False
    # BCBS group types
    assert nu("BCBS", "agent_commission", "fy") is True
    assert nu("BCBS", "agent_commission", "new") is True
    assert nu("BCBS", "agent_commission", "renew") is False
    # Aetna sales events
    assert nu("Aetna", "agent_commission", "pro-rata payment") is True
    assert nu("Aetna", "agent_commission", "renewal") is False
    # Chargebacks / overrides / hra are never "new members"
    assert nu("Devoted", "chargeback", "initial - new") is False
    assert nu("Devoted", "founders_override", "override") is False
    assert nu("Devoted", "hra_bonus", "hra") is False
    # Unknown carrier/type → conservative False
    assert nu("UHC", "agent_commission", "whatever") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_recap.py::test_is_new_enrollment_per_carrier -v`
Expected: FAIL — `No module named 'app.commission.recap'`

- [ ] **Step 3: Create `app/commission/recap.py` with the classifier**

```python
"""
app/commission/recap.py

R2 — the agent commission recap assembler. Turns the R1 CommissionLineItem
ledger (+ Policy term data) into a per-agent, per-period RecapView the template
renders. No new commission math — reuses ledger.split_breakdown.

See docs/superpowers/specs/2026-06-09-agent-commission-recap-design.md.
"""
from dataclasses import dataclass, field
from typing import List, Optional

# Per-carrier mapping of native payment_type text → "is this a NEW enrollment?"
# Only agent_commission rows can be new; chargeback/override/hra never are.
# Verified against real ledger data (2026-06-09). Lowercased payment_type.
_NEW_PAYMENT_TYPES = {
    "Devoted": {"initial - new", "initial - not new"},
    "Humana": {"arcf", "med2", "iccf", "icfa"},        # first-year txn codes
    "BCBS": {"fy", "new"},
    "Aetna": {"pro-rata payment", "new"},
    "HealthSpring": {"initial", "initial - new", "initial - not new"},
}


def is_new_enrollment(carrier, classification, payment_type) -> bool:
    """True only for agent_commission rows whose carrier-native payment_type marks
    a new enrollment. Conservative: unknown carrier/type → False (counts as renewal,
    never inflates 'new members')."""
    if classification != "agent_commission":
        return False
    pt = (payment_type or "").strip().lower()
    return pt in _NEW_PAYMENT_TYPES.get(carrier, set())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_recap.py::test_is_new_enrollment_per_carrier -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/recap.py tests/test_commission_recap.py
git commit -m "feat(recap): per-carrier is_new_enrollment classifier"
```

---

### Task 2: `AgentRecapPeriod` model + migration 024

**Files:**
- Modify: `app/models.py` (add class after `CommissionLineItem`)
- Create: `migrations/versions/024_agent_recap_period.py`
- Test: `tests/test_commission_recap.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_recap.py`:

```python
def test_agent_recap_period_model(db_session, agency):
    from app.models import AgentRecapPeriod, User
    from app.extensions import db

    agent = User(name="Tim Winslow", email="tim@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()

    p = AgentRecapPeriod(agency_id=agency.id, agent_id=agent.id,
                         period_label="May 2026")
    db.session.add(p); db.session.flush()

    got = AgentRecapPeriod.query.filter_by(agent_id=agent.id,
                                           period_label="May 2026").first()
    assert got.status == "draft"          # default
    assert got.uhc_manual_amount is None
    assert got.prior_year_total is None
    assert got.published_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_recap.py::test_agent_recap_period_model -v`
Expected: FAIL — `cannot import name 'AgentRecapPeriod'`

- [ ] **Step 3: Add the model**

In `app/models.py`, immediately after the `CommissionLineItem` class's `__repr__`, add:

```python
class AgentRecapPeriod(db.Model):
    """
    R2 — workflow state for one agent's commission recap for one period.
    Per-carrier figures and line items are DERIVED live from CommissionLineItem;
    this row stores only: publish state, AJ's manual UHC figure (until R4
    automates UHC), and an optional prior-year baseline for YoY.
    """
    __tablename__ = "agent_recap_periods"

    id            = db.Column(db.Integer, primary_key=True)
    agency_id     = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    agent_id      = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    agent         = db.relationship("User", foreign_keys=[agent_id])
    period_label  = db.Column(db.String(32), nullable=False, index=True)   # "May 2026"

    status        = db.Column(db.String(16), nullable=False, default="draft")  # draft | published

    # AJ's manual UHC commission figure for this agent/period (R4 will automate).
    uhc_manual_amount = db.Column(db.Float)
    uhc_manual_note   = db.Column(db.String(256))

    # Optional manual prior-year total for YoY when last year's detail isn't loaded.
    prior_year_total  = db.Column(db.Float)

    published_at   = db.Column(db.DateTime)
    published_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    notified_at    = db.Column(db.DateTime)

    created_at     = db.Column(db.DateTime, server_default=db.func.now())
    updated_at     = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("agency_id", "agent_id", "period_label",
                            name="uq_recap_agent_period"),
    )

    def __repr__(self):
        return f"<AgentRecapPeriod agent={self.agent_id} {self.period_label} {self.status}>"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_recap.py::test_agent_recap_period_model -v`
Expected: PASS

- [ ] **Step 5: Write the migration**

Create `migrations/versions/024_agent_recap_period.py`:

```python
"""AgentRecapPeriod table (R2 agent commission recap)

Revision ID: 024
Revises: 023
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_recap_periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("period_label", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("uhc_manual_amount", sa.Float(), nullable=True),
        sa.Column("uhc_manual_note", sa.String(length=256), nullable=True),
        sa.Column("prior_year_total", sa.Float(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("published_by_id", sa.Integer(), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.ForeignKeyConstraint(["agent_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["published_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_id", "agent_id", "period_label", name="uq_recap_agent_period"),
    )
    op.create_index("ix_agent_recap_periods_agency_id", "agent_recap_periods", ["agency_id"])
    op.create_index("ix_agent_recap_periods_agent_id", "agent_recap_periods", ["agent_id"])
    op.create_index("ix_agent_recap_periods_period_label", "agent_recap_periods", ["period_label"])


def downgrade():
    op.drop_table("agent_recap_periods")
```

- [ ] **Step 6: Commit**

```bash
git add app/models.py migrations/versions/024_agent_recap_period.py tests/test_commission_recap.py
git commit -m "feat(recap): AgentRecapPeriod model + migration 024"
```

---

### Task 3: Recap assembler — per-carrier blocks + line rows

**Files:**
- Modify: `app/commission/recap.py` (dataclasses + `build_carrier_blocks`)
- Test: `tests/test_commission_recap.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_recap.py`:

```python
def _mk_line(db, agency, agent, carrier, cls, ptype, raw, split, name, period="May 2026"):
    from app.models import CommissionLineItem, CommissionStatement
    from datetime import date
    stmt = (CommissionStatement.query
            .filter_by(agency_id=agency.id, carrier=carrier, period_label=period).first())
    if stmt is None:
        stmt = CommissionStatement(agency_id=agency.id, carrier=carrier, agent_id=None,
                                   period_label=period, filename="f.xlsx",
                                   statement_date=date(2026, 5, 1))
        db.session.add(stmt); db.session.flush()
    li = CommissionLineItem(agency_id=agency.id, statement_id=stmt.id, carrier=carrier,
                            period_label=period, source_ref=f"{carrier}::{name}::{raw}",
                            agent_id=agent.id, member_name=name, raw_amount=raw,
                            split_rate=split, classification=cls, payment_type=ptype)
    db.session.add(li); db.session.flush()
    return li


def test_build_carrier_blocks_reconciles_and_counts(db_session, agency):
    from app.models import User
    from app.extensions import db
    from app.commission.recap import build_carrier_blocks

    agent = User(name="Tim Winslow", email="t@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()

    # Devoted: 1 new (initial-new), 1 renewal, 1 chargeback
    _mk_line(db, agency, agent, "Devoted", "agent_commission", "initial - new", 1000.0, 0.55, "Alice")
    _mk_line(db, agency, agent, "Devoted", "agent_commission", "renewal - monthly", 100.0, 0.55, "Bob")
    _mk_line(db, agency, agent, "Devoted", "chargeback", "initial - not new", -200.0, 0.55, "Cara")
    db.session.flush()

    blocks = build_carrier_blocks(agent.id, agency.id, "May 2026")
    dev = next(b for b in blocks if b.carrier == "Devoted")
    # payout = 1000*.55 + 100*.55 - 200*.55 = 550 + 55 - 110 = 495
    assert round(dev.total_payout, 2) == 495.00
    assert dev.new_members == 1            # only the initial-new agent_commission
    # groups present
    kinds = {g.kind for g in dev.groups}
    assert kinds == {"New enrollments", "Renewals", "Chargebacks"}
    # each line carries raw, split, payout that reconciles
    allrows = [r for g in dev.groups for r in g.rows]
    assert round(sum(r.payout for r in allrows), 2) == round(dev.total_payout, 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_recap.py::test_build_carrier_blocks_reconciles_and_counts -v`
Expected: FAIL — `cannot import name 'build_carrier_blocks'`

- [ ] **Step 3: Implement dataclasses + `build_carrier_blocks`**

Append to `app/commission/recap.py`:

```python
from app.extensions import db
from app.models import CommissionLineItem
from app.commission.ledger import split_breakdown


@dataclass
class LineRow:
    member_name: str
    customer_id: Optional[int]
    type_label: str          # "New enrollment" | "Renewal" | "Chargeback"
    type_kind: str           # "new" | "renewal" | "chargeback"
    raw_amount: float
    split_rate: Optional[float]
    payout: float


@dataclass
class CarrierGroup:
    kind: str                # "New enrollments" | "Renewals" | "Chargebacks"
    count: int
    subtotal: float
    rows: List[LineRow] = field(default_factory=list)


@dataclass
class CarrierBlock:
    carrier: str
    total_payout: float
    new_members: int
    lost_members: int = 0
    pct_of_book: float = 0.0
    source: str = "ledger"   # "ledger" | "manual" (UHC)
    note: Optional[str] = None
    groups: List[CarrierGroup] = field(default_factory=list)


_GROUP_FOR = {"new": "New enrollments", "renewal": "Renewals", "chargeback": "Chargebacks"}
_TYPE_LABEL = {"new": "New enrollment", "renewal": "Renewal", "chargeback": "Chargeback"}


def _row_kind(carrier, li):
    if li.classification == "chargeback":
        return "chargeback"
    if is_new_enrollment(carrier, li.classification, li.payment_type):
        return "new"
    return "renewal"


def build_carrier_blocks(agent_id, agency_id, period_label) -> List[CarrierBlock]:
    """One CarrierBlock per carrier the agent has ledger rows for, grouped into
    New / Renewals / Chargebacks. founders_override/hra_bonus rows are excluded
    (they are not the agent's commission). Totals reconcile to Σ split_breakdown."""
    rows = (CommissionLineItem.query
            .filter_by(agent_id=agent_id, agency_id=agency_id, period_label=period_label)
            .filter(CommissionLineItem.classification.in_(["agent_commission", "chargeback"]))
            .all())
    by_carrier = {}
    for li in rows:
        payout, _ = split_breakdown(li)
        kind = _row_kind(li.carrier, li)
        lr = LineRow(member_name=li.member_name or "(unnamed)", customer_id=li.customer_id,
                     type_label=_TYPE_LABEL[kind], type_kind=kind,
                     raw_amount=li.raw_amount, split_rate=li.split_rate, payout=payout)
        by_carrier.setdefault(li.carrier, []).append(lr)

    blocks = []
    for carrier, lrs in by_carrier.items():
        groups = {}
        for lr in lrs:
            g = groups.setdefault(lr.type_kind,
                                  CarrierGroup(kind=_GROUP_FOR[lr.type_kind], count=0, subtotal=0.0))
            g.count += 1
            g.subtotal = round(g.subtotal + lr.payout, 2)
            g.rows.append(lr)
        ordered = [groups[k] for k in ("new", "renewal", "chargeback") if k in groups]
        block = CarrierBlock(
            carrier=carrier,
            total_payout=round(sum(lr.payout for lr in lrs), 2),
            new_members=sum(1 for lr in lrs if lr.type_kind == "new"),
            groups=ordered,
        )
        blocks.append(block)
    blocks.sort(key=lambda b: b.total_payout, reverse=True)
    return blocks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_recap.py::test_build_carrier_blocks_reconciles_and_counts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/recap.py tests/test_commission_recap.py
git commit -m "feat(recap): carrier blocks (grouped new/renewal/chargeback, reconciling totals)"
```

---

### Task 4: Lost members, % of book, UHC manual block

**Files:**
- Modify: `app/commission/recap.py`
- Test: `tests/test_commission_recap.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_recap.py`:

```python
def test_lost_members_and_uhc_manual(db_session, agency):
    from app.models import User, Policy, AgentRecapPeriod
    from app.extensions import db
    from datetime import date
    from app.commission.recap import lost_members_by_carrier, uhc_manual_block

    agent = User(name="Tim Winslow", email="t2@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()

    # 2 Devoted policies termed in May 2026, 1 active (not counted), 1 termed wrong month
    for i, (status, td) in enumerate([("termed", date(2026,5,10)), ("termed", date(2026,5,20)),
                                      ("active", None), ("termed", date(2026,4,2))]):
        db.session.add(Policy(agency_id=agency.id, carrier="Devoted", member_id=f"D{i}",
                              agent_id=agent.id, status=status, term_date=td))
    db.session.flush()

    lost = lost_members_by_carrier(agent.id, agency.id, "May 2026")
    assert lost.get("Devoted") == 2

    # UHC manual block from AgentRecapPeriod
    p = AgentRecapPeriod(agency_id=agency.id, agent_id=agent.id, period_label="May 2026",
                         uhc_manual_amount=4375.68, uhc_manual_note="AEP true-up incl.")
    db.session.add(p); db.session.flush()
    blk = uhc_manual_block(p)
    assert blk is not None
    assert blk.carrier == "UHC"
    assert blk.total_payout == 4375.68
    assert blk.source == "manual"
    assert blk.note == "AEP true-up incl."

    # No UHC figure → no block
    assert uhc_manual_block(AgentRecapPeriod(agency_id=agency.id, agent_id=agent.id,
                                             period_label="June 2026")) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_recap.py::test_lost_members_and_uhc_manual -v`
Expected: FAIL — `cannot import name 'lost_members_by_carrier'`

- [ ] **Step 3: Implement**

Append to `app/commission/recap.py`:

```python
from datetime import datetime
from app.models import Policy


def _period_bounds(period_label):
    """'May 2026' -> (date(2026,5,1), date(2026,5,31)). Returns (start, end)."""
    import calendar
    dt = datetime.strptime(period_label, "%B %Y")
    last = calendar.monthrange(dt.year, dt.month)[1]
    from datetime import date
    return date(dt.year, dt.month, 1), date(dt.year, dt.month, last)


def lost_members_by_carrier(agent_id, agency_id, period_label) -> dict:
    """Count this period's terminations per carrier for policies the agent owns.
    Lost = Policy.status termed with term_date inside the period month."""
    start, end = _period_bounds(period_label)
    rows = (Policy.query
            .filter_by(agent_id=agent_id, agency_id=agency_id, status="termed")
            .filter(Policy.term_date >= start, Policy.term_date <= end)
            .all())
    out = {}
    for p in rows:
        out[p.carrier] = out.get(p.carrier, 0) + 1
    return out


def uhc_manual_block(recap_period) -> Optional[CarrierBlock]:
    """Build the UHC carrier block from AJ's manually entered figure (no ledger
    extractor for UHC until R4). Returns None when AJ hasn't entered one."""
    amt = getattr(recap_period, "uhc_manual_amount", None)
    if amt is None:
        return None
    return CarrierBlock(carrier="UHC", total_payout=round(amt, 2), new_members=0,
                        source="manual", note=getattr(recap_period, "uhc_manual_note", None))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_recap.py::test_lost_members_and_uhc_manual -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/recap.py tests/test_commission_recap.py
git commit -m "feat(recap): lost members from Policy term data + UHC manual block"
```

---

### Task 5: Full `build_recap` — headline KPIs + YTD + run-rate

**Files:**
- Modify: `app/commission/recap.py`
- Test: `tests/test_commission_recap.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_recap.py`:

```python
def test_build_recap_headline_and_ytd(db_session, agency):
    from app.models import User, AgentRecapPeriod
    from app.extensions import db
    from app.commission.recap import build_recap

    agent = User(name="Tim Winslow", email="t3@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()

    # May: Devoted 1 new $1000 + 1 chargeback -$200 (payouts 550, -110) ; net 440
    _mk_line(db, agency, agent, "Devoted", "agent_commission", "initial - new", 1000.0, 0.55, "A")
    _mk_line(db, agency, agent, "Devoted", "chargeback", "initial - not new", -200.0, 0.55, "B")
    # AJ entered UHC $2000
    db.session.add(AgentRecapPeriod(agency_id=agency.id, agent_id=agent.id,
                                    period_label="May 2026", uhc_manual_amount=2000.0))
    db.session.flush()

    r = build_recap(agent.id, agency.id, "May 2026")
    # total = ledger payouts (440) + UHC manual (2000) = 2440
    assert round(r.total_paid, 2) == 2440.00
    # after chargebacks is the same total (chargebacks already netted into payouts)
    assert round(r.net_after_chargebacks, 2) == 2440.00
    assert r.new_members == 1
    # carriers include both Devoted (ledger) and UHC (manual)
    names = {b.carrier for b in r.carriers}
    assert "Devoted" in names and "UHC" in names
    uhc = next(b for b in r.carriers if b.carrier == "UHC")
    assert uhc.source == "manual"
    # pct_of_book sums to ~100 across carriers with members (UHC has 0 members here)
    # run-rate is a positive projection from YTD
    assert r.run_rate >= r.ytd_current
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_recap.py::test_build_recap_headline_and_ytd -v`
Expected: FAIL — `cannot import name 'build_recap'`

- [ ] **Step 3: Implement `RecapView` + `build_recap` + YTD/run-rate helpers**

Append to `app/commission/recap.py`:

```python
@dataclass
class RecapView:
    agent_id: int
    agent_name: str
    period_label: str
    status: str
    total_paid: float
    net_after_chargebacks: float
    new_members: int
    lost_members: int
    net_member_change: int
    carriers: List[CarrierBlock]
    ytd_current: float
    ytd_prior: Optional[float]
    ytd_growth_pct: Optional[float]
    run_rate: float
    monthly_trend: list           # [(month_label, payout), ...] current year
    prior_year_known: bool


def _ledger_ytd_total(agent_id, agency_id, year):
    """Sum agent payouts across all periods in `year` from the ledger."""
    rows = (CommissionLineItem.query
            .filter_by(agent_id=agent_id, agency_id=agency_id)
            .filter(CommissionLineItem.classification.in_(["agent_commission", "chargeback"]))
            .all())
    total = 0.0
    months = {}
    for li in rows:
        try:
            dt = datetime.strptime(li.period_label or "", "%B %Y")
        except ValueError:
            continue
        if dt.year != year:
            continue
        payout, _ = split_breakdown(li)
        total += payout
        months[dt.month] = round(months.get(dt.month, 0.0) + payout, 2)
    return round(total, 2), months


def build_recap(agent_id, agency_id, period_label) -> RecapView:
    from app.models import User, AgentRecapPeriod
    agent = User.query.get(agent_id)
    rp = (AgentRecapPeriod.query
          .filter_by(agency_id=agency_id, agent_id=agent_id, period_label=period_label).first())

    carriers = build_carrier_blocks(agent_id, agency_id, period_label)
    uhc = uhc_manual_block(rp) if rp else None
    if uhc:
        carriers.append(uhc)
        carriers.sort(key=lambda b: b.total_payout, reverse=True)

    lost = lost_members_by_carrier(agent_id, agency_id, period_label)
    for b in carriers:
        b.lost_members = lost.get(b.carrier, 0)

    # % of book: each carrier's active policy count / agent's total active policies
    active = (Policy.query.filter_by(agent_id=agent_id, agency_id=agency_id, status="active").all())
    by_carrier_active = {}
    for p in active:
        by_carrier_active[p.carrier] = by_carrier_active.get(p.carrier, 0) + 1
    total_active = sum(by_carrier_active.values()) or 1
    for b in carriers:
        b.pct_of_book = round(100.0 * by_carrier_active.get(b.carrier, 0) / total_active, 1)

    total_paid = round(sum(b.total_payout for b in carriers), 2)
    new_members = sum(b.new_members for b in carriers)
    lost_members = sum(lost.values())

    # YTD + trend (current year from period_label)
    cur_year = datetime.strptime(period_label, "%B %Y").year
    ytd_current, months = _ledger_ytd_total(agent_id, agency_id, cur_year)
    ytd_prior_ledger, _ = _ledger_ytd_total(agent_id, agency_id, cur_year - 1)
    prior_year_known = ytd_prior_ledger != 0.0
    ytd_prior = ytd_prior_ledger if prior_year_known else (rp.prior_year_total if rp else None)
    if ytd_prior:
        prior_year_known = True
    growth = (round(100.0 * (ytd_current - ytd_prior) / ytd_prior, 1)
              if ytd_prior else None)

    months_elapsed = max((datetime.strptime(period_label, "%B %Y").month), 1)
    run_rate = round(ytd_current / months_elapsed * 12, 2) if ytd_current else 0.0

    import calendar
    trend = [(calendar.month_abbr[m], months.get(m, 0.0)) for m in range(1, cur_year and 13 or 13)]
    trend = [(lbl, v) for lbl, v in trend][: datetime.strptime(period_label, "%B %Y").month]

    return RecapView(
        agent_id=agent_id, agent_name=(agent.name if agent else "Agent"),
        period_label=period_label, status=(rp.status if rp else "draft"),
        total_paid=total_paid, net_after_chargebacks=total_paid,
        new_members=new_members, lost_members=lost_members,
        net_member_change=new_members - lost_members,
        carriers=carriers, ytd_current=ytd_current, ytd_prior=ytd_prior,
        ytd_growth_pct=growth, run_rate=run_rate, monthly_trend=trend,
        prior_year_known=prior_year_known)
```

Note: `net_after_chargebacks == total_paid` because `split_breakdown` already nets chargebacks (negative payouts) into each carrier total. The separate headline exists for clarity/labeling, and to stay correct if a future classification is added that should be excluded from "after chargebacks."

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_recap.py::test_build_recap_headline_and_ytd -v`
Expected: PASS

- [ ] **Step 5: Run the whole recap test file**

Run: `python3 -m pytest tests/test_commission_recap.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/commission/recap.py tests/test_commission_recap.py
git commit -m "feat(recap): build_recap — headline KPIs, YTD, run-rate, trend"
```

---

### Task 6: `app/mailer.py` — generic SendGrid sender

**Files:**
- Create: `app/mailer.py`
- Test: `tests/test_commission_recap.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_recap.py`:

```python
def test_send_email_builds_message(monkeypatch, app):
    from app import mailer
    sent = {}

    class FakeSG:
        def __init__(self, key): sent["key"] = key
        def send(self, message): sent["message"] = message

    monkeypatch.setattr(mailer, "SendGridAPIClient", FakeSG)
    with app.app_context():
        app.config["SENDGRID_API_KEY"] = "k"
        app.config["LABELS_FROM_EMAIL"] = "from@x.com"
        ok = mailer.send_email("to@x.com", "Subj", "hello body")
    assert ok is True
    assert sent["key"] == "k"
    assert sent["message"] is not None


def test_send_email_no_key_returns_false(app):
    from app import mailer
    with app.app_context():
        app.config["SENDGRID_API_KEY"] = ""
        assert mailer.send_email("to@x.com", "S", "b") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_recap.py -k send_email -v`
Expected: FAIL — `No module named 'app.mailer'`

- [ ] **Step 3: Implement `app/mailer.py`**

```python
"""
app/mailer.py

Minimal SendGrid sender, factored from the labels.py usage so multiple features
(birthday labels, recap publish notifications) share one path. Returns True on
send, False when not configured (never raises into request flow).
"""
from flask import current_app
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail


def send_email(to_email, subject, text, html=None) -> bool:
    """Send a plain (and optionally HTML) email. Returns False if SendGrid isn't
    configured or the send fails — callers decide whether that's fatal."""
    api_key = current_app.config.get("SENDGRID_API_KEY")
    from_email = current_app.config.get("LABELS_FROM_EMAIL") or current_app.config.get("MAIL_FROM")
    if not api_key or not from_email or not to_email:
        return False
    message = Mail(from_email=from_email, to_emails=to_email,
                   subject=subject, plain_text_content=text,
                   html_content=html or None)
    try:
        SendGridAPIClient(api_key).send(message)
        return True
    except Exception as e:
        current_app.logger.warning(f"send_email failed to {to_email}: {e}")
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_recap.py -k send_email -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/mailer.py tests/test_commission_recap.py
git commit -m "feat(mailer): generic SendGrid send_email helper"
```

---

### Task 7: Publish workflow function + visibility rule

**Files:**
- Modify: `app/commission/recap.py` (`publish_recap`, `get_or_create_period`)
- Test: `tests/test_commission_recap.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_recap.py`:

```python
def test_publish_workflow_and_visibility(db_session, agency, app, monkeypatch):
    from app.models import User, AgentRecapPeriod
    from app.extensions import db
    from app.commission import recap as R

    agent = User(name="Tim", email="pub@x.com", agency_id=agency.id)
    admin = User(name="AJ", email="aj@x.com", agency_id=agency.id, is_admin=True)
    db.session.add_all([agent, admin]); db.session.flush()

    # draft created on demand, not visible to agent
    p = R.get_or_create_period(agent.id, agency.id, "May 2026")
    assert p.status == "draft"
    assert R.is_visible_to_agent(p) is False

    # publish notifies once
    calls = []
    monkeypatch.setattr(R, "send_email", lambda *a, **k: calls.append(a) or True)
    with app.app_context():
        R.publish_recap(p, published_by_id=admin.id, agent_email=agent.email,
                        total_paid=2440.0, base_url="http://x")
    db.session.flush()
    assert p.status == "published"
    assert p.published_at is not None
    assert p.notified_at is not None
    assert R.is_visible_to_agent(p) is True
    assert len(calls) == 1

    # re-publish does not re-notify
    R.publish_recap(p, published_by_id=admin.id, agent_email=agent.email,
                    total_paid=2440.0, base_url="http://x")
    assert len(calls) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_recap.py -k publish_workflow -v`
Expected: FAIL — `cannot import name 'get_or_create_period'`

- [ ] **Step 3: Implement**

Append to `app/commission/recap.py` (add `from app.mailer import send_email` near the top imports):

```python
def get_or_create_period(agent_id, agency_id, period_label):
    from app.models import AgentRecapPeriod
    p = (AgentRecapPeriod.query
         .filter_by(agency_id=agency_id, agent_id=agent_id, period_label=period_label).first())
    if p is None:
        p = AgentRecapPeriod(agency_id=agency_id, agent_id=agent_id,
                             period_label=period_label, status="draft")
        db.session.add(p); db.session.flush()
    return p


def is_visible_to_agent(recap_period) -> bool:
    return recap_period is not None and recap_period.status == "published"


def publish_recap(recap_period, published_by_id, agent_email, total_paid, base_url) -> None:
    """Flip a recap period to published, stamp it, and notify the agent ONCE."""
    recap_period.status = "published"
    if recap_period.published_at is None:
        recap_period.published_at = datetime.utcnow()
    recap_period.published_by_id = published_by_id
    if recap_period.notified_at is None and agent_email:
        subject = f"Your {recap_period.period_label} commission recap is ready"
        link = f"{base_url}/commissions/recap?period={recap_period.period_label}"
        body = (f"Your {recap_period.period_label} commission recap is ready — "
                f"${total_paid:,.2f}.\n\nView it here: {link}")
        if send_email(agent_email, subject, body):
            recap_period.notified_at = datetime.utcnow()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_recap.py -k publish_workflow -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/recap.py tests/test_commission_recap.py
git commit -m "feat(recap): publish workflow (draft→published, notify once, visibility)"
```

---

### Task 8: Routes — agent recap, admin view, publish, set-UHC, carrier-detail JSON

**Files:**
- Modify: `app/commission/routes.py`
- Test: `tests/test_commission_recap.py`

- [ ] **Step 1: Write the failing test (route-level, using the test client)**

Append to `tests/test_commission_recap.py`:

```python
def _login(client, user):
    with client.session_transaction() as s:
        s["_user_id"] = str(user.id)


def test_agent_recap_route_hides_draft_shows_published(db_session, agency, app):
    from app.models import User, AgentRecapPeriod
    from app.extensions import db
    agent = User(name="Tim", email="route@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()
    _mk_line(db, agency, agent, "Devoted", "agent_commission", "renewal - monthly", 100.0, 0.55, "A")
    db.session.add(AgentRecapPeriod(agency_id=agency.id, agent_id=agent.id,
                                    period_label="May 2026", status="draft"))
    db.session.commit()

    client = app.test_client()
    _login(client, agent)
    # draft → agent sees a "pending" state, not the numbers
    resp = client.get("/commissions/recap?period=May+2026")
    assert resp.status_code == 200
    assert b"pending" in resp.data.lower() or b"not yet" in resp.data.lower()

    # publish, then the total shows
    p = AgentRecapPeriod.query.filter_by(agent_id=agent.id, period_label="May 2026").first()
    p.status = "published"; db.session.commit()
    resp2 = client.get("/commissions/recap?period=May+2026")
    assert b"55" in resp2.data  # $55.00 payout appears
```

(Note: the conftest `app` fixture must register routes; if the test client needs login wiring, mirror existing route tests. If no route test exists in the repo to copy, keep this test but mark the data-layer tests as the primary guarantee.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_recap.py -k recap_route -v`
Expected: FAIL — route 404 (not yet defined).

- [ ] **Step 3: Add routes to `app/commission/routes.py`**

Add imports near the top (with the other `from app.commission... import`):

```python
from app.commission.recap import (build_recap, get_or_create_period, is_visible_to_agent,
                                   publish_recap, build_carrier_blocks)
from app.models import AgentRecapPeriod
```

Add the routes (anywhere among the other `@commission_bp.route` defs):

```python
@commission_bp.route("/commissions/recap")
@login_required
def agent_recap():
    period = request.args.get("period") or _latest_published_period(current_user.id, current_user.agency_id)
    rp = AgentRecapPeriod.query.filter_by(
        agency_id=current_user.agency_id, agent_id=current_user.id, period_label=period).first() if period else None
    if not period or not is_visible_to_agent(rp):
        return render_template("commission/recap.html", recap=None, pending=True,
                               period_label=period, is_admin=current_user.is_admin,
                               periods=_published_periods(current_user.id, current_user.agency_id))
    recap = build_recap(current_user.id, current_user.agency_id, period)
    return render_template("commission/recap.html", recap=recap, pending=False,
                           period_label=period, is_admin=current_user.is_admin,
                           periods=_published_periods(current_user.id, current_user.agency_id))


@commission_bp.route("/admin/commissions/recap")
@login_required
def admin_recap():
    if not current_user.is_admin:
        abort(403)
    agent_id = request.args.get("agent_id", type=int) or current_user.id
    period = request.args.get("period") or date.today().strftime("%B %Y")
    rp = get_or_create_period(agent_id, current_user.agency_id, period)
    db.session.commit()
    recap = build_recap(agent_id, current_user.agency_id, period)
    agents = User.query.filter_by(agency_id=current_user.agency_id).order_by(User.name).all()
    return render_template("commission/recap.html", recap=recap, pending=False, admin_view=True,
                           period_label=period, recap_period=rp, agents=agents,
                           selected_agent_id=agent_id, is_admin=True)


@commission_bp.route("/admin/commissions/recap/publish", methods=["POST"])
@login_required
def admin_recap_publish():
    if not current_user.is_admin:
        abort(403)
    agent_id = request.form.get("agent_id", type=int)
    period = request.form.get("period")
    rp = get_or_create_period(agent_id, current_user.agency_id, period)
    recap = build_recap(agent_id, current_user.agency_id, period)
    agent = User.query.get(agent_id)
    publish_recap(rp, published_by_id=current_user.id,
                  agent_email=(agent.email if agent else None),
                  total_paid=recap.total_paid, base_url=request.url_root.rstrip("/"))
    db.session.commit()
    flash(f"Published {period} recap for {agent.name if agent else agent_id}.", "success")
    return redirect(url_for("commission.admin_recap", agent_id=agent_id, period=period))


@commission_bp.route("/admin/commissions/recap/set-uhc", methods=["POST"])
@login_required
def admin_recap_set_uhc():
    if not current_user.is_admin:
        abort(403)
    agent_id = request.form.get("agent_id", type=int)
    period = request.form.get("period")
    rp = get_or_create_period(agent_id, current_user.agency_id, period)
    raw = (request.form.get("uhc_amount") or "").replace("$", "").replace(",", "").strip()
    rp.uhc_manual_amount = float(raw) if raw else None
    rp.uhc_manual_note = (request.form.get("uhc_note") or "").strip() or None
    db.session.commit()
    flash("UHC figure updated.", "success")
    return redirect(url_for("commission.admin_recap", agent_id=agent_id, period=period))


@commission_bp.route("/commissions/recap/carrier")
@login_required
def recap_carrier_detail():
    """JSON: the grouped line items for one carrier (lazy-loaded drill-down + search)."""
    agent_id = request.args.get("agent_id", type=int) or current_user.id
    if agent_id != current_user.id and not current_user.is_admin:
        abort(403)
    period = request.args.get("period")
    carrier = request.args.get("carrier")
    q = (request.args.get("q") or "").strip().lower()
    blocks = build_carrier_blocks(agent_id, current_user.agency_id, period)
    block = next((b for b in blocks if b.carrier == carrier), None)
    if block is None:
        return {"carrier": carrier, "groups": []}
    def rowj(r):
        return {"member": r.member_name, "customer_id": r.customer_id, "type": r.type_label,
                "kind": r.type_kind, "raw": r.raw_amount, "split": r.split_rate, "payout": r.payout}
    groups = []
    for g in block.groups:
        rows = [rowj(r) for r in g.rows if not q or q in (r.member_name or "").lower()]
        groups.append({"kind": g.kind, "count": g.count, "subtotal": g.subtotal, "rows": rows})
    return {"carrier": carrier, "total": block.total_payout, "groups": groups}
```

Add the two small helpers near the recap routes:

```python
def _published_periods(agent_id, agency_id):
    rows = (AgentRecapPeriod.query
            .filter_by(agency_id=agency_id, agent_id=agent_id, status="published")
            .order_by(AgentRecapPeriod.published_at.desc()).all())
    return [r.period_label for r in rows]


def _latest_published_period(agent_id, agency_id):
    ps = _published_periods(agent_id, agency_id)
    return ps[0] if ps else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_recap.py -k recap_route -v`
Expected: PASS (if the repo's test client can't easily auth, keep the data-layer tests authoritative and assert the route returns 200 / 302 as wired — adapt to the existing route-test pattern in `tests/`).

- [ ] **Step 5: Commit**

```bash
git add app/commission/routes.py tests/test_commission_recap.py
git commit -m "feat(recap): routes — agent/admin recap, publish, set-UHC, carrier-detail JSON"
```

---

### Task 9: Template — single-screen recap + drill-down (the look)

**Files:**
- Create: `app/templates/commission/recap.html`
- Modify: `app/templates/base.html` (fonts link + nav item)

- [ ] **Step 1: Add the Google Fonts link + nav item to base.html**

In `app/templates/base.html` `<head>` (near other font/style links), add:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Merriweather:wght@700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
```

In the agent "My Book" / "Commissions" nav section (find the existing `nav-section-label` for commissions), add as the first commission item:

```html
<a href="{{ url_for('commission.agent_recap') }}"
   class="nav-item {% if request.endpoint == 'commission.agent_recap' %}active{% endif %}">
  <span class="nav-dot"></span> My Commissions
</a>
```

If admins should reach the admin view, add under the Agency/admin section:

```html
<a href="{{ url_for('commission.admin_recap') }}"
   class="nav-item {% if request.endpoint == 'commission.admin_recap' %}active{% endif %}">
  <span class="nav-dot"></span> Agent Recaps
</a>
```

- [ ] **Step 2: Create `app/templates/commission/recap.html`**

Build the single-screen page using the approved mockup `recap-final-v1.html` as the visual reference (in `.superpowers/brainstorm/.../content/`). Requirements the template MUST meet (match the mockup):

- Extends `base.html`; all recap CSS in `{% block styles %}` using the Founders tokens (blue `#266EA5`, green `#65BB84`, navy `#002E4D`, etc.), Plus Jakarta Sans body 1.25rem, Merriweather headings.
- **Pending state** (`pending=True`): a friendly card — "Your {{ period_label }} recap isn't published yet. You'll be notified when it's ready." No numbers. (Satisfies the visibility test.)
- **Period selector** (dropdown of `periods`); admin view adds an agent `<select>` + the set-UHC form + a Publish button.
- **Tier 1 headline:** three cards — Total Paid (`recap.total_paid`), New Members (`+{{ recap.new_members }}`, sub "gained N · lost M · net X", gradient card), After Chargebacks (`recap.net_after_chargebacks`, ⓘ tooltip). Numbers `|round(2)` with `$` and commas via a `"{:,.2f}".format()` filter or inline.
- **Tier 2 carrier cards:** loop `recap.carriers` — brand-colored bar+chip (use a small JS/Jinja `CARRIER_BRAND` color lookup; approximations OK), carrier name, `$ {{ b.total_payout }}`, "+{{ b.new_members }} new members" or "no new members", "{{ b.pct_of_book }}% of your book", "verify ›". UHC card (`b.source == 'manual'`) shows a small "entered by AJ" tag + `b.note`. Each card `onclick` opens the drill-down for that carrier.
- **Tier 2b drill-down:** an in-place panel (hidden by default) populated by fetching `/commissions/recap/carrier?period=&carrier=&agent_id=` (JSON). Render grouped sections (New / Chargebacks / Renewals) with counts + subtotals; groups expand to a member table (Member, Type pill, Carrier Paid, × split, Your Payout); a search `<input>` re-fetches with `&q=`; reconciliation footer "✓ these lines add up to $X". Big groups: render rows from JSON (already filtered server-side); cap initial render and show "show all N" to reveal the rest.
- **Tier 3 YTD strip:** This Year So Far (`recap.ytd_current` vs `recap.ytd_prior` or "no prior-year data" when `not recap.prior_year_known`), Growth (`recap.ytd_growth_pct` with ▲/▼ and correct color — green up, red down — guard `None`), On Pace For (`recap.run_rate`, ⓘ), mini monthly-trend bars from `recap.monthly_trend`.
- **Tooltips:** dotted-underline spans with `title=` for Chargebacks, After Chargebacks, Carrier Paid, On Pace For. A "What do these mean?" link is optional.
- Accessibility: `cursor:pointer` on cards, visible `:focus`, keyboard-operable drill-down toggle, `prefers-reduced-motion` guard on any count-up/transition, responsive grid (3→2→1).

- [ ] **Step 3: Smoke-test the template renders**

Run:
```bash
python3 -c "
import os; os.environ['SECRET_KEY']='x'; os.environ['TESTING']='1'; os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import create_app; from app.extensions import db
a=create_app(); a.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SERVER_NAME='localhost')
from app.commission.recap import RecapView
with a.app_context(), a.test_request_context():
    db.create_all()
    from flask import render_template
    # pending render
    html = render_template('commission/recap.html', recap=None, pending=True, period_label='May 2026', is_admin=False, periods=[])
    assert 'not' in html.lower() or 'pending' in html.lower()
    print('pending render OK,', len(html), 'bytes')
"
```
Expected: prints "pending render OK".

- [ ] **Step 4: Run the full recap suite + whole suite**

Run: `python3 -m pytest tests/test_commission_recap.py -q && python3 -m pytest -q 2>&1 | tail -3`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/templates/commission/recap.html app/templates/base.html tests/test_commission_recap.py
git commit -m "feat(recap): single-screen recap template + drill-down + nav item"
```

---

### Task 10: Verify in the running app + docs

**Files:**
- Modify: `CLAUDE.md`, `docs/superpowers/specs/2026-06-09-agent-commission-recap-design.md`

- [ ] **Step 1: Run the app and eyeball the recap**

Use the project's run pattern (the `/run` skill or `flask run` with a SQLite dev DB), log in as an agent with some published ledger data, and confirm: headline numbers render, a carrier card opens the drill-down, the line items sum to the carrier total, the YTD strip shows. Fix any rendering issues found (this is the "verify against rendered output, not just green tests" step from the session method). Capture a screenshot if the run skill supports it.

- [ ] **Step 2: Mark the spec implemented**

In the spec, set: `**Status:** ✅ Implemented (on feat/agent-recap)`.

- [ ] **Step 3: Add a CLAUDE.md build-status entry**

After the R1.1 entry, add:

```markdown
- **R2 — Agent Commission Recap ✅ (2026-06-09, on `feat/agent-recap`)** — agent-facing single-screen recap built on the R1 ledger. `app/commission/recap.py` assembler: `build_recap()` → headline KPIs (total paid, new members gained/lost/net, net-after-chargebacks), per-carrier blocks (grouped New/Renewal/Chargeback, reconciling to Σ split_breakdown), lost members from `Policy` term data, % of book, YTD CY-vs-LY + run-rate (graceful "no prior-year data"). `is_new_enrollment(carrier,...)` per-carrier payment_type map. `AgentRecapPeriod` (migration 024) = publish workflow (draft→published, notify once) + AJ-manual UHC figure (until R4) + optional prior-year baseline. Routes: agent `/commissions/recap`, admin `/admin/commissions/recap` (+publish, +set-uhc), JSON `/commissions/recap/carrier` (lazy drill-down + member search). Template = Founders Material-3 look (Plus Jakarta Sans + Merriweather, #266EA5/#65BB84, big centered numbers, brand-colored carrier cards, in-place drill-down with reconciliation footer "✓ lines add up to $X"). `app/mailer.py` generic SendGrid sender. Flagship of the new portal look (full re-theme deferred). Per-carrier exact brand hex = polish TODO.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-06-09-agent-commission-recap-design.md
git commit -m "docs(R2): mark agent recap implemented; build-status entry"
```

---

## Deployment (after merge)

Migration 024 + code. Standard VPS deploy + migration:

```bash
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100
cd /var/www/founders-portal && git pull \
  && ./venv/bin/pip install -r requirements.txt \
  && flask db upgrade \
  && systemctl restart founders-portal
```

Then AJ: open `/admin/commissions/recap`, pick an agent + period, enter the UHC figure, click Publish — the agent gets notified and sees their recap.

---

## Self-review notes (done while writing)

- **Spec coverage:** users/access → Task 8 routes (agent/admin/scoping); publish workflow + AgentRecapPeriod → Tasks 2,7,8; data sources (ledger/UHC-manual/lost/% book/YTD/run-rate) → Tasks 3,4,5; new-vs-renewal per-carrier → Task 1; single-screen 3-tier layout + Option C drill-down + reconciliation → Task 9; visual tokens/fonts → Task 9; notifications/mailer → Tasks 6,7; tests throughout. ✅
- **Placeholder scan:** Task 9 (template) describes requirements rather than full HTML — this is deliberate (the approved mockup `recap-final-v1.html` is the literal visual reference the implementer copies; reproducing ~300 lines of styled HTML inline would be brittle). Every binding (`recap.total_paid`, `b.pct_of_book`, etc.) and the JSON contract are concrete. Acceptable; not a logic placeholder.
- **Type consistency:** `RecapView`/`CarrierBlock`/`CarrierGroup`/`LineRow` fields used in routes/JSON/template match their Task 3/5 definitions; `is_new_enrollment`, `build_carrier_blocks`, `build_recap`, `lost_members_by_carrier`, `uhc_manual_block`, `get_or_create_period`, `publish_recap`, `is_visible_to_agent`, `send_email` signatures consistent across tasks. ✅
- **Known judgment call for the executor:** the route test (Task 8) depends on the repo's test-client auth pattern; if none exists to copy, the data-layer tests (Tasks 1-7) are the authoritative guarantee and the route test can assert status codes only. Flagged in-task.
- **Net-after-chargebacks == total_paid** today (chargebacks already netted by split_breakdown); the separate field is intentional labeling headroom, noted in Task 5.
