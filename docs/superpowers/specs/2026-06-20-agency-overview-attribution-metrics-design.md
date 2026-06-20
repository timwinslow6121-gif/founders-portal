# Agency Overview, Attribution & Shared Metrics — Design (Round 1)

_Date: 2026-06-20 · Status: approved, ready for implementation plan_

## 0. Why this exists

Brian (Founders owner, tech-averse, final say) and AJ meet at 1:30 today. Brian
needs to trust the portal's numbers and to toggle between **whole-agency** data and
**his own agent** data, in the same UI AJ sees. Today the Agency Overview is
misleading and wrong:

- **Agent counts are wrong.** Brian shows **481** active policies; his real book is
  ~**1,200**. On the live VPS: **5,187 active policies, but only 2,342 have an
  `agent_id` — 2,845 (55%) are NULL/unattributed.** The agent breakdown only sums
  the attributed half. **2,799 of the NULL policies already carry a carrier
  writing-ID** (`Policy.agent_id_carrier`) that maps to a real agent — it was just
  never resolved.
- **The commission cards are useless.** "Est. Monthly Commission" applies a flat
  55% split to every agent (wrong — Betty/Mike are 52.5%, real splits live in
  `AgentCarrierContract`); "Est. Annual — MAPD flat rate only" ignores that the book
  includes Medigap/PDP/DVH/hospital-indemnity. The estimate is derived from policy
  counts × a hardcoded rate (`MAPD_MONTHLY_RATE`/`SPLIT_RATE` in `app/routes.py`).
- **Numbers are computed in ~10 different files** with no shared source, so the same
  agent can show different totals on different pages (the Agency Overview and the
  agent-detail page already use the same fake estimate and can diverge from the
  ledger). This is the drift that makes the system untrustworthy and hard to reason
  about.

This spec is **Round 1**. It makes the numbers *real and consistent* and gives Brian
his toggle. It deliberately defers the deep date-aware reconciliation engine
(Round 2) and the whole-codebase audit/map (Round 3) — see §8.

## 1. Governing principle (non-negotiable, applies portal-wide)

1. **One `app/metrics.py` is the only place book/money numbers are computed.** Every
   page is a thin caller passing a *scope* `(agent_id, carrier, period)`. No page
   writes its own `.query.filter().count()` for these numbers.
2. **Book numbers come from BOB (the `Policy` table).** Counts, carrier mix, plan
   mix, upcoming terms. **Money comes from the commission ledger
   (`CommissionLineItem` via `split_breakdown`).** We never estimate money from
   policy counts again.
3. **Book and money are shown side by side; disagreement is surfaced honestly, never
   hidden.** Round 1 shows a "**N to reconcile →**" pointer (an honest count of
   book-vs-ledger mismatches). Round 2 turns that into a date-aware verdict (lag vs.
   real gap).

This principle is enforced by a **guard test** (§6) so it can't silently erode.

## 2. What already exists vs. what we build (inventory — so this question is never re-derived)

| Capability | State today | This spec |
| --- | --- | --- |
| `app/metrics.py` shared layer | ❌ does not exist | **BUILD** (§3a) |
| Writing-ID → agent resolution (commission path) | ✅ live (`AgentCarrierContract.id_value`, used by UHC/commission parsers + `ingest.py`) | reuse / extract shared resolver |
| Writing-ID → agent resolution (BOB path) | ❌ missing — `upload.py` stores `agent_id_carrier` but never resolves it (the bug) | **BUILD** (§4) |
| Per-carrier writing-ID map completeness | 🟡 UHC ~complete; Humana SANs + several carriers missing | **re-resolve + infer-and-confirm** (§4) |
| `seed_uhc_writing_ids.py` | ✅ exists, **UHC-only** | generalize to all carriers |
| Reconciliation module (`_reconcile`, 2 routes, template, in nav) | ✅ live but agent-id-keyed → **blind to the 2,799 NULL policies** | fixed *for free* once attribution lands; deeper work = Round 2 |
| Carrier brand color map | 🟡 trapped in `recap.html` JS | **promote to `app/branding.py`** (§5a) |
| Carrier drill-down page / honest dashboard / Brian toggle | ❌ net-new | **BUILD** (§3b, §5) |
| Date-aware reconciliation (stale-BOB, lag, freshness) | ❌ | **Round 2** (§8) |
| Whole-codebase map + route-integrity/orphan checks | ❌ | **Round 3** (§8) |

## 3. Components

### 3a. `app/metrics.py` — the shared codepath

Pure functions, each taking a *scope* `Scope(agent_id=None, carrier=None,
period=None, agency_id=…)`:

- `policy_count(scope) -> int` — active policies (BOB), scoped.
- `book_breakdown(scope) -> {by_carrier, by_plan_type, by_plan, by_agent}` — each
  entry `{key, count, pct}`. `pct` is share of the scoped total.
- `commission_totals(scope) -> {paid, agent_payout, founders_keep}` — from the
  ledger, reusing `split_breakdown` (never re-deriving the split). Scoped by
  agent/carrier/period.
- `upcoming_terms(scope, days=30) -> [ {member, plan, term_date, reason, customer_id} ]`.

These are unit-tested directly (TDD). A number proven correct here is correct on
every page.

### 3b. Honest Agency Overview (`app/routes.py:admin_overview` + `admin_overview.html`)

Cards become:

1. **Total Active Policies** (BOB) + an **attribution-coverage** line:
   "✓ 100% attributed" once backfill runs, else "N unattributed →" linking to the
   Unattributed Policies view.
2. **Upcoming Terms (30d)** — count, links to the term list. (Honors the AEP note:
   outside AEP terms cluster at the 1st of next month — we show dates, not a rolling
   guess.)
3. **Commissions — latest period (actual)** — `commission_totals` for the latest
   period: agency payout + Founders keep, tagged with the period label
   (e.g. "May 2026"). **The flat-55%/MAPD estimate is deleted.**
4. **Book ↔ Pay** — "**N policies to reconcile →**" (Round 1: honest count of
   book-vs-ledger mismatches from the existing `_reconcile`, now seeing the full
   attributed book; links to the reconciliation page). Round 2 makes it a verdict.

**Agent Breakdown table:** same `metrics` calls per agent → Brian shows ~1,200.
Money columns come from the ledger (real per-agent payout), not the estimate.
Top-carrier chips use brand colors (§5a).

### 3c. `agent_detail` page (`app/routes.py:agent_detail`, ~lines 80-91)

Migrated onto `metrics.py` too — it currently uses the same fake
`MAPD_MONTHLY_RATE`/`SPLIT_RATE` estimate and would otherwise contradict the
overview. After migration, `MAPD_MONTHLY_RATE` and the duplicated `SPLIT_RATE`
constants are **deleted** (§6, delete-don't-orphan).

## 4. Attribution fix

The contract map is mostly already correct; the failure is that resolution only ran
at certain upload moments, leaving policies NULL even when the map knew the answer
(e.g. Rebekah's UHC writing ID `6435806` is 100% NULL on policies despite being in
her contract row). So the backfill is primarily a **re-resolution pass**, not
guessing.

**4a. Complete the per-carrier writing-ID map.** Each carrier uses its own ID system
(confirmed with Tim):

| Carrier | ID system | Example (Tim) |
| --- | --- | --- |
| Humana | Agent SAN | `1839547` |
| UHC | AgentID | `6337213` |
| Devoted, Aetna (MAPD & PDP — *not* Medigap, which is AHIP/agent-ID), Healthspring | NPN | `18708064` |
| BCBS | Producer code (pcode/pnumber) | `P0056227` |
| Medico / Wellabe | Writing Agent # | `143893WDL3` |
| GTL | Agent Code | `0118BK05` |

Note: for **UHC the portal keys on the AgentID, not the NPN.** Rebekah's UHC AgentID
`6435806` is shared-with-Founders by design (the agency writes under one writing
entity); her personal NPN (`20388847`) is *not* the UHC matching key and is not
stored. This is expected, not a conflict.

Process: pull every distinct `agent_id_carrier` off NULL-agent policies per carrier,
cross-reference the commission files (where many already resolve to an agent), and
**present Tim a confirmation table** (ID → proposed agent + policy count). Tim
confirms/corrects → seed `AgentCarrierContract.id_value`. **No data changes before
sign-off.** In practice UHC needs ~no new entries; **Humana SANs** are the main gap.

**4b. Shared resolver + backfill.** New
`resolve_writing_agent(carrier, writing_id, agency_id) -> agent_id | None`. Backfill
script walks NULL-agent active policies, resolves via the confirmed map, sets
`agent_id`. **Dry-run first** (prints per-agent before/after), `--apply` to commit,
**idempotent**, **DB backed up first**. Unresolved IDs stay NULL and surface in an
**Unattributed Policies** admin view (mirrors the existing unassigned-customers
view) for AJ to clean up over time.

**4c. Wire into BOB upload** (`app/upload.py`): after storing `agent_id_carrier`,
call `resolve_writing_agent` and set `agent_id` on admin uploads so attribution
stays fixed. Self-service agent uploads still self-attribute (unchanged).

**Guardrail (map-integrity only):** the resolver maps a writing ID to a *book
owner*. The Founders override is a **commission classification** on the ledger (same
writing ID, same agent — `split_breakdown` keeps the money), **never** a separate
book attribution, so it creates no ambiguity here. The guardrail fires only when the
*same* writing ID appears under *two different agents'* contract rows for a carrier
(a seeding typo): that ID is left unresolved and surfaced in the Unattributed view,
never guessed.

## 5. Carrier drill-down, brand colors, Brian's toggle

### 5a. `app/branding.py` — one carrier-color source

Promote the `CARRIER_BRAND` map from `recap.html` JS to a server-side module
(`CARRIER_BRAND` dict + `carrier_color(name)`, default Founders blue `#266EA5`;
Wellabe/Medico collapse handled here). Recap, dashboard chips, and the carrier page
all read it. One place to edit a color.

### 5b. Carrier drill-down page — `/carriers/<carrier>`

Admin/owner; agent-scoped when Brian is in "My view". Linked from every carrier box
on the dashboard. All data from `metrics.py`; **Material 3 Founders UI**. Sections
(mockup approved 2026-06-20):

1. **Hero band** — full carrier brand color: name, total active policies, % of agency
   book.
2. **Proof strip** — attribution coverage ("✓ 100% attributed · Σ agents = total · 0
   orphan"), the carrier's commission **balance badge** (reuse existing
   `balance_status`), data source/freshness.
3. **Policy type mix** — MA/MAPD, D-SNP/C-SNP, Medigap, PDP, DVH — `#`/`%`
   (`by_plan_type`).
4. **Agent share of the carrier book** — `#`/`%` per agent (`by_agent`).
5. **Plans table** — per-plan `#`/`%` + **est. monthly commission** (clearly labeled
   *est.*, derived from the plan's real rate — **not** shown as actual paid), each
   row → plan detail.
6. **Upcoming terms (30d)** — count + actual term dates (honest about 1st-of-month
   batching outside AEP), linking to those members.

Deferred (not this spec): full Carriers & Plans rebuild down to plan→member. This
page is the new carrier-level entry point; existing plan list/detail remain the
deeper level.

### 5c. Brian's agency/own toggle

An "Agency view / My view" scope switch on the dashboard, agent breakdown, and
carrier pages. Available to admins + owners (Brian). It only flips the *scope object*
passed to `metrics` — "My view" sets `scope.agent_id = current_user.id`. Because
every page routes through `metrics`, the toggle is nearly free and **self-verifying**:
Brian's "My UHC" is literally the carrier page's "Brian" row. Persists per session
(no DB).

## 6. Safeguards (keep the system coherent without Tim tracking it in his head)

All four approved:

1. **Guard test (build fails on drift).** A test that scans route files for raw
   `Policy.query…count()` / `func.count(Policy…)` / book-or-money computation outside
   `app/metrics.py` and **fails** if a new one appears. Machine-enforced — the metric
   drift bug cannot be silently reintroduced. (Existing pre-metrics call sites are
   either migrated or added to an explicit, shrinking allowlist with a reason.)
2. **Trust-map table.** A living table (in this spec + referenced from the Session
   Protocol) listing every metric surface and its state: ✅ on `metrics.py` / ⚠️
   computes its own / ❌ deleted. The canonical "coherent vs. stale vs.
   coded-no-UI" answer, in the repo. Initial state:

   | Surface | State after Round 1 |
   | --- | --- |
   | Agency Overview (`admin_overview`) | ✅ metrics.py |
   | Agent detail (`agent_detail`) | ✅ metrics.py |
   | Carrier drill-down (new) | ✅ metrics.py |
   | Agent recap (`recap.py`) | ✅ ledger via `split_breakdown` (already canonical for money) |
   | Reconciliation (`_reconcile`) | ⚠️ own query — correct once attributed; Round 2 rebuilds |
   | `MAPD_MONTHLY_RATE` / `SPLIT_RATE` estimate | ❌ deleted |

3. **Migrate `agent_detail` + delete fake constants.** Pull `agent_detail` onto
   `metrics.py`; **delete** `MAPD_MONTHLY_RATE` and the duplicated `SPLIT_RATE`
   constants (`app/routes.py`, `app/commission/routes.py:27`) so the wrong estimate
   can't resurface.
4. **Delete-don't-orphan.** This spec lists what is removed (the fake-estimate cards
   + constants). Nothing is left dangling/ambiguous. If Round 2 replaces a
   reconciliation surface, that removal is listed there.

## 7. Testing & rollout

- **TDD on `metrics.py`** — it's the keystone; unit-test each function against
  fixtures before wiring pages.
- **Guard test** (§6.1) added to the suite.
- **Attribution backfill verified on real Postgres** — DB backed up → dry-run → Tim
  confirms the map table → `--apply` → confirm **Brian ≈ 1,200**, **Σ agents = agency
  total, 0 orphan**. (Per project discipline: money/attribution changes proven on
  Postgres, not just SQLite tests.)
- **No new migration expected** (Unattributed view reuses NULL `agent_id`; branding
  is a module; metrics is read-only). If one proves necessary it is called out in the
  plan.
- **Deploy:** merge → VPS pull → run backfill (`--apply`) → restart. Material 3 +
  brand colors are template/CSS only.

## 8. Explicitly OUT of scope (tracked, not forgotten)

- **Round 2 — date-aware BOB↔commission reconciliation engine.** As-of date
  comparison (stale BOB labeled "N days older than the statement", not flagged
  wrong); **saved-customer chargeback / CMS-lag detection** (chargeback present but
  BOB still active → "likely reverses next cycle", not a real loss); **per-agent BOB
  freshness** (self-service agents Tim/Justin/Rebekah/Chris can refresh anytime; LOA
  agents Mike/Betty/Anjana are only as fresh as the last Founders pull — never
  penalized for a book Founders hasn't refreshed). Round 1's "N to reconcile →"
  pointer is this engine's front door. Gets its own spec.
- **Round 3 — whole-codebase audit & map.** `/gsd:map-codebase` (top-down structured
  map in `.planning/codebase/`) + a **route-integrity test** (every `url_for` /
  nav link resolves to a live route) + an **orphan-page test** (every registered
  route is reachable or explicitly marked internal) wired into the suite. Addresses
  the "cobweb of links/pages/calculators, hidden pages, fake-vs-real data fighting"
  worry across the whole portal. Gets its own spec.
- Full Carriers & Plans module rebuild (plan→member level).
- Phase 2 AOR / policy supersession (already paused mid-design in BACKLOG).

## 9. Roadmap summary

- **Round 1 (this spec):** attribution fix + `metrics.py` + honest dashboard +
  carrier drill-down + Brian's toggle + brand colors + 4 safeguards. Ships for the
  1:30 Brian meeting.
- **Round 2:** date-aware reconciliation engine.
- **Round 3:** whole-codebase audit & map + route-integrity/orphan checks.
