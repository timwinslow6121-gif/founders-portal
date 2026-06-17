# Commission → Customer/Policy Enrichment + AOR Timeline Reconciliation (Design / Spec)

**Date:** 2026-06-16
**Status:** 📝 SPEC for Tim's review — NOT built yet
**Author:** brainstormed with Tim 2026-06-16 (grounded in the Tocara Brown case)

---

## 1. Context & the grounding case

Commission statements carry rich per-member data, but most of it lands only on
`PolicyPayment` and never enriches the `Customer`/`Policy` master — so commission-
created stubs stay sparse (no effective date, plan, state, county, etc.), and the
AOR timeline gets duplicate/overlapping intervals.

**Tocara Brown (customer 1991, Humana, agent Brian)** — the case that surfaced this:
- 2 AOR intervals, BOTH open (end=None): eff **2026-03-01** and **2026-06-01**.
- 3 May PolicyPayments (all paid stmt_date 2026-05-01, all Brian):
  - chargeback −$260.24 (eff 3/1), chargeback −$144.59 (eff 3/1) — her 3/1 enrollment reversed,
  - enrollment +$202.42 (eff **6/1**) — a NEW enrollment effective 6/1.
- Diagnosis: she enrolled 3/1, it was charged back, she re-enrolled 6/1. The 3/1 interval
  should be **closed**; only 6/1 should be open. Today both are open → an old, replaced
  enrollment looks active. Brian IS her agent (policy active, eff 3/1, no term).

**What already exists (good news):** `PolicyPayment` already stores `effective_date`,
`term_date`, `term_reason`, `statement_date` (payment date), `commission_action`,
`is_chargeback`, `plan_name`, `carrier_member_id`. So the dates Tim asked about
("exact date of payments, track initial vs chargeback") are ALREADY parsed — they're
just not propagated to Customer/Policy or used to reconcile AOR.

## 2. Goals (decided with Tim)

**A. Enrichment — fill blanks only, never overwrite.** On commission import, use the
matched member's data to fill ONLY EMPTY fields on the resolved `Policy` and `Customer`.
Never overwrite an existing value, and never touch a `manually_edited=True` customer
field (the existing BOB rule).
- **Policy** fill-blanks: `effective_date`, `term_date`, `plan_name`, `plan_type`,
  `plan_contract`/pbp → `plan_id` (via the alias map), `state`, `county`, `member_id`/
  `carrier_member_id`, `commission_type` (initial vs renewal).
- **Customer** fill-blanks: `state`, `county` (PII like phone/address/DOB: only if blank
  AND not manually_edited — same guard as BOB).
- Precedence: **manual > BOB > commission**. Commission only fills what's still empty.

**B. AOR timeline reconciliation — newer enrollment end-dates the older.** When an
ENROLLMENT row resolves with a later effective date than an existing OPEN interval for
the same (customer, carrier), close the older interval: `end_date = new_eff − 1 day`.
Result: one current open interval, prior ones historical. (Tocara: 3/1 closes at 5/31
when 6/1 opens.)
- Renewals do NOT open new intervals (only enrollments do) — prevents the per-row
  duplication.
- A chargeback that reverses an enrollment is corroborating signal; for v1 the
  supersession-by-effective-date rule is the primary mechanism (simplest, matches the
  data). Chargeback-driven closing can be a later refinement.
- BCBS still special-cases `end_date` (its term_date is a renewal date, never an end).
- DON'T retro-break existing good intervals: only close an interval that is OPEN and has
  an EARLIER effective date than the incoming enrollment.

## 3. Where the data comes from / gaps to close

- Dates + plan + lifecycle: already on `MemberFact` (effective_date, term_date,
  plan_contract, plan_pbp, plan_type, plan_name) and `PolicyPayment`.
- **`state`, `county`, `policy_number` are NOT on `MemberFact` yet** — they're in the raw
  rows (e.g. Aetna `Member State`, UHC `Member State`/`Member County`/`Policy Number`).
  Enriching those requires extending `MemberFact` + each carrier's normalizer to capture
  them. Scope decision: **Phase 2** (dates/plan/lifecycle first — highest value, no
  normalizer changes; state/county/policy# second).

## 4. Implementation plan (phased, TDD, each shippable)

- **Phase 1 — AOR reconciliation** (fixes Tocara-type duplicates; smallest, highest signal):
  - `resolver._open_aor_interval`: only open for ENROLLMENT row_class; when opening, close
    any open earlier-effective interval for the same (customer, carrier). Backfill script to
    reconcile existing duplicate open intervals (close superseded ones).
  - Tests: supersession closes the older; renewal opens nothing; BCBS end-date untouched;
    no-op when only one interval.
- **Phase 2 — fill-blanks enrichment of Policy/Customer** from the MemberFact (dates, plan,
  commission_type). `resolver._attach_policy` + a new `_enrich_policy`/`_enrich_customer`
  applied on BOTH create and crosswalk-match (so re-uploads backfill blanks on existing
  records). Strict fill-blanks + manual/BOB precedence. Tests for each precedence case.
- **Phase 3 — extend MemberFact + normalizers for state/county/policy#**, then fill those
  too. One carrier at a time (UHC/Aetna/Humana have them; BCBS/Devoted vary).
- **Phase 4 (optional) — surface payment dates in the UI**: the customer profile "Payment
  History" already reads PolicyPayment; add the statement_date + initial/renewal/chargeback
  columns so AJ/agents can see "exact date of payments + initial vs chargeback" (Tim's ask).

## 5. Non-goals / guardrails
- Never overwrite existing or manually_edited fields (fill-blanks only).
- AOR reconciliation only end-dates OPEN, strictly-earlier intervals — never deletes
  history, never reopens.
- No new migration expected for Phase 1–2 (uses existing columns). Phase 3 may add
  MemberFact fields (in-memory only) + possibly Policy already has state/county.
- Prove against real Postgres (the Tocara case + a re-upload) — fill-blanks + AOR changes
  must be verified on live-shaped data, not just SQLite.

## 6. Verification
- Tocara Brown: after Phase 1 + backfill, exactly ONE open Humana AOR (eff 6/1); the 3/1
  interval end-dated 2026-05-31. Brian remains her agent.
- A re-upload fills blank Policy.effective_date/plan_name where empty, leaves set values
  and manually_edited fields untouched.
- Full suite green; spot-check a handful of multi-enrollment customers on the VPS.

## 7. Open questions for Tim
1. AOR close boundary: `end_date = new_eff − 1 day` (no gap) vs `end_date = new_eff` — preference?
2. Phase 1 backfill: auto-close all superseded open intervals agency-wide now, or dry-run +
   review first (like the unassigned backfill)?
3. Phase 3 (state/county/policy#): worth it, or is dates+plan+lifecycle enough for now?
