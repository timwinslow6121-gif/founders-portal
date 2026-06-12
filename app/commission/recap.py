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


_GROUP_FOR = {"new": "New enrollments", "renewal": "Renewals",
              "bonus": "HRA", "chargeback": "Chargebacks"}
_TYPE_LABEL = {"new": "New enrollment", "renewal": "Renewal",
               "bonus": "HRA", "chargeback": "Chargeback"}


def _row_kind(carrier, li):
    if li.classification == "chargeback":
        return "chargeback"
    # HRA bonuses are agent commission (they split to the agent), but they are
    # not enrollments — own group so they're counted in payout yet never inflate
    # the new-member count.
    if li.classification == "hra_bonus":
        return "bonus"
    if is_new_enrollment(carrier, li.classification, li.payment_type):
        return "new"
    return "renewal"


def build_carrier_blocks(agent_id, agency_id, period_label) -> List[CarrierBlock]:
    """One CarrierBlock per carrier the agent has ledger rows for, grouped into
    New / Renewals / Bonuses / Chargebacks. hra_bonus IS the agent's commission
    (it splits to them) so it's included; only founders_override (100% Founders)
    is excluded. Totals reconcile to Σ split_breakdown."""
    rows = (CommissionLineItem.query
            .filter_by(agent_id=agent_id, agency_id=agency_id, period_label=period_label)
            .filter(CommissionLineItem.classification.in_(
                ["agent_commission", "hra_bonus", "chargeback"]))
            .all())
    by_carrier = {}
    for li in rows:
        payout, _ = split_breakdown(li)
        kind = _row_kind(li.carrier, li)
        # Round each line's payout to cents AT THE SOURCE. Every aggregate below
        # then sums these identical 2dp values, so the drill-down rows ALWAYS add
        # up exactly to the group subtotal and the carrier total (no per-row-vs-
        # per-total drift — the "✓ lines add up to $X" guarantee holds to the penny).
        lr = LineRow(member_name=li.member_name or "(unnamed)", customer_id=li.customer_id,
                     type_label=_TYPE_LABEL[kind], type_kind=kind,
                     raw_amount=li.raw_amount, split_rate=li.split_rate,
                     payout=round(payout, 2))
        by_carrier.setdefault(li.carrier, []).append(lr)

    blocks = []
    for carrier, lrs in by_carrier.items():
        groups = {}
        for lr in lrs:
            g = groups.setdefault(lr.type_kind,
                                  CarrierGroup(kind=_GROUP_FOR[lr.type_kind], count=0, subtotal=0.0))
            g.count += 1
            g.rows.append(lr)
        # Subtotals + total are sums of the already-rounded row payouts (round once
        # more only to clear float addition noise like 0.1+0.2).
        for g in groups.values():
            g.subtotal = round(sum(r.payout for r in g.rows), 2)
        ordered = [groups[k] for k in ("new", "renewal", "bonus", "chargeback") if k in groups]
        block = CarrierBlock(
            carrier=carrier,
            total_payout=round(sum(lr.payout for lr in lrs), 2),
            new_members=sum(1 for lr in lrs if lr.type_kind == "new"),
            groups=ordered,
        )
        blocks.append(block)
    blocks.sort(key=lambda b: b.total_payout, reverse=True)
    return blocks


def quarantined_line_items(statement_id, agency_id):
    """The needs_manual_review line items for a statement (UHC's ~2.3% the parser
    can't auto-split: 'New' enrollment proration, PARTD dust, other-agent
    Med-Supp). These are recorded but NOT split (split_rate NULL → payout 0), so
    nothing is silently dropped — AJ hand-splits them from the quarantine tab.
    Returns {count, total, rows:[{member_name, mbi, amount, action}]}."""
    items = (CommissionLineItem.query
             .filter_by(statement_id=statement_id, agency_id=agency_id,
                        classification="needs_manual_review")
             .order_by(CommissionLineItem.member_name)
             .all())
    rows = [{"member_name": li.member_name or "(unnamed)", "mbi": li.mbi,
             "amount": round(li.raw_amount or 0.0, 2), "action": li.payment_type or ""}
            for li in items]
    return {"count": len(rows),
            "total": round(sum(r["amount"] for r in rows), 2),
            "rows": rows}


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
    # UHC is now a real ledger carrier (R4 parser, 2026-06). The manual figure is a
    # legacy fallback ONLY for periods with no parsed UHC data — never add it on top
    # of a ledger UHC block (that would double-count). New manual entry is removed.
    has_ledger_uhc = any(b.carrier == "UHC" for b in carriers)
    uhc = (uhc_manual_block(rp) if rp else None) if not has_ledger_uhc else None
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

    # Net = chargeback-inclusive (each block.total_payout already nets negatives).
    net_paid = round(sum(b.total_payout for b in carriers), 2)
    # Gross = before chargebacks: sum every block total MINUS its Chargebacks group
    # (a chargeback subtotal is negative, so subtracting it adds it back out).
    chargeback_total = 0.0
    for b in carriers:
        for g in b.groups:
            if g.kind == "Chargebacks":
                chargeback_total += g.subtotal
    gross_paid = round(net_paid - chargeback_total, 2)
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
        total_paid=gross_paid, net_after_chargebacks=net_paid,
        new_members=new_members, lost_members=lost_members,
        net_member_change=new_members - lost_members,
        carriers=carriers, ytd_current=ytd_current, ytd_prior=ytd_prior,
        ytd_growth_pct=growth, run_rate=run_rate, monthly_trend=trend,
        prior_year_known=prior_year_known)


def latest_period_with_data(agency_id):
    """The period_label of the most recently-dated commission statement in this
    agency — used as the admin recap default so opening the page lands on the
    period you just uploaded, not today's calendar month. Ordered by the real
    statement_date (period_label sorts wrong: 'December' < 'February' alphabetically).
    Returns None when no statements exist."""
    from app.models import CommissionStatement
    row = (CommissionStatement.query
           .filter_by(agency_id=agency_id)
           .filter(CommissionStatement.period_label.isnot(None))
           .order_by(CommissionStatement.statement_date.desc())
           .first())
    return row.period_label if row else None


def all_periods_with_data(agency_id):
    """All distinct period_labels that have commission statements in this agency,
    most-recent first (by statement_date). Powers the admin period dropdown."""
    from app.models import CommissionStatement
    rows = (CommissionStatement.query
            .filter_by(agency_id=agency_id)
            .filter(CommissionStatement.period_label.isnot(None))
            .order_by(CommissionStatement.statement_date.desc())
            .all())
    seen, out = set(), []
    for r in rows:
        if r.period_label not in seen:
            seen.add(r.period_label)
            out.append(r.period_label)
    return out


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
