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
