---
phase: 05-plan-database-sob-enhancement-next
plan: "03"
subsystem: carriers
tags: [plan-database, sob, templates, ui]
dependency_graph:
  requires: ["05-01"]
  provides: ["plan_detail SOB cards", "plan_list benefit columns"]
  affects: ["app/carriers.py", "app/templates/plan_detail.html", "app/templates/plan_list.html"]
tech_stack:
  added: []
  patterns: ["json.loads in route layer (not template)", "GROUP BY pre-compute to avoid N+1"]
key_files:
  created: []
  modified:
    - app/carriers.py
    - app/templates/plan_detail.html
    - app/templates/plan_list.html
decisions:
  - "D-07 confirmed: plan_list columns are MOOP, PCP, Dental, OTC, Stars, Members (specialist_copay intentionally excluded)"
  - "SOB benefit data pre-parsed at route level (_parse_details helper) — no JSON parsing in Jinja templates"
  - "Member counts pre-computed via single GROUP BY query — no N+1 in plan_list"
metrics:
  duration: "3 minutes"
  completed: "2026-06-02"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 3
requirements: [SOB-01, SOB-02, SOB-03, SOB-04, SOB-05]
---

# Phase 05 Plan 03: Plan Detail SOB Cards + Plan List Benefit Columns Summary

**One-liner:** Plan detail page now shows three stacked SOB cards (Medical, Supplemental, Prescriptions) plus a gold "View SOB PDF" button; plan list replaces commission columns with six benefit-focused columns (MOOP, PCP, Dental, OTC, Stars, Members) backed by pre-computed member counts.

## What Was Built

### Task 1 — app/carriers.py route updates (commit 32012df)

**Lines modified:** imports block (added `import json`), new helper after `PLAN_LETTERS` constant (~line 56), `plan_list()` body (~lines 89-113), `plan_detail()` body (~lines 160-167).

- Added `_parse_details(details_json_str)` helper: safe `json.loads` with `{}` fallback on null/error
- `plan_list()`: pre-computes `member_counts` via single `GROUP BY Policy.plan_id` query (multi-tenant scoped to `current_user.agency_id`), pre-parses `details_map = {p.id: _parse_details(p.details_json) for p in plans}`
- `plan_detail()`: adds `details = _parse_details(plan.details_json)` before render_template, passes `details=details` kwarg
- All existing kwargs preserved in both render_template calls

### Task 2 — app/templates/plan_detail.html (commit edfc9e9)

**Lines modified:**
- Header section (~line 74): added `{% if plan.sob_url %}` conditional gold-accent "View SOB PDF" button (uses `var(--gold)`, `var(--bg)`, `var(--radius)`, `target="_blank" rel="noopener"`)
- ~Lines 186-192: **removed** entire `{% if plan.details_json %}` block with raw `<pre>{{ plan.details_json }}</pre>` dump
- After detail-grid closing `</div>`: inserted three new stacked `.detail-card` blocks:
  - **Medical Benefits** (8 rows): Inpatient Hospital, SNF, Outpatient Surgery, Ambulance, PCP Copay, Specialist Copay, ER Copay, Urgent Care
  - **Supplemental Benefits** (7 rows): Dental Allowance, Vision Allowance, Hearing, OTC Allowance, Healthy Food Card, Transportation, Gym/Fitness
  - **Prescriptions** (7 rows): Drug Deductible, Deductible Exempt Tiers, Tiers 1-5

All 24 `details.get()` calls have `or '—'` fallback. Note fields render as `<span style="font-size:11px;color:var(--slate)">` inline next to the value. All text color uses `var(--ivory)` or `var(--slate)`.

### Task 3 — app/templates/plan_list.html (commit 623b12e)

**Lines modified:**
- `<thead>` row (~lines 149-154): replaced 3 commission `<th>` elements (Initial, Renewal, HRA) with 6 benefit `<th>` elements (MOOP, PCP, Dental, OTC, Stars, Members) with proportional widths
- Carrier group header row (~line 164): updated `colspan` from `11/10` to `14/13` (+3 net columns)
- Per-plan `<td>` block: replaced 3 commission cells with 6 benefit cells:
  ```
  p.annual_oopm or '—'
  p.pcp_copay or '—'
  details_map.get(p.id, {}).get('dental_allowance') or '—'
  details_map.get(p.id, {}).get('otc_allowance') or '—'
  p.star_rating or '—'
  member_counts.get(p.id, 0)   ← 0 not em-dash (count is meaningful)
  ```

## Verification Results

All automated checks passed:

| Check | Result |
|---|---|
| `carriers.py` AST parse | PASS |
| `_parse_details` defined | FOUND |
| `member_counts` in plan_list | FOUND (3+ occurrences) |
| `details_map` in plan_list | FOUND (2+ occurrences) |
| `func.count(Policy.id)` | FOUND |
| `Policy.agency_id == current_user.agency_id` | FOUND |
| `details=details` kwarg in plan_detail | FOUND |
| Medical Benefits card | 2 occurrences (h3 + section) |
| Supplemental Benefits card | 2 occurrences |
| Prescriptions card | 2 occurrences |
| View SOB PDF button | 1 occurrence |
| `{% if plan.sob_url %}` | 1 occurrence |
| Raw `<pre>{{ plan.details_json }}` | NONE (removed) |
| `details.get(` count | 24 (≥15 required) |
| `plan.drug_tier4` | 1 |
| `plan.drug_tier5` | 1 |
| `or '—'` em-dash fallbacks in plan_detail | 31 (≥15 required) |
| `color: var(--ink)` for text | NONE |
| New hardcoded hex colors added | NONE |
| MOOP/PCP/Dental/OTC/Stars/Members headers | FOUND |
| Initial/Renewal/HRA headers | NONE (removed) |
| Specialist column | NONE (D-07) |
| `member_counts.get(p.id` | FOUND |
| `details_map.get(p.id` | 2 occurrences (dental + OTC) |
| `p.annual_oopm` | FOUND |
| `p.pcp_copay` | FOUND |
| `p.star_rating` | FOUND |
| colspan updated | 14/13 |
| Commission data cells removed | NONE |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

**Dental and OTC columns on plan_list will show em-dash (—) on fresh deploy** until `scripts/sync_pbp_extended_benefits.py` (Plan 05-02) runs on the VPS to populate `details_json` with `dental_allowance` and `otc_allowance` values. This is expected behavior per plan spec — the rendering layer is correct; the data population is a separate VPS execution step. SOB-05 is satisfied end-to-end only after Plan 05-02 runs on VPS.

## D-07 vs ROADMAP Reconciliation

The ROADMAP "Plan list view enhancements" bullet mentioned "PCP/specialist copay" as desired columns. Locked decision **D-07 supersedes**: the final 6 columns are MOOP, PCP, Dental, OTC, Stars, Members. `specialist_copay` is NOT on the plan list. It remains visible on the plan_detail page inside the Medical Benefits SOB card. This is intentional — the 6-column layout prioritizes member-benefit summary over agent-internal copay comparison.

## Self-Check: PASSED

Files verified:
- FOUND: app/carriers.py
- FOUND: app/templates/plan_detail.html
- FOUND: app/templates/plan_list.html
- FOUND: .planning/phases/05-plan-database-sob-enhancement-next/05-03-SUMMARY.md

Commits verified:
- 32012df feat(05-03): add _parse_details helper, member_counts, details_map to carriers.py routes
- edfc9e9 feat(05-03): plan_detail SOB cards + SOB PDF button, remove raw JSON dump
- 623b12e feat(05-03): plan_list benefit columns (MOOP, PCP, Dental, OTC, Stars, Members)
