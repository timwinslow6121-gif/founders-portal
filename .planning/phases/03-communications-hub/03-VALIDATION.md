---
phase: 3
slug: communications-hub
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pytest.ini` or `setup.cfg` (Wave 0 installs if missing) |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 1 | SC-7 | migration | `flask db upgrade && flask db downgrade` | ❌ W0 | ⬜ pending |
| 3-01-02 | 01 | 1 | SC-7 | unit | `pytest tests/test_agency_scoping.py -x -q` | ❌ W0 | ⬜ pending |
| 3-02-01 | 02 | 2 | SC-1, SC-2, SC-6 | unit | `pytest tests/test_comms_webhooks.py -x -q` | ❌ W0 | ⬜ pending |
| 3-03-01 | 03 | 3 | SC-3 | unit | `pytest tests/test_comms_webhooks.py -x -q -k "calendly"` | ❌ W0 | ⬜ pending |
| 3-04-01 | 04 | 4 | SC-5 | unit | `pytest tests/test_comms_sms.py -x -q` | ❌ W0 | ⬜ pending |
| 3-05-01 | 05 | 4 | SC-4 | unit | `pytest tests/test_meet_pubsub.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Plan 01 creates the full test infrastructure. The consolidated file names produced by Plan 01 are:

- [ ] `tests/test_agency_scoping.py` — stubs for SC-7 query scoping
- [ ] `tests/test_comms_webhooks.py` — stubs for SC-1 (Dialpad call/missed/voicemail), SC-2 (Dialpad SMS), SC-3 (Calendly booking), SC-6 (unknown caller queue), HealthSherpa enrollment
- [ ] `tests/test_comms_sms.py` — stubs for SC-5 (template approval + send + consent guard)
- [ ] `tests/test_meet_pubsub.py` — stubs for SC-4 (Pub/Sub transcript.fileGenerated)
- [ ] `tests/test_phone_utils.py` — stubs for phone normalization utilities
- [ ] `tests/conftest.py` — shared fixtures (app factory, test DB, mock agency)
- [ ] `pytest` — install if not detected in requirements.txt

Note: Individual per-concern files (test_dialpad_webhook.py, test_dialpad_sms.py, test_unmatched_call.py, test_calendly_webhook.py, test_sms_template.py) are NOT created. Coverage for those concerns is consolidated into test_comms_webhooks.py and test_comms_sms.py respectively.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Dialpad JWT signature validation | SC-1, SC-2 | Requires live Dialpad signing secret + real webhook payload | Send test webhook from Dialpad dashboard; verify 200 response + CustomerNote created |
| SMS message content visibility | SC-2 | Requires `message_content_export` scope on Dialpad API key | Send test SMS; verify body appears in CustomerNote |
| Retell AI missed call triage | SC-1 | Requires live Retell AI account + SIP trunk configured | Call test number; verify AI answers + creates CustomerNote on hangup |
| Calendly booking → pre-call brief | SC-3 | Requires live Calendly Professional+ account | Book test appointment; verify upcoming appointments card on agent dashboard |
| Google Meet transcript delivery | SC-4 | Requires Google Workspace Pub/Sub subscription live | Complete Meet call; wait for transcript webhook; verify CustomerNote created |
| HealthSherpa enrollment | SC-7 (data integrity) | Requires HealthSherpa agency account + captive join code | Submit test enrollment; verify CustomerNote created with correct agency_id |
| SMS consent guard | SC-5 | UX flow — no send button if `sms_consent_at` is NULL | Attempt SMS send on customer without consent; verify UI blocks it |
| Unmatched call resolution | SC-6 | UX flow — resolution queue and match workflow | Call from unknown number; verify sidebar badge + resolution UI |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
