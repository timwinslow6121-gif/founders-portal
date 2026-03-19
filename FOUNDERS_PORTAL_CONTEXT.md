# Founders Insurance Agency — Agent Portal
## Master Project Context Document
*Last updated: March 19, 2026*

---

## 1. Who I Am

**Name:** Timothy Winslow  
**Role:** Writing Agent + Unofficial IT Director / CTO  
**Agency:** Founders Insurance Agency  
**Website:** www.foundersinsuranceagency.com  
**Email:** tim@foundersinsuranceagency.com  
**Personal GitHub:** timwinslow6121-gif  
**Personal email:** tim.winslow6121@gmail.com

I maintain the agency website, Google Workspace, Google Business page, RingCentral, and provide IT support + Medicare consulting for 8 agents. I am building a custom agency management portal to be compensated for this work. Long-term this becomes a white-label SaaS product for Medicare insurance agencies — see PRODUCT_VISION.md.

---

## 2. The Agency

- **8 agents** total including myself
- **Principal agent / commission manager:** AJ (also a Google Workspace super admin)
- **All agents** have `@foundersinsuranceagency.com` Google Workspace Business Plus accounts
- **CRM:** Zoho One (Tim only — replacing with this portal)
- **Phone:** RingCentral (main agency number + per-agent extensions)
- **Enrollment platform:** MedicareCenter (primary) + carrier portals (fallback)
- **Scheduling:** Acuity (Tim) — moving to Calendly for API integration
- **Meeting AI:** Fireflies.ai (Tim only currently)
- **Hosting:** NixiHost MiniShared ($60/yr) for the main website
- **Google Workspace:** Business Plus ($18/user/month)

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
- Pharmacy performance tracking (leads generated) is a future feature
- This relationship explains the commission cap structure (55% → 70%) — rent payments come out of agency margin

---

## 3. The Portal — What We Are Building

A custom web-based agency management system hosted at:
**`https://portal.foundersinsuranceagency.com`**

### Purpose
This is being built as a **Medicare Agency Management System (MAMS)** — purpose-built for Medicare insurance agencies. It replaces Zoho CRM entirely for this use case and does things Zoho cannot:
- Commission audit with carrier-specific parsers
- AOR ownership history and cannibalization detection
- Carrier BOB normalization across 6 carriers
- Medicaid level tagging and plan eligibility logic
- Partner pharmacy relationship tracking
- SOA (Scope of Appointment) management
- MedicareCenter enrollment PDF OCR and customer matching

### Commission Flow (Critical Context)
- Carriers pay **Founders** directly — not individual agents
- AJ receives all commission statements for all agents from each carrier
- AJ calculates each agent's split (varies per agent) and pays them
- Agents have NO direct access to raw carrier commission data — only AJ does
- Agents DO have access to their carrier BOB exports (policy lists)
- AJ sends each agent a filtered per-agent commission spreadsheet monthly

### Data Philosophy — Carrier Data vs Agent Data
Carrier imports are a **starting point**, not the source of truth. The agent is the source of truth for their customers.

```
Carrier import → system checks MBI in customer master
  EXISTS → flag differences, agent reviews/accepts/rejects
  NEW    → create customer record from carrier data

Agent can always edit:
  - Preferred name (carrier has "SMITH, MARY J" → agent corrects to "Mary Smith")
  - Address (carrier has wrong zip → agent corrects it)
  - Point of Contact (may be daughter, nurse case manager, not the patient)
  - Pharmacy (tag their preferred pharmacy)
  - Medicaid level
  - Notes and interaction log

Carrier data preserved in original form.
Agent edits stored separately, displayed as authoritative.
Full audit trail: who changed what, when.
```

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
- **Database:** SQLite (`instance/founders_portal.db`) — upgrade to PostgreSQL later
- **Web server:** Nginx (reverse proxy) + Gunicorn (WSGI)
- **Auth:** Google OAuth 2.0 (restricted to @foundersinsuranceagency.com)
- **ORM:** Flask-SQLAlchemy
- **Data processing:** pandas, openpyxl, lxml, reportlab
- **Email:** SendGrid (Twilio, free tier → Essentials $20/mo for campaigns)
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
# SSH into VPS
ssh root@23.187.248.100

# Restart the app
systemctl restart founders-portal

# View live logs
journalctl -u founders-portal -f

# Check for errors
journalctl -u founders-portal -n 50 --no-pager | grep "Error\|File \"/var"

# Activate virtual environment
cd /var/www/founders-portal && source venv/bin/activate

# Check database tables
sqlite3 /var/www/founders-portal/instance/founders_portal.db ".tables"

# Check commission statements
sqlite3 /var/www/founders-portal/instance/founders_portal.db "SELECT carrier, gross_amount, expected_amount, paid_amount, status FROM commission_statements;"

# Check agent contracts
sqlite3 /var/www/founders-portal/instance/founders_portal.db "SELECT u.name, c.carrier, c.is_active, c.split_rate FROM agent_carrier_contracts c JOIN users u ON c.agent_id=u.id ORDER BY u.name, c.carrier;"
```

### Git Workflow — CRITICAL
**The VPS is the single source of truth. Always push from VPS, pull on Chromebook. Never commit from Chromebook.**

```bash
# On VPS (root@portal):
git add <files> && git commit -m "message" && git push origin main

# On Chromebook (tim@penguin):
cd ~/founders-portal && git pull origin main
```

---

## 5. Google OAuth

- **Google Cloud Project:** Founders Portal
- **OAuth Consent Screen:** Internal (Workspace only)
- **Allowed domain:** foundersinsuranceagency.com
- **Client ID:** 991785142812-gnmh1rrhv7m8ujdo77p7g85t6sukbq5g.apps.googleusercontent.com
- **Client Secret:** stored in .env
- **Redirect URI:** https://portal.foundersinsuranceagency.com/auth/callback
- **Admin emails:** tim@foundersinsuranceagency.com, admin@foundersinsuranceagency.com

---

## 6. SendGrid (Email)

- **Provider:** Twilio SendGrid (free tier → upgrade to Essentials for campaigns)
- **Domain authenticated:** foundersinsuranceagency.com (CNAME + TXT in NixiHost DNS)
- **From address:** tim@foundersinsuranceagency.com
- **Labels recipient:** tim+birthdays@foundersinsuranceagency.com
- **API key:** stored in .env as SENDGRID_API_KEY
- **Config keys:** SENDGRID_API_KEY, LABELS_EMAIL, LABELS_FROM_EMAIL
- **Future:** campaign module for mass email (50K emails/mo on Essentials at $20/mo)

---

## 7. GitHub Repository

- **Repo:** github.com/timwinslow6121-gif/founders-portal (Private)
- **Clone URL:** git@github.com:timwinslow6121-gif/founders-portal.git

### Project Structure
```
founders-portal/
├── app/
│   ├── __init__.py              → Flask app factory, blueprint registration
│   ├── extensions.py            → db + login_manager (avoids circular imports)
│   ├── auth.py                  → Google OAuth login + user_loader
│   ├── routes.py                → dashboard, admin overview, agent detail view
│   ├── models.py                → All database models
│   ├── upload.py                → carrier BOB file upload blueprint
│   ├── labels.py                → birthday labels blueprint (Avery 5160 PDF)
│   ├── agent_settings.py        → agent settings blueprint
│   ├── commission/
│   │   ├── __init__.py          → commission_bp Blueprint
│   │   ├── routes.py            → upload, parse, audit + all 5 carrier parsers
│   │   ├── audit.py             → placeholder
│   │   └── forecast.py          → placeholder
│   ├── parsers/
│   │   ├── __init__.py          → parse_carrier_file() dispatcher
│   │   ├── uhc.py / humana.py / aetna.py / bcbs.py / devoted.py / healthspring.py
│   └── templates/
│       ├── base.html            → sidebar layout, Founders logo
│       ├── login.html / dashboard.html / admin_overview.html
│       ├── upload.html / labels.html / commission.html
│       ├── agent_settings.html / agent_settings_detail.html
│       └── [future templates]
├── seed_agents.py               → seeds fake agents + policies for demo
├── config.py / requirements.txt / wsgi.py
└── .env / .env.example / .gitignore / README.md
```

---

## 8. Carriers & File Formats

### BOB Export Files (Agent access — already parsed)
| Carrier | Format | Unique ID | Active Filter | Address Fields |
|---|---|---|---|---|
| UHC | XLSX (header row 2) | mbiNumber | Active-only export | memberAddress1, memberCity, memberState, memberZip |
| Humana | CSV | Humana ID | Status == "Active Policy" | Mail Address, Mail City, Mail State, Mail ZipCd |
| Aetna | CSV | Medicare Number | Member Status == "A" | TBD |
| BCBS NC | CSV | Medicare/BCBSNC Number | term_date > today | Address 1, City, State, Zip |
| Devoted | CSV | member_id (UUID) | status == "ENROLLED" | TBD |
| Healthspring | XLS (HTML) | Medicare Number | Status == "Enrolled" | TBD |

### Commission Statement Files (AJ only — all 5 parsers complete ✅)
| Carrier | Agent Name Format | Split Row Pattern | Special Notes |
|---|---|---|---|
| UHC | `WINSLOW, TIMOTHY JAMES` | `7955.79 x.55` → `4375.68` | HA payment bonuses in Commission Action col |
| Aetna | `WINSLOW, TIMOTHY` | `202.44 x.55` → `111.34` | Clean format |
| Humana | `WINSLOW TIMOTHY J` | `$1,509.18 x. 55` → `830.05` | Chargebacks negative — net ALL rows |
| BCBS | `TIMOTHY WINSLOW` | `$635.79 x.55` → `349.68` | Has =SUM() formula row, skip it |
| Devoted | `Timothy Winslow` | `$1,100 x.55` + `605 + 4,389.55 = $4,994.55` on same row | Bonus and paid on same summary row |

### Key Parser Notes
- **Agent auto-detection:** normalizes name (handles all formats) and fuzzy-matches to User.name
- **UHC gross:** includes HA bonus amounts
- **Humana gross:** NET of all rows including chargebacks
- **Devoted paid:** extracted from `= $4,994.55` pattern on bonus summary row
- **Contract validation:** upload rejected if agent has no active contract with that carrier
- **Split rate:** pulled from AgentCarrierContract per agent — not hardcoded

---

## 9. Database Schema

### Current Tables
- **users** — portal users (Google OAuth)
- **policies** — normalized BOB records from carrier imports
- **import_batches** — tracks every file upload
- **audit_logs** — immutable action log
- **commission_statements** — parsed commission data ✅
- **agent_carrier_contracts** — per-agent carrier contracts, split rates, agent IDs ✅

### Planned Tables (Customer Master Database)
```
customers
  id, mbi (unique cross-carrier key), medicare_id
  first_name, last_name, preferred_name
  dob, gender
  phone_primary, phone_secondary
  email
  address1, city, state, zip_code, county
  carrier_address (raw from import, preserved)
  medicaid_level  (Full/QMB/SLMB/QI/None)
  medicaid_id
  pharmacy_id (FK → pharmacies)
  notes
  created_at, updated_at
  created_by (FK → users)

customer_aor_history
  id, customer_id (FK → customers)
  agent_id (FK → users)
  carrier, plan_name, plan_id
  effective_date, term_date (NULL = current)
  source ("carrier_import" / "manual" / "medicare_center_pdf")
  created_at

customer_contacts (POC — not always the patient)
  id, customer_id (FK → customers)
  name, relationship (daughter/son/nurse/power_of_attorney/etc)
  phone, email
  is_primary_contact (bool)
  notes

customer_notes (interaction log)
  id, customer_id, agent_id
  note_text, note_type (call/meeting/email/sms/general)
  meeting_summary (from Fireflies.ai webhook)
  created_at

customer_documents (SOA, enrollment apps, etc)
  id, customer_id, agent_id
  doc_type (SOA/enrollment_app/other)
  filename, storage_path
  ocr_extracted_data (JSON — from MedicareCenter PDF parsing)
  signed_at, signed_by
  created_at

pharmacies
  id, name, address1, city, state, zip_code, phone
  is_partner (bool — paying rent)
  rent_amount, rent_frequency
  contact_name, contact_phone
  notes
  created_at

carrier_plans (master reference — plan database)
  id, carrier, plan_name, plan_id (H-number)
  plan_type (MAPD/PDP/Supplement/Dental/SNP)
  snp_type (D-SNP/C-SNP/I-SNP/null)
  year
  monthly_premium, annual_deductible, moop
  network_type (HMO/PPO/PFFS)
  service_counties (JSON array)
  cms_star_rating
  is_active

scope_of_appointments (SOA tracking)
  id, customer_id, agent_id
  method (in_person/sms/email/medicarecenter)
  sent_at, signed_at
  topics_covered (JSON array — CMS required)
  stored_by (portal/medicarecenter/paper)
  medicarecenter_ref_id
  valid_until (signed_at + 48hrs for same-day, or scheduled appt date)
  created_at
```

### CommissionStatement Model — Key Fields
```
carrier, statement_date, period_label
agent_id, uploaded_by_id
gross_amount, bonus_amount, split_rate
expected_amount, paid_amount, difference
status (verified/discrepancy/pending)
line_items (JSON)
filename, upload_date
```

### AgentCarrierContract Model — Key Fields
```
agent_id, carrier
is_active (False = upload rejected)
split_rate (e.g. 0.55 or 0.525 for Betty)
id_type (NPN/writing_number/agent_code)
id_value (actual ID string)
notes
```

---

## 10. Commission Structure

### Split Rate by Year (Default Schedule)
| Year | Split |
|---|---|
| 2026 | 55% |
| 2027 | 57.5% |
| 2028 | 60% |
| 2029 | 62.5% |
| 2030 | 65% |
| 2031 | 67.5% |
| 2032+ | 70% (cap) |

**Note:** Betty Marlowe is at 52.5%. Split rates stored in AgentCarrierContract, not hardcoded.
**Note:** Commission cap exists partly because Founders pays rent to partner pharmacies for leads.

### CMS Commission Rates (2026)
- **MAPD:** $346.92/year ($28.91/month)
- **Part D:** ~$104/year ($8.67/month)
- **Supplements/Dental:** % of premium (varies — needs carrier_plans table)

### February 2026 Commission — All Carriers Verified ✅
| Carrier | Gross | Split | Your Amount | Status |
|---|---|---|---|---|
| UHC | $7,955.79 | 55% | $4,375.68 | ✅ Verified |
| Devoted | $9,081.00* | 55% | $4,994.55 | ✅ Verified |
| Humana | $1,509.18 | 55% | $830.05 | ✅ Verified |
| BCBS | $635.79 | 55% | $349.68 | ✅ Verified |
| Aetna | $202.44 | 55% | $111.34 | ✅ Verified |

---

## 11. Medicaid Levels (Important for Plan Eligibility)

| Level | Full Name | What It Means |
|---|---|---|
| Full Dual | Full Dual Eligible | Qualifies for D-SNP plans, premiums + copays covered by Medicaid |
| QMB | Qualified Medicare Beneficiary | Premiums, deductibles, and copays covered |
| SLMB | Specified Low-Income Medicare Beneficiary | Part B premium only covered |
| QI | Qualifying Individual | Partial Part B premium help |
| None | Standard Medicare | No Medicaid assistance |

- Must be tagged per customer in the portal
- Determines which plans a customer is eligible for
- D-SNP plans require Full Dual or QMB status
- Affects which carrier plans are appropriate recommendations

---

## 12. Scope of Appointment (SOA) Notes

**CMS requires a Scope of Appointment be signed before discussing Medicare Advantage or Part D plans.**

**The 48-hour rule:** SOA must be signed 48 hours before a scheduled appointment — unless it's an unscheduled walk-in or the beneficiary initiates contact.

**Reality on the ground:** The 48-hour rule is widely not followed because it actively prevents helping people who want help immediately. A 75-year-old who walks into the office shouldn't be turned away.

**Current workflow:**
- Paper SOA (most common)
- MedicareCenter SOA via SMS/email (stores for required 10 years)
- In-person signature at appointment

**Portal SOA goals:**
- Send CMS-compliant SOA via SMS or email from within the portal
- Track signature status
- Store signed SOAs for 10-year CMS requirement
- Link to customer record
- For MedicareCenter-handled SOAs: store the reference ID, don't duplicate storage

**Key point:** MedicareCenter already handles SOA storage compliantly. Portal should integrate with it, not replace it for compliance purposes.

---

## 13. MedicareCenter Integration

**MedicareCenter** is the primary enrollment platform. After submitting an enrollment:
- Agent can immediately download the signed application PDF
- PDF contains: customer name, DOB, plan selected, effective date, agent NPN

**Portal integration goals:**
- Agent uploads enrollment PDF to customer record
- OCR extracts: customer name, DOB, MBI/Medicare #, plan name, carrier, effective date
- System auto-matches to existing customer record (by MBI or name+DOB)
- Creates/updates AOR history record
- Tags deal stage: "Enrolled - Pending Effective Date"
- Sends automated confirmation to customer (future)

**OCR approach:** PyMuPDF (fitz) or pdfplumber for text extraction from MedicareCenter PDFs. These are text-based PDFs not scanned images, so true OCR (Tesseract) probably not needed — just PDF text extraction.

---

## 14. Communication Stack (AEP Automation)

**What Tim built for AEP 2025 that other agents didn't have:**

```
Customer calls Tim's RingCentral number (missed)
        ↓
Auto-reply SMS: "Sorry I missed you — book here: [Acuity link]"
        ↓
Customer books appointment via Acuity
        ↓
Acuity triggers:
  - Confirmation SMS + email to customer
  - Calendar invite to Tim's Google Calendar
  - Notification SMS/email to Tim
        ↓
Day before: reminder SMS + email to customer
1 hour before: reminder SMS + email to customer
        ↓
Appointment (Fireflies.ai records if virtual)
        ↓
Follow-up email: summary of what was discussed + next steps
```

**Other agents during AEP:** 10-hour days back-to-back, no auto-replies, customers felt ignored, leads fell through cracks.

**Portal communication hub goals (future):**
- Per-agent RingCentral extension configuration
- Auto-reply SMS template management
- Calendly integration (better API than Acuity, $10/mo per agent)
- Automated reminder sequences
- Fireflies.ai webhook → meeting summary → customer record
- SMS template library (CMS-compliant templates, AJ-approved)
- Email campaign module (SendGrid, filter by carrier/plan/renewal date/birthday)

---

## 15. Current BOB Stats (Tim — March 2026)

| Carrier | Active Clients | % of BOB |
|---|---|---|
| UnitedHealthcare | 281 | 52.4% |
| Humana | 195 | 36.4% |
| BCBS NC | 27 | 5.0% |
| Devoted Health | 22 | 4.1% |
| Aetna | 10 | 1.9% |
| Healthspring (Cigna) | 3 | 0.6% |
| **Total** | **538** | **100%** |

### Agency-Wide (seeded demo data ~5,479 total)
Brian: ~1,100 | Rebekah: ~950 | Chris: ~751 | Justin: ~700
Mike: ~530 | Betty: ~480 | Anjana: ~430 | Tim: 538 (real)

---

## 16. Compensation Proposal (Pending AJ Conversation)

### Asking For
- **Target:** $1,500/month retainer
- **Opening ask:** $1,800/month
- **Floor:** $1,200/month
- **Structure:** $800 base + $600 platform fee + $22 E&O contribution

### E&O Issue
- Other agents: Level C, $265/year — Founders pays 100%
- Tim: Level A, $400/year — currently paying out of pocket
- Ask: Founders contributes same $265 they pay for every other agent

---

## 17. Build Progress

### Completed ✅
- [x] VPS, Nginx, Gunicorn, SSL, DNS all live
- [x] Google OAuth (Founders accounts only, admin detection)
- [x] SQLite database, all models, Flask app factory
- [x] All 6 carrier BOB parsers (UHC, Humana, Aetna, BCBS, Devoted, Healthspring)
- [x] Carrier auto-detection from column headers
- [x] Single + bulk file upload interface (admin only)
- [x] Policy upsert logic (carrier + member_id unique constraint)
- [x] ImportBatch + AuditLog tracking
- [x] Agent dashboard (filtered by agent_id)
- [x] Admin overview with agency KPIs and agent detail view
- [x] Birthday labels — Avery 5160 PDF download
- [x] Commission audit — all 5 carriers, per-agent split rates, contract validation
- [x] Agent settings — carrier contracts, split rates, agent IDs
- [x] Founders logo in sidebar
- [x] All 8 agents seeded with demo data (~5,479 policies)
- [x] All code on GitHub

### Next Up 🔜
- [ ] Upcoming terminations dedicated page
- [ ] Customer master database (MBI linking, basic profile, editable records)
- [ ] Customer POC (point of contact — not always the patient)
- [ ] Pharmacy master list + customer tagging
- [ ] Medicaid level tagging per customer
- [ ] MedicareCenter PDF upload + OCR extraction → customer matching
- [ ] Customer profile page (full view)
- [ ] Clickable member names in commission line items → customer profile

### Roadmap (Post-MVP)
- [ ] Carrier plan master database (H-numbers, plan types, Medicaid eligibility)
- [ ] SOA tracking and sending (CMS-compliant)
- [ ] AOR ownership history + cannibalization detection
- [ ] Deal stage tracking (Lead/SOA Sent/Enrolled/Effective/Termed)
- [ ] Communication hub (RingCentral SMS, email campaigns, auto-replies)
- [ ] Calendly integration per agent
- [ ] Fireflies.ai webhook → meeting summaries → customer records
- [ ] Commission forecast (Part D + supplement rates)
- [ ] Churn risk scoring
- [ ] Inbound call routing ("who's calling?" lookup by phone number)
- [ ] Admin master file upload (one per carrier for all agents)
- [ ] Birthday labels email cron
- [ ] Mobile responsive styling
- [ ] PostgreSQL migration
- [ ] White-label packaging (see PRODUCT_VISION.md)

---

## 18. Important Notes

- **Carrier data is not the source of truth** — agents edit and correct customer records, carrier data preserved in original form
- **MBI is the cross-carrier unique key** — except Humana (masked), use Humana ID there
- **BCBS Supplement term dates** = renewal dates, never real disenrollments
- **Healthspring `.xls`** is actually HTML — parser sniffs automatically
- **UHC/BCBS sentinel dates** converted to NULL (2300-01-01 and 12/31/2199)
- **Address fields** populated for UHC + Humana only so far
- **Commission estimate** on dashboard = MAPD flat rate only, no supplement/dental/Part D yet
- **Betty Marlowe** is at 52.5% split — stored in agent_carrier_contracts
- **Commission upload validation** — checks AgentCarrierContract.is_active before saving
- **Partner pharmacies** = warm leads in exchange for agency rent payments — explains commission cap
- **SOA compliance** — MedicareCenter handles 10-year storage, portal should reference not duplicate
- **MedicareCenter PDFs** are text-based not scanned — use pdfplumber for extraction, not Tesseract
- **Fireflies.ai** is already in Tim's workflow — webhook integration planned for customer records
- **Calendly** preferred over Acuity for portal integration (better API)
- **SendGrid Essentials** ($20/mo) needed for email campaigns — free tier (100/day) fine for transactional
- **Git:** VPS is source of truth. Push from VPS only. Pull on Chromebook only
- **This Claude account** is the work account — keep all agency/portal work here
