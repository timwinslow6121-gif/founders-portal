# Founders Insurance Agency — Agent Portal
## Master Project Context Document
*Last updated: March 18, 2026*

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
7. **Birthday Labels** — Avery 5160 PDF emailed automatically on the 1st of each month
8. **CRM Integration** — matches carrier data to Zoho contacts by MBI
9. **Unmatched Policy Alerts** — policies in carrier BOBs not found in Zoho contacts
10. **Admin Control Panel** — AJ uploads carrier files, system handles the rest

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
- **Data processing:** pandas, openpyxl, lxml, reportlab
- **Email:** SendGrid (domain authenticated, foundersinsuranceagency.com verified)
- **Version control:** GitHub (private repo)

### Key File Paths on VPS
```
/var/www/founders-portal/          → app root
/var/www/founders-portal/.env      → secrets (not in GitHub)
/var/www/founders-portal/venv/     → Python virtual environment
/var/www/founders-portal/instance/ → SQLite database
/var/www/founders-portal/instance/uploads/ → temp upload dir (auto-cleaned)
/var/www/founders-portal/cron_labels.py → monthly labels cron script
/etc/nginx/sites-available/founders-portal → Nginx config
/etc/systemd/system/founders-portal.service → systemd service
/etc/letsencrypt/live/portal.foundersinsuranceagency.com/ → SSL certs
/var/log/founders-labels.log → cron job output log
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

# Check for errors
journalctl -u founders-portal -n 50 --no-pager | grep "Error\|File \"/var"

# Activate virtual environment
cd /var/www/founders-portal && source venv/bin/activate

# Deploy latest code from GitHub
cd /var/www/founders-portal && git pull origin main && systemctl restart founders-portal

# Check database tables
sqlite3 /var/www/founders-portal/instance/founders_portal.db ".tables"

# Check policy counts by carrier
sqlite3 /var/www/founders-portal/instance/founders_portal.db "SELECT carrier, count(*) FROM policies GROUP BY carrier;"

# Check cron jobs
crontab -l

# Manually run birthday labels cron (for testing)
/var/www/founders-portal/venv/bin/python3 /var/www/founders-portal/cron_labels.py
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

## 6. SendGrid (Email)

- **Provider:** Twilio SendGrid (free tier, 100 emails/day)
- **Domain authenticated:** foundersinsuranceagency.com (CNAME + TXT records in NixiHost)
- **From address:** tim@foundersinsuranceagency.com (verified sender)
- **Labels recipient:** tim+birthdays@foundersinsuranceagency.com
- **API key:** stored in /var/www/founders-portal/.env as SENDGRID_API_KEY
- **Config keys:** SENDGRID_API_KEY, LABELS_EMAIL, LABELS_FROM_EMAIL

---

## 7. GitHub Repository

- **Repo:** github.com/timwinslow6121-gif/founders-portal
- **Visibility:** Private
- **Clone URL:** git@github.com:timwinslow6121-gif/founders-portal.git

### Project Structure
```
founders-portal/
├── app/
│   ├── __init__.py          → Flask app factory
│   ├── extensions.py        → db and login_manager instances (avoids circular imports)
│   ├── auth.py              → Google OAuth login + user_loader
│   ├── routes.py            → page routes (dashboard)
│   ├── models.py            → User, Policy, ImportBatch, AuditLog
│   ├── upload.py            → file upload blueprint (single + bulk)
│   ├── labels.py            → birthday labels blueprint (PDF + SendGrid email)
│   ├── parsers/
│   │   ├── __init__.py      → parse_carrier_file() dispatcher
│   │   ├── uhc.py           → UHC XLSX parser (header row 2)
│   │   ├── humana.py        → Humana CSV parser
│   │   ├── aetna.py         → Aetna CSV parser
│   │   ├── bcbs.py          → BCBS CSV parser (MA + Supplement + Dental)
│   │   ├── devoted.py       → Devoted CSV parser (snake_case)
│   │   └── healthspring.py  → Healthspring HTML-disguised XLS parser
│   ├── templates/
│   │   ├── base.html        → full sidebar layout, design system
│   │   ├── login.html       → Google OAuth login page
│   │   ├── dashboard.html   → live agent dashboard
│   │   ├── upload.html      → bulk carrier file upload (admin only)
│   │   └── labels.html      → birthday labels page
│   └── static/
│       ├── css/style.css
│       └── js/main.js
├── cron_labels.py           → monthly cron script (runs outside Flask context)
├── config.py                → app configuration
├── requirements.txt         → Python dependencies
├── .env.example             → environment variables template
├── .env                     → secrets (NOT in GitHub)
├── .gitignore
├── wsgi.py                  → Gunicorn entry point
└── README.md
```

---

## 8. Carriers & File Formats

| Carrier | Format | Unique ID | Active Filter | Name Format | Address Fields |
|---|---|---|---|---|---|
| UHC | XLSX (header row 2) | mbiNumber (MBI) | Active-only export | memberFirstName / memberLastName | memberAddress1, memberCity, memberState, memberZip |
| Humana | CSV | Humana ID | Status == "Active Policy" | MbrFirstName / MbrLastName | Mail Address, Mail City, Mail State, Mail ZipCd |
| Aetna | CSV | Medicare Number (MBI) | Member Status == "A" | First Name / Last Name | TBD — confirmed on next upload |
| BCBS NC | CSV | Medicare Number (MA) / BCBSNC Member Number (Supp/Dental) | term_date > today | First Name / Last Name | Address 1, City, State, Zip |
| Devoted | CSV | member_id (UUID) | status == "ENROLLED" | first_name / last_name | TBD — confirmed on next upload |
| Healthspring | XLS (HTML) | Medicare Number (MBI) | Status == "Enrolled" | First Name / Last Name | TBD — confirmed on next upload |

### Key Notes
- **MBI** is the cross-carrier unique key — present on all carriers except Humana (masked)
- **Humana** MBI shows as `XXXXX12HN86` — use Humana ID as primary key instead
- **Healthspring** `.xls` file is actually HTML disguised — parser sniffs and handles automatically
- **BCBS** export includes MA, Medicare Supplement, AND Dental on same file
- **BCBS Supplement** term dates are renewal/anniversary dates, NOT real disenrollments — stored as `renewal_date`, never shown in terminations
- **Devoted** export is a raw API dump with snake_case column names and UUID member IDs
- **UHC** policyTermDate of `2300-01-01` = no real term date (sentinel) — stored as NULL
- **BCBS** termination date of `12/31/2199` = no real term date (sentinel) — stored as NULL
- **Auto-detection:** bulk upload sniffs carrier from column headers automatically

### Carrier Auto-Detection Logic
```
UHC:          mbiNumber column present
Humana:       MbrFirstName + Humana ID columns present
Aetna:        Medicare Number + Member Status columns present
BCBS:         BCBSNC Member Number column present
Devoted:      member_id + first_name + status columns present (snake_case)
Healthspring: Medicare Number + First Name columns present (or HTML table)
```

---

## 9. Database Schema

### Tables
- **users** — portal users (Google OAuth accounts)
- **policies** — normalized policy records from carrier BOB imports
- **import_batches** — tracks every file upload (carrier, filename, record counts, status)
- **audit_logs** — immutable action log

### Policy Model — Key Fields
```
carrier          — UHC / Humana / Aetna / BCBS / Devoted / Healthspring
member_id        — carrier's own ID (MBI for most, HumanaId for Humana, UUID for Devoted)
mbi              — Medicare Beneficiary ID (blank for Humana, UUID for Devoted)
first_name / last_name / full_name
dob              — date of birth
phone
county
address1 / city / state / zip_code   — mailing address (populated for UHC + Humana so far)
plan_name / plan_type
effective_date
term_date        — NULL means no term (sentinels converted to NULL)
renewal_date     — BCBS Supplement anniversary date (never shown as a termination)
status           — "active"
last_seen_date   — date of most recent import where record appeared
import_batch_id
zoho_matched     — NULL=unchecked, True=matched, False=unmatched
agent_id         — FK to users table (was NULL on all records, fixed with one-time UPDATE)
agent_id_carrier — agent ID as reported by carrier
```

---

## 10. Commission Structure

### Split Rate by Year
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

### Dashboard Commission Estimate Notes
- Current dashboard shows MAPD-only estimate at flat $28.91/month per policy
- Does NOT yet account for supplement/dental (% of premium) or Part D rates
- Does NOT yet account for HRA bonuses
- Full commission audit module will reconcile against actual AJ payment statements

---

## 11. Current BOB Stats (as of March 2026)

| Carrier | Active Clients | % of BOB |
|---|---|---|
| UnitedHealthcare | 281 | 52.4% |
| Humana | 195 | 36.4% |
| BCBS NC | 27 | 5.0% |
| Devoted Health | 22 | 4.1% |
| Aetna | 10 | 1.9% |
| Healthspring (Cigna) | 3 | 0.6% |
| **Total** | **538** | **100%** |

### BCBS Breakdown
- 23 Medicare Advantage
- 2 Medicare Supplement (David White, Gayle Canaday — MEDSUP G 2019)
- 2 Dental (Christopher Huff, Blanche Schwarz)
- 2 rows with blank Plan Type (Florence Stinson, Linda Redmond) — BCBS data quality issue

---

## 12. Compensation Proposal (Pending AJ Conversation)

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

---

## 13. Build Progress

### Completed ✅
- [x] VPS provisioned and secured
- [x] Ubuntu 22.04, Python, Nginx, Gunicorn, Git, sqlite3, lxml installed
- [x] Firewall configured
- [x] Flask application running as systemd service
- [x] SSL certificate (Let's Encrypt, auto-renews)
- [x] DNS subdomain live and propagated
- [x] Nginx upload size limit set to 52MB
- [x] Google OAuth login (Founders accounts only)
- [x] Domain restriction enforced
- [x] Admin detection by email
- [x] SQLite database initialized with correct schema
- [x] extensions.py (db + login_manager) — avoids circular import
- [x] user_loader registered in auth.py
- [x] Login page with Google sign-in button
- [x] Logout working
- [x] base.html — full sidebar layout with design system
- [x] All 6 carrier parsers ported to Python (UHC, Humana, Aetna, BCBS, Devoted, Healthspring)
- [x] Carrier auto-detection from file column headers
- [x] Single-file upload interface (admin only)
- [x] Bulk multi-file upload — select all 6 files at once, one click import
- [x] ImportBatch tracking (per-upload record with counts and error messages)
- [x] Policy upsert logic (carrier + member_id unique constraint)
- [x] AuditLog entries on every upload
- [x] BCBS supplement renewal_date handling (never shown as termination)
- [x] UHC/BCBS sentinel term dates converted to NULL
- [x] Address fields on Policy model (address1, city, state, zip_code)
- [x] Address populated for UHC and Humana parsers
- [x] Live agent dashboard with:
  - [x] Active policy count across all carriers
  - [x] Upcoming terminations (90-day window, color coded)
  - [x] Carrier breakdown with horizontal bar chart
  - [x] Commission estimate by carrier (MAPD flat rate, 55% split)
  - [x] Monthly + annual commission projection
- [x] Code on GitHub (private repo)
- [x] Birthday labels page (/birthday-labels)
  - [x] Month picker with live label counts per month
  - [x] Avery 5160 PDF generated with ReportLab (print-ready, no mail merge needed)
  - [x] SendGrid email integration (Twilio SendGrid, domain authenticated)
  - [x] Manual "Send Labels" button on page — one click, PDF arrives in email
  - [x] Monthly cron job (1st of month, 8am UTC) fires automatically for all agents
  - [x] Email lists skipped customers by name, carrier, DOB with fix instructions
  - [x] Deduplication by name + address + zip (one label per household)
  - [x] Missing address panel on page shows who will be skipped and why
- [x] SendGrid configured (API key in .env, domain authenticated via NixiHost DNS)
- [x] cron_labels.py — standalone cron script, runs outside Flask request context
- [x] All policies assigned to agent_id (one-time migration, were NULL)
- [x] reportlab + sendgrid installed in venv

### Next Up 🔜
- [ ] Push all VPS changes to GitHub (labels.py, labels.html, cron_labels.py, config.py)
- [ ] Add address fields to Aetna, Devoted, Healthspring parsers (need files)
- [ ] Upcoming terminations dedicated page (filter by urgency tier + carrier)
- [ ] Commission audit module (reconcile against AJ payment statements)
- [ ] Commission forecast calculator (with Part D + supplement rates)
- [ ] Churn history tracking
- [ ] Unmatched policies page (BOB vs Zoho contacts)
- [ ] Admin agency overview (all agents combined)
- [ ] Weekly cron job for automated audit
- [ ] Email summary after audit runs
- [ ] Mobile responsive styling
- [ ] Handoff documentation for AJ

---

## 14. Important Notes

- **Customers vs Contacts:** Customers = active policyholders being paid to service. Contacts = everyone (current, past, deceased, leads). Birthday cards go to **customers only**.
- **BCBS Supplement term dates** are renewal/anniversary dates — never real disenrollments. Stored as `renewal_date`, never shown in termination alerts.
- **Humana MBI:** Always masked (`XXXXX...`). Use Humana ID as primary key.
- **Healthspring file:** `.xls` extension but actually HTML. Parser sniffs and routes automatically.
- **BCBS export:** Includes MA, Supplement, and Dental on same file. All three are captured.
- **UHC export:** Has 2-row preamble before header. Parser uses `header=2`.
- **Devoted export:** snake_case column names, UUID member IDs, not MBIs.
- **Address fields:** Populated for UHC and Humana. Aetna/Devoted/Healthspring TBD when files are uploaded for inspection.
- **Commission estimate:** Dashboard shows MAPD-only flat rate. Does not yet account for supplement, dental, Part D, or HRA bonuses.
- **Google Workspace:** Business Plus, 8 agents, all have Founders emails. Only Founders emails allowed in portal. App passwords not available — use SendGrid for all outbound email.
- **extensions.py:** db and login_manager live here to avoid circular imports between __init__.py, models.py, and auth.py.
- **agent_id was NULL:** All policies imported before March 18 2026 had agent_id=NULL. Fixed with: `UPDATE policies SET agent_id = 1 WHERE agent_id IS NULL`. Future imports will set this correctly via the upload blueprint.
- **Birthday labels skipped customers:** Aetna and Devoted have no address fields yet (TBD on next file upload). BCBS Supplement members may not have addresses in carrier export. These show in the missing address panel on the labels page and are listed in the email.
- **This work account** is separate from personal Claude account. Keep agency/technical work here.
