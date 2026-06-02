---
phase: 05-plan-database-sob-enhancement-next
plan: "04"
subsystem: carriers
tags: [plan-database, sob, admin-form, details_json, benefits]
dependency_graph:
  requires: [05-01, 05-03]
  provides: [structured-admin-sob-form]
  affects: [app/carriers.py, app/templates/plan_form.html]
tech_stack:
  added: []
  patterns: [merge-not-overwrite details_json, HTML5 details/summary collapse]
key_files:
  created: []
  modified:
    - app/carriers.py
    - app/templates/plan_form.html
decisions:
  - "Collapsible sections use HTML5 details/summary — no JS dependency"
  - "Empty form values become null (not empty string) in details_json so plan_detail fallback works"
  - "Merge-not-overwrite pattern: CMS-synced keys not in BENEFIT_KEYS are preserved through admin saves"
  - "details={} for plan_new GET; _parse_details(plan.details_json) for plan_edit GET"
metrics:
  duration: "3 minutes"
  completed: "2026-06-02"
  tasks_completed: 2
  files_modified: 2
---

# Phase 05 Plan 04: Plan Form Structured SOB Sections + Serialization Summary

Structured admin form with 19 benefit field inputs organized into three collapsible sections replaces the raw `details_json` textarea. POST handlers merge form values into existing `details_json` (preserving CMS-synced fields) and write `sob_url`, `drug_tier4`, `drug_tier5` as explicit DB columns.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | BENEFIT_KEYS + _serialize_benefits + POST handler updates | a6b5f22 | app/carriers.py |
| 2 | plan_form.html structured sections + details= wiring | 7c44979 | app/templates/plan_form.html, app/carriers.py |

## Changes Made

### app/carriers.py

**BENEFIT_KEYS constant** (lines after _parse_details helper):
- 19 keys: inpatient_hospital, inpatient_hospital_note, outpatient_surgery, snf, ambulance, urgent_care_copay, dental_allowance, dental_note, vision_allowance, vision_note, otc_allowance, otc_note, healthy_food_card, transportation, gym, hearing, hearing_note, drug_deductible, drug_deductible_exempt_tiers

**_serialize_benefits helper** (added after BENEFIT_KEYS):
- Parses existing details_json into dict (or empty dict on null/error)
- Overlays BENEFIT_KEYS from form.get() with strip-or-None
- Keys NOT in BENEFIT_KEYS (e.g., pcp_copay from CMS sync) are preserved
- Returns json.dumps(merged_dict)
- Uses module-level `import json` from Plan 05-03 — no duplicate import

**plan_new() POST handler** (before db.session.add):
- plan.sob_url = stripped or None
- plan.drug_tier4 = stripped or None
- plan.drug_tier5 = stripped or None
- plan.details_json = _serialize_benefits(plan.details_json, request.form)

**plan_edit() POST handler** (before db.session.commit):
- Same four lines — merge-not-overwrite preserves CMS-synced data in existing details_json

**render_template wiring**:
- plan_new() GET: `details = {}` then `details=details` kwarg
- plan_edit() GET: `details = _parse_details(plan.details_json)` then `details=details` kwarg
- Total `details=details` count across carriers.py: 3 (plan_detail from 05-03 + plan_new + plan_edit)

### app/templates/plan_form.html

**sob_url input** — added in Section 1 Plan Identity after friendly_name field:
- type="url" for browser validation
- value="{{ plan.sob_url or '' }}"

**drug_tier4/5 inputs** — added in Section 3 Benefits snapshot after drug_tier3:
- Same form-row/form-input/form-label pattern as drug_tier1/2/3

**Raw details_json textarea** — REMOVED (was lines 237-242 in original)

**Three collapsible `<details>` sections** — added between Section 3 and Section 4:
1. Medical Benefits: inpatient_hospital/note, snf, outpatient_surgery, ambulance, urgent_care_copay (6 inputs)
2. Supplemental Benefits: dental/note, vision/note, hearing/note, otc/note, healthy_food_card, transportation, gym (12 inputs)
3. Prescriptions: drug_deductible, drug_deductible_exempt_tiers (2 inputs)

**CSS** (added to existing {% block styles %}):
- `details.form-card > summary` flex layout with chevron toggle
- `.benefit-row` 2-col grid, 12px gap
- `.form-label` utility class (same as .form-row label)

**All values use CSS vars** — no hardcoded hex, no var(--ink) for text.

## Verification Results

```
python3 -c "import ast; ast.parse(open('app/carriers.py').read())"  -> PASS
grep -c "^BENEFIT_KEYS = [" app/carriers.py                         -> 1
grep -c "def _serialize_benefits" app/carriers.py                   -> 1
grep -c "_serialize_benefits(plan.details_json, request.form)"      -> 2
grep -c "plan.sob_url" app/carriers.py                              -> 2
grep -c "plan.drug_tier4" app/carriers.py                           -> 2
grep -c "plan.drug_tier5" app/carriers.py                           -> 2
grep -c "details=details" app/carriers.py                           -> 3
All 19 BENEFIT_KEYS: name= inputs in template                       -> ALL OK
grep -c '<details class="form-card"' plan_form.html                 -> 3
grep -c "Medical Benefits|Supplemental Benefits|Prescriptions"      -> 6 (summary + h3)
grep -c '<textarea name="details_json"' plan_form.html              -> 0
grep -c "details.get(" plan_form.html                               -> 19
No hardcoded hex in plan_form.html                                  -> PASS
No var(--ink) in plan_form.html                                     -> PASS
_serialize_benefits body has no inner import json                   -> PASS
```

## Deviations from Plan

None — plan executed exactly as written. Plan 05-03 was confirmed to have already added `import json` and `_parse_details` to carriers.py, so no duplicate imports were introduced.

## Known Stubs

None — all 19 benefit field inputs are wired to the BENEFIT_KEYS serialization path and will read/write from details_json immediately upon use.

## Self-Check: PASSED

- `app/carriers.py` — modified, committed at a6b5f22 and 7c44979
- `app/templates/plan_form.html` — modified, committed at 7c44979
- Both commits exist in git log
