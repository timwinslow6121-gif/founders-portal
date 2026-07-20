# Carrier Commission Models — validated notes (2026-06-11)

These are the REAL split rules, validated against AJ's per-agent answer-key files.
Folder structure: `2026-05_cycle/raw/<carrier>/` = what we parse;
`2026-05_cycle/aj-computed/<carrier>/` = AJ's answer key (his hand-split, validate against).

## Universal model (UHC + Devoted both follow this)
Two money types only:
- **Agent commission/renewal** → SPLITS at the agent's contract rate.
- **Founders override** → 100% to Founders Agency (treated as its own "agent"), NO split.
AJ's algorithm: per payment, peel off any override (→ Founders), SUM each agent's
portion, then apply the contract rate ONCE at the end (sum-then-split; sig figs matter).

## DEVOTED — VALIDATED (matches AJ to the penny: Brian/Michael/Tim exact)
- RAW file = `Founders Devoted April 2026 TM May 2026.xlsx`, 4 sheets:
  - **Agent Portion** (name=col2, amount=col17 "Base Amount") = clean agent money,
    override ALREADY stripped out. SPLITS at agent rate.
  - **HRA** (name=col0, amount=col2) = $50 Health Risk Assessment bonus. Part of the
    agent portion — SPLITS at the agent's rate ($50 × rate = agent take).
  - **Override** (sheet) = 100% Founders Agency, NO split.
  - **Total** = reconciliation.
- **AGENT PAYOUT = (Σ that agent's Agent-Portion lines + their HRA lines) × contract rate.**
- Rebekah ships a SEPARATE file (`20182775_Rebekah_Long_*.xlsx`, Summary/Detail/Misc) —
  the R1.1 two-file case. Both combine into one Devoted statement.
- **CONTRACT RATES (the bug was Brian):**
  - **Brian Freeman = 0.50** (50/50, NOT 0.55 — AJ confirmed). ⚠ our code used 0.55.
  - Michael Lauzurique = 0.525, Betty Marlowe = 0.525
  - Everyone else = 0.55
- **WRINKLE (UHC + maybe Devoted):** 2 RETIRED agents (Cyndi Mortimer, Donald Long)
  get small commissions; their 50% AGENT SPLIT rolls UP to Brian's total (his downline).
- Validation: Brian $1,264.50 ✓, Michael $720.47 ✓, Tim $695.48 ✓ (Chris/Justin off by
  cents = AJ rounding; Anjana's AJ file mixed March data → ignore that diff).

## UHC — VALIDATED (see docs/superpowers/specs/2026-06-11-uhc-raw-parser-design.md)
Same two-type model. $28.92 renewal (splits) + $4.59 override (Founders). Built, 97.7%
auto. Brian = 0.50 here too (per the retired-agent rollup note). NOT yet wired live.

## OTHER CARRIERS (status vs AJ, 2026-06-11)
- **Healthspring**: ✅ exact (penny). Done.
- **BCBS**: 27¢ total across all agents = rounding. Essentially correct.
- **Aetna**: -$18 off. Small, real — needs a few lines reconciled.
- **Devoted**: model now validated; code fix = Brian's 0.50 rate + don't mix override into agent split.
- **UHC**: 97.7% auto, validated, not wired live.

## KEY METHOD (learned the hard way 2026-06-11)
Validate MONEY code against AJ's real answer-key files, not numbers typed from memory.
AJ's per-agent files have his math at the bottom (`<sum> x.55 = <payout>`) — that's the
ground truth for each agent's rate AND payout. Reorganizing raw-vs-computed files is what
exposed Brian's 0.50 rate. Don't jump to code before the model matches the answer key.

## UPDATE 2026-06-11 — our parser CAUGHT an AJ error (Devoted validation)
Chris Foster: our parser = $722.97 (both his HRAs); AJ had $695.47 (he MISSED the
2nd HRA — Google Sheets filter cut off the top row). So OUR number was right.
Lesson reinforced: validate against the RAW file's actual data (completeness
invariant), NOT "match AJ's hand-math exactly" — AJ's files have human errors.
The automation's value: doesn't get tired, doesn't lose rows to spreadsheet bugs.

Devoted model = CONFIRMED CORRECT. Only real code fix outstanding:
- **Brian Freeman Devoted split = 0.50** (currently 0.55 in our data). Contract-data fix.
- (Retired agents Cyndi M + Don L: their agent split rolls up to Brian — UHC at least;
   confirm whether Devoted too.)
