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
- This distinction matters for client ownership tracking, agent departure scenarios, and the Brian cannibalization problem

---

## 3. The Portal — What We Are Building

A custom web-based agency management system hosted at:
**`https://portal.foundersinsuranceagency.com`**

### Purpose
- Each agent logs in with their Founders Google account and sees **only their own data**
- AJ has an **admin view** across all agents
- No spreadsheets, no manual work, no technical knowledge required from agents
- Replaces manual carrier data normalization that AJ currently does monthly

### Commission Flow (Critical Context)
- Carriers pay **Founders** directly — not individual agents
- AJ receives all commission statements for all agents from each carrier
- AJ calculates each agent's split and pays them (split varies per agent)
- Agents have NO direct access to raw carrier commission data — only AJ does
- Agents DO have access to their carrier BOB exports (policy lists)
- AJ sends each agent a filtered per-agent commission spreadsheet monthly
- Unknown whether AJ's files are raw carrier exports filtered per agent or reformatted — TBD

### MVP Features (Completed ✅)
1. **Carrier BOB Import** — auto-normalizes UHC, Humana, Aetna, BCBS, Devoted, Healthspring
2. **Per-Agent Dashboard** — active policies, upcoming terms, carrier breakdown, commission estimate
3. **Admin Overview** — AJ sees all agents, agency totals, clickable agent detail view
4. **Birthday Labels** — Avery 5160 PDF download, monthly preview, missing address alerts
5. **Commission Audit** — AJ uploads carrier statements, auto-detects carrier + agent, verifies split math per agent's actual rate
6. **Agent Settings** — AJ configures carrier contracts, split rates, agent IDs per agent

### Next Features (Post-MVP)
7. **Upcoming Terminations Page** — dedicated page with filters by urgency/carrier, CSV export
8. **Customer Master Database** — backbone linking MBIs → customers → agents across all carriers
9. **AOR Ownership Tracking** — full AOR history per customer, who owned them and when
10. **Cannibalization Detection** — flag when agent writes a customer already in Founders BOB (Brian problem)
11. **Clickable Customer Profiles** — from commission line items → customer profile page
12. **Inbound Call Routing** — customer calls → find their agent instantly
13. **Commission Forecast** — projects income with Part D + supplement rates
14. **Churn Risk Scoring** — tag high-risk customers, track churn by carrier/plan
15. **Granular Carrier/Plan Breakdown** — MAPD/PDP/Medigap → plan-level counts per agent
16. **Admin Master File Upload** — AJ uploads one file per carrier for all agents, system splits by agent
17. **Birthday Labels Email Cron** — auto-email PDF to each agent on 1st of month
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
- **Email:** SendGrid (Twilio, free tier, domain authenticated)
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

# Check policy counts by carrier
sqlite3 /var/www/founders-portal/instance/founders_portal.db "SELECT carrier, count(*) FROM policies GROUP BY carrier;"

# Check commission statements
sqlite3 /var/www/founders-portal/instance/founders_portal.db "SELECT carrier, gross_amount, expected_amount, paid_amount, status FROM commission_statements;"

# Check agent contracts
sqlite3 /var/www/founders-portal/instance/founders_portal.db "SELECT u.name, c.carrier, c.is_active, c.split_rate FROM agent_carrier_contracts c JOIN users u ON c.agent_id=u.id ORDER BY u.name, c.carrier;"
```

### Git Workflow — CRITICAL
**The VPS is the single source of truth. Always push from VPS, pull on Chromebook. Never commit from Chromebook.**

```bash
# On VPS (root@portal) — make changes, then:
git add <files>
git commit -m "message"
git push origin main

# On Chromebook (tim@penguin) — sync only:
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

- **Provider:** Twilio SendGrid (free tier, 100 emails/day)
- **Domain authenticated:** foundersinsuranceagency.com (CNAME + TXT in NixiHost DNS)
- **From address:** tim@foundersinsuranceagency.com
- **Labels recipient:** tim+birthdays@foundersinsuranceagency.com
- **API key:** stored in .env as SENDGRID_API_KEY
- **Config keys:** SENDGRID_API_KEY, LABELS_EMAIL, LABELS_FROM_EMAIL

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
│   ├── models.py                → User, Policy, ImportBatch, AuditLog, CommissionStatement, AgentCarrierContract
│   ├── upload.py                → carrier BOB file upload blueprint
│   ├── labels.py                → birthday labels blueprint (Avery 5160 PDF)
│   ├── agent_settings.py        → agent settings blueprint (carrier contracts, split rates)
│   ├── commission/
│   │   ├── __init__.py          → commission_bp Blueprint definition
│   │   ├── routes.py            → upload, parse, audit routes + all 5 carrier parsers
│   │   ├── audit.py             → placeholder (future detailed audit logic)
│   │   └── forecast.py          → placeholder (future commission forecast)
│   ├── parsers/
│   │   ├── __init__.py          → parse_carrier_file() dispatcher
│   │   ├── uhc.py               → UHC XLSX parser
│   │   ├── humana.py            → Humana CSV parser
│   │   ├── aetna.py             → Aetna CSV parser
│   │   ├── bcbs.py              → BCBS CSV parser
│   │   ├── devoted.py           → Devoted CSV parser
│   │   └── healthspring.py      → Healthspring HTML-XLS parser
│   └── templates/
│       ├── base.html            → sidebar layout, design system, Founders logo
│       ├── login.html           → Google OAuth login
│       ├── dashboard.html       → agent dashboard
│       ├── admin_overview.html  → agency overview (admin only)
│       ├── upload.html          → BOB file upload (admin only)
│       ├── labels.html          → birthday labels page
│       ├── commission.html      → commission audit page (redesigned)
│       ├── agent_settings.html  → agent settings overview (admin only)
│       └── agent_settings_detail.html → per-agent settings editor (admin only)
├── seed_agents.py               → seeds 7 fake agents + ~4,941 policies for demo
├── config.py                    → app configuration (reads from .env)
├── requirements.txt
├── .env / .env.example
├── wsgi.py                      → Gunicorn entry point
└── README.md
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
| Carrier | Agent Name Column | Agent Name Format | Split Row Pattern | Special Notes |
|---|---|---|---|---|
| UHC | Col B: Writing Agent Name | `WINSLOW, TIMOTHY JAMES` | `7955.79 x.55` → `4375.68` | HA payment bonuses in Commission Action col |
| Aetna | Col I: Writing Agent Name | `WINSLOW, TIMOTHY` | `202.44 x.55` → `111.34` | Clean format |
| Humana | Col B: WaName | `WINSLOW TIMOTHY J` | `$1,509.18 x. 55` → `830.05` | Chargebacks are negative — net ALL rows |
| BCBS | Col B: Agent Name | `TIMOTHY WINSLOW` | `$635.79 x.55` → `349.68` | Has =SUM() formula row, skip it |
| Devoted | Col C: Agent Name | `Timothy Winslow` | `$1,100 x.55` + `605 + 4,389.55 = $4,994.55` on same row | Bonus and paid total on same summary row |

### Key Parser Notes
- **Agent auto-detection:** normalizes name from file (handles LAST, FIRST / LAST FIRST INITIAL / First Last) and fuzzy-matches to User.name in DB
- **UHC gross:** includes HA bonus amounts (bonus is part of gross for split calculation)
- **Humana gross:** NET of all rows including chargebacks (negative values reduce gross)
- **Devoted paid:** extracted from col 3 `= $4,994.55` pattern on the bonus summary row
- **All carriers:** summary row with `gross x.55` pattern is at bottom of file
- **Discrepancy threshold:** < $0.02 = verified (floating point tolerance)
- **Contract validation:** upload rejected if agent has no active contract with that carrier
- **Split rate:** pulled from AgentCarrierContract per agent — not hardcoded

### Carrier Auto-Detection Logic (Commission files)
```
UHC:     "commission action" + "writing agent" in headers
Aetna:   "payee amount" + "sales event" in headers
Humana:  "commrundt" or "grpname" in headers
BCBS:    "billed amount" + "customer name" in headers
Devoted: "member hicn" or "agent npn" in headers
```

---

## 9. Database Schema

### Tables
- **users** — portal users (Google OAuth)
- **policies** — normalized BOB records from carrier imports
- **import_batches** — tracks every file upload
- **audit_logs** — immutable action log
- **commission_statements** — parsed commission data from AJ's uploads ✅
- **agent_carrier_contracts** — per-agent carrier contracts, split rates, agent IDs ✅

### Policy Model — Key Fields
```
carrier, member_id, mbi
first_name, last_name, full_name, dob, phone
address1, city, state, zip_code, county
plan_name, plan_type, effective_date, term_date, renewal_date
status ("active"), last_seen_date, import_batch_id
zoho_matched (NULL=unchecked, True=matched, False=unmatched)
agent_id (FK → users), agent_id_carrier
```

### CommissionStatement Model — Key Fields
```
carrier, statement_date, period_label ("February 2026")
agent_id (FK → users), uploaded_by_id (FK → users)
gross_amount     — total gross including bonuses
bonus_amount     — HA/HRA bonuses (tracked separately)
split_rate       — agent's actual split rate at time of upload
expected_amount  — gross × split_rate
paid_amount      — AJ's summary row amount
difference       — expected - paid (0.00 = verified)
status           — "verified" / "discrepancy" / "pending"
line_items       — JSON array of individual member rows
filename, upload_date
```

### AgentCarrierContract Model — Key Fields
```
agent_id (FK → users), carrier
is_active        — bool (False = upload rejected for this carrier)
split_rate       — e.g. 0.55 or 0.525 for Betty
id_type          — "NPN" / "writing_number" / "agent_code"
id_value         — actual ID string (e.g. "18708064" for Tim's NPN)
notes            — optional freeform notes
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

**Note:** Betty Marlowe is at 52.5% — stored in AgentCarrierContract, not the default schedule.

### CMS Commission Rates (2026)
- **MAPD:** $346.92/year ($28.91/month)
- **Part D:** ~$104/year ($8.67/month)
- **Supplements/Dental:** % of premium (varies — needs config table)

### February 2026 Commission — All Carriers Verified ✅
| Carrier | Gross | Split | Your Amount | Status |
|---|---|---|---|---|
| UHC | $7,955.79 | 55% | $4,375.68 | ✅ Verified |
| Devoted | $9,081.00* | 55% | $4,994.55 | ✅ Verified |
| Humana | $1,509.18 | 55% | $830.05 | ✅ Verified |
| BCBS | $635.79 | 55% | $349.68 | ✅ Verified |
| Aetna | $202.44 | 55% | $111.34 | ✅ Verified |

*Devoted: $7,981 base + $1,100 HRA bonuses (22 × $50)

---

## 11. Current BOB Stats (Tim — March 2026)

| Carrier | Active Clients | % of BOB |
|---|---|---|
| UnitedHealthcare | 281 | 52.4% |
| Humana | 195 | 36.4% |
| BCBS NC | 27 | 5.0% |
| Devoted Health | 22 | 4.1% |
| Aetna | 10 | 1.9% |
| Healthspring (Cigna) | 3 | 0.6% |
| **Total** | **538** | **100%** |

### Agency-Wide (seeded demo data)
- Total policies in DB: ~5,479
- Brian: ~1,100 | Rebekah: ~950 | Chris: ~751 | Justin: ~700
- Mike: ~530 | Betty: ~480 | Anjana: ~430 | Tim: 538 (real data)

---

## 12. Compensation Proposal (Pending AJ Conversation)

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

## 13. Build Progress

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
  - [x] Policy count, carrier breakdown, commission estimate
  - [x] Upcoming terminations (90d, color-coded urgency badges)
- [x] Admin overview (/admin)
  - [x] Agency KPIs, carrier breakdown, per-agent table
  - [x] Agent names clickable → agent detail view
  - [x] "Viewing as" banner when AJ views an agent
- [x] Birthday labels (/birthday-labels)
  - [x] Month picker with live label counts
  - [x] Avery 5160 PDF download (ReportLab, print-ready)
  - [x] Missing address panel, deduplication by household
- [x] Commission audit (/admin/commissions + /commissions)
  - [x] CommissionStatement model + DB table
  - [x] All 5 carrier parsers (UHC, Humana, Aetna, BCBS, Devoted)
  - [x] Auto-detects carrier from column headers
  - [x] Auto-detects agent by name matching (handles all name formats)
  - [x] Uses agent's actual split rate from AgentCarrierContract
  - [x] Rejects upload if agent has no active contract with that carrier
  - [x] Verified/discrepancy status with to-the-penny math
  - [x] Hero bar with total gross, split, paid, audit status
  - [x] Per-carrier status cards (green/red border)
  - [x] Line items table with per-member breakdown
  - [x] Admin view with agency-wide totals + Founders retains
- [x] Agent settings (/admin/agent-settings)
  - [x] AgentCarrierContract model + DB table
  - [x] Per-agent carrier contract toggles (8 carriers)
  - [x] Per-agent commission split rate
  - [x] Per-carrier agent ID type + value (NPN / writing_number / agent_code)
  - [x] Betty Marlowe seeded at 52.5%, Tim's NPN pre-filled
- [x] Founders logo in sidebar
- [x] All 8 agents seeded with realistic demo data (~5,479 policies)
- [x] All 8 agents seeded with carrier contracts
- [x] All 5 carriers seeded with fake commission data for demo
- [x] SendGrid configured (domain authenticated)
- [x] reportlab + sendgrid + openpyxl installed in venv
- [x] All code on GitHub

### Next Up 🔜
- [ ] Upcoming terminations dedicated page (filters by urgency + carrier, CSV export)
- [ ] Customer master database
  - [ ] `customers` table (MBI, name, DOB, phone, address)
  - [ ] `customer_aor_history` table (who owned them and when)
  - [ ] Clickable member names in commission line items → customer profile
  - [ ] Customer search across all agents (visible to all, owned by AOR)
- [ ] Fix Avery 5160 label alignment (test print needed)
- [ ] Show AJ the demo

### Roadmap (Post-MVP)
- [ ] AOR ownership tracking + cannibalization detection
- [ ] Inbound call routing reference
- [ ] Commission forecast (Part D + supplement rates)
- [ ] Churn risk scoring
- [ ] Granular carrier/plan breakdown admin view
- [ ] Admin master file upload (one per carrier for all agents)
- [ ] Birthday labels email cron (auto-email on 1st)
- [ ] Mobile responsive styling
- [ ] PostgreSQL migration
- [ ] Handoff docs for AJ

---

## 14. Important Notes

- **BCBS Supplement term dates** = renewal dates, never real disenrollments. Stored as `renewal_date`, never shown in termination alerts.
- **Humana MBI** always masked — use Humana ID as primary key.
- **Healthspring `.xls`** is actually HTML — parser sniffs and routes automatically.
- **UHC sentinel date** `2300-01-01` = no real term date → stored as NULL.
- **BCBS sentinel date** `12/31/2199` = no real term date → stored as NULL.
- **Address fields** populated for UHC + Humana only. Aetna/Devoted/Healthspring TBD.
- **Commission estimate** on dashboard = MAPD flat rate only. No supplement/dental/Part D yet.
- **agent_id was NULL** on all policies before March 18 2026. Fixed: `UPDATE policies SET agent_id = 1 WHERE agent_id IS NULL`.
- **Seeded agents** (Brian, Rebekah, Chris, Justin, Mike, Betty, Anjana) have fake policy data. Tim has real data.
- **admin@foundersinsuranceagency.com** = AJ's portal login. is_admin=True. Excluded from agent breakdown tables.
- **Betty Marlowe** is at 52.5% split — stored in agent_carrier_contracts, not the hardcoded default.
- **Commission upload validation** — checks AgentCarrierContract.is_active before saving. Rejects if no active contract.
- **Agent name normalization** — handles LAST, FIRST MIDDLE / LAST FIRST INITIAL / First Last formats across all 5 carriers.
- **Google Workspace app passwords** not available at domain level — use SendGrid for all outbound email.
- **extensions.py** holds db + login_manager to avoid circular imports.
- **Git:** VPS is source of truth. Push from VPS only. Pull on Chromebook only. Never commit from Chromebook.
- **Customer master database** — next major feature. MBI is the cross-carrier key. Will enable AOR history, cannibalization detection, call routing, and clickable customer profiles from commission line items.
- **This Claude account** is the work account — keep all agency/portal work here, separate from personal Claude.
