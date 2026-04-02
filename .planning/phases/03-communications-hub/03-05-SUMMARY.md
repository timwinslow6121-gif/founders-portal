---
phase: 03-communications-hub
plan: "05"
subsystem: sms
tags: [twilio, sms, templates, tcpa, consent, flask, jinja2]

requires:
  - phase: 03-01
    provides: SmsTemplate model with pending/approved/rejected status; Customer.sms_consent_at column; CustomerNote.twilio_msg_sid column
  - phase: 03-02
    provides: comms_bp blueprint; normalize_e164 utility

provides:
  - SMS template admin page at /comms/sms-templates (agent suggest, admin approve/reject)
  - send_sms_template() function with no_consent/template_not_approved guards
  - POST /comms/sms/send route with flash error handling
  - sms_consent_at toggle button on customer profile
  - SMS send modal on customer profile (approved templates only)
  - SMS Templates nav link in admin and agent sidebars

affects:
  - 03-07 (agency_id scoping sweep — Customer.agency_id not yet available; agent fallback used in send_sms_template)
  - 03-06 (blast — reuses send_sms_template function and SmsTemplate.status='approved' pattern)

tech-stack:
  added: [twilio (Client import in sms.py)]
  patterns:
    - "_admin_required decorator defined locally per blueprint (same pattern as customers.py)"
    - "TDD RED-GREEN — tests written before implementation, then implementation to pass"
    - "Template send consent guard: ValueError raise, caught in route, flash+redirect"

key-files:
  created:
    - app/comms/templates_admin.py
    - app/comms/sms.py
    - app/templates/comms/sms_templates_admin.html
    - app/templates/comms/sms_send_modal.html
  modified:
    - app/templates/customer_profile.html
    - app/customers.py
    - app/comms/__init__.py
    - app/templates/base.html
    - tests/test_comms_sms.py

key-decisions:
  - "CustomerNote has no agency_id column — removed agency_id kwarg from note creation; plan 07 sweep will add if needed"
  - "SMS consent toggle implemented as separate POST route (customer_toggle_sms_consent) — cleaner than checkbox in existing edit form"
  - "send_sms_template raises ValueError not HTTP error — keeps business logic testable without Flask request context"
  - "Sidebar nav added for SMS Templates in both admin and agent sections — otherwise page would be unreachable"

patterns-established:
  - "Consent guard pattern: check sms_consent_at before Twilio call; raise ValueError('no_consent'); route catches and flashes"
  - "Template status workflow: pending (default) -> approved | rejected; only approved usable by agents"

requirements-completed:
  - SC-5

duration: 4min
completed: 2026-04-02
---

# Phase 3 Plan 05: SMS Template Approval Workflow and Customer Profile Send Summary

**CMS-compliant SMS send via Twilio using admin-approved templates, consent-gated at the customer level with full TCPA workflow (suggest, review, approve/reject)**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-02T19:32:36Z
- **Completed:** 2026-04-02T19:37:05Z
- **Tasks:** 2 (+ checkpoint)
- **Files modified:** 9

## Accomplishments

- Admin template management page at /comms/sms-templates with approve/reject buttons and agent suggest form; status badges (amber=pending, green=approved, gray=rejected)
- `send_sms_template()` function in app/comms/sms.py with two guards: `ValueError("no_consent")` if sms_consent_at is None, `ValueError("template_not_approved")` if status != approved; creates CustomerNote on success
- Customer profile gains SMS Consent status display, enable/revoke toggle button, and Send SMS modal showing approved templates with body preview

## Task Commits

1. **RED: Failing tests** - `6afda9a` (test)
2. **Task 1: SMS template admin routes + HTML** - `7cde7b1` (feat)
3. **Task 2: SMS send function + profile integration** - `fb9bee3` (feat)
4. **Sidebar nav update** - `76b4160` (feat)

## Files Created/Modified

- `app/comms/templates_admin.py` — 4 routes: GET list, POST create/approve/reject; local _admin_required decorator
- `app/comms/sms.py` — send_sms_template() with consent/approval guards; POST /comms/sms/send route
- `app/templates/comms/sms_templates_admin.html` — template table with status badges + suggest form
- `app/templates/comms/sms_send_modal.html` — send form with consent warning, template dropdown, body preview
- `app/templates/customer_profile.html` — SMS consent display, toggle button, send modal include
- `app/customers.py` — approved_templates query in profile route; customer_toggle_sms_consent route
- `app/comms/__init__.py` — added templates_admin and sms imports
- `app/templates/base.html` — SMS Templates nav item in admin and agent sidebars
- `tests/test_comms_sms.py` — 4 tests replacing stubs; all passing

## Decisions Made

- CustomerNote has no agency_id column — removed from note creation (plan 07 sweep will handle if needed)
- SMS consent toggle is a separate POST route rather than a checkbox in the general edit form — cleaner and more explicit for TCPA compliance auditing
- `send_sms_template()` raises ValueError rather than returning HTTP errors — keeps function testable independently of Flask request context
- Added sidebar SMS Templates nav link (not in original plan) — discovered page would be unreachable without it; auto-fixed per Rule 3 (blocking for usability)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added SMS Templates sidebar navigation link**
- **Found during:** Task 2 (profile integration)
- **Issue:** /comms/sms-templates had no navigation entry — page would be unreachable in production
- **Fix:** Added SMS Templates nav item (gold dot) to both admin Tools section and agent Tools section in base.html
- **Files modified:** app/templates/base.html
- **Verification:** Full test suite (21 passed, 2 skipped) still passes
- **Committed in:** 76b4160 (separate commit after task 2)

**2. [Rule 1 - Bug] Removed agency_id from CustomerNote creation**
- **Found during:** Task 2 (writing sms.py)
- **Issue:** Plan spec included `agency_id` kwarg on CustomerNote, but CustomerNote model has no agency_id column — would raise SQLAlchemy error at runtime
- **Fix:** Removed agency_id from CustomerNote constructor call; noted in comment that plan 07 sweep addresses if needed
- **Files modified:** app/comms/sms.py
- **Verification:** test_sms_send_creates_customer_note passes with note created successfully
- **Committed in:** fb9bee3 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 missing critical nav, 1 model mismatch bug)
**Impact on plan:** Both necessary for correctness. No scope creep.

## Issues Encountered

None — plan executed cleanly.

## User Setup Required

None — no new external service configuration required beyond what Plan 01 documented. Twilio credentials (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER) must be in .env before the send route will successfully deliver messages; verified by trying to send and checking flash error vs. Twilio dashboard.

## Next Phase Readiness

- SC-5 requirement satisfied: template approval workflow complete, consent guard active, CustomerNote created on send
- Task 3 checkpoint awaits human verification of the UI flow on the VPS
- Plan 06 (SMS blast) can reuse send_sms_template() directly — the function signature and consent guard are the right interface
- Plan 07 agency_id sweep will add Customer.agency_id; send_sms_template already has a fallback comment noting this

---
*Phase: 03-communications-hub*
*Completed: 2026-04-02*

## Self-Check: PASSED

- app/comms/templates_admin.py: FOUND
- app/comms/sms.py: FOUND
- app/templates/comms/sms_templates_admin.html: FOUND
- app/templates/comms/sms_send_modal.html: FOUND
- 03-05-SUMMARY.md: FOUND
- Commits 6afda9a, 7cde7b1, fb9bee3, 76b4160: all FOUND
