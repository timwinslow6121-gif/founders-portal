# Commission Ledger Completeness — Design Spec (R1)

**Date:** 2026-06-08
**Status:** Approved (brainstorm complete) — ready for implementation planning
**Part of:** the Commission Balancing System. R1 is the data foundation.

## The larger goal (context)

AJ's job each month: take the carrier commission files, calculate exactly what goes to each agent vs. what Founders keeps, and pay agents — once per month, with a per-agent breakdown by carrier and payment type, chargebacks named. It is fundamentally a **balancing** problem with one invariant:

> **Total across all carrier sheets = (Σ all agent payouts) + (what Founders keeps)**

Every dollar (every cent) must be attributable: carrier → agent → customer → payment type → splittable-or-Founders-keep. All carriers pay **Founders** first (no agent is paid directly by a carrier); the split is applied entirely on the Founders side per each agent's contract. Carrier row labels ("Broker Level", "Agent Portion", "Payee Amount") are bookkeeping terms — the amounts are **pre-split**.

Decomposed into R1→R2→R3→R4:
- **R1. Commission ledger completeness** *(this spec)* — persist every sheet row with full amount + classification + attribution; make balancing provable. 5 clean carriers.
- **R2. Per-agent payout statement** — the monthly per-agent report. *Brainstormed AFTER R1, once AJ's current monthly process is shared, so the report matches his real workflow.*
- **R3. Balance/reconciliation view** — "do the books balance?" made visible.
- **R4. UHC** — the lumped-split hard problem.

R2/R3/R4 are out of scope here.

## Problem (R1)

The current commission import (built for customer-sync) stores only each agent's splittable line + HRA, and **drops the Founders-override / Service-Fee amounts** — there is no column for them, so they're lost at write. You cannot prove "agent pay + Founders keep = carrier total" from stored data. R1 introduces a faithful per-row ledger so balancing is possible and every cent is tracked.

## Architecture

A new `CommissionLineItem` table (a 1:1 mirror of every carrier-sheet row) + per-carrier ledger extractors + upload wiring + a balancing/completeness self-check + a re-import backfill. `PolicyPayment` (customer ledger) and the Plan-1 normalizers (customer-sync) are unchanged and coexist — ledger extractors are a separate "money facts" layer alongside the "customer facts" layer.

### The model

Migration 023 adds `CommissionLineItem`:
```
id, agency_id
statement_id        FK CommissionStatement
carrier             str   # Healthspring | BCBS | Devoted | Aetna | Humana
period_label, statement_date
source_ref          str   # "healthspring::Detail::7" — stable per-row key (idempotent re-import)

agent_id            FK User, nullable      # resolved writing/earning agent (NULL for pure-Founders lines)
customer_id         FK Customer, nullable  # resolved member (NULL for overrides/HRA w/o a member)
member_name         str                    # raw name as on the sheet
mbi, carrier_member_id  str, nullable

raw_amount          Numeric/Float          # exactly what the sheet shows (may be negative). The TRUTH.
split_rate          Float, nullable        # agent's contract split snapshotted at import (NULL for founders_override)

classification      str   # agent_commission | founders_override | hra_bonus | chargeback  (STRING for forward-compat)
payment_type        str, nullable          # renewal | initial | hra | override | ... (descriptive)

created_at
```

`agent_payout` / `founders_keep` are **derived, not stored** — one shared helper (`split_breakdown(line)`):
- `agent_commission` / `hra_bonus` / `chargeback`: `agent_payout = raw_amount × split_rate`; `founders_keep = raw_amount − agent_payout`.
- `founders_override`: `agent_payout = 0`; `founders_keep = raw_amount`.

Rationale (locked): storing raw + rate keeps a single source of truth; a split correction (or Anjana adjustment) re-derives instantly with no stale figures; the balance holds by construction. `classification` is a plain string (no DB enum) so future classes (e.g. `true_up`, `advance_clawback`) need no migration.

### Per-carrier ledger extractors (`app/commission/ledger.py`)

One `extract_lineitems_<carrier>(sheets, statement, agency_id) -> list[CommissionLineItem]` per carrier. Each walks **every** relevant sheet row (does NOT collapse paired rows — the key difference from the Plan-1 normalizers), classifies each, and resolves the agent via the existing `_match_agent_name`. Verified per-carrier rules:

- **Healthspring** (page 2 "Detail"): one line per row, keyed on `Earner Name` + `Payment Description`:
  - `Broker Level` → `agent_commission` (agent = Writing Broker; split applies)
  - `Service Fee` + Founders Insurance Agency → `founders_override` (no split, Founders keeps all)
  - negative amount → `chargeback`
- **BCBS** (Sheet1): use the **Commission** column (NOT Billed Amount). Each row → `agent_commission` (negative → `chargeback`), agent = Agent Name, split applies. 0-commission FY rows are still recorded (balance to $0).
- **Devoted** (BOTH files: `Founders Devoted April 2026` 4 sheets + `20182775_Rebekah_Long`):
  - `Agent Portion` sheet → `agent_commission` (negative → `chargeback`; split applies)
  - `Override` sheet → `founders_override` (no split)
  - `HRA` sheet (col A agent, col B NPN, col C amount) → `hra_bonus` ($amount × split)
- **Aetna**: each row → `agent_commission`/`chargeback`, agent = Writing Agent (col 16), split applies.
- **Humana**: classify by `TxnTypeCd`/sign → `agent_commission`/`chargeback`; `HRAP` → `hra_bonus`; agent = `WaName`; split applies.

`split_rate` is looked up from the resolved agent's `AgentCarrierContract` for that carrier at import (snapshotted). Anjana's conditional rows get her default split + the existing `provenance_conditional` flag handling (carried to R2/R4). UHC: no extractor in R1.

### Upload wiring

In the existing `_ingest_normalized_upload` path (the 5 clean carriers), in addition to the current customer-sync + `PolicyPayment` writes, call the matching ledger extractor and persist its `CommissionLineItem`s for the statement. Idempotent by `source_ref` (re-upload updates in place). Line items populate automatically on every upload going forward.

### Balancing / completeness self-check

`verify_statement_balance(statement)` asserts:
1. **Internal balance (by construction):** `Σ raw_amount == Σ agent_payout + Σ founders_keep`.
2. **Completeness (the valuable check):** `Σ line-item raw_amount == the independent total of the carrier's money rows`, where "money rows" is defined per carrier as ALL the amount-bearing rows across the sheets the extractor is responsible for (e.g. Devoted = Agent Portion + Override + HRA sheets summed; Healthspring = every Detail row's Payment Amount incl. both Broker Level and Service Fee; BCBS = Commission column). This independent total is computed by a separate pass over the raw sheets (NOT from the line items), so a row the extractor dropped or mis-summed makes the two diverge → the check fails loudly, naming the statement. This is the "every cent tracked" guarantee made testable, and the guard that catches a future unhandled row type (the exact bug class that dropped the Founders overrides originally). Note: the per-carrier "money rows" definition lives next to each extractor so the two stay in sync.

### Re-import backfill

`scripts/backfill_commission_lineitems.py` (run on VPS) re-reads already-uploaded commission files and populates line items for existing statements, so AJ's current data is balance-ready. Idempotent / re-runnable. (Uses the same project-root `sys.path` bootstrap as other scripts.)

## Testing

Local SQLite + the real raw fixtures in `tests/fixtures/commission/` (`tests/test_commission_ledger.py`):
- **Per-carrier extraction:** correct line-item count, classification per row (Broker Level→agent_commission, Service Fee→founders_override, HRA→hra_bonus, negatives→chargeback), agent attribution, raw_amount captured. Healthspring: BOTH Broker Level AND Service Fee lines present (override not dropped). Devoted: Override + Agent Portion + HRA all produce line items across both files.
- **Completeness/balance:** `Σ line-item raw == Σ sheet amount column` per carrier; `Σ raw == Σ agent_payout + Σ founders_keep`.
- **Split snapshot + derivation:** split_rate matches contract; payout derivation correct (e.g. BCBS 28.91 × 0.55; founders_override → payout 0, keep = raw).
- **Idempotency:** re-running extraction/backfill yields identical line items (no duplicates, keyed on source_ref).

## Boundaries (what R1 is NOT)

- NOT R2 (payout statement UI), R3 (balance dashboard UI), R4 (UHC). R1 is headless + verifiable.
- NOT touching Plan-1 normalizers or the customer-sync / `PolicyPayment` path (coexist).
- Founders-override amounts are now captured, but no agency-P&L view yet (R3).

## Deliverable

`CommissionLineItem` model + migration 023, `app/commission/ledger.py` (5-carrier extractors + `split_breakdown` helper + `verify_statement_balance`), upload wiring, re-import backfill, full tests. Every cent from the 5 clean carriers tracked, attributed (carrier/agent/customer/payment-type/classification), and balance-verified — the foundation R2 and R3 build on.

## Open items (non-blocking)
- R2 brainstorm waits on Tim sharing AJ's current monthly commission-sharing process.
- Anjana conditional-split exact rule (AJ has it) — her R1 line items use default split + flag; precise handling is R2/R4.
- UHC (R4).
