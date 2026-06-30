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

## The roadmap (build in this order — radar first, then prevention, cure, linkage, display)

### 0. Data-Integrity Radar & Guard Suite (BUILD FIRST) — ✅ SHIPPED + LIVE 2026-06-26
**Status:** Done (merge edbc991, baseline 7da4dd9). `app/integrity.py` registry + 10 invariants +
`scripts/audit_integrity.py` CLI + `/admin/integrity` dashboard + `tests/test_integrity_guards.py`
ratchet against `integrity_baseline.json`. Frozen prod baseline = the live debt (see below). Opus
whole-branch review clean. **LIVE DEBT (the work items 1-5 drive to 0):** plan_id_orphans=4611,
orphan_stub_customers=571, payment_without_customer=76, no_name_policies=56, duplicate_customers=18
(high-confidence; NULL-dob name matches excluded). Each remediation item below now = "clean its
invariant to 0 + ratchet the baseline down."
**Goal:** the radar + ratchet that ends whack-a-mole. One `@invariant` registry
(`app/integrity.py`) feeding a CLI, an `/admin/integrity` dashboard, and a CI guard with
a baseline ratchet (fails only if a count goes ABOVE its frozen baseline → existing debt
doesn't block, nothing gets worse). Covers data + cross-page-consistency + route/page
invariants. Written **lifecycle-aware** (manual leads with no MBI are VALID, not
violations) and **multi-AOR-aware** (a person with 2 concurrent AORs is ONE customer,
not a dup). Full design: `2026-06-25-data-integrity-radar-design.md`. **Why first:** it's
how we PROVE items 1-5 worked and the net that stops new corruption while we fix.

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

### 6. Lead lifecycle (stage-driven) + auto-advance
**Goal:** make the existing `deal_stage` (`Lead/Enrolled/.../Active/Termed`) +
`source='manual'` actually govern who is a Lead vs a Customer. Agents add a
new-to-Medicare person (demographics, no MBI yet) as a Lead; they don't count in
book/customer metrics until `deal_stage='Active'`, which **auto-advances when
effective_date passes** (nightly job) OR a BOB/commission row confirms them. A Leads
filter/view so leads are visible but not polluting customer counts. (Radar item 0
already EXEMPTS non-Active stages; this item makes the transition real.) Grounding:
a new-to-Medicare lead entered mid-month stays a Lead until their 1st-of-month eff date.

### 7. AOR is per-policy (multi-AOR model-truth fix)
**Goal:** retire the single `Customer.primary_agent_id` as "the agent." A person can have
2 concurrent policies with 2 different AORs (Rebekah=MAPD, Tim=hospital-indemnity, same
person). AOR truth already lives in `CustomerAorHistory` (per carrier, own agent_id).
Migrate attribution / access-control / counts to derive the agent(s) from the POLICY's
AOR; a customer's agents = the SET across their active policies. **Likely a root cause of
some dup stubs** (a 2nd agent's commission row can't fit the single field → a 2nd
customer gets spawned), so this reinforces items 1-2. Bigger blast radius (touches
metrics, access, attribution) → its own spec when reached. Grounding: the Rebekah+Tim
shared customer shows both, each scoped to their policy, as ONE customer row.

## Out of scope (separate, later)
Round 2 (date-aware BOB↔commission reconciliation) — depends on this being done.
The 103 no-name policies overlap item 1/2 (name recovery) and will be folded into
whichever lands first. UI/Material-3, breadcrumbs, infra (backup/cert) unchanged.

## Next step (updated 2026-06-30)
**Items 0 ✅ (radar) and 1 ✅ (stub-creation prevention / commission = match-or-park) are
SHIPPED + LIVE.** Item 1 stopped the bleeding, so **item 2 (no-MBI customer MERGE) is now
unblocked and is NEXT — brainstorm-first** (spec→plan→subagent-build→opus-review→deploy).

**Item 2 live grounding (re-verified on prod 2026-06-30): John Connelly ×5 is STILL there.**
ids: 1367 (keeper, MBI 4RH5X85DC65, DOB 1953-04-07) · 1419 ("John Connelly Iii", same DOB) ·
4239/4243/5960 (stub=True, commission_import, full_name="CONNELLY, JOHN", first/last BLANK;
only 4243 carries the DOB). ⚠️ The 3 stubs have BLANK first/last — a `last_name` query misses
them; the dup-detection MUST normalize `full_name` + handle the "LAST, FIRST" stub format.
Numbers: `duplicate_customers`=18 (high-conf name+DOB), 277 loose name-only clusters / 288
excess rows, 571 commission-import stubs. Central design question: which clusters are SAFE to
auto-suggest vs human-confirm (name+DOB = suggest; bare name or DOB-less stub = never auto;
need a corroborating id). Build on `app/customers.py` `customer_merge`/`customer_duplicates` +
`app/identity.py` matcher + the radar's `_duplicate_customers`. Full handoff:
`memory/session-handoff-2026-06-30-item2-no-mbi-merge.md`.

Then items 3 (plan_id linkage), 4 (hub resolve actions), 5 (count consistency), 6 (lead
lifecycle), 7 (AOR-is-per-policy). The radar is already written aware of leads + multi-AOR
so it never false-positives on them.
