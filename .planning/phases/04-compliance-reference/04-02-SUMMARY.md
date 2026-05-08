---
phase: 04-compliance-reference
plan: 02
subsystem: database
tags: [postgres, data-cleanup, one-time-script, shell-customers]

# Dependency graph
requires:
  - phase: 04-01
    provides: Humana MBI NULL migration + partial unique index on customers.mbi
provides:
  - scripts/delete_shell_customers.py — hard-delete script for shell customers with no MBI/humana_id
affects:
  - 04-03 (duplicate MBI detection will not be polluted by null-MBI ghosts after this runs)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One-time deletion script pattern: dry-run default, --execute flag to apply, per-row dependent check before delete"

key-files:
  created:
    - scripts/delete_shell_customers.py
  modified: []

key-decisions:
  - "Policy table excluded from dependent checks — Policy has no customer_id FK; joins by MBI, and shells have mbi=NULL so no linked policies exist"
  - "No agency scoping on delete query — customer_id is globally unique; dependent checks are agency-agnostic by design"
  - "Hard delete (not soft delete) per D-05 — data is in build phase, no real agent notes on shells"

patterns-established:
  - "Shell deletion pattern: query mbi IS NULL AND humana_id IS NULL, per-row dependent check (notes/contacts/aor_history), SKIP any with dependents, DEL the rest"

requirements-completed: [D-05, D-06, D-21]

# Metrics
duration: 2min (Task 1 script creation; Task 2 VPS execution pending human verify)
completed: 2026-05-07
---

# Phase 04 Plan 02: Shell Customer Deletion Summary

**One-time hard-delete script for ~29 shell customers (mbi=NULL, humana_id=NULL, no dependents) — dry-run default, --execute flag required to apply**

## Performance

- **Duration:** ~2 min (Task 1 only — Task 2 is human-verified VPS execution)
- **Started:** 2026-05-07T00:25:37Z
- **Completed:** 2026-05-07 (Task 1); Task 2 pending VPS execution
- **Tasks:** 1 of 2 complete (Task 2 is checkpoint:human-verify)
- **Files modified:** 1

## Accomplishments
- Created `scripts/delete_shell_customers.py` with dry-run default and `--execute` flag
- Per-row dependent check guards against deleting any customer with notes, contacts, or AOR history
- Policy table correctly excluded from dependent checks (no customer_id FK — joins by MBI)
- Documents cross-agency scoping rationale in script header

## Task Commits

1. **Task 1: Create shell customer deletion script** - `caf8a0a` (feat)
2. **Task 2: VPS deploy + run** — PENDING (checkpoint:human-verify)

## Files Created/Modified
- `scripts/delete_shell_customers.py` — one-time hard-delete script with dry-run default and --execute flag

## Decisions Made
- Policy table excluded from dependent checks per RESEARCH.md Pitfall 2 — Policy has no customer_id FK
- Script deletes across all agencies (no agency filter needed) because shells with mbi=NULL have no cross-tenant data risk and customer_id FK is globally unique
- DRY-RUN is the default mode; human must explicitly pass --execute after reviewing dry-run output

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required

**VPS execution required.** After pushing this commit:

1. Pull on VPS: `ssh -i ~/.ssh/id_ed25519 root@23.187.248.100 && cd /var/www/founders-portal && git pull`
2. Dry-run: `./venv/bin/python3 scripts/delete_shell_customers.py`
3. Review output — expect ~29 candidates, breakdown of deletable vs skipped
4. Execute: `./venv/bin/python3 scripts/delete_shell_customers.py --execute`
5. Verify: `psql -U founders_user -d founders_portal -c "SELECT COUNT(*) FROM customers WHERE mbi IS NULL AND humana_id IS NULL;"`

## Next Phase Readiness
- After VPS execution, `mbi IS NULL AND humana_id IS NULL` customers will be reduced to only those with dependents
- Plan 04-03 duplicate MBI detection will not be polluted by null-MBI ghost records
- Customer count drop expected: ~535 - N_deleted ≈ lower (exact count after VPS run)

---
*Phase: 04-compliance-reference*
*Completed: 2026-05-07*
