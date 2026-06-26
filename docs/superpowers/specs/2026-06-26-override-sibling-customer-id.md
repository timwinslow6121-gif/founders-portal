# Override Siblings Drop `customer_id` → Orphaned Line Items

_Date: 2026-06-26 · Status: diagnosed against live prod + real code; spec ready.
**Build after `feat/stub-creation-prevention` (item 1) deploys** (item 1 added the radar that
caught this; keep changes un-stacked). Small money-adjacent fix — TDD, opus review, DB backup,
real-Postgres verify. Pairs naturally with the other UHC commission-edit fixes._

## Why this exists

The Data-Integrity Radar's `payment_without_customer` count rose by ~24 after AJ started
hand-editing UHC commission lines. Tim asked if his edits caused it. **They did — and the radar
working as designed is what surfaced it.**

## Root cause (confirmed in code + live data)

When AJ edits a split (`edit_line_split`) or resolves a quarantined line
(`resolve_quarantine_line`), the code creates a Founders-override **sibling** line item with
`source_ref = "<parent>::ovr"`. The sibling constructor copies the parent's `member_name`, `mbi`,
and `carrier_member_id` — but **NOT `customer_id`** (`app/commission/ledger.py:1150-1155` for
`edit_line_split`; the same omission in `resolve_quarantine_line`). So every newly-created
override sibling is born with `customer_id = NULL` → an orphaned money fact the
`payment_without_customer` invariant counts.

**Live data confirms (prod, agency_id=1):**
- 8 NULL-customer rows with `payment_type = "override [edited]"` (from `edit_line_split`).
- 16 NULL-customer rows with `payment_type = "override [resolved]"` (from `resolve_quarantine_line`).
- = **24 edit/resolve-created override siblings with no customer** — exactly the radar's "+24".

The override sibling represents the **same member** as its parent line, so it should carry the
**same `customer_id`**. There is no reason for it to be NULL.

(Separately, the NULL-customer count also includes a pre-existing population — UHC `hra`/`renewal`
rows that never linked a customer because the line-item→customer back-link only populates by MBI
and those rows have no MBI match. Those are NOT from AJ's edits and are out of scope here.)

## The fix

### A. Stop the bleed — copy `customer_id` onto the sibling (both creators)
In `edit_line_split` (`ledger.py:1150-1155`) and in `resolve_quarantine_line` (the analogous
sibling-creation block), add `customer_id=line.customer_id` to the `CommissionLineItem(...)`
constructor:

```python
ovr = existing_ovr or CommissionLineItem(
    agency_id=line.agency_id, statement_id=line.statement_id,
    carrier=line.carrier, period_label=line.period_label,
    statement_date=line.statement_date, source_ref=ovr_ref,
    member_name=line.member_name, mbi=line.mbi,
    carrier_member_id=line.carrier_member_id,
    customer_id=line.customer_id)          # ← the missing line
```

Also for the `existing_ovr` (update) path: if an override sibling already exists but has a NULL
`customer_id` while the parent now has one, set `ovr.customer_id = line.customer_id` on update
(self-heals a previously-orphaned sibling whenever its line is edited again). One assignment
alongside the other `ovr.*` fields.

This changes NO money/split math — `customer_id` is identity linkage only, never used in
`split_breakdown`. The override amount, classification, split_rate are untouched.

### B. One-time backfill of the existing 24 (Tim's choice)
A small idempotent script (`scripts/backfill_override_sibling_customer.py`) that, for every
`commission_line_items` row where `source_ref LIKE '%::ovr'` AND `customer_id IS NULL`, looks up
its parent (`source_ref` minus the trailing `::ovr`, same `statement_id`) and, **if the parent
has a `customer_id`, copies it onto the sibling**. Dry-run first, then `--apply`; DB backed up.

**Live reality (prod):** of the 24 orphaned siblings, **12 have a parent WITH a customer_id
(backfillable now)**; the other **12 have a parent that is ALSO customer-less** (no customer to
copy — those belong to the separate pre-existing no-MBI population, not the edit bug). So the
backfill drives `payment_without_customer` **down by 12**; the remaining 12 are pre-existing debt
that this fix does not own (they'd resolve only if their parent line gets a customer, e.g. via the
MBI back-link or a future identity fix). Report both counts honestly.

## Verify
- Unit test: editing a line whose parent has `customer_id=X` and creating an override sibling →
  the sibling has `customer_id=X` (not NULL). Same for `resolve_quarantine_line`.
- Unit test: editing a line that already has a NULL-customer override sibling, when the parent has
  a customer → the sibling's `customer_id` is repaired on the edit.
- The fix must NOT change the sibling's `raw_amount`, `classification` (`founders_override`),
  `split_rate` (None), or `agent_id` (None) — only `customer_id`.
- Real-Postgres: run the backfill dry-run (expect 12 fixable / 12 parent-also-null), `--apply`,
  confirm `payment_without_customer` drops by 12 and `statement_balance_complete` is unaffected
  (no dollars moved). Then ratchet the `payment_without_customer` baseline DOWN to the new floor
  (it can only improve from here).

## Files (expected; confirm at build)
- `app/commission/ledger.py` — add `customer_id=line.customer_id` to the override-sibling
  constructor in BOTH `edit_line_split` and `resolve_quarantine_line`; repair on the update path.
- `scripts/backfill_override_sibling_customer.py` — new one-time idempotent backfill (dry-run /
  --apply).
- Tests in `tests/test_commission_audit_undo.py` or the edit/quarantine test file.
- No migration. No change to commission math.
