# Commission Docs — organized (2026-06-11)

Clean structure to stop the raw-vs-computed confusion. **These are COPIES** —
originals still live in the messy `Commission docs/` + `Raw commissions docs from AJ/`
folders (not yet deleted — confirm before cleanup).

## Layout
```
2026-05_cycle/                  ← current cycle (April book of business, paid May 2026)
  raw/<carrier>/                ← RAW carrier downloads = WHAT THE PARSER INGESTS
  aj-computed/<carrier>/        ← AJ's hand-split per-agent files = THE ANSWER KEY (validate against)
_archive_old_months/           ← March cycle (stale)
_reference_images/             ← recap screenshots/jpgs (not statements)
_unsorted/                     ← anything unclassified
```

## What's a "raw" vs "aj-computed" file?
- **RAW** = the carrier's own download. UHC: `statement-NNNN-*.xlsx` (3 sheets). Devoted:
  `Founders Devoted ... .xlsx` (Total/Override/Agent Portion/HRA) + Rebekah's separate
  `20182775_*.xlsx`. BCBS: one `<Agent> (Founders) BCBS NC ...` file per agent.
  Healthspring: `NN_NNNNNN.xlsx` batch files. Aetna: `Aetna Founders - *.xlsx`.
  Humana: `CommissionData (N).xls`.
- **AJ-COMPUTED** = AJ's per-agent worked file with his split math at the bottom
  (`<sum> x.55 = <payout>`). The ground truth for each agent's RATE + payout.

## Current sort status (2026-06-11)
- raw/: UHC ✓, Devoted ✓, BCBS ✓(7), Healthspring ✓(4), Aetna ✓, Humana ✓
- aj-computed/: UHC ✓(8), Devoted ✓(8). BCBS/Aetna/Humana/Healthspring answer keys
  NOT yet separated (likely in the old `Commission docs/` folder; grab when reconciling
  those carriers — only Aetna -$18 actually needs fixing; Healthspring penny-perfect, BCBS 27¢).

## Validated carrier models: see CARRIER_MODELS_NOTES.md (the split rules + per-agent rates).
