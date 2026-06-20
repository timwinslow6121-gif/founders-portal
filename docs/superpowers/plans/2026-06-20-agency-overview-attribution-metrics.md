# Agency Overview, Attribution & Shared Metrics — Implementation Plan (Round 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Agency Overview, agent dashboard, and a new carrier drill-down page show *real, consistent* book (BOB) and money (ledger) numbers — fixing Brian's 481→~1,200 attribution bug — all routed through one shared `app/metrics.py`, with a Brian agency/own toggle and coherence safeguards.

**Architecture:** Resolve the 2,799 unattributed policies via the existing per-carrier writing-ID map (mostly re-resolution, not guessing). Introduce `app/metrics.py` as the single place book/money are computed; every page becomes a thin caller passing a scope. Money always comes from the commission ledger (`split_breakdown`), never from per-policy estimates. A guard test fails the build if a page bypasses `metrics.py`.

**Tech Stack:** Python 3.10, Flask 3, Flask-SQLAlchemy, Alembic (no migration expected), Jinja2 templates extending base.html, pytest. PostgreSQL on VPS / SQLite in tests.

## Global Constraints

- **Source-of-truth rule (verbatim from spec §1):** book numbers (counts, carrier mix, plan mix, terms) come from the `Policy` table; money comes from the `CommissionLineItem` ledger via `app.commission.ledger.split_breakdown`. Never estimate money from policy counts.
- **One computation site:** book/money numbers are computed only in `app/metrics.py`. No new `Policy.query…count()` or `func.count(Policy…)` book/money computation in route/view files.
- **Agency scoping:** every query filters `agency_id` (multi-tenant requirement).
- **Real splits live in `AgentCarrierContract.split_rate`** (Betty/Mike = 0.525, not 0.55). Never hardcode a split. `MAPD_MONTHLY_RATE`/`SPLIT_RATE` constants are deleted by this plan.
- **Material 3 Founders UI** for new templates (Plus Jakarta Sans + Merriweather, blue `#266EA5` / green `#65BB84`, tokens from base.html `:root`; use `var(--…)` tokens, never `var(--ink)` for text).
- **Money/attribution changes proven on real Postgres**, not just SQLite tests; back up the DB before any `--apply` backfill.
- Tests run: `python3 -m pytest -q` (current suite ~296).
- **Test bootstrap — IMPORTANT, applies to EVERY test example below.** `create_app()` takes **no argument**; tests use the existing `tests/conftest.py` fixtures: session-scoped `app`, function-scoped `db_session` (runs `create_all()`/`drop_all()` per test), `agency` (a ready Agency row). **Task 2's example shows the exact corrected pattern — follow it for all tasks.** Mechanically convert any example written as `app = create_app("testing")` + `with app.app_context(): db.create_all() … db.drop_all()` into: a fixture that takes `(db_session, app)`, wraps its body in `with app.app_context():`, drops the manual `create_all`/`drop_all` (the `db_session` fixture does both), and each test function takes `(<fixture>, app)` and runs its assertions inside `with app.app_context():`. Do NOT call `create_app("testing")` anywhere.
- VPS deploy: `ssh -i ~/.ssh/id_ed25519 root@23.187.248.100`, `cd /var/www/founders-portal && git pull && ./venv/bin/pip install -r requirements.txt && FLASK_APP=wsgi.py ./venv/bin/flask db upgrade && systemctl restart founders-portal`.

---

## File Structure

- `app/branding.py` — **new**. `CARRIER_BRAND` dict + `carrier_color(name)`. One source of carrier colors.
- `app/metrics.py` — **new**. `Scope` dataclass + `policy_count`, `book_breakdown`, `commission_totals`, `upcoming_terms`, `attribution_coverage`. The only place book/money is computed.
- `app/attribution.py` — **new**. `resolve_writing_agent(carrier, writing_id, agency_id)` shared resolver.
- `scripts/seed_writing_ids.py` — **new**. Generalizes `seed_uhc_writing_ids.py` to all carriers from a confirmed map; idempotent.
- `scripts/backfill_policy_attribution.py` — **new**. Re-resolves NULL-agent active policies; dry-run default, `--apply`.
- `app/routes.py` — **modify**. Rewrite `admin_overview`; rewrite `_build_dashboard_context` to use metrics + ledger; delete `MAPD_MONTHLY_RATE`/`SPLIT_RATE`; add Unattributed Policies view; add scope toggle.
- `app/commission/routes.py` — **modify**. Delete the duplicate `SPLIT_RATE = 0.55` (line 27) and any use.
- `app/upload.py` — **modify**. Call `resolve_writing_agent` after storing `agent_id_carrier` on admin uploads.
- `app/carriers.py` — **modify**. Add `/carriers/c/<carrier>` drill-down route.
- `app/templates/admin_overview.html`, `dashboard.html` — **modify**. Honest cards, brand chips, toggle.
- `app/templates/carrier_detail.html`, `unattributed_policies.html` — **new**.
- `app/templates/commission/recap.html` — **modify**. Read brand colors from a server-injected map (drop the hardcoded JS dict duplication) — optional cleanup, low risk.
- `tests/test_metrics.py`, `tests/test_attribution.py`, `tests/test_metrics_guard.py`, `tests/test_carrier_detail.py` — **new**.

---

## Task 1: `app/branding.py` — one carrier-color source

**Files:**
- Create: `app/branding.py`
- Test: `tests/test_branding.py`

**Interfaces:**
- Produces: `CARRIER_BRAND: dict[str,str]`; `carrier_color(name: str) -> str` (returns the brand hex or default `#266EA5`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_branding.py
from app.branding import carrier_color, CARRIER_BRAND

def test_known_carrier_colors():
    assert carrier_color("UHC") == "#002677"
    assert carrier_color("Humana") == "#5EA908"
    assert carrier_color("BCBS") == "#0080C7"

def test_alias_and_default():
    assert carrier_color("UnitedHealthcare") == "#002677"
    assert carrier_color("Nonexistent") == "#266EA5"

def test_map_is_dict():
    assert isinstance(CARRIER_BRAND, dict) and "Aetna" in CARRIER_BRAND
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_branding.py -v`
Expected: FAIL (`ModuleNotFoundError: app.branding`)

- [ ] **Step 3: Write minimal implementation**

```python
# app/branding.py
"""Single source of truth for carrier brand colors (was duplicated in recap.html JS)."""

CARRIER_BRAND = {
    "UnitedHealthcare": "#002677", "UHC": "#002677",
    "Humana": "#5EA908",
    "Devoted": "#FF4F00", "Devoted Health": "#FF4F00",
    "BCBS": "#0080C7", "BCBS NC": "#0080C7",
    "Aetna": "#7D3F98",
    "HealthSpring": "#9E28B5", "Healthspring": "#9E28B5",
    "GTL": "#2F61FE",
    "Medico": "#EDC319", "Wellabe": "#EDC319",
}
DEFAULT_BRAND = "#266EA5"

def carrier_color(name: str) -> str:
    return CARRIER_BRAND.get(name, DEFAULT_BRAND)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_branding.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/branding.py tests/test_branding.py
git commit -m "feat(branding): single-source carrier color map"
```

---

## Task 2: `app/attribution.py` — shared writing-ID resolver

**Files:**
- Create: `app/attribution.py`
- Test: `tests/test_attribution.py`

**Interfaces:**
- Consumes: `AgentCarrierContract` (fields `agent_id`, `carrier`, `id_value`, `agency_id`).
- Produces: `resolve_writing_agent(carrier: str, writing_id: str, agency_id: int) -> int | None` — returns the agent `User.id` whose contract for that carrier has `id_value == writing_id`. Returns `None` if no match, blank id, or **map-integrity collision** (the same id_value maps to two different agents for that carrier).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_attribution.py
import pytest
from app.extensions import db
from app.models import Agency, User, AgentCarrierContract
from app.attribution import resolve_writing_agent

@pytest.fixture
def fixt(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u1 = User(name="Brian", email="b@x.com", agency_id=ag.id)
        u2 = User(name="Chris", email="c@x.com", agency_id=ag.id)
        db.session.add_all([u1, u2]); db.session.flush()
        db.session.add(AgentCarrierContract(agent_id=u1.id, carrier="UHC", id_value="6515098", agency_id=ag.id))
        db.session.commit()
        yield ag.id, u1.id, u2.id

def test_resolves_known_id(fixt, app):
    ag, u1, u2 = fixt
    with app.app_context():
        assert resolve_writing_agent("UHC", "6515098", ag) == u1

def test_blank_and_unknown_return_none(fixt, app):
    ag, u1, u2 = fixt
    with app.app_context():
        assert resolve_writing_agent("UHC", "", ag) is None
        assert resolve_writing_agent("UHC", "9999999", ag) is None

def test_collision_returns_none(fixt, app):
    ag, u1, u2 = fixt
    with app.app_context():
        db.session.add(AgentCarrierContract(agent_id=u2, carrier="UHC", id_value="6515098", agency_id=ag))
        db.session.commit()
        assert resolve_writing_agent("UHC", "6515098", ag) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_attribution.py -v`
Expected: FAIL (`ModuleNotFoundError: app.attribution`)

- [ ] **Step 3: Write minimal implementation**

```python
# app/attribution.py
"""Resolve a carrier writing-ID to a portal agent (book ownership).

The Founders override is a COMMISSION classification (same writing-id, same agent;
split_breakdown keeps the money), never a separate book attribution — so it creates
no ambiguity here. The only ambiguity is a map-integrity collision: the same id_value
under two different agents' contract rows for one carrier (a seeding typo). We refuse
to guess in that case and return None so the policy surfaces in the Unattributed view.
"""
from app.extensions import db
from app.models import AgentCarrierContract


def resolve_writing_agent(carrier, writing_id, agency_id):
    wid = (writing_id or "").strip()
    if not wid:
        return None
    rows = (AgentCarrierContract.query
            .filter_by(carrier=carrier, id_value=wid, agency_id=agency_id)
            .all())
    agent_ids = {r.agent_id for r in rows}
    if len(agent_ids) == 1:
        return agent_ids.pop()
    return None  # 0 matches or a collision → don't guess
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_attribution.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/attribution.py tests/test_attribution.py
git commit -m "feat(attribution): shared writing-id resolver with collision guard"
```

---

## Task 3: `scripts/seed_writing_ids.py` — generalize the ID map seeder

**Files:**
- Create: `scripts/seed_writing_ids.py`
- Reference: `scripts/seed_uhc_writing_ids.py` (the UHC-only predecessor)

**Interfaces:**
- Produces: a runnable script that upserts `AgentCarrierContract.id_value`/`id_type` for a confirmed per-carrier map. Idempotent. Prints what it changed. **No test** (one-shot ops script; verified by running on VPS after Tim confirms the map).

> **NOTE for the implementer:** the actual ID→agent map values are filled in by Tim during execution (the spec §4a confirmation step). Ship the script with the UHC block (already known) + an empty, clearly-marked per-carrier block for Tim to paste into. Do NOT invent Humana SANs.

- [ ] **Step 1: Write the script**

```python
# scripts/seed_writing_ids.py
"""Seed AgentCarrierContract.id_value for ALL carriers (generalizes seed_uhc_writing_ids.py).

Each carrier uses its own ID system (Humana=SAN, UHC=AgentID, Devoted/Aetna-MAPD/
Healthspring=NPN, BCBS=pcode, Medico/Wellabe=writing #, GTL=agent code).
Idempotent. Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_writing_ids.py
"""
from app import create_app
from app.extensions import db
from app.models import AgentCarrierContract, User

# carrier -> { "Agent Name": ("id_type", "id_value") }.  UHC is confirmed.
# Other carriers: Tim pastes confirmed IDs here before running (spec §4a).
WRITING_IDS = {
    "UHC": {
        "Timothy Winslow": ("agent_code", "6337213"),
        "Mike Lauzurique": ("agent_code", "6540381"),
        "Rebekah Long":    ("agent_code", "6435806"),
        "Brian Freeman":   ("agent_code", "6515098"),
        "Justin Basinger": ("agent_code", "6448551"),
        "Chris Foster":    ("agent_code", "6453223"),
        "Anjana Patel":    ("agent_code", "6573660"),
        "Betty Marlowe":   ("agent_code", "6632869"),
    },
    # "Humana": { "Brian Freeman": ("writing_number", "19832009"), ... },  # Tim fills
}

def main():
    app = create_app()
    with app.app_context():
        changed = 0
        for carrier, people in WRITING_IDS.items():
            for name, (id_type, id_value) in people.items():
                u = User.query.filter_by(name=name).first()
                if not u:
                    print(f"  SKIP (no user): {name}"); continue
                ct = AgentCarrierContract.query.filter_by(agent_id=u.id, carrier=carrier).first()
                if not ct:
                    ct = AgentCarrierContract(agent_id=u.id, carrier=carrier,
                                              agency_id=u.agency_id, is_active=True)
                    db.session.add(ct)
                if ct.id_value != id_value or ct.id_type != id_type:
                    ct.id_value, ct.id_type = id_value, id_type
                    changed += 1
                    print(f"  SET {carrier} {name} -> {id_value}")
        db.session.commit()
        print(f"Done. {changed} contract id_values set/updated.")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity-run locally (no commit of data, just import check)**

Run: `python3 -c "import ast; ast.parse(open('scripts/seed_writing_ids.py').read()); print('parse ok')"`
Expected: `parse ok`

- [ ] **Step 3: Commit**

```bash
git add scripts/seed_writing_ids.py
git commit -m "feat(scripts): all-carrier writing-id seeder (UHC confirmed; others pasted at run)"
```

---

## Task 4: `scripts/backfill_policy_attribution.py` — re-resolve NULL-agent policies

**Files:**
- Create: `scripts/backfill_policy_attribution.py`

**Interfaces:**
- Consumes: `resolve_writing_agent` (Task 2).
- Produces: dry-run report (per-agent counts of would-resolve + unresolved tally) by default; `--apply` commits `Policy.agent_id`. Idempotent (only touches `agent_id IS NULL`). **No unit test** (ops script; verified on Postgres in Task 11).

- [ ] **Step 1: Write the script**

```python
# scripts/backfill_policy_attribution.py
"""Re-resolve NULL-agent active policies via the (now-complete) writing-id map.

Mostly a RE-RESOLUTION pass: most IDs are already in AgentCarrierContract; they were
just never resolved at upload time. Dry-run by default. Back up the DB before --apply.
Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_policy_attribution.py [--apply]
"""
import sys
from collections import Counter
from app import create_app
from app.extensions import db
from app.models import Policy, User
from app.attribution import resolve_writing_agent

def main(apply):
    app = create_app()
    with app.app_context():
        q = (Policy.query
             .filter(Policy.status == "active", Policy.agent_id.is_(None),
                     Policy.agent_id_carrier.isnot(None), Policy.agent_id_carrier != ""))
        resolved, unresolved = Counter(), Counter()
        for p in q.all():
            aid = resolve_writing_agent(p.carrier, p.agent_id_carrier, p.agency_id)
            if aid:
                resolved[aid] += 1
                if apply:
                    p.agent_id = aid
            else:
                unresolved[(p.carrier, p.agent_id_carrier)] += 1
        if apply:
            db.session.commit()
        print(f"{'APPLIED' if apply else 'DRY-RUN'} — resolved {sum(resolved.values())} policies:")
        for aid, n in resolved.most_common():
            u = db.session.get(User, aid)
            print(f"  {n:5d}  {u.name if u else aid}")
        print(f"Unresolved (stay NULL → Unattributed view): {sum(unresolved.values())}")
        for (carrier, wid), n in unresolved.most_common(20):
            print(f"  {n:5d}  {carrier} writingID={wid!r}")

if __name__ == "__main__":
    main("--apply" in sys.argv)
```

- [ ] **Step 2: Parse-check**

Run: `python3 -c "import ast; ast.parse(open('scripts/backfill_policy_attribution.py').read()); print('parse ok')"`
Expected: `parse ok`

- [ ] **Step 3: Commit**

```bash
git add scripts/backfill_policy_attribution.py
git commit -m "feat(scripts): re-resolve NULL-agent policy attribution (dry-run/--apply)"
```

---

## Task 5: `app/upload.py` — resolve attribution on admin BOB upload

**Files:**
- Modify: `app/upload.py` (the two admin-upload write sites near lines 97 and 349 that set `agent_id_carrier` but leave `agent_id` unresolved)

**Interfaces:**
- Consumes: `resolve_writing_agent` (Task 2).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_upload_attribution.py
import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, User, AgentCarrierContract, Policy
from app.attribution import resolve_writing_agent

def test_resolver_used_for_admin_upload_row():
    # Proxy test: a policy carrying a mapped writing-id resolves to the agent.
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="Brian", email="b@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        db.session.add(AgentCarrierContract(agent_id=u.id, carrier="UHC", id_value="6515098", agency_id=ag.id))
        db.session.commit()
        assert resolve_writing_agent("UHC", "6515098", ag.id) == u.id
        db.drop_all()
```

(The full upload path is integration-heavy; this proves the seam the modification calls. The modification itself is verified live in Task 11.)

- [ ] **Step 2: Run it (passes — guards the seam)**

Run: `python3 -m pytest tests/test_upload_attribution.py -v`
Expected: PASS

- [ ] **Step 3: Modify `app/upload.py` admin-upload sites**

At each admin-upload branch where `bulk_agent_id`/`upload_agent_id` is `None` and the code sets `agent_id_carrier=rec["agent_id"]`, add resolution. Add the import at the top of `upload.py`:

```python
from app.attribution import resolve_writing_agent
```

Then where a new/updated Policy gets its carrier writing-id on an **admin** upload (agent not self-attributing), set:

```python
# admin upload: resolve the carrier writing-id to a portal agent so the book is attributed
if effective_agent_id is None and rec.get("agent_id"):
    effective_agent_id = resolve_writing_agent(rec["carrier"], rec["agent_id"], agency_id)
```

placing it immediately after `effective_agent_id` is computed (lines ~130 and ~389), and ensure the Policy's `agent_id` uses `effective_agent_id`. Do not change self-service agent uploads (they self-attribute).

- [ ] **Step 4: Run the upload test suite**

Run: `python3 -m pytest tests/ -k upload -q`
Expected: PASS (no regressions)

- [ ] **Step 5: Commit**

```bash
git add app/upload.py tests/test_upload_attribution.py
git commit -m "feat(upload): resolve writing-id to agent on admin BOB upload"
```

---

## Task 6: `app/metrics.py` — the shared metrics layer

**Files:**
- Create: `app/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `Policy`, `CommissionLineItem`, `split_breakdown`, `User`.
- Produces:
  - `Scope(agency_id: int, agent_id: int | None = None, carrier: str | None = None, period: str | None = None)` (dataclass).
  - `policy_count(scope) -> int`
  - `book_breakdown(scope) -> dict` with keys `by_carrier`, `by_plan_type`, `by_plan`, `by_agent`, each a list of `{"key": str, "count": int, "pct": float}` sorted desc by count; `pct` = share of the scoped total.
  - `commission_totals(scope) -> dict` `{"paid": float, "agent_payout": float, "founders_keep": float}` from the ledger (uses `split_breakdown`); honors agent/carrier/period filters.
  - `upcoming_terms(scope, days=30) -> list[dict]` `{"member": str, "plan": str, "term_date": date, "reason": str|None, "customer_id": int|None}`.
  - `attribution_coverage(scope) -> dict` `{"total": int, "attributed": int, "pct": float}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics.py
import pytest
from datetime import date, timedelta
from app import create_app
from app.extensions import db
from app.models import Agency, User, Policy, CommissionLineItem, CommissionStatement
from app.metrics import (Scope, policy_count, book_breakdown,
                         commission_totals, upcoming_terms, attribution_coverage)

@pytest.fixture
def seeded():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        brian = User(name="Brian", email="b@x.com", agency_id=ag.id)
        chris = User(name="Chris", email="c@x.com", agency_id=ag.id)
        db.session.add_all([brian, chris]); db.session.flush()
        # 3 UHC for Brian, 1 Humana for Chris, 1 UHC unattributed
        for i in range(3):
            db.session.add(Policy(carrier="UHC", member_id=f"u{i}", status="active",
                                  agent_id=brian.id, agency_id=ag.id, plan_type="MA",
                                  plan_name="NC-0015"))
        db.session.add(Policy(carrier="Humana", member_id="h1", status="active",
                              agent_id=chris.id, agency_id=ag.id, plan_type="MAPD"))
        db.session.add(Policy(carrier="UHC", member_id="u9", status="active",
                              agent_id=None, agent_id_carrier="6515098", agency_id=ag.id,
                              plan_type="MA"))
        st = CommissionStatement(carrier="UHC", period_label="May 2026", agency_id=ag.id)
        db.session.add(st); db.session.flush()
        db.session.add(CommissionLineItem(agency_id=ag.id, statement_id=st.id, carrier="UHC",
            period_label="May 2026", source_ref="x::1", agent_id=brian.id,
            raw_amount=100.0, split_rate=0.55, classification="agent_commission"))
        db.session.commit()
        yield ag.id, brian.id, chris.id
        db.drop_all()

def test_policy_count_scopes(seeded):
    ag, brian, chris = seeded
    assert policy_count(Scope(agency_id=ag)) == 5
    assert policy_count(Scope(agency_id=ag, agent_id=brian)) == 3
    assert policy_count(Scope(agency_id=ag, carrier="UHC")) == 4

def test_book_breakdown_by_carrier(seeded):
    ag, brian, chris = seeded
    bc = {r["key"]: r["count"] for r in book_breakdown(Scope(agency_id=ag))["by_carrier"]}
    assert bc == {"UHC": 4, "Humana": 1}

def test_commission_totals_from_ledger(seeded):
    ag, brian, chris = seeded
    t = commission_totals(Scope(agency_id=ag, period="May 2026"))
    assert round(t["agent_payout"], 2) == 55.0
    assert round(t["founders_keep"], 2) == 45.0

def test_attribution_coverage(seeded):
    ag, brian, chris = seeded
    cov = attribution_coverage(Scope(agency_id=ag))
    assert cov["total"] == 5 and cov["attributed"] == 4 and cov["pct"] == 80.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_metrics.py -v`
Expected: FAIL (`ModuleNotFoundError: app.metrics`)

- [ ] **Step 3: Write the implementation**

```python
# app/metrics.py
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
    q = Policy.query.filter_by(status="active", agency_id=scope.agency_id)
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
        "by_plan_type": _grouped(scope, Policy.plan_type),
        "by_plan": _grouped(scope, Policy.plan_name),
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
             "term_date": p.term_date, "reason": p.term_reason,
             "customer_id": cust.get(p.mbi)} for p in rows]


def attribution_coverage(scope) -> dict:
    total = _policy_q(scope).count()
    attributed = _policy_q(scope).filter(Policy.agent_id.isnot(None)).count()
    return {"total": total, "attributed": attributed,
            "pct": round(attributed / total * 100, 1) if total else 100.0}
```

> Implementer note: verify `Policy` has `first_name`/`last_name`/`term_reason`/`plan_name`/`plan_type`/`mbi`. If a column name differs, adjust the attribute (do NOT add a column).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_metrics.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/metrics.py tests/test_metrics.py
git commit -m "feat(metrics): shared book/money metrics layer (single source of truth)"
```

---

## Task 7: Guard test — build fails if a page bypasses metrics.py

**Files:**
- Create: `tests/test_metrics_guard.py`

**Interfaces:**
- Produces: a test scanning route/view files for raw book/money computation outside `app/metrics.py`, with an explicit shrinking allowlist.

- [ ] **Step 1: Write the test**

```python
# tests/test_metrics_guard.py
"""Coherence guard (spec §6.1): book/money numbers are computed ONLY in app/metrics.py.
Fails if a route/view file introduces a new raw policy COUNT or a hardcoded split rate.
Migrate the call into metrics.py, or (rarely) add it to ALLOWLIST with a reason."""
import re, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCANNED = ["app/routes.py", "app/carriers.py", "app/commission/routes.py"]

# Files/lines knowingly still computing their own numbers (shrink over time).
# Format: (relpath, substring that identifies the allowed line)
ALLOWLIST = {
    # e.g. ("app/commission/routes.py", "_reconcile"),  # Round 2 rebuilds this
}

COUNT_RE = re.compile(r"func\.count\(\s*Policy|\.filter_by\([^)]*\)\.count\(\)|Policy\.query[\s\S]{0,80}\.count\(\)")
RATE_RE = re.compile(r"MAPD_MONTHLY_RATE|SPLIT_RATE\s*=")

def test_no_book_or_money_compute_outside_metrics():
    offenders = []
    for rel in SCANNED:
        text = (ROOT / rel).read_text()
        for ln, line in enumerate(text.splitlines(), 1):
            if COUNT_RE.search(line) or RATE_RE.search(line):
                if any(rel == a and sub in line for a, sub in ALLOWLIST):
                    continue
                offenders.append(f"{rel}:{ln}: {line.strip()}")
    assert not offenders, (
        "Book/money computed outside app/metrics.py — move it into metrics.py "
        "or allowlist with a reason:\n" + "\n".join(offenders))
```

- [ ] **Step 2: Run it — EXPECT FAIL (proves it catches the current fake constants)**

Run: `python3 -m pytest tests/test_metrics_guard.py -v`
Expected: FAIL listing `app/routes.py` (MAPD_MONTHLY_RATE/SPLIT_RATE) and any Policy counts. This confirms the guard works; Tasks 8–9 make it pass by removing them.

- [ ] **Step 3: Commit (failing guard, to be satisfied by the rewrites)**

```bash
git add tests/test_metrics_guard.py
git commit -m "test(metrics): guard test — book/money only in metrics.py (currently failing by design)"
```

---

## Task 8: Rewrite `_build_dashboard_context` + delete fake constants

**Files:**
- Modify: `app/routes.py` (`_build_dashboard_context` lines 27–119; constants lines 11–12; `dashboard` + `agent_detail` already call it)

**Interfaces:**
- Consumes: `metrics.book_breakdown`, `metrics.commission_totals`, `metrics.upcoming_terms`, `metrics.policy_count`, `branding.carrier_color`, `latest_period_with_data`.

- [ ] **Step 1: Update the dashboard test expectations**

```python
# tests/test_dashboard_metrics.py
import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, User, Policy, CommissionStatement, CommissionLineItem

def test_dashboard_carrier_breakdown_has_no_fake_money():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="Brian", email="b@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        db.session.add(Policy(carrier="UHC", member_id="u1", status="active",
                              agent_id=u.id, agency_id=ag.id, plan_type="MA"))
        db.session.commit()
        from app.routes import _build_dashboard_context
        from datetime import date
        ctx = _build_dashboard_context(u.id, date.today(), ag.id)
        # money comes from ledger now: with no ledger rows, commission total is $0.00, not an estimate
        assert ctx["monthly_commission"] == "$0.00"
        assert ctx["policy_count"] == 1
        db.drop_all()
```

- [ ] **Step 2: Run — FAIL (old code returns a fake estimate)**

Run: `python3 -m pytest tests/test_dashboard_metrics.py -v`
Expected: FAIL (`monthly_commission` is a fake non-zero estimate)

- [ ] **Step 3: Rewrite `_build_dashboard_context`**

Replace lines 11–12 (delete the constants) and the body of `_build_dashboard_context` (27–119) so carrier breakdown comes from `book_breakdown` + `carrier_color`, and money comes from `commission_totals` for the latest period:

```python
# top of app/routes.py — replace the two constants with:
from app.metrics import (Scope, policy_count, book_breakdown,
                         commission_totals, upcoming_terms)
from app.branding import carrier_color
from app.commission.recap import latest_period_with_data
# (MAPD_MONTHLY_RATE / SPLIT_RATE deleted)
```

```python
def _build_dashboard_context(agent_id, today, agency_id):
    scope = Scope(agency_id=agency_id, agent_id=agent_id)
    book = book_breakdown(scope)
    period = latest_period_with_data(agency_id)
    money = commission_totals(Scope(agency_id=agency_id, agent_id=agent_id, period=period))

    terms = upcoming_terms(scope, days=90)
    terms_90 = len(terms)
    terms_30 = sum(1 for t in terms if (t["term_date"] - today).days <= 30)

    carrier_breakdown = [{"carrier": r["key"], "count": r["count"], "pct": r["pct"],
                          "color": carrier_color(r["key"])} for r in book["by_carrier"]]

    last_batch = (ImportBatch.query.filter_by(status='success', agency_id=agency_id)
                  .order_by(ImportBatch.upload_date.desc()).first())
    last_import = last_batch.upload_date.strftime('%b %d, %Y') if last_batch else None

    return dict(
        policy_count=policy_count(scope),
        carrier_count=len(book["by_carrier"]),
        terms_90=terms_90, terms_30=terms_30,
        upcoming_terms=terms,
        carrier_breakdown=carrier_breakdown,
        monthly_commission=_fmt(money["agent_payout"]),
        commission_period=period,
        last_import=last_import,
    )
```

> Implementer: `dashboard.html` references some removed keys (`annual_commission`, `total_gross_monthly`, `gross_monthly`/`your_monthly` per carrier, `upcoming_appointments`). Update the template in Step 4 to use the new keys (count/pct/color, `monthly_commission` labeled "actual — {{ commission_period }}"); drop the fake gross/your columns. Keep `upcoming_appointments` only if still wired — if removed, delete its template block.

- [ ] **Step 4: Update `dashboard.html`** to the new keys (brand-colored carrier chips via `style="background:{{ c.color }}"`, money labeled as actual ledger for the period, no fake gross/estimate columns).

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_dashboard_metrics.py tests/test_metrics.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/routes.py app/templates/dashboard.html tests/test_dashboard_metrics.py
git commit -m "refactor(dashboard): route through metrics.py; ledger money; delete fake estimate constants"
```

---

## Task 9: Rewrite `admin_overview` + Unattributed Policies view

**Files:**
- Modify: `app/routes.py` (`admin_overview` 166–259)
- Modify: `app/templates/admin_overview.html`
- Create: `app/templates/unattributed_policies.html`
- Modify: `app/commission/routes.py` (delete `SPLIT_RATE = 0.55` line 27 + any use)

**Interfaces:**
- Consumes: `metrics.*`, `branding.carrier_color`, `latest_period_with_data`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_overview.py
import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, User, Policy

def test_admin_overview_agent_counts_full_book(client_admin_ctx):
    pass  # see Step 3; asserts agent count includes attributed policies
```

(Use the simpler direct-helper test below to avoid auth scaffolding.)

```python
# tests/test_admin_overview.py
import pytest
from datetime import date
from app import create_app
from app.extensions import db
from app.models import Agency, User, Policy
from app.metrics import Scope, book_breakdown

def test_agent_breakdown_counts_attributed_book():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        brian = User(name="Brian", email="b@x.com", agency_id=ag.id); db.session.add(brian); db.session.flush()
        for i in range(7):
            db.session.add(Policy(carrier="UHC", member_id=f"u{i}", status="active",
                                  agent_id=brian.id, agency_id=ag.id))
        db.session.commit()
        rows = book_breakdown(Scope(agency_id=ag.id))["by_agent"]
        brian_row = next(r for r in rows if r["agent_id"] == brian.id)
        assert brian_row["count"] == 7
        db.drop_all()
```

- [ ] **Step 2: Run — PASS (metrics already correct); this guards the wiring**

Run: `python3 -m pytest tests/test_admin_overview.py -v`
Expected: PASS

- [ ] **Step 3: Rewrite `admin_overview`** to build all numbers from `metrics`:

```python
@main.route('/admin')
@login_required
def admin_overview():
    if not current_user.is_admin:
        abort(403)
    today = date.today()
    agency_id = current_user.agency_id
    scope = Scope(agency_id=agency_id)
    book = book_breakdown(scope)
    period = latest_period_with_data(agency_id)
    money = commission_totals(Scope(agency_id=agency_id, period=period))
    cov = attribution_coverage(scope)

    carrier_rows = [{"carrier": r["key"], "count": r["count"], "pct": r["pct"],
                     "color": carrier_color(r["key"])} for r in book["by_carrier"]]

    agent_rows = []
    for r in book["by_agent"]:
        if r["agent_id"] is None:
            continue
        a_scope = Scope(agency_id=agency_id, agent_id=r["agent_id"])
        a_money = commission_totals(Scope(agency_id=agency_id, agent_id=r["agent_id"], period=period))
        a_terms = upcoming_terms(a_scope, days=30)
        agent_rows.append({
            "agent_id": r["agent_id"], "name": r["key"], "count": r["count"],
            "pct_of_agency": r["pct"], "terms_30": len(a_terms),
            "payout": _fmt(a_money["agent_payout"]),
            "top_carriers": book_breakdown(a_scope)["by_carrier"][:3],
        })

    return render_template('admin_overview.html',
        total_policies=policy_count(scope),
        coverage=cov,
        terms_30=len(upcoming_terms(scope, days=30)),
        terms_90=len(upcoming_terms(scope, days=90)),
        commission_period=period,
        agency_payout=_fmt(money["agent_payout"]),
        founders_keep=_fmt(money["founders_keep"]),
        carrier_rows=carrier_rows,
        agent_rows=agent_rows,
        carrier_color=carrier_color,
        today=today)
```

Add the Unattributed Policies route:

```python
@main.route('/admin/unattributed-policies')
@login_required
def unattributed_policies():
    if not current_user.is_admin:
        abort(403)
    rows = (Policy.query
            .filter(Policy.status == "active", Policy.agent_id.is_(None),
                    Policy.agency_id == current_user.agency_id)
            .order_by(Policy.carrier, Policy.agent_id_carrier).all())
    return render_template('unattributed_policies.html', rows=rows)
```

- [ ] **Step 4: Update `admin_overview.html`** — 4 honest cards (Total Active Policies + coverage line linking to unattributed view; Upcoming Terms 30d; Commissions — {{ commission_period }} actual = agency_payout / founders_keep; "N to reconcile →" pointer to the reconciliation page); carrier grid uses `style="background:{{ row.color }}"`; agent table shows `count`, `pct_of_agency`, `terms_30`, `payout`, brand-colored top-carrier chips. Create `unattributed_policies.html` (table: carrier, writing-id, member, link). Both Material 3.

- [ ] **Step 5: Delete `SPLIT_RATE = 0.55` in `app/commission/routes.py:27`** and fix any reference (grep first: `grep -n SPLIT_RATE app/commission/routes.py`). If used, replace with the real contract rate or remove the dead code.

- [ ] **Step 6: Run the guard + suite**

Run: `python3 -m pytest tests/test_metrics_guard.py tests/test_admin_overview.py -q`
Expected: PASS (guard now green — fake constants gone)

- [ ] **Step 7: Commit**

```bash
git add app/routes.py app/commission/routes.py app/templates/admin_overview.html app/templates/unattributed_policies.html tests/test_admin_overview.py
git commit -m "refactor(overview): honest dashboard via metrics.py; unattributed view; delete duplicate SPLIT_RATE"
```

---

## Task 10: Carrier drill-down page + Brian's toggle

**Files:**
- Modify: `app/carriers.py` (add `/carriers/c/<carrier>` — distinct from `/carriers/<int:plan_id>`)
- Create: `app/templates/carrier_detail.html`
- Modify: `app/templates/admin_overview.html`, `dashboard.html` (carrier boxes link to it; add the agency/own toggle)
- Test: `tests/test_carrier_detail.py`

**Interfaces:**
- Consumes: `metrics.*`, `branding.carrier_color`, existing `balance_status` (from recap.py) for the commission proof badge.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_carrier_detail.py
import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, User, Policy
from app.metrics import Scope, book_breakdown, attribution_coverage

def test_carrier_scope_breakdowns():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="Brian", email="b@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        for i in range(4):
            db.session.add(Policy(carrier="UHC", member_id=f"u{i}", status="active",
                                  agent_id=u.id, agency_id=ag.id, plan_type="MA", plan_name="NC-0015"))
        db.session.add(Policy(carrier="Humana", member_id="h", status="active",
                              agent_id=u.id, agency_id=ag.id))
        db.session.commit()
        s = Scope(agency_id=ag.id, carrier="UHC")
        bd = book_breakdown(s)
        assert sum(r["count"] for r in bd["by_plan_type"]) == 4
        assert attribution_coverage(s)["pct"] == 100.0
        db.drop_all()
```

- [ ] **Step 2: Run — PASS (guards the scope the page uses)**

Run: `python3 -m pytest tests/test_carrier_detail.py -v`
Expected: PASS

- [ ] **Step 3: Add the route** in `app/carriers.py`:

```python
from app.metrics import (Scope, policy_count, book_breakdown,
                         commission_totals, upcoming_terms, attribution_coverage)
from app.branding import carrier_color
from app.commission.recap import latest_period_with_data

@carriers_bp.route("/carriers/c/<carrier>")
@login_required
def carrier_detail(carrier):
    agency_id = current_user.agency_id
    # Brian/admin agency-vs-own toggle: ?view=mine scopes to the current agent
    agent_id = current_user.id if request.args.get("view") == "mine" else None
    if agent_id is None and not current_user.is_admin:
        agent_id = current_user.id  # non-admins only ever see their own
    scope = Scope(agency_id=agency_id, agent_id=agent_id, carrier=carrier)
    period = latest_period_with_data(agency_id)
    return render_template("carrier_detail.html",
        carrier=carrier, color=carrier_color(carrier),
        total=policy_count(scope),
        agency_total=policy_count(Scope(agency_id=agency_id, carrier=carrier)),
        coverage=attribution_coverage(scope),
        book=book_breakdown(scope),
        money=commission_totals(Scope(agency_id=agency_id, agent_id=agent_id,
                                      carrier=carrier, period=period)),
        terms=upcoming_terms(scope, days=30),
        period=period,
        view_mine=(agent_id is not None and current_user.is_admin))
```

> Implementer: ensure `request`, `login_required`, `current_user` are imported in `carriers.py` (add if missing).

- [ ] **Step 4: Create `carrier_detail.html`** — Material 3, the approved mockup: hero band (`background:{{ color }}`, total + % of agency book), proof strip (coverage + balance + source), policy-type mix (`book.by_plan_type`), agent share (`book.by_agent`), plans table (`book.by_plan`, link rows to plan detail), upcoming terms (30d, dates). Include an "Agency / My view" toggle linking `?view=mine`/no-arg for admins.

- [ ] **Step 5: Link carrier boxes** in `admin_overview.html` + `dashboard.html` to `url_for('carriers.carrier_detail', carrier=row.carrier)`; add the same agency/own toggle control to the overview header for admins/owner.

- [ ] **Step 6: Run**

Run: `python3 -m pytest tests/test_carrier_detail.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/carriers.py app/templates/carrier_detail.html app/templates/admin_overview.html app/templates/dashboard.html tests/test_carrier_detail.py
git commit -m "feat(carrier): carrier drill-down page + agency/own toggle, all via metrics.py"
```

---

## Task 11: Full-suite green + live Postgres verification & rollout

**Files:** none (verification + deploy)

- [ ] **Step 1: Full suite**

Run: `python3 -m pytest -q`
Expected: PASS (≈296 + new tests; guard green)

- [ ] **Step 2: Update trust-map + BACKLOG + START HERE**

Update `BACKLOG.md` (mark Round-1 items shipped; add Round 2/3 as open), the spec's trust-map table state, and CLAUDE.md START HERE per the Session Protocol.

```bash
git add BACKLOG.md CLAUDE.md docs/superpowers/specs/2026-06-20-agency-overview-attribution-metrics-design.md
git commit -m "docs: trust-map + backlog + START HERE for metrics/attribution round 1"
```

- [ ] **Step 3: Push + deploy to VPS**

```bash
git push origin main
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100 'cd /var/www/founders-portal && git pull && ./venv/bin/pip install -r requirements.txt && systemctl restart founders-portal'
```

- [ ] **Step 4: Confirm the per-carrier ID map with Tim, seed, back up, dry-run, apply**

Tim pastes confirmed Humana/other IDs into `scripts/seed_writing_ids.py` (the inferred table is generated from a dry-run of `backfill_policy_attribution.py` reading distinct unresolved IDs). Then on VPS:

```bash
# back up first
ssh … 'cd /var/www/founders-portal && PGPASSWORD=<from .env> pg_dump -U founders_user -h localhost founders_portal > /root/founders_pre_attribution_$(date +%F).sql'
# seed the confirmed map
ssh … 'cd /var/www/founders-portal && PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_writing_ids.py'
# dry-run, eyeball, then apply
ssh … 'cd /var/www/founders-portal && PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_policy_attribution.py'
ssh … 'cd /var/www/founders-portal && PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_policy_attribution.py --apply'
```

- [ ] **Step 5: Verify Brian's number on live Postgres**

Confirm Brian ≈ 1,200 active policies, Σ agents = agency total, 0 orphan (or the residual surfaced in the Unattributed view). Spot-check the Agency Overview + a carrier page + Brian's "My view" toggle agree (same `metrics` calls → must match).

---

## Self-Review

**Spec coverage:**
- §1 governing principle → Task 6 (metrics) + Task 7 (guard). ✓
- §2 inventory → reused: branding (T1), resolver extends commission pattern (T2), seeder generalizes UHC (T3). ✓
- §3a metrics layer → Task 6. ✓
- §3b honest overview → Task 9. §3c agent_detail → Task 8 (shared `_build_dashboard_context`, also fixes the agent dashboard). ✓
- §4 attribution (re-resolve + infer/confirm + wire upload + guardrail) → Tasks 2–5, 11. ✓
- §5a branding → Task 1. §5b carrier page → Task 10. §5c toggle → Task 10 + Task 9. ✓
- §6 safeguards: guard test (T7), trust-map (T11 docs), migrate agent_detail + delete fake constants (T8, T9), delete-don't-orphan (T8/T9 delete constants; T9 deletes duplicate SPLIT_RATE). ✓
- §7 testing/rollout → Task 11 (Postgres verify, backup, no migration). ✓
- §8 out-of-scope (Round 2/3) → not implemented, only referenced. ✓

**Placeholder scan:** all code steps contain real code; ops-script ID values are intentionally Tim-supplied at runtime (spec §4a) and flagged as such, not a plan placeholder. ✓

**Type consistency:** `Scope(agency_id, agent_id, carrier, period)` used identically across Tasks 6/8/9/10. `book_breakdown` returns `by_carrier/by_plan_type/by_plan/by_agent` with `{key,count,pct}` (+`agent_id` on by_agent) — consumed consistently. `commission_totals` returns `{paid,agent_payout,founders_keep}` everywhere. `carrier_color(name)` signature stable. ✓
