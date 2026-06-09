# Devoted Two-File Support — Design Spec (R1.1)

**Date:** 2026-06-08
**Status:** Approved (brainstorm complete) — ready for implementation planning
**Part of:** the Commission Balancing System. Follows R1 (commission ledger completeness), which is built + deployed. Promoted ahead of R2 at Tim's request.
**Related:** [[commission-balancing-system]], [[devoted-dual-file-problem]], R1 spec `2026-06-08-commission-ledger-completeness-design.md`.

## Problem

Devoted ships **two structurally-different files** per month, and the portal currently handles only the first:

1. **Agency file** (`Founders Devoted April 2026 …xlsx`) — all agents **except Rebekah Long** (the principal). Sheets: `Total / Override / Agent Portion / HRA`. This is what R1's `extract_lineitems_devoted` and the customer-sync `normalize_devoted` already parse.
2. **Rebekah's per-agent statement** (`20182775_Rebekah_Long_…xlsx`) — Rebekah only. Sheets: `Summary / Detail / Misc`. A statement-style document with a running balance. **Not parseable by the current code** (different sheet names) and, until re-downloaded as clean `.xlsx`, not even loadable.

Two consequences make R1's "every cent provable" guarantee fail for Devoted specifically:

- **Rebekah's money is invisible.** Her file's format isn't recognized, so none of her commissions/clawbacks land in the ledger.
- **Statement-identity collision.** A `CommissionStatement` is keyed `(carrier, agent_id=NULL, period_label)`, and `CommissionLineItem` / `PolicyPayment` are keyed `(statement_id, source_ref)`. Both Devoted files resolve to the *same* statement, and the replace-on-reupload cleanup blanket-deletes all of a statement's rows — so uploading the second Devoted file wipes the first's line items.

This spec makes both Devoted files coexist under one monthly Devoted statement, fully ledgered and balanced.

## Verified facts (from the real fixtures)

- The Rebekah file's `Detail` sheet has **identical column indices** to the agency file's `Agent Portion` sheet: Agent NPN=1, Agent Name=2, Member ID=3, Member HICN=4, First=5, Last=6, Effective Date=9, Disenroll Date=10, Commission Type=15, **Base Amount=17**. The statement extractor reuses the exact agency column logic.
- The Rebekah `Misc` sheet is **identical to the agency `HRA` sheet**: Rep Name=0, Rep ID=1, Amount=2, Note=3. The difference is the amounts are **negative** (`($50.00)` HRA clawbacks).
- Rebekah file money (verified): `Detail` = 2 renewals @ $28.91 = **+$57.82**; `Misc` = 8 HRA clawbacks @ −$50 = **−$400.00**; current-period net = **−$342.18**. The `Summary` "Balance" row (−$375.93) is a **prior-period carryforward**; "Sub Total"/"TOTAL" (−$718.11) = current (−$342.18) + carryforward (−$375.93).
- Rebekah is **absent** from the agency file's Agent Portion sheet (confirmed) — the two files are disjoint in agent coverage, so combining them is additive, not duplicative.
- The clean-`.xlsx` Rebekah file **loads fine** via the existing `load_sheets` (no loader change needed).

## Out of scope

- **Loader repair** — dropped. The `.xls`-that-was-malformed-XLSX problem is solved by re-downloading as clean `.xlsx`; the existing loader reads it. (If a future malformed export recurs, revisit then.)
- **Carryforward operational semantics** — how AJ actually pays against a rolling negative balance is R2 (payout statement), not this ledger work. The `Summary` carryforward is *not* recorded as a line item here.
- **Why Rebekah gets a separate file** — AJ to clarify; does not affect parsing (we detect by sheet shape, not by agent).
- **UHC** (R4). **Other carriers' replace behavior** — unchanged (single-file).

## Architecture

Four focused changes, all within the existing commission modules. No new model or migration (`source_ref` already exists and is the idempotency key).

### Component 1 — Devoted format detection

A helper `_devoted_format(sheets) -> "agency" | "statement"` in `app/commission/ledger.py` (and mirrored for the normalizer):
- `"Agent Portion" in sheets` → `"agency"`.
- `"Detail" in sheets and "Misc" in sheets` → `"statement"`.
- neither → raise `ValueError` naming the carrier and the sheet names found (fail loud, don't silently produce zero rows).

Both `extract_lineitems_devoted` (ledger) and `normalize_devoted` (customer-sync) call it and branch.

### Component 2 — Rebekah statement extractor (ledger + normalizer)

For `"statement"` format, in `extract_lineitems_devoted`:
- **`Detail` sheet** → one line item per member row, reusing the agency Agent-Portion column logic (Member ID=3, HICN=4, First=5, Last=6, Eff=9, Disenroll=10, Base Amount=17). Classification: negative amount OR disenroll date → `chargeback` (agent split applies); else `agent_commission`. `source_ref = devoted::<filetoken>::Detail::<idx>`.
- **`Misc` sheet** → one line item per row, reusing the agency HRA column logic (Rep=0, Amount=2, Note=3). Classification: **negative amount → `chargeback`** (HRA clawback, agent split applies); positive → `hra_bonus`. `member_name` from the Note (col 3). `source_ref = devoted::<filetoken>::Misc::<idx>`.
- **`Summary` sheet → NOT extracted.** Its "Balance"/carryforward is prior-period money; recording it would double-count and break per-period balancing (consistent with the agency format never extracting its `Total` sheet).

`normalize_devoted` (customer-sync) gets the matching statement branch so `PolicyPayment` stays in sync: Detail rows → MemberFacts (ENROLLMENT/RENEWAL/CHARGEBACK via the existing `_classify_devoted`), Misc rows → `NON_CUSTOMER` facts (HRA), negatives flagged chargeback. (The normalizer collapses paired rows by design, but the statement file has no Override sheet to pair, so each Detail row stands alone.)

### Component 3 — Negative-override consistency fix (agency format)

In the existing agency Override handling (`extract_lineitems_devoted`): a **negative** Override amount → `chargeback` with **`split_rate=None`** (a clawed-back override is 100% Founders money — `split_breakdown` returns payout 0, keep = the full negative amount). A **positive** Override amount stays `founders_override` (also `split_rate=None`).

Locked rule (applies project-wide to the ledger): **`classification` is the human-readable label; `split_rate` drives the math.** `split_rate=None` means "no split — Founders keeps/absorbs the whole amount." So both negative overrides and negative agent-HRA classify as `chargeback`, but agent-side chargebacks keep the agent's split_rate while override chargebacks get `None`. No change to `split_breakdown`, no new classification, balance holds by construction. (This also corrects the R1 behavior where negative overrides were mislabeled `founders_override`.)

### Component 4 — Per-file discriminator + file-scoped replace

**Filetoken (stable per file, distinct between the two Devoted files):**
- agency format → `"agency"`.
- statement format → `"npn" + <Agent NPN from Detail col 1>` (e.g. `npn20182775`). Data-driven and stable across re-uploads of the same file.

A helper `_devoted_filetoken(sheets, fmt) -> str` computes it.

**source_ref change (both ledgers):** every Devoted `source_ref` becomes `devoted::<filetoken>::<sheet>::<rowidx>`:
- agency: `devoted::agency::Agent Portion::5`, `devoted::agency::Override::8`, `devoted::agency::HRA::2`
- statement: `devoted::npn20182775::Detail::1`, `devoted::npn20182775::Misc::3`

This applies to `extract_lineitems_devoted` (CommissionLineItem) **and** `normalize_devoted` (PolicyPayment via MemberFact.source_ref) so both ledgers are file-scoped.

**File-scoped replace-on-reupload (`app/commission/routes.py`, `_ingest_normalized_upload`):** today the replace block blanket-deletes `WHERE statement_id=X` for both `PolicyPayment` and `CommissionLineItem`. Change so that **for Devoted**, the delete is scoped to the uploaded file's rows: `... AND source_ref LIKE 'devoted::<filetoken>::%'`. For non-Devoted carriers, keep the existing blanket delete (single-file; no behavior change). The filetoken for the delete is computed from the just-loaded `sheets` before ingest, using the same `_devoted_filetoken` helper.

Result: uploading the agency file then the Rebekah file produces line items for **both** under one `(Devoted, period)` statement; re-uploading either file replaces only its own rows (idempotent, no cross-file wipe).

## Data flow (one month, two uploads)

1. AJ uploads `Founders Devoted April 2026.xlsx` → detected `agency` → filetoken `agency` → agency replace-scope (deletes only `devoted::agency::%`, none yet) → line items `devoted::agency::*` written (73 rows incl. negative-override→chargeback fix).
2. AJ uploads `20182775_Rebekah_Long.xlsx` → detected `statement` → filetoken `npn20182775` → statement replace-scope (deletes only `devoted::npn20182775::%`, none yet) → line items `devoted::npn20182775::Detail/Misc` written (10 rows, net −$342.18). Agency rows untouched.
3. Both coexist under the same statement. `verify_statement_balance` is computed per upload against that file's `money_rows_total` (agency sum / statement Detail+Misc sum), so each file balances independently.

## Testing

Real fixtures: the agency Devoted file + the re-downloaded Rebekah `.xlsx` (`tests/fixtures/commission/`). In `tests/test_commission_ledger.py` (+ a normalizer test where relevant):

- **Format detection:** agency file → `"agency"`; Rebekah file → `"statement"`; a bogus sheet set → `ValueError`.
- **Statement extractor:** Rebekah file → 2 Detail `agent_commission` + 8 Misc `chargeback` line items; Summary not extracted; `Σ raw == −342.18`; `money_rows_total` (Detail+Misc) matches; carryforward −375.93 is absent.
- **Negative-override fix:** an agency Override row with a negative amount → `chargeback` with `split_rate is None`; `split_breakdown` → payout 0, keep = full negative; positive override still `founders_override`.
- **Filetoken + source_ref:** agency rows carry `devoted::agency::…`; statement rows carry `devoted::npn20182775::…`; tokens differ between files.
- **Coexistence + file-scoped replace (integration-style with DB fixtures):** persist agency line items, then persist statement line items under the same statement → both present; re-persist the statement file → only `npn20182775` rows replaced, agency rows intact (count unchanged); idempotent (no duplicates on re-run).
- **Balance still holds:** `Σ raw == Σ agent_payout + Σ founders_keep` for each file.

## Deliverable

`_devoted_format` + `_devoted_filetoken` helpers, Rebekah statement branch in `extract_lineitems_devoted` and `normalize_devoted`, negative-override→chargeback fix, file-tagged Devoted `source_ref` across both ledgers, file-scoped Devoted replace in `routes.py`, full tests. Both Devoted files tracked, attributed, and balance-verified under one monthly statement — closing the R1 known limitation for Devoted.

## Open items (non-blocking; for AJ / R2)
- Why Devoted issues Rebekah a separate per-agent statement (principal-agent quirk, reason unconfirmed).
- Confirm the −$375.93 carryforward is prior-period money (assumed; not recorded as a line item).
- How AJ pays against a rolling negative balance (R2 payout semantics).
