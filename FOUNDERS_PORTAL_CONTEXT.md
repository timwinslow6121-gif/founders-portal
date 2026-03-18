# Founders Insurance Agency — Agent Portal
## Master Project Context Document
*Last updated: March 17, 2026*

---

## 1. Who I Am

**Name:** Timothy Winslow  
**Role:** Writing Agent + Unofficial IT Director / CTO  
**Agency:** Founders Insurance Agency  
**Website:** www.foundersinsuranceagency.com  
**Email:** tim@foundersinsuranceagency.com  
**Personal GitHub:** timwinslow6121-gif  
**Personal email:** tim.winslow6121@gmail.com

I maintain the agency website, Google Workspace, Google Business page, RingCentral, and provide IT support + Medicare consulting for 8 agents. I am building a custom agency management portal to be compensated for this work.

---

## 2. The Agency

- **8 agents** total including myself
- **Principal agent / commission manager:** AJ (also a Google Workspace super admin)
- **All agents** have `@foundersinsuranceagency.com` Google Workspace Business Plus accounts
- **CRM:** Zoho One (I use it, other agents do not)
- **Phone:** RingCentral
- **Hosting:** NixiHost MiniShared ($60/yr) for the main website
- **Google Workspace:** Business Plus ($18/user/month)

---

## 3. The Portal — What We Are Building

A custom web-based agency management system hosted at:
**`https://portal.foundersinsuranceagency.com`**

### Purpose
- Each agent logs in with their Founders Google account and sees **only their own data**
- AJ has an **admin view** across all agents
- No spreadsheets, no manual work, no technical knowledge required from agents
- Replaces manual carrier data normalization that AJ currently does monthly

### Features Planned
1. **Carrier BOB Import** — auto-normalizes UHC, Humana, Aetna, BCBS, Devoted, Healthspring weekly
2. **Per-Agent Dashboard** — active policies, upcoming terms, unmatched alerts
3. **Commission Audit** — verifies AJ's split math per carrier, flags discrepancies to the penny
4. **Commission Forecast** — projects monthly/annual income based on current BOB + CMS rates
5. **Churn Tracking** — plan-level and customer-level churn with retention rates over time
6. **Upcoming Terminations** — members with real term dates in next 90 days, color coded
7. **Birthday Labels** — Avery 5160 mail labels for active customers by any month
8. **CRM Integration** — matches carrier data to Zoho contacts by MBI
9. **Unmatched Policy Alerts** — policies in carrier BOBs not found in Zoho contacts
10. **Admin Control Panel** — AJ uploads one file per carrier, system handles the rest

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
- **Registrar/Host:** NixiHost (same account as main website)
- **Main site:** foundersinsuranceagency.com (MiniShared hosting)
- **Portal subdomain:** portal.foundersinsuranceagency.com → A record → 23.187.248.100

### SSL
- **Provider:** Let's Encrypt (via Certbot)
- **Auto-renews:** Yes (Certbot systemd timer)
- **Expires:** June 15, 2026 (auto-renews before then)

### Stack
- **Language:** Python 3.10
- **Framework:** Flask 3.0
- **Database:** SQLite (instance/founders_portal.db) — upgrade to PostgreSQL later
- **Web server:** Nginx (reverse proxy) + Gunicorn (WSGI)
- **Auth:** Google OAuth 2.0 (restricted to @foundersinsuranceagency.com)
- **ORM:** Flask-SQLAlchemy
- **Data processing:** pandas, openpyxl
- **Version control:** GitHub (private repo)

### Key File Paths on VPS
```
/var/www/founders-portal/          → app root
/var/www/founders-portal/.env      → secrets (not in GitHub)
/var/www/founders-portal/venv/     → Python virtual environment
/var/www/founders-portal/instance/ → SQLite database
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

# Check app status
systemctl status founders-portal

# Activate virtual environment
cd /var/www/founders-portal && source venv/bin/activate

# Deploy latest code from GitHub
cd /var/www/founders-portal && git pull origin main && systemctl restart founders-portal
```

---

## 5. Google OAuth

- **Google Cloud Project:** Founders Portal
- **OAuth Consent Screen:** Internal (Workspace only)
- **Allowed domain:** foundersinsuranceagency.com
- **Client ID:** 991785142812-gnmh1rrhv7m8ujdo77p7g85t6sukbq5g.apps.googleusercontent.com
- **Client Secret:** stored in /var/www/founders-portal/.env
- **Redirect URI:** https://portal.foundersinsuranceagency.com/auth/callback
- **Admin emails:** tim@foundersinsuranceagency.com, aj@foundersinsuranceagency.com

---

## 6. GitHub Repository

- **Repo:** github.com/timwinslow6121-gif/founders-portal
- **Visibility:** Private
- **Clone URL:** git@github.com:timwinslow6121-gif/founders-portal.git

### Project Structure
```
founders-portal/
├── app/
│   ├── __init__.py          → Flask app factory
│   ├── auth.py              → Google OAuth login
│   ├── routes.py            → page routes
│   ├── models.py            → database models (User, Policy, AuditLog)
│   ├── parsers/
│   │   ├── uhc.py           → UHC BOB parser
│   │   ├── humana.py        → Humana parser
│   │   ├── aetna.py         → Aetna parser
│   │   ├── bcbs.py          → BCBS parser
│   │   ├── devoted.py       → Devoted parser
│   │   └── healthspring.py  → Healthspring parser (HTML-disguised XLS)
│   ├── commission/
│   │   ├── audit.py         → commission verification
│   │   └── forecast.py      → income forecasting
│   ├── templates/
│   │   ├── login.html       → Google OAuth login page
│   │   ├── dashboard.html   → agent dashboard (placeholder)
│   │   └── ...
│   └── static/
│       ├── css/style.css
│       └── js/main.js
├── parsers_test/
│   └── sample_files/        → test carrier files
├── config.py                → app configuration
├── requirements.txt         → Python dependencies
├── .env.example             → environment variables template
├── .env                     → secrets (NOT in GitHub)
├── .gitignore
├── wsgi.py                  → Gunicorn entry point
└── README.md
```

---

## 7. Carriers & File Formats

| Carrier | Format | Unique ID | Active Filter | Name Format |
|---|---|---|---|---|
| UHC | XLSX | mbiNumber (MBI) | Active only export | memberFirstName / memberLastName |
| Humana | CSV | Humana ID (MBI masked) | Active only export | MbrFirstName / MbrLastName |
| Aetna | CSV | Medicare Number (MBI) | Member Status = A | First Name / Last Name |
| BCBS NC | CSV | Medicare Number (MBI) | Filter future term date | First Name / Last Name |
| Devoted | CSV | member_id (UUID) | status = ENROLLED | first_name / last_name |
| Healthspring | XLS (HTML) | Medicare Number (MBI) | Status = Enrolled | First Name / Last Name |
| MedicareCenter | CSV | Policy Number (MC internal) | Status = ACTIVE | Policyholder Name (full) |
| Physicians Mutual | XLSX | Policy Number | All rows active | Policy Owner (full name) |
| GTL | PDF (commission stmt) | N/A | Skip — no BOB export | N/A |
| Wellabe | Low priority | TBD | TBD | TBD |

### Key Notes
- **MBI** is the cross-carrier unique key — present on all carriers except Humana (masked)
- **Humana** MBI shows as `XXXXX12HN86` — use Humana ID as primary key instead
- **Healthspring** `.xls` file is actually HTML disguised — must parse as HTML not Excel
- **BCBS** export includes historical termed records — filter by term date > today
- **Devoted** export is a raw API dump with snake_case column names and UUID member IDs
- **MedicareCenter** is supplemental only — has data quality issues, not source of truth

---

## 8. Commission Structure

### Your Split Rate by Year
| Year | Split |
|---|---|
| 2026 | 55% |
| 2027 | 57.5% |
| 2028 | 60% |
| 2029 | 62.5% |
| 2030 | 65% |
| 2031 | 67.5% |
| 2032+ | 70% (cap) |

### CMS Commission Rates (2026)
- **Medicare Advantage (MAPD):** $346.92/year ($28.91/month)
- **New enrollment:** $28.91 × months remaining in year (paid upfront)
- **Renewal:** $28.91/month flat
- **Part D (standalone):** ~$104/year ($8.67/month)
- **Supplements/HI/Dental:** % of premium (varies by carrier — needs config table)

### Commission Math Per Carrier (February 2026 — verified)
| Carrier | Gross | Split | Your Amount | Status |
|---|---|---|---|---|
| UHC | $7,955.79 | 55% | $4,375.68 | ✅ Verified |
| Devoted | $9,081.00* | 55% | $4,994.55 | ✅ Verified |
| Humana | $1,509.18 | 55% | $830.05 | ✅ Verified |
| BCBS | $635.79 | 55% | $349.68 | ✅ Verified |
| Aetna | $202.44 | 55% | $111.33 | ✅ Verified |

*Devoted gross = $7,981 base commissions + $1,100 HRA bonuses (22 × $50)

### HRA Bonuses (Devoted)
Devoted pays $50 per Health Risk Assessment completed. Track separately from base commissions.

### Chargeback Logic
If a member terms or changes plans mid-year: chargeback = $28.91 × months remaining.  
New enrollment mid-year: paid upfront = $28.91 × months remaining from effective date.

---

## 9. Zoho CRM Structure

### Modules
- **Contacts** — all contacts (current, past, leads, deceased). Field: `Medicare ID Number` = MBI
- **Leads** — prospects
- **Insurance Carriers** (custom) — carrier reference data
- **Insurance Plans** (custom) — available plan options per carrier
- **Plan Memberships** (custom) — active policies, links to Contact + Plan

### Key Zoho Field Names (Contacts module)
```
Record Id              → zcrm_ unique ID (use for upsert imports)
First Name
Middle Name
Last Name
Date of Birth
Gender
Mobile
Home Phone
Email
Mailing Street
AddressTwo
Mailing City
Mailing State
Mailing Zip
Mailing County
Medicare ID Number     → MBI (primary match key)
Medicaid ID
Medicaid /LIS Status
Pharmacy.id
Pharmacy
Spouse/Partner
Client Status          → Active Client / etc
```

### Matching Logic
- **Primary:** MBI (Medicare ID Number) — strictest, no false positives
- **Humana fallback:** Name + DOB (MBI is masked in their export)
- **Non-Medicare customers:** Name + DOB (dental/supplement, no MBI)

---

## 10. Current BOB Stats (as of Feb 2026)

| Carrier | Active Clients | % of BOB |
|---|---|---|
| UnitedHealthcare | 274 | 51.9% |
| Humana | 195 | 36.9% |
| BCBS NC | 24 | 4.5% |
| Devoted Health | 24 | 4.5% |
| Aetna | 8 | 1.5% |
| Healthspring (Cigna) | 3 | 0.6% |
| **Total** | **528** | **100%** |

---

## 11. Compensation Proposal (Pending AJ Conversation)

### Value Being Delivered (Market Rate)
| Role | Hours/mo | Rate | Monthly Value |
|---|---|---|---|
| IT Support | 10 | $75 | $750 |
| Website Admin | 4 | $75 | $300 |
| Medicare Consulting | 6 | $100 | $600 |
| Data & Reporting | 8 | $100 | $800 |
| Platform Development | 15 | $125 | $1,875 |
| Platform Maintenance | 5 | $100 | $500 |
| **Total** | **48** | | **$4,825/mo** |

### Asking For
- **Target:** $1,500/month retainer
- **Opening ask:** $1,800/month
- **Floor:** $1,200/month
- **Proposed structure:** $800 base + $600 platform fee + $22 E&O contribution

### E&O Insurance Issue
- Other agents: Level C, $265/year, Founders pays 100%
- Me: Level A, $400/year, currently paying $400 myself
- **Ask:** Founders contributes same $265 they pay for every other agent. I cover remaining $135.

### Proposal Document
Created as Word doc — `Founders_Agency_Value_Proposal.docx`

---

## 12. Build Progress

### Completed ✅
- [x] VPS provisioned and secured
- [x] Ubuntu 22.04, Python, Nginx, Gunicorn, Git installed
- [x] Firewall configured
- [x] Flask application running as systemd service
- [x] SSL certificate (Let's Encrypt, auto-renews)
- [x] DNS subdomain live and propagated
- [x] Google OAuth login (Founders accounts only)
- [x] Domain restriction enforced
- [x] Admin detection by email
- [x] SQLite database initialized
- [x] Login page with Google sign-in button
- [x] Logout working
- [x] Code on GitHub (private)

### Next Up 🔜
- [ ] Port all carrier parsers from Apps Script to Python
- [ ] File upload interface (AJ uploads carrier files)
- [ ] CURRENT_POLICIES database population
- [ ] BOB_Unmatched logic vs Zoho contacts export
- [ ] Upcoming terminations page
- [ ] Real agent dashboard with live data
- [ ] Commission audit module
- [ ] Commission forecast calculator
- [ ] Churn history tracking
- [ ] Birthday labels generator (Avery 5160)
- [ ] Admin view for AJ (all agents combined)
- [ ] Weekly cron job for automated audit
- [ ] Email summary after audit runs
- [ ] Mobile responsive styling
- [ ] Handoff documentation

---

## 13. Apps Script Reference

The original Google Apps Script (v7) is the reference implementation for all carrier parsers, commission audit logic, churn tracking, and BOB_Unmatched logic. When porting to Python, refer to that script for the exact column mappings, filter logic, and normalization rules.

Key file: `MasterEnrollmentAuditor.gs` (available in Claude conversation history)

---

## 14. Questions for AJ (Pending)

Before next build session, have this conversation with AJ:

1. What does your app actually do — walk me through it live
2. What did you build it with and where is it hosted
3. What still requires manual work each month
4. Are you open to expanding it or replacing it
5. Would the agency pay for a proper platform as a business expense
6. What is my contracted split rate for each carrier (confirm 55% across the board)
7. Is the Devoted split actually 55% or different
8. E&O contribution — $265/year same as every other agent

---

## 15. Important Notes

- **Customers vs Contacts:** Customers = active policyholders being paid to service. Contacts = everyone (current, past, deceased, leads). Birthday cards go to **customers only**.
- **CONTACTS sheet in Zoho:** Read-only reference. Script never writes to it.
- **MedicareCenter export:** Supplemental only. Has data quality issues. Not source of truth.
- **Humana MBI:** Always masked (`XXXXX...`). Use Humana ID as primary key.
- **Healthspring file:** `.xls` extension but actually HTML. Must parse with HTML parser not openpyxl.
- **BCBS export:** Includes termed records. Must filter by term date > today for active only.
- **Google Workspace:** Business Plus, 8 agents, all have Founders emails. Only Founders emails allowed in portal.
- **This work account** is separate from personal Claude account. Keep agency/technical work here.
