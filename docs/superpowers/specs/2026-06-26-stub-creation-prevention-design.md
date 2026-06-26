# Stub-Creation Prevention — Commission = Match-or-Park (Roadmap Item 1)

_Date: 2026-06-26 · Status: design approved by Tim, ready for writing-plans.
Roadmap item 1 of `docs/superpowers/specs/2026-06-25-data-integrity-remediation-roadmap.md`._

## The rule, in one sentence

**Commission import attaches a payment to an existing customer ONLY via a 100%-unique
carrier ID (MBI or carrier member id, carrier-scoped). Match → attach to the customer's
policy + AOR. No confident ID match → park the full payment in the Needs-Identity hub.
Commission import NEVER creates a customer and NEVER matches on a name.**

Identity comes from ONE door: the BOB import. The money file (commission) only matches
to people the BOB already knows, or waits (parked) until it does.

## Why this exists (grounded in live data, 2026-06-26, agency_id=1)

- **571 stub customers, ALL `source='commission_import'`.** The BOB import created **zero**
  stubs. The commission path is the sole source of the dup-stub garbage.
- **None of the 571 have a DOB.** The resolver's name+DOB and composite matchers are
  therefore **dead code for commission rows** — no commission normalizer populates `dob`
  (verified: `grep -n "dob=" app/commission/normalizers.py` → nothing).
- **275 of the 487 no-MBI stubs collide by exact name with a real (non-stub) customer**
  (274 of whom already have a real policy). These are the John-Connelly-class dups: the
  commission file invented a second "person" the agency already had.
- Root cause: we let the **money file create people**. The cure is structural — take that
  power away. Then the bug cannot recur (not merely "is discouraged").

## What already exists (this is mostly subtraction + reuse — NOT new construction)

| Piece | Status |
|---|---|
| Single `resolve_customer()` seam shared by BOB + commission | ✅ built (`app/commission/resolver.py`) |
| ID matchers `_crosswalk` / `_match_by_mbi` / `_match_by_carrier_member_id` | ✅ built |
| `source="commission_import"` already passed into `resolve_customer()` | ✅ built (`app/commission/ingest.py:154`) |
| `MatchSuggestion` model + Needs-Identity hub `/customers/unassigned` | ✅ built (`app/models.py:624`, `app/customers.py:1012`) |
| Parked payment = `PolicyPayment(customer_id=NULL, match_confidence='unmatched')` | ✅ model already supports it (`app/models.py:687`, columns nullable) |
| `normalize_person_name()` → "First MI. Last" standard | ✅ built (`app/names.py`) |
| Every carrier carries a unique ID on every real commission row | ✅ verified (table below) |

**Genuinely new / to-confirm:** the **auto-sweep** (a parked payment re-attaching when a
later BOB import produces a matching-ID customer). Confirm during planning whether any
form of this already runs in the BOB upsert; if not, it is the one net-new bit, and small.

No new models. No migration. The change is overwhelmingly **deletion** (remove
customer-creation from the commission path) + **reuse** (the hub, the matchers).

## The unique-ID guarantee (why attribution is 100% or nothing)

Every commission row already carries a carrier-issued, never-reused unique ID. Match on the
**ID, never the name** — names collide (5 Connellys), IDs do not. Verified in the parsers:

| Carrier | Unique ID on the row | MemberFact field | Matched against |
|---|---|---|---|
| UHC          | MBI            | `mbi`               | `Customer.mbi` |
| Aetna        | MBI + Member ID | `mbi` / `carrier_member_id` | `Customer.mbi` / Policy `member_id` |
| Humana       | humana_id      | `carrier_member_id` | `Customer.humana_id` (Humana keys on humana_id, not mbi) |
| BCBS         | Customer No (col F / row[5]) | `carrier_member_id` | active Policy `member_id` |
| Healthspring | HICN / Member ID | `mbi` / `carrier_member_id` | `Customer.mbi` / Policy `member_id` |
| Devoted      | Member ID      | `carrier_member_id` | active Policy `member_id` |

BCBS already reads `customer_no` into `carrier_member_id` AND skips any row without it
(`normalizers.py` "skips Total: row"). So every real BCBS payment row has a usable ID too.

Because a payment can only attach via a matching unique ID, **a different person (different
ID) can never receive it.** The outcome is binary: correct attribution, or parked.

## Architecture — the change lives in `resolver.py` + `normalizers.py`

### A. Commission ladder becomes match-or-park

In `resolve_customer()`, when `source == "commission_import"`, the resolution ladder is:

```
1.  crosswalk            (Policy by carrier + effective member_id)   → adopt, attach
2.  MBI / humana_id      (Customer by mbi / humana_id)               → attach
2b. carrier_member_id    (Customer via active Policy member_id)      → attach
→   PARK                 (no ID match): NO customer, NO policy, NO AOR, NO payout.
                          Record a parked PolicyPayment (held) + a needs-identity item.
```

Everything from step 3 onward in the current resolver (composite, name+DOB suggest-link,
`has_strong_identity` stub creation, the weak-identity tail) is **NOT executed for the
commission path**. `_create_stub` is never called when `source == "commission_import"`.

**Implementation:** gate on `source`. The cleanest shape is an early branch:
`if source == "commission_import": return _resolve_commission(...)` — an ID-only ladder
that ends in park — leaving the existing full ladder intact for BOB (`source != commission`).
This keeps BOB's creation rights untouched (one door for identity) and makes the commission
path trivially auditable: it has exactly three attach tiers and one park terminus.

### B. Park = a recorded-but-unattached payment in the existing hub

A parked payment is **not** a new entity — it is the data we already write:

- `PolicyPayment` with `customer_id = NULL`, `policy_id = NULL`,
  `match_confidence = 'unmatched'` (model already supports all three; `payments.py`
  already defaults `match_confidence='unmatched'` for no-match rows).
- It carries everything needed to resolve later: full_name, mbi, carrier_member_id,
  carrier, writing agent, plan, amount, effective/term dates, statement_date.
- Surfaced in the existing Needs-Identity hub (`/customers/unassigned`) so a human can
  match it. **Reuse the hub — do not build a new queue** (Tim's constraint).

The agency's money math stays whole: parked payments are recorded and counted (the
recap/balance still sums correctly), shown as "unattached — needs review," not dropped.

**Park HOLDS THE WHOLE PAYMENT — no payout until 100% confident on BOTH customer AND
pay-split (Tim's decision).** A parked payment is *recorded and counted* but *paid to
nobody* — neither the agent nor the agency — until it is resolved. Rationale: the
split/payout is itself a confidence problem, not a given. Agent pay nuance is real
(LOA arrangements, the retired-agent rollup Cyndi/Don→Brian, Betty's 52.5%, UHC overrides),
so a shaky agent-match would produce a *mismatched payment* — the exact failure this whole
effort exists to eliminate. Holding the payment is therefore correct: an agent's correct
pay is never delayed by a *known-good* match, and a *not-yet-trusted* one never goes out
wrong. (NB: this is stricter than NON_CUSTOMER rows like HRA bonuses, which DO pay an agent
with no customer — those are a distinct, already-trusted case and are unchanged. A
genuinely-unmatched member payment HOLDS.)

### C. Auto-sweep on BOB import (the thing that empties the parking lot)

When a BOB import creates or updates a customer (the ONLY path that creates identity), and
that customer's MBI / humana_id / carrier_member_id matches a parked `PolicyPayment`
(`customer_id IS NULL`), the parked payment **auto-attaches**: set its `customer_id`,
resolve/attach its `policy_id`, and ensure the AOR interval. No human step, no stub,
guaranteed-correct because it is an ID match.

This runs inside the BOB upsert flow (`app/upload.py` `_upsert_customer_from_policy` /
the `resolve_customer` BOB branch). Confirm in planning whether an existing re-match hook
covers this; if not, add a small `_sweep_parked_payments(customer)` called after a BOB
customer's IDs are known. Idempotent: a re-run finds no `customer_id IS NULL` rows to sweep.

### D. Name normalization for the commission normalizers (folded in)

All ~7 `MemberFact` constructions in `app/commission/normalizers.py` currently do ad-hoc
name handling (`name.split()[0]` / `name.split()[-1]`, raw column first/last, inline comma
splits) and **none call `normalize_person_name()`**. Route every one through the existing
`normalize_person_name(raw) → (first, mi, last, full)` so the parked-payment + hub names a
human reads are clean, consistent "First MI. Last". This directly serves the human-match
step (a parked `CONNELLY,JOHN J` vs a customer `John J. Connelly` is the exact friction
that bred dups). **Reuse `app/names.py` — no new normalizer.** In scope: commission
normalizers only. Out of scope: the BOB parsers (already mostly normalized; separate sweep).

### E. Unknown-carrier upload → BLOCK with a clear reason

The agency has **8 carriers: UHC, Humana, Devoted, BCBS, Aetna, Healthspring,
Medico/Wellable, GTL** (more may come later). The `NORMALIZERS` registry currently covers
**6** (Medico/Wellable + GTL are not yet wired). Today an unparseable / unknown-carrier
file can slip through as a silent no-op — invisible to AJ, which violates "nothing lost."

**Rule:** if `_detect_carrier` cannot fingerprint the file, OR the detected carrier has no
entry in `NORMALIZERS`, **reject the upload** with an explicit flash: *"Cannot parse this
file — carrier '<X>' is not yet supported (supported: UHC, Humana, Devoted, BCBS, Aetna,
Healthspring). Nothing was imported."* Never import a partial/empty statement. This is a
small guard at the `commission_upload()` entry point (`routes.py:1002`) — a check that the
detected carrier ∈ `NORMALIZERS` before ingesting. (Wiring Medico/Wellable + GTL parsers is
its own backlog item; this guard just makes their absence loud instead of silent.)

## Guardrails

- **ID-only, carrier-scoped.** Never auto-attach without a matching unique ID. No ID → park.
  Names are never a basis for auto-attach (Tim: "100% correct every time or park it").
- **Never overwrite an existing identifier.** The auto-sweep only *fills* a customer's
  empty MBI/humana_id if the matching row supplies one; it never changes a populated ID
  (same spirit as the `manually_edited` rule).
- **Idempotent re-upload.** Re-running the same commission file re-resolves attached
  payments via crosswalk/MBI (no change) and re-parks the still-unmatched ones to the same
  rows (no duplicate parked payment, no duplicate hub item — guard on `source_ref`).
- **BOB path unchanged.** Only the `source == "commission_import"` branch loses creation
  rights. BOB keeps `_create_stub` and identity writing.

## Edge cases

- **NON_CUSTOMER rows** (HRA bonuses, pure overrides, sub-$1 dust): already handled before
  `resolve_customer` (`ingest.py` writes the payment with `customer=None` and `continue`s).
  Unchanged — they were never a stub source.
- **Carrier-switch / rapid-disenroll / AOR lifecycle** side effects: only apply on the
  attach tiers (where a customer exists), exactly as today. A parked row has no customer,
  so none of these fire — correct.
- **A row whose MBI matches no customer but whose name matches one:** under the strict rule
  this **parks** (no name auto-attach). It resolves when BOB adds that MBI (auto-sweep) or a
  human matches it in the hub. This is the deliberate trade for 100% correctness.

## Verification (the radar is the proof)

- A commission upload reports `stubs_created = 0` (it already counts this in `ingest.py`).
- New radar invariant in `app/integrity.py`: **`commission_import_stubs` = count of
  `Customer.stub AND source='commission_import'`.** Its frozen baseline today is 571.
  Item 1 guarantees this count can only go DOWN (no new ones); item 2's merge drives it to
  0. The ratchet (`tests/test_integrity_guards.py`) fails the build if it ever rises above
  baseline — so a regression that re-enables commission stub-creation is caught immediately.
- `orphan_stub_customers` must not increase; the ratchet enforces it.
- **"Nothing lost" balance invariant (the money-side proof).** Add a radar invariant that,
  per statement, asserts to the penny:
  **Σ(all commission line items) == Σ(attached payments) + Σ(parked payments) +
  Σ(non-customer payments)** (tolerance $0.01, the existing `verify_statement_balance`
  tolerance). This proves the parking lot itself leaks nothing — a payment can be *held*,
  but it can never *vanish*. Held money is always still in the total.
- **Stale-park aging alert.** A badge/alert when any payment has been parked > 30 days, so
  held money is visibly chased, not left to rot. Surfaced on the hub + (optionally) a
  count in the admin commission view. Keeps the parking lot from silently growing into
  lost money. (Reuse the existing `unmatched_count` plumbing in `routes.py:1446/1668`.)
- Unit tests (`tests/`): commission row with matching MBI → attach, no stub; with matching
  carrier_member_id → attach; with no ID match → parked PolicyPayment, `customer_id IS NULL`,
  no Customer/Policy/AOR created and NO agent payout (held); BOB import of a matching MBI →
  parked payment auto-sweeps onto the customer; name normalizer output is "First MI. Last"
  for each carrier shape; an unknown-carrier file → upload rejected, 0 rows imported.
- **Real-Postgres verify (protocol):** DB backed up; re-upload a UHC + a BCBS + a Humana
  file on the VPS; confirm 0 stubs created, payments either attach by ID or land parked;
  then run a BOB import and confirm parked payments sweep onto the matched customers.

## Out of scope (later items)

- **Merging the existing 571 stubs** + sweeping their historical payments onto the merged
  profile = roadmap **item 2** (no-MBI merge). Item 1 only stops *new* stubs.
- **Hub resolve actions** (one-click human match in the needs-match tab) = item 4. Item 1
  parks payments into the hub; making the hub button actionable is item 4's job (this spec
  assumes the hub can already display a parked/needs-match item, which it can).
- BOB-parser name normalization (a separate, smaller sweep).
- **Wiring the Medico/Wellable + GTL normalizers** (the 2 carriers not yet in `NORMALIZERS`)
  = its own backlog item. Item 1 only makes their absence a *loud block*, not a silent
  no-op. → add to `BACKLOG.md`.
- `plan_id` linkage (item 3), count consistency (item 5), lead lifecycle (6), per-policy
  AOR (7).

## Files touched (all existing)

- `app/commission/resolver.py` — add the `source == "commission_import"` ID-only
  match-or-park branch; ensure `_create_stub` is unreachable on that path; a parked row
  resolves NO agent payout (held until customer + split are both confident).
- `app/commission/normalizers.py` — route the ~7 name constructions through
  `normalize_person_name`.
- `app/commission/routes.py` — `commission_upload()`: reject when detected carrier ∉
  `NORMALIZERS`, with a clear reason; nothing imported.
- `app/upload.py` (BOB path) — add/confirm the `_sweep_parked_payments(customer)` hook
  (must sweep ALL parked rows for the matched ID, not just one).
- `app/integrity.py` — add the `commission_import_stubs` invariant (ratchet from 571) AND
  the per-statement "nothing lost" balance invariant; surface the stale-park (>30d) alert.
- `tests/` — branch coverage + the two integrity invariants + unknown-carrier rejection.
- No model change, no migration.
