# Requirements: Founders Portal / MAMS

**Defined:** 2026-03-20
**Last updated:** 2026-06-01 — full traceability sync after Phases 3 & 4 complete
**Core Value:** Agents open one tab and everything they need is there — no switching between carrier portals, personal phones, spreadsheets, scheduling tools, and CRMs.

## v1 Requirements

Requirements for phases 3–8. Phases 1 & 2 are validated (see PROJECT.md).

---

### Webhook Infrastructure *(Phase 3 — Complete)*

- [x] **WEBH-01**: System stores every inbound webhook event with provider-assigned event ID before processing — idempotency via `quo_call_id` / `twilio_msg_sid` / `calendly_event_id` unique checks
- [x] **WEBH-02**: System rejects webhooks with invalid HMAC signature and returns 403 — `verify_quo_webhook()` and `verify_calendly_webhook()` abort(403) on failure
- [x] **WEBH-03**: System returns 200 within 3 seconds of webhook receipt — all handlers return immediately, heavy work is minimal (note write + commit)

---

### Quo (OpenPhone) Integration *(Phase 3 — Partially Complete)*

> Note: OpenPhone rebranded to Quo. All webhook code uses Quo naming.

- [x] **OPHO-01**: Agent can view calls (completed + missed) on a customer's profile page, with timestamp, duration, and direction — CustomerNote (note_type=call / missed_call) rendered on profile
- [x] **OPHO-02**: System automatically creates a CustomerNote (note_type=call) when a call.completed webhook fires for a known customer phone number
- [x] **OPHO-03**: System automatically creates a CustomerNote (note_type=missed_call) when a call.missed webhook fires
- [x] **OPHO-04**: Agent can view SMS thread with a customer on the customer profile — CustomerNote (note_type=sms) per message
- [x] **OPHO-05**: System automatically logs inbound and outbound SMS messages as CustomerNotes when message webhooks fire
- [ ] **OPHO-06**: Admin can view and manage provisioned Quo numbers mapped to agents in agent settings — *not built; deferred to Phase 6*

---

### Calendly Integration *(Phase 3 — Complete)*

- [x] **CALY-01**: Each agent has a Calendly booking URL stored on their user profile — `User.calendly_url` field used in webhook routing
- [x] **CALY-02**: System automatically creates a CustomerNote (note_type=appointment_scheduled) when a Calendly invitee.created webhook fires
- [x] **CALY-03**: System stores appointment timestamp from Calendly webhook — `calendly_event_id` + scheduled_start stored on CustomerNote for downstream SOA rule enforcement

---

### ~~Fireflies Integration~~ *(Out of Scope — replaced by Google Meet)*

> Fireflies eliminated: BAA requires $40/user/mo Enterprise + Private Storage. Google Workspace Business Plus BAA already covers Meet at $0 additional cost.

- ~~FIRE-01~~: *Eliminated — Google Meet Pub/Sub subscriber handles meeting summary → CustomerNote*
- ~~FIRE-02~~: *Eliminated — same replacement*

**Replacement (Phase 3 — Skeleton built, pending external setup):**
Google Meet Pub/Sub subscriber (`app/comms/` + systemd service) built. Pending: Meet recording + transcription enabled in Workspace admin, Pub/Sub topic/subscription created, service account on VPS.

---

### SMS Template Library *(Phase 3 — Complete)*

- [x] **SMST-01**: Admin can create, edit, and deactivate SMS templates with name, body text, and CMS-compliance status — `SmsTemplate` model, admin CRUD routes in `app/comms/templates_admin.py`
- [x] **SMST-02**: Agent can send an approved SMS template to a customer from the customer profile page — send endpoint + customer profile integration
- [x] **SMST-03**: Sent template messages are logged as CustomerNotes (note_type=sms) with template name recorded
- [x] **SMST-04**: System blocks sending to customers where sms_consent is False or null — `send_sms_template()` raises ValueError("no_consent") if `sms_consent_at is None`

---

### Email Campaigns *(Phase 6 — Not built)*

- [ ] **EMAI-01**: Admin can create email campaigns with subject, body (HTML), and recipient filter criteria
- [ ] **EMAI-02**: Recipient filters support: carrier, plan name, renewal month, birthday month, Medicaid level, deal_stage, lead_source
- [ ] **EMAI-03**: Admin can preview recipient count before sending
- [ ] **EMAI-04**: System sends campaigns via SendGrid and logs each send as a CustomerNote (note_type=email)
- [ ] **EMAI-05**: System blocks sending to customers where email_consent is False or null
- [ ] **EMAI-06**: All campaign emails include mandatory CMS-compliant disclaimer language

---

### Automated Reminder Sequences *(Phase 6 — Not built)*

- [ ] **REMI-01**: System sends a day-before appointment reminder SMS when a Calendly appointment is booked
- [ ] **REMI-02**: System sends a 1-hour-before appointment reminder SMS
- [ ] **REMI-03**: System sends a post-appointment follow-up email after meeting summary received
- [ ] **REMI-04**: Agent can disable automated reminders for a specific customer appointment

---

### Consent Tracking *(Phase 3 — Partial)*

- [x] **CONS-01**: Customer model has `sms_consent_at` (datetime, nullable) — present on Customer model
- [ ] **CONS-02**: Agent can set sms_consent and email_consent from the customer profile page — *sms_consent_at settable; email_consent field not yet added; no dedicated consent UI*
- [ ] **CONS-03**: Customer list displays consent status indicators — *not built*

> Note: `email_consent` field not added to Customer model yet. Needed before email campaign work begins.

---

### Carrier Plan Master *(Phase 4 — Partially Complete; Phase 5 extends)*

> Note: PLAN-01 originally specified CMS Plan Finder API. Actual implementation used manual seed + CMS Landscape CSV + PBP flat file sync scripts — more reliable and no API auth required.

- [x] **PLAN-01** *(revised)*: Plans table populated from CMS Landscape CSV and PBP flat files — `sync_cms_plan_data.py` + `sync_pbp_benefit_data.py`; 38 plans seeded with H-numbers, premiums, MOOP, star ratings, pcp/specialist/er copays
- [ ] **PLAN-02**: Admin can trigger a manual refresh of carrier plan data — *not built; refresh done by running scripts on VPS; a UI trigger is a Phase 5 nice-to-have*
- [x] **PLAN-03**: Agent can look up a plan by H-number or carrier name — carriers_bp plan list with carrier/type/year filters and H-number display on plan detail
- [ ] **PLAN-04**: Customer AOR history displays plan name and premium from carrier_plans when available — *partial; plan_name displayed on profile via Policy join, but not yet pulling premium from Plan table*

---

### NIPR License Sync *(Phase 6 — Not built)*

- [ ] **NIPR-01**: Each agent has a license records table (state, license number, type, issued date, expiration date, status)
- [ ] **NIPR-02**: System syncs agent license status from NIPR API on demand (admin-triggered)
- [ ] **NIPR-03**: Dashboard displays a warning for agents with licenses expiring within 60 days
- [ ] **NIPR-04**: Admin can view all agent licenses and expiration dates in one view

---

### Expense Reimbursement *(Phase 6 — Not built)*

- [ ] **EXPE-01**: Agent can submit an expense (type, amount, description, optional receipt upload) for admin approval
- [ ] **EXPE-02**: Admin can approve or reject submitted expenses with a note
- [ ] **EXPE-03**: Agent can view their expense history (submitted/approved/paid status)
- [ ] **EXPE-04**: Admin can mark approved expenses as paid and view total unpaid reimbursements per agent

---

### Commission → Customer/Policy Sync *(Phase 6 — Not built; plan exists)*

> Design plan at `/home/timothywinslowlinux/.claude/plans/we-need-to-discuss-buzzing-honey.md`

- [ ] **CSYN-01**: On commission upload, matched policy records are enriched — plan_type, plan_name, effective_date (if earlier), term_date + status='termed', term_reason, commission_type
- [ ] **CSYN-02**: Unmatched MBI on commission upload auto-creates a stub Customer + Policy (stub=True, source='commission_import')
- [ ] **CSYN-03**: Stub customer profile shows "Incomplete Record" banner; auto-promoted to full record when DOB + contact info filled in
- [ ] **CSYN-04**: AOR discrepancy (commission file agent ≠ stored primary_agent_id) flagged in import modal 5th tab; not auto-updated
- [ ] **CSYN-05**: CommissionStatement.aor_flags_json stores discrepancy list per upload

---

### Operations *(Phase 6 — Not built)*

- [ ] **OPER-01**: Agent can log time spent on a customer interaction (minutes, activity type: prospecting/servicing/enrollment/admin)
- [ ] **OPER-02**: Agent can create and close customer service tickets (issue type, description, resolution notes)
- [ ] **OPER-03**: Customer profile displays open tickets and time log summary
- [ ] **OPER-04**: Customer model has lead_source field (pharmacy_referral / self_generated / referral / web / other)
- [ ] **OPER-05**: Admin can create and publish SOP documents in a searchable knowledge base
- [ ] **OPER-06**: Agent can view the SOP knowledge base and search by keyword

> Note: OPER-05 (MedicareCenter PDF OCR) removed from scope — too memory-intensive on 1GB VPS; replaced by HealthSherpa webhooks for enrollment data.

---

### Plan Database SOB Enhancement *(Phase 5 — Not built)*

- [x] **SOB-01**: Plan detail page shows full medical benefits section — inpatient hospital (tiered by day), SNF, outpatient surgery, ambulance, ER, PCP, specialist, urgent care
- [x] **SOB-02**: Plan detail page shows supplemental benefits section — dental (allowance + note), vision, hearing, OTC (allowance + note), healthy food card, transportation, gym
- [x] **SOB-03**: Plan detail page shows drug coverage section — deductible, exempt tiers, tier 1–5 copays
- [x] **SOB-04**: SOB PDF link displayed prominently on plan detail page (sob_url field)
- [x] **SOB-05**: Plan list rows show benefit summary: dental allowance, OTC, star rating, member count
- [ ] **SOB-06**: Per-benefit note fields editable in admin plan form (dental_note, otc_note, vision_note, etc.)
- [x] **SOB-07**: CMS PBP sync scripts populated for inpatient, SNF, ambulance, dental, vision, hearing, drug tiers (pbp_b1a, b2, b9, b10, b16, b17, b18, mrx files)
- [x] **SOB-08**: Migration 018 adds drug_tier4, drug_tier5 VARCHAR(32) and sob_url VARCHAR(512) to plans table

---

### Analytics *(Phase 7 — Not built)*

- [ ] **ANAL-01**: Dashboard displays commission forecast by carrier (Part D + supplement + MAPD projected rates) for each agent
- [ ] **ANAL-02**: Dashboard displays AEP performance per agent: appointments booked, enrolled, conversion rate, vs prior AEP
- [ ] **ANAL-03**: Admin can view retention rates by carrier and plan across the agency
- [ ] **ANAL-04**: System flags customers at churn risk based on plan age, contact recency, plan changes
- [ ] **ANAL-05**: Admin can view partner pharmacy ROI: leads and enrolled per pharmacy per rent dollar
- [ ] **ANAL-06**: Analytics data is pre-aggregated nightly — no on-demand GROUP BY queries against live database

---

### White Label / Multi-Tenant *(Phase 8 — Not built)*

- [ ] **WLAB-01**: Founders agency data intact in isolated PostgreSQL schema after migration — zero data loss
- [ ] **WLAB-02**: New agencies provisioned via admin onboarding wizard: isolated schema, branding, Stripe subscription — no manual DB work
- [ ] **WLAB-03**: Each agency can configure custom branding (logo, agency name, primary color)
- [ ] **WLAB-04**: Billing handled via Stripe with per-tier subscription management
- [ ] **WLAB-05**: MAMS operator admin portal can view all agencies, billing status, and support tickets
- [ ] **WLAB-06**: Any agency can export all their data (customers, policies, notes, commissions) as CSV/JSON
- [ ] **WLAB-07**: All data processors have signed HIPAA Business Associate Agreements (SendGrid, NixiHost, Twilio, Retell AI, Calendly)
- [ ] **WLAB-08**: Audit log captures all PHI mutations with user ID, timestamp, and field-level diff

---

## v2 Requirements

### SOA Management

- **SOA-01**: Agent can create a CMS-compliant Scope of Appointment, send via SMS or email, and track signature status
- **SOA-02**: System enforces the 48-hour rule: SOA signed_at must be ≥48 hours before appointment time
- **SOA-03**: System stores SOA reference ID from MedicareCenter for 10-year retention compliance
- **SOA-04**: Agent can send SOA for e-signature via DocuSign from the customer profile page

### Customer Portal

- **CUST-01**: Customer can log in to view their own plan information, renewal dates, and agent contact info
- **CUST-02**: Customer can book an appointment directly from the customer portal via Calendly embed
- **CUST-03**: Customer can sign SOA electronically from the customer portal

### Mobile PWA

- **PWA-01**: Portal installs as a Progressive Web App on iOS and Android home screens
- **PWA-02**: Customer list and customer profiles are readable offline (cached)
- **PWA-03**: "Who's calling?" inbound phone lookup: entering an incoming phone number returns the matching customer record instantly

### Carrier Contacts

- **CARR-01**: Admin can maintain a carrier rep contact directory (rep name, phone, email, role, what they handle)
- **CARR-02**: Agents can search carrier contacts by carrier and issue type

---

## Out of Scope

| Feature | Reason |
|---|---|
| Native e-signature (non-DocuSign) | HIPAA/CMS compliance requires a BAA-backed provider |
| Real-time chat (agent ↔ customer) | SMS via Quo covers the use case; chat is high complexity |
| Video post/storage | Not a Medicare agency workflow |
| Native mobile app (iOS/Android) | PWA covers field use without app store overhead |
| Replacing MedicareCenter | It handles 10-year SOA storage required by CMS |
| Fireflies integration | Eliminated — BAA $40/user/mo Enterprise; Google Meet native recording used instead |
| MedicareCenter PDF OCR | Too memory-intensive on 1GB VPS; HealthSherpa webhooks replace enrollment data |
| Amplicare/Enliven Health parity | Replace with CMS Plan Finder bulk files (free, government-authoritative) |
| Generic CRM features | MAMS differentiates on Medicare-specific data (MBI, AOR, Medicaid levels) |
| Celery/Redis message queue | Unnecessary at 8-agent scale; 150-300MB RAM overhead on 1GB VPS |

---

## Traceability

| Requirement | Phase | Status |
|---|---|---|
| WEBH-01 | Phase 3 | ✅ Complete |
| WEBH-02 | Phase 3 | ✅ Complete |
| WEBH-03 | Phase 3 | ✅ Complete |
| OPHO-01 | Phase 3 | ✅ Complete |
| OPHO-02 | Phase 3 | ✅ Complete |
| OPHO-03 | Phase 3 | ✅ Complete |
| OPHO-04 | Phase 3 | ✅ Complete |
| OPHO-05 | Phase 3 | ✅ Complete |
| OPHO-06 | Phase 3 | ⏳ Deferred to Phase 6 |
| CALY-01 | Phase 3 | ✅ Complete |
| CALY-02 | Phase 3 | ✅ Complete |
| CALY-03 | Phase 3 | ✅ Complete |
| FIRE-01 | — | 🚫 Out of scope (replaced by Google Meet) |
| FIRE-02 | — | 🚫 Out of scope (replaced by Google Meet) |
| SMST-01 | Phase 3 | ✅ Complete |
| SMST-02 | Phase 3 | ✅ Complete |
| SMST-03 | Phase 3 | ✅ Complete |
| SMST-04 | Phase 3 | ✅ Complete |
| EMAI-01 | Phase 6 | ⏳ Not built |
| EMAI-02 | Phase 6 | ⏳ Not built |
| EMAI-03 | Phase 6 | ⏳ Not built |
| EMAI-04 | Phase 6 | ⏳ Not built |
| EMAI-05 | Phase 6 | ⏳ Not built |
| EMAI-06 | Phase 6 | ⏳ Not built |
| REMI-01 | Phase 6 | ⏳ Not built |
| REMI-02 | Phase 6 | ⏳ Not built |
| REMI-03 | Phase 6 | ⏳ Not built |
| REMI-04 | Phase 6 | ⏳ Not built |
| CONS-01 | Phase 3 | ✅ Complete (sms_consent_at) |
| CONS-02 | Phase 6 | ⏳ Partial — no email_consent field yet; no consent UI |
| CONS-03 | Phase 6 | ⏳ Not built |
| PLAN-01 | Phase 4 | ✅ Complete (revised — CSV/PBP sync, not API) |
| PLAN-02 | Phase 5 | ⏳ Not built (no UI trigger; scripts run manually on VPS) |
| PLAN-03 | Phase 4 | ✅ Complete |
| PLAN-04 | Phase 5 | ⏳ Partial — plan_name shown, premium not yet pulled from Plan table |
| NIPR-01 | Phase 6 | ⏳ Not built |
| NIPR-02 | Phase 6 | ⏳ Not built |
| NIPR-03 | Phase 6 | ⏳ Not built |
| NIPR-04 | Phase 6 | ⏳ Not built |
| EXPE-01 | Phase 6 | ⏳ Not built |
| EXPE-02 | Phase 6 | ⏳ Not built |
| EXPE-03 | Phase 6 | ⏳ Not built |
| EXPE-04 | Phase 6 | ⏳ Not built |
| CSYN-01 | Phase 6 | ⏳ Not built (plan ready) |
| CSYN-02 | Phase 6 | ⏳ Not built (plan ready) |
| CSYN-03 | Phase 6 | ⏳ Not built (plan ready) |
| CSYN-04 | Phase 6 | ⏳ Not built (plan ready) |
| CSYN-05 | Phase 6 | ⏳ Not built (plan ready) |
| OPER-01 | Phase 6 | ⏳ Not built |
| OPER-02 | Phase 6 | ⏳ Not built |
| OPER-03 | Phase 6 | ⏳ Not built |
| OPER-04 | Phase 6 | ⏳ Not built |
| OPER-05 | Phase 6 | ⏳ Not built |
| OPER-06 | Phase 6 | ⏳ Not built |
| SOB-01 | Phase 5 | ⏳ Not built |
| SOB-02 | Phase 5 | ⏳ Not built |
| SOB-03 | Phase 5 | ⏳ Not built |
| SOB-04 | Phase 5 | ⏳ Not built |
| SOB-05 | Phase 5 | ⏳ Not built |
| SOB-06 | Phase 5 | ⏳ Not built |
| SOB-07 | Phase 5 | ⏳ Not built |
| SOB-08 | Phase 5 | ⏳ Not built |
| ANAL-01 | Phase 7 | ⏳ Not built |
| ANAL-02 | Phase 7 | ⏳ Not built |
| ANAL-03 | Phase 7 | ⏳ Not built |
| ANAL-04 | Phase 7 | ⏳ Not built |
| ANAL-05 | Phase 7 | ⏳ Not built |
| ANAL-06 | Phase 7 | ⏳ Not built |
| WLAB-01 | Phase 8 | ⏳ Not built |
| WLAB-02 | Phase 8 | ⏳ Not built |
| WLAB-03 | Phase 8 | ⏳ Not built |
| WLAB-04 | Phase 8 | ⏳ Not built |
| WLAB-05 | Phase 8 | ⏳ Not built |
| WLAB-06 | Phase 8 | ⏳ Not built |
| WLAB-07 | Phase 8 | ⏳ Not built |
| WLAB-08 | Phase 8 | ⏳ Not built |

**Coverage summary (2026-06-01):**
- v1 requirements: 72 total (67 original + 5 CSYN added + OPER-05 removed + 8 SOB added)
- Complete: 17 (WEBH ×3, OPHO ×5, CALY ×3, SMST ×4, CONS-01, PLAN-01, PLAN-03)
- Partial / skeleton: 4 (Google Meet, CONS-02, PLAN-02, PLAN-04)
- Out of scope: 2 (FIRE-01, FIRE-02)
- Not yet built: 49

---
*Requirements defined: 2026-03-20*
*Last updated: 2026-06-01 — full traceability sync; Phase 3 items marked complete; FIRE eliminated; CSYN added; SOB block added; phase assignments corrected for NIPR/EXPE (Phase 4→6)*
