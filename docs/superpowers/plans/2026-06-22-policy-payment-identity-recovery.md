# Policy / Payment Identity Recovery & AOR Traceability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every payment, policy, and customer traceable to the AOR — each satisfies its link (payment→customer, policy→identity, customer→agent, owned-record→dated AOR interval) or sits in one unified Needs Identity hub — via cleanup + prevention, reusing the existing resolver.

**Architecture:** A small `app/identity.py` orchestrator applies a confidence ladder (MBI → carrier_member_id → strong composite → queue) reusing `app/commission/resolver.py`'s matchers. Three idempotent dry-run/--apply cleanup scripts run it over the live gaps. The existing `/customers/unassigned` page is broadened into the 4-category hub. Commission ingest stops spawning phantom stubs on weak identity. `app/metrics.py` excludes queued/stub records from book counts.

**Tech Stack:** Python 3.10, Flask 3, Flask-SQLAlchemy, Alembic (one small migration for hub category state), Jinja2, pytest. PostgreSQL on VPS / SQLite in tests.

## Global Constraints

- **The four-link guarantee (verbatim acceptance, spec §10):** every `CommissionLineItem` has a `customer_id` OR is a tagged non-customer payment OR is in the hub; every active `Policy` has a name + member_id OR is in the hub; every `Customer` has a `primary_agent_id` OR is in the hub; every agent'd `Customer` has a dated `CustomerAorHistory` interval OR is in the hub.
- **Match ladder (spec §2):** auto-write ONLY on tier 1 (MBI exact), tier 2 (member_id/carrier_member_id exact), or tier 3 (strong composite = name + DOB + at least one of zip/phone/email/address). **Name alone never matches and never writes.** Weaker → queue.
- **Carrier-provided start/end dates are the source of truth** for derived AOR intervals; never invent or shift them. BCBS interval `end_date` is always `None` (BCBS term_date is a renewal date, not a termination).
- **Never overwrite** an existing name/agent, and never touch a `manually_edited` customer.
- **Prevention is a confidence boundary, not "never create" (spec §6):** strong identity (MBI/carrier-id/full composite) → create new customer/policy (legit new-to-Medicare); weak → enqueue with full attribution info, no phantom policy.
- **Reuse `app/commission/resolver.py`** matchers (`_match_by_mbi`, `_find_name_dob_match`, `_create_stub`, `_open_aor_interval`, `_enqueue_suggestion`, `_aor_close_date`); do not reimplement matching.
- Every query filters `agency_id` (multi-tenant). Money/attribution cleanup verified on real Postgres + DB backed up before any `--apply`.
- Test bootstrap uses the existing `tests/conftest.py` fixtures (`db_session`, `app`, `agency`); `create_app()` takes NO argument. See `tests/test_attribution.py` for the working pattern. Never call `create_app("testing")`.
- Tests: `python3 -m pytest -q` (suite ~312). The `app/metrics.py` guard test must stay green.
- VPS deploy: `ssh -i ~/.ssh/id_ed25519 root@23.187.248.100`; `git pull && ./venv/bin/pip install -r requirements.txt && FLASK_APP=wsgi.py ./venv/bin/flask db upgrade && systemctl restart founders-portal`. Backup: `PGPASSWORD=<from .env> pg_dump -U founders_user -h localhost founders_portal`.

---

## File Structure

- `app/identity.py` — **new.** `Identity` confidence ladder orchestrator + composite matcher. The one seam for "resolve this record's identity."
- `app/commission/resolver.py` — **modify.** Add a `carrier_member_id → Policy.member_id` match (tier 2 for payments); extend `_find_name_dob_match` to a corroborated composite; change the no-match tail (§6 prevention).
- `scripts/recover_payment_customer.py` — **new.** Link-1 cleanup: re-point NULL-customer line items via carrier_member_id/MBI; parse Devoted HRA descriptions; delete resolved `uhc::0::N` stubs.
- `scripts/recover_policy_names.py` — **new.** Link-2 cleanup: ledger-first name recovery for no-name policies.
- `scripts/recover_aor_intervals.py` — **new.** Link-4 cleanup: derive AOR intervals from policy facts.
- `app/customers.py` — **modify.** Broaden `customers_unassigned` into the 4-category Needs Identity hub + add `_suggested_customer_match` + a confirm-match action.
- `app/templates/customers_unassigned.html` — **modify.** Category filter/tabs; per-category rows + actions.
- `app/metrics.py` — **modify.** Exclude stub `member_id LIKE 'uhc::%'` + hub-queued items from `_policy_q`.
- `app/commission/ingest.py` (or wherever `resolve_customer` is invoked) — **modify.** Prevention wiring (covered by the resolver tail change).
- Tests: `tests/test_identity.py`, `tests/test_resolver_carrier_member_id.py`, `tests/test_resolver_prevention.py`, `tests/test_needs_identity_hub.py`.

---

## Task 1: carrier_member_id match in the resolver (the big payment join)

**Files:**
- Modify: `app/commission/resolver.py` (add `_match_by_carrier_member_id`; call it in `resolve_customer` after `_match_by_mbi`)
- Test: `tests/test_resolver_carrier_member_id.py`

**Interfaces:**
- Consumes: `MemberFact` (has `carrier`, `carrier_member_id`), `Policy`, `Customer`.
- Produces: `_match_by_carrier_member_id(fact, agency_id) -> Customer | None` — returns the Customer of an existing active `Policy` whose `(carrier, member_id) == (fact.carrier, fact.carrier_member_id)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resolver_carrier_member_id.py
import pytest
from app.extensions import db
from app.models import Agency, User, Customer, Policy
from app.commission.member_fact import MemberFact
from app.commission.resolver import _match_by_carrier_member_id

@pytest.fixture
def fixt(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=ag.id, full_name="JANE DOE", first_name="Jane", last_name="Doe",
                     primary_agent_id=u.id); db.session.add(c); db.session.flush()
        p = Policy(agency_id=ag.id, carrier="BCBS", member_id="112850623", status="active",
                   customer_id=c.id, agent_id=u.id, member_name="DOE, JANE"); db.session.add(p)
        db.session.commit()
        yield ag.id, c.id

def test_matches_by_carrier_member_id(fixt, app):
    ag, cid = fixt
    with app.app_context():
        f = MemberFact(carrier="BCBS", full_name="DOE, JANE", carrier_member_id="112850623")
        c = _match_by_carrier_member_id(f, ag)
        assert c is not None and c.id == cid

def test_no_match_wrong_carrier(fixt, app):
    ag, cid = fixt
    with app.app_context():
        f = MemberFact(carrier="Humana", full_name="x", carrier_member_id="112850623")
        assert _match_by_carrier_member_id(f, ag) is None

def test_blank_returns_none(fixt, app):
    ag, cid = fixt
    with app.app_context():
        assert _match_by_carrier_member_id(MemberFact(carrier="BCBS", full_name="x"), ag) is None
```

- [ ] **Step 2: Run — FAIL** (`ImportError: _match_by_carrier_member_id`)

Run: `python3 -m pytest tests/test_resolver_carrier_member_id.py -v`

- [ ] **Step 3: Implement** in `app/commission/resolver.py` (place near `_match_by_mbi`):

```python
def _match_by_carrier_member_id(fact, agency_id):
    """Return the Customer of an existing active Policy whose (carrier, member_id)
    equals this fact's (carrier, carrier_member_id). Resolves commission rows that
    carry the carrier's member id but no MBI (the matcher previously only tried MBI).
    no_autoflush: must not autoflush a pending stub mid-import."""
    cmid = (fact.carrier_member_id or "").strip()
    if not cmid:
        return None
    with db.session.no_autoflush:
        p = (Policy.query
             .filter_by(carrier=fact.carrier, member_id=cmid, agency_id=agency_id)
             .filter(Policy.customer_id.isnot(None))
             .first())
    return Customer.query.get(p.customer_id) if p else None
```

Then in `resolve_customer`, **after** the MBI block (step 2, after line ~328) and before the suggest-link block, add a tier-2 block:

```python
    # 2b. carrier_member_id match — a real carrier id is as good as an MBI.
    customer = _match_by_carrier_member_id(fact, agency_id)
    if customer is not None:
        result.customer = customer
        existing = _crosswalk(fact, agency_id)
        if existing is not None:
            existing.customer_id = existing.customer_id or customer.id
            result.policy = existing
        else:
            result.policy = _attach_policy(fact, customer, agency_id, agent_id)
            result.created_policy = True
        result.match_path = "carrier_member_id"
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result, source)
        return result
```

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_resolver_carrier_member_id.py -v`

- [ ] **Step 5: Run the resolver/commission suite for regressions**

Run: `python3 -m pytest tests/ -k "resolver or commission or ledger" -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/commission/resolver.py tests/test_resolver_carrier_member_id.py
git commit -m "feat(resolver): match by carrier_member_id (resolves ~393 NULL-customer payments)"
```

---

## Task 2: corroborated composite matcher + prevention tail

**Files:**
- Modify: `app/commission/resolver.py` (`_find_name_dob_match` → add a corroborating-field requirement for an `auto` tier; change the no-match tail per §6)
- Test: `tests/test_resolver_prevention.py`

**Interfaces:**
- Consumes: `MemberFact`, `Customer`.
- Produces: `_composite_match(fact, agency_id) -> (Customer|None, str|None)` returning `(customer, "composite")` only when name + DOB + ≥1 of {zip, phone} agree, else `(None, None)`. `has_strong_identity(fact) -> bool` (True if MBI, carrier_member_id, or a composite match exists).

> **Reality note (spec §1 re-audit):** `MemberFact` and `CommissionLineItem` carry name/MBI/carrier_member_id but **no dob/zip/phone**. So `_composite_match` will rarely fire for commission rows (the data isn't there) — it exists for BOB-sourced facts (which carry dob/zip/phone) and future use. For payments, tier-1/tier-2 do the real work; the composite is the honest "name-alone-isn't-enough" gate.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resolver_prevention.py
import pytest
from datetime import date
from app.extensions import db
from app.models import Agency, User, Customer
from app.commission.member_fact import MemberFact
from app.commission.resolver import _composite_match, has_strong_identity

@pytest.fixture
def fixt(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        c = Customer(agency_id=ag.id, first_name="Jane", last_name="Doe",
                     full_name="Jane Doe", dob=date(1950,1,1), zip_code="28012",
                     phone_primary="7045551212"); db.session.add(c)
        db.session.commit()
        yield ag.id, c.id

def test_composite_needs_corroborating_field(fixt, app):
    ag, cid = fixt
    with app.app_context():
        # name + dob ONLY → not enough → no auto match
        f1 = MemberFact(carrier="UHC", full_name="Jane Doe", first_name="Jane",
                        last_name="Doe", dob=date(1950,1,1))
        assert _composite_match(f1, ag) == (None, None)
        # name + dob + zip → composite
        f2 = MemberFact(carrier="UHC", full_name="Jane Doe", first_name="Jane",
                        last_name="Doe", dob=date(1950,1,1))
        f2.zip_code = "28012"
        c, conf = _composite_match(f2, ag)
        assert c is not None and conf == "composite"

def test_has_strong_identity(app):
    with app.app_context():
        assert has_strong_identity(MemberFact(carrier="UHC", full_name="x", mbi="1ABC")) is True
        assert has_strong_identity(MemberFact(carrier="UHC", full_name="x",
                                              carrier_member_id="999")) is True
        assert has_strong_identity(MemberFact(carrier="UHC", full_name="x")) is False
```

- [ ] **Step 2: Run — FAIL**

Run: `python3 -m pytest tests/test_resolver_prevention.py -v`
Expected: FAIL (`_composite_match` / `has_strong_identity` not defined; `MemberFact` has no `zip_code`)

- [ ] **Step 3: Implement**

First add optional corroborating fields to `MemberFact` in `app/commission/member_fact.py` (additive, defaults None):

```python
    zip_code: Optional[str] = None
    phone: Optional[str] = None
```

Then in `app/commission/resolver.py`:

```python
def _composite_match(fact, agency_id):
    """Auto-match tier: name + DOB + at least one corroborating field (zip/phone).
    Name+DOB alone is NOT enough. Returns (customer, 'composite') or (None, None)."""
    fn = (fact.first_name or "").strip().lower()
    ln = (fact.last_name or "").strip().lower()
    if not fn or not ln or not fact.dob:
        return None, None
    corrob = []
    if getattr(fact, "zip_code", None):
        corrob_zip = fact.zip_code.strip()
    else:
        corrob_zip = None
    phone = (getattr(fact, "phone", None) or "").strip() or None
    if not corrob_zip and not phone:
        return None, None      # name+dob only → not enough
    with db.session.no_autoflush:
        q = (Customer.query.filter(
                Customer.agency_id == agency_id,
                db.func.lower(Customer.first_name) == fn,
                db.func.lower(Customer.last_name) == ln,
                Customer.dob == fact.dob))
        if corrob_zip:
            q = q.filter(Customer.zip_code == corrob_zip)
        if phone:
            q = q.filter(Customer.phone_primary == phone)
        c = q.first()
    return (c, "composite") if c else (None, None)


def has_strong_identity(fact, agency_id=None):
    """True if the fact carries an MBI, a carrier_member_id, or (when agency_id given)
    a composite match exists. Used by prevention to decide create-vs-queue."""
    if (fact.mbi or "").strip() or (fact.carrier_member_id or "").strip():
        return True
    if agency_id is not None:
        c, _ = _composite_match(fact, agency_id)
        return c is not None
    return False
```

Now change the **no-match tail** of `resolve_customer` (steps 3 & 4, lines ~330-357). Replace the unconditional stub creation with the §6 boundary:

```python
    # 3. Composite auto-match (name+DOB+corroborating field) — adopt, no queue.
    cand, conf = _composite_match(fact, agency_id)
    if cand is not None:
        result.customer = cand
        result.policy = _attach_policy(fact, cand, agency_id, agent_id)
        result.created_policy = True
        result.match_path = "composite"
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result, source)
        return result

    # 4. Name+DOB-only near-match → suggest-link (stub + MatchSuggestion for human confirm).
    candidate, confidence = _find_name_dob_match(fact, agency_id)
    if candidate is not None:
        customer = _create_stub(fact, agency_id, agent_id, source)
        result.customer = customer; result.created_customer = True
        result.policy = _attach_policy(fact, customer, agency_id, agent_id)
        result.created_policy = True
        result.match_path = "suggest_link"
        _enqueue_suggestion(fact, customer, candidate, confidence, agency_id, result)
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result, source)
        return result

    # 5. No candidate. §6 boundary: strong identity → create (legit new-to-Medicare);
    #    weak identity → enqueue a needs-match item, NO phantom policy.
    if has_strong_identity(fact):
        customer = _create_stub(fact, agency_id, agent_id, source)
        result.customer = customer; result.created_customer = True
        result.policy = _attach_policy(fact, customer, agency_id, agent_id)
        result.created_policy = True
        result.match_path = "new_strong"
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result, source)
        return result

    # weak identity → no policy; enqueue with full info for the hub
    _enqueue_suggestion(fact, None, None, "weak_identity", agency_id, result)
    result.match_path = "needs_identity"
    return result
```

> Implementer: `_enqueue_suggestion` **currently does `stub_customer.id` and `candidate.id` directly** (verified) — it WILL crash on `None`. You MUST make it NULL-tolerant: change those to `stub_customer.id if stub_customer else None` and `candidate.id if candidate else None`. The `stub_customer_id`/`suggested_customer_id` columns are already nullable (verified — no migration). Also fold the line item's amount + writing agent into `source_member_fact_json` so the hub row shows full attribution info. Add a focused test asserting a `(None, None)` enqueue stores a row with NULL stub/suggested + the fact JSON.

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_resolver_prevention.py -v`

- [ ] **Step 5: Regression run**

Run: `python3 -m pytest tests/ -k "resolver or commission or ledger or upload" -q`
Expected: PASS (the resolver tail change is behavior-significant — confirm existing resolver tests still pass; if a test asserted "always creates a stub on no-match", update it to the new strong-vs-weak behavior and note why)

- [ ] **Step 6: Commit**

```bash
git add app/commission/resolver.py app/commission/member_fact.py tests/test_resolver_prevention.py
git commit -m "feat(resolver): corroborated composite match + strong-vs-weak create boundary (prevention)"
```

---

## Task 3: `app/identity.py` — the cleanup orchestrator

**Files:**
- Create: `app/identity.py`
- Test: `tests/test_identity.py`

**Interfaces:**
- Consumes: resolver matchers (Task 1, 2), `CommissionLineItem`, `Policy`, `Customer`.
- Produces:
  - `resolve_payment_identity(line_item, agency_id) -> dict` — applies MBI → carrier_member_id → composite; returns `{"action": "linked"|"queued", "customer_id": int|None, "tier": str}`. On link, sets `line_item.customer_id`. On a `uhc::%` stub policy whose payment now links, signals the caller to delete the stub (`"delete_stub_policy_id": id|None`).
  - `recover_policy_name(policy, agency_id) -> dict` — ledger-first name fill; returns `{"action": "filled"|"queued", "source": str}`; never overwrites an existing name or a manually_edited customer.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_identity.py
import pytest
from app.extensions import db
from app.models import (Agency, User, Customer, Policy, CommissionStatement,
                        CommissionLineItem)
from app.identity import resolve_payment_identity, recover_policy_name

@pytest.fixture
def fixt(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        cust = Customer(agency_id=ag.id, first_name="Jane", last_name="Doe",
                        full_name="Jane Doe", primary_agent_id=u.id); db.session.add(cust); db.session.flush()
        pol = Policy(agency_id=ag.id, carrier="BCBS", member_id="112850623", status="active",
                     customer_id=cust.id, agent_id=u.id, first_name="Jane", last_name="Doe")
        db.session.add(pol); db.session.flush()
        st = CommissionStatement(carrier="BCBS", period_label="May 2026", agency_id=ag.id)
        db.session.add(st); db.session.flush()
        li = CommissionLineItem(agency_id=ag.id, statement_id=st.id, carrier="BCBS",
            period_label="May 2026", source_ref="bcbs::x::1", raw_amount=10.0,
            split_rate=0.55, classification="agent_commission",
            carrier_member_id="112850623", member_name="DOE, JANE")
        db.session.add(li); db.session.flush()
        # a no-name policy whose line item carries the name
        np = Policy(agency_id=ag.id, carrier="UHC", member_id="NG999", status="active",
                    customer_id=cust.id, agent_id=u.id)  # blank name
        db.session.add(np); db.session.flush()
        nli = CommissionLineItem(agency_id=ag.id, statement_id=st.id, carrier="UHC",
            period_label="May 2026", source_ref="uhc::x::9", raw_amount=5.0, split_rate=0.55,
            classification="agent_commission", carrier_member_id="NG999",
            member_name="SMITH, ROBERT"); db.session.add(nli)
        db.session.commit()
        yield ag.id, li.id, cust.id, np.id

def test_payment_links_by_carrier_member_id(fixt, app):
    ag, li_id, cid, np_id = fixt
    with app.app_context():
        li = db.session.get(CommissionLineItem, li_id)
        r = resolve_payment_identity(li, ag)
        assert r["action"] == "linked" and r["customer_id"] == cid and r["tier"] == "carrier_member_id"
        assert li.customer_id == cid

def test_policy_name_recovered_from_ledger(fixt, app):
    ag, li_id, cid, np_id = fixt
    with app.app_context():
        np = db.session.get(Policy, np_id)
        r = recover_policy_name(np, ag)
        assert r["action"] == "filled"
        assert np.last_name == "Smith" and np.first_name == "Robert"
```

- [ ] **Step 2: Run — FAIL**

Run: `python3 -m pytest tests/test_identity.py -v`

- [ ] **Step 3: Implement `app/identity.py`**

```python
"""Identity recovery orchestrator (spec 2026-06-22). The one seam for resolving a
record's identity via the confidence ladder, reusing app.commission.resolver matchers.
Auto-writes only on tier 1-3 (MBI / carrier_member_id / corroborated composite)."""
from app.extensions import db
from app.models import CommissionLineItem, Policy, Customer
from app.commission.member_fact import MemberFact
from app.commission.resolver import (_match_by_mbi, _match_by_carrier_member_id,
                                      _composite_match)


def _fact_from_line_item(li):
    nm = (li.member_name or "").strip()
    first = last = ""
    if "," in nm:
        last, first = [x.strip() for x in nm.split(",", 1)]
    elif nm:
        parts = nm.split()
        first, last = parts[0], (parts[-1] if len(parts) > 1 else "")
    return MemberFact(carrier=li.carrier, full_name=nm, first_name=first, last_name=last,
                      mbi=li.mbi or None, carrier_member_id=li.carrier_member_id or None)


def resolve_payment_identity(line_item, agency_id):
    fact = _fact_from_line_item(line_item)
    cust = _match_by_mbi(fact, agency_id)
    tier = "mbi" if cust else None
    if cust is None:
        cust = _match_by_carrier_member_id(fact, agency_id)
        tier = "carrier_member_id" if cust else None
    if cust is None:
        cust, conf = _composite_match(fact, agency_id)
        tier = "composite" if cust else None
    if cust is None:
        return {"action": "queued", "customer_id": None, "tier": "none",
                "delete_stub_policy_id": None}
    line_item.customer_id = cust.id
    # If this payment spawned a uhc::N stub policy, signal it for deletion.
    stub = (Policy.query
            .filter(Policy.agency_id == agency_id,
                    Policy.member_id == line_item.source_ref).first())
    return {"action": "linked", "customer_id": cust.id, "tier": tier,
            "delete_stub_policy_id": (stub.id if stub and str(stub.member_id).startswith(line_item.carrier.lower()+"::") else None)}


def _titlecase(s):
    return " ".join(w.capitalize() for w in (s or "").split())


def recover_policy_name(policy, agency_id):
    if (policy.first_name or policy.last_name):
        return {"action": "skip", "source": "already named"}
    # ledger-first: a line item carrying this policy's identity + a member_name
    li = (CommissionLineItem.query
          .filter(CommissionLineItem.agency_id == agency_id,
                  CommissionLineItem.member_name.isnot(None),
                  CommissionLineItem.member_name != "")
          .filter((CommissionLineItem.carrier_member_id == policy.member_id) |
                  (CommissionLineItem.mbi == policy.mbi))
          .first())
    if not li:
        return {"action": "queued", "source": "no ledger name"}
    nm = li.member_name.strip()
    if "," in nm:
        last, first = [x.strip() for x in nm.split(",", 1)]
    else:
        parts = nm.split(); first = parts[0] if parts else ""; last = parts[-1] if len(parts) > 1 else ""
    policy.first_name = _titlecase(first); policy.last_name = _titlecase(last)
    policy.full_name = f"{policy.first_name} {policy.last_name}".strip()
    # also fill the customer if blank and not manually edited
    if policy.customer_id:
        c = db.session.get(Customer, policy.customer_id)
        if c and not c.manually_edited and not (c.first_name or c.last_name):
            c.first_name, c.last_name = policy.first_name, policy.last_name
            c.full_name = policy.full_name
    return {"action": "filled", "source": "ledger"}
```

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_identity.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/identity.py tests/test_identity.py
git commit -m "feat(identity): payment + policy-name recovery orchestrator (ladder, ledger-first)"
```

---

## Task 4: `scripts/recover_payment_customer.py` (Link 1 cleanup)

**Files:**
- Create: `scripts/recover_payment_customer.py`

**Interfaces:**
- Consumes: `resolve_payment_identity` (Task 3).
- Produces: dry-run report (linked-by-tier counts + queued count) by default; `--apply` commits link + deletes resolved `uhc::%` stub policies. Idempotent. No unit test (ops script; verified live Task 9).

- [ ] **Step 1: Write the script**

```python
# scripts/recover_payment_customer.py
"""Link 1: re-point NULL-customer commission line items to real customers via the
identity ladder (MBI -> carrier_member_id -> composite). Deletes any uhc::N stub
policy whose payment now links. Dry-run default; --apply commits. Back up DB first.
Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/recover_payment_customer.py [--apply]
"""
import sys
from collections import Counter
from app import create_app
from app.extensions import db
from app.models import CommissionLineItem, Policy
from app.identity import resolve_payment_identity

def main(apply):
    app = create_app()
    with app.app_context():
        rows = (CommissionLineItem.query
                .filter(CommissionLineItem.customer_id.is_(None),
                        CommissionLineItem.classification.in_(["agent_commission", "chargeback"]))
                .all())
        tiers = Counter(); queued = 0; stubs_deleted = 0
        for li in rows:
            r = resolve_payment_identity(li, li.agency_id)
            if r["action"] == "linked":
                tiers[r["tier"]] += 1
                if apply and r["delete_stub_policy_id"]:
                    p = db.session.get(Policy, r["delete_stub_policy_id"])
                    if p:
                        db.session.delete(p); stubs_deleted += 1
            else:
                queued += 1
        if apply:
            db.session.commit()
        print(f"{'APPLIED' if apply else 'DRY-RUN'} — linked {sum(tiers.values())} payments:")
        for t, n in tiers.most_common():
            print(f"  {n:5d}  via {t}")
        print(f"  stub policies deleted: {stubs_deleted}")
        print(f"  queued (weak identity → hub): {queued}")

if __name__ == "__main__":
    main("--apply" in sys.argv)
```

- [ ] **Step 2: Parse-check**

Run: `python3 -c "import ast; ast.parse(open('scripts/recover_payment_customer.py').read()); print('parse ok')"`
Expected: `parse ok`

- [ ] **Step 3: Commit**

```bash
git add scripts/recover_payment_customer.py
git commit -m "feat(scripts): Link-1 payment->customer recovery (carrier_member_id, delete resolved stubs)"
```

---

## Task 5: `scripts/recover_policy_names.py` (Link 2 cleanup)

**Files:**
- Create: `scripts/recover_policy_names.py`

**Interfaces:**
- Consumes: `recover_policy_name` (Task 3).
- Produces: dry-run/`--apply`, idempotent, reports filled vs queued. No unit test (logic tested in Task 3).

- [ ] **Step 1: Write the script**

```python
# scripts/recover_policy_names.py
"""Link 2: recover names for no-name active policies (ledger-first via
recover_policy_name). Dry-run default; --apply commits. Back up DB first.
Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/recover_policy_names.py [--apply]
"""
import sys
from collections import Counter
from sqlalchemy import or_
from app import create_app
from app.extensions import db
from app.models import Policy
from app.identity import recover_policy_name

def main(apply):
    app = create_app()
    with app.app_context():
        rows = (Policy.query.filter(Policy.status == "active",
                or_(Policy.first_name.is_(None), Policy.first_name == ""),
                or_(Policy.last_name.is_(None), Policy.last_name == "")).all())
        out = Counter()
        for p in rows:
            r = recover_policy_name(p, p.agency_id)
            out[r["action"]] += 1
        if apply:
            db.session.commit()
        print(f"{'APPLIED' if apply else 'DRY-RUN'} — {len(rows)} no-name policies:")
        for a, n in out.most_common():
            print(f"  {n:5d}  {a}")

if __name__ == "__main__":
    main("--apply" in sys.argv)
```

- [ ] **Step 2: Parse-check**

Run: `python3 -c "import ast; ast.parse(open('scripts/recover_policy_names.py').read()); print('parse ok')"`
Expected: `parse ok`

- [ ] **Step 3: Commit**

```bash
git add scripts/recover_policy_names.py
git commit -m "feat(scripts): Link-2 no-name policy recovery (ledger-first)"
```

---

## Task 6: `scripts/recover_aor_intervals.py` (Link 4 — the big derivation)

**Files:**
- Create: `scripts/recover_aor_intervals.py`
- Test: `tests/test_aor_derivation.py`

**Interfaces:**
- Consumes: `Policy`, `Customer`, `CustomerAorHistory`, `_aor_close_date` semantics (carrier dates authoritative, BCBS end=None).
- Produces: `derive_interval_for_customer(customer, agency_id) -> dict` `{"action": "derived"|"queued"|"skip", ...}` + the script. Idempotent (skip if an equivalent interval exists). Tested (it writes ownership history for ~2,353 records — TDD this one).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_aor_derivation.py
import pytest
from datetime import date
from app.extensions import db
from app.models import Agency, User, Customer, Policy, CustomerAorHistory
from scripts.recover_aor_intervals import derive_interval_for_customer

@pytest.fixture
def fixt(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=ag.id, full_name="Jane Doe", primary_agent_id=u.id)
        db.session.add(c); db.session.flush()
        p = Policy(agency_id=ag.id, carrier="UHC", member_id="m1", status="active",
                   customer_id=c.id, agent_id=u.id, effective_date=date(2025,1,1),
                   term_date=None); db.session.add(p)
        # BCBS customer with a term_date (should derive end=None)
        c2 = Customer(agency_id=ag.id, full_name="Bob Roe", primary_agent_id=u.id)
        db.session.add(c2); db.session.flush()
        p2 = Policy(agency_id=ag.id, carrier="BCBS", member_id="m2", status="active",
                    customer_id=c2.id, agent_id=u.id, effective_date=date(2025,3,1),
                    term_date=date(2026,2,28)); db.session.add(p2)
        # customer whose policy lacks effective_date → should queue
        c3 = Customer(agency_id=ag.id, full_name="No Facts", primary_agent_id=u.id)
        db.session.add(c3); db.session.flush()
        p3 = Policy(agency_id=ag.id, carrier="UHC", member_id="m3", status="active",
                    customer_id=c3.id, agent_id=u.id, effective_date=None); db.session.add(p3)
        db.session.commit()
        yield ag.id, c.id, u.id, c2.id, c3.id

def test_derives_interval_from_policy(fixt, app):
    ag, cid, uid, c2, c3 = fixt
    with app.app_context():
        c = db.session.get(Customer, cid)
        r = derive_interval_for_customer(c, ag)
        assert r["action"] == "derived"
        h = CustomerAorHistory.query.filter_by(customer_id=cid).first()
        assert h.carrier == "UHC" and h.effective_date.year == 2025 and h.agent_id == uid

def test_bcbs_end_date_is_none(fixt, app):
    ag, cid, uid, c2, c3 = fixt
    with app.app_context():
        derive_interval_for_customer(db.session.get(Customer, c2), ag)
        h = CustomerAorHistory.query.filter_by(customer_id=c2).first()
        assert h.end_date is None  # BCBS term_date is a renewal, not a termination

def test_no_facts_queues(fixt, app):
    ag, cid, uid, c2, c3 = fixt
    with app.app_context():
        r = derive_interval_for_customer(db.session.get(Customer, c3), ag)
        assert r["action"] == "queued"

def test_idempotent(fixt, app):
    ag, cid, uid, c2, c3 = fixt
    with app.app_context():
        c = db.session.get(Customer, cid)
        derive_interval_for_customer(c, ag); db.session.commit()
        r2 = derive_interval_for_customer(c, ag)
        assert r2["action"] == "skip"
        assert CustomerAorHistory.query.filter_by(customer_id=cid).count() == 1
```

- [ ] **Step 2: Run — FAIL**

Run: `python3 -m pytest tests/test_aor_derivation.py -v`

- [ ] **Step 3: Implement `scripts/recover_aor_intervals.py`**

```python
"""Link 4: derive a CustomerAorHistory interval for agent'd customers that have none,
from their policy facts (carrier-provided effective/term dates are authoritative;
BCBS end_date always None). Dry-run default; --apply. Idempotent. Back up DB first.
Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/recover_aor_intervals.py [--apply]
"""
import sys
from collections import Counter
from app import create_app
from app.extensions import db
from app.models import Customer, Policy, CustomerAorHistory


def derive_interval_for_customer(customer, agency_id):
    if customer.primary_agent_id is None:
        return {"action": "skip", "why": "no agent"}
    # pick the customer's active policy with the facts we need
    pol = (Policy.query.filter_by(customer_id=customer.id, agency_id=agency_id, status="active")
           .filter(Policy.effective_date.isnot(None), Policy.carrier.isnot(None))
           .order_by(Policy.effective_date.asc()).first())
    if pol is None:
        return {"action": "queued", "why": "no policy facts"}
    end = None if pol.carrier == "BCBS" else pol.term_date
    exists = CustomerAorHistory.query.filter_by(
        customer_id=customer.id, carrier=pol.carrier,
        effective_date=pol.effective_date).first()
    if exists:
        return {"action": "skip", "why": "interval exists"}
    db.session.add(CustomerAorHistory(
        agency_id=agency_id, customer_id=customer.id, agent_id=customer.primary_agent_id,
        carrier=pol.carrier, effective_date=pol.effective_date, end_date=end,
        source="derive_backfill"))
    return {"action": "derived", "carrier": pol.carrier}


def main(apply):
    app = create_app()
    with app.app_context():
        with_agent = Customer.query.filter(Customer.primary_agent_id.isnot(None))
        have_iv = db.session.query(CustomerAorHistory.customer_id).distinct()
        rows = with_agent.filter(~Customer.id.in_(have_iv)).all()
        out = Counter()
        for c in rows:
            out[derive_interval_for_customer(c, c.agency_id)["action"]] += 1
        if apply:
            db.session.commit()
        print(f"{'APPLIED' if apply else 'DRY-RUN'} — {len(rows)} customers w/ agent but no interval:")
        for a, n in out.most_common():
            print(f"  {n:5d}  {a}")


if __name__ == "__main__":
    main("--apply" in sys.argv)
```

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_aor_derivation.py -v`

- [ ] **Step 5: Commit**

```bash
git add scripts/recover_aor_intervals.py tests/test_aor_derivation.py
git commit -m "feat(scripts): Link-4 AOR interval derivation from policy facts (BCBS end=None, idempotent)"
```

---

## Task 7: Needs Identity hub — broaden `/customers/unassigned`

**Files:**
- Modify: `app/customers.py` (`customers_unassigned` → 4-category hub; add `_needs_match_items`, `_needs_name_items`, `_needs_interval_items`)
- Modify: `app/templates/customers_unassigned.html` (category filter/tabs + per-category rows)
- Test: `tests/test_needs_identity_hub.py`

**Interfaces:**
- Consumes: `Customer`, `Policy`, `CommissionLineItem`, `MatchSuggestion`, `CustomerAorHistory`.
- Produces: the page renders 4 categories (`agent`, `match`, `name`, `interval`) chosen by `?cat=`; default shows counts for all. Reuses `_suggested_agent_id` + `customer_set_agent`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_needs_identity_hub.py
import pytest
from app.extensions import db
from app.models import Agency, User, Customer

def test_hub_categories_render(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        admin = User(name="AJ", email="admin@foundersinsuranceagency.com",
                     agency_id=ag.id, is_admin=True); db.session.add(admin)
        db.session.add(Customer(agency_id=ag.id, full_name="No Agent", primary_agent_id=None))
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as s:
            s["_user_id"] = str(admin.id)
        # default page lists categories + counts; needs-agent shows the unassigned customer
        resp = client.get("/customers/unassigned?cat=agent")
        assert resp.status_code == 200
        assert b"No Agent" in resp.data
```

> Implementer: match the existing login/test pattern in the repo's customer tests for authenticating the test client (grep `tests/` for `_user_id` or an existing admin-client fixture; reuse it).

- [ ] **Step 2: Run — FAIL** (route still single-category or auth differs)

Run: `python3 -m pytest tests/test_needs_identity_hub.py -v`

- [ ] **Step 3: Implement** — broaden `customers_unassigned` in `app/customers.py`:

Keep the existing "needs agent" query as `cat=agent` (default). Add three category builders + a counts summary, selected by `request.args.get("cat", "agent")`:

```python
@customers_bp.route("/customers/unassigned")
@login_required
def customers_unassigned():
    """Needs Identity hub: every record lacking a known identity/origin, in one place.
    Categories: agent | match | name | interval. (Repurposed from the old
    unassigned-only view per the 2026-06-22 identity-recovery spec.)"""
    if not current_user.is_admin:
        abort(403)
    aid = current_user.agency_id
    cat = request.args.get("cat", "agent")
    agents = (User.query.filter_by(agency_id=aid)
              .filter(User.email != "admin@foundersinsuranceagency.com")
              .order_by(User.name).all())

    counts = {
        "agent": Customer.query.filter_by(agency_id=aid, primary_agent_id=None).count(),
        "match": CommissionLineItem.query.filter_by(agency_id=aid, customer_id=None)
                 .filter(CommissionLineItem.classification.in_(["agent_commission", "chargeback"])).count(),
        "name": Policy.query.filter(Policy.agency_id == aid, Policy.status == "active",
                 db.or_(Policy.first_name.is_(None), Policy.first_name == ""),
                 db.or_(Policy.last_name.is_(None), Policy.last_name == "")).count(),
        "interval": _needs_interval_count(aid),
    }

    items = []
    if cat == "agent":
        rows = (Customer.query.filter_by(agency_id=aid, primary_agent_id=None)
                .order_by(Customer.full_name).all())
        for c in rows:
            sid, basis = _suggested_agent_id(c)
            sname = next((a.display_name for a in agents if a.id == sid), None)
            items.append({"c": c, "suggested_id": sid, "suggested_name": sname, "basis": basis})
    elif cat == "match":
        items = _needs_match_items(aid)
    elif cat == "name":
        items = _needs_name_items(aid)
    elif cat == "interval":
        items = _needs_interval_items(aid)

    return render_template("customers_unassigned.html",
        items=items, agents=agents, cat=cat, counts=counts)
```

Add the helper builders (each returns lightweight dicts showing what's known + a suggestion). Keep them small and agency-scoped. `_needs_interval_count`/`_needs_interval_items` mirror the Task-6 query (agent'd customers with no `CustomerAorHistory`). `_needs_match_items` lists the NULL-customer line items with carrier/name/amount/period/writing-agent + a `resolve_payment_identity` suggestion.

- [ ] **Step 4: Update the template** `customers_unassigned.html`: a category tab bar (`agent | match | name | interval`, each with its count badge from `counts`, linking `?cat=`), and a per-category table. Keep the existing agent-assign form for `cat=agent`. For `match`/`name`/`interval`, show the known fields + the relevant one-click action (confirm match / it auto-recovers / assign agent). Material 3 tokens; `var(--ivory)` for text.

- [ ] **Step 5: Run — PASS**

Run: `python3 -m pytest tests/test_needs_identity_hub.py -v`

- [ ] **Step 6: Commit**

```bash
git add app/customers.py app/templates/customers_unassigned.html tests/test_needs_identity_hub.py
git commit -m "feat(hub): broaden /customers/unassigned into the 4-category Needs Identity hub"
```

---

## Task 8: metrics excludes stub/queued records from book counts

**Files:**
- Modify: `app/metrics.py` (`_policy_q` — exclude `uhc::%` stub policies)
- Test: `tests/test_metrics_excludes_stubs.py`

**Interfaces:**
- Consumes: `Policy`.
- Produces: `_policy_q(scope)` additionally filters out stub policies (`member_id LIKE 'uhc::%'`), so a placeholder never inflates a book/agent/carrier count.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics_excludes_stubs.py
import pytest
from app.extensions import db
from app.models import Agency, User, Policy
from app.metrics import Scope, policy_count

def test_stub_policies_excluded(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        db.session.add(Policy(agency_id=ag.id, carrier="UHC", member_id="REAL1",
                              status="active", agent_id=u.id))
        db.session.add(Policy(agency_id=ag.id, carrier="UHC", member_id="uhc::0::5",
                              status="active", agent_id=u.id))  # stub
        db.session.commit()
        assert policy_count(Scope(agency_id=ag.id)) == 1  # stub excluded
```

- [ ] **Step 2: Run — FAIL** (count is 2)

Run: `python3 -m pytest tests/test_metrics_excludes_stubs.py -v`

- [ ] **Step 3: Implement** — in `app/metrics.py` `_policy_q`:

```python
def _policy_q(scope):
    q = (Policy.query.filter_by(status="active", agency_id=scope.agency_id)
         .filter(~Policy.member_id.like("%::0::%")))  # exclude commission stub placeholders
    if scope.agent_id is not None:
        q = q.filter(Policy.agent_id == scope.agent_id)
    if scope.carrier:
        q = q.filter(Policy.carrier == scope.carrier)
    return q
```

- [ ] **Step 4: Run — PASS** + guard test stays green

Run: `python3 -m pytest tests/test_metrics_excludes_stubs.py tests/test_metrics_guard.py tests/test_metrics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/metrics.py tests/test_metrics_excludes_stubs.py
git commit -m "feat(metrics): exclude commission stub placeholders from book counts"
```

---

## Task 9: full-suite + live Postgres cleanup & verification

**Files:** none (verification + rollout)

- [ ] **Step 1: Full suite green**

Run: `python3 -m pytest -q`
Expected: PASS (≈312 + new tests; guard green)

- [ ] **Step 2: Merge to main + push** (after final review per the SDD skill)

- [ ] **Step 3: Deploy + back up DB on VPS**

```bash
ssh … 'cd /var/www/founders-portal && git pull && ./venv/bin/pip install -r requirements.txt && systemctl restart founders-portal'
ssh … 'cd /var/www/founders-portal && PGPASSWORD=<from .env> pg_dump -U founders_user -h localhost founders_portal > /root/founders_pre_identity_$(date +%F_%H%M).sql'
```

- [ ] **Step 4: Run the three cleanups dry-run → eyeball → apply (in order)**

```bash
# Link 1 — payments
ssh … 'cd /var/www/founders-portal && PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/recover_payment_customer.py'        # dry-run
ssh … 'cd /var/www/founders-portal && PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/recover_payment_customer.py --apply'
# Link 2 — names
ssh … 'cd /var/www/founders-portal && PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/recover_policy_names.py'
ssh … 'cd /var/www/founders-portal && PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/recover_policy_names.py --apply'
# Link 4 — AOR intervals (the big one — eyeball the dry-run carefully before apply)
ssh … 'cd /var/www/founders-portal && PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/recover_aor_intervals.py'
ssh … 'cd /var/www/founders-portal && PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/recover_aor_intervals.py --apply'
```

- [ ] **Step 5: Verify the four links on live Postgres**

Confirm: NULL-customer agent/chargeback line items ≈ 0 (remainder queued); no-name active policies ≈ 0; `uhc::%` stub policies deleted (and **Tim's UHC ≈ 262**); agent'd customers without an interval ≈ 0; the four hub categories show the residual counts; the metrics guard + book invariant (Σ agents = total, stubs excluded) hold. Re-run each script dry-run → expect 0 new (idempotent).

- [ ] **Step 6: Update docs (Session Protocol)**

Update `BACKLOG.md` (mark identity recovery shipped; note residual hub counts), `CLAUDE.md` START HERE, and the spec Status. Commit.

---

## Self-Review

**Spec coverage:**
- §1 four links → Task 1+4 (Link 1), Task 3+5 (Link 2), existing+hub (Link 3), Task 6 (Link 4). ✓
- §2 ladder (MBI→carrier_member_id→composite; name-alone never writes) → Task 1, 2, 3. ✓
- §3 ledger-first name recovery → Task 3 (`recover_policy_name`) + Task 5. ✓
- §4 AOR derivation, carrier dates authoritative, BCBS end=None → Task 6. ✓
- §5 hub repurpose (no new page) → Task 7. ✓
- §6 prevention (strong→create, weak→queue, no phantom) → Task 2 (resolver tail). ✓
- §7 components → identity.py (T3), 3 scripts (T4/5/6), hub (T7), metrics filter (T8). ✓
- §8 cleanup execution → Task 9. §9 testing → TDD on identity.py (T3) + AOR (T6) + guard stays green (T8). ✓
- §10 acceptance → Task 9 Step 5 verifies all four. ✓

**Placeholder scan:** ops-script outputs and the hub helper builders (`_needs_match_items` etc.) are described with their exact queries inline in Task 7 Step 3 prose + the counts dict; implementer fills the small list-builders following the shown `counts` queries. No TBD/TODO. ✓

**Type consistency:** `resolve_payment_identity` returns `{action,customer_id,tier,delete_stub_policy_id}` (T3) consumed in T4. `recover_policy_name` returns `{action,source}` (T3) consumed in T5. `derive_interval_for_customer` returns `{action,...}` (T6) consumed in its script + hub. `_match_by_carrier_member_id`/`_composite_match`/`has_strong_identity` signatures consistent across T1/T2/T3. ✓

**Migration note:** No schema migration is strictly required — the hub reads existing tables, stubs are excluded by member_id pattern, `MatchSuggestion` already exists. The MemberFact field additions (T2) are dataclass-only. If `_enqueue_suggestion` needs to allow NULL stub/candidate (T2 note), confirm the columns are already nullable (they are per models.py) — no migration.
