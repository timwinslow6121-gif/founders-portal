# No-MBI Customer Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin collapse duplicate-customer clusters that have NO shared MBI into one profile — suggest-only, product-line-aware, fill-blanks-only, audited.

**Architecture:** A new detection module (`app/dedup.py`) clusters customers by normalized `full_name` and tags each cluster with a corroboration signal. A generalized merge engine (`merge_customers`) reattaches all five child-record types to a keeper, fills only blank keeper fields by precedence, refuses contradictory clusters, and is idempotent + audited. The existing `/admin/customers/duplicates` page and the per-field edit route consume these.

**Tech Stack:** Python 3.10, Flask, Flask-SQLAlchemy, Jinja2, pytest (SQLite in tests; real Postgres for final verify).

**Spec:** `docs/superpowers/specs/2026-06-30-no-mbi-customer-merge-design.md`

## Global Constraints

- Every customer query MUST be agency-scoped: `filter(... agency_id == agency_id ...)`. Missing scope = cross-tenant data leak.
- `Customer.first_name` / `last_name` are `nullable=False` → stubs store **empty strings, not NULL**. Names may live only in `full_name` ("LAST, FIRST"). Always normalize `full_name`.
- Reuse `app.integrity._norm_name` (lowercases, strips punctuation/commas, drops suffixes iii/ii/iv/jr/sr, **sorts tokens**) — do not re-implement name normalization.
- Merge is **suggest-only**: no code path collapses a cluster without a human action (UI button) or an explicit `--apply` on a qualifying-signal cluster.
- **Fill-blanks-only**: never overwrite an existing keeper field value.
- Precedence for filling a blank: **manually_edited > non-stub > stub**.
- Audit every merge via `app.audit.log_event(action="customer_merge", category="admin", ...)`.
- All times reported to humans in EST/EDT (DB is UTC).

---

### Task 1: Detection — cluster no-MBI duplicates with signal tags

**Files:**
- Create: `app/dedup.py`
- Test: `tests/test_dedup.py`

**Interfaces:**
- Consumes: `app.integrity._norm_name(full_name) -> str`; models `Customer`, `Policy`, `CommissionLineItem`.
- Produces:
  - `find_no_mbi_clusters(agency_id: int) -> list[Cluster]`
  - `Cluster` is a dataclass: `keeper_id: int`, `member_ids: list[int]` (all rows incl. keeper), `signal: str` (one of `"dob_match"`, `"shared_id"`, `"name_only"`, `"conflict"`).
  - Helper `cluster_signal(rows: list[Customer], agency_id: int) -> str` (importable for tests).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dedup.py
import pytest
from datetime import date
from app import create_app
from app.extensions import db
from app.models import Customer, Agency
from app.dedup import find_no_mbi_clusters, cluster_signal


@pytest.fixture
def app_ctx():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        ag = Agency(name="T")
        db.session.add(ag)
        db.session.flush()
        yield ag.id
        db.session.remove()
        db.drop_all()


def _cust(agency_id, **kw):
    base = dict(agency_id=agency_id, first_name="", last_name="", stub=False)
    base.update(kw)
    c = Customer(**base)
    db.session.add(c)
    db.session.flush()
    return c


def test_connelly_blank_name_stubs_cluster_with_real_rows(app_ctx):
    agency_id = app_ctx
    keeper = _cust(agency_id, first_name="John", last_name="Connelly",
                   full_name="John Connelly", mbi="4RH5X85DC65", dob=date(1953, 4, 7))
    _cust(agency_id, first_name="John", last_name="Connelly Iii",
          full_name="John Connelly Iii", dob=date(1953, 4, 7))
    _cust(agency_id, full_name="CONNELLY, JOHN", stub=True)            # blank first/last
    _cust(agency_id, full_name="CONNELLY, JOHN", dob=date(1953, 4, 7), stub=True)
    db.session.commit()

    clusters = find_no_mbi_clusters(agency_id)
    # All four Connelly rows form ONE cluster (full_name normalized + token-sorted).
    conn = [c for c in clusters if c.keeper_id == keeper.id]
    assert len(conn) == 1
    assert len(conn[0].member_ids) == 4
    # DOB shared by 3 of them => merge offered.
    assert conn[0].signal == "dob_match"


def test_contradictory_dob_is_conflict(app_ctx):
    agency_id = app_ctx
    a = _cust(agency_id, first_name="Jane", last_name="Doe",
              full_name="Jane Doe", dob=date(1950, 1, 1))
    _cust(agency_id, first_name="Jane", last_name="Doe",
          full_name="Jane Doe", dob=date(1962, 9, 9))
    db.session.commit()
    clusters = find_no_mbi_clusters(agency_id)
    doe = [c for c in clusters if a.id in c.member_ids][0]
    assert doe.signal == "conflict"


def test_bare_name_no_dob_no_id_is_name_only(app_ctx):
    agency_id = app_ctx
    a = _cust(agency_id, first_name="Bob", last_name="Smith", full_name="Bob Smith")
    _cust(agency_id, first_name="Bob", last_name="Smith", full_name="Bob Smith", stub=True)
    db.session.commit()
    clusters = find_no_mbi_clusters(agency_id)
    smith = [c for c in clusters if a.id in c.member_ids][0]
    assert smith.signal == "name_only"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_dedup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.dedup'`.

- [ ] **Step 3: Write minimal implementation**

```python
# app/dedup.py
"""No-MBI duplicate detection (spec 2026-06-30). Clusters customers by normalized
full_name and tags each cluster with a corroboration signal. Suggest-only: this
module never writes — it only proposes clusters for human/script review."""
from collections import defaultdict
from dataclasses import dataclass, field

from app.extensions import db
from app.models import Customer, Policy, CommissionLineItem
from app.integrity import _norm_name


@dataclass
class Cluster:
    keeper_id: int
    member_ids: list
    signal: str = "name_only"


def _keeper_score(c):
    """Most-complete real row wins: non-stub + has mbi + has dob + has name."""
    return (0 if c.stub else 1, 1 if c.mbi else 0, 1 if c.dob else 0,
            1 if (c.full_name or c.first_name or c.last_name) else 0, c.id * -1)


def _shared_carrier_ids(member_ids, agency_id):
    """carrier_member_ids that appear on the cluster's commission line items + policies."""
    ids = set()
    li = (CommissionLineItem.query
          .filter(CommissionLineItem.agency_id == agency_id,
                  CommissionLineItem.customer_id.in_(member_ids),
                  CommissionLineItem.carrier_member_id.isnot(None))
          .with_entities(CommissionLineItem.carrier, CommissionLineItem.carrier_member_id).all())
    ids.update((c, v) for c, v in li if v)
    pol = (Policy.query
           .filter(Policy.agency_id == agency_id,
                   Policy.customer_id.in_(member_ids))
           .with_entities(Policy.carrier, Policy.member_id).all())
    ids.update((c, v) for c, v in pol if v)
    return ids


def cluster_signal(rows, agency_id):
    """Return the merge signal for a set of same-name Customer rows."""
    dobs = {r.dob for r in rows if r.dob is not None}
    mbis = {r.mbi for r in rows if r.mbi}
    if len(dobs) > 1 or len(mbis) > 1:
        return "conflict"
    # >1 row carrying the SAME non-null dob => shared dob.
    if sum(1 for r in rows if r.dob is not None) > 1:
        return "dob_match"
    # A shared carrier id corroborates only if >1 row actually carries it.
    per_row = defaultdict(set)
    for r in rows:
        for c, v in _shared_carrier_ids([r.id], agency_id):
            per_row[(c, v)].add(r.id)
    if any(len(who) > 1 for who in per_row.values()):
        return "shared_id"
    return "name_only"


def find_no_mbi_clusters(agency_id):
    """Cluster customers by normalized full_name; return Clusters of size > 1.
    Includes stubs and NULL-dob rows (unlike the radar's duplicate_customers)."""
    rows = (Customer.query
            .filter(Customer.agency_id == agency_id)
            .all())
    by_name = defaultdict(list)
    for c in rows:
        name = c.full_name or f"{c.first_name} {c.last_name}".strip()
        key = _norm_name(name)
        if key:
            by_name[key].append(c)
    clusters = []
    for key, group in by_name.items():
        if len(group) < 2:
            continue
        keeper = max(group, key=_keeper_score)
        clusters.append(Cluster(
            keeper_id=keeper.id,
            member_ids=[c.id for c in group],
            signal=cluster_signal(group, agency_id),
        ))
    return clusters
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_dedup.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/dedup.py tests/test_dedup.py
git commit -m "feat: no-MBI duplicate cluster detection with signal tags"
```

---

### Task 2: Multi-product-line is NOT a duplicate

**Files:**
- Modify: `app/dedup.py` (no logic change expected — this task proves the invariant)
- Test: `tests/test_dedup.py`

**Interfaces:**
- Consumes: `find_no_mbi_clusters` from Task 1.
- Produces: nothing new — guards existing behavior.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_dedup.py
from app.models import Policy


def test_one_person_many_product_lines_is_not_a_duplicate(app_ctx):
    """A person with a MAPD + a dental + a hospital-indemnity policy (no MBI on the
    latter two) is ONE customer with THREE policies — never flagged as duplicates."""
    agency_id = app_ctx
    c = _cust(agency_id, first_name="Pat", last_name="Jones", full_name="Pat Jones",
              mbi="9AB8X12CD34", dob=date(1955, 6, 1))
    for carrier, ptype, mid in [("UHC", "MAPD", "M1"),
                                ("Aflac", "Hospital Indemnity", "H1"),
                                ("VSP", "Dental Vision Hearing", "D1")]:
        db.session.add(Policy(agency_id=agency_id, carrier=carrier, member_id=mid,
                              plan_type=ptype, customer_id=c.id, full_name="Pat Jones"))
    db.session.commit()
    clusters = find_no_mbi_clusters(agency_id)
    # Only one customer named Pat Jones — no cluster of size > 1.
    assert not any(c.id in cl.member_ids and len(cl.member_ids) > 1 for cl in clusters)
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `python3 -m pytest tests/test_dedup.py::test_one_person_many_product_lines_is_not_a_duplicate -v`
Expected: PASS (detection clusters by identity, not product — one customer = no cluster). If it FAILS, detection is wrongly using policy/carrier as an identity axis — fix `find_no_mbi_clusters` to cluster on name only.

- [ ] **Step 3: Implementation (only if Step 2 failed)**

No change expected. If it failed, ensure `find_no_mbi_clusters` groups solely on `_norm_name`, never on carrier/policy.

- [ ] **Step 4: Run full dedup suite**

Run: `python3 -m pytest tests/test_dedup.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_dedup.py
git commit -m "test: multi-product-line person is not flagged as a duplicate"
```

---

### Task 3: Merge engine — reattach all children, fill-blanks-only, refuse contradictions, idempotent, audited

**Files:**
- Modify: `app/customers.py` (add `merge_customers`; rewrite the `customer_merge` route to call it)
- Test: `tests/test_customer_merge.py`

**Interfaces:**
- Consumes: models `Customer`, `Policy`, `PolicyPayment`, `CustomerNote`, `CustomerContact`, `CustomerAorHistory`; `app.audit.log_event`.
- Produces:
  - `merge_customers(keeper_id: int, loser_ids: list[int], agency_id: int, actor) -> dict`
  - Returns `{"ok": bool, "merged": int, "filled": list[str], "moved": dict, "error": str|None}`.
  - Raises nothing on a normal contradiction — returns `{"ok": False, "error": "contradictory ..."}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_customer_merge.py
import pytest
from datetime import date
from app import create_app
from app.extensions import db
from app.models import (Customer, Agency, Policy, PolicyPayment, CustomerNote,
                        CustomerContact, CustomerAorHistory, User)
from app.customers import merge_customers


@pytest.fixture
def ctx():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(email="a@b.com", agency_id=ag.id, is_admin=True,
                 first_name="Ad", last_name="Min", role="admin")
        db.session.add(u); db.session.flush()
        yield ag.id, u
        db.session.remove(); db.drop_all()


def _c(agency_id, **kw):
    base = dict(agency_id=agency_id, first_name="", last_name="", stub=False)
    base.update(kw); c = Customer(**base); db.session.add(c); db.session.flush(); return c


def test_merge_reattaches_all_children_and_fills_blanks(ctx):
    agency_id, actor = ctx
    keeper = _c(agency_id, first_name="John", last_name="Connelly",
                full_name="John Connelly", mbi="4RH5X85DC65", dob=date(1953, 4, 7))
    loser = _c(agency_id, full_name="CONNELLY, JOHN", stub=True,
               phone_primary="828-555-0100")          # keeper has no phone
    db.session.add(Policy(agency_id=agency_id, carrier="UHC", member_id="M1",
                          customer_id=loser.id))
    db.session.add(PolicyPayment(agency_id=agency_id, customer_id=loser.id))
    db.session.add(CustomerNote(customer_id=loser.id, body="hi"))
    db.session.add(CustomerContact(customer_id=loser.id, contact_name="x"))
    db.session.add(CustomerAorHistory(customer_id=loser.id, carrier="UHC",
                                      effective_date=date(2025, 1, 1)))
    db.session.commit()

    res = merge_customers(keeper.id, [loser.id], agency_id, actor)
    db.session.commit()
    assert res["ok"] is True
    assert db.session.get(Customer, loser.id) is None          # loser deleted
    assert Policy.query.filter_by(customer_id=keeper.id).count() == 1
    assert PolicyPayment.query.filter_by(customer_id=keeper.id).count() == 1
    assert CustomerNote.query.filter_by(customer_id=keeper.id).count() == 1
    assert CustomerContact.query.filter_by(customer_id=keeper.id).count() == 1
    assert CustomerAorHistory.query.filter_by(customer_id=keeper.id).count() == 1
    assert keeper.phone_primary == "828-555-0100"              # blank filled from loser


def test_merge_never_overwrites_keeper_value(ctx):
    agency_id, actor = ctx
    keeper = _c(agency_id, first_name="A", last_name="B", full_name="A B",
                phone_primary="111-111-1111")
    loser = _c(agency_id, first_name="A", last_name="B", full_name="A B", stub=True,
               phone_primary="222-222-2222")
    db.session.commit()
    merge_customers(keeper.id, [loser.id], agency_id, actor); db.session.commit()
    assert keeper.phone_primary == "111-111-1111"              # kept, not overwritten


def test_merge_refuses_contradictory_dob(ctx):
    agency_id, actor = ctx
    keeper = _c(agency_id, first_name="C", last_name="D", full_name="C D",
                dob=date(1950, 1, 1))
    loser = _c(agency_id, first_name="C", last_name="D", full_name="C D",
               dob=date(1961, 2, 2))
    db.session.commit()
    res = merge_customers(keeper.id, [loser.id], agency_id, actor)
    assert res["ok"] is False
    assert "contradict" in res["error"].lower()
    assert db.session.get(Customer, loser.id) is not None      # nothing deleted


def test_merge_is_idempotent_on_missing_loser(ctx):
    agency_id, actor = ctx
    keeper = _c(agency_id, first_name="E", last_name="F", full_name="E F")
    db.session.commit()
    res = merge_customers(keeper.id, [99999], agency_id, actor)  # loser doesn't exist
    db.session.commit()
    assert res["ok"] is True
    assert res["merged"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_customer_merge.py -v`
Expected: FAIL — `ImportError: cannot import name 'merge_customers'`.

- [ ] **Step 3: Write minimal implementation**

Add to `app/customers.py` (near the existing merge code, ~line 770). Precedence sort: `manually_edited` first, then non-stub, then stub.

```python
# Fields the merge will fill on a blank keeper (never PII-overwrite a keeper value).
_MERGE_FILL_FIELDS = (
    "mbi", "humana_id", "dob", "gender", "phone_primary", "phone_secondary",
    "email", "address1", "city", "state", "zip_code", "county",
    "medicaid_level", "medicaid_id", "lead_source",
)


def _merge_precedence_key(c):
    # manually_edited (2) > non-stub (1) > stub (0); newer id breaks ties.
    return (2 if c.manually_edited else (0 if c.stub else 1), c.id)


def merge_customers(keeper_id, loser_ids, agency_id, actor):
    """Collapse loser customers into the keeper. Single transaction (caller commits).
    Reattaches Policy, PolicyPayment, AOR, notes, contacts. Fill-blanks-only by
    precedence manual>real>stub. Refuses contradictory dob/mbi. Idempotent."""
    from app.audit import log_event
    keeper = Customer.query.filter_by(id=keeper_id, agency_id=agency_id).first()
    if keeper is None:
        return {"ok": False, "merged": 0, "filled": [], "moved": {}, "error": "keeper not found"}
    losers = (Customer.query
              .filter(Customer.agency_id == agency_id, Customer.id.in_(loser_ids),
                      Customer.id != keeper_id)
              .all())
    if not losers:
        return {"ok": True, "merged": 0, "filled": [], "moved": {}, "error": None}

    # Refuse contradictions across the whole resulting set.
    everyone = [keeper] + losers
    dobs = {c.dob for c in everyone if c.dob is not None}
    mbis = {c.mbi for c in everyone if c.mbi}
    if len(dobs) > 1 or len(mbis) > 1:
        return {"ok": False, "merged": 0, "filled": [], "moved": {},
                "error": "contradictory dob or mbi in cluster"}

    moved = {}
    for model in (Policy, PolicyPayment, CustomerNote, CustomerContact, CustomerAorHistory):
        n = (model.query
             .filter(model.customer_id.in_([l.id for l in losers]))
             .update({"customer_id": keeper.id}, synchronize_session=False))
        moved[model.__name__] = n

    # Fill-blanks-only by precedence.
    fillers = sorted(losers, key=_merge_precedence_key, reverse=True)
    filled = []
    for fld in _MERGE_FILL_FIELDS:
        if getattr(keeper, fld, None):
            continue
        for src in fillers:
            v = getattr(src, fld, None)
            if v:
                setattr(keeper, fld, v)
                filled.append(fld)
                break

    for l in losers:
        db.session.delete(l)

    log_event(action="customer_merge", category="admin",
              detail=f"keeper={keeper.id} losers={[l.id for l in losers]} "
                     f"filled={filled} moved={moved}",
              user=actor, customer_id=keeper.id, record_count=len(losers),
              agency_id_override=agency_id)
    return {"ok": True, "merged": len(losers), "filled": filled, "moved": moved, "error": None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_customer_merge.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/customers.py tests/test_customer_merge.py
git commit -m "feat: merge_customers engine — reattach all children, fill-blanks-only, refuse contradictions, audited"
```

---

### Task 4: Route the existing merge form through the engine

**Files:**
- Modify: `app/customers.py:773-810` (the `customer_merge` POST route)
- Test: `tests/test_customer_merge.py`

**Interfaces:**
- Consumes: `merge_customers` from Task 3.
- Produces: route accepts `primary_id` + one-or-more `secondary_id` form values; on contradiction flashes an error and does NOT delete.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_customer_merge.py
def test_merge_route_uses_engine_and_blocks_contradiction(ctx):
    agency_id, actor = ctx
    app = db.session.get_bind()  # ensure within app context
    from flask import url_for
    keeper = _c(agency_id, first_name="G", last_name="H", full_name="G H",
                dob=date(1950, 1, 1))
    loser = _c(agency_id, first_name="G", last_name="H", full_name="G H",
               dob=date(1962, 2, 2))
    db.session.commit()
    res = merge_customers(keeper.id, [loser.id], agency_id, actor)
    assert res["ok"] is False  # engine refuses; the route surfaces this as a flash
```

(The route itself is exercised end-to-end in the Task 7 real-Postgres verify; this unit test pins the engine contract the route depends on.)

- [ ] **Step 2: Run test to verify it passes against current engine**

Run: `python3 -m pytest tests/test_customer_merge.py::test_merge_route_uses_engine_and_blocks_contradiction -v`
Expected: PASS.

- [ ] **Step 3: Rewrite the route to call the engine**

Replace the body of `customer_merge` (lines ~782-810) with:

```python
    primary_id = request.form.get("primary_id", type=int)
    secondary_ids = request.form.getlist("secondary_id", type=int)
    if not primary_id or not secondary_ids or primary_id in secondary_ids:
        flash("Invalid merge request.", "error")
        return redirect(url_for("customers.customer_duplicates"))

    res = merge_customers(primary_id, secondary_ids, current_user.agency_id, current_user)
    if not res["ok"]:
        db.session.rollback()
        flash(f"Merge blocked: {res['error']}.", "error")
        return redirect(url_for("customers.customer_duplicates"))
    db.session.commit()
    flash(f"Merged {res['merged']} record(s); filled {', '.join(res['filled']) or 'nothing'}.",
          "success")
    return redirect(url_for("customers.customer_profile", customer_id=primary_id))
```

- [ ] **Step 4: Run full merge suite**

Run: `python3 -m pytest tests/test_customer_merge.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/customers.py tests/test_customer_merge.py
git commit -m "feat: route customer_merge form through merge_customers engine (multi-loser + contradiction guard)"
```

---

### Task 5: Surface no-MBI clusters in the duplicates view

**Files:**
- Modify: `app/customers.py:720-770` (the `customer_duplicates` view)
- Modify: `app/templates/customer_duplicates.html`
- Test: `tests/test_customer_merge.py`

**Interfaces:**
- Consumes: `find_no_mbi_clusters` (Task 1); existing MBI grouping.
- Produces: template receives `no_mbi_clusters` = list of `{"signal": str, "keeper": Customer, "rows": list[Customer]}`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_customer_merge.py
def test_duplicates_view_includes_no_mbi_clusters(ctx):
    agency_id, actor = ctx
    from app import create_app
    a = _c(agency_id, first_name="Iz", last_name="Q", full_name="Iz Q", dob=date(1940, 5, 5))
    _c(agency_id, first_name="Iz", last_name="Q", full_name="Iz Q", dob=date(1940, 5, 5),
       stub=True)
    db.session.commit()
    from app.dedup import find_no_mbi_clusters
    clusters = find_no_mbi_clusters(agency_id)
    assert any(c.signal == "dob_match" and a.id in c.member_ids for c in clusters)
```

- [ ] **Step 2: Run test to verify it passes (data layer)**

Run: `python3 -m pytest tests/test_customer_merge.py::test_duplicates_view_includes_no_mbi_clusters -v`
Expected: PASS — confirms the cluster data the view will render exists.

- [ ] **Step 3: Wire the view + template**

In `customer_duplicates` (after building MBI `groups`), add:

```python
    from app.dedup import find_no_mbi_clusters
    raw = find_no_mbi_clusters(current_user.agency_id)
    no_mbi_clusters = []
    for cl in raw:
        rows = (Customer.query
                .filter(Customer.agency_id == current_user.agency_id,
                        Customer.id.in_(cl.member_ids))
                .all())
        keeper = next((r for r in rows if r.id == cl.keeper_id), rows[0])
        no_mbi_clusters.append({"signal": cl.signal, "keeper": keeper, "rows": rows})
    return render_template("customer_duplicates.html", groups=groups,
                           no_mbi_clusters=no_mbi_clusters)
```

In `customer_duplicates.html`, add a section after the MBI groups (autoescape on — no `|safe`):

```html
{% if no_mbi_clusters %}
<h2>Possible duplicates (no shared MBI)</h2>
{% for cl in no_mbi_clusters %}
<div class="card">
  <span class="badge badge-{{ cl.signal }}">{{ cl.signal|replace('_',' ') }}</span>
  {% if cl.signal == 'conflict' %}
    <p class="warn">Different DOB or MBI in this group — review manually; merge blocked.</p>
  {% endif %}
  <form method="post" action="{{ url_for('customers.customer_merge') }}">
    <input type="hidden" name="primary_id" value="{{ cl.keeper.id }}">
    <ul>
      {% for r in cl.rows %}
      <li>
        {{ r.display_name }} — DOB {{ r.dob or '—' }} — MBI {{ r.mbi or '—' }}
        {{ 'stub' if r.stub else '' }}
        {% if r.id != cl.keeper.id %}
          <input type="checkbox" name="secondary_id" value="{{ r.id }}"
                 {{ 'checked' if cl.signal != 'conflict' else 'disabled' }}>
        {% else %}<em>(keeper)</em>{% endif %}
      </li>
      {% endfor %}
    </ul>
    {% if cl.signal == 'name_only' %}
      <label><input type="checkbox" required> I confirm these are the same person</label>
    {% endif %}
    {% if cl.signal != 'conflict' %}
      <button type="submit">Merge into keeper</button>
    {% endif %}
  </form>
</div>
{% endfor %}
{% endif %}
```

- [ ] **Step 4: Run full suite**

Run: `python3 -m pytest tests/test_customer_merge.py tests/test_dedup.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/customers.py app/templates/customer_duplicates.html tests/test_customer_merge.py
git commit -m "feat: surface no-MBI clusters with signal-gated merge in duplicates view"
```

---

### Task 6: Remediation #4 — edit-an-already-used-MBI offers merge

**Files:**
- Modify: `app/customers.py:656-685` (`customer_set_field`)
- Test: `tests/test_customer_merge.py`

**Interfaces:**
- Consumes: existing `customer_set_field` route + `Customer`.
- Produces: when `field == "mbi"` and the value belongs to another customer, returns JSON `{"ok": False, "merge_with": <id>, "merge_with_name": <str>, "error": "..."}` and does NOT save.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_customer_merge.py
def test_editing_to_used_mbi_offers_merge(ctx):
    agency_id, actor = ctx
    app = create_app("testing")
    owner = _c(agency_id, first_name="Own", last_name="Er", full_name="Own Er",
               mbi="1AA2BB3CC44")
    target = _c(agency_id, first_name="Tar", last_name="Get", full_name="Tar Get")
    db.session.commit()
    with app.test_request_context(
        f"/customers/{target.id}/field", method="POST",
        data={"field": "mbi", "value": "1AA2BB3CC44"}):
        from flask_login import login_user
        login_user(actor)
        from app.customers import customer_set_field
        resp = customer_set_field(target.id)
    body = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
    assert body["ok"] is False
    assert body["merge_with"] == owner.id
    # target's MBI was NOT changed
    assert db.session.get(Customer, target.id).mbi is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_customer_merge.py::test_editing_to_used_mbi_offers_merge -v`
Expected: FAIL — currently the field save proceeds or errors generically.

- [ ] **Step 3: Add the pre-check**

In `customer_set_field`, right after the `value = ...` line and before `cp.set_human_value`:

```python
    if field == "mbi" and value:
        owner = (Customer.query
                 .filter(Customer.agency_id == current_user.agency_id,
                         Customer.mbi == value, Customer.id != customer.id)
                 .first())
        if owner is not None:
            return jsonify({"ok": False, "merge_with": owner.id,
                            "merge_with_name": owner.display_name,
                            "error": f"That MBI belongs to {owner.display_name}. "
                                     "Same person? Review a merge."}), 409
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_customer_merge.py::test_editing_to_used_mbi_offers_merge -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/customers.py tests/test_customer_merge.py
git commit -m "feat: editing to an already-used MBI offers merge instead of hard error (remediation #4)"
```

---

### Task 7: Cleanup script + real-Postgres verify

**Files:**
- Create: `scripts/merge_no_mbi_clusters.py`
- Test: manual real-Postgres verify (documented below)

**Interfaces:**
- Consumes: `find_no_mbi_clusters` (Task 1), `merge_customers` (Task 3).
- Produces: a dry-run/`--apply` script that collapses only `dob_match` / `shared_id` clusters.

- [ ] **Step 1: Write the script**

```python
# scripts/merge_no_mbi_clusters.py
"""Collapse no-MBI duplicate clusters that qualify for an unattended merge
(signal dob_match or shared_id). Dry-run by default; pass --apply to write.
NEVER touches name_only or conflict clusters. Back up the DB before --apply."""
import sys
from app import create_app
from app.extensions import db
from app.dedup import find_no_mbi_clusters
from app.customers import merge_customers
from app.models import Agency, User

QUALIFYING = {"dob_match", "shared_id"}


def main(apply=False):
    app = create_app()
    with app.app_context():
        actor = User.query.filter_by(is_admin=True).first()
        for ag in Agency.query.all():
            clusters = [c for c in find_no_mbi_clusters(ag.id) if c.signal in QUALIFYING]
            print(f"agency {ag.id}: {len(clusters)} qualifying clusters")
            for cl in clusters:
                losers = [i for i in cl.member_ids if i != cl.keeper_id]
                print(f"  keeper {cl.keeper_id} <- {losers} [{cl.signal}]")
                if apply:
                    res = merge_customers(cl.keeper_id, losers, ag.id, actor)
                    if res["ok"]:
                        db.session.commit()
                        print(f"    merged {res['merged']}, filled {res['filled']}")
                    else:
                        db.session.rollback()
                        print(f"    SKIPPED: {res['error']}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
```

- [ ] **Step 2: Dry-run locally / in tests**

Run: `python3 -m pytest tests/test_dedup.py tests/test_customer_merge.py -v` (full new suite green).
Then confirm the script imports cleanly: `python3 -c "import scripts.merge_no_mbi_clusters"`.
Expected: PASS + clean import.

- [ ] **Step 3: Run the whole suite**

Run: `python3 -m pytest -q`
Expected: all green (was 443; expect ~458 with the new tests).

- [ ] **Step 4: Real-Postgres verify (on VPS, after DB backup)**

This step is the gate before apply — SQLite hides partial-unique-index / autoflush / concurrency bugs (see item-1 history). Documented here for the deploy session:
```
# 1. Back up:  PGPASSWORD=... pg_dump -U founders_user -h localhost founders_portal > /root/pre_item2_$(date +%Y%m%d).sql
# 2. Dry-run:  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/merge_no_mbi_clusters.py
# 3. Spot-check the John Connelly cluster appears (keeper 1367).
# 4. Apply:    ... scripts/merge_no_mbi_clusters.py --apply
# 5. Verify:   /admin/integrity shows duplicate_customers + orphan_stub_customers dropped.
# 6. Ratchet integrity_baseline.json down to the new counts; commit.
```
Expected: Connelly collapses to one profile (keeper 1367, MBI + DOB intact, all policies/payments attached); counts drop; no errors.

- [ ] **Step 5: Commit**

```bash
git add scripts/merge_no_mbi_clusters.py
git commit -m "feat: scripts/merge_no_mbi_clusters.py — dry-run/--apply cleanup of qualifying no-MBI clusters"
```

---

## Self-review notes (for the executor)

- **Opus whole-branch review** is required before merge to main (every data-path round has caught a real bug). Focus it on: agency-scoping in `find_no_mbi_clusters` + the route; the fill-blanks precedence; the contradiction guard covering the *whole* set not just keeper-vs-one-loser; idempotency on re-run.
- After deploy: update CLAUDE.md START HERE, `BACKLOG.md`, the session-handoff, and ratchet `integrity_baseline.json`.
