---
phase: 03-communications-hub
plan: "04"
subsystem: communications
tags: [calendly, webhooks, flask, jinja2, unmatched-calls, resolution-queue]

# Dependency graph
requires:
  - phase: 03-communications-hub plan 01
    provides: Phase 3 schema (CustomerNote, UnmatchedCall, comms migrations)
  - phase: 03-communications-hub plan 02
    provides: comms_bp blueprint, verify_calendly_webhook util, UnmatchedCall model
  - phase: 03-communications-hub plan 03
    provides: Quo webhook handler pattern, unmatched_call_count context processor

provides:
  - "POST /comms/webhook/calendly: invitee.created → CustomerNote(appointment_scheduled) or UnmatchedCall"
  - "GET /comms/resolution: agent-scoped unmatched call resolution queue"
  - "POST /comms/resolution/<id>/link: link unmatched call to customer, create note, mark resolved"
  - "Upcoming Appointments card on agent dashboard (partial template)"
  - "Sidebar badge: unmatched_call_count in agent + admin nav"

affects:
  - 03-05
  - 03-06
  - agent-dashboard

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "verify_calendly_webhook imported at module level so tests can patch app.comms.webhooks.verify_calendly_webhook"
    - "_agency_id() helper in resolution.py guards against missing User.agency_id until Plan 07"
    - "Calendly event ID extracted as last path segment of invitee URI"
    - "Appointment time stored in note_text as 'Appointment: {start_time}' — proper datetime column deferred to later plan"

key-files:
  created:
    - app/comms/resolution.py
    - app/templates/comms/unmatched_calls.html
    - app/templates/comms/partials/upcoming_appointments.html
  modified:
    - app/comms/webhooks.py
    - app/comms/__init__.py
    - app/routes.py
    - app/templates/base.html
    - app/templates/dashboard.html
    - tests/test_comms_webhooks.py

key-decisions:
  - "verify_calendly_webhook imported at module level in webhooks.py (not accessed via app.comms.utils) so test patches target app.comms.webhooks.verify_calendly_webhook — consistent with Quo webhook pattern from Plan 03"
  - "_agency_id() helper defers Customer.agency_id FK scoping to Plan 07 — guards gracefully with DEFAULT_AGENCY_ID fallback"
  - "Upcoming appointments card excluded from admin agent-detail view (viewing_agent check) — admin sees team-wide data, per-agent appointments visible only on that agent's own dashboard"
  - "CustomerNote link in unmatched_calls.html requires agent to look up customer ID from profile — full inline search deferred to future plan (SC-6 enhancement)"

patterns-established:
  - "resolution.py: all multi-tenant queries guarded by _agency_id() helper until User.agency_id column exists (Plan 07)"
  - "TDD: Calendly tests use copy.deepcopy(PAYLOAD) for mutation safety in unmatched test variant"

requirements-completed: [SC-3, SC-6]

# Metrics
duration: 6min
completed: 2026-04-02
---

# Phase 03 Plan 04: Communications Hub — Calendly + Resolution Queue Summary

**Calendly invitee.created webhook with phone/email customer matching, UnmatchedCall resolution queue UI, and Upcoming Appointments pre-call brief card on agent dashboard**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-04-02T19:37:00Z
- **Completed:** 2026-04-02T19:37:25Z
- **Tasks:** 2 of 2 auto tasks complete (checkpoint:human-verify pending)
- **Files modified:** 8

## Accomplishments

- Calendly `invitee.created` webhook handler: phone-first customer matching via `questions_and_answers`, email fallback, agent resolution by email, idempotency on `calendly_event_id`
- UnmatchedCall resolution queue at GET /comms/resolution — agent-scoped, admin sees all, data-table with inline link-to-customer form
- Upcoming Appointments card partial included in agent dashboard — `<details>`/`<summary>` pre-call brief shows last note and open tasks
- Sidebar badge injected for both agent and admin nav sections
- All 10 comms webhook tests pass; full suite 21 passed

## Task Commits

1. **Task 1 (TDD RED): Failing Calendly tests** — `c95b27d` (test)
2. **Task 1 (TDD GREEN): Calendly webhook handler** — `6de3a26` (feat)
3. **Task 2: Resolution queue + dashboard card** — `37f3bb0` (feat)

## Files Created/Modified

- `app/comms/webhooks.py` — Added `POST /comms/webhook/calendly`, `verify_calendly_webhook` import, `_extract_phone_from_qna()`, `_extract_calendly_event_id()` helpers
- `app/comms/resolution.py` — Resolution queue (GET) and link action (POST); `_agency_id()` helper for pre-Plan-07 safety
- `app/comms/__init__.py` — Added `from app.comms import resolution` import
- `app/templates/comms/unmatched_calls.html` — Resolution queue page with data-table and inline link form
- `app/templates/comms/partials/upcoming_appointments.html` — Appointments card for dashboard
- `app/routes.py` — Added `CustomerNote` import; `_build_dashboard_context` returns `upcoming_appointments`
- `app/templates/base.html` — Agent + admin sidebar: Unmatched Calls nav item with gold badge
- `app/templates/dashboard.html` — Includes upcoming appointments partial (agent view only)
- `tests/test_comms_webhooks.py` — Replaced Calendly stubs with real tests

## Decisions Made

- `verify_calendly_webhook` imported at module level in `webhooks.py` so tests can patch `app.comms.webhooks.verify_calendly_webhook` (mirrors Quo webhook pattern from Plan 03).
- `_agency_id()` helper in `resolution.py` falls back to `DEFAULT_AGENCY_ID` config when `User.agency_id` is absent — defers Plan 07 migration.
- Upcoming appointments card hidden on admin "viewing agent" view — admin agent-detail pages focus on policy/commission data.
- Inline customer ID entry (not search) for resolution queue link form — full inline search is deferred.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added `_agency_id()` helper for missing `User.agency_id` attribute**
- **Found during:** Task 2 (resolution.py)
- **Issue:** Plan code referenced `current_user.agency_id` directly; `User` model has no `agency_id` column until Plan 07 — would raise `AttributeError` at runtime.
- **Fix:** Extracted `_agency_id()` helper using `getattr(current_user, 'agency_id', None)` with `DEFAULT_AGENCY_ID` config fallback, consistent with STATE.md decision for this phase.
- **Files modified:** `app/comms/resolution.py`
- **Verification:** App starts without error; routes registered correctly.
- **Committed in:** `37f3bb0` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (missing critical — prevented AttributeError)
**Impact on plan:** Essential for runtime correctness before Plan 07 adds `agency_id` to User model. No scope creep.

## Issues Encountered

None beyond the auto-fixed `User.agency_id` issue above.

## Next Phase Readiness

- Calendly webhook is complete and tested; pending human verification of UI rendering.
- Resolution queue and sidebar badge ready for production deployment.
- Upcoming Appointments partial visible on agent dashboard — will populate once Calendly bookings flow in.
- Plan 05 (Retell AI / Twilio SIP) and Plan 06 (HealthSherpa / Google Meet) can proceed after human-verify checkpoint passes.

---
*Phase: 03-communications-hub*
*Completed: 2026-04-02*
