"""The ONLY place agency book/money numbers are computed (spec §1, §3a).
Book numbers come from Policy (BOB); money comes from the commission ledger via
split_breakdown. Every page is a thin caller passing a Scope. Enforced by
tests/test_metrics_guard.py."""
from dataclasses import dataclass
from datetime import date, timedelta
from sqlalchemy import func
from app.extensions import db
from app.models import Policy, CommissionLineItem, Customer, User
from app.commission.ledger import split_breakdown


@dataclass
class Scope:
    agency_id: int
    agent_id: int | None = None
    carrier: str | None = None
    period: str | None = None


def _policy_q(scope):
    q = (Policy.query.filter_by(status="active", agency_id=scope.agency_id)
         .filter(~Policy.member_id.like("%::0::%")))  # exclude commission stub placeholders
    if scope.agent_id is not None:
        q = q.filter(Policy.agent_id == scope.agent_id)
    if scope.carrier:
        q = q.filter(Policy.carrier == scope.carrier)
    return q


def policy_count(scope) -> int:
    return _policy_q(scope).count()


def _grouped(scope, col):
    base = _policy_q(scope)
    total = base.count()
    rows = (base.with_entities(col, func.count(Policy.id))
            .group_by(col).order_by(func.count(Policy.id).desc()).all())
    return [{"key": k if k is not None else "—", "count": n,
             "pct": round(n / total * 100, 1) if total else 0.0} for k, n in rows]


def _by_plan(scope):
    """Group active policies by their LINKED Plan bucket (plan_id), NOT the free-text
    Policy.plan_name. Each row keys off the canonical bucket (name + plan_id, so the UI
    links via the id — no name string-match). Policies with no plan_id collapse into ONE
    honest 'Unlinked' row (plan_id=None), not clickable. Rows sum to the carrier total."""
    from app.models import Plan
    base = _policy_q(scope)
    total = base.count()
    rows = (base.with_entities(Policy.plan_id, func.count(Policy.id))
            .group_by(Policy.plan_id).all())
    # resolve plan_id → canonical (name, type) in one query
    ids = [pid for pid, _ in rows if pid is not None]
    plans = {p.id: p for p in Plan.query.filter(Plan.id.in_(ids)).all()} if ids else {}
    out = []
    unlinked = 0
    for pid, n in rows:
        if pid is None or pid not in plans:
            unlinked += n
            continue
        p = plans[pid]
        out.append({"key": p.plan_name or f"Plan {pid}", "plan_id": pid, "count": n,
                    "pct": round(n / total * 100, 1) if total else 0.0})
    out.sort(key=lambda r: r["count"], reverse=True)
    if unlinked:
        out.append({"key": "Unlinked / needs plan", "plan_id": None, "count": unlinked,
                    "pct": round(unlinked / total * 100, 1) if total else 0.0})
    return out


# Canonical plan-type label — collapses the casing drift between the two bucket
# generations (CMS seed "MA"/"PDP" vs old-gen "mapd"/"pdp") so the mix reads cleanly.
# NOTE: MA and MAPD are kept DISTINCT (MA = Advantage no-drug, MAPD = with drug) — both
# are Part C. The full Part-C-parent + SNP/network taxonomy is a separate Layer-2/3 spec.
_PLAN_TYPE_LABEL = {
    "ma": "MA", "mapd": "MAPD", "pdp": "PDP", "medigap": "Medigap", "ms": "Medigap",
    "dvh": "DVH", "dental": "DVH", "pffs": "PFFS", "": "Unknown",
}


def _canon_plan_type(pt):
    pt = (pt or "").strip()
    return _PLAN_TYPE_LABEL.get(pt.lower(), pt)


def _by_plan_type(scope):
    """Plan-type mix derived from the LINKED bucket's type (clean MA/MAPD/PDP/Medigap/DVH),
    NOT the unreliable free-text Policy.plan_type; casing canonicalized so the two bucket
    generations don't split (MA vs mapd). Unlinked policies → 'Unknown'. Reconciles to the
    carrier total so it agrees with the Plans container."""
    from app.models import Plan
    base = _policy_q(scope)
    total = base.count()
    rows = (base.with_entities(Policy.plan_id, func.count(Policy.id))
            .group_by(Policy.plan_id).all())
    ids = [pid for pid, _ in rows if pid is not None]
    plans = {p.id: p for p in Plan.query.filter(Plan.id.in_(ids)).all()} if ids else {}
    tally = {}
    for pid, n in rows:
        p = plans.get(pid) if pid is not None else None
        key = _canon_plan_type(p.plan_type) if p and p.plan_type else "Unknown"
        tally[key] = tally.get(key, 0) + n
    out = [{"key": k, "count": v, "pct": round(v / total * 100, 1) if total else 0.0}
           for k, v in tally.items()]
    out.sort(key=lambda r: r["count"], reverse=True)
    return out


def book_breakdown(scope) -> dict:
    by_agent_rows = (_policy_q(scope)
                     .with_entities(Policy.agent_id, func.count(Policy.id))
                     .group_by(Policy.agent_id)
                     .order_by(func.count(Policy.id).desc()).all())
    total = _policy_q(scope).count()
    by_agent = []
    for aid, n in by_agent_rows:
        u = db.session.get(User, aid) if aid else None
        by_agent.append({"key": u.display_name if u else "Unattributed", "agent_id": aid,
                         "count": n, "pct": round(n / total * 100, 1) if total else 0.0})
    return {
        "by_carrier": _grouped(scope, Policy.carrier),
        "by_plan_type": _by_plan_type(scope),
        "by_plan": _by_plan(scope),
        "by_agent": by_agent,
    }


def commission_totals(scope) -> dict:
    q = CommissionLineItem.query.filter_by(agency_id=scope.agency_id)
    if scope.agent_id is not None:
        q = q.filter(CommissionLineItem.agent_id == scope.agent_id)
    if scope.carrier:
        q = q.filter(CommissionLineItem.carrier == scope.carrier)
    if scope.period:
        q = q.filter(CommissionLineItem.period_label == scope.period)
    paid = payout = keep = 0.0
    for li in q.all():
        a, f = split_breakdown(li)
        paid += li.raw_amount or 0.0
        payout += a
        keep += f
    return {"paid": round(paid, 2), "agent_payout": round(payout, 2),
            "founders_keep": round(keep, 2)}


def upcoming_terms(scope, days=30) -> list:
    today = date.today()
    end = today + timedelta(days=days)
    q = (_policy_q(scope)
         .filter(Policy.term_date.isnot(None),
                 Policy.term_date >= today, Policy.term_date <= end)
         .order_by(Policy.term_date.asc()))
    rows = q.all()
    mbis = [p.mbi for p in rows if p.mbi]
    cust = {}
    if mbis:
        for mbi, cid in (Customer.query
                         .filter(Customer.mbi.in_(mbis), Customer.agency_id == scope.agency_id)
                         .with_entities(Customer.mbi, Customer.id).all()):
            cust[mbi] = cid
    return [{"member": f"{p.first_name} {p.last_name}".strip(), "plan": p.plan_name,
             "carrier": p.carrier, "term_date": p.term_date, "reason": p.term_reason,
             "customer_id": cust.get(p.mbi)} for p in rows]


def attribution_coverage(scope) -> dict:
    total = _policy_q(scope).count()
    attributed = _policy_q(scope).filter(Policy.agent_id.isnot(None)).count()
    return {"total": total, "attributed": attributed,
            "pct": round(attributed / total * 100, 1) if total else 100.0}
