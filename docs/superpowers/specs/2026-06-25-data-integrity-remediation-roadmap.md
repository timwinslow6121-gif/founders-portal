# Data-Integrity Remediation Roadmap

_Date: 2026-06-25 · Status: roadmap approved by Tim; each numbered item becomes its own
spec → plan → build → deploy. Supersedes the narrow `2026-06-25-cross-page-count-
consistency-design.md` (absorbed as item 5)._

## Why this exists

Tim stress-tested the portal (2026-06-25) and found 5 discrepancies in minutes. A live
audit showed they are **three root problems**, not five symptoms, and they are
portal-wide — confirming Tim's "a lot needs fixing / is the portal FUBAR" worry is
real and quantified. Governing principle (Tim): **nothing blank, nothing of unknown
origin, nothing duplicated; every displayed number traceable to correct underlying
data.**

### The 5 reported symptoms → 3 root causes

| # | Symptom (Tim) | Root cause | Roadmap item |
|---|---|---|---|
| 3 | Search "John" → "Connelly, John" ×5 | **Duplicate customer records** — 1 real person split across 5 rows | #2 (cure) + #1 (prevent) |
| 1 | 56 `uhc::0::2` stubs in needs-name | Stub garbage from commission import | #1 (prevent) + #2 (merge/clean) |
| 4 | Can't edit MBI when already used | No merge path for no-MBI dups / MBI-collision | #2 |
| 2 | Needs-match can't pick a suggested agent ("no match found, queued") | Missing resolve ACTION in the hub | #4 |
| 5 | Plan "Gold Plus H1036-335" 250 vs Humana 1701 | **`plan_id` FK orphaned** — counts computed off different keys | #3 (linkage) + #5 (consistency) |

### Live audit numbers (2026-06-25, agency_id=1)

- **Customers:** 5,174 total; **571 are `stub=True`**.
- **Duplicate clusters:** 107 name-collision clusters; **152 excess mergeable rows.**
  Worst: Andrea Horstmann ×6 (4 stubs), James McIntyre ×6, **John Connelly ×5** (3
  stubs + "John Connelly" w/ MBI 4RH5X85DC65 + "John Connelly Iii") — Tim confirms ALL
  5 are ONE person whose policies he wrote.
- **Plan_id orphans:** **90% of active policies have NULL `plan_id`** — only 524 of
  5,135 link to a Plan record. (Gold Plus H1036-335: 1,701 policies by plan_name, only
  113 linked by plan_id → the 250-vs-1701 mismatch.)

## Grounding case (carry through every item)

**John Connelly** — 5 customer rows that are ONE person:
- id=1367 `John Connelly` — **the keeper** (real MBI 4RH5X85DC65, DOB 1953-04-07)
- id=1419 `John Connelly Iii` — same person (DOB matches), no MBI
- id=4239, 4243, 5960 `CONNELLY, JOHN` — stub=True, no MBI/DOB, from commission import

Tim wrote these policies; he is certain it's one customer. The fix must (a) stop the
import from creating these stubs when the person already exists, and (b) merge the 5
into 1, reconciling MBI/DOB/name/policies/AOR onto the keeper.

## The roadmap (build in this order — prevention before/with cure, linkage, then display)

### 1. Stub-creation PREVENTION (fix the source)
**Goal:** commission import must MATCH an existing customer instead of spawning a new
`CONNELLY, JOHN` stub. **Why first:** stops the bleeding — merging dups (item 2) is
futile while the importer keeps regenerating them.
**Investigate:** why `_create_stub`/resolver made 3 separate Connelly stubs when a real
John Connelly (with MBI) already existed. Likely the commission rows carry a NAME but no
MBI, and the matcher only matches on MBI/carrier_member_id → name-only rows always
create. Strengthen the match ladder: name + DOB, or name + carrier_member_id, or
corroborated composite (the identity-recovery work already built `app/identity.py` +
the corroborated matcher — reuse it), and ONLY create a stub when no corroboration
exists. **Grounding:** re-running the import must not recreate a Connelly stub.
**Out of scope:** merging the EXISTING dups (item 2).

### 2. No-MBI customer MERGE (the cure) — clean the 152
**Goal:** a way to collapse a duplicate cluster into one profile, even when the dups
have NO MBI (the existing merge UI only catches MBI-duplicates, so it never saw these).
Reconcile MBI/DOB/name/phone/address (manual > real > stub), reattach all Policies +
PolicyPayments + AOR intervals + notes to the keeper, delete the emptied dups. **Also
delivers #4** — when editing an MBI that's "already used," offer "these look like the
same person — merge?" instead of a hard error. **Run on the 152** (dry-run → apply, DB
backed up). **Grounding:** John Connelly → 1 profile (keeper id=1367, adopts DOB from
1419, absorbs the 3 stubs' policies, 4 rows deleted). **Depends on:** item 1 ideally
shipped first (else dups refill).

### 3. `plan_id` LINKAGE repair (fix #5)
**Goal:** link the 4,611 orphaned active policies to their Plan record so plan-page
counts and carrier counts come from the same key. **Investigate:** the BOB upload
already calls `_plan_alias_map` to resolve `plan_id` on upsert — why is it NULL on 90%?
(Likely: alias map incomplete, or older policies predate the resolver, or plan_name
strings don't match aliases.) Backfill `Policy.plan_id` from plan_name via the alias
resolver (dry-run → apply); report unmatched plan_names for AJ to alias. **Guard:** a
test/measure so plan_id coverage can't silently regress. **Grounding:** Gold Plus
H1036-335 plan page shows ~1,701, matching the carrier breakdown's Humana Gold Plus
line.

### 4. Hub RESOLVE actions (fix #2, partial #4)
**Goal:** make the Needs-Identity hub's needs-match / needs-name tabs ACTIONABLE — pick
an agent or customer, one click, it resolves (currently informational only, "no match
found, queued"). Reuse item 2's merge + the agent-set route. **Depends on:** items 1-2
(the matchers + merge they build).

### 5. Count consistency + guard (the original narrow spec, folded in LAST)
**Goal:** all carrier book counts via `app/metrics.py`; show "N members · M policies"
everywhere; add `app/customers.py` to the guard's `SCANNED`; a consistency test that
fails if two pages diverge. **Why last:** now that items 1-3 make the underlying
numbers CORRECT (no dup-stub inflation, no plan_id orphans), making the pages agree
means they agree on RIGHT numbers. Full design already drafted in
`2026-06-25-cross-page-count-consistency-design.md` — absorb it here as item 5.

## Sequencing rationale
Prevention (1) before cure (2) so cleanup doesn't refill. Linkage (3) is independent and
can run in parallel but is sequenced after the dup work so plan counts aren't computed
over duplicate customers. Hub actions (4) reuse 1-2's matchers. Count consistency (5)
last so it displays already-correct numbers. Each item is independently shippable and
DB-backed-up + Postgres-verified per the project protocol.

## Out of scope (separate, later)
Round 2 (date-aware BOB↔commission reconciliation) — depends on this being done.
The 103 no-name policies overlap item 1/2 (name recovery) and will be folded into
whichever lands first. UI/Material-3, breadcrumbs, infra (backup/cert) unchanged.

## Next step
Brainstorm **item 1 (stub-creation prevention)** into a full design spec, then plan →
build → deploy. Then item 2, etc.
