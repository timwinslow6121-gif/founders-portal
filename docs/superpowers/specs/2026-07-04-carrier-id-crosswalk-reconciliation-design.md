# Carrier ID Crosswalk & Commission↔BOB Reconciliation — Design

**Status:** Brainstormed + decisions locked with Tim 2026-07-04 (against real May-2026
Humana commission + July-2026 BOB files). Ready for spec review → writing-plans.
**Grounding case:** Sandra Agner — customer **2059** (stub, `source=commission_import`,
holds the $28.91 Humana payment, no MBI/DOB) and customer **6315** (real, `source=bob`,
`humana_id=H73527562`, DOB 10/3/1953, zip, phone). Same woman, split across two records,
linkable only by name today. This design links them permanently and stops it recurring.

## The problem, proven

There is **no universal linking ID** between a carrier's commission file and its BOB — it
is **per-carrier**, and several carriers share no usable key:

| Carrier | Commission member key | BOB member key | Shared ID today |
|---|---|---|---|
| Aetna | `Member ID` (`NG10…`) | `Member ID` (`NG10…`) | ✅ same |
| Healthspring | MBI + carrier id | MBI | ✅ |
| **Humana** | `PID`/`GrpNbr` (9-digit); MBI only on new-enroll rows | `Humana ID` (`H…`); Medicare No **masked** (last6 real) | ❌ none |
| **BCBS** | `Customer No` (9-digit) | MBI (stored as `Policy.member_id`) | ❌ none |
| UHC | full MBI | **BOB has NO MBI column** | ❌ none |
| Devoted | (per-agent) | Application report: name+DOB+NPN | ❌ by design |

**CORRECTED root cause (verified 2026-07-04 by reading the LIVE resolver — the earlier
draft mis-blamed the parser; that was wrong).** The live commission path is
`normalize_humana` (normalizers.py) → `MemberFact` → `_resolve_commission_match_or_park`
(resolver.py), NOT the legacy `extract_humana`/`_match_policy` in payments.py. The truth:
1. **The parser is FINE.** `normalize_humana` already reads `mbi=UMID`, `carrier_member_id=PID`,
   `EffDate`, `Contract` into a MemberFact. It does NOT throw IDs away.
2. **The `humana_id` column is INTENTIONAL, not a bug.** `_create_stub` stores the Humana
   MBI in `customers.humana_id` (resolver.py:124-127) AND `_match_by_mbi` matches Humana's
   `fact.mbi` against `customers.humana_id` (resolver.py:95-96). Consistent by design. (The
   `have_full_mbi=12 vs have_humana_id=2319` split is that consistency, not a defect.)
3. **THE REAL GAP — renewals have no shared ID to any existing record.**
   `_resolve_commission_match_or_park` tries, in order: crosswalk (Policy by
   carrier+member_id) → `_match_by_mbi` → `_match_by_carrier_member_id` → else PARK. For a
   **renewal** (Sandra Agner, `FrstYrRnwl=R`): `fact.mbi` is blank (Humana omits it on
   renewals) so `_match_by_mbi` fails; her `PID` (591236450) ≠ the BOB customer's
   `Policy.member_id` (which holds the `Humana ID` H73527562), so `_match_by_carrier_member_id`
   fails → **PARK / legacy stub.** The resolver is doing the SAFE thing (never name-guessing);
   it simply has no persistent way to know "GrpNbr 00019275764K = this customer."
4. **So the fix is exactly the crosswalk (Tim's Option 3):** persist `GrpNbr ↔ customer ↔ MBI`
   so that once a member is linked (via a new-enrollment MBI row), every future renewal —
   which carries the SAME GrpNbr — rides the stored link. Sandra's legacy stub (2059) predates
   item-1's park behavior; the cleanup collapses it into her real customer (6315).
   **The parser and the humana_id column need NO change.** The work is: (a) capture GrpNbr onto
   the MemberFact + the crosswalk, (b) add a crosswalk lookup as resolution step 1, (c) seed +
   (d) clean up the legacy stubs.

**Two lifecycle facts that shape the fix (proven):**
- **Active/inactive = BOB col AE `Status`.** 948/948 blank-MBI Humana BOB rows are
  `Inactive Policy`; 2,270/2,271 active rows HAVE the MBI. Blank-MBI ⟺ inactive ⟺ ignore.
- **Humana puts the MBI only on NEW-enrollment rows** (`FrstYrRnwl=F`, 45/232); renewals
  (`FrstYrRnwl=R`, 187) carry NO MBI by design. So renewals can't self-identify by MBI —
  but they DO carry the same **`GrpNbr`** as the member's original new-enrollment row.

## The design: a stable per-member ID crosswalk (Tim's Option 3)

**Verified:** `GrpNbr` is a clean **1:1, stable, per-member** key (222 distinct GrpNbr =
222 distinct PID; 0 GrpNbr→multi-PID; 0 GrpNbr→multi-name). It is populated on 229/232
rows (better than PID 225, far better than MBI 45).

**The durable chain:**
```
commission GrpNbr  ↔  carrier_id_crosswalk  ↔  Founders customer id  ↔  MBI / carrier id
```
Link a member **once**; every future renewal carries the same `GrpNbr` and rides the
stored link straight to the right customer — deterministic, no name-matching ever again.

### Component 1 — `carrier_id_crosswalk` table (NEW)
The permanent equivalence store. One row per (carrier, carrier_key) → customer.
- `carrier` (str), `carrier_key` (str — Humana GrpNbr; BCBS Customer No; generic),
  `key_kind` (str — 'grpnbr'|'customer_no'|'member_id'), `customer_id` (FK),
  `mbi` (str, nullable — captured when known), `agency_id` (FK),
  `confidence` ('exact_id'|'mbi_last6'|'name_dob_plan'|'human_confirmed'),
  `created_at`, `source_note`.
- Unique on `(agency_id, carrier, carrier_key)`.
- This is the single seam every carrier's resolver reads/writes.

### Component 2 — add a crosswalk step to the EXISTING resolver
Extend `_resolve_commission_match_or_park` (resolver.py) — do NOT build a parallel matcher.
Add ONE new step at the FRONT of its existing ladder (crosswalk-Policy → `_match_by_mbi`
→ `_match_by_carrier_member_id` → PARK), plus a write-back on success:
- **New step 0 — `carrier_id_crosswalk` lookup:** `(agency_id, carrier, GrpNbr)` in the
  new table → attach to that customer. This is the deterministic path that carries every
  future renewal, and it runs BEFORE the existing MBI/carrier-id steps.
- **Write-back:** whenever ANY step (crosswalk-Policy, `_match_by_mbi`,
  `_match_by_carrier_member_id`) resolves a customer AND the fact has a `GrpNbr`, upsert a
  `carrier_id_crosswalk` row `(carrier, GrpNbr) → customer` (+ mbi when present). That is
  how a member linked once (via a new-enrollment MBI) seeds the key that carries their
  renewals. Idempotent upsert on the unique `(agency_id, carrier, carrier_key)`.
- **No name-matching added to the live path.** The name+eff+plan / last6 logic is used ONLY
  by the one-time SEED + the human-confirm merge UI (below), never in the per-upload
  resolver — the "David White" boundary stays intact.

### Component 3 — carry `GrpNbr` on the MemberFact (small, additive)
`normalize_humana` already reads UMID/PID/EffDate/Contract. Add ONE field: read `GrpNbr`
(the stable per-member key) onto the `MemberFact` (e.g. `fact.member_group_key`) so the
resolver's crosswalk step + write-back can key on it. **The parser is otherwise unchanged;
the `humana_id` column is unchanged** (storing Humana's MBI there is correct — `_match_by_mbi`
reads it there). Other carriers keep their existing key extraction; only Humana gains GrpNbr.

### Component 4 — active-only pre-filter
Before matching, ignore BOB rows where col AE `Status` != active (blank-MBI inactive noise).
Reuse the data-integrity radar's active notion where possible.

### Component 5 — park, never stub (already shipped, item-1)
Unmatched/ambiguous commission rows PARK (`PolicyPayment.policy_id=NULL`,
`match_confidence='unmatched'`) for human resolution. This design ADDS the crosswalk +
resolver ladder BEFORE the park, so far fewer park.

## Seeding (Tim's Option 1 — "seed what we can with guaranteed info, then enrich both
records so remaining merges are 100% confident")

**Phase A — history seed (guaranteed), via a READ-ONLY file scan — NOT a re-import.**
For every member who has EVER appeared with an MBI in ANY past Humana commission file,
write `carrier_id_crosswalk` (GrpNbr↔MBI↔customer). **CRITICAL (Tim's concern, 2026-07-04):
seeding must NOT re-run the ingest pipeline.** Re-importing would recalculate amounts/
splits/attribution and risk overwriting AJ's hand-verified, proven-correct commission data.
The seed is DECOUPLED from money: a standalone read-only script (`scripts/seed_humana_
crosswalk.py`, dry-run/--apply) that (1) reads the raw Humana commission files Tim hands
over, (2) extracts ONLY the identity pairing `(GrpNbr, MBI, name, eff-date)` per member,
(3) writes ONLY `carrier_id_crosswalk` rows — it NEVER touches `commission_line_items`,
`policy_payments`, amounts, splits, or any AJ edit. Zero blast radius on the money.
Idempotent, dry-run first, DB backup, real-Postgres verify. **Tim provides the historical
Humana files; the script reads them directly (does not go through `/admin/commissions`
upload).**

**Phase B — enrich both halves.** For the existing split pairs (stub + real, like Sandra):
pull EVERY corroborating field each source carries and attach it, so the merge is provable,
not a name guess:
- Commission side carries: name, PID, GrpNbr, MBI(new-enroll), **effective date, plan/
  contract, agent, FrstYrRnwl**.
- BOB side carries: name+MI, Humana ID, **last-6 MBI**, **DOB**, gender, phone, email,
  full address, zip, county, status, effective date, plan, NPN, servicing agent.
- **Overlap available to corroborate a 100%-confidence merge:** NAME + EFFECTIVE DATE +
  PLAN/CONTRACT + last6-MBI (BOB always; commission on new-enroll) + AGENT
  (commission `WaName`/`WaSan` ↔ BOB `Servicing Agent`).
- **PROVEN (2026-07-04, real files):** the backbone key **name + effective-date** has
  **0 collisions** across 2,271 active Humana members and uniquely matched 86 commission
  members with **0 ambiguous**. **agent + plan + last6-MBI layer on as REINFORCEMENT** —
  each, when present and matching, drives the odds of a wrong merge to nil. Tim's rule:
  "if agent + name + eff-date + plan + last6 all match across the two files, it is the
  same person." Confirmed: 0 keys collide. **The confident-merge key = name+eff-date
  (backbone) + agent/plan/last6 (reinforcement).**
- **Agent-name normalization required:** commission `WaName` = "LAST FIRST"
  ("LAUZURIQUE MICHAEL"); BOB `Servicing Agent` = "First  Last" ("MICHAEL  LAUZURIQUE",
  double-spaced). Normalize via the EXISTING `_norm`/`_resolve_agent_id` seam in
  payments.py before comparing — raw compare yields false 0-match.
- The 143 name+eff "no-match" rows are NOT collisions — they are renewals whose
  new-enrollment link isn't seeded yet (Phase A MBI-history seed + Phase C human-confirm
  sweep them; thereafter their GrpNbr rides the crosswalk forever).

**Phase C — human-confirm the residue.** Whatever can't be auto-merged with certainty
surfaces in the existing `/admin/customers/duplicates` merge UI (rich context already
built 2026-07-02), and each human confirm **writes a `carrier_id_crosswalk` row** — so
every confirm permanently seeds the crosswalk and never has to be repeated.

## One-time cleanup
After seeding, collapse the ~540 existing commission stubs into their real active
customers via the crosswalk + `merge_customers` (the audited fill-blanks-only engine
shipped 2026-07-01). Ratchet the integrity baselines (`orphan_stub_customers`,
`commission_import_stubs`, `duplicate_customers`) down. DB backup + dry-run + real-Postgres
`--apply` (SQLite hides FK/unique bugs — lesson from item-2's live AOR-collision).

## Scope decision (for spec review)
Recommend **Humana-first, end-to-end** (biggest stub carrier: 220): build the crosswalk
table + resolver + extract_humana fix + Humana seed + Humana stub cleanup, prove the
pattern LIVE, then repeat the resolver entry for BCBS/UHC/Devoted. Aetna/Healthspring
already reconcile by shared ID (regression-test only).

## Constraints (carry from the codebase)
- Every query agency-scoped; `_upsert_customer_from_policy` takes explicit agency_id.
- DB backup before any migration/apply; dry-run then real-Postgres `--apply`; confirm
  `systemctl restart` cycled; all times EST/EDT (DB is UTC).
- Opus whole-branch review on this data/money path (it has caught a Postgres-only bug
  every round — FK-500 ×2, savepoint data-loss, AOR unique-collision).
- No name-ONLY auto-merge, ever (the two-David-Whites rule). Name is only ever used
  WITH eff-date+plan (+last6), or to seed a crosswalk that is thereafter ID-based.

## Explicitly out of scope
- Getting a native carrier PID↔HumanaID roster export (would be ideal but not available;
  the crosswalk is built from our own MBI history + confirmed merges instead).
- The go-forward reconciliation *dashboard* ("N of M reconciled per agent/carrier") — a
  follow-on once the crosswalk exists (Round 2 reconciliation engine, already a backlog stub).

## Reuse (don't rebuild)
`_match_policy`/`build_payments` (payments.py), `merge_customers` + `/admin/customers/
duplicates` merge UI (customers.py, shipped 2026-07-01/02), the park-don't-stub behavior
(item-1), the data-integrity radar baselines (integrity.py), `sweep_parked_payments`.
