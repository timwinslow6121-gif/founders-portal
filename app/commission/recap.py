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
    # NB: ledger stores this carrier as "Healthspring" (lowercase s) — key MUST match.
    "Healthspring": {"initial", "initial - new", "initial - not new"},
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
from app.mailer import send_email


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
