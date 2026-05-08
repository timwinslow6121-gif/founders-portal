---
phase: "04-compliance-reference"
plan: "05"
subsystem: "commission/reconciliation"
tags: ["reconciliation", "payment-ledger", "customer-profile", "commission"]
dependency_graph:
  requires: ["04-01"]
  provides: ["BOB-commission reconciliation routes", "per-customer payment history"]
  affects: ["app/commission/routes.py", "app/templates/customer_profile.html", "app/templates/base.html"]
tech_stack:
  added: ["python-dateutil>=2.8 (explicit, was transitive)"]
  patterns: ["LEFT ANTI-JOIN via subquery on PolicyPayment.policy_id", "agency-scoped period-bounded reconciliation"]
key_files:
  created:
    - "app/templates/commission_reconciliation.html"
  modified:
    - "app/commission/routes.py"
    - "app/customers.py"
    - "app/templates/customer_profile.html"
    - "app/templates/base.html"
    - "requirements.txt"
decisions:
  - "dateutil.relativedelta used for period boundary arithmetic (was transitive dep of pandas; made explicit in requirements.txt)"
  - "Payment History uses policy_id IN subquery — Humana null-MBI policies with only fuzzy name match will not appear (acceptable v1; documented)"
  - "Reconciliation route only queries CommissionStatement periods that exist for that agent — no false positives against missing uploads (D-17)"
metrics:
  duration: "~15 minutes"
  completed: "2026-05-07"
  tasks_completed: 5
  tasks_total: 5
  files_modified: 5
---

# Phase 04 Plan 05: BOB ↔ Commission Reconciliation + Customer Payment History Summary

Standalone reconciliation page in the Commissions nav plus a per-customer Payment History collapsible section on the customer profile.

## What Was Built

**Two new routes in `app/commission/routes.py`:**
- `GET /commissions/reconciliation` — agent view; scoped to current_user
- `GET /admin/commissions/reconciliation` — admin view with agent selector dropdown

**Helper functions:**
- `_period_bounds(period_label)` — converts "March 2026" to `(date(2026,3,1), date(2026,3,31))`
- `_reconcile(agency_id, agent_id, carrier, period_label)` — runs both gap queries; returns `{unpaid_policies, unmatched_payments}`

**New template `app/templates/commission_reconciliation.html`:**
- Filter bar: carrier + period dropdowns populated only from existing CommissionStatement rows (D-17)
- Agent selector for admin view
- Summary cards: "In BOB, not paid" count + "Paid, not in BOB" count
- "In BOB, not paid" table: member name, MBI, plan, effective, term
- "Paid, not in BOB" table: member name from statement, carrier ID, amount, action
- Humana disclaimer note when carrier=Humana
- Empty states for both no-selection and zero-gap scenarios

**`app/customers.py` — customer_profile route:**
- Loads `PolicyPayment` records where `policy_id IN (customer policy ids)`, scoped by `agency_id`
- Ordered by `statement_date desc`
- Passes `payments=payments` to template

**`app/templates/customer_profile.html`:**
- New collapsible Payment History card (click h2 to toggle)
- Table: period, carrier, action, amount, confidence dot
- Dot colors: green=exact MBI/carrier ID, amber=fuzzy name, red=unmatched
- Chargeback rows styled in `var(--status-error-text)` via `.row-chargeback`
- CSS uses only CSS vars — no hardcoded hex

**`app/templates/base.html`:**
- "Reconciliation" nav link added after "Payment Ledger" in both admin and agent Commissions sections

## Reconciliation Logic

**"In BOB, not paid" (D-15, D-18, D-19):**
```
paid_policy_ids = PolicyPayment WHERE agency/agent/carrier/period AND policy_id IS NOT NULL
unpaid = Policy WHERE agency/agent/carrier/status='active'
             AND effective_date <= period_end        # D-18: excludes future-dated
             AND (term_date IS NULL OR term_date > period_start)  # D-19: post-death gaps surface
             AND id NOT IN paid_policy_ids
```

**"Paid, not in BOB" (D-15):**
```
PolicyPayment WHERE match_confidence='unmatched' AND agency/agent/carrier/period
```

## Decisions Made

1. `dateutil.relativedelta` used for period end-date arithmetic. Was already a transitive dep of pandas; made explicit in `requirements.txt` per plan instruction.
2. Payment History on customer profile uses `policy_id IN (...)` — Humana policies matched only by fuzzy name will have `policy_id=NULL` in PolicyPayment and will NOT appear. This is acceptable v1 behavior; a future iteration could also query by `member_name_normalized`.
3. Period dropdown is populated exclusively from existing `CommissionStatement` rows — no false positives against periods with no uploaded statement (D-17 satisfied).

## Deviations from Plan

None — plan executed exactly as written. All CSS uses vars. No hardcoded hex. Both admin and agent nav entries added as specified.

## Checkpoint: COMPLETE

Task 5 (VPS smoke test) passed — deploy confirmed working 2026-05-07. Routes `/commissions/reconciliation` and `/admin/commissions/reconciliation` verified live on VPS.

## Self-Check: PASSED
