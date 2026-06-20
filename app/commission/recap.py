"""
app/commission/recap.py

R2 — the agent commission recap assembler. Turns the R1 CommissionLineItem
ledger (+ Policy term data) into a per-agent, per-period RecapView the template
renders. No new commission math — reuses ledger.split_breakdown.

See docs/superpowers/specs/2026-06-09-agent-commission-recap-design.md.
"""
from collections import defaultdict
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
    status: str = "received"  # received | confirmed_zero | pending (data status this period)
    groups: List[CarrierGroup] = field(default_factory=list)


_GROUP_FOR = {"new": "New enrollments", "renewal": "Renewals",
              "bonus": "HRA", "chargeback": "Chargebacks", "adjustment": "Adjustments"}
_TYPE_LABEL = {"new": "New enrollment", "renewal": "Renewal",
               "bonus": "HRA", "chargeback": "Chargeback", "adjustment": "Adjustment"}


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

    # AJ's manual reconciliation adjustments (per agent+carrier+period). Each is a
    # synthetic line in its carrier block: payout = amount (no split — it's already
    # the final dollar effect); note shown as the "member" so the agent sees why.
    from app.models import CommissionAdjustment
    adjustments = (CommissionAdjustment.query
                   .filter_by(agent_id=agent_id, agency_id=agency_id, period_label=period_label)
                   .all())
    for adj in adjustments:
        amt = round(adj.amount or 0.0, 2)
        by_carrier.setdefault(adj.carrier, []).append(
            LineRow(member_name=adj.note, customer_id=None,
                    type_label=_TYPE_LABEL["adjustment"], type_kind="adjustment",
                    raw_amount=amt, split_rate=None, payout=amt))

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
        ordered = [groups[k] for k in ("new", "renewal", "bonus", "chargeback", "adjustment")
                   if k in groups]
        block = CarrierBlock(
            carrier=carrier,
            total_payout=round(sum(lr.payout for lr in lrs), 2),
            new_members=sum(1 for lr in lrs if lr.type_kind == "new"),
            groups=ordered,
        )
        blocks.append(block)
    blocks.sort(key=lambda b: b.total_payout, reverse=True)
    return blocks


def line_revisions(line_id, agency_id):
    """Revision history for one commission line, newest first, agency-scoped.
    Drives the 'who changed this, when, before->after' display + Undo control."""
    from app.models import CommissionLineItemRevision
    return (CommissionLineItemRevision.query
            .filter_by(line_item_id=line_id, agency_id=agency_id)
            .order_by(CommissionLineItemRevision.id.desc())
            .all())


def _suggested_quarantine_agent(li, agency_id):
    """The agent to pre-select on a quarantine row: the line's own agent_id, else
    another resolved line item for the same member (MBI) — same basis as the
    unassigned-customers view. Carrier-agnostic."""
    if li.agent_id:
        return li.agent_id
    if li.mbi:
        other = (CommissionLineItem.query
                 .filter_by(agency_id=agency_id, mbi=li.mbi)
                 .filter(CommissionLineItem.agent_id.isnot(None)).first())
        if other:
            return other.agent_id
    return None


def _quarantine_row(li, agency_id):
    return {"id": li.id, "carrier": li.carrier,
            "member_name": li.member_name or "(unnamed)", "mbi": li.mbi,
            "amount": round(li.raw_amount or 0.0, 2), "action": li.payment_type or "",
            "agent_id": li.agent_id,
            "suggested_agent_id": _suggested_quarantine_agent(li, agency_id)}


def quarantined_line_items(statement_id, agency_id):
    """needs_manual_review line items for ONE statement. Any carrier — these are
    recorded but NOT split (payout 0), so nothing is silently dropped; AJ resolves
    them in-line. Returns {count, total, rows:[{id, carrier, member_name, mbi,
    amount, action, agent_id, suggested_agent_id}]}."""
    items = (CommissionLineItem.query
             .filter_by(statement_id=statement_id, agency_id=agency_id,
                        classification="needs_manual_review")
             .order_by(CommissionLineItem.member_name)
             .all())
    rows = [_quarantine_row(li, agency_id) for li in items]
    return {"count": len(rows),
            "total": round(sum(r["amount"] for r in rows), 2),
            "rows": rows}


def _resolved_row(li, revisions):
    return {"id": li.id, "carrier": li.carrier,
            "member_name": li.member_name or "(unnamed)", "mbi": li.mbi,
            "amount": round(li.raw_amount or 0.0, 2), "action": li.payment_type or "",
            "agent_id": li.agent_id, "classification": li.classification,
            "revisions": revisions}


def _revisions_by_line(line_ids, agency_id):
    """Fetch ALL revisions for a set of line_ids in ONE query, grouped by
    line_item_id, newest first (avoids N+1 from calling line_revisions() per
    row in the recently-resolved feeds)."""
    from collections import defaultdict
    from app.models import CommissionLineItemRevision
    grouped = defaultdict(list)
    if not line_ids:
        return grouped
    revs = (CommissionLineItemRevision.query
            .filter(CommissionLineItemRevision.agency_id == agency_id,
                    CommissionLineItemRevision.line_item_id.in_(line_ids))
            .order_by(CommissionLineItemRevision.id.desc())
            .all())
    for r in revs:
        grouped[r.line_item_id].append(r)   # already newest-first due to id.desc() order
    return grouped


def recently_resolved_line_items(statement_id, agency_id):
    """Lines on ONE statement that have a revision history (resolved and/or
    edited via the quarantine workflow) and are NOT currently quarantined —
    i.e. what AJ can review + Undo. Newest-touched first. Each row carries its
    full `revisions` list (line_revisions()) for the history display."""
    from app.models import CommissionLineItemRevision
    line_ids = [lid for (lid,) in (
        db.session.query(CommissionLineItemRevision.line_item_id)
        .filter_by(agency_id=agency_id, statement_id=statement_id)
        .distinct().all())]
    if not line_ids:
        return []
    items = (CommissionLineItem.query
             .filter(CommissionLineItem.id.in_(line_ids),
                     CommissionLineItem.agency_id == agency_id,
                     CommissionLineItem.classification != "needs_manual_review")
             .all())
    revs_by_line = _revisions_by_line([li.id for li in items], agency_id)
    rows = [_resolved_row(li, revs_by_line.get(li.id, [])) for li in items]
    rows.sort(key=lambda r: max((rev.id for rev in r["revisions"]), default=0), reverse=True)
    return rows


def period_quarantine(agency_id, period_label):
    """ALL needs_manual_review line items for a period, across every carrier /
    statement — what the agency-overview matrix links to. Same row shape as
    quarantined_line_items, plus a per-carrier breakdown for the header."""
    items = (CommissionLineItem.query
             .filter_by(agency_id=agency_id, period_label=period_label,
                        classification="needs_manual_review")
             .order_by(CommissionLineItem.carrier, CommissionLineItem.member_name)
             .all())
    rows = [_quarantine_row(li, agency_id) for li in items]
    by_carrier = {}
    for r in rows:
        b = by_carrier.setdefault(r["carrier"], {"count": 0, "total": 0.0})
        b["count"] += 1
        b["total"] = round(b["total"] + r["amount"], 2)
    return {"count": len(rows),
            "total": round(sum(r["amount"] for r in rows), 2),
            "rows": rows, "by_carrier": by_carrier}


def _period_sort_key(period_label):
    """Sort key for a 'June 2026' label → its first-of-month date, so periods order
    chronologically (newest-first when reversed). Unparseable labels sort oldest."""
    from datetime import datetime
    try:
        return datetime.strptime(period_label or "", "%B %Y")
    except ValueError:
        return datetime.min


def quarantine_workbench(agency_id, *, period=None, carrier=None, agent_id=None, sort=None):
    """The standalone Quarantine Workbench data: every needs_manual_review line for
    the agency, optionally filtered by period/carrier/agent. Default = all months
    GROUPED by month (newest first). When `sort` is 'amount_asc'/'amount_desc' the
    grouping is FLATTENED into one amount-sorted list so identical amounts cluster
    across months. Returns:
      {count, total, sort, grouped, groups:[{period_label,count,total,rows:[...]}],
       flat:[...], by_carrier:{carrier:{count,total}},
       filter_options:{periods:[...], carriers:[...], agents:[user_id,...]}}
    Rows use the shared _quarantine_row shape (id/carrier/member_name/mbi/amount/
    action/agent_id/suggested_agent_id) plus 'period_label' for display."""
    q = CommissionLineItem.query.filter_by(
        agency_id=agency_id, classification="needs_manual_review")
    if period:
        q = q.filter(CommissionLineItem.period_label == period)
    if carrier:
        q = q.filter(CommissionLineItem.carrier == carrier)
    if agent_id:
        q = q.filter(CommissionLineItem.agent_id == agent_id)
    items = q.all()

    def row(li):
        r = _quarantine_row(li, agency_id)
        r["period_label"] = li.period_label or ""
        return r
    rows = [row(li) for li in items]

    total = round(sum(r["amount"] for r in rows), 2)
    by_carrier = {}
    for r in rows:
        b = by_carrier.setdefault(r["carrier"], {"count": 0, "total": 0.0})
        b["count"] += 1
        b["total"] = round(b["total"] + r["amount"], 2)

    # filter options = the distinct periods/carriers/agents that HAVE quarantine
    # (across the WHOLE agency, ignoring current filters, so the dropdowns are stable).
    all_items = CommissionLineItem.query.filter_by(
        agency_id=agency_id, classification="needs_manual_review").all()
    periods = sorted({li.period_label for li in all_items if li.period_label},
                     key=_period_sort_key, reverse=True)
    carriers = sorted({li.carrier for li in all_items if li.carrier})
    agents = sorted({li.agent_id for li in all_items if li.agent_id})

    result = {"count": len(rows), "total": total, "sort": sort,
              "by_carrier": by_carrier,
              "filter_options": {"periods": periods, "carriers": carriers, "agents": agents}}

    if sort in ("amount_asc", "amount_desc"):
        flat = sorted(rows, key=lambda r: r["amount"], reverse=(sort == "amount_desc"))
        result.update({"grouped": False, "flat": flat, "groups": []})
        return result

    # default: group by month, newest first; rows within a group by member name
    by_period = defaultdict(list)
    for r in rows:
        by_period[r["period_label"]].append(r)
    groups = []
    for plabel in sorted(by_period, key=_period_sort_key, reverse=True):
        grp_rows = sorted(by_period[plabel], key=lambda r: (r["member_name"] or ""))
        groups.append({"period_label": plabel, "count": len(grp_rows),
                       "total": round(sum(r["amount"] for r in grp_rows), 2),
                       "rows": grp_rows})
    result.update({"grouped": True, "groups": groups, "flat": []})
    return result


def recompute_ledger_total(stmt, agency_id):
    """Set stmt.ledger_total = Σ raw_amount of its persisted line items (the
    provable internal total). Returns the total. Used to backfill pre-A3 statements
    — money_rows_total (the independent file re-sum) can't be recovered without the
    original file, so a backfilled statement that has no money_rows_total stays
    'unknown' until re-uploaded."""
    from app.models import CommissionLineItem
    total = round(sum(
        (li.raw_amount or 0.0) for li in
        CommissionLineItem.query.filter_by(statement_id=stmt.id, agency_id=agency_id).all()
    ), 2)
    stmt.ledger_total = total
    return total


def balance_status(stmt):
    """A3 — the balance gate's display state for a statement, from its persisted
    balance result. Returns (state, delta):
      'ok'      — Σ line items == the carrier file's money-row total (balances)
      'off'     — they diverge by |delta| (a row was dropped/mis-summed — surface it)
      'unknown' — not yet checked (pre-A3 statement, or a carrier with no extractor)
    delta = ledger_total − money_rows_total (rounded)."""
    if stmt.balanced is None or stmt.ledger_total is None or stmt.money_rows_total is None:
        return ("unknown", 0.0)
    delta = round((stmt.ledger_total or 0.0) - (stmt.money_rows_total or 0.0), 2)
    return ("ok", 0.0) if stmt.balanced else ("off", delta)


def quarantine_total_count(agency_id):
    """Total needs_manual_review line items for the agency — the nav badge count."""
    return CommissionLineItem.query.filter_by(
        agency_id=agency_id, classification="needs_manual_review").count()


def recently_resolved_workbench(agency_id, *, period=None, carrier=None, agent_id=None, limit=100):
    """Resolved/edited commission lines across the WHOLE agency (every statement),
    for the Quarantine Workbench's 'Recently resolved' section so AJ can Undo/Edit a
    change from the all-months triage page. Honors the same period/carrier/agent
    filters as the workbench. A line undone back to needs_manual_review is excluded
    (it's in the active quarantine list instead). Newest change first, capped."""
    from app.models import CommissionLineItemRevision
    line_ids = [lid for (lid,) in (
        db.session.query(CommissionLineItemRevision.line_item_id)
        .filter(CommissionLineItemRevision.agency_id == agency_id)
        .distinct().all())]
    if not line_ids:
        return []
    q = (CommissionLineItem.query
         .filter(CommissionLineItem.id.in_(line_ids),
                 CommissionLineItem.agency_id == agency_id,
                 CommissionLineItem.classification != "needs_manual_review"))
    if period:
        q = q.filter(CommissionLineItem.period_label == period)
    if carrier:
        q = q.filter(CommissionLineItem.carrier == carrier)
    if agent_id:
        q = q.filter(CommissionLineItem.agent_id == agent_id)
    items = q.all()
    revs_by_line = _revisions_by_line([li.id for li in items], agency_id)
    rows = []
    for li in items:
        r = _resolved_row(li, revs_by_line.get(li.id, []))
        r["period_label"] = li.period_label or ""
        rows.append(r)
    rows.sort(key=lambda r: max((rev.id for rev in r["revisions"]), default=0), reverse=True)
    return rows[:limit]


def recently_resolved_period_line_items(agency_id, period_label):
    """Same as recently_resolved_line_items but across every statement in a
    period — what the period-level review page ('Payments to Review') shows
    so AJ can Undo a resolve regardless of which statement it came from."""
    from app.models import CommissionLineItemRevision, CommissionStatement
    stmt_ids = [sid for (sid,) in (
        db.session.query(CommissionStatement.id)
        .filter_by(agency_id=agency_id, period_label=period_label).all())]
    if not stmt_ids:
        return []
    line_ids = [lid for (lid,) in (
        db.session.query(CommissionLineItemRevision.line_item_id)
        .filter(CommissionLineItemRevision.agency_id == agency_id,
                CommissionLineItemRevision.statement_id.in_(stmt_ids))
        .distinct().all())]
    if not line_ids:
        return []
    items = (CommissionLineItem.query
             .filter(CommissionLineItem.id.in_(line_ids),
                     CommissionLineItem.agency_id == agency_id,
                     CommissionLineItem.classification != "needs_manual_review")
             .all())
    revs_by_line = _revisions_by_line([li.id for li in items], agency_id)
    rows = [_resolved_row(li, revs_by_line.get(li.id, [])) for li in items]
    rows.sort(key=lambda r: max((rev.id for rev in r["revisions"]), default=0), reverse=True)
    return rows


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


def carrier_period_status(agency_id, period_label, carrier=None):
    """Per-(carrier, period) data status for the agency:
      'received'       — a CommissionStatement was uploaded for this carrier+period
      'confirmed_zero' — no statement, but AJ confirmed there was no business
      'pending'        — neither: the statement hasn't been uploaded yet
    Returns a {carrier: status} dict, or a single status string if `carrier` given."""
    from app.models import CommissionStatement, CarrierPeriodConfirmation
    received = {c for (c,) in db.session.query(CommissionStatement.carrier)
                .filter_by(agency_id=agency_id, period_label=period_label).distinct()}
    confirmed = {c for (c,) in db.session.query(CarrierPeriodConfirmation.carrier)
                 .filter_by(agency_id=agency_id, period_label=period_label).distinct()}

    def _status(c):
        if c in received:
            return "received"
        if c in confirmed:
            return "confirmed_zero"
        return "pending"

    if carrier is not None:
        return _status(carrier)
    return {c: "received" for c in received} | {c: "confirmed_zero" for c in confirmed if c not in received}


def build_aggregate_matrix(agency_id, scope="month", period_label=None, year=None):
    """Admin all-agents × all-carriers matrix (#6, Option A). One cell per
    (agent, carrier) with agent `payout` (take-home, incl. adjustments — matches
    the agent's recap carrier total) and Founders `keep` (override/keep). Plus row
    totals, carrier column totals, and a grand total.

    scope='month' uses period_label ("May 2026"); scope='ytd' sums every period in
    `year` (defaults to the current period's year). Returns a dict the template
    renders directly."""
    from app.models import User, CommissionAdjustment

    PAYOUT_CLASSES = {"agent_commission", "hra_bonus", "chargeback"}

    def _in_scope(li):
        if scope == "month":
            return li.period_label == period_label
        try:
            return datetime.strptime(li.period_label or "", "%B %Y").year == year
        except ValueError:
            return False

    rows_q = CommissionLineItem.query.filter_by(agency_id=agency_id)
    if scope == "month":
        rows_q = rows_q.filter_by(period_label=period_label)
    lis = [li for li in rows_q.all() if _in_scope(li)]

    # accumulate per (agent_id, carrier):
    #   pay        = agent take-home (split commissions + HRA + chargebacks)
    #   split_keep = Founders' share of those split commissions
    #   override   = pure founders_override lines (100% Founders)
    #   pending    = unsplit quarantine (needs_manual_review) rows — NOT counted as
    #                Founders keep (they're awaiting AJ's split, e.g. UHC "New"
    #                enrollments). Surfaced separately so a big "New" month doesn't
    #                inflate an agent's keep (the Mike $9,177 bug).
    pay = defaultdict(float)
    split_keep = defaultdict(float)
    override = defaultdict(float)
    pending = defaultdict(float)
    pending_count = 0
    carriers, agents_with_data = set(), set()
    for li in lis:
        p, k = split_breakdown(li)
        carriers.add(li.carrier)
        agents_with_data.add(li.agent_id)
        key = (li.agent_id, li.carrier)
        if li.classification == "founders_override":
            override[key] += k
        elif li.classification in PAYOUT_CLASSES:
            pay[key] += p
            split_keep[key] += k
        else:
            pending[key] += (li.raw_amount or 0.0)
            pending_count += 1

    # adjustments fold into payout (per agent+carrier; scope-filtered)
    adj_q = CommissionAdjustment.query.filter_by(agency_id=agency_id)
    if scope == "month":
        adj_q = adj_q.filter_by(period_label=period_label)
    for adj in adj_q.all():
        if scope == "ytd":
            try:
                if datetime.strptime(adj.period_label or "", "%B %Y").year != year:
                    continue
            except ValueError:
                continue
        carriers.add(adj.carrier)
        agents_with_data.add(adj.agent_id)
        pay[(adj.agent_id, adj.carrier)] += (adj.amount or 0.0)

    carriers = sorted(carriers)
    users = {u.id: u.name for u in User.query.filter_by(agency_id=agency_id).all()}

    rows = []
    for aid in agents_with_data:
        name = users.get(aid, "(unattributed)") if aid else "(unattributed)"
        cells = {}
        for c in carriers:
            pv = round(pay.get((aid, c), 0.0), 2)
            sk = round(split_keep.get((aid, c), 0.0), 2)
            ov = round(override.get((aid, c), 0.0), 2)
            pd = round(pending.get((aid, c), 0.0), 2)
            if pv or sk or ov or pd:
                cells[c] = {"payout": pv, "split_keep": sk, "override": ov,
                            "keep": round(sk + ov, 2), "pending": pd}
        rows.append({
            "agent_id": aid, "agent_name": name, "cells": cells,
            "payout_total": round(sum(v["payout"] for v in cells.values()), 2),
            "split_keep_total": round(sum(v["split_keep"] for v in cells.values()), 2),
            "override_total": round(sum(v["override"] for v in cells.values()), 2),
            "keep_total": round(sum(v["keep"] for v in cells.values()), 2),
            "pending_total": round(sum(v["pending"] for v in cells.values()), 2),
        })
    rows.sort(key=lambda r: r["payout_total"], reverse=True)

    def _coltot(c, field):
        return round(sum(r["cells"].get(c, {}).get(field, 0.0) for r in rows), 2)
    carrier_totals = {c: {"payout": _coltot(c, "payout"),
                          "split_keep": _coltot(c, "split_keep"),
                          "override": _coltot(c, "override"),
                          "keep": _coltot(c, "keep"),
                          "pending": _coltot(c, "pending")} for c in carriers}
    grand = {
        "payout": round(sum(r["payout_total"] for r in rows), 2),
        "split_keep": round(sum(r["split_keep_total"] for r in rows), 2),
        "override": round(sum(r["override_total"] for r in rows), 2),
        "keep": round(sum(r["keep_total"] for r in rows), 2),
        "pending": round(sum(r["pending_total"] for r in rows), 2),
        "pending_count": pending_count,
    }
    # Read-only "Founders Agency" row: the agency's own earnings = all
    # founders_override per carrier (100% Founders, written under the agency NPN /
    # paired with each agent's split). Surfaced as a first-class row so AJ sees what
    # the agency itself made on overrides, without making it a real agent.
    agency_row = {
        "cells": {c: carrier_totals[c]["override"] for c in carriers
                  if carrier_totals[c]["override"]},
        "total": round(sum(carrier_totals[c]["override"] for c in carriers), 2),
    }
    return {"scope": scope, "period_label": period_label, "year": year,
            "carriers": carriers, "rows": rows, "agency_row": agency_row,
            "carrier_totals": carrier_totals, "grand": grand}


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

    # Persistent carrier containers: show EVERY carrier this agent is contracted
    # with, even at $0, so a carrier never silently disappears. Tag each with its
    # data status (received / confirmed_zero / pending) so $0 from "no business
    # confirmed" is distinguishable from "statement not uploaded yet".
    from app.models import AgentCarrierContract
    status_map = carrier_period_status(agency_id, period_label)
    contracted = {c.carrier for c in AgentCarrierContract.query
                  .filter_by(agent_id=agent_id, agency_id=agency_id, is_active=True).all()}
    present = {b.carrier for b in carriers}
    for carrier in contracted - present:
        carriers.append(CarrierBlock(carrier=carrier, total_payout=0.0, new_members=0,
                                     status=status_map.get(carrier, "pending")))
    for b in carriers:
        b.status = status_map.get(b.carrier, "received" if b.groups else "pending")
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
