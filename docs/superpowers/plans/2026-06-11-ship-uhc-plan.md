# Ship UHC — wire the validated raw parser live (full normalized pipeline + quarantine tab)

## Goal
AJ uploads the raw UHC statement (`Commission Transactions` sheet, ~3,140 rows) and the portal
auto-splits the routine rows into the R1 ledger (so UHC appears in the agent recap, payment ledger,
and customer sync), while surfacing the ~89 quarantined rows in a **quarantine tab** for AJ to
hand-split. Replaces AJ's monthly hand-splitting of ~3,100 lines.

## Current state (verified this session)
- `extract_lineitems_uhc` + `money_rows_total_uhc` exist in `ledger.py`, validated (97.7% auto, all
  agents balance to the penny). Quarantined rows are tagged `NEEDS_MANUAL_REVIEW`.
- Detection ALREADY works: `_detect_carrier_from_sheets` → "UHC" on the real raw file.
- Retired-agent rollup (Cyndi/Don → Brian @0.50) is ALREADY wired for UHC at all 3 seams.
- BLOCKERS: UHC is **not** in `EXTRACTORS` (ledger) and **not** in `NORMALIZERS` (so it falls to the
  legacy path = PolicyPayment only, no CommissionLineItem, no recap). The legacy `PARSERS["UHC"]` +
  `payments.extract_uhc` exist but produce the OLD un-split behavior.

## Approach (chosen): full normalized pipeline + quarantine tab

### Task 1 — `normalize_uhc(sheets)` in normalizers.py  [TDD]
Reduce the `Commission Transactions` sheet to `List[MemberFact]` (drives PolicyPayment + customer sync).
- Model on `normalize_aetna` (agency-level, agent via writing_agent_raw).
- Columns (same indices as the ledger extractor): agent=5, member=7, mbi=8, plan_type=12,
  contract=13, pbp=14, eff=11, action=19, amount=23.
- `row_class` via a `_classify_uhc(action, amount)`: chargeback if amount<0 or action has
  "chargeback"; enrollment if action startswith "new"; else renewal. HA/override/dust → NON_CUSTOMER
  (payment-only, no customer create) — mirror how the ledger treats them so we don't spawn junk stubs.
- `source_ref = f"uhc::0::{idx}"` (matches the ledger extractor's scheme → idempotent replace works).
- Skip zero-amount and empty rows (same guards as the extractor).
- Tests: `tests/test_commission_normalizers.py` — classify cases + that it reduces the real sheet shape
  to facts with correct mbi/agent/amount and NON_CUSTOMER for HA/override.

### Task 2 — register UHC in both registries
- `normalizers.py`: add `"UHC": normalize_uhc` to `NORMALIZERS`.
- `ledger.py`: add `"UHC": (extract_lineitems_uhc, money_rows_total_uhc)` to `EXTRACTORS`, and
  DELETE the stale "⚠ UHC deliberately NOT registered / KNOWN-WRONG totals" warning block (superseded
  by validation).
- Effect: UHC now flows through `_ingest_normalized_upload` → ledger + member facts + rollup.

### Task 3 — quarantine is already persisted (NO migration)  [TDD]
The ledger drafts already carry `classification == NEEDS_MANUAL_REVIEW` and `persist_line_items`
already writes them as `CommissionLineItem` rows (split_rate=None → payout 0, so they never enter an
agent's payout). So there is **nothing new to persist** — the quarantine tab just QUERIES
`CommissionLineItem` where `classification == 'needs_manual_review'` for the statement. No new column,
no migration.
- Add a small helper `quarantined_line_items(statement_id, agency_id)` (recap.py or routes.py) →
  rows + count + total, for the tab + the flash message.
- Tests: a new `tests/test_uhc_pipeline.py` — given the real fixture, assert N quarantined rows
  exist, their total matches `money_rows_total - Σ(auto rows)`, and every agent balances to the penny.

### Task 4 — quarantine tab UI (mirror the unresolvable-BOB quarantine pattern)
- In the commission admin / statement detail view, when a statement has quarantine rows, show a tab
  listing them (member, amount, action, mbi) so AJ can hand-split. Read-only list this round
  (AJ keys them wherever he does today) + show the **total** so nothing is silently dropped.
- Flash on upload: append `, N lines ($X) need manual review — see Quarantine tab`.
- Find the existing template + route for the import/statement modal; add the tab there.

### Task 5 — verify on the REAL raw file end-to-end (offline harness, then VPS dry-run)
- Run the full pipeline against `statement-2813549-...xlsx` locally: assert the completeness invariant
  (every agent balances to the penny), quarantine count ≈89/2.3%, and recap totals are sane.
- Do NOT make it system-of-record until AJ reviews one real upload run (his sign-off, per the resume).

## Out of scope (explicitly)
- The "New" enrollment proration math (cols L/T/AA/AB) — stays quarantined (irreducible; route to AJ).
- Med-Supp pairing confirmation across more months (Tim ~80% confident; revisit later).
- Aetna Medigap supplement parser (separate deferred task).

## Risks / guards
- **Don't double-count:** UHC must take the normalized path ONLY (remove/bypass the legacy
  `PARSERS["UHC"]` branch for UHC, or ensure the NORMALIZERS check short-circuits before it — it
  already does at routes.py:1010, but verify UHC can't also hit the legacy block on any code path).
- **source_ref parity:** normalizer + ledger must use the SAME `uhc::0::idx` scheme so re-upload
  replace is clean and PolicyPayment/CommissionLineItem align.
- **split rates:** production uses real `AgentCarrierContract` rates via `_ledger_split_lookup`
  (not the test 0.55 hardcode) — already true through the live seam.
- **No migration** — quarantine rows are already persisted as NEEDS_MANUAL_REVIEW CommissionLineItems
  (Task 3 just queries them). Nothing destructive on the VPS.

## Verification (must pass before "done")
1. Full test suite green (currently 208).
2. Offline: real UHC raw file → all agents balance to the penny, ~89 quarantined, total reconciles.
3. Deploy to VPS; live dry-run upload; confirm UHC block appears in a recap with sane numbers and the
   quarantine tab lists the flagged lines. Flag for AJ's review before system-of-record.
