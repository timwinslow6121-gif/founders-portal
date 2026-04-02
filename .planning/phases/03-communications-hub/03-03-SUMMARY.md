---
phase: 03-communications-hub
plan: "03"
subsystem: api
tags: [flask, webhook, quo, openphone, hmac, call-logging, sms, voicemail, pytest, tdd]

requires:
  - phase: 03-communications-hub-02
    provides: app/comms/ package, comms_bp Blueprint, verify_quo_webhook, normalize_e164, find_customer_by_phone, DEFAULT_AGENCY_ID config slot
  - phase: 03-communications-hub-01
    provides: CustomerNote model (quo_call_id, twilio_msg_sid columns), UnmatchedCall model, pytest conftest with SQLite in-memory

provides:
  - app/comms/webhooks.py — POST /comms/webhook/quo handling all Quo event types
  - call.completed handling: answered calls (note_type='call'), missed calls (note_type='missed_call')
  - call.recording.completed handling: voicemails (note_type='voicemail') with recording URL fetch
  - message.received / message.delivered handling: SMS notes (note_type='sms')
  - Unknown callers -> UnmatchedCall with provider='quo'
  - Idempotency: duplicate quo_call_id or twilio_msg_sid returns 200 without duplicate records
  - 8 unit tests covering all stated behaviors

affects:
  - 03-communications-hub-04 (Calendly webhook — same comms_bp, same conftest pattern)
  - 03-communications-hub-05 (Retell AI webhook — same error-handling pattern)
  - 03-communications-hub-07 (agency_id scoping sweep — find_customer_by_phone will be updated)

tech-stack:
  added: []
  patterns:
    - "Webhook handler imports verify_quo_webhook directly — patch target must be app.comms.webhooks.verify_quo_webhook, not app.comms.utils.verify_quo_webhook"
    - "Always return 200 from webhook routes — log errors, rollback, return status=error body to prevent provider retry storms"
    - "Quo duration field is in seconds — store as duration_minutes = duration_seconds // 60 (not // 60000)"
    - "twilio_msg_sid column used for Quo message IDs — SMS idempotency key regardless of provider"
    - "agency_id resolved from DEFAULT_AGENCY_ID config — User model has no agency_id until Plan 07"

key-files:
  created:
    - app/comms/webhooks.py
  modified:
    - app/comms/__init__.py
    - tests/test_comms_webhooks.py

key-decisions:
  - "patch target is app.comms.webhooks.verify_quo_webhook (where function is imported) not app.comms.utils.verify_quo_webhook (where it is defined) — Python mock patches the name binding in the module using it"
  - "CustomerNote has no agency_id column — idempotency check uses just quo_call_id (globally unique Quo call ID)"
  - "agency_id for UnmatchedCall always sourced from DEFAULT_AGENCY_ID config (int, default 1) — User model has no agency_id FK until Plan 07 scoping sweep"
  - "Missed call detection: status in ('no-answer','missed') OR answeredAt is None — covers all Quo missed call variants"

patterns-established:
  - "Webhook handler helpers (_handle_call_completed, _handle_recording_completed, _handle_sms) return None — caller commits after all handlers run"
  - "Outer try/except in quo_webhook() catches all exceptions, rolls back session, returns 200 with status=error body"
  - "_resolve_customer_from_participants() walks participants list and returns (customer, from_number) — used by both call and recording handlers"
  - "_create_unmatched_call() is the single path for any unresolvable call/SMS regardless of event type"

requirements-completed: [SC-1, SC-2, SC-6]

duration: 22min
completed: 2026-04-02
---

# Phase 3 Plan 03: Quo Webhook Handler Summary

**Flask POST /comms/webhook/quo handling all Quo event types — calls, missed calls, voicemails, SMS — with UnmatchedCall fallback for unknown numbers and idempotency on all event IDs**

## Performance

- **Duration:** 22 min
- **Started:** 2026-04-02T19:25:57Z
- **Completed:** 2026-04-02T19:47:57Z
- **Tasks:** 2 (TDD: test RED commit + implementation GREEN commit)
- **Files modified:** 3

## Accomplishments
- `app/comms/webhooks.py` created — unified Quo webhook handler covering all 4 event types with per-type helpers and shared `_resolve_customer_from_participants` / `_create_unmatched_call` utilities
- Idempotency enforced on all paths: `quo_call_id` for calls/voicemails, `twilio_msg_sid` for SMS — second POST with duplicate ID returns 200 without creating records
- 8 unit tests replacing Plan 01 stubs — all passing; HMAC rejection test verifies without mocking; 7 functional tests use `app.comms.webhooks.verify_quo_webhook` patch target

## Task Commits

Each task was committed atomically:

1. **Task 1: Write failing tests (RED phase)** - `52ee313` (test)
2. **Task 2: Implement webhooks.py + fix patch targets (GREEN phase)** - `26303e6` (feat)

_Note: Task 1 was TDD RED — all 8 tests failed with 404 before webhooks.py existed. Task 2 turned them GREEN._

## Files Created/Modified
- `app/comms/webhooks.py` — POST /comms/webhook/quo route plus 3 event handlers and 2 shared helpers (261 lines)
- `app/comms/__init__.py` — Added `from app.comms import webhooks  # noqa` to register routes
- `tests/test_comms_webhooks.py` — 8 real tests replacing stubs; Calendly stubs preserved for Plan 04

## Decisions Made
- Python mock patches the name binding in the module that uses the function, not where it's defined. Tests must patch `app.comms.webhooks.verify_quo_webhook`. This was discovered during GREEN phase when all mocked tests returned 403 — auto-fixed immediately.
- `CustomerNote` has no `agency_id` column (added in Plan 07 scoping sweep). Idempotency check uses just `quo_call_id` which is globally unique by Quo convention.
- `agency_id` for `UnmatchedCall` always comes from `DEFAULT_AGENCY_ID` config (defaults to 1). `User` model has no `agency_id` FK until Plan 07.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed mock patch target from utils to webhooks module**
- **Found during:** Task 2 (GREEN phase — running tests after implementation)
- **Issue:** Plan's test pattern used `patch("app.comms.utils.verify_quo_webhook")` but `webhooks.py` imports the function directly into its namespace, so the utils module name binding is not what Flask calls at request time
- **Fix:** Updated all 7 functional test patch targets to `app.comms.webhooks.verify_quo_webhook`; updated `requests.get` patch to `app.comms.webhooks.requests.get` for the recording test
- **Files modified:** `tests/test_comms_webhooks.py`
- **Verification:** All 8 tests pass after fix
- **Committed in:** `26303e6` (Task 2 commit)

**2. [Rule 1 - Bug] Removed agency_id from CustomerNote idempotency query**
- **Found during:** Task 2 (implementation review — CustomerNote model has no agency_id column)
- **Issue:** Plan's pseudocode showed `CustomerNote.query.filter_by(quo_call_id=call_id, agency_id=agency_id)` but CustomerNote has no agency_id column; adding that filter would raise an AttributeError at runtime
- **Fix:** Idempotency query uses only `quo_call_id` (globally unique per Quo); voicemail check additionally filters on `note_type="voicemail"` to allow a separate note if the same call ID somehow appears in both event types
- **Files modified:** `app/comms/webhooks.py`
- **Verification:** Idempotency test (test_quo_duplicate_idempotency) passes; no AttributeError
- **Committed in:** `26303e6` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 bugs)
**Impact on plan:** Both fixes necessary for correctness. No scope creep.

## Issues Encountered
None beyond the two auto-fixed deviations above.

## User Setup Required
None — no new external service configuration required. Route exists at `/comms/webhook/quo`; will activate when `QUO_WEBHOOK_SIGNING_KEY` is set in VPS `.env` and Quo dashboard webhook URL is registered.

## Next Phase Readiness
- Quo webhook handler is complete and tested — ready to go live once Quo account is provisioned
- `app/comms/__init__.py` routes pattern established: add `from app.comms import <module>  # noqa` to register additional webhook handlers
- Plans 04 (Calendly) and 05 (Retell) follow the same structure: new handler module, import in `__init__.py`, tests patching `app.comms.<module>.verify_*`
- Pre-flight blocker remains: Quo (OpenPhone) account must be provisioned before `/comms/webhook/quo` goes live

## Self-Check: PASSED

- app/comms/webhooks.py: FOUND
- tests/test_comms_webhooks.py: FOUND
- 03-03-SUMMARY.md: FOUND
- commit 52ee313 (RED tests): FOUND
- commit 26303e6 (implementation): FOUND

---
*Phase: 03-communications-hub*
*Completed: 2026-04-02*
