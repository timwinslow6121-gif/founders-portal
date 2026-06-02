---
phase: 05-plan-database-sob-enhancement-next
plan: "01"
subsystem: plan-database
tags: [migration, orm, schema, sob]
dependency_graph:
  requires: [migration-017]
  provides: [migration-018, plan-sob-columns]
  affects: [plans-table, plan-model]
tech_stack:
  added: []
  patterns: [alembic-direct-alter-table, orm-column-nullable]
key_files:
  created:
    - migrations/versions/018_sob_fields.py
  modified:
    - app/models.py
decisions:
  - sob_url, drug_tier4, drug_tier5 all nullable — no defaults, no index, matches migration 018 schema
  - No batch_alter_table — PostgreSQL supports direct ALTER TABLE (SQLite no longer used in production)
  - Columns inserted after drug_tier3 in Plan class, before details_json, following existing alignment style
metrics:
  duration: "~2 minutes"
  completed: "2026-06-02T13:30:00Z"
  tasks_completed: 2
  files_changed: 2
---

# Phase 5 Plan 01: Migration 018 + Plan Model SOB Columns Summary

Migration 018 adds three columns (drug_tier4, drug_tier5, sob_url) to the plans table and exposes them as ORM attributes on the Plan model, enabling all downstream SOB enhancement work.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create Alembic migration 018 | a6ff584 | migrations/versions/018_sob_fields.py |
| 2 | Add columns to Plan ORM model | 0a190cc | app/models.py |

## Migration File

**Path:** `migrations/versions/018_sob_fields.py`
**Revision:** 018
**Revises:** 017 (plan_link — current head before this plan)

Columns added in upgrade():
- `sob_url` — String(512), nullable — direct link to CMS/carrier SOB PDF
- `drug_tier4` — String(32), nullable — tier 4 drug copay (e.g. "$100")
- `drug_tier5` — String(32), nullable — tier 5 (specialty) drug copay

All three dropped in downgrade() in reverse order.

## Model Changes

**File:** `app/models.py`
**Lines added:** after line 348 (drug_tier3), before details_json

```python
    drug_tier4      = db.Column(db.String(32))
    drug_tier5      = db.Column(db.String(32))
    sob_url         = db.Column(db.String(512))
```

## Verification Results

```
grep -E "drug_tier4|drug_tier5|sob_url" app/models.py | wc -l  → 3
grep -E "drug_tier4|drug_tier5|sob_url" migrations/versions/018_sob_fields.py | wc -l  → 7
python3 -c "import ast; ast.parse(open('app/models.py').read())"  → OK
python3 -c "import ast; ast.parse(open('migrations/versions/018_sob_fields.py').read())"  → OK
revision = '018' present, down_revision = '017' present
op.add_column count: 3, op.drop_column count: 3
```

## VPS Deploy Note

After `git pull` on VPS, run:
```bash
flask db upgrade
```
This applies migration 018 and adds the three columns to the live `plans` table. `psql \d plans` will then show `sob_url`, `drug_tier4`, `drug_tier5`.

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- [x] `migrations/versions/018_sob_fields.py` exists
- [x] `app/models.py` contains drug_tier4, drug_tier5, sob_url column definitions
- [x] Commits a6ff584 and 0a190cc exist in git log
- [x] No other files modified (plan is purely additive at schema/model layer)
