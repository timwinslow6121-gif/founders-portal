# Item 0 — Data-Integrity Radar & Guard Suite — Design

_Date: 2026-06-25 · Status: approved, ready for implementation plan. This is **item 0**
of `2026-06-25-data-integrity-remediation-roadmap.md` — built BEFORE remediation items
1-5 because it's the radar that proves each fix worked and the net that stops new
corruption._

## 0. Why this exists

The portal is in a whack-a-mole loop: fix a symptom on one page, the bad data underneath
resurfaces elsewhere, and fixes break two more things (Tim, 2026-06-25). Root cause is a
MISSING SYSTEM, not a discipline failure — there's no continuous, reliable detector of
data-integrity violations and no net that fails the build when something regresses. A
live audit found this is portal-wide: 571 stub customers, 152 mergeable duplicate rows
(107 clusters), 4,611/5,135 active policies with NULL plan_id (90%).

**Division of labor (the honest boundary):** the MACHINE finds, counts, and prevents
regression; a HUMAN makes truth calls (is "CONNELLY, JOHN" the same person as "John
Connelly"? — only Tim knows, he wrote the policies); the remediation TOOLS execute
approved fixes safely. This is NOT an auto-fixer — auto-deciding data fixes corrupts
data silently (exactly how we got 152 dups). It's a radar + a ratchet + human-approved
repair.

## 1. Architecture — one registry, three consumers, one baseline

```
app/integrity.py   (the registry: @invariant functions — the ONE source of truth)
        │
   ┌────┼────────────────────┬───────────────────────┐
   ▼    ▼                    ▼                       ▼
scripts/audit_     /admin/integrity        tests/test_integrity_    integrity_baseline.json
integrity.py       (live dashboard          guards.py (ratchet:      (frozen per-invariant
(CLI / CI print)    w/ drill-in links)      fail if count>baseline)  debt levels)
```

Adding ONE `@invariant` function lights up all three surfaces at once — the report and
CI can never disagree about what's checked (that drift IS the class of bug we're killing).

### 1.1 `app/integrity.py` — the registry
- `@invariant(key, *, severity, domain, description)` decorator registers a function
  returning a `Violation(key, severity, domain, count, sample, description)`.
  - `severity` ∈ `high | med | low`; `domain` ∈ `data | consistency | route`.
  - `count` = number of violating rows; `sample` = up to ~10 example rows (id + a label
    + drill-in link target) for the report; the function does the query.
- `run_all() -> list[Violation]` iterates the registry. Pure read-only; never mutates.

### 1.2 `scripts/audit_integrity.py` — CLI / CI
- Prints a table: `key | domain | severity | count | baseline | Δ | sample`.
- Exit non-zero if ANY count > its baseline (so CI can call it directly too). `--json`
  for machine use; `--update-baseline` to re-freeze after an approved cleanup.

### 1.3 `/admin/integrity` — the live dashboard (admin-only)
- Same `run_all()` data, grouped by domain, severity-colored, with count vs baseline and
  Δ. Each invariant row drills into the violating records (e.g. click dup_customers →
  the 107 clusters → a cluster → its rows). Read-only radar; remediation actions live in
  items 1-5, linked from here as they ship.

### 1.4 `tests/test_integrity_guards.py` + `integrity_baseline.json` — the ratchet
- `integrity_baseline.json` records today's count per invariant key.
- The guard test FAILS only if a live count EXCEEDS its baseline (new corruption);
  existing debt does NOT block work. As each remediation item cleans an invariant, drop
  its baseline (down to 0 when fully cleaned) — the ratchet only tightens. At baseline 0,
  ANY violation fails the build.
- `tests/test_metrics_guard.py` folds in as the `count_only_via_metrics` consistency
  invariant (its current logic preserved).

## 2. Launch invariants (all already proven to exist in live data)

**domain=data**
- `plan_id_orphans` (high) — active non-stub Policy with NULL `plan_id` (≈4,611).
- `duplicate_customers` (high) — >1 non-stub-distinct Customer sharing normalized
  name + DOB (≈152 excess across 107 clusters). **Multi-AOR-aware:** a person with two
  concurrent policies/AORs is ONE customer, never a duplicate (see §4).
- `no_name_policies` (high) — active Policy with blank first+last (≈103).
- `orphan_stub_customers` (med) — `stub=True` customers not tied to any line item /
  payment origin (the unknown-origin garbage; ≈subset of 571). **Lifecycle-aware:** a
  `source='manual'` lead is NOT a violation (see §3).
- `payment_without_customer` (high) — PolicyPayment with NULL customer link.
- `backwards_date_interval` (high) — CustomerAorHistory or Policy with
  `effective_date > term_date` (we hit one: Katherine D. Bryant).
- `unattributed_active_policy` (med) — active Policy with no derivable agent (via policy
  AOR, see §4) — ≈15.

**domain=consistency**
- `count_only_via_metrics` (high) — no book/money count computed outside `app/metrics.py`
  in the scanned files (absorbs `test_metrics_guard`; adds `app/customers.py`).
- `carrier_counts_agree` (high) — for each carrier, the number Agency Overview renders ==
  the number All Customers renders == the plan-rollup sum (the "two pages must agree"
  guarantee as a test; this is roadmap item 5's keystone, registered now as report-only
  until item 5 cleans it).

**domain=route**
- `links_resolve` (med) — every `url_for(...)` / nav link target resolves to a
  registered route.
- `no_orphan_routes` (low) — every registered view route is reachable from nav or
  another page (or explicitly marked internal/API/webhook).

## 3. Lifecycle-awareness — leads are NOT violations (Tim, 2026-06-25)

Agents can manually add a person before they're a customer: a **new-to-Medicare lead**
with demographics but **no MBI yet**, no BOB, no commission. They can change/cancel the
application until month-end, so they are NOT a customer until the **effective date
passes**. The model ALREADY supports this — `Customer.deal_stage`
(`Lead/SOA_Sent/Appointed/Enrolled/Active/Termed`) + `Customer.source`
(`manual | bob | commission_import | healthsherpa`). The bug is these aren't used as the
basis for "is this row legitimate."

**Rules the radar + counts must honor:**
- **Provenance ≠ completeness.** "Nothing of unknown origin" means every row has a known
  `source` — NOT "every row has an MBI." A `source='manual'` lead with no MBI has a known
  origin (an agent typed it on purpose) and is VALID. A `source='commission_import',
  stub=True` row duplicating a real person has a wrong/unknown origin and is GARBAGE.
  Same "no MBI," opposite legitimacy — discriminated by `source` + `deal_stage`.
- **Lead/Enrolled-stage people are EXEMPT** from "must trace to a BOB/commission row" and
  from "must have an MBI" invariants. Only `deal_stage='Active'` (or Termed) people are
  held to the customer-grade invariants.
- **Lead→Customer transition (chosen model — stage-driven, auto-advance):** manual entry
  starts at `Lead` (or `Enrolled` once an app is submitted). They do NOT count in
  book/customer metrics until `deal_stage='Active'`, which **auto-advances when their
  effective_date passes** (a nightly check) OR when a BOB/commission row confirms them.
  Matches how MedicareCenter/HealthSherpa tag-advance (but cleaner — "do better than
  MedicareCenter"). No separate Leads table (Zoho uses two DBs; `deal_stage` already
  does this lighter). _(The auto-advance nightly job is its own small build, sequenced
  with the lifecycle item; the radar lands first and simply EXEMPTS non-Active stages.)_
- `app/metrics.py` book/member counts already filter `status='active'` on Policy; the
  member/customer counts must additionally treat only `deal_stage='Active'` people as
  customers (leads excluded from "customers", shown in a Leads filter instead).

## 4. Multi-AOR-awareness — AOR is per-POLICY, not per-person (Tim, 2026-06-25)

A person can have TWO concurrent policies with TWO different AORs: Rebekah is AOR on the
MAPD, Tim is AOR on the hospital-indemnity plan, same person, same time. So **"the
customer's agent" is not a single value** — `Customer.primary_agent_id` (a single field)
is a lie for these people, and is likely a ROOT CAUSE of some dup stubs (a second agent's
commission row can't fit the single field → a second customer record gets spawned).

The truth already lives in the right place: `CustomerAorHistory` is per
`(customer, carrier, ...)` with its own `agent_id` — it CAN hold two concurrent AORs.

**Constraints on the radar NOW (the full model fix is a separate roadmap item, designed
later — Tim's call):**
- The `duplicate_customers` invariant MUST NOT flag a person with two concurrent
  policies/AORs as a duplicate. One person = one Customer row even with multiple agents.
- Agent attribution in invariants (e.g. `unattributed_active_policy`) derives the
  agent(s) from the POLICY's AOR, not solely from `Customer.primary_agent_id`.
- A "customer's agents" is the SET of agents across their active policies' AORs; the
  radar and (eventually) the UI reflect the set, scoped per policy.
- **New roadmap item logged:** "AOR is per-policy" — migrate attribution/access/counts
  off single `primary_agent_id` onto per-policy AOR. Not built here; the radar is written
  multi-AOR-aware so it's correct when that item lands.

## 5. Scope

**In scope (item 0):** `app/integrity.py` registry + the launch invariants (§2),
written lifecycle-aware (§3) and multi-AOR-aware (§4); `scripts/audit_integrity.py`;
`/admin/integrity` dashboard (read-only, drill-in); `tests/test_integrity_guards.py` +
`integrity_baseline.json` ratchet; fold in `test_metrics_guard`.

**Out of scope (separate items, this enables/sequences them):** the actual REMEDIATION
(roadmap items 1-5 clean each invariant to 0 + ratchet down); the lead-lifecycle
auto-advance nightly job (sequenced with the lifecycle work — radar just exempts
non-Active now); the multi-AOR model migration (§4, its own spec); Round 2 reconciliation.

## 6. Testing (TDD)

- Registry mechanics: a known-bad fixture trips its invariant; a clean fixture returns
  count 0; `run_all` aggregates.
- Ratchet: count > baseline FAILS; count == baseline passes; count < baseline passes
  (and the test suggests re-freezing).
- Each launch invariant has a fixture proving it detects its violation AND a fixture
  proving it does NOT false-positive on the legitimate case: a `manual`/Lead row is not
  flagged (§3); a two-AOR person is not a duplicate (§4).
- `/admin/integrity` renders read-only, admin-gated, drill-in links resolve.

## 7. Acceptance criteria

One `@invariant` registry feeds the CLI, the `/admin/integrity` dashboard, and the CI
guard. The launch invariants report live counts matching the hand-run audit
(plan_id_orphans ≈4,611, duplicate_customers ≈152, etc.). The ratchet fails the build
only when a count exceeds its frozen baseline; existing debt doesn't block work. Leads
(`source='manual'`, non-Active stage) and multi-AOR persons are NOT flagged as
violations. `test_metrics_guard` is absorbed. No data is mutated by the radar. Each
later roadmap item can clean its invariant to 0 and ratchet the baseline down.
