# Roadmap: Founders Portal / MAMS

## Overview

Phases 1–4 are complete and deployed to production. The portal is live at portal.foundersinsuranceagency.com serving 8 agents, 510 customers, and 524 policies across 5 carriers. Phase 5 (Plan Database SOB) extends the Carriers & Plans module into a full plan comparison reference tool. Phases 6–8 build the operational tooling, analytics, and multi-tenant SaaS architecture that becomes MAMS.

**Note on Phase numbering:** Phase 2.5 (PostgreSQL) and Phase 3 (Communications Hub) completed as planned. Phase 4 was replanned mid-execution to focus on data integrity + plan database rather than NIPR/expense tracking (those moved to Phase 6). All historical plans remain in `.planning/phases/`.

## Phases

**Phase Numbering:**
- Integer phases: Planned milestone work
- Decimal phases: Urgent insertions or extensions

<details>
<summary>Phases 1 & 2 — Complete (validated 2026-03-20)</summary>

- [x] **Phase 1: Infrastructure & Core** — VPS, Nginx, Gunicorn, SSL, Google OAuth, carrier BOB parsers (6 carriers), commission audit, agent dashboard, birthday labels
- [x] **Phase 2: Customer Master** — Customer model (MBI-keyed), CustomerContact, CustomerNote, CustomerAorHistory, Pharmacy model, customers_bp + pharmacies_bp, all templates

</details>

<details>
<summary>Phase 2.5 — PostgreSQL Migration — Complete (validated 2026-03-26)</summary>

- [x] **Phase 2.5: PostgreSQL Migration** — PostgreSQL 16 on VPS, Flask-Migrate initialized, Agency multi-tenant model + agency_id FKs, 5,589 rows migrated, 2GB swap, Gunicorn gthread. All 5 plans complete.

</details>

- [x] **Phase 3: Communications Hub** — Quo/Twilio webhooks, Calendly integration, SMS templates, agency_id scoping sweep, UnmatchedCall resolution UI, Google Meet Pub/Sub + HealthSherpa webhook skeleton. All 7 plans complete. (2026-04-13)
- [x] **Phase 4: Data Integrity & Plan Database** — MBI backfill, partial unique index, duplicate merge UI, BOB quarantine, commission reconciliation, Carriers & Plans module (Plan model, 38 plans seeded, CMS sync scripts), payment ledger, AOR visibility, commission type, customer list enhancements, theme overhaul. (2026-06-01)
- [ ] **Phase 5: Plan Database SOB Enhancement** — Full SOB snapshot per plan (inpatient, SNF, dental, vision, OTC, drug tiers), enhanced plan list/detail views matching HealthSherpa reference charts, per-benefit admin note fields
- [ ] **Phase 6: Operations** — Commission statement→customer sync, agent time logging, service tickets, lead source tracking, NIPR license sync, expense reimbursement, SOP hub
- [ ] **Phase 7: Analytics** — Commission forecast, AEP performance, retention/churn metrics, pharmacy ROI, nightly pre-aggregation
- [ ] **Phase 8: White Label / Multi-Tenant** — PostgreSQL schema-per-tenant, agency onboarding wizard, branding, Stripe billing, HIPAA gates, audit log closure

---

## Phase Details

### Phase 5: Plan Database SOB Enhancement *(next)*

**Goal**: The Carriers & Plans page becomes the portal's equivalent of HealthSherpa's plan comparison tool — every plan has a full SOB snapshot (medical benefits, supplemental benefits, drug tiers) that agents can reference without leaving the portal. CMS bulk files auto-populate most fields; agents add nuance notes manually.

**Depends on**: Phase 4

**Design decisions locked in (2026-06-01):**
- Enhance existing `plan_list.html` / `plan_detail.html` / `plan_form.html` — do not rebuild
- Per-benefit note fields stored as named keys in `details_json` (column already exists) — no 30-column migration
- Migration 018: `drug_tier4` + `drug_tier5` VARCHAR(32), `sob_url` VARCHAR(512)
- CMS PBP flat files drive auto-population; manual note fields for nuance (e.g. "OTC = online only")

**Benefit fields to populate (via `details_json`):**
```
inpatient_hospital, inpatient_hospital_note
outpatient_surgery
snf
ambulance
urgent_care_copay
dental_allowance, dental_note
vision_allowance, vision_note
otc_allowance, otc_note
healthy_food_card
transportation
gym
hearing, hearing_note
drug_deductible, drug_deductible_exempt_tiers
sob_url
```

**CMS source files for additional sync scripts (pbp-benefits-2026/):**
- `pbp_b1a_inpat_hosp.txt` → inpatient_hospital
- `pbp_b2_snf.txt` → snf
- `pbp_b9_outpat_hosp.txt` → outpatient_surgery
- `pbp_b10_amb_trans.txt` → ambulance
- `pbp_b16_dental.txt` → dental_allowance
- `pbp_b17_eye_exams_wear.txt` → vision_allowance
- `pbp_b18_hearing_exams_aids.txt` → hearing
- `pbp_mrx.txt` + `pbp_mrx_tier.txt` → drug tiers 4+5, deductible

**Success Criteria** (what must be TRUE):
1. Plan detail page shows complete SOB: medical benefits section, supplemental benefits section (dental/vision/hearing/OTC/fitness/food/transport), drug tier table
2. Per-benefit note fields visible inline next to each benefit on detail view
3. SOB PDF link displayed prominently on plan detail
4. Plan list rows show: premium, MOOP, PCP copay, specialist copay, dental allowance, OTC, star rating, member count
5. All benefit data for active MAPD plans populated from CMS PBP files (b1a, b2, b9, b10, b16, b17, b18, mrx)
6. Admin form allows editing all benefit fields and saving notes per benefit

**Plans**: 4 plans

- [x] 05-01-PLAN.md — Migration 018 + Plan model SOB columns (drug_tier4, drug_tier5, sob_url)
- [ ] 05-02-PLAN.md — sync_pbp_extended_benefits.py: 9 CMS PBP files → details_json + drug_tier4/5 DB columns
- [ ] 05-03-PLAN.md — plan_detail SOB cards + plan_list benefit columns (routes + 2 templates)
- [ ] 05-04-PLAN.md — plan_form structured SOB sections + merge-not-overwrite details_json serialization

---

### Phase 6: Operations

**Goal**: Commission data enriches customer/policy records automatically on upload. Agents have structured tooling for time logging, service tickets, and lead tracking. NIPR license expiration warnings prevent compliance lapses. Expense reimbursement has a clear submission/approval workflow. Agents have a searchable SOP knowledge base.

**Depends on**: Phase 5

**Key work items:**
- Commission statement → Customer/Policy sync on upload (stub customer auto-creation on unmatched MBI; AOR discrepancy flagging; policy enrichment — plan_type, plan_name, effective_date, commission_type, term_date)
- Agent time log per customer interaction (minutes + activity type from customer profile)
- Service tickets (open/close/resolve) linked to customers
- Lead source field on Customer model
- NIPR license sync per agent (API or manual) + dashboard expiration warnings (60-day window)
- Expense reimbursement (submit/approve/reject/mark-paid workflow with receipt upload)
- SOP knowledge base (admin publish, agent search by keyword)

**Pending migrations:** 019+ for stub Customer fields (stub boolean, source string), CommissionStatement.aor_flags_json, service ticket table, time log table, lead source field

**Success Criteria** (what must be TRUE):
1. Commission upload automatically enriches matched policy records (plan_type, plan_name, effective_date, commission_type)
2. Unmatched MBI on commission upload auto-creates a stub Customer + Policy; agent can promote to full record from portal
3. AOR discrepancy (commission file writing agent ≠ stored primary_agent_id) is flagged in import modal — not auto-updated
4. Agent can log time on a customer interaction; profile shows time log summary
5. Agent can open and close service tickets on a customer
6. Dashboard warns agents with licenses expiring within 60 days
7. Agent can submit an expense with receipt; admin can approve/reject/mark-paid
8. Agent can search published SOP documents by keyword

**Plans**: TBD (estimate 5–6 plans)

---

### Phase 7: Analytics

**Goal**: Admins and agents have a data-driven view of agency performance — commission forecast, AEP conversion rates, retention by carrier, and pharmacy ROI sourced from nightly pre-aggregated summary tables, never on-demand queries.

**Depends on**: Phase 6

**Success Criteria** (what must be TRUE):
1. Agent dashboard shows commission forecast by carrier (MAPD/PDP/supplement projected rates)
2. Admin can view AEP performance per agent: appointments booked, enrolled, conversion rate, vs prior AEP
3. Admin can view retention rates by carrier and plan; churn-risk customers flagged on profiles
4. Analytics pages load from pre-aggregated nightly tables — no GROUP BY against live data

**Plans**: TBD

---

### Phase 8: White Label / Multi-Tenant

**Goal**: The portal becomes a deployable SaaS product — new agencies are provisioned with isolated PostgreSQL schemas, have their own branding, and pay via Stripe. HIPAA compliance gates are fully closed. Founders Agency runs as the first tenant.

**Depends on**: Phase 7

**Prerequisites (must be true before Phase 8 starts):**
- All Alembic migrations use PostgreSQL-compatible types
- `SQLALCHEMY_ECHO=False` enforced in production config
- AuditLog model complete and capturing all PHI mutations
- HIPAA BAA obtained from all data processors (SendGrid, NixiHost, Twilio, Retell AI, Calendly)
- `current_agency` context processor injected in all templates

**Success Criteria** (what must be TRUE):
1. Founders agency data intact in isolated schema after migration — zero data loss
2. New agency provisioned through onboarding wizard: isolated schema, branding, Stripe subscription — no manual DB work
3. Each agency sees only its own data; MAMS operator portal has cross-tenant visibility
4. Any agency can export all data as CSV/JSON; all PHI mutations in audit log with field-level diff

**Plans**: TBD

---

## Progress

**Execution Order:** 5 → 6 → 7 → 8

| Phase | Plans | Status | Completed |
|-------|-------|--------|-----------|
| 1. Infrastructure & Core | — | ✅ Complete | 2026-03-20 |
| 2. Customer Master | — | ✅ Complete | 2026-03-20 |
| 2.5. PostgreSQL Migration | 5/5 | ✅ Complete | 2026-03-26 |
| 3. Communications Hub | 7/7 | ✅ Complete | 2026-04-13 |
| 4. Data Integrity & Plan Database | 5/5 | ✅ Complete | 2026-06-01 |
| 5. Plan Database SOB Enhancement | 1/4 | In Progress|  |
| 6. Operations | 0/TBD | Not started | — |
| 7. Analytics | 0/TBD | Not started | — |
| 8. White Label / Multi-Tenant | 0/TBD | Not started | — |

---

## What Phase 4 Built (vs. Original Scope)

The original Phase 4 scope described NIPR license sync, expense reimbursement, and CMS Plan Finder API. During execution the scope was revised to urgent data integrity work first, then the Carriers & Plans module, customer list enhancements, and theme overhaul built organically across multiple sessions (2026-05-05 to 2026-06-01). NIPR and expense tracking deferred to Phase 6.

**Completed between Phase 3 and Phase 5 (all in production):**

*Data integrity & migrations:*
- Migration 014: Humana mbi=''→NULL backfill, partial unique index on customers.mbi, unresolvable_json column
- Migration 015: PolicyPayment.agent_id nullable
- Migration 016: CustomerSavedView table
- Migration 017: Plan.friendly_name + Policy.plan_id FK
- 25 shell customers hard-deleted; 510 customers remain
- MBI duplicate detection + side-by-side merge UI (AOR-safe, single-transaction)
- BOB quarantine pipeline (4th tab in import modal, 3 inline resolution actions)
- BOB↔Commission reconciliation page + per-customer payment history on profile

*Commission & payments:*
- Policy commission_type field (initial/renewal); inline AJAX editor on customer profile
- Payment Ledger: per-carrier, per-period, 3-tier match confidence (MBI/ID/fuzzy name)
- Commission parser fixes: UHC April 2026 29-col layout, Aetna per-row agent attribution, nickname matching
- paid=0 handling: defaults to expected amount (no summary row = clean carrier file)

*Agent visibility:*
- Agent AOR visibility: current-AOR-only default, read-only former-AOR toggle, write-lock for non-current AOR

*Carriers & Plans module:*
- Plan model (migration 009) with CMS plan ID, lifecycle status, successor chain, SNP flags, commission rates, benefits snapshot, BOB alias matching
- 38 plans seeded across 6 carriers; Humana chain 137→291→335 linked; CMS IDs populated
- Plan list (filter by year/carrier/type/status), plan detail (chain viz, member count, commission highlights), admin add/edit
- Plan friendly names normalized; redundant carrier prefix stripped
- CMS sync: sync_cms_plan_data.py (Landscape CSV → monthly_premium/annual_oopm/star_rating)
- CMS sync: sync_pbp_benefit_data.py (PBP flat files → pcp_copay/specialist_copay/er_copay)
- BOB upload now resolves plan_id via _plan_alias_map() on every upsert

*Customer list:*
- Filter bar: carrier, plan_type, agent, medicaid (8 curated plan type options)
- Stats strip: total/active/termed/medicaid counts
- CSV export: /customers/export
- Resizable columns (drag handles, capture:true fix)
- Column visibility picker (9 options); saved views (personal localStorage + shared DB via CustomerSavedView)
- Sortable columns via sort=/dir= URL params

*UI/UX:*
- System-aware light/dark theme (prefers-color-scheme; replaces Lux dark-only theme)
- Border-radius 6px, larger card padding, font sizes bumped throughout
- Terminations redesign: priority-based (high/low/death), 30-day window, inline AJAX reason editor
- Pharmacy enhancements: pharmacy_agents join table, agent location assignment, expanded list view
- BOB parser fixes: UHC/Healthspring rewrites, _detect_carrier() 15-row scan, HTML-XLS detection

---
*Roadmap created: 2026-03-20*
*Last updated: 2026-06-01 — full sync after Phase 4 completion; Phases 5–8 replanned to reflect actual built state*
