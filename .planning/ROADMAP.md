# Roadmap: Founders Portal / MAMS

## Overview

Phases 1 and 2 are complete: production infrastructure, carrier BOB parsers, commission auditing, and the customer master record are live. Phase 2.5 (PostgreSQL migration) is a hard prerequisite before Phase 3 begins — the multi-tenant Agency model must be built in PostgreSQL from the start, never retrofitted from SQLite. Phases 3 through 7 build the features that make the portal the single tab agents need — communication history without manual entry, compliance-grade SOA and license tracking, operational tooling, analytics, and finally the full multi-tenant SaaS architecture that becomes MAMS.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

<details>
<summary>Phases 1 & 2 — Complete (validated 2026-03-20)</summary>

- [x] **Phase 1: Infrastructure & Core** - VPS, auth, carrier BOB parsers, commission audit, agent dashboard
- [x] **Phase 2: Customer Master** - Customer model (MBI-keyed), contacts, notes, AOR history, pharmacies

</details>

- [ ] **Phase 2.5: PostgreSQL Migration** *(hard prerequisite — must complete before Phase 3)*
- [ ] **Phase 3: Communications Hub** - Twilio + Retell AI voice engine; Google Meet native recording; Calendly + HealthSherpa webhooks; SMS templates; email campaigns; consent model; multi-tenant Agency model
- [ ] **Phase 4: Compliance Reference** - Carrier plan master (CMS API), NIPR license sync, expense reimbursement
- [ ] **Phase 5: Operations** - Time logging, service tickets, lead source, MedicareCenter PDF OCR, SOP hub
- [ ] **Phase 6: Analytics** - Commission forecast, AEP performance, retention/churn metrics, pharmacy ROI, nightly aggregation
- [ ] **Phase 7: White Label / Multi-Tenant** - PostgreSQL schema-per-tenant, agency onboarding wizard, branding, Stripe billing, audit log, HIPAA gates
  *(Agency model + agency_id FK architecture established in Phase 2.5/3 — this phase adds full schema isolation, billing, and operator portal)*

## Phase Details

### Phase 2.5: PostgreSQL Migration *(Hard prerequisite — do not start Phase 3 until complete)*

**Goal**: Migrate the production database from SQLite to PostgreSQL on the NixiHost VPS, with zero data loss. All existing data (policies, commissions, customers, agents) must be verified in PostgreSQL before any Phase 3 work begins. The multi-tenant Agency model and agency_id foreign keys must land in PostgreSQL from the start — never in SQLite.

**Why this is a hard prerequisite**: The Agency model and agency_id FK columns that underpin all Phase 3 features require PostgreSQL column types and constraints. Building these in SQLite and migrating later creates schema debt and data migration risk during AEP season.

**Depends on**: Phase 2

**Tasks**:
  - Install PostgreSQL on NixiHost VPS
  - Create `founders_portal` database and user with appropriate permissions
  - Update `config.py` DATABASE_URL from SQLite to PostgreSQL connection string
  - Run `flask db upgrade` — verify all existing Alembic migrations apply cleanly
  - Verify all existing data migrated correctly (commissions, policies, customers, agent contracts)
  - Update `.env` with new `DATABASE_URL`
  - Test full application against PostgreSQL (auth, BOB upload, commission audit, customer master)
  - Remove SQLite dependency from `requirements.txt`
  - Add 2GB swap file to VPS (required before AEP webhook traffic)
  - Update Gunicorn config to threading model (`--workers 2 --threads 4 --worker-class gthread`)
  - Update FOUNDERS_PORTAL_CONTEXT.md Section 4 to reflect PostgreSQL as production database

**Success Criteria** (what must be TRUE):
  1. Flask app starts and serves requests from PostgreSQL — no SQLite file referenced in production
  2. All existing data is present and counts match between old SQLite export and new PostgreSQL tables
  3. Commission audit, BOB upload, and customer master all function identically against PostgreSQL
  4. Alembic migration chain applies cleanly from scratch against a fresh PostgreSQL database
  5. VPS swap file active and Gunicorn threading config deployed

**Plans:** 5 plans

Plans:
- [ ] 02.5-01-PLAN.md — Fix __init__.py syntax, init Flask-Migrate, generate baseline migration
- [ ] 02.5-02-PLAN.md — Add Agency model, generate migrations 002+003 (nullable + NOT NULL), create seed script
- [ ] 02.5-03-PLAN.md — Install PostgreSQL 16 on VPS, create DB/user, run flask db upgrade
- [ ] 02.5-04-PLAN.md — pgloader data transfer, verify row counts, seed Agency, apply NOT NULL migration
- [ ] 02.5-05-PLAN.md — Cutover .env, add swap file, update Gunicorn threading, full smoke test

---

### Phase 3: Communications Hub

**Goal**: Agents see complete communication history on every customer profile — calls, SMS threads, and meeting summaries appear automatically without manual entry; agents can send CMS-approved SMS templates and targeted email campaigns from within the portal. All multi-tenant Agency infrastructure lands here.

**Telephony**: Dialpad (primary). Webhooks for call.completed, call.missed, voicemail.created, SMS. JWT HS256 signed payloads.

**Edge-case telephony**: Twilio — for programmatic SMS blasts and Retell AI SIP trunking.

**AI Voice Engine**: Retell AI (confirmed). HIPAA compliant, SOC2 Type II, $0.07/min, 600-800ms latency. Handles inbound missed calls — triage, appointment booking via Calendly mid-call, message taking.

**Meeting Recording**: Google Meet native recording. Fireflies eliminated (BAA requires $40/user/mo Enterprise + Private Storage). Google Workspace Business Plus BAA already covers Meet. One unique Meet space created per appointment via Meet REST API; Workspace Events webhook fires when transcript is ready. Cost: $0 additional.

**Enrollment Data**: HealthSherpa webhooks replace MedicareCenter PDF OCR (abandoned — too memory-intensive). Agency account setup pending — email medicare-integrations@healthsherpa.com. Captive join code required for LOA agents (full payload); AOR agents use independent join code (limited payload).

**Pre-code dependencies (must be true before Phase 3 code starts)**:
  - Phase 2.5 complete — app running on PostgreSQL
  - Dialpad account provisioned (DIALPAD_HMAC_SECRET in `.env`) — sign BAA immediately on signup
  - Twilio account provisioned (account SID, auth token in `.env`) — for SMS blasts and Retell SIP trunk
  - Retell AI trial tested — call own number, verify quality with Medicare senior persona
  - HealthSherpa agency account active and captive join code distributed
  - Google Workspace admin settings: Meet recording + transcription enabled for domain
  - Calendly plan tier confirmed for API access (Professional or Teams)
  - HIPAA BAA status verified: Google Workspace (done via Business Plus), Twilio/SendGrid, Retell AI, Calendly, HealthSherpa, NixiHost

**Depends on**: Phase 2.5

**New models (Phase 3 schema migrations)**:
  - `UnmatchedCall` — queue for calls with no customer match (new table)
  - `SmsTemplate` — admin-approved CMS-compliant template library (new table)
  - `CustomerNote` extended — dialpad_call_id, twilio_msg_sid, retell_call_id, resolved columns added
  - `Customer` extended — sms_consent_at datetime added
  - `agency_id` FK backfill on remaining tables without it (CustomerContact, CustomerAorHistory, etc.)

**Success Criteria** (what must be TRUE):
  1. Agent opens a customer profile and sees all calls (completed and missed) with timestamp, duration, direction, and AI summary — no manual entry required
  2. Agent opens a customer profile and sees the full SMS thread with that customer, including inbound and outbound messages via Dialpad
  3. After a Calendly booking, a pre-call brief (current plan, last interaction, open tasks) appears on the agent dashboard automatically
  4. After a Google Meet appointment, the AI-extracted meeting summary and action items appear on the customer profile — no manual entry
  5. Agent can send an admin-approved, CMS-compliant SMS template to a consenting customer directly from the customer profile
  6. Inbound call from unknown number creates an UnmatchedCall record and surfaces in agent's resolution queue
  7. Every database query is scoped to `agency_id` — no query returns cross-tenant data

**Plans:** 7 plans

Plans:
- [ ] 03-01-PLAN.md — Schema migrations + test infrastructure (models, Alembic, pytest fixtures)
- [ ] 03-02-PLAN.md — comms blueprint skeleton, phone utils, webhook verifiers, config slots
- [ ] 03-03-PLAN.md — Dialpad webhook handler (calls + SMS + voicemail + UnmatchedCall creation)
- [ ] 03-04-PLAN.md — Calendly webhook + UnmatchedCall resolution UI + upcoming appointments dashboard card
- [ ] 03-05-PLAN.md — SMS template admin CRUD + agent send endpoint + consent guard
- [ ] 03-06-PLAN.md — Google Meet Pub/Sub subscriber (systemd service) + HealthSherpa webhook
- [ ] 03-07-PLAN.md — agency_id scoping sweep across all existing queries (SC-7)

---

### Phase 4: Compliance Reference

**Goal**: Agents and admins have authoritative plan and license data without leaving the portal — carrier plans are sourced from CMS and searchable by H-number; agent licenses are synced from NIPR with expiration warnings; expense reimbursements have a clear submission and approval workflow.

**Depends on**: Phase 3

**Requirements**: PLAN-01, PLAN-02, PLAN-03, PLAN-04, NIPR-01, NIPR-02, NIPR-03, NIPR-04, EXPE-01, EXPE-02, EXPE-03, EXPE-04

**Success Criteria** (what must be TRUE):
  1. Agent can look up any carrier plan by H-number or carrier name and see premium, MOOP, network type, and star rating — data sourced from CMS Plan Finder, not manually maintained
  2. Customer AOR history displays plan name and premium pulled from the carrier_plans table when a match exists
  3. Dashboard displays a warning banner for any agent whose license expires within 60 days; admin can view all agent licenses in one view
  4. Agent can submit an expense with receipt, admin can approve or reject it with a note, and admin can mark approved expenses as paid and see total unpaid reimbursements per agent

**Plans**: TBD

### Phase 5: Operations

**Goal**: Agents have structured tooling for tracking their time and service work within the portal — interaction time is logged against customers, service tickets are opened and closed, the lead source field enables downstream analytics, MedicareCenter enrollment PDFs are auto-parsed into customer records, and agents have a searchable SOP knowledge base.

**Depends on**: Phase 4

**Requirements**: OPER-01, OPER-02, OPER-03, OPER-04, OPER-05, OPER-06, OPER-07

**Success Criteria** (what must be TRUE):
  1. Agent can log time spent on a customer interaction (minutes, activity type) from the customer profile; the profile displays a time log summary
  2. Agent can open and close service tickets on a customer; the customer profile shows all open tickets
  3. Agent uploads a MedicareCenter enrollment PDF and the system extracts name, DOB, plan, carrier, effective date, and agent NPN — matching the record to the correct customer automatically
  4. Agent can search the SOP knowledge base by keyword and find published SOP documents; admin can publish new SOPs

**Plans**: TBD

### Phase 6: Analytics

**Goal**: Admins and agents have a data-driven view of agency performance — commission forecast, AEP conversion rates, retention by carrier, and pharmacy ROI are all visible from the dashboard with data sourced from pre-aggregated nightly summary tables, never on-demand queries against live data.

**Depends on**: Phase 5

**Requirements**: ANAL-01, ANAL-02, ANAL-03, ANAL-04, ANAL-05, ANAL-06

**Success Criteria** (what must be TRUE):
  1. Each agent's dashboard shows a commission forecast by carrier (Part D, supplement, MAPD) broken down by projected rates
  2. Admin can view AEP performance per agent: appointments booked, enrolled, conversion rate, and comparison to the prior AEP
  3. Admin can view retention rates by carrier and plan across the agency; customers flagged as churn risk appear with a visible indicator on their profiles
  4. Analytics pages load from pre-aggregated summary tables — no on-demand GROUP BY queries run against live customer or policy tables

**Plans**: TBD

### Phase 7: White Label / Multi-Tenant

**Goal**: The portal becomes a deployable SaaS product — new agencies are provisioned with isolated PostgreSQL schemas, have their own branding, and pay via Stripe; HIPAA compliance gates (BAA, audit log, data export) are fully closed; the Founders agency runs as the first tenant with zero data loss from the SQLite migration.

**Depends on**: Phase 6

**Prerequisites (must be true before Phase 7 starts)**:
  - All Phase 3–6 Alembic migrations use PostgreSQL-compatible column types (no SQLite-specific types)
  - `SQLALCHEMY_ECHO=False` enforced in production config
  - Audit log model complete (current CONCERNS.md flags it as incomplete)
  - HIPAA BAA obtained from SendGrid, OpenPhone, and hosting provider
  - `current_agency` context processor injected in all templates (prevents hardcoded-brand refactor)

**Requirements**: WLAB-01, WLAB-02, WLAB-03, WLAB-04, WLAB-05, WLAB-06, WLAB-07, WLAB-08

**Success Criteria** (what must be TRUE):
  1. Founders agency data is fully intact in a `founders` PostgreSQL schema after migration — all customers, policies, notes, commissions, and files present with zero data loss
  2. A new agency can be provisioned through the admin onboarding wizard: isolated schema created, branding configured, Stripe subscription active — without any manual database work
  3. Each agency sees only its own data; the MAMS operator portal can view all agencies, billing status, and support tickets across tenants
  4. Any agency can export all of their data (customers, policies, notes, commissions) as CSV or JSON; all PHI mutations are recorded in the audit log with user ID, timestamp, and field-level diff

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 2.5 → 3 → 4 → 5 → 6 → 7
**Phase 2.5 is a hard gate — Phase 3 does not begin until 2.5 is complete and verified.**

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Infrastructure & Core | - | Complete | 2026-03-20 |
| 2. Customer Master | - | Complete | 2026-03-20 |
| 2.5. PostgreSQL Migration | 0/TBD | Not started | - |
| 3. Communications Hub | 0/7 | Planned | - |
| 4. Compliance Reference | 0/TBD | Not started | - |
| 5. Operations | 0/TBD | Not started | - |
| 6. Analytics | 0/TBD | Not started | - |
| 7. White Label / Multi-Tenant | 0/TBD | Not started | - |

---
*Roadmap created: 2026-03-20*
*Last updated: 2026-03-26 — Phase 3 planned (7 plans, 6 waves); telephony updated to Dialpad primary / Twilio edge-case; new models updated to reflect CustomerNote extension approach (not 8 new tables); plan list added*
