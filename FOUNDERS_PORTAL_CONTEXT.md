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

### Agent Roster
| Agent | Email | Type | Notes |
|---|---|---|---|
| Timothy Winslow | tim@foundersinsuranceagency.com | AOR | Owns BOB, portal admin |
| AJ (Admin) | admin@foundersinsuranceagency.com | Admin | Commission manager, portal admin |
| Brian Freeman | brian@foundersinsuranceagency.com | AOR/LOA | TBD — largest BOB (~1,100) |
| Rebekah Long | rebekah@foundersinsuranceagency.com | AOR | 2nd largest BOB (~950) |
| Chris Foster | chris@foundersinsuranceagency.com | AOR | ~750 policies |
| Justin Basinger | justin@foundersinsuranceagency.com | AOR | ~700 policies |
| Mike Lauzurique | mike@foundersinsuranceagency.com | LOA | ~530 policies, extension of Founders |
| Betty Marlowe | betty@foundersinsuranceagency.com | LOA | ~480 policies, extension of Founders |
| Anjana Patel | anjana@foundersinsuranceagency.com | LOA | ~430 policies, extension of Founders |

### AOR vs LOA Distinction
- **AOR agents** (Tim, Chris, Rebekah, possibly Brian) — own their BOB, commissions assigned to Founders temporarily. They own their clients.
- **LOA agents** (Mike, Betty, Anjana) — Founders owns the clients, agents are extensions of Founders. Relevant for client ownership tracking and agent departure scenarios.

---

## 3. The Portal — What We Are Building

A custom web-based agency management system hosted at:
**`https://portal.foundersinsuranceagency.com`**

### Purpose
- Each agent logs in with their Founders Google account and sees **only their own data**
- AJ has an **admin view** across all agents
- No spreadsheets, no manual work, no technical knowledge required from agents
- Replaces manual carrier data normalization that AJ currently does monthly

### Commission Flow (Important)
- Carriers pay **Founders** directly (not individual agents)
- AJ receives all commission statements for all agents from each carrier
- AJ calculates each agent's split (55% in 2026) and pays them
- Agents have NO direct access to carrier commission data — only AJ does
- Agents DO have access to their carrier BOB exports (policy lists)
- AJ sends each agent a filtered per-agent commission spreadsheet monthly

### Features — MVP (In Progress)
1. **Carrier BOB Import** ✅ — auto-normalizes UHC, Humana, Aetna, BCBS, Devoted, Healthspring
2. **Per-Agent Dashboard** ✅ — active policies, upcoming terms, carrier breakdown, commission estimate
3. **Admin Overview** ✅ — AJ sees all agents, agency totals, clickable agent detail view
4. **Birthday Labels** ✅ — Avery 5160 PDF download, monthly preview, missing address alerts
5. **Commission Audit** 🔜 — AJ uploads carrier statements, agents verify their split math
6. **Upcoming Terminations Page** 🔜 — dedicated page with filters by urgency/carrier

### Features — Roadmap (Post-MVP)
7. **Customer/MBI Master Database** — backbone linking MBIs to customers to agents across all carriers
8. **AOR Tracking** — who owns which customer, prevents cannibalization
9. **Inbound Call Routing Reference** — customer calls → find their agent instantly
10. **Commission Forecast** — projects monthly/annual income with Part D + supplement rates
11. **Churn Risk Scoring** — tag high-risk customers, track churn by carrier/plan
12. **Cannibalization Alerts** — flag when agent tries to write a customer already in Founders BOB (Brian problem)
13. **Granular Carrier/Plan Breakdown** — click carrier → see MAPD/PDP/Medigap breakdown → plan-level counts per agent
14. **Admin Agency Control Panel** — AJ uploads master carrier files, system splits by agent
15. **Birthday Labels Email Cron** — auto-email PDF to each agent on 1st of month
16. **CRM Integration** — Zoho match for Tim only
17. **Unmatched Policy Alerts** — BOB vs CRM discrepancies
18. **Mobile Responsive Styling**
19. **Handoff Documentation for AJ**

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
```

### Git Workflow — IMPORTANT
- **All code changes happen on the VPS**
- **Push from VPS only** (`root@portal`)
- **Pull on Chromebook only** (`tim@penguin`)
- Never commit from the Chromebook — causes diverged branch conflicts

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
- **Client Secret:** stored in /var/www/founders-portal/.env
- **Redirect URI:** https://portal.foundersinsuranceagency.com/auth/callback
- **Admin emails:** tim@foundersinsuranceagency.com, admin@foundersinsuranceagency.com

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
│   ├── routes.py            → dashboard, admin overview, agent detail view
│   ├── models.py            → User, Policy, ImportBatch, AuditLog, CommissionStatement (🔜)
│   ├── upload.py            → file upload blueprint (single + bulk)
│   ├── labels.py            → birthday labels blueprint (PDF download)
│   ├── commission.py        → commission audit blueprint (🔜 in progress)
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
│   │   ├── admin_overview.html → agency overview (admin only)
│   │   ├── upload.html      → bulk carrier file upload (admin only)
│   │   ├── labels.html      → birthday labels page
│   │   └── commission.html  → commission audit page (🔜 in progress)
│   └── static/
│       ├── css/style.css
│       └── js/main.js
├── seed_agents.py           → seeds fake agent data for demo/testing
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

### BOB Export Files (Agent access)
| Carrier | Format | Unique ID | Active Filter | Name Format | Address Fields |
|---|---|---|---|---|---|
| UHC | XLSX (header row 2) | mbiNumber (MBI) | Active-only export | memberFirstName / memberLastName | memberAddress1, memberCity, memberState, memberZip |
| Humana | CSV | Humana ID | Status == "Active Policy" | MbrFirstName / MbrLastName | Mail Address, Mail City, Mail State, Mail ZipCd |
| Aetna | CSV | Medicare Number (MBI) | Member Status == "A" | First Name / Last Name | TBD — confirmed on next upload |
| BCBS NC | CSV | Medicare Number (MA) / BCBSNC Member Number (Supp/Dental) | term_date > today | First Name / Last Name | Address 1, City, State, Zip |
| Devoted | CSV | member_id (UUID) | status == "ENROLLED" | first_name / last_name | TBD — confirmed on next upload |
| Healthspring | XLS (HTML) | Medicare Number (MBI) | Status == "Enrolled" | First Name / Last Name | TBD — confirmed on next upload |

### Commission Statement Files (AJ only)
| Carrier | Format | Key Columns | Action Types | Split Row Pattern |
|---|---|---|---|---|
| UHC | XLSX | Statement Date, Member Name, Commission Action, Commission | Renewal, New, HA payment | `7955.79 x.55` → `4375.68` |
| Aetna | XLSX | Payment Date, Member Name, Sales Event, Payee Amount | Renewal | `202.44 x.55` → `111.34` |
| Humana | XLSX | CommRunDt, GrpName, Comment, PaidAmount | Renewal, First Year, Med 2nd Half, Chargebacks (negative) | `$1,509.18 x. 55` → `830.05` |
| BCBS | XLSX | Agent #, Customer Name, Group Type, Commission | FY, RENEW | `$635.79 x.55` → `349.68` |
| Devoted | XLSX | Statement Date, Member First/Last, Period, Base Amount | All new/AEP | `$1,100 x.55` + base breakdown |
| Healthspring | N/A | 3 customers, all paid out for year upfront | N/A | N/A |

### Key Notes
- **MBI** is the cross-carrier unique key — present on all carriers except Humana (masked)
- **Humana** MBI shows as `XXXXX12HN86` — use Humana ID as primary key instead
- **Healthspring** `.xls` file is actually HTML disguised — parser sniffs and handles automatically
- **BCBS** export includes MA, Medicare Supplement, AND Dental on same file
- **BCBS Supplement** term dates are renewal/anniversary dates, NOT real disenrollments
- **Devoted** export is a raw API dump with snake_case column names and UUID member IDs
- **UHC** policyTermDate of `2300-01-01` = no real term date (sentinel) — stored as NULL
- **BCBS** termination date of `12/31/2199` = no real term date (sentinel) — stored as NULL
- **UHC HA payments** — Health Assessment bonuses embedded in Commission Action field as long string
- **Humana chargebacks** — negative PaidAmount values, track separately
- **Devoted HRA bonuses** — $50 per Health Risk Assessment, shown separately from base commissions
- **New enrollment commissions** — UHC shows NULL commission on New rows (paid in separate cycle)

---

## 9. Database Schema

### Tables
- **users** — portal users (Google OAuth accounts)
- **policies** — normalized policy records from carrier BOB imports
- **import_batches** — tracks every file upload (carrier, filename, record counts, status)
- **audit_logs** — immutable action log
- **commission_statements** — parsed commission data from AJ's carrier uploads (🔜)

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
agent_id         — FK to users table
agent_id_carrier — agent ID as reported by carrier
```

### CommissionStatement Model — Key Fields (🔜)
```
carrier           — UHC / Humana / Aetna / BCBS / Devoted
statement_date    — date on the statement
agent_id          — FK to users table
gross_amount      — total gross commissions from carrier
split_rate        — 0.55 (per year schedule)
expected_amount   — gross × split_rate (what agent should receive)
paid_amount       — what AJ's summary row shows as paid
bonus_amount      — HA/HRA bonuses (separate from base)
status            — verified / discrepancy / pending
line_items        — JSON array of individual member rows
upload_date
uploaded_by       — FK to users table (always AJ)
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
  - [x] Active policy count across all carriers (filtered by agent_id)
  - [x] Upcoming terminations (90-day window, color coded with urgency badges)
  - [x] Carrier breakdown with horizontal bar chart
  - [x] Commission estimate by carrier (MAPD flat rate, 55% split)
  - [x] Monthly + annual commission projection
- [x] Admin overview page (/admin)
  - [x] Agency-wide KPIs (total policies, terms, commission estimates)
  - [x] Carrier breakdown across all agents
  - [x] Per-agent table with share of book bar chart, urgency badges, top carriers
  - [x] Agent names clickable → agent detail view
- [x] Agent detail view (/admin/agent/<id>) — AJ views any agent's dashboard
- [x] "Viewing as" blue banner when AJ views an agent
- [x] Birthday labels page (/birthday-labels)
  - [x] Month picker with live label counts per month
  - [x] Avery 5160 PDF download (print-ready, no mail merge needed)
  - [x] Missing address panel shows who will be skipped and why
  - [x] Deduplication by name + address + zip
- [x] SendGrid configured (API key in .env, domain authenticated)
- [x] All 8 agents seeded with realistic fake data (~5,479 total policies)
- [x] All policies assigned to agent_id
- [x] reportlab + sendgrid installed in venv
- [x] Code on GitHub (private repo)

### Next Up 🔜
- [ ] Commission audit module (app/commission.py)
  - [ ] CommissionStatement model added to models.py
  - [ ] Admin upload page for carrier commission statements
  - [ ] Parsers for all 5 carriers (UHC, Humana, Aetna, BCBS, Devoted)
  - [ ] Per-agent audit view (expected vs paid, line items, discrepancy flags)
  - [ ] Admin view (all agents, ✅/❌ per carrier)
- [ ] Upcoming terminations dedicated page
  - [ ] Filter by urgency tier (< 30d / 30-60d / 60-90d)
  - [ ] Filter by carrier
  - [ ] Export to CSV
- [ ] Push all changes to GitHub after commission audit
- [ ] Update FOUNDERS_PORTAL_CONTEXT.md after commission audit

### Roadmap (Post-MVP)
- [ ] Customer/MBI master database
- [ ] AOR ownership tracking
- [ ] Cannibalization detection (Brian problem)
- [ ] Inbound call routing reference
- [ ] Commission forecast (Part D + supplement rates)
- [ ] Churn risk scoring and tagging
- [ ] Granular carrier/plan breakdown (admin)
- [ ] Birthday labels email cron (auto-email PDF on 1st of month)
- [ ] Admin master file upload (one file per carrier for all agents)
- [ ] Mobile responsive styling
- [ ] Handoff documentation for AJ
- [ ] PostgreSQL migration (when SQLite hits limits)

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
- **agent_id was NULL:** All policies imported before March 18 2026 had agent_id=NULL. Fixed with: `UPDATE policies SET agent_id = 1 WHERE agent_id IS NULL`. Future imports set this correctly via upload blueprint.
- **Seeded agents:** Brian, Rebekah, Chris, Justin, Mike, Betty, Anjana have fake policy data for demo. Tim has real data (538 policies).
- **admin@foundersinsuranceagency.com:** AJ's portal login. Has is_admin=True. Excluded from agent breakdown table (shows all other agents including Tim).
- **Git workflow:** VPS is source of truth. Push from VPS only. Pull on Chromebook only. Never commit from Chromebook.
- **This work account** is separate from personal Claude account. Keep agency/technical work here.
