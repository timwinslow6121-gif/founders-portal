# Corrected Lane-Aware Merge — Design

**Date:** 2026-07-24
**Status:** Approved (brainstorm complete) — ready for implementation plan
**Author:** Tim + assistant
**Builds on:** `docs/superpowers/specs/2026-07-21-customer-plan-domain-model.md` (§3 lanes, §6 corrected merge)

## Problem

The narrow "reissued-MBI merge override" shipped 2026-07-21 (commits
a53785f..395ea50) is **disabled** (`REISSUED_MBI_MERGE_ENABLED = False`) because
its logic — "term the loser's stale-MBI policy" — is **wrong for coexistence**:
it would term Jana Benson's active DVH. The domain model (§6) defines the
correct behavior: a merge auto-terms **only same-lane superseded primary-medical
plans**, never a coexisting product.

This build replaces that disabled override with the **corrected lane-aware
merge**: consolidate the person, keep the correct current MBI, auto-term only
the superseded primary-medical plan, keep all coexisting products active. It
re-enables the UI, unblocks Barbara Overcash (the one confirmed switcher still
in the duplicates list), and gives every future merge the right behavior.

## The core idea (Tim's framing)

**"How many of THIS kind can one person have?"**

- **Primary-medical (MAPD / MA-only / PDP): never more than 1 active.** Two → one
  superseded the other; newer wins, older termed. The ONLY lane that auto-terms.
- **Everything else — freely multiple, keep them all:**
  - Medigap: 2+ allowed (never auto-cancels; customer must call).
  - Ancillary (DVH, Hospital Indemnity, Life): multiples of each + mixed, all kept.

One strict single-slot lane; three free-coexist lanes.

## Section 1 — Lane classifier (`app/plan_lane.py`, new)

`plan_lane(plan_type) -> "primary_medical" | "medigap" | "ancillary" | "other"`,
layering on the existing `app/plan_sections.py::coverage_category()`:

| coverage_category | plan_lane |
|-------------------|-----------|
| `part_c`, `pdp` | `primary_medical` |
| `medigap` | `medigap` |
| `dvh`, `hospital_indemnity`, (life) | `ancillary` |
| else (`other`) | `other` |

**`plan_lane()` is a PURE, ON-DEMAND function — never persisted, never
overwrites `plan_type`.** It is the merge's coexist-vs-supersede lens only. The
specific type stays fully intact everywhere: "which customers have an HI plan"
filters on the specific type (`hospital_indemnity` via `coverage_category`), NOT
the lane — HI, DVH, and Life remain individually distinguishable for all future
filtering/reporting. This classifier is the shared helper the plan-taxonomy /
Brian-view filters will reuse.

(External-primary is a manual-entry lane in the domain model, not derived from
`plan_type` — out of scope here.)

## Section 2 — `resolve_primary_medical(policies)` (`app/plan_lane.py`)

Given a person's policies, decide which primary-medical plan is current and which
older ones to supersede.

```
resolve_primary_medical(policies) -> {
    "current":     Policy | None,   # the surviving primary-medical plan
    "supersede":   [Policy, ...],   # older primary-medical plans to term
    "needs_review": bool,           # ambiguous → term nothing, flag
}
```

- Consider only **active** policies where `plan_lane(plan_type) == "primary_medical"`.
- **0 or 1** → `current` = that one (or None), `supersede` = [], `needs_review` = False.
- **2+** → auto-supersede ONLY when **unambiguous**:
  - both have **known, DIFFERENT contract codes** (via the plan's `cms_plan_id` /
    `contract_code`), **AND**
  - exactly one has a **strictly-newer effective date**.
  - → `current` = the newest; `supersede` = the rest; `needs_review` = False.
- **Ambiguous** (any code missing, codes equal = renewal, eff dates tie, or can't
  tell which is newer) → `current` = None (or the newest as a hint), `supersede`
  = [], **`needs_review` = True**. Never auto-terms on a money/coverage decision.
- Medigap / ancillary / other policies are **never** in scope — they pass through
  untouched (this function only looks at the primary-medical lane).

Grounding: Overcash = Aetna PLUS *PDP* (2024) + UHC *MAPD* (2026) → different
codes, UHC strictly newer → `current` = UHC, `supersede` = [Aetna PDP],
`needs_review` = False.

## Section 3 — `merge_customers_lane_aware(...)` wrapper (`app/customers.py`)

The corrected merge. **Wraps the untouched `merge_customers` engine** — the
engine's "one non-null MBI" guard stays sacred (load-bearing for all callers).

```
merge_customers_lane_aware(keeper_id, loser_ids, agency_id, actor)
    -> {ok, merged, current_mbi, superseded_policy_ids, needs_review, error}
```

Sequence:
1. Gather the combined active policy set across keeper + losers.
2. `resolve_primary_medical(policies)` → `current` primary-medical plan + `supersede` list + `needs_review`.
3. **Current MBI** = `current`'s MBI **if it passes the CMS format validator**
   (§1.1 of the domain model; a value like Benson's `45039665600` is a policy
   number, never an MBI). **Null the stale MBI(s)** on the loser record(s) whose
   MBI != the chosen current MBI, and flush — so by the time the engine runs,
   exactly one MBI remains and its guard passes honestly.
   - If there is an unambiguous `current` primary-medical plan with a valid MBI →
     that is the current MBI; every other differing valid MBI is nulled.
     (Overcash: UHC is current → keep UHC MBI, null Aetna's.)
   - If `needs_review` (no unambiguous current) AND the records carry **two
     different valid MBIs** → do NOT force a merge (the engine guard would refuse
     two MBIs anyway). Return `needs_review=True` with `ok=False` and a clear
     "can't determine the current MBI — resolve the primary-medical plan first"
     message. This is the safe refusal, not a guess.
   - If only one valid MBI exists across the records (the coexistence case, e.g.
     Benson: one real Medigap MBI + one policy-number) → keep that one MBI; the
     non-MBI value stays on its policy. Merge proceeds.
4. Call `merge_customers(keeper_id, loser_ids, agency_id, actor)` — moves ALL
   policies onto the keeper. Coexisting policies (Medigap/ancillary/other) are
   kept active, unchanged.
5. **After the merge, term the superseded primary-medical policies** (only if
   NOT `needs_review`): set `status='termed'`, `term_date` = the current plan's
   effective_date − 1 day (Medicare month-end), `term_reason`, and **close their
   open AOR chapter** at that date (via `_close_open_aor_on_term`, the fix from
   the switcher work — terming a policy must close its AOR interval).
6. If `needs_review`: merge the person, term **nothing**, return
   `needs_review=True` so the caller flashes a "review primary-medical" note.

Failure on any step → rollback, no changes (mirrors the existing handlers). This
is a money/identity path.

## Section 4 — UI re-enable + broadened gate

- Rewire the existing `POST /admin/customers/merge-reissued-mbi` route and the
  `/admin/customers/duplicates` conflict-card panel to call
  `merge_customers_lane_aware`.
- Flip `REISSUED_MBI_MERGE_ENABLED` back **on**.
- **Broaden the gate:** offer the panel on **any same-DOB conflict cluster** (not
  only same-DOB/different-MBI), because the corrected merge handles all three
  cases uniformly — coexistence (Benson), switcher (Overcash), reissue (Frazier).
  Still requires the same-DOB safety (never merge different DOBs; that's a
  different-person signal).
- Update the panel copy from "Reissued MBI?" to **"Same person? Reconcile these
  records"** with a **per-case preview**: which MBI will be kept, which
  primary-medical policy (if any) will be termed, and which policies coexist.
  Admin confirms per-case. A `needs_review` result merges the person but terms
  nothing and says so.

## Section 5 — Testing & safety

- **`plan_lane()`**: mapd/ma/dsnp/csnp/pdp→primary_medical; ms/medigap→medigap;
  dvh/dental/hi/gtl/life→ancillary; unknown→other. HI vs DVH vs Life stay
  distinct via the specific type (assert `coverage_category` unchanged).
- **`resolve_primary_medical()`**: Overcash-shape (diff codes, newer eff →
  supersede older); renewal-shape (same code, diff year → no term); tie /
  missing-code → `needs_review`, supersede empty; Benson-shape (medigap+dvh → no
  primary-medical in scope, nothing to resolve); MA-only+PDP not built for (§3.4).
- **`merge_customers_lane_aware()`**: Overcash → one record, UHC MBI kept, Aetna
  PDP termed + its AOR chapter closed, no coexisting product touched; Benson →
  one record, both policies active, `45039665600` never becomes the MBI;
  needs-review case → merges but terms nothing + flags; different-DOB pair
  refused.
- **Engine untouched**: the `merge_customers` contradiction-guard test stays green.
- **Money invariant**: total `PolicyPayment` sum + count unchanged, 0 orphaned
  payments (assert in tests + real-Postgres verify).
- Process: opus whole-branch review (money/identity), DB backup, real-Postgres
  verify, confirm restart cycled. No migration (no schema change — `plan_lane`
  is a pure function; MBI null + policy term use existing columns).

## Rollout

Build → opus review → deploy → flip `REISSUED_MBI_MERGE_ENABLED` on →
**apply to Barbara Overcash** (the one live confirmed case) via the UI, verify
(one record, UHC MBI, Aetna PDP termed + AOR closed). Benson/Schwarz/Collins were
already merged manually this session, so Overcash is the live proof case.

## Out of scope / follow-ups

- **Manual "term this policy" action on the customer profile** (with a reason
  field) — the legitimate mechanism to term a **confirmed-cancelled Medigap**
  (domain model: "a term is a human/business decision"), with the carrier BOB as
  the independent backstop. Generally useful for any manually-retired policy.
  Own small spec.
- **Book-wide "one-active-per-primary-medical-lane" integrity check** — a radar
  invariant that flags any customer who *currently* holds 2+ active
  primary-medical plans (this build enforces the rule at merge time; the audit
  scans the existing book). Own radar item.
- **`resolve_primary_medical()` reused by BOB import / reconciliation** — the
  classifier + supersession are deliberately standalone so import can call them
  later; wiring that in is a follow-on.
- **External-primary lane** (SHP/employer/TRICARE/VA) — manual-entry, domain
  model §4, not in this build.
- **MBI history / alias** (domain model §1.3) — when a stale MBI is nulled here,
  it is dropped, not archived. An MBI-history table is a separate build.
