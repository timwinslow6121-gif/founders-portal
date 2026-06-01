# Founders Portal / MAMS

## What This Is

A purpose-built Medicare agency management portal serving Founders Insurance Agency (8 agents, 510 customers, 524 policies across 5 carriers). Built by a Medicare agent for Medicare agents — consolidating carrier BOB imports, commission auditing, customer master records, and communications into one platform. Long-term trajectory: white-label SaaS (MAMS) for the 15,000–20,000 independent Medicare agencies nationwide.

## Core Value

Agents open one tab and everything they need is there — no switching between carrier portals, personal phones, spreadsheets, scheduling tools, and CRMs.

## Requirements

### Validated (built and deployed)

*Phase 1 — Infrastructure & Core:*
- ✓ VPS, Nginx, Gunicorn, SSL, DNS — production infra live
- ✓ Google OAuth restricted to @foundersinsuranceagency.com
- ✓ Carrier BOB parsers: UHC, Humana, Aetna, BCBS, Devoted, Healthspring (all XLSX/XLS formats including HTML-disguised XLS)
- ✓ Single + bulk BOB file upload (agents + admins); agent uploads auto-attribute to current_user
- ✓ Agent dashboard filtered by agent_id
- ✓ Admin overview with agent detail view
- ✓ Birthday labels (Avery 5160 PDF)
- ✓ Commission audit (7 carriers, per-agent split rates, contract validation, discrepancy workflow)
- ✓ Agent settings (carrier contracts, splits, agent IDs)

*Phase 2 — Customer Master:*
- ✓ Flask-Migrate initialized — all schema changes tracked
- ✓ Customer model (MBI-keyed, humana_id, manually_edited flag, carrier_address, deal_stage)
- ✓ CustomerContact, CustomerNote, CustomerAorHistory models
- ✓ _upsert_customer_from_policy() — BOB imports auto-build customer master; manually_edited flag protects agent edits
- ✓ customers_bp blueprint (list, profile, notes, contacts, pharmacy link, duplicates, merge)
- ✓ Pharmacy model + pharmacies_bp (admin CRUD, rent tracking, pharmacy_agents join table)

*Phase 2.5 — PostgreSQL Migration:*
- ✓ PostgreSQL 16 on NixiHost VPS; Flask-Migrate baseline + all migrations apply cleanly
- ✓ Agency multi-tenant model; agency_id FK on all tables
- ✓ All data migrated from SQLite (5,589 rows); 2GB swap; Gunicorn gthread workers

*Phase 3 — Communications Hub:*
- ✓ comms_bp blueprint: Quo/Twilio/Calendly webhooks; UnmatchedCall model + resolution queue
- ✓ Phone normalization + customer lookup utilities
- ✓ Quo webhook handler (call.completed, call.missed, voicemail, SMS → CustomerNote)
- ✓ Calendly invitee.created webhook → CustomerNote (appointment_scheduled)
- ✓ UnmatchedCall resolution UI (agent queue, inline assign/create/search)
- ✓ SMS template admin (create/approve/reject) + agent send endpoint + consent guard
- ✓ Google Meet Pub/Sub subscriber skeleton + HealthSherpa webhook skeleton (pending external provisioning)
- ✓ agency_id scoping sweep — all queries scoped to current_user.agency_id

*Phase 4 — Data Integrity & Plan Database:*
- ✓ Humana mbi=''→NULL backfill (196 policies); partial unique index WHERE mbi IS NOT NULL (migration 014)
- ✓ 25 shell customers hard-deleted; 510 customers, 524 policies remain
- ✓ MBI duplicate detection + side-by-side admin merge UI (AOR-safe, single-transaction)
- ✓ BOB quarantine — non-Humana rows missing MBI quarantined; 4th tab in import modal with inline resolution
- ✓ BOB↔Commission reconciliation page
- ✓ Per-customer payment history section on customer profile
- ✓ Policy commission_type field (initial/renewal); inline AJAX editor
- ✓ Payment Ledger (per-carrier, per-period; MBI/ID/fuzzy match confidence)
- ✓ Agent AOR visibility — current-AOR-only default; read-only former-AOR toggle; write-lock for non-current AOR
- ✓ Plan model (migration 009): 38 plans seeded, CMS IDs, lifecycle status, successor chain, commission rates, BOB alias matching
- ✓ carriers_bp: plan list (filter/sort), plan detail (chain viz, member count), admin add/edit
- ✓ CMS sync: sync_cms_plan_data.py (premium/MOOP/star rating from Landscape CSV)
- ✓ CMS sync: sync_pbp_benefit_data.py (pcp/specialist/er copays from PBP flat files)
- ✓ Customer list filter bar (carrier, plan type, agent, medicaid), stats strip, CSV export, resizable columns, saved views (personal + shared DB)
- ✓ Commission parser fixes: UHC April 2026 29-col layout, Aetna per-row agent attribution, nickname matching
- ✓ System-aware light/dark theme (prefers-color-scheme); border-radius 6px; font sizes normalized
- ✓ Terminations redesign: priority-based, 30-day window, term_reason/new_carrier/new_plan_name fields

### Active / In Progress

*Phase 5 — Plan Database SOB Enhancement (next):*
- [ ] Migration 018: drug_tier4, drug_tier5, sob_url columns on plans table
- [ ] Full benefit snapshot in details_json: inpatient, SNF, ambulance, dental, vision, OTC, food card, transport, gym, hearing, drug deductible + exempt tiers
- [ ] Additional CMS sync scripts: pbp_b1a, pbp_b2, pbp_b9, pbp_b10, pbp_b16, pbp_b17, pbp_b18, pbp_mrx
- [ ] plan_detail.html — SOB sections: Medical, Supplemental, Prescriptions
- [ ] plan_list.html — benefit summary columns (dental allowance, OTC, star rating)
- [ ] plan_form.html — per-benefit note fields

*Phase 6 — Operations (planned):*
- [ ] Commission statement → Customer/Policy sync on upload (stub auto-creation, AOR discrepancy flagging)
- [ ] Agent time log per customer interaction (minutes + activity type)
- [ ] Service tickets (open/close/resolve) linked to customers
- [ ] Lead source field on Customer model
- [ ] NIPR license sync per agent + dashboard expiration warnings (60-day)
- [ ] Expense reimbursement (submit/approve/reject/paid; receipt upload)
- [ ] SOP knowledge base (admin publish, agent search)

*Phase 7 — Analytics (planned):*
- [ ] Commission forecast by carrier per agent
- [ ] AEP performance tracking per agent (vs. prior AEP)
- [ ] Retention/churn rates by carrier and plan; churn-risk flag on customer profile
- [ ] Pharmacy ROI (leads + enrolled per pharmacy per rent dollar)
- [ ] Nightly pre-aggregation — no on-demand GROUP BY against live tables

*Phase 8 — White Label / Multi-Tenant (planned):*
- [ ] PostgreSQL schema-per-tenant isolation; agency onboarding wizard
- [ ] White-label branding per agency (logo, name, primary color)
- [ ] Stripe billing + per-tier subscription management
- [ ] MAMS operator portal (cross-tenant visibility + support)
- [ ] Full data export (CSV/JSON) per agency
- [ ] HIPAA BAA from all data processors (SendGrid, NixiHost, Twilio, Retell AI, Calendly)
- [ ] Audit log: all PHI mutations with user ID, timestamp, field-level diff

### Out of Scope

- Real-time chat — SMS via Quo covers the use case; chat is high complexity and not a Medicare workflow
- Native mobile app (iOS/Android) — PWA covers field use without app store overhead
- Replacing MedicareCenter — CMS requires 10-year SOA storage; portal references it, doesn't duplicate it
- MedicareCenter PDF OCR — abandoned (too memory-intensive on 1GB VPS); HealthSherpa webhooks replace it
- Celery/Redis message queue — unnecessary at 8-agent scale; 150-300MB RAM overhead on 1GB VPS
- Fireflies integration — eliminated; BAA requires $40/user/mo Enterprise; Google Meet native recording used instead
- Generic CRM features — MAMS differentiates on Medicare-specific data (MBI, AOR, Medicaid levels)

## Context

- **Agency:** Founders Insurance Agency, Charlotte NC — 8 agents, AOR/LOA split, partner pharmacy relationships
- **Infrastructure:** NixiHost KVM VPS ($5/mo), Ubuntu 22.04, 1GB RAM, 2vCPU, portal.foundersinsuranceagency.com
- **Database:** PostgreSQL 16 in production (migrated from SQLite in Phase 2.5); Flask-Migrate tracking all migrations
- **Carriers:** UHC, Humana, Aetna, BCBS NC, Devoted, Healthspring — all BOB + commission parsers complete
- **VoIP:** Quo (formerly OpenPhone) — primary VoIP, webhooks live. Twilio for SMS blasts + Retell AI SIP trunking.
- **Commission split:** 55% default; Betty Marlowe 52.5%; Tim (Humana) 100% direct; escalating to 70% by 2032
- **Dev workflow:** Local Crostini is dev machine; commit + push from local; VPS pulls + flask db upgrade + restart
- **Long-term:** MAMS white-label SaaS targeting 15,000–20,000 independent Medicare agencies; FMO partnerships Q4 2026; community launch Q1 2027

## Key Decisions

| Decision | Rationale | Status |
|---|---|---|
| MBI as cross-carrier customer key | Only stable identifier across all carriers; Humana masks it (humana_id fallback) | ✓ Production |
| manually_edited flag on Customer | Agents' corrections must survive carrier BOB re-imports | ✓ Production |
| BCBS term_date as renewal date | BCBS uses "term date" as next renewal, not disenrollment; sentinel logic in place | ✓ Production |
| Flask-Migrate from Phase 2 | db.create_all() unsafe in production; migration history required for multi-tenant migration | ✓ Production |
| PostgreSQL on VPS (Phase 2.5) | Multi-tenant schema isolation and Agency model require PostgreSQL column types | ✓ Production |
| Quo (OpenPhone) over RingCentral | Modern webhook-first API, $13/user/mo Standard; webhooks live in production | ✓ Production |
| Twilio edge-case + Retell AI SIP | SMS blasts + missed-call AI callbacks via Twilio SIP; Retell AI HIPAA SOC2 compliant | ✓ Production |
| Google Meet native recording (not Fireflies) | Google Workspace Business Plus BAA covers Meet; Fireflies BAA requires $40/user/mo Enterprise | ✓ Skeleton built, pending Workspace admin setup |
| HealthSherpa webhooks (not PDF OCR) | MedicareCenter OCR too memory-intensive; HealthSherpa provides enrollment data via webhook | ✓ Skeleton built, pending HealthSherpa provisioning |
| details_json for SOB benefit fields | Avoids 30-column migration on plans table; flexible for adding fields per plan type | ✓ Active (Phase 5) |
| Partial unique index on customers.mbi | Allows mbi=NULL (Humana) while enforcing uniqueness for all carriers with MBI | ✓ Migration 014 |
| BOB quarantine for unresolvable rows | Prevents shell customer creation; gives AJ inline resolution UI instead of silent data loss | ✓ Production |
| schema-per-tenant PostgreSQL (Phase 8) | Maximum HIPAA isolation, per-agency backup/restore, clear data ownership | Pending Phase 8 |
| Founders as living beta | Real data, real agents, real pain points — builds proof before FMO outreach | ✓ Production |

## External Blockers (Phase 3.06)

- **HealthSherpa:** Agency admin account created; awaiting provisioning. Webhook skeleton built; register URL + HEALTHSHERPA_WEBHOOK_SECRET once active.
- **Google Meet Pub/Sub:** Pub/Sub subscriber code built; pending: Meet recording + transcription enabled in Workspace admin, Pub/Sub topic + subscription created, service account on VPS, GOOGLE_MEET_PUBSUB_SUBSCRIPTION in .env.

---
*Last updated: 2026-06-01 — full sync: PostgreSQL live, Quo live, Phases 1–4 complete, Phase 5–8 replanned*
