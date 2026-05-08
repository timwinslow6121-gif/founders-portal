---
phase: 04-compliance-reference
plan: 03
subsystem: ui
tags: [flask, jinja2, sqlalchemy, customer-dedup, mbi-merge]

# Dependency graph
requires:
  - phase: 04-compliance-reference
    provides: "04-01: Humana MBI cleanup + partial unique index on customers.mbi"
provides:
  - "GET /customers/duplicates — agent-facing MBI duplicate list with adjacent-pair Merge buttons"
  - "GET /customers/merge/<a_id>/<b_id> — side-by-side merge view (not admin-only)"
  - "POST /customers/merge/<a_id>/<b_id> — atomic merge: AOR collision handled, notes/contacts migrated, discarded deleted"
  - "get_duplicate_mbi_count() helper — used by context processor for nav badge"
  - "inject_duplicate_count context processor — duplicate_mbi_count available in all templates"
  - "Conditional Duplicates nav item in base.html with count badge"
  - "Conditional warning link in customers_list.html"
affects: [04-04, 04-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Context processor pattern for injecting per-request counts into all templates"
    - "AOR unique constraint collision guard: collect existing keys before bulk reassign, delete collisions first"
    - "Adjacent-pair iteration for N-way duplicate groups: range(len-1) yields [i, i+1] pairs"

key-files:
  created:
    - app/templates/customer_merge.html
  modified:
    - app/customers.py
    - app/templates/customer_duplicates.html
    - app/templates/base.html
    - app/templates/customers_list.html
    - app/__init__.py

key-decisions:
  - "Agent-facing (not admin-only): D-07 satisfied; agents see only their own duplicate groups"
  - "Side-by-side full-page merge view (not modal): modals too narrow for field comparison"
  - "Wholesale canonical selection via radio button: no per-field overrides (D-22 minimal friction)"
  - "AOR collision guard: existing_aor_keys set built before loop; collisions deleted not migrated"
  - "Context processor pattern chosen over view-level injection: nav badge visible on every page"
  - "customer_duplicates.html rewritten for MBI-based approach; old admin name+DOB+phone route retained for backward compat"

patterns-established:
  - "Context processor for cross-template counters: wrap in try/except, return empty dict if not authenticated"
  - "Adjacent-pair duplicate groups: render (rows[i], rows[i+1]) pairs so each Merge targets exactly 2 records"

requirements-completed: [D-07, D-08, D-09, D-10, D-22]

# Metrics
duration: 3min
completed: 2026-05-08
---

# Phase 4 Plan 3: Duplicate MBI Merge UI Summary

**Agent-facing MBI duplicate detection with side-by-side merge tool: atomic transaction migrates notes/contacts/AOR history, handles unique constraint collisions, and hard-deletes the discarded record**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-05-08T03:12:18Z
- **Completed:** 2026-05-08T03:15:14Z
- **Tasks:** 4 auto + 1 checkpoint (human-verify)
- **Files modified:** 6

## Accomplishments
- Three new agent-facing routes in `customers_bp`: duplicates list, merge view, execute merge
- Atomic merge transaction handles AOR (carrier, effective_date) unique constraint collisions
- Context processor injects `duplicate_mbi_count` into all templates for nav badge
- Conditional Duplicates nav entry and customers_list inline warning link

## Task Commits

1. **Task 1: Add duplicates detection + merge routes** - `c15c3cb` (feat)
2. **Task 2: Rewrite customer_duplicates.html** - `50e90ea` (feat)
3. **Task 3: Create customer_merge.html** - `ab52592` (feat)
4. **Task 4: Nav entry + context processor** - `7d744f0` (feat)

## Files Created/Modified
- `app/customers.py` — Added `get_duplicate_mbi_count()`, `duplicates_list`, `merge_view`, `execute_merge` routes; added `func` import from sqlalchemy, `abort` from flask
- `app/templates/customer_duplicates.html` — Rewritten for MBI-based groups with adjacent-pair Merge buttons
- `app/templates/customer_merge.html` — New: 2-column side-by-side merge form with radio canonical selection
- `app/templates/base.html` — Conditional Duplicates nav item with count badge (agent sidebar only)
- `app/templates/customers_list.html` — Conditional warning link above toolbar when duplicates exist
- `app/__init__.py` — `inject_duplicate_count` context processor registered

## Decisions Made
- Agent-facing (not admin-only): agents see only duplicate groups that include at least one of their own customers; admins see all
- Full-page side-by-side view (not modal): wider layout needed to compare all key fields
- Wholesale radio selection (no per-field overrides): D-22 minimal friction — pick canonical, click merge
- AOR collision handled by collecting existing canonical keys before the loop, then deleting collisions instead of migrating
- context processor wraps import in try/except to gracefully fail if DB is unreachable during template render

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed active-state clash for /customers nav item**
- **Found during:** Task 4
- **Issue:** Original `{% if '/customers' in request.path %}` would also highlight Customers when visiting /customers/duplicates or /customers/merge, making both items appear active
- **Fix:** Added `and 'duplicate' not in request.path and 'merge' not in request.path` to Customers nav condition
- **Files modified:** app/templates/base.html
- **Committed in:** 7d744f0

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Minor nav active-state precision fix. No scope creep.

## Issues Encountered
- Existing `customer_duplicates.html` served the old admin-only name+DOB+phone dedupe form. Plan required rewriting it for MBI-based approach. Old admin route (`/admin/customers/duplicates`) still exists and points to the same template — it will now render the MBI-based view, which is acceptable since the admin flow also benefits from MBI grouping.

## Known Stubs
None. All routes return real data from the database.

## User Setup Required
None — no external service configuration required. Deploy as normal: `git pull && flask db upgrade && systemctl restart founders-portal` (no new migrations in this plan).

## VPS Smoke Test (Task 5) — COMPLETE

- VPS deploy confirmed working (2026-05-07): git pull, flask db upgrade (no migrations), systemctl restart — all succeeded
- User confirmed: merge tested and working end-to-end
- /customers/duplicates, /customers/merge/<a_id>/<b_id>, POST merge — all routes live and verified
- Portal running clean; agents can immediately start cleaning duplicate customer records
- Duplicate count > 0 will surface the nav entry automatically once real duplicates exist

## Next Phase Readiness
- Plan 04-03 fully verified and complete
- Proceed to 04-04

---
*Phase: 04-compliance-reference*
*Completed: 2026-05-08*
