# Contract-Code Customer/Plan Database — Design

**Status:** Brainstormed + approved section-by-section with Tim 2026-07-06. Ready for spec
review → writing-plans.
**Origin (Brian, via AJ):** "When you look at all customers, base it on Contract code, not
plan Name." Brian (who controls whether Tim gets paid) wants to click a **contract code**
(`H1036-335-001`) → see the **exact total customer count** on that plan → then whittle by
agent / pharmacy (main vs TrueCare) / LIS / hospital-indemnity / email-known-vs-unknown /
etc. "The ultimate Medicare plan database where every data point can filter + sort the
book." Must agree across BOB + CMS ingest + commissions — **never conflicting counts.**

## The problem this solves (proven against prod 2026-07-06)
- Counts by contract code are impossible today: only **523 of 5,279 active policies (10%)**
  link to a `Plan` record (`Policy.plan_id`); **4,756 are orphaned** — the `plan_id_orphans`
  integrity debt. A "customers per contract code" number would see ~10% of the book.
- The **Carriers & Plans module** (`/carriers`) and the **carrier drill-down**
  (`/carriers/c/Humana`, reachable only via Overview→Humana) DISAGREE and don't
  cross-reference — same root cause: the module counts members via `Policy.plan_id`
  (mostly NULL → 0/wrong), the drill-down counts raw `plan_name` strings from policies.
- The orphaning is tractable: the 4,756 orphans come from just **~64 distinct plan_name
  strings**, and many literally embed the contract code (e.g. "HUMANA GOLD PLUS HMO POS
  **H1036-335**" = 1,591 policies). Only **36 Plan rows have a cms_plan_id** today.
- Most of Brian's filter dimensions are near-empty today: pharmacy 4, LIS/medicaid 1,
  email 2 (of 4,652 active). So filters must self-populate + honestly distinguish
  "confirmed no" from "not captured yet."

## Guiding principles (Tim)
1. **ONE source of truth for plan/policy/customer counts** — exactly like `app/metrics.py`
   is the single source for commission/book numbers, with a build-failing guard test. No
   view computes plan counts on its own → conflicting counts become impossible by
   construction.
2. **Contract code is the plan identity** — show the full 3-part code (`H1036-335-001`)
   where we have the segment (the segment MATTERS: BCBS Mecklenburg/Union seg 1-2 vs worse
   seg 3-4 benefits — agents use it to infer county + benefit tier), COUNT at the plan
   level (2-part `cms_plan_id`).
3. **The Plan module becomes the authoritative hub** — after linkage repair, every view
   (dashboard, carrier drill-down, customer list, Plan module) cross-references the SAME
   linked Plan data and agrees.
4. **Reuse, don't rebuild** — extend the existing `metrics.py` seam, the existing
   `Plan`/`Policy` models, the existing customers-list filter framework, the existing
   integrity-guard mechanism.

## Build order (dependency-ordered; each layer independently shippable + verifiable)

### Layer 1 — Data foundation: repair plan_id linkage + capture the 3-part code
The whole thing rests on this; counts are meaningless until it's done.
- **Add `Policy.contract_code` (String, nullable, indexed)** — the full raw 3-part
  Contract-PBP-Segment string (`H1036-335-001`) parsed from the BOB row. The Policy still
  LINKS to a `Plan` keyed on 2-part `cms_plan_id` for counting; the raw 3-part rides on the
  policy for display/truth (never lose the segment). Migration adds the column.
- **BOB upload going forward:** parse the contract code from the raw plan_name / carrier
  fields → set `Policy.contract_code`; resolve `Policy.plan_id` via the existing
  `_plan_alias_map` PLUS a new **embedded-code extractor** (regex `H####-###` /
  `S####-###` in the raw plan_name → match a Plan by `cms_plan_id`).
- **One-time repair script** (`scripts/repair_plan_id_linkage.py`, dry-run/--apply,
  read-only planning): for each of the ~64 orphaned plan_names, (a) extract embedded
  contract code → match Plan by cms_plan_id; (b) else alias-match; (c) backfill
  `Policy.plan_id` + `Policy.contract_code`. Report the leftover unmatched names (a short
  list) for Tim/AJ to map by hand (add the alias or create the Plan). Drives
  `plan_id_orphans` toward 0.
- **Auto-create missing Plan rows** where a contract code appears in the book but no Plan
  exists (so the module lists every real plan) — carrier + cms_plan_id + a best-effort
  name from the raw string; flagged `needs_review` for AJ to enrich (benefits/CMS sync).
- **Outcome:** every active policy links to a Plan; the module + drill-down agree.

### Layer 2 — Single-source counts (metrics.py) + guard test
- **Extend `app/metrics.py`**: add `plan_count(scope)` and `by_contract_code(scope)` (and
  a `by_plan` that groups on the LINKED Plan's cms_plan_id, not the raw string). `Scope`
  gains an optional `contract_code` filter. These become the ONLY place plan/contract-code
  counts are computed.
- **Every view reads metrics** — Plan module member counts, carrier drill-down, dashboard
  plan counts, customer-list result count: all via `metrics.py`. None query Policy/Plan for
  counts directly.
- **Guard test** (extend `tests/test_integrity_guards.py` / the existing metrics-guard
  absorbed there): (a) the `plan_id_orphans` invariant must stay at its ratcheted baseline
  (→ 0 after repair) so counts are complete; (b) a NEW consistency invariant asserts the
  contract-code count for a plan is IDENTICAL via the module and via the drill-down (they
  cannot disagree). Build fails if a route computes plan counts outside metrics.py (grep-
  style guard, mirroring the commission-metrics guard).

### Layer 3 — Contract code as plan identity everywhere
- **Display:** wherever a plan appears (customers list column, customer profile policy row,
  carrier drill-down, Plan module list + detail), show the contract code — full 3-part
  (`Policy.contract_code`) on the individual policy where present, 2-part (`Plan.cms_plan_id`)
  for the plan record; plan name as the human-readable subtitle.
- **Count:** every "how many customers/policies" number aggregates by the linked Plan
  (2-part), via metrics.py (Layer 2) → complete + consistent.
- **Click-through:** contract code is a link → Plan detail → that plan's customers
  (filterable, Layer 4).

### Layer 4 — Filterable dimensions (3-state) + the Brian-view
- **Filters** (compose freely; pick a contract code, then narrow): agent, carrier,
  plan-type, **contract-code** (work now); **pharmacy** (main vs TrueCare), **LIS/medicaid**,
  **email**, **hospital-indemnity / DVH / GTL held-plan** (wired now, self-populate).
- **3-state for yes/no attributes** (Brian's "no email vs we just don't have it yet"):
  each such filter offers HAS it / CONFIRMED does-not-have / UNKNOWN (not captured).
  **Mechanism:** a nullable "status" seam per attribute — the value field holds the data
  (e.g. `email`), and a companion nullable flag records "confirmed none". Concretely for
  email: `email` non-empty → HAS; a new nullable `email_status` (`has` | `none_confirmed` |
  NULL) → filter reads it (NULL/empty = UNKNOWN). Reuse the same nullable-flag pattern for
  the other captured-later attributes (pharmacy, LIS) rather than inventing a new mechanism
  per field. LIS: **backfill from the Humana/UHC BOBs** (they carry Low-Income-Subsidy) so
  the filter isn't empty on day one — a real LIS value → HAS; explicit "not LIS" from the
  BOB → none_confirmed; absent → UNKNOWN.
- **The Brian-view + nav:** the Plan module (`/carriers`) is the hub — a plan/contract-code
  list with REAL member counts (from metrics.py), click a code → total count + the filter
  bar → drill down to the filtered customer set. **Fix the nav gap** so the module +
  contract-code view are reachable directly (today the carrier drill-down is only reachable
  via Overview→Humana).

## Architecture / files
- **Models:** `Policy.contract_code` (new col + migration); possibly `Plan.needs_review`
  (bool) for auto-created plans; a "confirmed no email" seam TBD in Layer 4 (nullable field).
- **`app/metrics.py`:** `plan_count`, `by_contract_code`, `by_plan` (linked), `Scope`
  gains `contract_code`. Single source.
- **`app/upload.py`:** parse `contract_code` + embedded-code plan_id resolution on BOB
  import.
- **`scripts/repair_plan_id_linkage.py`:** one-time backfill (dry-run/--apply).
- **`app/carriers.py` + `app/customers.py` + templates:** read counts from metrics.py;
  contract-code column/filter; unify the two plan views; nav.
- **`app/integrity.py` + `tests/test_integrity_guards.py`:** plan_id_orphans → 0 baseline;
  new module-vs-drilldown consistency invariant; guard forbidding out-of-metrics counts.

## Constraints (carry from the codebase)
- Every query agency-scoped. Counts ONLY via metrics.py (guard-enforced).
- The repair script is read-only planning + explicit `--apply`; DB backup first; dry-run →
  review the ~64 mappings WITH Tim → apply; real-Postgres verify; confirm restart cycled;
  times EST/EDT.
- Opus whole-branch review on the data path (Layer 1 backfill touches 4,756 policies).
- No fabricated data: a Plan auto-created from a book code is flagged `needs_review`, not
  presented as CMS-verified. A filter over unknown data shows "unknown", never a false 0.
- Reuse the existing `Plan` provenance seam (`app/plan_provenance.py`) for any benefit
  enrichment; don't blind-overwrite human-verified plan data.

## Explicitly out of scope (YAGNI / later)
- Bulk email/pharmacy/LIS data-ENTRY tooling — the filters self-populate as BOB/agent data
  arrives; a dedicated capture UI is a later project.
- CMS benefit re-sync for auto-created plans (AJ enriches via the existing plan editor /
  CMS sync scripts).
- Reworking the commission modules (this is book/plan data, not money).

## Definition of done
- `plan_id_orphans` at 0 (or the leftover short list explicitly triaged); every active
  policy links to a Plan; `Policy.contract_code` populated where the BOB provides it.
- Contract code shown (3-part where known) + counted (2-part) across dashboard, customer
  list, carrier drill-down, and the Plan module — all agreeing, all via metrics.py.
- Guard test fails the build if plan counts are computed outside metrics.py OR if the
  module and drill-down disagree on a contract-code count.
- The composable 3-state filter set live on the Plan-module hub + customer list; LIS
  backfilled; nav reachable.
- Opus review + real-Postgres backfill verify + deploy.
