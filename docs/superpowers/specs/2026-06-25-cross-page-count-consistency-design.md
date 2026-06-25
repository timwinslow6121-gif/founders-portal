# Cross-Page Count Consistency (single source of truth, labeled) — Design

_Date: 2026-06-25 · Status: ABSORBED as **item 5** of `2026-06-25-data-integrity-
remediation-roadmap.md`. Tim's stress-test (John Connelly ×5, plan 250-vs-1701) showed
this narrow display-consistency fix was too shallow — the underlying numbers are wrong
(dup-stub inflation + 90% orphaned plan_id), so making two pages agree would agree on
WRONG numbers. This spec is correct but deferred to LAST in the roadmap, after items 1-3
fix the underlying data. Build the roadmap's item 1 first._

## 0. Why this exists (the bug)

Two pages show **different counts for the same carrier**, which destroys trust in
every number the portal displays (Tim, 2026-06-25): Admin Agency Overview shows
Humana 2498 / UHC 2269 / BCBS 238 / Aetna 87 active policies (15 unattributed); the
All Customers page shows Humana 2497 / UHC ~2323 / BCBS 233 / Aetna 81. "If we can't
display the same numbers across two pages, the whole portal is FUBAR."

**Live root-cause investigation (2026-06-25) — the discrepancy is fully explained, not
corruption:**
- **Agency Overview counts POLICIES** via `app/metrics.py` (`_policy_q`: `status="active"`,
  agency-scoped, **excludes `::0::` commission-stub placeholders**).
- **All Customers counts CUSTOMERS** (distinct customers who have a policy in that
  carrier) and **does NOT exclude the stubs**. It rolls its own queries in
  `app/customers.py` — it never calls `metrics.py`.

Three precisely-measured sources of divergence:
1. **Different unit** — policies vs. distinct customers. A customer with 2 plans in one
   carrier counts as 2 policies but 1 member. Live: 7 Aetna customers have 2 active
   policies each → Aetna 87 policies = ~80 members.
2. **Stub-filter mismatch (the big UHC gap)** — UHC has **51 `::0::` stub policies**.
   Agency Overview excludes them (2320→2269); All Customers does not. Distinct UHC
   customers: 2315 with stubs, 2264 without.
3. A few residual from FK-vs-MBI customer-link edge cases.

**The architectural root:** `app/metrics.py` exists precisely to be "the ONLY place
agency book numbers are computed" (enforced by `tests/test_metrics_guard.py`), and the
Dashboard, Agency Overview, and Carrier drill-down all use it and agree. But
**`app/customers.py` was never migrated onto metrics AND was never added to the guard
test's `SCANNED` list**, so it silently rolled its own numbers with different rules.

## 1. Audit (done 2026-06-25) — every book-count surface

| Page / surface | File | Uses metrics? | Counts |
|---|---|---|---|
| Dashboard | routes.py | ✅ | policies |
| Agency Overview | routes.py | ✅ | policies |
| Carrier drill-down `/carriers/c/<carrier>` | carriers.py | ✅ | policies |
| Plan list per-plan tally | carriers.py | ⚠️ allowlisted (plan-detail tally, ok) | policies |
| **All Customers list + carrier counts** | **customers.py** | **❌ rolls own** | **customers, stubs NOT excluded** |
| Needs-Identity hub | customers.py | ❌ (different purpose, out of scope) | mixed |
| Pharmacies | pharmacies.py | ❌ (per-pharmacy scope, out of scope) | policies |

Only `app/customers.py` is a trust-relevant book-count surface that bypasses metrics.
It is also absent from the guard's `SCANNED = ["app/routes.py", "app/carriers.py",
"app/commission/routes.py"]`.

## 2. The decision (Tim, 2026-06-25)

Every carrier book number, on every page, is shown as **"N members · M policies"**,
sourced from `app/metrics.py` so the two numbers are defined once and identical
everywhere. The All Customers page's carrier chips show the same "members · policies"
as Agency Overview; the customer list below still lists customers (unchanged).

## 3. Scope

**In scope (tight — fixes "two pages disagree" and prevents regression):**
1. `app/metrics.py`: add member counting (distinct customers, stub-excluded) alongside
   the existing policy counting.
2. `app/customers.py`: stop rolling its own carrier counts; consume `metrics.py`. Apply
   the `::0::` stub exclusion to the customer-list filter path too.
3. Both Agency Overview and All Customers render "N members · M policies" from the same
   `book_breakdown` call.
4. Extend `tests/test_metrics_guard.py` `SCANNED` to include `app/customers.py` so a
   future raw `Policy...count()` there fails the build.
5. A consistency test asserting the two pages' per-carrier numbers are equal (same
   metrics call).

**Out of scope (separate follow-up specs that THIS unblocks):**
- **Stub RESOLUTION** — matching the 51 `::0::` stubs to real customers (identity work;
  this spec only makes their *exclusion from counts* canonical). [[Carriers & Plans cleanup]]
- **103 no-name policies** — name recovery (identity work).
- **Round 2** — date-aware BOB↔commission reconciliation (different axis: book vs. pay;
  depends on a stable book number, which this provides).
- **Round 3** — whole-codebase audit. This spec's audit + guard extension is a slice /
  proof-of-concept of Round 3's pattern (one source + a build-failing guard); Round 3
  generalizes it to all count/route/orphan surfaces later.
- Needs-Identity hub counts and Pharmacies counts (different scopes, not the bug).

## 4. Components

### 4.1 `app/metrics.py` (extend)
- `member_count(scope) -> int` — DISTINCT customers who have an active policy matching the
  scope, using the SAME FK-or-MBI resolution the customers page uses today, with the
  SAME filters as `_policy_q` (active, agency, `~member_id.like('%::0::%')`, optional
  carrier/agent). One definition of "a member in this carrier."
- `book_breakdown(scope)` — extend so `by_carrier` entries carry BOTH `count` (policies,
  existing) and `members` (new). Implementation: compute a `by_carrier_members` map
  (distinct-customer count per carrier under the stub-excluded policy set) and merge it
  into the existing `by_carrier` list keyed by carrier. Existing `count`/`pct` semantics
  unchanged (back-compat for current consumers).
- The member-per-carrier query reuses the FK-first + MBI-fallback union already proven in
  `customers.py::_apply_customer_filters` (FK customer_ids ∪ customers whose MBI matches a
  matching policy's MBI), but restricted to the stub-excluded active policy set.

### 4.2 `app/customers.py` (migrate)
- The carrier chips/stat strip on All Customers call `metrics.book_breakdown(Scope(
  agency_id=current_user.agency_id))` and render `by_carrier` as "N members · M policies".
- Add the `::0::` stub exclusion to the policy-matching base in `_apply_customer_filters`
  so a carrier-filtered customer view never includes a stub-only customer.
- Remove the page's own raw carrier-count query (the `db.session.query(Policy.carrier)...`
  distinct list stays only if needed for the filter dropdown options, which is a label
  list, not a count — keep it but it computes no counts).

### 4.3 `app/routes.py` (Agency Overview template data)
- Already calls `book_breakdown`. Update the Agency Overview template to render
  "N members · M policies" per carrier from the now-extended `by_carrier`.

### 4.4 `tests/test_metrics_guard.py` (extend)
- Add `"app/customers.py"` to `SCANNED`. Allowlist (with a reason) any intentional
  non-book count there (e.g. the Needs-Identity hub category counts, the customer
  deal-stage stat strip — those count Customers by stage, not the agency book, so they
  are not what the guard targets; allowlist them explicitly so the guard stays green
  while still catching new raw Policy book-counts).

## 5. Data flow

```
Scope(agency_id, [agent_id], [carrier])
  → metrics._policy_q  (active, agency, ::0:: excluded)
  → policy_count / member_count / book_breakdown(by_carrier{count, members})
        ├─ routes.py Agency Overview  → "N members · M policies"
        └─ customers.py All Customers → "N members · M policies" (same call)
```

## 6. Testing (TDD)

- **member_count excludes stubs:** a `uhc::0::N` stub policy's customer is NOT counted.
- **member_count is distinct:** a customer with 2 active policies in one carrier counts
  once; `policy_count` counts both.
- **book_breakdown carries members:** each `by_carrier` entry has `count` (policies) and
  `members` (distinct customers); members ≤ count.
- **CONSISTENCY KEYSTONE:** for a fixture agency with stubs + multi-plan members, the
  per-carrier `(members, policies)` pair returned for the Agency-Overview scope EQUALS
  the pair the All-Customers page renders — i.e. both call the same function and cannot
  diverge. (This is the test that would have caught the original bug.)
- **Guard test:** `app/customers.py` is scanned; a deliberately-added raw
  `Policy.query...count()` would fail unless allowlisted.
- **Live verify (Postgres):** Agency Overview and All Customers show identical
  "members · policies" per carrier; UHC reconciles to the stub-excluded numbers
  (2269 policies / 2264 members), Aetna shows 87 policies / ~80 members.

## 7. Acceptance criteria

All carrier book counts on every in-scope page come from `app/metrics.py`; Agency
Overview and All Customers display identical "N members · M policies" per carrier;
the `::0::` stub exclusion is applied consistently; `app/customers.py` is in the guard
test's `SCANNED` so the divergence cannot regress; a consistency test asserts the two
pages' numbers are equal. No migration. Stub-resolution, no-name policies, and
Rounds 2/3 remain separate follow-up specs that this unblocks.
