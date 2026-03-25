# Founders Insurance Agency — Agent Portal
## Master Project Context Document
*Last updated: March 20, 2026*

---

## 1. Who I Am

**Name:** Timothy Winslow  
**Role:** Writing Agent + Unofficial IT Director / CTO  
**Agency:** Founders Insurance Agency  
**Website:** www.foundersinsuranceagency.com  
**Email:** tim@foundersinsuranceagency.com  
**Personal GitHub:** timwinslow6121-gif  
**Personal email:** tim.winslow6121@gmail.com

I maintain the agency website, Google Workspace, Google Business page, and provide IT support + Medicare consulting for 8 agents. I am building a custom agency management portal to be compensated for this work. Long-term this becomes a white-label SaaS product for Medicare insurance agencies — see PRODUCT_VISION.md.

---

## 2. The Agency

- **8 agents** total including myself
- **Principal agent / commission manager:** AJ (also a Google Workspace super admin)
- **All agents** have `@foundersinsuranceagency.com` Google Workspace Business Plus accounts
- **No SOPs, no onboarding process, no expense reimbursement system** — AJ/Brian cut checks in person
- **No standardized tech stack** — every agent uses different tools (see Section 3)

### Agent Roster
| Agent | Email | Type | BOB Size | Split | Notes |
|---|---|---|---|---|---|
| Timothy Winslow | tim@foundersinsuranceagency.com | AOR | 538 | 55% | Owns BOB, portal admin, real data in DB |
| AJ (Admin) | admin@foundersinsuranceagency.com | Admin | — | — | Commission manager, portal admin only |
| Brian Freeman | brian@foundersinsuranceagency.com | AOR/LOA | ~1,100 | 55% | TBD — largest BOB, cannibalization risk |
| Rebekah Long | rebekah@foundersinsuranceagency.com | AOR | ~950 | 55% | 2nd largest BOB |
| Chris Foster | chris@foundersinsuranceagency.com | AOR | ~750 | 55% | |
| Justin Basinger | justin@foundersinsuranceagency.com | AOR | ~700 | 55% | |
| Mike Lauzurique | mike@foundersinsuranceagency.com | LOA | ~530 | 55% | Extension of Founders, doesn't own clients |
| Betty Marlowe | betty@foundersinsuranceagency.com | LOA | ~480 | 52.5% | Extension of Founders, lower split rate |
| Anjana Patel | anjana@foundersinsuranceagency.com | LOA | ~430 | 55% | Extension of Founders, doesn't own clients |

### AOR vs LOA Distinction
- **AOR agents** (Tim, Chris, Rebekah, Brian TBD) — own their BOB, commissions temporarily assigned to Founders
- **LOA agents** (Mike, Betty, Anjana) — Founders owns the clients, agents are extensions of Founders
- This distinction matters for client ownership, agent departure scenarios, and the Brian cannibalization problem

### Partner Pharmacies (Important Business Relationship)
- Founders pays rent to independent partner pharmacies
- In exchange, pharmacies refer customers (warm leads) to Founders agents
- Each customer should be tagged with their pharmacy in the portal
- Pharmacy referral tracking is a planned feature
- This relationship partly explains the commission cap structure (55% → 70%)

---

## 3. Current Tech Stack (The Problem)

This is what agents are currently juggling. The goal of the portal is to **consolidate as many of these as possible** into one platform so agents spend less time switching apps and more time helping customers.

| # | Tool | Purpose | Status | Replace With |
|---|---|---|---|---|
| 1 | **Zoho CRM** | Customer management | Tim only, others use nothing | This portal (full replacement) |
| 2 | **RingCentral** | SMS + telephony (Tim) | Evaluating cancellation | **Twilio** (confirmed production telephony backbone — 2026-03-24) |
| 3 | **VOXO** | SMS + telephony (some agents) | Inconsistent across agents | **Twilio** agency-wide |
| 4 | **Personal cell phones** | Customer calls/SMS | Most agents — nightmare | Twilio numbers for all agents |
| 5 | **Pharmacy direct lines** | Customer calls at pharmacy | Untrackable | Twilio routing |
| 6 | **Google Workspace** | Email, docs, calendar, storage | All agents have it | Keep — integrate deeper |
| 7 | **MedicareCenter** | Enrollment platform | All agents | Integrate via PDF OCR, don't replace |
| 8 | **Carrier portals** | UHC, Humana, etc. | Required by carriers | Can't replace, surface data via BOB imports |
| 9 | **Amplicare/Enliven Health** | Pharmacy & drug cost syncing | Some agents, expensive, unreliable | Replace with Medicare.gov API + portal |
| 10 | **Medicare.gov** | Drug cost lookup, plan comparison | Tim (most compliant method) | Embed/link + CMS Plan Finder API |
| 11 | **Calendly** | Scheduling (Tim's preference) | Tim only | Adopt agency-wide, integrate with portal |
| 12 | **Zoho Bookings** | Scheduling (some agents) | Tim hates it | Replace with Calendly |
| 13 | **Acuity Scheduling** | Scheduling (Tim previously) | Switching away | Calendly has better API |
| 14 | **Dropbox** | Document sharing (AJ) | AJ only | Replace with Google Drive (already paid for) |
| 15 | **Fireflies.ai** | Meeting recording + AI summaries | **ELIMINATED** | **Google Meet native recording** (BAA already covered by Workspace Business Plus; Fireflies BAA = $40/user/mo Enterprise only) |
| 16 | **Retell AI** | AI voice engine — inbound missed calls | New — pending trial | Twilio SIP → Retell; HIPAA/SOC2; $0.07/min; books Calendly appointments mid-call |
| 17 | **HealthSherpa** | Enrollment platform | Replacing MedicareCenter | Webhooks replace PDF OCR (abandoned — memory-intensive) |

### The Core Problem
Agents are independently operating with wildly different tools, no shared data, no SOPs, and no way to collaborate. A customer can call the pharmacy line, leave a voicemail on an agent's personal cell, send a text to a VOXO number, and email the Founders address — and none of those touch points are connected or tracked anywhere.

### The Vision: One Portal to Rule Them All
The portal becomes the single hub. Every integration flows into it:
- Twilio webhook → call logged on customer record (inbound + outbound)
- Retell AI post-call webhook → AI summary + action items extracted → customer record
- Calendly webhook → appointment linked to customer record, pre-call brief generated
- Google Meet Workspace Events webhook → transcript → meeting summary + tasks on customer record
- HealthSherpa enrollment webhook → customer matched or created, AOR history updated
- SendGrid → emails sent from portal, tracked on customer record
- Google Drive → documents linked to customer record

Agents open one tab. Everything is there.

---

## 4. Infrastructure

### VPS (Founders Portal Server)
- **Provider:** NixiHost KVM VPS
- **Cost:** $5/month
- **IP:** 23.187.248.100
- **OS:** Ubuntu 22.04 LTS
- **Specs:** 1GB RAM, 2 vCPU, 30GB SSD, 2TB bandwidth
- **SSH:** `ssh root@23.187.248.100`

### Domain & DNS
- **Registrar/Host:** NixiHost
- **Main site:** foundersinsuranceagency.com (MiniShared hosting)
- **Portal subdomain:** portal.foundersinsuranceagency.com → A record → 23.187.248.100

### SSL
- **Provider:** Let's Encrypt (Certbot, auto-renews)
- **Expires:** June 15, 2026

### Stack
- **Language:** Python 3.10
- **Framework:** Flask 3.0
- **Database:** SQLite → **PostgreSQL** (Phase 2.5 — hard prerequisite before Phase 3)
- **Web server:** Nginx (reverse proxy) + Gunicorn (WSGI)
- **Auth:** Google OAuth 2.0 (restricted to @foundersinsuranceagency.com)
- **ORM:** Flask-SQLAlchemy + Flask-Migrate (Alembic) — added Phase 2
- **Data processing:** pandas, openpyxl, lxml, reportlab, pdfplumber (planned for OCR)
- **Email:** SendGrid (Twilio, domain authenticated)
- **Version control:** GitHub (private repo)

### Key File Paths on VPS
```
/var/www/founders-portal/               → app root
/var/www/founders-portal/.env           → secrets (not in GitHub)
/var/www/founders-portal/venv/          → Python virtual environment
/var/www/founders-portal/instance/      → SQLite database
/var/www/founders-portal/seed_agents.py → fake agent data seeder
/etc/nginx/sites-available/founders-portal → Nginx config
/etc/systemd/system/founders-portal.service → systemd service
/etc/letsencrypt/live/portal.foundersinsuranceagency.com/ → SSL certs
```

### Useful Commands
```bash
ssh root@23.187.248.100
systemctl restart founders-portal
journalctl -u founders-portal -f
journalctl -u founders-portal -n 50 --no-pager | grep "Error\|File \"/var"
cd /var/www/founders-portal && source venv/bin/activate
sqlite3 /var/www/founders-portal/instance/founders_portal.db ".tables"
sqlite3 /var/www/founders-portal/instance/founders_portal.db "SELECT carrier, count(*) FROM policies GROUP BY carrier;"
sqlite3 /var/www/founders-portal/instance/founders_portal.db "SELECT carrier, gross_amount, expected_amount, paid_amount, status FROM commission_statements;"
```

### Git Workflow — CRITICAL
**Local Crostini (Chromebook) is the dev machine. Commit and push from local. VPS pulls.**

```bash
# On local Crostini (tim@penguin) — development + commits:
cd ~/Founders-Portal/founders-portal
git add <files> && git commit -m "message" && git push origin main

# On VPS (root@portal) — deployment after git pull:
cd /var/www/founders-portal && git pull origin main
source venv/bin/activate
flask db upgrade          # always run after pull if models changed
systemctl restart founders-portal
```

### VPS Deployment Checklist (after every git pull)
1. `git pull origin main`
2. `pip install -r requirements.txt` (if requirements.txt changed)
3. `flask db upgrade` (if models.py or migrations/ changed — Phase 2+)
4. `systemctl restart founders-portal`
5. `journalctl -u founders-portal -n 20 --no-pager` (verify no startup errors)

---

## 5. Google OAuth

- **Client ID:** 991785142812-gnmh1rrhv7m8ujdo77p7g85t6sukbq5g.apps.googleusercontent.com
- **Client Secret:** stored in .env
- **Redirect URI:** https://portal.foundersinsuranceagency.com/auth/callback
- **Admin emails:** tim@foundersinsuranceagency.com, admin@foundersinsuranceagency.com

---

## 6. SendGrid (Email)

- **Provider:** Twilio SendGrid (free tier → Essentials $20/mo for campaigns)
- **Domain authenticated:** foundersinsuranceagency.com
- **From address:** tim@foundersinsuranceagency.com
- **API key:** stored in .env as SENDGRID_API_KEY

---

## 7. GitHub Repository

- **Repo:** github.com/timwinslow6121-gif/founders-portal (Private)
- **Clone URL:** git@github.com:timwinslow6121-gif/founders-portal.git

### Project Structure
```
founders-portal/
├── app/
│   ├── __init__.py              → Flask app factory (registers all blueprints)
│   ├── extensions.py            → db + login_manager
│   ├── auth.py                  → Google OAuth
│   ├── routes.py                → dashboard, admin overview, agent detail
│   ├── models.py                → all database models
│   ├── upload.py                → carrier BOB upload + _upsert_customer_from_policy()
│   ├── customers.py             → customer blueprint (list, profile, notes, contacts, merge) ✅ Phase 2
│   ├── pharmacies.py            → pharmacy blueprint (admin CRUD) ✅ Phase 2
│   ├── labels.py                → birthday labels PDF
│   ├── agent_settings.py        → agent settings (contracts, splits)
│   ├── commission/
│   │   ├── __init__.py / routes.py / audit.py / forecast.py
│   ├── parsers/
│   │   ├── uhc / humana / aetna / bcbs / devoted / healthspring
│   ├── migrations/              → Alembic migration history (Flask-Migrate) ✅ Phase 2
│   └── templates/
│       ├── base.html / login.html / dashboard.html
│       ├── admin_overview.html / upload.html / labels.html
│       ├── commission.html / agent_settings.html / agent_settings_detail.html
│       ├── customers_list.html / customer_profile.html / customer_new.html ✅ Phase 2
│       ├── customer_duplicates.html ✅ Phase 2
│       ├── pharmacies.html / pharmacy_form.html ✅ Phase 2
├── seed_agents.py
├── config.py / requirements.txt / wsgi.py
└── .env / .gitignore / README.md / PRODUCT_VISION.md / FOUNDERS_PORTAL_CONTEXT.md
```

---

## 8. Carriers & File Formats

### BOB Export Files (all 6 parsers complete ✅)
| Carrier | Format | Unique ID | Address Fields |
|---|---|---|---|
| UHC | XLSX (header row 2) | mbiNumber | memberAddress1, memberCity, memberState, memberZip |
| Humana | CSV | Humana ID | Mail Address, Mail City, Mail State, Mail ZipCd |
| Aetna | CSV | Medicare Number | TBD |
| BCBS NC | CSV | Medicare/BCBSNC Number | Address 1, City, State, Zip |
| Devoted | CSV | member_id (UUID) | TBD |
| Healthspring | XLS (HTML) | Medicare Number | TBD |

### Commission Statement Files (all 5 parsers complete ✅)
| Carrier | Agent Name Format | Split Row | Special Notes |
|---|---|---|---|
| UHC | `WINSLOW, TIMOTHY JAMES` | `7955.79 x.55` | HA bonuses in Commission Action col |
| Aetna | `WINSLOW, TIMOTHY` | `202.44 x.55` | Clean format |
| Humana | `WINSLOW TIMOTHY J` | `$1,509.18 x. 55` | Chargebacks negative — net ALL rows |
| BCBS | `TIMOTHY WINSLOW` | `$635.79 x.55` | Has =SUM() row, skip it |
| Devoted | `Timothy Winslow` | `$1,100 x.55` + `605 + 4,389.55 = $4,994.55` | Bonus + paid on same row |

---

## 9. Database Schema

### Current Tables (Phase 1 + Phase 2 — all live as of 2026-03-20)
- **users, policies, import_batches, audit_logs** ✅
- **commission_statements** ✅
- **agent_carrier_contracts** ✅
- **pharmacies** ✅ Phase 2
- **customers** ✅ Phase 2
- **customer_contacts** ✅ Phase 2
- **customer_notes** ✅ Phase 2
- **customer_aor_history** ✅ Phase 2

### Key Customer Model Fields (important rules encoded here)
- `mbi` — unique index, nullable (Humana-only customers won't have it until resolved)
- `humana_id` — Humana's member ID (fallback key when MBI is masked)
- `manually_edited` — boolean; when True, BOB imports skip overwriting phone/address fields
- `carrier_address` — raw import address stored separately; never shown to agents
- `last_carrier_sync` — timestamp of most recent BOB import match
- `deal_stage` — Active / Lead / SOA_Sent / Appointed / Enrolled / Termed

### Customer Upsert Logic (in upload.py — _upsert_customer_from_policy)
1. Match by MBI first (all carriers except Humana)
2. Humana: match by `humana_id`, then name+DOB+zip (all three must match)
3. If `manually_edited == True`: do NOT overwrite phone, address, city, state, zip — only update `carrier_address` and `last_carrier_sync`
4. BCBS: `end_date` in CustomerAorHistory always set to None — BCBS term_date is a renewal date

### Planned Tables (Future Phases)
```
customers
  mbi (unique), medicare_id, preferred_name, first_name, last_name
  dob, gender, phone_primary, phone_secondary, email
  address1, city, state, zip_code, county
  carrier_address (raw import, preserved separately)
  medicaid_level (Full/QMB/SLMB/QI/None)
  medicaid_id, pharmacy_id (FK)
  deal_stage (Lead/SOA_Sent/Appointed/Enrolled/Active/Termed)
  lead_source (pharmacy_referral/self_generated/referral/etc)
  notes, created_by, created_at, updated_at

customer_aor_history
  customer_id, agent_id, carrier, plan_name, plan_id
  effective_date, term_date (NULL=current)
  source (carrier_import/manual/medicare_center_pdf)

customer_contacts (POC — not always the patient)
  customer_id, name, relationship, phone, email
  is_primary_contact, notes

customer_notes (interaction log)
  customer_id, agent_id, note_text
  note_type (call/meeting/email/sms/general)
  meeting_summary (from Google Meet Workspace Events webhook via Claude API extraction)
  duration_minutes (for time tracking)
  created_at

customer_documents
  customer_id, agent_id, doc_type (SOA/enrollment_app/other)
  filename, storage_path
  ocr_extracted_data (JSON — from MedicareCenter PDF)
  signed_at, created_at

customer_tasks (action items)
  customer_id, agent_id, title, description
  due_date, priority (high/medium/low)
  status (open/in_progress/done)
  source (manual/ringcentral_missed_call/fireflies/inbound_email)
  created_at, completed_at

customer_tickets (servicing issues)
  customer_id, agent_id, issue_type, description
  status (open/in_progress/resolved)
  resolution_notes, created_at, resolved_at

pharmacies
  name, address1, city, state, zip_code, phone
  is_partner, rent_amount, rent_frequency
  contact_name, contact_phone, notes

carrier_plans (master reference — CMS Plan Finder API)
  carrier, plan_name, plan_id (H-number), plan_type
  snp_type (D-SNP/C-SNP/I-SNP/null)
  year, monthly_premium, annual_deductible, moop
  network_type (HMO/PPO/PFFS)
  service_counties (JSON), cms_star_rating, is_active

scope_of_appointments
  customer_id, agent_id, method, sent_at, signed_at
  topics_covered (JSON), stored_by (portal/medicarecenter/paper)
  medicarecenter_ref_id, valid_until

agent_licenses (NIPR integration)
  agent_id, state, license_number, license_type
  issued_date, expiration_date, status
  last_nipr_sync

carrier_contacts (rep directory)
  carrier, rep_name, role, phone, email, notes

agent_expenses (reimbursement tracking)
  agent_id, expense_type (stamps/AHIP/CE/etc)
  amount, description, receipt_url
  submitted_at, approved_at, paid_at
  approved_by (FK → users)
```

---

## 10. Commission Structure

### Split Rate by Year (Default)
2026: 55% → 2027: 57.5% → 2028: 60% → 2029: 62.5% → 2030: 65% → 2031: 67.5% → 2032+: 70% cap

Betty Marlowe: 52.5% — stored in agent_carrier_contracts.

### February 2026 Verified ✅
UHC $7,955.79 → $4,375.68 | Devoted $9,081.00 → $4,994.55 | Humana $1,509.18 → $830.05 | BCBS $635.79 → $349.68 | Aetna $202.44 → $111.34

---

## 11. Medicaid Levels (Reference)

| Level | Coverage | Plan Eligibility |
|---|---|---|
| Full Dual | Premiums + copays + deductibles covered | D-SNP eligible |
| QMB Only | Premiums + copays + deductibles covered | D-SNP eligible |
| SLMB | Part B premium only | Standard MAPD |
| QI | Partial Part B premium | Standard MAPD |
| None | Standard Medicare only | All plans |

C-SNP plans require specific chronic conditions (CHF, ESRD, diabetes, etc.) — reference table planned.

---

## 12. SOA (Scope of Appointment) Notes

- CMS requires SOA signed before discussing MA or Part D plans
- 48-hour rule: SOA must be signed 48hrs before scheduled appointment (with exceptions)
- Current workflow: paper, MedicareCenter SMS/email, or in-person
- MedicareCenter stores SOAs for required 10 years — portal should reference, not duplicate
- Portal goal: send CMS-compliant SOA, track signature, store reference ID

---

## 13. MedicareCenter Integration

- Primary enrollment platform for all agents
- After enrollment: agent downloads signed application PDF
- PDF contains: name, DOB, plan, carrier, effective date, agent NPN
- Portal goal: upload PDF → OCR extraction → auto-match to customer record
- PDFs are text-based (not scanned) — use pdfplumber, not Tesseract
- Creates/updates AOR history, sets deal stage to "Enrolled"

---

## 14. AEP Communication Stack (Tim's Proven System)

```
**Target stack (Phase 3):**
Missed call → Twilio routes to Retell AI
→ AI triage + books Calendly appointment mid-call (via Make.com)
→ Calendly sends confirmation + reminders natively
→ Appointment: agent taps [Start Recording] on portal → joins unique Google Meet space
→ Meet ends → Workspace Events webhook → Claude API extracts summary + action items
→ CustomerNote + CustomerTask created automatically
→ SendGrid fires post-appointment summary email to customer

**Previous manual stack (Tim only, now replaced):**
Missed call → RingCentral auto-reply SMS → Calendly booking link → ... → Fireflies records
```

Other agents had none of this during AEP. They worked 10-hour days back-to-back, missed calls, lost leads, customers felt ignored.

Portal communication hub will provision this stack for every agent automatically.

---

## 15. Current BOB Stats (Tim — March 2026)

UHC: 281 (52.4%) | Humana: 195 (36.4%) | BCBS: 27 (5.0%) | Devoted: 22 (4.1%) | Aetna: 10 (1.9%) | Healthspring: 3 (0.6%) | **Total: 538**

Agency demo data: ~5,479 total across all 8 agents.

---

## 16. Compensation Proposal (Pending AJ Conversation)

- **Ask:** $1,800/mo opening, $1,500/mo target, $1,200/mo floor
- **Structure:** $800 base + $600 platform fee + $22 E&O contribution
- **E&O:** Tim pays Level A ($400/yr) out of pocket; other agents get Level C ($265/yr) covered by Founders

---

## 17. Build Progress

### Completed ✅

**Phase 1 — Policy Reporting**
- [x] VPS, Nginx, Gunicorn, SSL, DNS
- [x] Google OAuth (Founders accounts only)
- [x] All 6 carrier BOB parsers
- [x] Single + bulk file upload (admin)
- [x] Agent dashboard (filtered by agent_id)
- [x] Admin overview with agent detail view
- [x] Birthday labels — Avery 5160 PDF
- [x] Commission audit — all 5 carriers, per-agent split rates, contract validation
- [x] Agent settings — carrier contracts, split rates, agent IDs
- [x] Founders logo in sidebar
- [x] ~5,479 seeded demo policies, commission data for all agents
- [x] All code on GitHub

**Phase 2 — Customer Master (completed 2026-03-20)**
- [x] Flask-Migrate (Alembic) initialized — all future schema changes tracked
- [x] `Pharmacy` model — partner pharmacies with rent tracking, contact info
- [x] `Customer` model — MBI-keyed master record, `humana_id`, `manually_edited` flag, `carrier_address`, `deal_stage`
- [x] `CustomerContact` model — POC contacts (not always the patient)
- [x] `CustomerNote` model — interaction log with note_type, source_url, integration FK fields
- [x] `CustomerAorHistory` model — per-carrier enrollment history with unique constraint
- [x] `_upsert_customer_from_policy()` in upload.py — called on every BOB import
- [x] `customers_bp` blueprint — list, profile, notes, contacts, pharmacy link, duplicates, merge
- [x] `pharmacies_bp` blueprint — admin CRUD for partner pharmacies
- [x] Sidebar updated — Customers + Pharmacies nav links
- [x] All 7 Phase 2 templates built
- [x] Obsidian vault created at ~/Founders-Portal/Founders-Portal-Vault/Founders Portal/

### Next Up 🔜 (Phase 3 — Communication Hub)

**Pre-code setup required first (Phase 2.5 must be complete before any of this):**
- [ ] Phase 2.5: PostgreSQL migration complete and verified
- [ ] Twilio account provisioned — TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN in .env
- [ ] Retell AI trial tested — call own number, evaluate quality
- [ ] HealthSherpa agency account active, captive join code distributed to LOA agents
- [ ] Google Workspace admin: Meet recording + transcription enabled for domain
- [ ] Add webhook URL: `https://portal.foundersinsuranceagency.com/comms/webhook/twilio`
  - Subscribe to: `call.completed`, `call.missed`, `message.received`, `message.sent`
  - Store signing secret as `OPENPHONE_WEBHOOK_SECRET`
- [ ] Test call to verify webhook fires before writing code

**Code (after Phase 2.5 and pre-code setup):**
- [ ] `Agency`, `Household`, `CustomerPhone`, `CallLog`, `SmsMessage`, `CustomerTask`, `UnmatchedCall`, `AgentLocation` models
- [ ] `calendly_booking_url` column on User model
- [ ] `app/openphone_client.py` — send_sms(), get_call_recording(), list_phone_numbers()
- [ ] `app/communications.py` blueprint — webhook handlers + SMS thread routes
- [ ] Calendly webhook — invitee.created → customer match → pre-call brief
- [ ] Google Meet Workspace Events webhook → transcript → CustomerNote + CustomerTask
- [ ] HealthSherpa enrollment webhook → upsert CustomerAorHistory
- [ ] Retell AI post-call webhook → CallLog + AI summary + action items
- [ ] HMAC signature verification on ALL webhook endpoints

### Roadmap (Phased)

**Phase 2.5 — PostgreSQL Migration** ← NEXT (hard gate before Phase 3)
- [ ] Install PostgreSQL on VPS, migrate all data, verify, update .env

**Phase 3 — Communication Hub** (after Phase 2.5 complete)
- [ ] Agency model + agency_id FK on all tables
- [ ] Twilio integration (call logs, SMS, missed call → CustomerTask)
- [ ] Retell AI post-call webhook → CallLog + AI summary + action items
- [ ] Google Meet unique-per-appointment + Workspace Events webhook → CustomerNote
- [ ] HealthSherpa enrollment webhook → CustomerAorHistory upsert
- [ ] Calendly booking webhook → customer match → pre-call brief
- [ ] SMS template library (AJ-approved, CMS-compliant)
- [ ] Unmatched call queue + resolution workflow
- [ ] Email campaign module (SendGrid, filtered recipient lists)
- [ ] Automated reminder sequences
- [ ] Replace Dropbox with Google Drive integration (already paid for)

**Phase 4 — Compliance + Operations**
- [ ] CMS-compliant campaign template library
- [ ] SOA e-signature (DocuSign or native)
- [ ] 10-year document storage
- [ ] Expense reimbursement tracking (stamps, AHIP, CE)
- [ ] Agent onboarding workflow + SOP documentation
- [ ] Out-of-state contracting requirements reference
- [ ] CE requirements + renewal tracking

**Phase 5 — Analytics**
- [ ] Commission forecast (Part D + supplement rates)
- [ ] AEP performance tracking per agent
- [ ] Retention rates by carrier/plan
- [ ] Churn risk scoring
- [ ] Lead source ROI (pharmacy referrals vs self-generated)
- [ ] Time spent prospecting vs servicing

**Phase 6 — Mobile + Customer Portal**
- [ ] PWA (Progressive Web App) — installs like native, no app store needed
- [ ] Customer portal (customers view their own plan info, book appointments)
- [ ] "Who's calling?" inbound phone lookup

**Phase 7 — White Label**
- [ ] Multi-tenant PostgreSQL architecture
- [ ] Custom branding per agency
- [ ] Stripe billing
- [ ] Onboarding wizard
- [ ] See PRODUCT_VISION.md

---

## 18. Important Notes

- **Carrier data is not the source of truth** — agents edit records, carrier data preserved separately
- **MBI is the cross-carrier key** — Humana masks it, use Humana ID there
- **BCBS Supplement term dates** = renewal dates, never disenrollments
- **Healthspring .xls** is HTML — parser sniffs automatically
- **UHC/BCBS sentinel dates** → NULL (2300-01-01, 12/31/2199)
- **Betty Marlowe** at 52.5% split — stored in agent_carrier_contracts
- **Commission upload validation** — rejects if no active contract for that carrier
- **Partner pharmacies** = warm leads via rent — explains commission cap
- **SOA compliance** — MedicareCenter handles 10-year storage, portal stores reference only
- **PDF OCR abandoned** — pdfplumber MedicareCenter scraping too memory-intensive; HealthSherpa webhooks replace it
- **Fireflies.ai ELIMINATED** — BAA requires $40/user/mo Enterprise; replaced by Google Meet native recording (Workspace Business Plus BAA already covers this)
- **Twilio confirmed** as telephony backbone (2026-03-24) — replaces RingCentral/OpenPhone/VOXO
- **Retell AI confirmed** as AI voice engine — HIPAA/SOC2, $0.07/min, books appointments mid-call
- **HealthSherpa** replaces MedicareCenter for enrollment data — webhook gives full payload for LOA agents (captive join), limited for AOR agents (independent join)
- **Multi-tenant Agency model from day one** — must land in PostgreSQL (Phase 2.5), never SQLite
- **Calendly** preferred over Acuity/Zoho Bookings for API integration — Phase 3
- **Make.com** is the automation platform — n8n not viable on 1GB VPS
- **Dropbox should be eliminated** — Google Drive already paid for by Workspace
- **No agency SOPs exist** — portal will eventually house onboarding + SOPs
- **No expense reimbursement system exists** — AJ/Brian cut checks in person
- **Amplicare/Enliven Health** — expensive, unreliable, used by some agents — replace with Medicare.gov API
- **Medicare.gov** — most CMS-compliant drug cost lookup, government takes blame if data wrong
- **Git:** Local Crostini is the dev machine. Commit and push from local. VPS pulls and runs `flask db upgrade`.
- **Flask-Migrate:** Always run `flask db upgrade` on VPS after any pull that touched models.py or migrations/
- **Obsidian vault:** ~/Founders-Portal/Founders-Portal-Vault/Founders Portal/ — living project docs
- **This Claude account** is the work account — keep all agency/portal work here
