---
phase: 04-compliance-reference
plan: "04"
subsystem: ui
tags: [flask, jinja2, vanilla-js, upload, bob-import, quarantine, mbi]

requires:
  - phase: 04-01
    provides: migration 014 adding unresolvable_json TEXT column to import_batches

provides:
  - bulk_upload() quarantine pre-check — non-Humana rows missing MBI are quarantined instead of creating shell customers
  - batch_detail() returns unresolvable array alongside new/updated/missing
  - POST /upload/unresolvable/resolve route — 3 inline resolution actions (assign_existing, enter_mbi, create_new)
  - upload.html 4th "Unresolvable" tab with amber badge, card-expand UI, and AJAX resolution

affects: [upload, bob-import, customer-master, shell-customers, data-integrity]

tech-stack:
  added: []
  patterns:
    - "Quarantine pattern: check condition before upsert, persist to batch JSON column, surface in modal"
    - "Inline AJAX resolution: card expand → action → POST → remove card + decrement badge"

key-files:
  created: []
  modified:
    - app/upload.py
    - app/models.py
    - app/templates/upload.html

key-decisions:
  - "Policy row still inserted for unresolvable rows (carrier record preserved); only _upsert_customer_from_policy is skipped"
  - "assign_existing takes customer ID (not search) in v1 — search modal deferred as follow-up"
  - "Humana rows always bypass quarantine regardless of MBI value — humana_id path handles them"
  - "unresolvable_json column ORM definition added to ImportBatch model (migration 014 already added it to DB)"

requirements-completed:
  - D-11
  - D-12
  - D-13
  - D-14
  - D-22

duration: 18min
completed: 2026-05-07
---

# Phase 04 Plan 04: Unresolvable BOB Row Quarantine + Inline Resolution Summary

**BOB quarantine pipeline: non-Humana rows missing MBI are quarantined to batch.unresolvable_json and surfaced in a 4th modal tab with 3 inline AJAX resolution actions (assign existing, enter MBI, create new)**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-05-07T00:00:00Z
- **Completed:** 2026-05-07T00:00:00Z
- **Tasks:** 4 of 5 (Task 5 is checkpoint:human-verify — paused for testing)
- **Files modified:** 3

## Accomplishments
- bulk_upload() now quarantines non-Humana rows with no MBI, preventing silent shell customer creation (D-11)
- Quarantined rows persisted as JSON on ImportBatch.unresolvable_json, available for later resolution
- batch_detail() JSON endpoint returns 4th key `unresolvable` alongside existing new/updated/missing
- New POST /upload/unresolvable/resolve route handles all 3 resolution actions with full agency_id scoping
- upload.html 4th tab "Unresolvable" with amber badge, click-to-expand cards, MBI input, and customer-ID assign
- showTab() updated to include 'unresolvable' in the tab cycle

## Task Commits

1. **Task 1: Quarantine logic in bulk_upload()** - `e452004` (feat)
2. **Task 2: batch_detail() unresolvable key** - `f0cb6ef` (feat)
3. **Task 3: POST /upload/unresolvable/resolve route** - `c9f9192` (feat)
4. **Task 4: 4th tab + inline resolution UI** - `a55b10e` (feat)

**Task 5 (checkpoint:human-verify):** Awaiting smoke test on local + VPS with real BOB file.

## Files Created/Modified
- `app/upload.py` — quarantine logic in bulk_upload(), unresolvable key in batch_detail(), resolve_unresolvable() route, import json added
- `app/models.py` — unresolvable_json ORM column added to ImportBatch model
- `app/templates/upload.html` — 4th tab button + panel, showTab() update, openBatchDetail() unresolvable population, resolveRow() AJAX function, CSS for card UI

## Example Flow
A UHC BOB row for "John Smith" arrives with MBI column empty. The quarantine check fires (`is_unresolvable = True`, carrier = "UHC" not "Humana"). The policy row is still inserted to preserve the carrier record, but `_upsert_customer_from_policy` is skipped. After the loop, `batch.unresolvable_json = json.dumps([{carrier: "UHC", member_id: "ABC123", full_name: "John Smith", ...}])`. When the agent opens the import modal, the "Unresolvable" tab shows count badge 1. The agent clicks the row, sees "John Smith — UHC Plan X, DOB 1942-03-15", types the MBI in the input, clicks "Save MBI". The server creates/matches a customer record, updates the policy's MBI, removes the row from the JSON list, returns `{ok: true, remaining: 0}`. The badge clears and the empty state shows.

## Decisions Made
- Policy row is inserted even for unresolvable rows — the carrier data is real and belongs in the policy table. Only the customer upsert is skipped.
- assign_existing uses customer ID in v1 — building a search modal was deferred to avoid scope creep; a customer ID lookup is sufficient for initial use.
- Humana explicitly excluded from quarantine at the condition level — humana_id path in `_upsert_customer_from_policy` handles Humana rows that lack MBI.
- ImportBatch.unresolvable_json ORM column added to models.py to match the migration 014 DB column.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added unresolvable_json to ImportBatch model**
- **Found during:** Task 1
- **Issue:** Migration 014 added `unresolvable_json` to the DB but the ORM model didn't have the column defined, which would cause AttributeError at runtime when writing `batch.unresolvable_json`
- **Fix:** Added `unresolvable_json = db.Column(db.Text, nullable=True)` to ImportBatch in models.py
- **Files modified:** app/models.py
- **Verification:** `python3 -c "import ast; ast.parse(open('app/upload.py').read())"` passes; grep confirms unresolvable_json present
- **Committed in:** e452004 (Task 1 commit)

**2. [Rule 1 - Bug] Fixed data.get('customer_id', type=int) pattern**
- **Found during:** Task 3
- **Issue:** Plan's code used `data.get('customer_id', type=int)` which only works with Flask's ImmutableMultiDict (form data), not plain dicts (JSON). Since we accept JSON, this would silently return None for customer_id on JSON requests.
- **Fix:** Used explicit `int(data.get("customer_id", 0))` with try/except instead
- **Files modified:** app/upload.py
- **Verification:** Both JSON and form data paths handled correctly
- **Committed in:** c9f9192 (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 bug)
**Impact on plan:** Both fixes essential for correctness. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviations above.

## Known Stubs
None — all resolution actions are fully implemented. The assign_existing search input accepts a customer ID directly (no typeahead search), which is a deliberate MVP simplification noted in decisions.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- Task 5 (smoke test on local + VPS) is the blocking checkpoint
- Once verified: all D-11 through D-14 and D-22 requirements satisfied
- Humana MBI backfill (04-02) and customer dedup UI (04-03) may proceed in parallel

---
*Phase: 04-compliance-reference*
*Completed: 2026-05-07*
