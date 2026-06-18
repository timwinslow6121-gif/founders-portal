# Commission Trust System — Audit + Design Spec

**Date:** 2026-06-18
**Status:** 📝 SPEC for Tim's review — NOT built yet
**Author:** brainstormed with Tim 2026-06-18 (grounded in a live audit of the running system)
**Why this matters:** Tim's pay (via his forming S-Corp) depends on Founders trusting the
portal's commissions. Brian (final say, tech-averse) requires the portal to agree with
AJ's manual line-by-line Excel before he relies on it. This is also the foundation of the
white-label product for Tidewater Management Group + downline agencies.

---

## 1. Audit findings (the factual starting point)

Pulled live from the VPS on 2026-06-18.

### 1.1 Quarantine is a ONE-CARRIER problem

| Carrier | Line items | Quarantined | Balances to penny |
|---|---|---|---|
| Aetna | 46 | 0 | ✅ |
| BCBS | 213 | 0 | ✅ |
| Devoted | 83 | 0 | ✅ |
| Healthspring | 20 | 0 | ✅ |
| Humana | 229 | 0 | ✅ |
| **UHC** | 4,033 | **80 (2.0%)** | ✅ |

**5 of 6 carriers are already at 100%** — zero quarantine, every line classified and
balanced. They classify on a stable per-carrier signal (e.g. Healthspring: "Service Fee"
description → override; negative → chargeback; else commission). They stay clean as long
as the carrier keeps that column.

**All quarantine is UHC**, and within UHC it's a small specific set: "New" enrollment
proration (months-remaining × PMPM, comp_type I vs R), "New Chargebacks", and a few DVH
manual rows. The 36% seen on the June UHC file is a small-file artifact (89 rows, mostly
the hard type), not a regression — the absolute count is ~80 across May+June.

### 1.2 What already works (do NOT rebuild)

- **Provable completeness invariant.** `verify_statement_balance()` checks
  `Σ line-item raw_amount == independent re-sum of the file's money rows`. Ran live: **all 7
  statements balance to the penny.** A dropped/mis-summed row makes the two diverge.
- **Quarantine ≠ lost money.** A quarantined row is still counted (100% Founders-keep)
  until resolved, so the books always balance; worst case is "held for AJ", never "vanished".
- **Per-carrier extractors → uniform `LineItemDraft` → one unified `CommissionLineItem`
  table.** Column knowledge is quarantined inside each carrier's extractor (one file per
  carrier). Everything downstream is carrier-agnostic (`raw_amount`, `agent_payout`,
  `founders_keep` are ROLES, not column letters). The "one giant table for all carriers"
  already exists.
- **`split_breakdown()` already computes AJ's two columns.** AJ's manual method = add an
  "Agent Commission" column (G) + a "Founders Override" column (H) to the raw file where
  G + H = the raw Commission (F). `split_breakdown()` derives exactly `(agent_payout,
  founders_keep)` summing to `raw_amount`. The portal already does AJ's method; it just
  needs to SHOW it the way he thinks about it.

### 1.3 The gaps (what this project fixes)

1. **The balance check only logs a warning** — the statement imports `verified` regardless.
   The machine that guarantees "every dollar accounted for" exists but is not a GATE.
2. **Quarantine resolution has NO audit trail and NO undo.** `resolve_quarantine_line()`
   mutates the row in place and destroys the original amount. On 2026-06-17 AJ misclicked
   "resolve" on 1–2 lines and had no way to see which, whether they were correct, or to undo.
   This is the single biggest trust breaker.
3. **No re-upload safety contract for human work.** AJ re-uploads corrected files often
   (3× this week). It's undefined whether his manual resolutions survive a re-upload.
4. **No statement sign-off/lock** — no explicit "AJ reviewed & this pay period is payable".
5. **No carrier stated-total cross-check** — we verify line items sum internally, but not
   against the carrier's OWN stated deposit total (e.g. the BCBS 27¢ gap is absorbed, not
   surfaced).

---

## 2. Goal & trust model

**The portal earns trust by reconciling to AJ's manual Excel to the penny, every carrier,
every agent, every month** — Brian's "do it both ways and they must agree" IS the
acceptance test. The portal does the identical thing AJ does (two columns, G+H=F), just
automatically and provably. The day the numbers agree N months running, Brian decides —
from evidence — that the manual way is redundant.

Three promises, in order:
1. **Fidelity** — what AJ sees IS the file: every raw row, unchanged, beside its computed
   split; nothing dropped or silently mutated; total ties to the file.
2. **Safe manipulation** — AJ works the hard rows like Excel, but every action is logged and
   reversible (unlike Excel and unlike today).
3. **Honest confidence boundary** — the portal clearly separates what it computes with 100%
   confidence (5 clean carriers + deterministic UHC rows) from what needs a human (UHC
   New-to-Medicare), and never fakes the latter.

**The 3-question UX principle** (every commission screen must answer at a glance, in order):
1. Does it balance? 2. What needs me? 3. Show me the proof.

---

## 3. Phase A — Trustworthy & auditable (build first)

Each item is independently shippable.

### A1. Multi-file batch commission upload (like BOB)
AJ drags ALL the month's commission files at once. Each file auto-detects its carrier and
routes to that carrier's existing extractor (parsing stays per-carrier — SAFE); all land in
the unified `CommissionLineItem` table. Per-file result line: "UHC 89 ✓ balances / Devoted
83 ✓ / …" plus any skips. Reuses the BOB bulk pattern hardened 2026-06-17 (per-row
savepoint + dedup). Explicitly NOT a universal parser — a carrier format change still breaks
only that carrier's extractor, loudly, via the balance check.

### A2. Fidelity View (the core trust screen)
Per statement, a sortable/filterable grid (Excel-like) showing EVERY raw row with three
ROLE columns: `Raw | Agent Commission | Founders Override`, with the parts shown summing to
the raw on each row. Also shows, per row, the **statement date (when paid)** beside the
**policy effective date (the business)** — surfacing the carrier pay-lag honestly (BCBS ~2mo
back, Healthspring ~1mo) WITHOUT the portal shifting periods or forecasting. Footer:
**"File total $X = Ledger total $X ✓"** (the completeness invariant, surfaced). This is the
on-screen version of AJ's two-column method — his exact workflow, computed.

### A3. Balance gate (status, not silent warning)
`verify_statement_balance` drives a visible statement STATUS:
- `✓ VERIFIED — every dollar balances`
- `⚠ N rows held for review ($X)` (quarantined; still balanced as Founders-keep)
- `✗ DOES NOT BALANCE — $Δ` (rare; blocks sign-off until explained)

### A4. Audit trail + undo on every human action (fixes AJ's misclick gap)
Every resolve / edit / adjust writes an audit record (who / when / before → after), shows on
the row ("split by AJ 6/17: $28.92 + $4.59"), and has **Undo** that restores the exact
pre-state. `resolve_quarantine_line()` stops destroying the original — it preserves the
pre-resolution state so undo is exact and "which rows did I touch?" is always answerable.

### A5. Constrained per-row edit of Agent-Commission / Founders-Override
AJ can correct G or H on any row when the parser got it wrong, or fill a quarantined row.
The edit is CONSTRAINED so `agent_commission + founders_override = raw_amount` always holds
(an edit can never break the balance). Logged + undoable (A4). This is exactly AJ's need:
"he doesn't edit the raw data, but if the parser gets the agent or override wrong, or it's
quarantined, he needs to fix/add it."

### A6. Re-upload safety contract
Define + build what happens to AJ's manual resolutions when he re-uploads a corrected file:
raw rows are replaced, but **human resolutions/edits are preserved (or clearly flagged to
re-confirm) — never silently lost or double-counted.** (AJ re-uploads constantly; losing an
hour of UHC splits would destroy trust instantly.) Exact mechanism = a design task in the
implementation plan (likely: key human edits to a stable per-row identity that survives
re-parse; on conflict, surface "you previously split this row — keep or redo").

### A7. Statement sign-off / lock
An explicit "AJ reviewed & locked this statement" action that freezes it (re-open requires a
logged reason). This is the moment a number becomes payable and answers "who approved this
pay period?" — a strong, concrete trust signal for Brian.

### A8. Carrier stated-total cross-check
Where the carrier file carries its own summary/deposit total, verify our line-item total
matches it and SURFACE any gap (e.g. BCBS 27¢) rather than absorbing it. Catches the
"carrier paid X but we recorded Y" error class.

---

## 4. Phase B — UHC New-to-Medicare math (after A)

Tim provides many worked examples (a row's amount + how AJ hand-splits it into agent vs
override, with effective date / comp_type / plan). Process:
1. Reverse-engineer the split formula (months-remaining = 13 − effective_month; agent_base =
   PMPM × months_remaining; override = the rest; comp_type I vs R may differ).
2. **Test the formula against EVERY example.** Rows it reproduces to the penny →
   auto-classify with confidence. Rows it cannot → stay honestly quarantined (now safe:
   Phase A made quarantine fully audited + undoable).
3. Honesty rule: if a case depends on info NOT in the file (AJ's outside knowledge, or UHC
   being internally inconsistent), it CANNOT be 100% automated — the portal flags it, never
   fakes a number. The completeness invariant keeps even those balanced + visible.

Goal: drive UHC quarantine from ~80 toward a small, clean, predictable handful per period.

---

## 5. Parking lot — explicit "DO NOT GUESS"

- **Betty's commission model.** Flat $100 per new/initial enrollment, NO renewals, plus an
  hourly fee Brian pays OUTSIDE the portal. **BLOCKED — get real specifics from AJ/Brian**
  before building: (a) chargeback behavior (does a reversed enrollment claw back her $100?),
  (b) which carriers the $100 covers, (c) the exact "$100-eligible" trigger (carrier
  new/initial flag, or only first-ever Medicare?). Tim only learned this contract exists on
  2026-06-17 (previously assumed she was on Mike/Anjana's split). The design leaves a clean
  slot for a per-agent FLAT-RATE commission model (distinct from carrier-split); build
  nothing for Betty until confirmed. Applying a normal renewal split to Betty would make
  every Betty number wrong.
- **Carrier pay-lag labels / forecasting.** Phase C clarity feature ("June BCBS reflects
  ~April business" + optional "you wrote $X → expect ~August"). Phase A only SHOWS the two
  dates; it does not compute or shift.
- **White-label multi-tenant** (Tidewater + downline). After Founders is rock-solid. The
  multi-tenant plumbing (`agency_id` scoping) already exists, so this de-risks rather than
  discards. Will need: per-agency carrier configs, per-agency split rules, self-serve
  carrier-format onboarding, per-agency isolation/billing.
- **Competitive UX polish pass.** A SEPARATE whole-portal UX audit AFTER commission
  correctness is proven — benchmark every module vs AgencyBloc / Radius / HubSpot, borrow
  what they get right (command-center landing, progressive disclosure, status-at-a-glance),
  beat them where they're weak (their commission reconciliation is shallow + unproven; they
  hide the math; they're built for power users not skeptical owners). Founders' wedge: DEEP +
  PROVABLE commissions, TRUSTABLE by a non-technical owner. Phase A bakes in CLARITY (the
  3-question principle) but not pixel-polish.

---

## 6. Non-goals / guardrails

- Do NOT hardcode any carrier's column positions outside that carrier's extractor.
- Do NOT build a universal/single parser — per-carrier extractors are the safety boundary.
- Do NOT shift commissions between periods or forecast based on effective dates (Phase A).
- Do NOT invent numbers for the UHC hard rows — flag honestly when not derivable.
- Do NOT build anything for Betty on assumptions.
- An edit/resolution must NEVER be able to break the `agent + override = raw` invariant.
- Re-upload must NEVER silently lose human work or double-count.

## 7. Verification (how we know it's done)

- Every statement shows a clear balance STATUS; a forced off-balance file shows `✗`, not a
  silent pass.
- AJ can resolve a row, see it in the audit trail (who/when/before→after), and UNDO it to the
  exact prior state.
- A re-upload of a corrected file preserves AJ's prior resolutions (or clearly re-prompts);
  proven on real Postgres with a real re-upload.
- For UHC New (Phase B): the derived formula reproduces 100% of Tim's worked examples to the
  penny, or the non-fitting cases are explicitly, honestly quarantined.
- The reconciliation Brian cares about: the portal's per-agent per-carrier totals equal AJ's
  manual Excel to the penny for a full month, across all carriers.
- Full test suite green; verified on real Postgres (SQLite hides partial-index/autoflush bugs).

## 8. Open questions for Tim (carry into planning)

1. Re-upload safety mechanism: confirm the desired behavior when a re-uploaded row conflicts
   with a prior manual split — auto-preserve silently, or surface "keep your split / redo"?
2. Statement lock: who can lock/unlock — AJ + admins only? Does a locked statement still
   allow Undo of a pre-lock action, or must it be unlocked first?
3. Betty specifics (the three parked questions in §5) — needed before any Betty work.
4. UHC worked examples — Tim to supply; volume + which comp_types/plans are covered.
