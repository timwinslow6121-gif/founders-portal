---
phase: 03-communications-hub
plan: "02"
subsystem: api
tags: [flask, blueprint, phonenumbers, hmac, webhook, e164, pytest]

requires:
  - phase: 03-communications-hub-01
    provides: UnmatchedCall model, SmsTemplate model, migration 004, pytest conftest with SQLite in-memory fixture
provides:
  - app/comms/ package (comms_bp Blueprint, url_prefix=/comms)
  - normalize_e164 — E.164 phone normalization via phonenumbers library
  - find_customer_by_phone — OR query on phone_primary/phone_secondary
  - verify_quo_webhook — HMAC-SHA256 with base64-decoded signing key, replay protection
  - verify_calendly_webhook — t=TIMESTAMP,v1=SIGNATURE format, stdlib hmac
  - verify_retell_webhook — base64-encoded HMAC-SHA256 (low-confidence step noted in code)
  - GET /comms/health smoke-test endpoint
  - inject_unmatched_count context processor for sidebar badge
  - QUO_WEBHOOK_SIGNING_KEY, QUO_API_KEY, and all Phase 3 webhook config slots in config.py
affects:
  - 03-communications-hub-03 (Quo webhook handler imports verify_quo_webhook from here)
  - 03-communications-hub-04 (Calendly webhook handler imports verify_calendly_webhook)
  - 03-communications-hub-05 (Retell webhook handler imports verify_retell_webhook)
  - 03-communications-hub-06 (any plan needing phone normalization or customer phone lookup)
  - 03-communications-hub-07 (agency_id scoping sweep adds filter to find_customer_by_phone)

tech-stack:
  added: []
  patterns:
    - "Webhook verifier pattern: stdlib hmac.new + base64 only — no PyJWT, no third-party jwt"
    - "Replay protection: 5-minute window via abs(time.time() - timestamp) > 300"
    - "TDD: test stubs from Plan 01 replaced with real tests; RED confirmed before GREEN"
    - "Context processor for sidebar badge: import model inside function to avoid circular imports"

key-files:
  created:
    - app/comms/__init__.py
    - app/comms/utils.py
  modified:
    - app/__init__.py
    - config.py
    - tests/test_phone_utils.py

key-decisions:
  - "find_customer_by_phone accepts agency_id parameter but does not filter on it yet — scoping deferred to Plan 07 sweep to avoid breaking before Customer.agency_id column exists"
  - "verify_retell_webhook base64 step marked LOW confidence — comment in code directs future maintainer to verify against Retell SDK source if signature validation fails"
  - "All webhook verifiers call abort(403) directly rather than raising exceptions — consistent with Flask idiom and avoids extra error-handler wiring"

patterns-established:
  - "Webhook verifier functions take the Flask request object as argument — no global current_request dependency"
  - "comms/__init__.py context processor uses try/except around the entire block to prevent unauthenticated or missing agency_id from raising in any template context"

requirements-completed: [SC-1, SC-2, SC-3, SC-6, SC-7]

duration: 18min
completed: 2026-04-02
---

# Phase 3 Plan 02: Communications Hub Foundation Summary

**Flask comms blueprint with E.164 phone normalization, customer phone lookup, and three HMAC webhook verifiers (Quo/Calendly/Retell) using stdlib only — no PyJWT**

## Performance

- **Duration:** 18 min
- **Started:** 2026-04-02T19:25:00Z
- **Completed:** 2026-04-02T19:43:00Z
- **Tasks:** 3
- **Files modified:** 4 (created 2, modified 2, replaced 1 test stub)

## Accomplishments
- `app/comms/` package created — comms_bp Blueprint with `/comms/health` smoke route and `inject_unmatched_count` context processor for sidebar badge
- `app/comms/utils.py` implemented: `normalize_e164` (7 US format variants), `find_customer_by_phone` (OR filter), and three webhook signature verifiers using stdlib hmac only
- Blueprint registered in `app/__init__.py` using exact CLAUDE.md 3-line pattern; all Phase 3 webhook config slots added to `config.py`
- 7 TDD tests in `tests/test_phone_utils.py` replacing Plan 01 stubs — all passing

## Task Commits

Each task was committed atomically:

1. **Task 1: Create app/comms/__init__.py** - `f2a492d` (feat)
2. **Task 2: Create app/comms/utils.py + real phone util tests** - `a7bd410` (feat)
3. **Task 3: Register comms_bp + config slots** - `227844e` (feat)

_Note: Task 2 was TDD — tests written first (RED: ImportError), then implementation (GREEN: 7/7 pass)_

## Files Created/Modified
- `app/comms/__init__.py` — Blueprint definition, health route, inject_unmatched_count context processor
- `app/comms/utils.py` — 5 shared functions: normalize_e164, find_customer_by_phone, verify_quo_webhook, verify_calendly_webhook, verify_retell_webhook
- `app/__init__.py` — Added 3-line comms_bp registration block
- `config.py` — Added QUO_WEBHOOK_SIGNING_KEY, QUO_API_KEY, RETELL_WEBHOOK_SECRET, CALENDLY_WEBHOOK_SECRET, HEALTHSHERPA_WEBHOOK_SECRET, GOOGLE_MEET_PUBSUB_SUBSCRIPTION, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, DEFAULT_AGENCY_ID
- `tests/test_phone_utils.py` — Replaced Plan 01 stubs with 7 real normalize_e164 tests

## Decisions Made
- `find_customer_by_phone` intentionally does not filter by `agency_id` yet — `Customer.agency_id` column added in Plan 07 scoping sweep. Parameter accepted so callers don't need to change signature in Plan 07.
- `verify_retell_webhook` base64 encoding step marked LOW confidence in an inline comment — exact Retell SDK signing method unverified from training data. Comment directs maintainer to check Retell SDK source if signature validation fails in production.
- Webhook verifiers call Flask `abort(403)` directly — no custom exception classes needed at this stage.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required (config slots added but use empty-string defaults until VPS .env is updated).

## Next Phase Readiness
- `app/comms/` package ready — Plans 03, 04, 05, 06 can now import from `app.comms.utils`
- `comms_bp` registered — webhook route handlers just need `from app.comms import comms_bp` and `@comms_bp.route(...)` decorators
- Config slots exist — once VPS .env has QUO_WEBHOOK_SIGNING_KEY and QUO_API_KEY, Quo webhook handler (Plan 03) can go live
- Remaining blocker: Quo (OpenPhone) account must be provisioned before webhook handler goes live (pre-flight checklist item)

---
*Phase: 03-communications-hub*
*Completed: 2026-04-02*
