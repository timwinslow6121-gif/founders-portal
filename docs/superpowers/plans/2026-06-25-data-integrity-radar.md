# Data-Integrity Radar & Guard Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only data-integrity radar — one `@invariant` registry feeding a CLI, an `/admin/integrity` dashboard, and a CI baseline-ratchet guard — that detects every data/consistency/route violation, prevents regression, and never false-positives on legitimate leads or multi-AOR customers.

**Architecture:** A single registry module `app/integrity.py` holds `@invariant`-decorated functions; each returns a `Violation(key, severity, domain, count, sample, description)` from a read-only query. `run_all()` iterates the registry and is consumed identically by `scripts/audit_integrity.py` (CLI/CI), `/admin/integrity` (dashboard), and `tests/test_integrity_guards.py` (ratchet vs `integrity_baseline.json`). The radar NEVER mutates data.

**Tech Stack:** Python 3.10, Flask 3.0, Flask-SQLAlchemy, pytest. Read-only SQLAlchemy queries against the existing models (Policy, Customer, PolicyPayment, CustomerAorHistory, Plan).

## Global Constraints

- The radar is **read-only** — no invariant function may mutate the DB.
- **One registry, three consumers** — CLI, admin page, and CI guard all call `app/integrity.py::run_all()`. No consumer defines its own invariant list.
- **Lifecycle-aware:** a customer with `source='manual'` and `deal_stage` NOT in (`Active`, `Termed`) is a LEAD — exempt from "must have MBI" / "must trace to carrier" invariants. Only `deal_stage='Active'` people are held to customer-grade invariants. (`Customer.deal_stage` ∈ `Lead/SOA_Sent/Appointed/Enrolled/Active/Termed`; `Customer.source` ∈ `manual/bob/commission_import/healthsherpa`.)
- **Multi-AOR-aware:** a person with two concurrent policies/AORs is ONE customer, never a duplicate; agent attribution derives from the POLICY's AOR (`CustomerAorHistory.agent_id`), not solely `Customer.primary_agent_id`.
- **Stub placeholder exclusion:** policies whose `member_id` matches `%::0::%` are commission stub placeholders — excluded from active-policy book invariants (same rule as `app/metrics.py::_policy_q`).
- **Baseline ratchet:** the CI guard fails ONLY when a live count EXCEEDS its baseline in `integrity_baseline.json`; existing debt does not block. Severity ∈ `high|med|low`; domain ∈ `data|consistency|route`.
- Admin-only surfaces use the existing pattern: `@login_required` + `if not current_user.is_admin: abort(403)`.
- Tests run with `python3 -m pytest`. Fixtures available in `tests/conftest.py`: `app`, `client`, `db_session`, `agency`, `admin_user`, `agent_user`, `customer`.

---

### Task 1: Invariant registry core (`app/integrity.py`)

**Files:**
- Create: `app/integrity.py`
- Test: `tests/test_integrity_registry.py`

**Interfaces:**
- Produces:
  - `@dataclass Violation` with fields `key: str`, `severity: str`, `domain: str`, `count: int`, `description: str`, `sample: list` (default empty list).
  - `invariant(key, *, severity, domain, description)` — decorator registering a zero-arg function that returns `(count: int, sample: list)`; the decorator wraps it so calling produces a full `Violation`.
  - `run_all() -> list[Violation]` — calls every registered invariant, returns Violations sorted by (domain, severity rank high>med>low, key).
  - `REGISTRY: dict[str, callable]` — key → wrapped function (for tests).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_integrity_registry.py
def test_registry_registers_and_runs():
    from app.integrity import invariant, run_all, REGISTRY, Violation

    @invariant("test_dummy", severity="high", domain="data",
               description="dummy for testing")
    def _dummy():
        return 3, [{"id": 1}, {"id": 2}, {"id": 3}]

    assert "test_dummy" in REGISTRY
    results = run_all()
    v = next(r for r in results if r.key == "test_dummy")
    assert isinstance(v, Violation)
    assert v.count == 3
    assert v.severity == "high"
    assert v.domain == "data"
    assert len(v.sample) == 3
    # cleanup so the dummy doesn't leak into other tests
    REGISTRY.pop("test_dummy", None)


def test_run_all_sorts_high_severity_first():
    from app.integrity import invariant, run_all, REGISTRY

    @invariant("z_low", severity="low", domain="data", description="x")
    def _a(): return 0, []

    @invariant("a_high", severity="high", domain="data", description="x")
    def _b(): return 0, []

    results = [r for r in run_all() if r.key in ("z_low", "a_high")]
    assert results[0].key == "a_high"   # high before low despite name order
    REGISTRY.pop("z_low", None); REGISTRY.pop("a_high", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_integrity_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.integrity'`

- [ ] **Step 3: Write the registry**

```python
# app/integrity.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_integrity_registry.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/integrity.py tests/test_integrity_registry.py
git commit -m "feat: data-integrity invariant registry core (Violation + @invariant + run_all)"
```

---

### Task 2: Data-domain invariants (lifecycle + multi-AOR aware)

**Files:**
- Modify: `app/integrity.py` (add invariant functions + a small helpers section)
- Test: `tests/test_integrity_data_invariants.py`

**Interfaces:**
- Consumes: `invariant`, `Violation`, `REGISTRY` from Task 1.
- Produces (registered invariant keys, each a zero-arg fn returning `(count, sample)`):
  - `plan_id_orphans` (high) — active, non-stub Policy with `plan_id IS NULL`.
  - `no_name_policies` (high) — active Policy with blank first AND last name.
  - `payment_without_customer` (high) — CommissionLineItem with `customer_id IS NULL` (the money-fact→customer link lives on CommissionLineItem.customer_id per app/identity.py, NOT on PolicyPayment which has no customer_id).
  - `backwards_date_interval` (high) — CustomerAorHistory with `effective_date > end_date` (both non-null).
  - `duplicate_customers` (high) — clusters of >1 non-stub Customer sharing normalized (name, dob); multi-AOR persons are ONE customer so this is name+dob based, not policy-based.
  - `orphan_stub_customers` (med) — `stub=True` Customer that is NOT a manual lead (lifecycle-aware exemption).
- Helper: `_norm_name(full_name) -> str` (lowercased, punctuation/suffix-stripped, token-sorted) used by `duplicate_customers`.

These read existing models. Use a module-scoped agency resolution: invariants run agency-wide for ALL agencies (the radar is global), grouping/filtering by `agency_id` where the count is per-agency-meaningful; for v1 they count across all agencies (single-tenant in practice — agency_id=1).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_integrity_data_invariants.py
from datetime import date
from app.extensions import db
from app.models import (Agency, User, Customer, Policy, CommissionLineItem,
                        CommissionStatement, CustomerAorHistory, Plan)


def _agency(name="T"):
    a = Agency(name=name); db.session.add(a); db.session.flush(); return a


def test_plan_id_orphans_counts_null_active_nonstub(app):
    from app.integrity import REGISTRY
    with app.app_context():
        a = _agency()
        db.session.add(Policy(agency_id=a.id, carrier="Humana", member_id="M1",
                              status="active", plan_id=None))            # orphan
        pl = Plan(agency_id=a.id, carrier="Humana", cms_plan_id="H1-1", year=2026,
                  plan_name="X")
        db.session.add(pl); db.session.flush()
        db.session.add(Policy(agency_id=a.id, carrier="Humana", member_id="M2",
                              status="active", plan_id=pl.id))           # linked
        db.session.add(Policy(agency_id=a.id, carrier="UHC", member_id="uhc::0::5",
                              status="active", plan_id=None))            # stub, excluded
        db.session.commit()
        v = REGISTRY["plan_id_orphans"]()
        assert v.count == 1


def test_no_name_policies_counts_blank_names(app):
    from app.integrity import REGISTRY
    with app.app_context():
        a = _agency()
        db.session.add(Policy(agency_id=a.id, carrier="UHC", member_id="N1",
                              status="active", first_name="", last_name=""))   # no name
        db.session.add(Policy(agency_id=a.id, carrier="UHC", member_id="N2",
                              status="active", first_name="Jane", last_name="Doe"))
        db.session.commit()
        assert REGISTRY["no_name_policies"]().count == 1


def test_payment_without_customer(app):
    from app.integrity import REGISTRY
    with app.app_context():
        a = _agency()
        st = CommissionStatement(agency_id=a.id, carrier="UHC", period_label="March 2026",
                                 statement_date=date(2026, 3, 1))
        db.session.add(st); db.session.flush()
        # money fact with NO customer link -> counts
        db.session.add(CommissionLineItem(agency_id=a.id, statement_id=st.id,
            carrier="UHC", source_ref="uhc::x::1", raw_amount=10.0,
            classification="agent_commission", customer_id=None))
        # money fact WITH a customer -> does not count
        c = Customer(agency_id=a.id, full_name="Has Cust"); db.session.add(c); db.session.flush()
        db.session.add(CommissionLineItem(agency_id=a.id, statement_id=st.id,
            carrier="UHC", source_ref="uhc::x::2", raw_amount=10.0,
            classification="agent_commission", customer_id=c.id))
        db.session.commit()
        assert REGISTRY["payment_without_customer"]().count == 1


def test_backwards_date_interval(app):
    from app.integrity import REGISTRY
    with app.app_context():
        a = _agency()
        u = User(name="A", email="a@x.com", agency_id=a.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=a.id, full_name="X Y", primary_agent_id=u.id)
        db.session.add(c); db.session.flush()
        db.session.add(CustomerAorHistory(agency_id=a.id, customer_id=c.id, agent_id=u.id,
            carrier="Aetna", effective_date=date(2026,1,1), end_date=date(2025,12,31)))  # backwards
        db.session.add(CustomerAorHistory(agency_id=a.id, customer_id=c.id, agent_id=u.id,
            carrier="UHC", effective_date=date(2024,1,1), end_date=date(2025,1,1)))      # fine
        db.session.commit()
        assert REGISTRY["backwards_date_interval"]().count == 1


def test_duplicate_customers_groups_by_name_dob_not_multi_aor(app):
    from app.integrity import REGISTRY
    with app.app_context():
        a = _agency()
        u = User(name="Ag", email="ag@x.com", agency_id=a.id); db.session.add(u); db.session.flush()
        # John Connelly x3 (same person, same dob) -> 2 excess
        for fn in ["CONNELLY, JOHN", "John Connelly", "John Connelly Iii"]:
            db.session.add(Customer(agency_id=a.id, full_name=fn, dob=date(1953,4,7),
                                    primary_agent_id=u.id))
        # A multi-AOR person: ONE customer with two policies/AORs -> must NOT be a dup
        m = Customer(agency_id=a.id, full_name="Multi Aor", dob=date(1950,1,1),
                     primary_agent_id=u.id)
        db.session.add(m); db.session.commit()
        v = REGISTRY["duplicate_customers"]()
        assert v.count == 2          # the 2 excess Connelly rows; Multi Aor not counted


def test_orphan_stub_customers_exempts_manual_lead(app):
    from app.integrity import REGISTRY
    with app.app_context():
        a = _agency()
        # a garbage stub from import (counts)
        db.session.add(Customer(agency_id=a.id, full_name="STUB ONE", stub=True,
                                source="commission_import"))
        # a manual lead with no MBI (does NOT count — legitimate)
        db.session.add(Customer(agency_id=a.id, full_name="Real Lead", stub=False,
                                source="manual", deal_stage="Lead", mbi=None))
        db.session.commit()
        v = REGISTRY["orphan_stub_customers"]()
        assert v.count == 1          # only the import stub
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_integrity_data_invariants.py -v`
Expected: FAIL — `KeyError: 'plan_id_orphans'` (invariants not registered yet).

- [ ] **Step 3: Implement the data invariants**

Append to `app/integrity.py`:

```python
import re
from sqlalchemy import func
from app.extensions import db
from app.models import Policy, Customer, CommissionLineItem, CustomerAorHistory

_STUB_LIKE = "%::0::%"
_CUSTOMER_STAGES = ("Active", "Termed")   # held to customer-grade invariants


def _sample(rows, n=10):
    return rows[:n]


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
    rows = Customer.query.with_entities(
        Customer.id, Customer.full_name, Customer.dob).all()
    from collections import defaultdict
    clusters = defaultdict(list)
    for cid, name, dob in rows:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_integrity_data_invariants.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/integrity.py tests/test_integrity_data_invariants.py
git commit -m "feat: data-domain integrity invariants (lifecycle + multi-AOR aware)"
```

---

### Task 3: Consistency-domain invariants (absorb the metrics guard)

**Files:**
- Modify: `app/integrity.py`
- Test: `tests/test_integrity_consistency.py`

**Interfaces:**
- Consumes: `invariant` (Task 1); `app/metrics.py` (`Scope`, `book_breakdown`).
- Produces:
  - `count_only_via_metrics` (high) — static scan: no raw `Policy...count()` / split-rate in the scanned route files (absorbs `tests/test_metrics_guard.py`'s logic, ADDING `app/customers.py` to the scanned set, honoring the existing allowlist). Returns count of offending lines + their text as sample.
  - `carrier_counts_agree` (high) — for each carrier in the (agency_id=1) book, the policy count from `metrics.book_breakdown` is internally self-consistent (sum of per-carrier counts == total). (Registered now; the cross-page rendering equality is item 5's deeper assertion — here it guards the metrics layer's own coherence.)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_integrity_consistency.py
def test_count_only_via_metrics_scans_customers_py(app):
    from app.integrity import REGISTRY
    # The invariant must include app/customers.py in its scanned set.
    v = REGISTRY["count_only_via_metrics"]()
    assert v.domain == "consistency"
    assert isinstance(v.count, int)   # 0 if clean (after item 5) or N offending lines now


def test_carrier_counts_agree_self_consistent(app, agency, db_session):
    from app.integrity import REGISTRY
    from app.extensions import db
    from app.models import Policy
    with app.app_context():
        db.session.add(Policy(agency_id=agency.id, carrier="UHC", member_id="C1",
                              status="active"))
        db.session.add(Policy(agency_id=agency.id, carrier="Humana", member_id="C2",
                              status="active"))
        db.session.commit()
        v = REGISTRY["carrier_counts_agree"]()
        assert v.count == 0   # per-carrier sums equal the total -> no violation
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_integrity_consistency.py -v`
Expected: FAIL — `KeyError: 'count_only_via_metrics'`.

- [ ] **Step 3: Implement the consistency invariants**

Append to `app/integrity.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_integrity_consistency.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/integrity.py tests/test_integrity_consistency.py
git commit -m "feat: consistency integrity invariants (absorb metrics guard, scan customers.py)"
```

---

### Task 4: Route-domain invariants (links resolve, no orphan routes)

**Files:**
- Modify: `app/integrity.py`
- Test: `tests/test_integrity_routes.py`

**Interfaces:**
- Consumes: `invariant` (Task 1); Flask `current_app.url_map`.
- Produces:
  - `links_resolve` (med) — every `url_for('endpoint')` call referenced in templates points to an endpoint that exists in `current_app.url_map`. Scans `app/templates/**/*.html` for `url_for('...')` first-arg endpoint names; flags any not in the url_map.
  - `no_orphan_routes` (low) — every GET view endpoint (excluding webhooks/api/static/auth) appears as a `url_for(...)` target in some template OR is in an allowlist of intentionally-unlinked endpoints. Flags the rest.

These need an app context (`current_app`). Tests use the real app's url_map.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_integrity_routes.py
def test_links_resolve_runs_and_is_int(app):
    from app.integrity import REGISTRY
    with app.app_context():
        v = REGISTRY["links_resolve"]()
        assert v.domain == "route"
        assert isinstance(v.count, int)   # 0 if all template url_for targets exist


def test_links_resolve_flags_bogus_endpoint(app, tmp_path, monkeypatch):
    from app.integrity import REGISTRY, _template_endpoints
    # _template_endpoints returns the set of url_for endpoint names found in templates;
    # feed it a fake template dir containing a bogus endpoint.
    d = tmp_path / "templates"; d.mkdir()
    (d / "x.html").write_text("{{ url_for('does.not_exist') }}")
    eps = _template_endpoints(str(d))
    assert "does.not_exist" in eps
    with app.app_context():
        assert "does.not_exist" not in {r.endpoint for r in app.url_map.iter_rules()}


def test_no_orphan_routes_runs(app):
    from app.integrity import REGISTRY
    with app.app_context():
        v = REGISTRY["no_orphan_routes"]()
        assert v.domain == "route"
        assert isinstance(v.count, int)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_integrity_routes.py -v`
Expected: FAIL — `ImportError: cannot import name '_template_endpoints'` / `KeyError`.

- [ ] **Step 3: Implement the route invariants**

Append to `app/integrity.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_integrity_routes.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/integrity.py tests/test_integrity_routes.py
git commit -m "feat: route-domain integrity invariants (links resolve, no orphan routes)"
```

---

### Task 5: The ratchet — baseline file + CI guard test

**Files:**
- Create: `integrity_baseline.json`
- Create: `tests/test_integrity_guards.py`
- Delete: `tests/test_metrics_guard.py` (absorbed by `count_only_via_metrics` in Task 3)
- Modify: `app/integrity.py` (add `load_baseline()` / baseline path constant)

**Interfaces:**
- Consumes: `run_all()` (Task 1), all registered invariants (Tasks 2-4).
- Produces:
  - `BASELINE_PATH` constant in `app/integrity.py`; `load_baseline() -> dict[str,int]`.
  - `integrity_baseline.json` — `{invariant_key: baseline_count}` for every registered key, frozen at current live levels (the implementer fills real numbers by running `run_all()` against the test DB = 0 for an empty fixture DB; the LIVE baseline is set during Task 8 deploy, see note).
  - `tests/test_integrity_guards.py::test_no_invariant_exceeds_baseline` — fails if any live count > its baseline.

**Note on baseline values:** the test runs against the empty test DB where all counts are 0, so the committed `integrity_baseline.json` starts at 0 for every key (nothing exceeds 0 in tests). The REAL production debt levels (plan_id_orphans=4611 etc.) are recorded by running `scripts/audit_integrity.py --update-baseline` ON THE VPS during deploy (Task 8); that VPS baseline is committed back so CI reflects real debt. This keeps the test green locally (0≤0) AND meaningful in production.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_integrity_guards.py
import json, pathlib


def test_baseline_covers_every_registered_invariant(app):
    from app.integrity import REGISTRY, load_baseline
    baseline = load_baseline()
    missing = [k for k in REGISTRY if k not in baseline]
    assert not missing, f"invariants missing a baseline entry: {missing}"


def test_no_invariant_exceeds_baseline(app):
    from app.integrity import run_all, load_baseline
    baseline = load_baseline()
    with app.app_context():
        offenders = []
        for v in run_all():
            limit = baseline.get(v.key, 0)
            if v.count > limit:
                offenders.append(f"{v.key}: {v.count} > baseline {limit}")
    assert not offenders, (
        "Data-integrity REGRESSION — a count rose above its frozen baseline:\n"
        + "\n".join(offenders)
        + "\n(Fix the regression, or if intentional run "
          "scripts/audit_integrity.py --update-baseline.)")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_integrity_guards.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_baseline'` and missing `integrity_baseline.json`.

- [ ] **Step 3: Implement baseline loader + create the baseline file**

Append to `app/integrity.py`:

```python
import json

BASELINE_PATH = _ROOT / "integrity_baseline.json"


def load_baseline():
    """Frozen per-invariant debt levels. Missing file or key => 0 (strictest)."""
    try:
        return json.loads(BASELINE_PATH.read_text())
    except FileNotFoundError:
        return {}
```

Create `integrity_baseline.json` with every registered key at 0 (local/test starts
clean; production debt is set on the VPS in Task 8):

```json
{
  "plan_id_orphans": 0,
  "no_name_policies": 0,
  "payment_without_customer": 0,
  "backwards_date_interval": 0,
  "duplicate_customers": 0,
  "orphan_stub_customers": 0,
  "count_only_via_metrics": 0,
  "carrier_counts_agree": 0,
  "links_resolve": 0,
  "no_orphan_routes": 0
}
```

- [ ] **Step 4: Delete the absorbed metrics guard**

```bash
git rm tests/test_metrics_guard.py
```

(Its logic now lives in the `count_only_via_metrics` invariant + this ratchet.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_integrity_guards.py -v`
Expected: PASS (2 tests) — empty test DB, all counts 0 ≤ baseline 0.

- [ ] **Step 6: Commit**

```bash
git add app/integrity.py integrity_baseline.json tests/test_integrity_guards.py
git commit -m "feat: integrity baseline ratchet guard (absorb + remove test_metrics_guard)"
```

---

### Task 6: CLI report (`scripts/audit_integrity.py`)

**Files:**
- Create: `scripts/audit_integrity.py`
- Test: `tests/test_audit_integrity_cli.py`

**Interfaces:**
- Consumes: `run_all()`, `load_baseline()`, `BASELINE_PATH` (Tasks 1, 5).
- Produces: a runnable script:
  - default: print a table (key, domain, severity, count, baseline, Δ) + samples for non-zero; exit 1 if any count > baseline, else 0.
  - `--json`: print `[{key, domain, severity, count, baseline}, ...]`.
  - `--update-baseline`: write current live counts to `integrity_baseline.json` and exit 0.
  - A `build_report()` function (importable, returns the list of dicts) so the test doesn't shell out.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audit_integrity_cli.py
def test_build_report_shape(app):
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
    import audit_integrity
    with app.app_context():
        report = audit_integrity.build_report()
    assert isinstance(report, list) and report
    row = report[0]
    for field in ("key", "domain", "severity", "count", "baseline", "delta"):
        assert field in row
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_audit_integrity_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audit_integrity'`.

- [ ] **Step 3: Write the CLI**

```python
# scripts/audit_integrity.py
"""Data-Integrity Radar CLI. Read-only.
  ./venv/bin/python3 scripts/audit_integrity.py             # table + exit 1 if regressed
  ./venv/bin/python3 scripts/audit_integrity.py --json
  ./venv/bin/python3 scripts/audit_integrity.py --update-baseline   # re-freeze
On VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/audit_integrity.py
"""
import sys, json
from app import create_app
from app.integrity import run_all, load_baseline, BASELINE_PATH


def build_report():
    baseline = load_baseline()
    out = []
    for v in run_all():
        base = baseline.get(v.key, 0)
        out.append({"key": v.key, "domain": v.domain, "severity": v.severity,
                    "count": v.count, "baseline": base, "delta": v.count - base,
                    "description": v.description, "sample": v.sample})
    return out


def main(argv):
    app = create_app()
    with app.app_context():
        if "--update-baseline" in argv:
            new = {v.key: v.count for v in run_all()}
            BASELINE_PATH.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n")
            print(f"baseline updated: {new}")
            return 0
        report = build_report()
        if "--json" in argv:
            print(json.dumps([{k: r[k] for k in
                  ("key", "domain", "severity", "count", "baseline")} for r in report]))
            return 0
        regressed = False
        print(f"{'KEY':28} {'DOMAIN':12} {'SEV':5} {'COUNT':>7} {'BASE':>7} {'Δ':>6}")
        for r in report:
            flag = "  <== REGRESSION" if r["delta"] > 0 else ""
            if r["delta"] > 0:
                regressed = True
            print(f"{r['key']:28} {r['domain']:12} {r['severity']:5} "
                  f"{r['count']:7} {r['baseline']:7} {r['delta']:6}{flag}")
        return 1 if regressed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_audit_integrity_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_integrity.py tests/test_audit_integrity_cli.py
git commit -m "feat: audit_integrity CLI (table / --json / --update-baseline)"
```

---

### Task 7: `/admin/integrity` dashboard page

**Files:**
- Modify: `app/routes.py` (add the route)
- Create: `app/templates/admin_integrity.html`
- Modify: `app/templates/base.html` (admin nav link)
- Test: `tests/test_integrity_dashboard.py`

**Interfaces:**
- Consumes: `run_all()`, `load_baseline()` (Tasks 1, 5).
- Produces: route `main.admin_integrity` at `/admin/integrity` (admin-only), rendering the violations grouped by domain with count vs baseline + samples.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_integrity_dashboard.py
def test_integrity_page_admin_only(client, app, agency, db_session):
    from app.extensions import db
    from app.models import User
    with app.app_context():
        admin = User(email="iadmin@t.com", name="IAdmin", is_admin=True, agency_id=agency.id)
        agent = User(email="iagent@t.com", name="IAgent", is_admin=False, agency_id=agency.id)
        db.session.add_all([admin, agent]); db.session.commit()
        aid, gid = admin.id, agent.id
    # anonymous -> redirect to login
    assert client.get("/admin/integrity").status_code in (302, 401)
    # agent -> 403
    with client.session_transaction() as s: s["_user_id"] = str(gid)
    assert client.get("/admin/integrity").status_code == 403
    # admin -> 200, shows a known invariant key
    with client.session_transaction() as s: s["_user_id"] = str(aid)
    r = client.get("/admin/integrity")
    assert r.status_code == 200
    assert b"plan_id_orphans" in r.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_integrity_dashboard.py -v`
Expected: FAIL — 404 (route doesn't exist).

- [ ] **Step 3: Add the route**

In `app/routes.py`, after the `admin_overview` route, add (ensure `run_all, load_baseline` are imported from `app.integrity` at the top):

```python
@main.route('/admin/integrity')
@login_required
def admin_integrity():
    if not current_user.is_admin:
        abort(403)
    from app.integrity import run_all, load_baseline
    baseline = load_baseline()
    violations = run_all()
    rows = []
    for v in violations:
        base = baseline.get(v.key, 0)
        rows.append({"key": v.key, "domain": v.domain, "severity": v.severity,
                     "count": v.count, "baseline": base, "delta": v.count - base,
                     "description": v.description, "sample": v.sample})
    by_domain = {}
    for r in rows:
        by_domain.setdefault(r["domain"], []).append(r)
    return render_template("admin_integrity.html", by_domain=by_domain,
                           total=sum(r["count"] for r in rows))
```

- [ ] **Step 4: Create the template**

Create `app/templates/admin_integrity.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="page-header"><h1>Data Integrity</h1>
  <p class="text-muted">{{ total }} total violations across {{ by_domain|length }} domains.
     Counts above their baseline are regressions (red).</p></div>

{% for domain, rows in by_domain.items() %}
<div class="card">
  <div class="card-header"><span class="card-title">{{ domain|capitalize }}</span></div>
  <div class="card-body">
    <table class="data-table">
      <thead><tr><th>Invariant</th><th>Sev</th><th>Count</th><th>Baseline</th>
                 <th>Δ</th><th>Description</th></tr></thead>
      <tbody>
      {% for r in rows %}
        <tr>
          <td class="fw-medium">{{ r.key }}</td>
          <td><span class="badge badge-{{ 'red' if r.severity=='high' else 'amber' if r.severity=='med' else 'gray' }}">{{ r.severity }}</span></td>
          <td>{{ r.count }}</td>
          <td class="text-muted">{{ r.baseline }}</td>
          <td style="color:{{ 'var(--green)' if r.delta<=0 else '#C0392B' }};font-weight:700">
            {{ '+' if r.delta>0 else '' }}{{ r.delta }}</td>
          <td class="text-muted" style="font-size:12px">{{ r.description }}
            {% if r.sample %}<br><span style="font-size:11px">
              e.g. {{ r.sample[:3]|map(attribute='label')|join('; ') }}</span>{% endif %}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endfor %}
{% endblock %}
```

- [ ] **Step 5: Add the admin nav link**

In `app/templates/base.html`, in the admin-only nav section (near the "Audit Log" link), add:

```html
{% if current_user.is_admin %}
  <a class="nav-item {{ 'active' if request.endpoint=='main.admin_integrity' }}"
     href="{{ url_for('main.admin_integrity') }}">Data Integrity</a>
{% endif %}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python3 -m pytest tests/test_integrity_dashboard.py -v`
Expected: PASS (admin 200 + key present; agent 403; anon redirect)

- [ ] **Step 7: Commit**

```bash
git add app/routes.py app/templates/admin_integrity.html app/templates/base.html tests/test_integrity_dashboard.py
git commit -m "feat: /admin/integrity dashboard (read-only radar, admin-only) + nav link"
```

---

### Task 8: Full suite, whole-branch review, deploy + freeze production baseline

**Files:** none (verification + deploy task)

- [ ] **Step 1: Run the entire suite**

Run: `python3 -m pytest -q`
Expected: all pass (the new tests + existing suite; `test_metrics_guard.py` removed, its coverage now in `count_only_via_metrics`).

- [ ] **Step 2: Whole-branch opus review**

Per the project protocol (opus whole-branch review on data paths), use `superpowers:requesting-code-review` on the full branch. Focus: no invariant mutates data; lifecycle/multi-AOR exemptions are correct (a manual lead and a multi-AOR person are NOT flagged); the ratchet logic (count>baseline fails) is right; the route invariant doesn't false-flag parameterized/webhook routes.

- [ ] **Step 3: Address findings, re-run suite**

Run: `python3 -m pytest -q`
Expected: all pass after fixes.

- [ ] **Step 4: Deploy + freeze the REAL production baseline**

Merge to main, deploy to VPS (git pull + restart; no migration). Then ON THE VPS record real debt levels and commit them back:

```bash
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100
cd /var/www/founders-portal && git pull
PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/audit_integrity.py
# review the real counts (plan_id_orphans ~4611, duplicate_customers ~152, etc.), then:
PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/audit_integrity.py --update-baseline
```

Copy the produced `integrity_baseline.json` back to the repo (scp or paste), commit it,
push, redeploy. Now CI/`test_integrity_guards.py` reflects real debt: nothing may exceed
it, and each remediation item (1-5) drops a baseline toward 0.

- [ ] **Step 5: Verify on VPS**

- `/admin/integrity` renders for admin, 403 for agent.
- `scripts/audit_integrity.py` exit code 0 right after `--update-baseline` (nothing exceeds the just-frozen baseline).
- Spot-check counts match the hand audit (plan_id_orphans ≈ 4611, duplicate_customers ≈ 152).

- [ ] **Step 6: Update docs**

Mark the radar spec Status → shipped; update the roadmap (item 0 ✅, baseline frozen); reconcile `BACKLOG.md`; update CLAUDE.md START HERE + a session-handoff memory. Commit.
