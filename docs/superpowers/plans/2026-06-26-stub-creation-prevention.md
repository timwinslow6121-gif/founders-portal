# Stub-Creation Prevention (Commission = Match-or-Park) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop commission import from creating customers — it matches a payment to an existing customer by unique carrier ID (MBI / carrier_member_id) and attaches it, or holds (parks) the whole payment for human/BOB resolution; BOB remains the only door that creates identity.

**Architecture:** A single `source`-gated branch in the shared `resolve_customer()` makes the commission path an ID-only ladder (crosswalk → MBI → carrier_member_id → park). Parked payments are recorded but unattached and unpaid; a BOB import that later supplies a matching ID auto-sweeps them onto the customer. The ~7 commission name parsers route through the existing `normalize_person_name()`. Unknown-carrier uploads are blocked. Two integrity invariants prove "no new commission stubs" and "no payment lost."

**Tech Stack:** Python 3.10, Flask, Flask-SQLAlchemy, pytest (SQLite in-memory for unit tests; PostgreSQL on VPS for final verify).

## Global Constraints

- **Commission import NEVER creates or edits a Customer.** `_create_stub` must be unreachable when `source == "commission_import"`. Verbatim spec rule.
- **Auto-attach ONLY via a 100%-unique carrier ID** (MBI / humana_id / carrier_member_id, carrier-scoped). NEVER match on name for auto-attach. No ID match → park.
- **Park HOLDS THE WHOLE PAYMENT** — no payout to agent OR agency until customer AND pay-split are both confident. A parked payment is recorded + counted, paid to nobody.
- **NON_CUSTOMER rows (HRA bonuses etc.) are unchanged** — they already pay an agent with `customer=None` and are handled before `resolve_customer` in `ingest.py`. Do not touch that path.
- **BOB path (`source="bob" / source != "commission_import"`) keeps full creation rights** — its ladder is untouched.
- **8 carriers:** UHC, Humana, Devoted, BCBS, Aetna, Healthspring, Medico/Wellable, GTL. `NORMALIZERS` covers 6 (no Medico/Wellable, no GTL). Unknown/unsupported carrier upload → block with a clear reason, import nothing.
- **No model change, no migration.** A parked payment is `PolicyPayment(policy_id=NULL, match_confidence='unmatched')` — `PolicyPayment` has NO `customer_id` column (linkage is via `policy_id → Policy.customer_id`); columns already nullable.
- **Tests run:** `python3 -m pytest -q` locally (SQLite). Frequent commits, one deliverable per task.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `app/commission/resolver.py` | Identity resolution seam | Add `source`-gated commission branch `_resolve_commission_match_or_park()`; existing BOB ladder untouched. |
| `app/commission/normalizers.py` | Carrier file → MemberFact | Route the ~7 name constructions through `normalize_person_name`. |
| `app/commission/routes.py` | `commission_upload()` entry | Block upload when detected carrier ∉ `NORMALIZERS`. |
| `app/upload.py` | BOB upsert | After a BOB customer's IDs are known, call `_sweep_parked_payments(customer)`. |
| `app/commission/payments.py` | Parked-payment sweep + age helper | Add `sweep_parked_payments(customer, agency_id)` + `parked_payments_older_than(days, agency_id)`. |
| `app/integrity.py` | Radar invariants | Add `commission_import_stubs` (ratchet from 571) + `statement_balance_complete` (nothing-lost). |
| `app/names.py` | Name normalizer | **No change** — reuse `normalize_person_name`. |
| `tests/test_resolver_prevention.py` | Resolver branch tests | Invert the `new_strong` stub test → park; add ID-attach + park tests. |
| `tests/test_commission_name_normalization.py` | Name normalization | New file. |
| `tests/test_parked_payment_sweep.py` | Auto-sweep | New file. |
| `tests/test_unknown_carrier_block.py` | Upload guard | New file. |
| `tests/test_integrity_data_invariants.py` | New invariants | Add 2 invariant tests. |

**Existing fixtures (conftest.py):** `app`, `db_session`, `agency`, `agent_user`. `agency.id` is the agency_id; `agent_user.id` is a valid agent. Tests use `with app.app_context():`.

---

### Task 1: Commission path becomes ID-only match-or-park (the core change)

Today `resolve_customer(..., source="commission_import")` runs the FULL ladder and, on a strong-identity no-match, creates a stub (`match_path="new_strong"`). This task carves out a commission-only branch that ends in **park** (no stub, ever) while leaving BOB untouched.

**Files:**
- Modify: `app/commission/resolver.py` — add `_resolve_commission_match_or_park()`, branch at the top of `resolve_customer()`.
- Test: `tests/test_resolver_prevention.py` (modify existing + add).

**Interfaces:**
- Consumes: `MemberFact` (`app/commission/member_fact.py`), `ResolveResult` (resolver.py), existing `_crosswalk(fact, agency_id)`, `_match_by_mbi(fact, agency_id)`, `_match_by_carrier_member_id(fact, agency_id)`, `_attach_policy(fact, customer, agency_id, agent_id)`, `_apply_rapid_disenroll`, `_apply_carrier_switch`, `_open_aor_interval`, `_enqueue_suggestion`.
- Produces: `resolve_customer(fact, *, agency_id, agent_id, batch_id=None, source)` unchanged signature; for `source == "commission_import"` it now returns `match_path ∈ {crosswalk, mbi, carrier_member_id, parked}` and NEVER `new_strong`/`stub`/`suggest_link`. `result.created_customer` is always `False` on this path. A parked result has `customer=None, policy=None, match_path="parked"`.

- [ ] **Step 1: Invert the existing strong-identity stub test to expect park**

Replace the body of `test_strong_identity_no_match_creates_new_customer` in `tests/test_resolver_prevention.py` (rename it for clarity):

```python
def test_commission_strong_identity_no_match_parks_no_stub(db_session, app):
    """Commission path: a row with an MBI that matches NO customer must PARK —
    no stub created (the spec's 'commission never creates' rule). This replaces
    the old new_strong-creates-a-stub behavior."""
    from app.commission.resolver import resolve_customer
    from app.commission.member_fact import MemberFact, RowClass
    from app.models import Customer, Policy, MatchSuggestion
    with app.app_context():
        ag = _agency()
        before = Customer.query.count()
        fact = MemberFact(carrier="UHC", full_name="Bob Jones", first_name="Bob",
                          last_name="Jones", mbi="9XX9XX9XX99",
                          row_class=RowClass.ENROLLMENT, amount=100.0,
                          effective_date=date(2026, 6, 1),
                          source_ref="uhc::x::Sheet1::1")
        r = resolve_customer(fact, agency_id=ag, agent_id=1, source="commission_import")
        assert r.match_path == "parked"
        assert r.customer is None
        assert r.policy is None
        assert r.created_customer is False
        assert Customer.query.count() == before          # NO stub created
        assert Policy.query.count() == 0                 # NO phantom policy
        # a needs-identity item is enqueued so the parked payment is visible
        assert MatchSuggestion.query.count() == 1
```

(Use the same `_agency()` / imports style already present at the top of the file. If a strong-identity creation test elsewhere asserts `new_strong` on the commission path, update it too — `grep -n "new_strong" tests/`.)

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_resolver_prevention.py::test_commission_strong_identity_no_match_parks_no_stub -v`
Expected: FAIL — current code returns `match_path="new_strong"` and creates a Customer.

- [ ] **Step 3: Add the commission branch in `resolver.py`**

Add this function ABOVE `resolve_customer`:

```python
def _resolve_commission_match_or_park(fact: MemberFact, agency_id: int,
                                      agent_id, batch_id, source: str) -> ResolveResult:
    """Commission path: attach ONLY by a unique carrier ID, else PARK.
    Never creates a customer, never matches on name. See
    docs/superpowers/specs/2026-06-26-stub-creation-prevention-design.md."""
    result = ResolveResult()

    def _attach(customer, match_path):
        result.customer = customer
        existing = _crosswalk(fact, agency_id)
        if existing is not None:
            existing.customer_id = existing.customer_id or customer.id
            result.policy = existing
        else:
            result.policy = _attach_policy(fact, customer, agency_id, agent_id)
            result.created_policy = True
        result.match_path = match_path
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, customer, agency_id, agent_id, batch_id, result, source)
        return result

    # 1. crosswalk — deterministic re-link to an existing policy's customer.
    policy = _crosswalk(fact, agency_id)
    if policy is not None and policy.customer_id:
        result.policy = policy
        result.customer = Customer.query.get(policy.customer_id)
        result.match_path = "crosswalk"
        _apply_rapid_disenroll(policy, fact, result)
        _apply_carrier_switch(fact, result.customer, policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result, source)
        return result

    # 2. MBI / humana_id
    customer = _match_by_mbi(fact, agency_id)
    if customer is not None:
        return _attach(customer, "mbi")

    # 2b. carrier_member_id (a real carrier id is as good as an MBI)
    customer = _match_by_carrier_member_id(fact, agency_id)
    if customer is not None:
        return _attach(customer, "carrier_member_id")

    # 3. No unique-ID match → PARK. No customer, no policy, no AOR, no payout.
    #    Enqueue a needs-identity item so the held payment is visible in the hub.
    _enqueue_suggestion(fact, None, None, "parked", agency_id, result)
    result.match_path = "parked"
    return result
```

Then add the gate as the FIRST lines of `resolve_customer` (right after `result = ResolveResult()`):

```python
    if source == "commission_import":
        return _resolve_commission_match_or_park(fact, agency_id, agent_id, batch_id, source)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_resolver_prevention.py::test_commission_strong_identity_no_match_parks_no_stub -v`
Expected: PASS.

- [ ] **Step 5: Add ID-attach tests (prove matching still works, no stub)**

Append to `tests/test_resolver_prevention.py`:

```python
def test_commission_mbi_match_attaches_no_stub(db_session, app):
    from app.commission.resolver import resolve_customer
    from app.commission.member_fact import MemberFact, RowClass
    from app.models import Customer, Policy
    with app.app_context():
        ag = _agency()
        c = Customer(agency_id=ag, first_name="John", last_name="Connelly",
                     full_name="John Connelly", mbi="4RH5X85DC65")
        from app.extensions import db
        db.session.add(c); db.session.flush()
        before = Customer.query.count()
        fact = MemberFact(carrier="UHC", full_name="CONNELLY, JOHN", first_name="John",
                          last_name="Connelly", mbi="4RH5X85DC65",
                          row_class=RowClass.RENEWAL, amount=28.92,
                          effective_date=date(2026, 6, 1), source_ref="uhc::x::Sheet1::2")
        r = resolve_customer(fact, agency_id=ag, agent_id=1, source="commission_import")
        assert r.match_path == "mbi"
        assert r.customer.id == c.id
        assert r.created_customer is False
        assert Customer.query.count() == before    # attached, NOT a new stub


def test_commission_carrier_member_id_match_attaches(db_session, app):
    from app.commission.resolver import resolve_customer
    from app.commission.member_fact import MemberFact, RowClass
    from app.models import Customer, Policy
    from app.extensions import db
    with app.app_context():
        ag = _agency()
        c = Customer(agency_id=ag, first_name="Jane", last_name="Doe", full_name="Jane Doe")
        db.session.add(c); db.session.flush()
        p = Policy(agency_id=ag, carrier="BCBS", member_id="BC12345",
                   status="active", customer_id=c.id)
        db.session.add(p); db.session.flush()
        fact = MemberFact(carrier="BCBS", full_name="DOE, JANE", first_name="Jane",
                          last_name="Doe", carrier_member_id="BC12345",
                          row_class=RowClass.RENEWAL, amount=20.0,
                          effective_date=date(2026, 6, 1), source_ref="bcbs::x::Sheet1::3")
        r = resolve_customer(fact, agency_id=ag, agent_id=1, source="commission_import")
        assert r.match_path == "carrier_member_id"
        assert r.customer.id == c.id
        assert r.created_customer is False
```

- [ ] **Step 6: Run the full prevention suite**

Run: `python3 -m pytest tests/test_resolver_prevention.py tests/test_resolver_carrier_member_id.py tests/test_commission_resolver.py -q`
Expected: PASS (fix any old test that asserted commission-path stub creation — those are now wrong by design; update them to expect `parked`).

- [ ] **Step 7: Commit**

```bash
git add app/commission/resolver.py tests/test_resolver_prevention.py
git commit -m "feat: commission resolver is ID-only match-or-park (never creates customers)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: ingest.py — a parked row writes a held payment, no payout

`write_payment_from_fact` already writes a `PolicyPayment` with `policy=None` when the resolver parked the row (`res.policy is None`). Confirm a parked payment is recorded as held (no agent/agency payout) and counted, and that the ingest result counts it as parked, not as a stub.

**Files:**
- Modify: `app/commission/ingest.py:154-168` (the resolve+write block) and `IngestResult`.
- Test: `tests/test_commission_ingest.py` (add).

**Interfaces:**
- Consumes: `resolve_customer` (Task 1), `write_payment_from_fact(fact, statement, policy, agency_id, agent_id)`.
- Produces: `IngestResult` gains `parked_payments: int`. A parked row → `PolicyPayment(policy_id=NULL, match_confidence='unmatched')` (no `customer_id` column), counted in `payments_written` AND `parked_payments`.

- [ ] **Step 1: Write the failing test**

```python
def test_parked_row_writes_held_unattached_payment(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import PolicyPayment, Customer
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission import ingest as ingest_mod
    with app.app_context():
        stmt = _statement(db, agency, carrier="UHC")
        before = Customer.query.count()
        fact = MemberFact(carrier="UHC", full_name="Bob Jones", first_name="Bob",
                          last_name="Jones", mbi="9XX9XX9XX99",
                          row_class=RowClass.ENROLLMENT, amount=100.0,
                          effective_date=date(2026, 6, 1), source_ref="uhc::x::Sheet1::9")
        res = ingest_mod.resolve_customer(fact, agency_id=agency.id,
                                          agent_id=agent_user.id, source="commission_import")
        p = ingest_mod.write_payment_from_fact(fact, stmt, res.policy, agency.id, agent_user.id)
        db.session.flush()
        assert Customer.query.count() == before        # nothing created
        assert p.policy_id is None                     # held, unattached (no customer_id column)
        assert p.policy_id is None
        assert p.match_confidence == "unmatched"
        assert p.paid_amount == 100.0                  # recorded + counted (not lost)
```

- [ ] **Step 2: Run it to verify it fails or passes**

Run: `python3 -m pytest tests/test_commission_ingest.py::test_parked_row_writes_held_unattached_payment -v`
Expected: may already PASS (the writer handles `policy=None`). If `match_confidence` is not `'unmatched'` for a no-policy row, proceed to Step 3; otherwise skip to Step 4.

- [ ] **Step 3: Ensure a no-policy payment is marked unmatched + add the counter**

In `app/commission/ingest.py`, in `write_payment_from_fact`, where `PolicyPayment` fields are set, ensure: when `policy is None`, `match_confidence` is `"unmatched"` and `policy_id` stays `None` (do not invent a policy). `PolicyPayment` has no `customer_id` column. In the ingest loop (after `res = resolve_customer(...)`), add:

```python
        if res.match_path == "parked":
            result.parked_payments += 1
```

And add `parked_payments: int = 0` to the `IngestResult` dataclass.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_commission_ingest.py::test_parked_row_writes_held_unattached_payment -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/commission/ingest.py tests/test_commission_ingest.py
git commit -m "feat: parked commission row writes a held unattached payment + counter

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Auto-sweep parked payments on BOB import

When a BOB import produces a customer with a known ID, attach every parked payment whose ID matches.

**Files:**
- Modify: `app/commission/payments.py` — add `sweep_parked_payments(customer, agency_id)`.
- Modify: `app/upload.py` — call it at the end of `_upsert_customer_from_policy` once IDs are known.
- Test: `tests/test_parked_payment_sweep.py` (new).

**IMPORTANT MODEL FACT (corrected during build):** `PolicyPayment` has **NO `customer_id` column.** A payment links to a customer ONLY via `policy_id → Policy.customer_id`. So:
- A **parked** payment = `policy_id IS NULL` + `match_confidence='unmatched'`.
- **Attaching** a parked payment = setting its `policy_id` to the customer's matching `Policy` (which already carries `customer_id` + the AOR). There is no `customer_id` on the payment to set — do NOT reference `PolicyPayment.customer_id` anywhere (it does not exist).
- A BOB import that just created/updated this customer also created/updated their `Policy`, so the matching policy exists by the time the sweep runs.

**Interfaces:**
- Consumes: `Customer` (with `mbi` / `humana_id`), `PolicyPayment` (`policy_id` NULL = parked; fields `mbi`, `carrier_member_id`, `carrier`, `match_confidence`), `Policy` (`carrier`, `member_id`, `customer_id`, `status`).
- Produces: `sweep_parked_payments(customer, agency_id) -> int` — number of parked payments attached. Finds ALL parked rows (`policy_id IS NULL`, `match_confidence='unmatched'`) matching the customer's MBI/humana_id OR the customer's active-policy `member_id`s, sets each row's `policy_id` to that matching `Policy`, and bumps `match_confidence` off `'unmatched'` to `'swept'`. Idempotent (only touches `policy_id IS NULL` rows; a row with no resolvable policy stays parked and is not counted).

- [ ] **Step 1: Write the failing test**

```python
from datetime import date

def _agency_and_user(db, app):
    from app.models import Agency, User
    a = Agency(name="T"); db.session.add(a); db.session.flush()
    u = User(name="Agent", email="a@x.com", agency_id=a.id); db.session.add(u); db.session.flush()
    return a, u

def test_sweep_attaches_all_parked_for_matching_mbi(db_session, app):
    """BOB creates the customer + their Policy; both parked payments for that MBI
    attach by getting policy_id set (PolicyPayment has no customer_id column —
    linkage is via the policy)."""
    from app.extensions import db
    from app.models import Customer, Policy, PolicyPayment, CommissionStatement
    from app.commission.payments import sweep_parked_payments
    with app.app_context():
        a, u = _agency_and_user(db, app)
        stmt = CommissionStatement(agency_id=a.id, carrier="UHC",
                                   statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(stmt); db.session.flush()
        # two parked payments, same MBI, not yet linked to any policy
        for i in range(2):
            db.session.add(PolicyPayment(agency_id=a.id, statement_id=stmt.id, carrier="UHC",
                                         member_name="Bob Jones", period_label="May 2026",
                                         commission_action="renewal",
                                         mbi="1AB2C", paid_amount=50.0,
                                         policy_id=None, match_confidence="unmatched",
                                         source_ref=f"uhc::x::S::{i}"))
        db.session.flush()
        # BOB now creates the customer AND their policy (member_id == the MBI for UHC)
        c = Customer(agency_id=a.id, first_name="Bob", last_name="Jones",
                     full_name="Bob Jones", mbi="1AB2C")
        db.session.add(c); db.session.flush()
        pol = Policy(agency_id=a.id, carrier="UHC", member_id="1AB2C",
                     status="active", customer_id=c.id)
        db.session.add(pol); db.session.flush()

        n = sweep_parked_payments(c, a.id)
        db.session.flush()
        assert n == 2
        # attached == both now carry the customer's policy_id
        assert PolicyPayment.query.filter_by(policy_id=pol.id).count() == 2
        assert PolicyPayment.query.filter_by(policy_id=None).count() == 0
        # and they trace to the customer through the policy
        for pay in PolicyPayment.query.filter_by(policy_id=pol.id).all():
            assert pay.policy.customer_id == c.id
            assert pay.match_confidence != "unmatched"
```

(Note: `member_name`, `period_label`, `commission_action` are NOT NULL on `PolicyPayment` — set them so the row inserts. Confirm any other NOT NULL columns by `grep -n "nullable=False" app/models.py` within the `PolicyPayment` class and set them too.)

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_parked_payment_sweep.py -v`
Expected: FAIL — `sweep_parked_payments` not defined.

- [ ] **Step 3: Implement `sweep_parked_payments`**

In `app/commission/payments.py`:

```python
def sweep_parked_payments(customer, agency_id) -> int:
    """Attach every parked (policy_id IS NULL, unmatched) PolicyPayment whose unique
    carrier ID matches this just-known customer, by setting its policy_id to the
    customer's matching Policy. PolicyPayment has no customer_id column — linkage is
    via the policy. Idempotent. Returns count attached."""
    from app.models import PolicyPayment, Policy
    # (matcher, value) pairs keyed on the payment's columns
    ids = []
    if customer.mbi:
        ids.append(("mbi", customer.mbi))
    if getattr(customer, "humana_id", None):
        ids.append(("carrier_member_id", customer.humana_id))
    for p in Policy.query.filter_by(agency_id=agency_id, customer_id=customer.id,
                                    status="active").all():
        if p.member_id:
            ids.append(("carrier_member_id", p.member_id))
    if not ids:
        return 0

    attached = 0
    seen = set()
    for field, value in ids:
        q = (PolicyPayment.query
             .filter_by(agency_id=agency_id, policy_id=None)
             .filter(getattr(PolicyPayment, field) == value))
        for pay in q.all():
            if pay.id in seen:
                continue
            # find the customer's policy for this payment's carrier+id
            pol = (Policy.query
                   .filter_by(agency_id=agency_id, customer_id=customer.id,
                              carrier=pay.carrier)
                   .filter(Policy.member_id == (pay.carrier_member_id or pay.mbi))
                   .first())
            if pol is None:
                continue                 # no resolvable policy yet → stays parked
            pay.policy_id = pol.id
            if pay.match_confidence == "unmatched":
                pay.match_confidence = "swept"
            seen.add(pay.id)
            attached += 1
    return attached
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_parked_payment_sweep.py -v`
Expected: PASS.

- [ ] **Step 5: Wire it into the BOB upsert**

In `app/upload.py`, at the END of `_upsert_customer_from_policy` (after the customer's MBI/humana_id are set AND its Policy has been created/flushed — so the policy the sweep needs exists — before return), add:

```python
    from app.commission.payments import sweep_parked_payments
    sweep_parked_payments(customer, agency_id)
```

(If the Policy for this BOB row is created by the resolver/caller AFTER `_upsert_customer_from_policy` returns rather than inside it, place the sweep call at the point where both the customer and its policy are committed — confirm by reading the BOB flow around the `_upsert_customer_from_policy` call site and the `resolve_customer(source="bob")` policy creation. The invariant that matters: the sweep must run after the matching Policy exists.)

- [ ] **Step 6: Add an idempotency test (re-run sweeps nothing)**

Append to `tests/test_parked_payment_sweep.py`:

```python
def test_sweep_is_idempotent(db_session, app):
    from app.extensions import db
    from app.models import Customer, Policy, PolicyPayment, CommissionStatement
    from app.commission.payments import sweep_parked_payments
    from datetime import date
    with app.app_context():
        a, u = _agency_and_user(db, app)
        stmt = CommissionStatement(agency_id=a.id, carrier="UHC",
                                   statement_date=date(2026,5,1), period_label="May 2026")
        db.session.add(stmt); db.session.flush()
        db.session.add(PolicyPayment(agency_id=a.id, statement_id=stmt.id, carrier="UHC",
                                     member_name="Z Z", period_label="May 2026",
                                     commission_action="renewal",
                                     mbi="ZZ9", paid_amount=10.0,
                                     policy_id=None, match_confidence="unmatched",
                                     source_ref="uhc::x::S::0"))
        c = Customer(agency_id=a.id, first_name="Z", last_name="Z", full_name="Z Z", mbi="ZZ9")
        db.session.add(c); db.session.flush()
        db.session.add(Policy(agency_id=a.id, carrier="UHC", member_id="ZZ9",
                              status="active", customer_id=c.id)); db.session.flush()
        assert sweep_parked_payments(c, a.id) == 1
        db.session.flush()
        assert sweep_parked_payments(c, a.id) == 0      # nothing left to sweep (policy_id set)
```

- [ ] **Step 7: Run + commit**

Run: `python3 -m pytest tests/test_parked_payment_sweep.py -q`
Expected: PASS.

```bash
git add app/commission/payments.py app/upload.py tests/test_parked_payment_sweep.py
git commit -m "feat: auto-sweep parked commission payments onto BOB-created customer by ID

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Route commission normalizers through `normalize_person_name`

The ~7 `MemberFact` name constructions in `normalizers.py` do ad-hoc name handling. Route them through the shared "First MI. Last" normalizer so parked/hub names are clean for the human matcher.

**Files:**
- Modify: `app/commission/normalizers.py` (the name fields of each `MemberFact`).
- Test: `tests/test_commission_name_normalization.py` (new).

**Interfaces:**
- Consumes: `from app.names import normalize_person_name` → `(first, middle_initial, last, full)`.
- Produces: every customer-bearing `MemberFact` has `full_name` in "First MI. Last" form, `first_name`/`last_name` title-cased. NON_CUSTOMER rows (HRA labels like "HRA Bonus") are left as-is (no person name).

- [ ] **Step 1: Write the failing test**

```python
def test_commission_names_are_first_mi_last(app):
    """Each carrier's raw name shape normalizes to 'First MI. Last'."""
    from app.names import normalize_person_name
    # sanity: the normalizer itself (the standard we route through)
    assert normalize_person_name("CONNELLY, JOHN J.")[3] == "John J. Connelly"
    assert normalize_person_name("BRYANT D,KATHERINE")[3] == "Katherine D. Bryant"
    assert normalize_person_name("jane doe")[3] == "Jane Doe"


def test_aetna_normalizer_emits_clean_name(app):
    from app.commission.normalizers import normalize_aetna
    # one Aetna row: name in col4 = "CONNELLY, JOHN J."
    row = [None]*21
    row[1] = "4RH5X85DC65"; row[2] = "M123"; row[4] = "CONNELLY, JOHN J."
    row[9] = "H1036-335"; row[12] = "2026-06-01"; row[16] = "Tim Winslow"; row[20] = 28.92
    sheets = {"Founders": [["header"], row]}
    facts = normalize_aetna(sheets)
    assert facts and facts[0].full_name == "John J. Connelly"
    assert facts[0].first_name == "John" and facts[0].last_name == "Connelly"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_commission_name_normalization.py -v`
Expected: `test_aetna_normalizer_emits_clean_name` FAILS (current Aetna emits raw `CONNELLY, JOHN J.`).

- [ ] **Step 3: Apply the normalizer in each carrier normalizer**

At the top of `app/commission/normalizers.py` add `from app.names import normalize_person_name`. Then for EACH customer-bearing `MemberFact` (UHC line ~73, Healthspring ~150, BCBS ~298, Aetna ~369, Devoted detail ~216 & ~524 — verify by `grep -n "full_name=" app/commission/normalizers.py`), replace the ad-hoc name fields. Pattern, using the carrier's raw name source:

```python
        first, mi, last, full = normalize_person_name(<raw name source for this carrier>)
        # ...
        MemberFact(
            ...
            full_name=full,
            first_name=first,
            last_name=last,
            ...
        )
```

- For carriers whose raw name is a single "Member Name" cell (UHC, BCBS, Aetna): pass that cell.
- For carriers giving separate first/last columns (Devoted, Healthspring): pass `f"{last}, {first}"` so the comma-form parser title-cases + orders correctly (or pass `f"{first} {last}"` — both are handled by `normalize_person_name`; prefer the form that preserves any middle initial).
- Do NOT touch NON_CUSTOMER rows (HRA Bonus / HRA / Misc) — they carry a label, not a person.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_commission_name_normalization.py -v`
Expected: PASS.

- [ ] **Step 5: Run the normalizer suite (no regressions)**

Run: `python3 -m pytest tests/test_commission_normalizers.py -q`
Expected: PASS. (If a normalizer test asserted a raw name, update its expectation to the clean form.)

- [ ] **Step 6: Commit**

```bash
git add app/commission/normalizers.py tests/test_commission_name_normalization.py
git commit -m "feat: commission normalizers emit clean 'First MI. Last' names via normalize_person_name

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Block uploads for unknown / unsupported carriers

An unparseable or unsupported-carrier commission file must be rejected with a clear reason, importing nothing.

**Files:**
- Modify: `app/commission/routes.py` — `commission_upload()` (around line 1040, after `carrier = _detect_carrier(ws)`).
- Test: `tests/test_unknown_carrier_block.py` (new).

**Interfaces:**
- Consumes: `_detect_carrier(ws)`, `NORMALIZERS` (`from app.commission.normalizers import NORMALIZERS`).
- Produces: when `carrier` is falsy OR `carrier not in NORMALIZERS`, flash an explicit message and redirect WITHOUT ingesting. Supported list derived from `sorted(NORMALIZERS)`.

- [ ] **Step 1: Write the failing test (logic-level, no HTTP)**

```python
def test_unsupported_carrier_is_blocked():
    """A detected carrier not in NORMALIZERS must be rejected (no ingest)."""
    from app.commission.normalizers import NORMALIZERS
    assert "GTL" not in NORMALIZERS
    assert "Wellable" not in NORMALIZERS and "Medico" not in NORMALIZERS
    # the supported set is exactly the 6 wired carriers
    assert set(NORMALIZERS) == {"UHC", "Humana", "Devoted", "BCBS", "Aetna", "Healthspring"}


def test_block_message_lists_supported(app):
    """The guard helper returns a clear block reason for an unsupported carrier."""
    from app.commission.routes import _carrier_supported_or_reason
    ok, reason = _carrier_supported_or_reason("GTL")
    assert ok is False
    assert "GTL" in reason and "not yet supported" in reason
    ok2, _ = _carrier_supported_or_reason("UHC")
    assert ok2 is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_unknown_carrier_block.py -v`
Expected: FAIL — `_carrier_supported_or_reason` not defined.

- [ ] **Step 3: Add the guard helper + call it in `commission_upload`**

In `app/commission/routes.py` add (near `_detect_carrier`):

```python
def _carrier_supported_or_reason(carrier):
    """Return (True, '') if we can ingest this carrier, else (False, reason)."""
    from app.commission.normalizers import NORMALIZERS
    if not carrier:
        return False, ("Could not detect the carrier from this file's headers. "
                       "Nothing was imported.")
    if carrier not in NORMALIZERS:
        supported = ", ".join(sorted(NORMALIZERS))
        return False, (f"Cannot parse this file — carrier '{carrier}' is not yet "
                       f"supported (supported: {supported}). Nothing was imported.")
    return True, ""
```

Then in `commission_upload()`, replace the existing `if not carrier:` block (lines ~1041-1043) with:

```python
    carrier = _detect_carrier(ws)
    ok, reason = _carrier_supported_or_reason(carrier)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("commission.commission_admin"))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_unknown_carrier_block.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/commission/routes.py tests/test_unknown_carrier_block.py
git commit -m "feat: block commission upload for unsupported carriers with a clear reason

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Integrity invariants — "no new commission stubs" + "nothing lost"

Add two radar invariants so the radar continuously proves item 1's guarantees.

**Files:**
- Modify: `app/integrity.py` — add `commission_import_stubs` + `statement_balance_complete`.
- Modify: `integrity_baseline.json` — freeze the two new counts at current prod levels.
- Test: `tests/test_integrity_data_invariants.py` (add).

**Interfaces:**
- Consumes: the `@invariant(key, *, severity, domain, description)` decorator; `Customer`, `PolicyPayment`, `CommissionLineItem`, `CommissionStatement` models; the wrapped fn returns `(count, sample)`.
- Produces: `REGISTRY["commission_import_stubs"]` and `REGISTRY["statement_balance_complete"]`. The ratchet test in `tests/test_integrity_guards.py` reads `integrity_baseline.json`.

- [ ] **Step 1: Write the failing test**

```python
def test_commission_import_stubs_invariant_counts_only_commission_stubs(db_session, app):
    from app.extensions import db
    from app.models import Customer
    from app.integrity import REGISTRY
    with app.app_context():
        a = _agency()  # use the file's existing agency helper
        db.session.add(Customer(agency_id=a, first_name="A", last_name="B", full_name="A B",
                                stub=True, source="commission_import"))
        db.session.add(Customer(agency_id=a, first_name="C", last_name="D", full_name="C D",
                                stub=True, source="bob"))            # not counted
        db.session.flush()
        v = REGISTRY["commission_import_stubs"]()
        assert v.count == 1


def test_statement_balance_complete_flags_a_dropped_payment(db_session, app):
    """Sigma(line items) must equal Sigma(payments). A line item with no matching
    payment is a 'lost payment' violation."""
    from app.integrity import REGISTRY
    with app.app_context():
        v = REGISTRY["statement_balance_complete"]()
        assert v.count >= 0     # registry callable returns a Violation
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_integrity_data_invariants.py -k "commission_import_stubs or statement_balance_complete" -v`
Expected: FAIL — `KeyError` (invariants not registered).

- [ ] **Step 3: Add the invariants in `app/integrity.py`**

```python
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
           description="Per statement, Sigma(commission line items) must equal "
                       "Sigma(payments) within $0.01 — proves no payment was lost.")
def _statement_balance_complete():
    from app.models import CommissionStatement, CommissionLineItem, PolicyPayment
    violations = []
    for s in CommissionStatement.query.all():
        li = sum(x.raw_amount or 0.0 for x in
                 CommissionLineItem.query.filter_by(statement_id=s.id).all())
        pay = sum(x.paid_amount or 0.0 for x in
                  PolicyPayment.query.filter_by(statement_id=s.id).all())
        if li and abs(round(li - pay, 2)) > 0.01:
            violations.append({"id": s.id,
                               "label": f"{s.carrier} {s.period_label}: lineitems={li:.2f} payments={pay:.2f}"})
    return len(violations), violations[:20]
```

(If `CommissionLineItem.raw_amount` / `PolicyPayment.paid_amount` names differ, `grep -n "raw_amount\|paid_amount" app/models.py` and use the actual columns.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_integrity_data_invariants.py -k "commission_import_stubs or statement_balance_complete" -v`
Expected: PASS.

- [ ] **Step 5: Freeze the baseline for the two new keys**

Run the CLI to print current counts, then add them to `integrity_baseline.json` (the ratchet's frozen levels). Locally this is 0/0; the REAL prod baseline (commission_import_stubs=571) is set on the VPS during deploy (Task 7 verify step):

Run: `python3 scripts/audit_integrity.py --json` (inspect output keys)
Then add `"commission_import_stubs": 0` and `"statement_balance_complete": 0` to `integrity_baseline.json` if the ratchet requires every key present. (Confirm format by reading the file first.)

- [ ] **Step 6: Run the guard suite**

Run: `python3 -m pytest tests/test_integrity_guards.py tests/test_integrity_registry.py -q`
Expected: PASS (no count above baseline locally).

- [ ] **Step 7: Commit**

```bash
git add app/integrity.py integrity_baseline.json tests/test_integrity_data_invariants.py
git commit -m "feat: integrity invariants — commission_import_stubs ratchet + statement_balance_complete

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Stale-park aging surface + full-suite + real-Postgres verify

Surface parked payments older than 30 days, run the whole suite, then verify on the VPS per protocol.

**Files:**
- Modify: `app/commission/payments.py` — add `parked_payments_older_than(days, agency_id)`.
- Modify: the admin commission view (`app/commission/routes.py` where `unmatched_count` is built, ~1446) to also expose `stale_parked_count`.
- Test: `tests/test_parked_payment_sweep.py` (add age test).

**Interfaces:**
- Consumes: `PolicyPayment` (parked = `policy_id IS NULL` + `match_confidence='unmatched'`; aged by `statement_date`), `datetime`. (`PolicyPayment` has NO `customer_id` — parked is `policy_id IS NULL`.)
- Produces: `parked_payments_older_than(days, agency_id) -> int`.

- [ ] **Step 1: Write the failing test**

```python
def test_parked_older_than_counts_aged_holds(db_session, app):
    from app.extensions import db
    from app.models import PolicyPayment, CommissionStatement
    from app.commission.payments import parked_payments_older_than
    from datetime import date, timedelta
    with app.app_context():
        a, u = _agency_and_user(db, app)
        old = CommissionStatement(agency_id=a.id, carrier="UHC",
                                  statement_date=date.today() - timedelta(days=45),
                                  period_label="old")
        db.session.add(old); db.session.flush()
        db.session.add(PolicyPayment(agency_id=a.id, statement_id=old.id, carrier="UHC",
                                     member_name="Old Hold", period_label="old",
                                     commission_action="renewal",
                                     mbi="OLD1", paid_amount=10.0, policy_id=None,
                                     match_confidence="unmatched",
                                     statement_date=date.today() - timedelta(days=45),
                                     source_ref="uhc::x::S::99"))
        db.session.flush()
        assert parked_payments_older_than(30, a.id) >= 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_parked_payment_sweep.py::test_parked_older_than_counts_aged_holds -v`
Expected: FAIL — function not defined.

- [ ] **Step 3: Implement the helper + surface the count**

In `app/commission/payments.py`:

```python
def parked_payments_older_than(days, agency_id) -> int:
    """Count parked (policy_id IS NULL, unmatched) payments older than `days`,
    by statement_date. The stale-park aging signal."""
    from app.models import PolicyPayment
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=days)
    return (PolicyPayment.query
            .filter_by(agency_id=agency_id, policy_id=None, match_confidence="unmatched")
            .filter(PolicyPayment.statement_date <= cutoff)
            .count())
```

(If `PolicyPayment` has no `statement_date`, use the statement's date via join, or `created_at` — `grep -n "statement_date\|created_at" app/models.py`.) In `routes.py` where the admin view builds `unmatched_count`, add `stale_parked_count = parked_payments_older_than(30, agency_id)` and pass it to the template context (a badge; template wiring is a one-line add — show "⚠ N held >30d" when > 0).

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_parked_payment_sweep.py::test_parked_older_than_counts_aged_holds -v`
Expected: PASS.

- [ ] **Step 5: Run the FULL suite**

Run: `python3 -m pytest -q`
Expected: PASS. Fix any older test that assumed commission-path stub creation (update to expect `parked`).

- [ ] **Step 6: Commit**

```bash
git add app/commission/payments.py app/commission/routes.py tests/test_parked_payment_sweep.py
git commit -m "feat: stale-park aging count (held >30d) surfaced on commission admin view

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 7: Real-Postgres verify on the VPS (project protocol — opus whole-branch review FIRST)**

Before deploy: request an **opus whole-branch review** (data/money path — required by the project protocol; it has caught a real bug every prior data round). Then:

```bash
# DB backup FIRST
ssh -i /home/timothywinslowlinux/.ssh/id_ed25519 root@23.187.248.100 \
  "cd /var/www/founders-portal && PGPASSWORD=<from .env> pg_dump -U founders_user -h localhost founders_portal > /root/founders_pre_item1_$(date +%F).sql"
# deploy
ssh ... "cd /var/www/founders-portal && git pull && ./venv/bin/pip install -r requirements.txt && systemctl restart founders-portal"
# confirm the restart actually cycled (ActiveEnterTimestamp advanced) per CLAUDE.md
ssh ... "systemctl show founders-portal -p ActiveEnterTimestamp"
# set the REAL prod baseline for the new invariant
ssh ... "cd /var/www/founders-portal && PYTHONPATH=. ./venv/bin/python3 scripts/audit_integrity.py --update-baseline"
# re-upload a UHC + a BCBS + a Humana statement via the admin UI; confirm:
#   - stubs_created = 0  (commission upload flash / ingest result)
#   - payments either attach by ID or land parked (policy_id NULL)
#   - then run a BOB import containing a parked MBI → confirm the parked payment swept on
```

Expected: 0 new commission stubs; `commission_import_stubs` does not rise; `statement_balance_complete` violation count = 0 (every dollar accounted for); a BOB import sweeps matching parked payments.

---

## Self-Review

**Spec coverage:**
- Match-or-park (ID-only, no name, no create) → Task 1 ✅
- Park holds whole payment, no payout → Task 2 ✅ (held, unattached; agent payout only happens via attached policy rows, never a parked row)
- Auto-sweep on BOB import (all rows for an ID) → Task 3 ✅
- Commission name normalization → Task 4 ✅
- Unknown-carrier block → Task 5 ✅
- `commission_import_stubs` invariant (ratchet 571) → Task 6 ✅
- "Nothing lost" balance invariant → Task 6 ✅
- Stale-park aging alert (>30d) → Task 7 ✅
- Real-Postgres verify + opus review + backup → Task 7 ✅
- No model/migration → honored throughout ✅
- Out-of-scope (item 2 merge, item 4 hub actions, Medico/GTL wiring) → not in any task ✅

**Placeholder scan:** No TBD/TODO; every code step shows code; commands have expected output. Two `grep -n` fallbacks (column/attribute name confirmation) are verification steps, not placeholders.

**Type consistency:** `sweep_parked_payments(customer, agency_id) -> int` consistent across Task 3 def + Task 3 wire-in. `parked_payments_older_than(days, agency_id) -> int` consistent Task 7. `match_path="parked"` consistent Tasks 1/2. `IngestResult.parked_payments` consistent Task 2. Invariant keys `commission_import_stubs` / `statement_balance_complete` consistent Tasks 6 def + tests.
