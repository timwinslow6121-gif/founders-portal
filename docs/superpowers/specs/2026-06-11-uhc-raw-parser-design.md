# UHC Raw Commission Parser (R4, partial) — Design

**Date:** 2026-06-11
**Goal:** Let AJ upload the RAW UHC carrier statement and have the portal auto-split the easy ~90% of lines (agent pay vs Founders override) into the R1 commission ledger, quarantining the hard 5-10% for manual review. Saves AJ hours/month.
**Status:** ✅ Implemented + validated (97.7% auto, all agents balance to the penny). NOT yet wired to live upload (pending "New" enrollments + AJ review). 2026-06-11.

---

## 1. The three UHC file types (verified from real files 2026-06-11)
Folder: `docs/Commission DL/Raw commissions docs from AJ/UHC/`
1. **RAW carrier statement** `statement-NNNN-YYYYMMDD.xlsx` — THE SOURCE the parser ingests. Sheets: `Commission Transactions` (the data), `Commission Summary` (payment totals), `Held Transactions` (out-of-state, NOT yet paid — SKIP). 30 cols.
2. **`UHC - Founders ...xlsx`** — AJ's MANUALLY-split version (gross/agent/override in 3 cols). This is the **ANSWER KEY** to validate the parser against — NOT ingested.
3. **`UHC - <agent> ...xlsx`** — per-agent cut. Helper only, not ingested.

## 2. RAW file columns (`Commission Transactions` sheet, 0-indexed, header=row 0)
- col5 = Writing Agent Name ("LAST, FIRST ..."), col7 = Member Name, col8 = MedicareID (MBI)
- col11 = Original Effective Date, col12 = Plan Type, col13 = Contract, col14 = PBP
- **col19 = Commission Action** (the classifier), **col23 = Commission** (the $ amount), col26 = Comp Type
- (Matches the existing `extract_uhc` in payments.py — verified.)

## 3. The split logic — CORRECTED 2026-06-11 after validation against AJ's answer key (THE REAL RULE)

**⚠ My first pass was WRONG and validation caught it** (Tim easy raw came out $7,707 vs AJ's $6,586, +17%). The fix: UHC has TWO money components per member that must be separated — this is the `agent_commission` vs `founders_override` distinction R1 already models.

**The rule (Tim explained + confirmed in raw data):**
- **Agent renewal** (e.g. **$28.92** for MAPD/DSNP, = UHC's rounding of $347/yr ÷ 12) → `agent_commission`, SPLIT: agent gets `× split_rate` (55% Tim), Founders gets the rest.
- **Founders override** (e.g. **$4.59**, = ~$55/yr ÷ 12) → `founders_override`, **100% to Founders, NO split, NOT shared with the agent** (split_rate=None — R1 already handles this classification).
- **Combined rows** (e.g. **$33.51 = $28.92 + $4.59**) — UHC sometimes emits ONE line that bundles renewal+override. These MUST be DECOMPOSED into two line items: a $28.92 `agent_commission` (split) + a $4.59 `founders_override` (Founders-only). The override is the fixed per-plan adder; renewal = remainder.

**Verified in the raw data (statement May 2026):** distinct renewal amounts = $28.92 (1057×, the split renewal), $4.59 (1087×, the standalone override), $33.51 (824×, the combined). ADAMS DARRELL shows the two-line form ($28.92 + $4.59, DSNP/H5253). So both forms (separate + combined) occur and net to the same agency economics.

**✅ IMPLEMENTED + VALIDATED 2026-06-11.** The full rule set (all from Tim, all confirmed in data) is now coded in `extract_lineitems_uhc`:
- **Override = flat $4.59/mo** on every override-bearing family (MA *and* Part D — same amount). 100% Founders, no split.
- **Combined decomposition:** $33.51 (HMO) → $28.92 renewal + $4.59 override; $30.68 (non-SNP PPO) → $26.09 renewal + $4.59 override. ($26.09 = the PPO renewal, splits like a normal renewal.)
- **Med-Supp (AARPMODMEDSUP):** premium-based, paired per member → larger line = renewal (splits), smaller = Founders override. Only for the LOA agents who write it (Tim/Chris/Justin/Michael/Don); others' Med-Supp → quarantine (rule unconfirmed, small BOBs).
- **HA payments ($50):** split agent%/Founders%, NO override (corrected — earlier draft wrongly quarantined them).
- **PARTD "dust" (<$1, e.g. $0.26):** quarantine (AJ drops these from renewal totals).
- **"New" enrollments:** QUARANTINE — genuinely complex (Tim: cols L/T/AA/AB interact, proration by months-remaining); the one piece NOT auto-handled yet.

**VALIDATION = the completeness invariant (the real ground truth):** every agent's line-item total sums EXACTLY to the raw file's per-agent total — every dollar reclassified, none lost/created (all 11 agents balance to the penny). Tim's renewal-only reconciles to his AJ file ($6,549.05 exact); Michael's renewal+override reconciles to his ($9,751.81 exact). KEY LESSON: AJ's per-agent files are INCONSISTENT (some keep $33.51 combined, some pre-split), so "match AJ's renewal sum" is NOT a clean validation target — the per-agent completeness balance is. **Result: 97.7% of lines auto-classified, only 2.3% (89/3944) quarantined.**

**REMAINING before wiring live (next session):**
1. **"New" enrollments** — the deep cols L/T/AA/AB analysis (months-remaining proration for new MA/PPO). The last meaningful chunk.
2. Confirm Med-Supp larger=renewal/smaller=override across a few months (Tim ~80% sure; needs more statements).
3. Wire into upload: add "UHC" to `EXTRACTORS` + a detection fingerprint (sheet "Commission Transactions" + headers Writing Agent Name/Commission Action/MedicareID), then have AJ review a real run before it's system-of-record.
- **SUM-THEN-SPLIT (sig-fig rule):** the agent's payout = (Σ all their easy raw_amounts) × rate, applied ONCE at the end, NOT line-by-line — avoids per-line rounding drift (same rule R1 `split_breakdown` already uses: store raw_amount per line, derive split, reconcile at total). Tim flagged: significant figures matter; never round mid-calc.
- **HARD rows** (the ~5-10%, QUARANTINE for manual review — do NOT auto-calc):
  - `HA payment for agent ID NNNN for member ...` / `HA payment for solicitor agent ID ...` — $50 Health-Assessment bonuses paid in FULL to a specific agent identified by ID embedded in the text (no split). Needs name↔agent-ID resolution.
  - `HA chargeback for solicitor agent ID ...` — negative HA clawback.
  - Any `Commission Action` that is free-text/garbage ("a", "New, DVH Manual Payment, ...") — non-standard, manual.
  - (Note: in the RAW file these HA rows ARE present in col19 as the long text; classify by `action.startswith("HA ")` or contains "DVH Manual" or action not in the known-clean set.)

## 4. Build (this session, partial)
- **`extract_lineitems_uhc(sheets, split_lookup)`** in `app/commission/ledger.py`, mirroring the per-agent carrier pattern but UHC is **agency-wide ONE raw file** (not per-agent) — agent comes from col5 per row (like Aetna). Reads `Commission Transactions` only (skip Summary + Held).
  - For each data row: resolve agent from col5 (reuse `_resolve_agent_id`/name-normalize from payments.py — handles "LAST, FIRST" + nicknames). Classify col19:
    - clean (Renewal/New/their negatives) → `LineItemDraft(carrier="UHC", classification="agent_commission" or "chargeback" if negative, raw_amount=col23, split_rate=agent's rate, agent_id=resolved, member/mbi from col7/col8, source_ref=f"uhc::{stmt}::{rowidx}")`.
    - HARD (HA*/DVH/garbage/unresolved agent) → flag for quarantine: classification="needs_manual_review", split_rate=None, keep raw_amount + the full action text in a note. These import but are visibly flagged (AJ handles manually). DO NOT guess their split.
  - UHC is agency-wide → blanket-replace on re-upload (like Humana/Aetna), source_ref = `uhc::<statementdate-or-fingerprint>::<rowidx>`.
- **Detection:** add UHC to the upload detection — fingerprint the raw file by sheet name `Commission Transactions` + headers `Writing Agent Name`+`Commission Action`+`MedicareID`.

## 5. VALIDATION (the key step — we have the answer key)
After building, run the parser on the RAW `statement...` file and compare the per-agent EASY totals against the `UHC - Founders` answer-key file (and/or the per-agent `UHC - <name>` files). The easy-row agent payouts must reconcile (within rounding) to AJ's numbers. The hard-row count + list should match the HA/chargeback/garbage lines. If they don't reconcile, the split logic is wrong — fix before shipping. This is "verify against real data," not just green tests.

## 6. Out of scope (this session / later = full R4)
- Auto-calculating the HARD rows (HA bonuses with agent-ID resolution, DVH manual, the embedded-override UHC LOA cases). Those stay manual/quarantined.
- The `Commission Summary` reconciliation (does Σ line items match the carrier's stated payment total). A good R4 add.
- Customer/policy enrichment from the raw file (it HAS MBI/plan/contract — could feed the commission→customer sync later).

Builds on R1 ledger (`LineItemDraft`, `split_breakdown`, `CommissionLineItem`). See [[commission-balancing-system]], [[raw-commission-vocab]].
