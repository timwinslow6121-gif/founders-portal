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
2. **Unique plan identity = YEAR + full CMS code** (`2026+H1036-335-001`). MA/PDP plans are
   1-year benefit contracts — the SAME code in a different year is a genuinely different
   plan (different benefits). Carriers are inconsistent about signaling renewals (some keep
   the old effective date), and CMS silently crosswalks members across codes at year rollover
   (all `H1036-291` → `H1036-335` for 2026; 291 discontinued; the customer "changed plans"
   without anyone submitting a change). So the plan a policy is ON must be tracked per year,
   with the crosswalk/successor history retained **6+ years**. **Show** the full 3-part code
   where the segment is known (the segment MATTERS: BCBS Mecklenburg/Union seg 1-2 vs worse
   seg 3-4 benefits — agents infer county + benefit tier from it); **count** at the
   `year + cms_plan_id` level.
3. **Plan-year is SEPARATE from effective date.** `effective_date` = when the enrollment
   relationship STARTED (permanent; a 2024 eff date means 3-year tenure) → feeds AOR/tenure
   ONLY. **Plan-year** = which year's plan the member is on NOW → the year of the BOB
   snapshot the policy appears in (the July-2026 book = the 2026 plan-year), NOT the eff
   date. A 3-year customer on UHC NC-0015 since 2024 COUNTS in `2026+H5253-117` because they
   are currently on the 2026 version; their 2024 eff date is irrelevant to the plan-year
   count and untouched. AOR records key on eff/term dates, never plan-year → unaffected. No
   double-counting: the same person appearing under `2025+CODE` (historical) and `2026+CODE`
   (current) is correct — that's the year dimension, not a duplicate.
4. **The Plan module becomes the authoritative hub** — after linkage repair, every view
   (dashboard, carrier drill-down, customer list, Plan module) cross-references the SAME
   linked Plan data and agrees.
5. **Reuse, don't rebuild** — extend the existing `metrics.py` seam, the existing
   `Plan`/`Policy` models, the existing customers-list filter framework, the existing
   integrity-guard mechanism. **The `Plan` model already supports year+code identity**:
   `UniqueConstraint(agency_id, carrier, cms_plan_id, year)`, `successor_plan_id` +
   `auto_transitioned` (the crosswalk chain), `status` (current/legacy/sunset/discontinued).
   The gap is thin data (39 plans for 2026, ~1 for 2025/2023, 2 chains) + policies not
   linking to the right YEAR's plan.

## Build order (dependency-ordered; each layer independently shippable + verifiable)

### Layer 1 — Data foundation: capture year + 3-part code, link policy → the right year's Plan
The whole thing rests on this; counts are meaningless until it's done.
- **Add `Policy.contract_code` (String, nullable, indexed)** — the full raw 3-part
  Contract-PBP-Segment string (`H1036-335-001`) parsed from the BOB row (never lose the
  segment). **Add `Policy.plan_year` (Integer, nullable, indexed)** = the BOB snapshot year
  the policy was last seen in (NOT the effective-date year — see principle 3). Migration
  adds both columns.
- **`Policy.plan_id` links to the `Plan` row for `(carrier, cms_plan_id, plan_year)`** — the
  correct YEAR's plan, not just the code. Counting keys on the linked Plan's
  `(year, cms_plan_id)`.
- **BOB upload going forward:** determine the snapshot year (an explicit BOB PlanYear column
  where present — Humana carries one — else the import/as-of date's year) → set
  `Policy.plan_year` + `Policy.contract_code`; resolve `Policy.plan_id` via the existing
  `_plan_alias_map` PLUS a new **embedded-code extractor** (regex `H####-###`/`S####-###` in
  the raw plan_name → match a Plan by `cms_plan_id` AND that year). A member whose BOB code
  changed year-over-year (CMS crosswalk) simply links to the new year's Plan; the successor
  chain records 291→335.
- **One-time repair script** (`scripts/repair_plan_id_linkage.py`, dry-run/--apply,
  read-only planning): for each of the ~64 orphaned plan_names, (a) extract embedded
  contract code → match Plan by cms_plan_id + plan_year; (b) else alias-match; (c) backfill
  `Policy.plan_id` + `Policy.contract_code` + `Policy.plan_year`. Report leftover unmatched
  names (a short list) for Tim/AJ to map by hand. Drives `plan_id_orphans` toward 0. DB
  backup + dry-run → review the ~64 mappings WITH Tim → apply → real-Postgres verify.
- **Auto-create missing Plan rows** where a `(code, year)` appears in the book but no Plan
  exists — carrier + cms_plan_id + year + best-effort name from the raw string, flagged
  `needs_review`. **Must sync with the shipped CMS-plan-info import** (the auto-created row
  is a stub the existing CMS sync scripts + AJ's plan editor enrich via
  `app/plan_provenance.py` — never presented as CMS-verified until enriched) **and agree
  with the BOB + commission imports** (same `(carrier, cms_plan_id, year)` key everywhere).
- **6-year retention:** past-year Plan rows + the successor chain are never deleted; a
  policy's year-history is reconstructable from its Plan links over time (each BOB import
  stamps the plan_year seen). The count for a PAST `year+code` is a historical query over
  that retained data.
- **Outcome:** every active policy links to the correct year's Plan; the module +
  drill-down agree; year-over-year plan history is preserved.

### Layer 2 — Single-source counts (metrics.py) + guard test
- **Extend `app/metrics.py`**: add `plan_count(scope)` and `by_contract_code(scope)` that
  group on the LINKED Plan's `(year, cms_plan_id)` — NOT the raw plan_name string. `Scope`
  gains optional `contract_code` and `plan_year` filters (default plan_year = current year,
  so "customers on this plan" means the current-year version unless a past year is asked
  for). These become the ONLY place plan/contract-code counts are computed.
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
  (`Policy.contract_code`) on the individual policy where present, `year + cms_plan_id`
  (`2026 H5253-117`) for the plan record; plan name as the human-readable subtitle.
- **Count:** every "how many customers/policies" number aggregates by the linked Plan's
  `(year, cms_plan_id)`, via metrics.py (Layer 2) → complete + consistent. Default view =
  the current plan-year; a year selector lets Brian look at a past year's plan.
- **Click-through:** contract code is a link → that year's Plan detail → its customers
  (filterable, Layer 4); the plan detail shows the successor/predecessor chain (e.g. this
  2026 plan came from 2025's H1036-291 via CMS crosswalk).

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
- **Models:** `Policy.contract_code` + `Policy.plan_year` (new cols + migration);
  `Plan.needs_review` (bool) for auto-created plans (enriched via CMS sync + AJ editor); the
  email/pharmacy/LIS 3-state nullable status fields (Layer 4). The `Plan`
  year+code+successor identity already exists — reuse it.
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
  policy links to the correct YEAR's Plan; `Policy.contract_code` + `Policy.plan_year`
  populated where the BOB provides them.
- Contract code shown (3-part where known) + counted by `year + cms_plan_id` across
  dashboard, customer list, carrier drill-down, and the Plan module — all agreeing, all via
  metrics.py; a year selector exposes past plan-years; the successor chain is visible on
  plan detail.
- Auto-created plans carry `(carrier, cms_plan_id, year)` matching the CMS import + BOB +
  commission keys, flagged `needs_review` until enriched.
- Guard test fails the build if plan counts are computed outside metrics.py OR if the
  module and drill-down disagree on a contract-code count.
- The composable 3-state filter set live on the Plan-module hub + customer list; LIS
  backfilled; nav reachable.
- Opus review + real-Postgres backfill verify + deploy.
