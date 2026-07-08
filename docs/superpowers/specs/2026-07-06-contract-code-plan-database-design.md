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
2. **Plan identity is PLAN-TYPE-DEPENDENT — there are two models:**
   - **Year-bound (MA / MAPD / PDP / DSNP / CSNP):** identity = `(carrier, cms_plan_id,
     YEAR)` (`2026+H1036-335-001`). These are 1-year benefit contracts — the SAME code in a
     different year is a genuinely different plan (different benefits). Carriers are
     inconsistent about signaling renewals (some keep the old effective date), and CMS
     silently crosswalks members across codes at year rollover (all `H1036-291` → `H1036-335`
     for 2026; 291 discontinued; the customer "changed plans" without submitting one). Track
     the plan a policy is ON per year, retain the crosswalk/successor history **6+ years**.
     **Show** the full 3-part code where the segment is known (the segment MATTERS: BCBS
     Mecklenburg/Union seg 1-2 vs worse seg 3-4 benefits — agents infer county + benefit tier
     from it); **count** at the `year + cms_plan_id` level.
   - **Year-INDEPENDENT (Medigap, DVH, Dental, Hospital-Indemnity, GTL):** these carry NO CMS
     contract code and their benefits do NOT change annually — "2019 Plan G" = "2026 Plan G"
     (the "2019" is a standardization *vintage*, not an annual benefit year). Identity =
     `(carrier, plan_letter)` for Medigap (G/N/F — the LETTER is the identity), `(carrier,
     normalized plan_name)` for DVH/Dental/Hospital-Indemnity/GTL. **ONE Plan row per such
     plan**, with a **`PERPETUAL` year sentinel (`year = 0`)** meaning "not year-bound." A
     customer on Plan G counts in the single Plan G row regardless of enrollment year — never
     split into fake 2025-vs-2026 duplicates. (The `Plan` model already has `plan_letter` for
     Medigap.)
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
- **`Policy.plan_id` links to the right Plan by the PLAN-TYPE identity rule:**
  - Year-bound (MA/MAPD/PDP/DSNP/CSNP) → the `(carrier, cms_plan_id, plan_year)` Plan.
  - Medigap → the `(carrier, plan_letter, year=PERPETUAL)` Plan (extract the letter G/N/F
    from the plan_name; `Policy.plan_year` = PERPETUAL sentinel 0).
  - DVH/Dental/Hospital-Indemnity/GTL → the `(carrier, normalized plan_name, year=PERPETUAL)`
    Plan.
  A `PERPETUAL = 0` constant lives in `app/plan_codes.py`. Counting keys on the linked Plan
  (year-bound: `(year, cms_plan_id)`; year-independent: the Plan row itself, year ignored).
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

### Layer 5 — Annual refresh workflow (the recurring AEP chore, not a scramble)
Plan data is not one-and-done: each October/November CMS publishes next year's ~187 NC plans
+ crosswalks (`H1036-291` → next year's version). Make the yearly refresh a documented,
one-command flow so AEP isn't a fire drill:
- `seed_plan_buckets.py --year <next>` from next year's CMS Landscape → creates the new
  year's buckets; `sync_cms_plan_data.py` enriches them.
- **Auto-populate the successor/crosswalk chain** (`Plan.successor_plan_id` +
  `auto_transitioned`, which already exist) from the CMS crosswalk file so members on a
  discontinued plan carry to its successor without anyone submitting a change. 6-year
  retention: old-year Plan rows + chains are never deleted.
- This is how HealthSherpa/MedicareCenter stay current (they hit CMS APIs live by
  code+ZIP); we do the file-based equivalent annually. At 8 agents / one metro / ~187 plans
  it's a genuinely small annual chore — the design just makes it repeatable, not manual.

### Layer 6 — County + segment awareness (agent geography intelligence)
The CMS Landscape carries **County per plan-segment** — the data behind Tim's own example
(BCBS Mecklenburg/Union get segment 1-2 with better benefits; other counties only get
segment 3-4). Capture which counties each plan-segment serves so an agent seeing a
segment-1 plan instantly knows the county + benefit tier without asking. Store as a
per-(plan, county) association (or a `service_counties` field on the segment-level Plan).
Nearly free — the seed already reads the CMS rows that carry it. High value for how the
team actually works a lead.

### Layer 7 — Pharmacy ↔ plan network status (the pharmacy-partnership lens) — CUSTOMER-FIRST
**Framing (Tim, non-negotiable):** Agents' fiduciary duty is to the CUSTOMER, always. We
recommend the plan that is genuinely best for the customer (their drugs, copays, benefits,
doctors). Deep pharmacy-contract knowledge makes us BETTER agents FOR THE CUSTOMER — it is
NOT a tool to steer customers to pharmacy-profitable plans. The pharmacy lens is a
**tie-breaker ONLY**: when the customer-facing options are genuinely equivalent (same
relevant drug copays + benefits), THEN — all else equal — favoring the plan that also keeps
a partner pharmacy healthy is the ethical long game (a surviving independent pharmacy serves
far more patients over time than any single steered enrollment; needs-of-the-many in a true
tie). The feature SURFACES pharmacy-network status as one informed data point; it must never
be presented as a profit-optimization/steering engine.

**Why it matters:** Founders exists because independent pharmacies (Cannon Main, Cannon
Sedgefield, TrueCare) partnered with agents who bring Medicare expertise — the pharmacies'
health is the hand that feeds the agency. A plan reimburses a pharmacy by that pharmacy's
network status with the plan's PBM: **preferred in-network** (best), **standard in-network**
(lower), **out-of-network** (worst/none). Same customer, same plan, different pharmacy →
different pharmacy margin.

**Data model:** a `PlanPharmacyNetwork` many-to-many — `(plan_id, pharmacy_id) → status`
(`preferred` | `standard` | `out` | `unknown`). Human-maintained per the pharmacies' real
PBM contracts (the pharmacy owners know these); a small table (partner pharmacies × the ~187
plans, mostly a handful of pharmacies). Surfaces on the plan detail + as a
customer-list/plan filter: e.g. "customers on a plan where their pharmacy is out-of-network"
= a *service opportunity to review at the customer's next annual check* (is there an equally-
good-for-them plan where their pharmacy is preferred?), NOT an auto-steer. Reuse the existing
`Pharmacy` model + `pharmacy_agents` pattern.

### Layer 8 — SOB / EOC in-context (make the portal a pleasure, not a filing cabinet)
**The north star (Tim):** the portal should be where the team LIVES — we only leave for the
few things it genuinely can't replace (e.g. enrollments). A "Download SOB.pdf" link is the
lazy fix ("here's the data, find it yourself, bugger off") — and it fails the real pain:
*"we can't remember if/when/where we last downloaded it."* We are NOT re-keying 200-page
docs into fields (infeasible; the top-asked facts — copays/premium/MOOP — are already
structured). We want the DOCUMENTS themselves navigable + searchable IN the portal, in the
context of the plan you're already looking at.

**Scope:** the two authoritative docs per plan-year — **SOB** (Summary of Benefits, ~10-20pp)
and **EOC** (Evidence of Coverage, 200+pp). Stored per `(plan, year)` (the `Plan.sob_url`
seam already exists; extend for EOC).

**Growth path (build the cheap tier first; each tier is independently useful):**
- **v1 — In-portal searchable viewer.** A pop-up that renders the SOB/EOC without leaving
  the portal, with in-document find. Solves "can't remember where I downloaded it" +
  "don't want to leave the portal." Modest build.
- **v2 — Full-text search across a plan's docs.** Extract the PDF text and index it, so
  typing "insulin copay" or "skilled nursing prior auth" jumps to the passage/page. The
  "type a question, land on the answer" experience.
- **v3 — Ask this plan a question.** RAG over the SOB/EOC → plain-English answers with a
  citation ("does this cover Ozempic?" → the passage + page). Most ambitious; needs the
  extracted text + an LLM call. Default to the latest Claude model when built.

Its own project, sequenced after the core plan-database layers are live and the team can see
how they use the plan pages in practice.

## Architecture / files
- **Models:** `Policy.contract_code` + `Policy.plan_year` (new cols + migration);
  `Plan.needs_review` (bool) for auto-created plans (enriched via CMS sync + AJ editor); the
  email/pharmacy/LIS 3-state nullable status fields (Layer 4). The `Plan`
  year+code+successor identity already exists — reuse it.
- **`app/metrics.py`:** `plan_count`, `by_contract_code`, `by_plan` (linked), `Scope`
  gains `contract_code`. Single source.
- **`scripts/seed_plan_buckets.py`:** create the ~187 NC buckets from CMS (Layer 1);
  `scripts/sync_cms_plan_data.py` (exists) enriches them. Complementary.
- **`app/plan_codes.py` + `app/plan_bucket.py`:** sorting keys + `find_plan_bucket`
  (sort-into-existing-bucket, never create).
- **`app/upload.py`:** set `contract_code`/`plan_year`/`plan_id` via `find_plan_bucket`;
  a miss → plan_id NULL + review queue.
- **`scripts/repair_plan_id_linkage.py`:** one-time backfill (dry-run/--apply).
- **`app/carriers.py` + `app/customers.py` + templates:** read counts from metrics.py;
  contract-code column/filter; unify the two plan views; nav.
- **`app/integrity.py` + `tests/test_integrity_guards.py`:** plan_id_orphans → 0 baseline;
  new module-vs-drilldown consistency invariant; guard forbidding out-of-metrics counts.
- **Layer 6:** `service_counties` on the segment-level Plan (or a plan↔county assoc).
- **Layer 7:** `PlanPharmacyNetwork` model `(plan_id, pharmacy_id, status)`; reuses the
  existing `Pharmacy` model; surfaced on plan detail + as a filter.

## Constraints (carry from the codebase)
- Every query agency-scoped. Counts ONLY via metrics.py (guard-enforced).
- The repair script is read-only planning + explicit `--apply`; DB backup first; dry-run →
  review the ~64 mappings WITH Tim → apply; real-Postgres verify; confirm restart cycled;
  times EST/EDT.
- Opus whole-branch review on the data path (Layer 1 backfill touches 4,756 policies).
- **Buckets first, sort don't create** (jelly-bean model): the parser matches a BOB row to
  an EXISTING seeded bucket; it NEVER auto-creates a Plan on a failed match. A miss → the
  policy stays plan_id=NULL + is surfaced to a human review queue (map it, or deliberately
  confirm a genuinely-new bucket). This prevents "an orange bean in the red bucket."
- No fabricated data: a filter over unknown data shows "unknown", never a false 0.
- Reuse the existing `Plan` provenance seam (`app/plan_provenance.py`) for any benefit
  enrichment; don't blind-overwrite human-verified plan data.
- **Pharmacy-network is customer-first, tie-breaker-only** (Layer 7) — surfaced as an
  informed data point, never a steering/profit-optimization engine.

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
- The ~187 NC buckets are seeded from CMS (`(carrier, cms_plan_id, year)`) + supplemental
  plans; the BOB parser sorts into them; unmatched rows are queued for human review, never
  auto-bucketed.
- (Later layers) annual refresh is one command per year with the crosswalk chain auto-
  populated; county/segment captured; the `PlanPharmacyNetwork` relationship surfaced
  customer-first as a tie-breaker signal.
- Guard test fails the build if plan counts are computed outside metrics.py OR if the
  module and drill-down disagree on a contract-code count.
- The composable 3-state filter set live on the Plan-module hub + customer list; LIS
  backfilled; nav reachable.
- Opus review + real-Postgres backfill verify + deploy.
