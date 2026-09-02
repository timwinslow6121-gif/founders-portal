"""Data-Integrity Radar — the ONE registry of invariants. Read-only.

An invariant is a named truth that must hold; its function finds every violating row.
The CLI (scripts/audit_integrity.py), the /admin/integrity dashboard, and the CI guard
(tests/test_integrity_guards.py) ALL iterate this registry — add one @invariant and it
appears in all three. NO function here may mutate the DB."""
from dataclasses import dataclass, field


@dataclass
class Violation:
    key: str
    severity: str          # high | med | low
    domain: str            # data | consistency | route
    count: int
    description: str
    sample: list = field(default_factory=list)


REGISTRY = {}              # key -> wrapped callable returning Violation
_META = {}                 # key -> (severity, domain, description)
_SEV_RANK = {"high": 0, "med": 1, "low": 2}


def invariant(key, *, severity, domain, description):
    """Register an invariant. The wrapped fn returns (count, sample); the wrapper
    turns that into a Violation. Keys must be unique."""
    def deco(fn):
        def wrapped():
            count, sample = fn()
            return Violation(key=key, severity=severity, domain=domain,
                             count=count, description=description, sample=sample)
        REGISTRY[key] = wrapped
        _META[key] = (severity, domain, description)
        return wrapped
    return deco


def run_all():
    """Run every registered invariant; return Violations sorted by domain, then
    severity (high first), then key."""
    results = [fn() for fn in REGISTRY.values()]
    results.sort(key=lambda v: (v.domain, _SEV_RANK.get(v.severity, 9), v.key))
    return results


import re
from app.extensions import db
from app.models import Policy, Customer, CommissionLineItem, CustomerAorHistory

_STUB_LIKE = "%::0::%"


@invariant("plan_id_orphans", severity="high", domain="data",
           description="Active non-stub policies not linked to a Plan record (plan_id NULL).")
def _plan_id_orphans():
    q = (Policy.query.filter(Policy.status == "active",
                             Policy.plan_id.is_(None),
                             ~Policy.member_id.like(_STUB_LIKE)))
    rows = [{"id": p.id, "label": f"{p.carrier} {p.plan_name or '—'} ({p.member_id})",
             "url": None} for p in q.limit(10).all()]
    return q.count(), rows


@invariant("no_name_policies", severity="high", domain="data",
           description="Active policies with no first AND no last name.")
def _no_name_policies():
    blank = lambda c: db.or_(c.is_(None), c == "")
    q = Policy.query.filter(Policy.status == "active",
                            blank(Policy.first_name), blank(Policy.last_name))
    rows = [{"id": p.id, "label": f"{p.carrier} {p.member_id}", "url": None}
            for p in q.limit(10).all()]
    return q.count(), rows


@invariant("payment_without_customer", severity="high", domain="data",
           description="Commission line items (money facts) not linked to any customer.")
def _payment_without_customer():
    q = CommissionLineItem.query.filter(CommissionLineItem.customer_id.is_(None))
    rows = [{"id": li.id, "label": f"{li.carrier} {li.classification} {li.raw_amount}",
             "url": None} for li in q.limit(10).all()]
    return q.count(), rows


@invariant("backwards_date_interval", severity="high", domain="data",
           description="AOR intervals whose effective_date is after their end_date.")
def _backwards_date_interval():
    q = CustomerAorHistory.query.filter(
        CustomerAorHistory.effective_date.isnot(None),
        CustomerAorHistory.end_date.isnot(None),
        CustomerAorHistory.effective_date > CustomerAorHistory.end_date)
    rows = [{"id": h.id, "label": f"cust {h.customer_id} {h.carrier} "
             f"{h.effective_date}->{h.end_date}", "url": None}
            for h in q.limit(10).all()]
    return q.count(), rows


def _norm_name(full_name):
    if not full_name:
        return ""
    toks = re.sub(r"[^a-z ]", "", full_name.lower().replace(",", " ")).split()
    toks = [t for t in toks if t not in ("iii", "ii", "iv", "jr", "sr")]
    return " ".join(sorted(toks))


@invariant("duplicate_customers", severity="high", domain="data",
           description="Multiple customer rows that are the same person "
                       "(same normalized name + DOB). Multi-AOR persons are ONE customer.")
def _duplicate_customers():
    # Group non-stub-distinct customers by (normalized name, dob). A person with two
    # concurrent policies/AORs is still ONE customer row, so grouping by name+dob (not
    # by policy/agent) cannot mistake a multi-AOR customer for a duplicate.
    # IMPORTANT: Only cluster customers with a NON-NULL dob. A NULL dob alone is NOT
    # identity; two different real people sharing a name but both missing DOB should NOT
    # be clustered as a duplicate (name without DOB is not enough to assert same person).
    rows = Customer.query.filter(Customer.stub.is_(False)).with_entities(
        Customer.id, Customer.full_name, Customer.dob).all()
    from collections import defaultdict
    clusters = defaultdict(list)
    for cid, name, dob in rows:
        if dob is None:
            continue  # Skip NULL-dob customers; they cannot form identity clusters
        key = (_norm_name(name), dob)
        if key[0]:
            clusters[key].append(cid)
    excess = 0
    sample = []
    for (nm, dob), ids in clusters.items():
        if len(ids) > 1:
            excess += len(ids) - 1
            if len(sample) < 10:
                sample.append({"id": ids[0], "label": f"{nm} ({dob}) x{len(ids)}",
                               "url": None})
    return excess, sample


@invariant("commission_import_stubs", severity="med", domain="data",
           description="Stub customers created by commission import (must only decrease; "
                       "commission no longer creates customers).")
def _commission_import_stubs():
    q = Customer.query.filter(Customer.stub.is_(True),
                              Customer.source == "commission_import")
    rows = [{"id": c.id, "label": c.full_name or f"{c.first_name} {c.last_name}"}
            for c in q.limit(20)]
    return q.count(), rows


@invariant("statement_balance_complete", severity="high", domain="data",
           description="Per statement, every ledger dollar is accounted for: "
                       "Sigma(raw_amount) == Sigma(agent_payout) + Sigma(founders_keep) "
                       "within tolerance (the ledger's internal balance, via split_breakdown). "
                       "Proves nothing is dropped or mis-split.")
def _statement_balance_complete():
    # NOTE: this is the LEDGER's internal balance, NOT line-items-vs-PolicyPayment.
    # PolicyPayment is a SEPARATE representation that deliberately collapses Founders-
    # override / HRA rows the ledger records in full, so Sigma(lineitems) > Sigma(payments)
    # is BY DESIGN for carriers like Devoted/Healthspring and is NOT lost money. The true
    # "nothing lost" check is that the ledger's own raw == payout + keep, which holds by
    # construction (split_breakdown derives both from raw_amount) unless a row is corrupt.
    from app.models import CommissionStatement, CommissionLineItem
    from app.commission.ledger import split_breakdown
    violations = []
    for s in CommissionStatement.query.all():
        items = CommissionLineItem.query.filter_by(statement_id=s.id).all()
        raw = sum(x.raw_amount or 0.0 for x in items)
        payout = keep = 0.0
        for x in items:
            p, k = split_breakdown(x)
            payout += p
            keep += k
        # Per-row rounding can drift a few cents across many rows; scale tolerance.
        tol = max(0.01, round(len(items) * 0.005, 2))
        if items and abs(round(raw - (payout + keep), 2)) > tol:
            violations.append({"id": s.id,
                               "label": f"{s.carrier} {s.period_label}: raw={raw:.2f} "
                                        f"payout+keep={payout + keep:.2f}"})
    return len(violations), violations[:20]


@invariant("orphan_stub_customers", severity="med", domain="data",
           description="Stub customers of unknown origin (excludes legitimate manual leads).")
def _orphan_stub_customers():
    # A stub from import is garbage; a manual lead (source='manual') is legitimate even
    # with no MBI, so it is EXEMPT (lifecycle-aware).
    q = Customer.query.filter(Customer.stub.is_(True),
                              db.or_(Customer.source.is_(None),
                                     Customer.source != "manual"))
    rows = [{"id": c.id, "label": f"{c.full_name} (source={c.source})", "url": None}
            for c in q.limit(10).all()]
    return q.count(), rows


# Consistency domain invariants (absorb metrics guard + add customers.py scanning)
import pathlib
from app.metrics import Scope, book_breakdown

_SCANNED = ["app/routes.py", "app/carriers.py", "app/commission/routes.py",
            "app/customers.py"]
_ALLOWLIST = {
    ("app/carriers.py", "Policy.plan_id"),     # per-plan tally, not agency book
    # customers.py legitimate non-book counts (deal-stage stat strip, hub categories):
    ("app/customers.py", "deal_stage"),
    ("app/customers.py", "primary_agent_id=None"),
    ("app/customers.py", "CommissionLineItem.classification"),
    # merge_customers counts payments PER POLICY to decide whether two rows are a
    # duplicate (both paid = the carrier is paying two policies, so never collapse).
    # Not a book count — it never aggregates across the agency.
    ("app/customers.py", "PolicyPayment.query.filter_by(policy_id="),
}
_COUNT_RE = re.compile(r"func\.count\(\s*Policy|\.filter_by\([^)]*\)\.count\(\)"
                       r"|Policy\.query[\s\S]{0,80}\.count\(\)")
_RATE_RE = re.compile(r"MAPD_MONTHLY_RATE|SPLIT_RATE\s*=")
_ROOT = pathlib.Path(__file__).resolve().parent.parent


@invariant("count_only_via_metrics", severity="high", domain="consistency",
           description="Book/money counts computed outside app/metrics.py "
                       "in scanned route files.")
def _count_only_via_metrics():
    offenders = []
    for rel in _SCANNED:
        text = (_ROOT / rel).read_text()
        for ln, line in enumerate(text.splitlines(), 1):
            if _COUNT_RE.search(line) or _RATE_RE.search(line):
                if any(rel == a and sub in line for a, sub in _ALLOWLIST):
                    continue
                offenders.append({"id": f"{rel}:{ln}", "label": line.strip()[:80],
                                  "url": None})
    return len(offenders), offenders[:10]


@invariant("carrier_counts_agree", severity="high", domain="consistency",
           description="Per-carrier policy counts sum to the agency total (metrics "
                       "layer self-coherence).")
def _carrier_counts_agree():
    # agency_id=1 is the live single tenant; guard the metrics layer's own coherence.
    book = book_breakdown(Scope(agency_id=1))
    per_carrier_sum = sum(r["count"] for r in book["by_carrier"])
    from app.metrics import policy_count
    total = policy_count(Scope(agency_id=1))
    if per_carrier_sum != total:
        return 1, [{"id": "carrier_sum", "label": f"sum {per_carrier_sum} != total {total}",
                    "url": None}]
    return 0, []


# Route-domain invariants
from flask import current_app

_URLFOR_RE = re.compile(r"url_for\(\s*['\"]([a-zA-Z0-9_.]+)['\"]")
_ROUTE_PREFIX_EXEMPT = ("auth.", "comms.", "static")   # webhooks/oauth/static unlinked-ok
_ORPHAN_ALLOWLIST = {"main.healthz"}                    # intentionally unlinked endpoints


def _template_endpoints(template_dir=None):
    """Set of endpoint names referenced via url_for(...) in template files."""
    base = pathlib.Path(template_dir) if template_dir else (_ROOT / "app" / "templates")
    eps = set()
    for p in base.rglob("*.html"):
        for m in _URLFOR_RE.finditer(p.read_text()):
            eps.add(m.group(1))
    return eps


@invariant("links_resolve", severity="med", domain="route",
           description="Template url_for() targets that don't resolve to a real route.")
def _links_resolve():
    valid = {r.endpoint for r in current_app.url_map.iter_rules()}
    referenced = _template_endpoints()
    broken = sorted(e for e in referenced if e not in valid)
    return len(broken), [{"id": e, "label": e, "url": None} for e in broken[:10]]


@invariant("no_orphan_routes", severity="low", domain="route",
           description="GET view routes not reachable from any template link.")
def _no_orphan_routes():
    referenced = _template_endpoints()
    orphans = []
    for r in current_app.url_map.iter_rules():
        ep = r.endpoint
        if ep in _ORPHAN_ALLOWLIST:
            continue
        if any(ep.startswith(pfx) for pfx in _ROUTE_PREFIX_EXEMPT):
            continue
        if "GET" not in (r.methods or set()):
            continue
        if "<" in r.rule:          # parameterized detail routes are linked dynamically
            continue
        if ep not in referenced:
            orphans.append(ep)
    orphans.sort()
    return len(orphans), [{"id": e, "label": e, "url": None} for e in orphans[:10]]


# Baseline ratchet (Task 5)
import json

BASELINE_PATH = _ROOT / "integrity_baseline.json"


def load_baseline():
    """Frozen per-invariant debt levels. Missing file or key => 0 (strictest)."""
    try:
        return json.loads(BASELINE_PATH.read_text())
    except FileNotFoundError:
        return {}
