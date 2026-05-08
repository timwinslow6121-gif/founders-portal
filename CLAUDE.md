# Founders Insurance Agency — Agent Portal

Flask CRM/portal for a Medicare insurance agency. 8 agents, 524 real policies across 5 carriers (UHC 287, Humana 196, BCBS 28, Aetna 11, Healthspring 2). 510 customers (25 shell customers deleted 2026-05-08). All seeded/fake data deleted 2026-05-07.

## Stack
- Python 3.10, Flask 3.0, Flask-SQLAlchemy, Flask-Migrate (Alembic)
- **PostgreSQL 16** (Phase 2.5 complete — production database on VPS)
- Nginx + Gunicorn on Ubuntu VPS (23.187.248.100)
- Google OAuth 2.0 — restricted to @foundersinsuranceagency.com
- Vanilla JS only — no React/Vue. Jinja2 templates extending base.html.
- SendGrid for email, **Quo (formerly OpenPhone)** (primary VoIP) + **Retell AI** (missed call AI callbacks via Twilio SIP) + **Twilio** (SIP trunk for Retell AI + SMS blasts)

## Git Workflow
Local Crostini is the dev machine. Commit and push from local. VPS pulls.
```
git add <files> && git commit -m "message" && git push origin main
```
VPS deployment after pull:
```
cd /var/www/founders-portal && git pull && ./venv/bin/pip install -r requirements.txt && flask db upgrade && systemctl restart founders-portal
```
- VPS Python scripts: `./venv/bin/python3 scripts/myscript.py` (never plain `python3`)
- SSH: `ssh -i /home/timothywinslowlinux/.ssh/id_ed25519 root@23.187.248.100`

## BOB Parser Architecture (app/parsers/)

One file per carrier. Called via `parse_carrier_file(carrier, filepath)` from `app/parsers/__init__.py`.

**Detection** (`_detect_carrier()` in upload.py): scans up to 15 rows to find the real header row (carriers have preamble rows before headers). Checks first 2 bytes for `<` to detect HTML-disguised-as-XLS.

**Per-carrier format notes (portal BOB downloads, not commission files):**
- UHC: XLSX, 2-row preamble, header=2. Columns: mbiNumber, memberFirstName, memberLastName, memberAddress1, memberCity, memberZip, memberState, dateOfBirth, memberPhone, product, planName, memberCounty, policyEffectiveDate, policyTermDate (sentinel: 2300-01-01), agentId. Fingerprint: `mbinumber` + `memberfirstname`.
- Healthspring: TWO formats from same portal — (1) XLSX: 12-row preamble, header=12. (2) XLS: HTML-disguised, header=0, parse with read_html(). Both have identical columns: First Name, Last Name, Medicare Number, Member ID, Effective Date, Disenroll Effective Date, Date of Birth, Phone Number, Residential Address/City/State/Zip, Status, Product. Fingerprint: `medicare number` + `first name` + `disenroll effective date`.
- Humana: MBI not provided in BOB — matched by humana_id. `mbi` stored as empty string `""`. 196 Humana policies currently have mbi="" (not NULL) — do not add unique constraint on mbi without handling this first.
- Devoted: member_id is the Devoted member ID (not a UUID). Old seeded data used UUIDs — deleted 2026-05-07.

**Policy dedup logic (bulk_upload in upload.py):**
1. Match by carrier + member_id
2. Fallback: match by carrier + mbi (handles format changes where member_id differs between exports). On MBI match, adopt the new member_id as authoritative.

**One-time backfill scripts** live in `scripts/`. Run with `./venv/bin/python3 scripts/name.py` on VPS.

## Blueprint Registration Pattern
All blueprints registered in `app/__init__.py` with this exact 3-line pattern:
```python
from app.customers import customers_bp
app.register_blueprint(customers_bp)
```

## Current Blueprints
- `routes.py` — dashboard, admin overview, agent detail (no blueprint, registered directly)
- `auth.py` — Google OAuth
- `upload.py` — BOB import (agents + admins); commission statements (admin only via commission/)
- `labels.py` — birthday labels PDF
- `agent_settings.py` — carrier contracts, splits (admin-only)
- `commission/` — audit (admin + agent views)
- `customers.py` — customer list, profile, notes, contacts, merge (`customers_bp`)
- `pharmacies.py` — partner pharmacy CRUD + analytics (`pharmacies_bp`); admin-only add/edit
- `carriers.py` — plan database, plan detail, admin add/edit (`carriers_bp`)
- `comms/` — Quo/Twilio/Calendly webhooks, SMS, unmatched call resolution (`comms_bp`)

## Database Rules — READ BEFORE TOUCHING models.py OR upload.py

**Customer matching in _upsert_customer_from_policy() (upload.py):**
1. Match by MBI first (all carriers except Humana)
2. Humana: match by `humana_id`, then name+DOB+zip (ALL THREE must match)
3. If `customer.manually_edited == True`: do NOT overwrite phone, address, city, state, zip. Only update `carrier_address` and `last_carrier_sync`.
4. BCBS: `end_date` in CustomerAorHistory always set to None — BCBS term_date is a renewal date, not a termination.

**UHC/BCBS sentinel dates** (2300-01-01, 12/31/2199) must be treated as NULL.

**Betty Marlowe** has a 52.5% split (not 55%) — stored in `agent_carrier_contracts`.

**Flask-Migrate:** Every schema change requires a migration. Never use `db.create_all()` in production.

**Multi-tenant requirement (Phase 2.5+):** Every table gets `agency_id` FK (non-nullable). Every query MUST be scoped: `Customer.query.filter_by(agency_id=current_user.agency_id, ...)`. Missing agency_id = data leak across tenants.

**agency_id scoping sweep complete (Plan 03-07, 2026-04-03):** All Customer, Policy, CommissionStatement, CustomerNote, CustomerAorHistory, AgentCarrierContract, ImportBatch queries are now scoped. `_upsert_customer_from_policy()` takes explicit `agency_id` param — do NOT use `current_user` inside it. No new migration was needed — DB columns already existed from Phase 2.5; Plan 07 added ORM column definitions to models.py.

**BOB upload access:** `/upload` is open to all agents (not admin-only). Agent uploads attribute policies to `current_user.id` automatically. Admin uploads leave `agent_id` unset (matched later via carrier file). Agents see only their own import history; admins see all.

**commission_statements.agency_id:** Column was missing from DB — added manually via ALTER TABLE on 2026-04-13, migration 005 stamps this. If deploying fresh, `flask db upgrade` will apply it correctly.

**PostgreSQL sequence drift:** After bulk inserts or manual SQL, sequences can fall behind max(id). Fix with: `SELECT setval('tablename_id_seq', (SELECT MAX(id) FROM tablename));` — has affected `commission_statements` and `agent_carrier_contracts` in production.

## UX Design System — NEW THEME (replacing Lux dark theme, 2026-05-04)

**Decision: Replace dark mode entirely with system-aware light/dark theme.**
Use CSS `prefers-color-scheme` media query so the OS setting drives the palette automatically — no toggle needed, no DB preference stored.

### Light mode palette (default / `prefers-color-scheme: light`)
- Background: `#F5F4F2`, Surface: `#FFFFFF`, Surface-Low: `#EEEDEB`
- Text: `#1A1917` (ink), Secondary: `#6B6760` (slate)
- Gold accent: `#B8975A` (darker for contrast on light bg)
- Border: `rgba(26,25,23,0.10)`
- Status: error=`#C0392B`, progress=`#B8860B`, resolved=`#2E7D32`, waiting=`#5C4DB1`

### Dark mode palette (`prefers-color-scheme: dark`)
- Keep existing Lux palette: Ink `#0A0A09`, Surface `#131312`, Surface-Low `#1C1C1A`, Gold `#DAC495`, Ivory `#E5E2DF`
- Border: `rgba(76,70,61,0.18)`

### Shared design tokens
- **Fonts:** Noto Serif (headlines/metrics) + Inter (UI/body) — unchanged
- **Border-radius:** 6px (replacing 0px — softer, more approachable)
- **Padding:** cards get `20px 24px` (was `14px 16px`) — more breathing room
- **220px sidebar**, uppercase nav items — unchanged
- CSS vars defined in `base.html :root` with `@media (prefers-color-scheme: dark)` override block

### Implementation rules
- All color values must use CSS vars (`var(--bg)`, `var(--surface)`, etc.) — no hardcoded hex in templates
- `{% block styles %}` per-template CSS must also use vars only
- **`labels.html` exception:** Keep light-mode print colors hardcoded — do not use vars
- **Google button stays `#fff`** regardless of theme (Google brand guidelines)
- **`login.html`** — update to use vars; left panel uses `var(--surface)`, right uses `var(--bg)`
- Class names unchanged: `.card`, `.data-table`, `.btn-primary`, `.btn-secondary`, `.badge`, `.nav-item`
- Status badges keep muted jewel tone concept but adapt per palette

## Build Status
- **Phase 1 ✅** — BOB parsers (6 carriers), commission audit, agent dashboard, admin overview, birthday labels
- **Phase 2 ✅** — Customer master: Pharmacy, Customer, CustomerContact, CustomerNote, CustomerAorHistory models; customers_bp + pharmacies_bp blueprints; all 7 templates
- **Phase 2.5 ✅** — PostgreSQL 16 on VPS; Agency multi-tenant model; 2GB swap; Gunicorn gthread; 5,589 rows migrated; UAT passed 7/7; login page redesigned (dark glassmorphic, Inter font)
- **Phase 3 ✅ DEPLOYED (2026-04-13)** — Plans 01-07 complete and live on VPS. OAuth login fixed (https force + scope relaxation). Plan 06 still blocked on external provisioning (HealthSherpa + Google Meet Pub/Sub).
- **Commission Audit ✅ (2026-04-13)** — All 7 carriers now supported: UHC, Aetna, BCBS, Humana, Devoted, Healthspring, Wellable. Real March 2026 files uploaded and parsing correctly. See Commission Parser Notes below.
- **Commission override workflow ✅ (2026-04-13)** — Discrepancy → AJ submits explanation → agent accepts/disputes → AJ closes. stated_rate detection flags when AJ's formula rate contradicts contract rate.
- **BOB upload fixes ✅ (2026-04-29)** — Bulk upload now uses real form submit (flash messages work). Fixed agency_id/agent_id scoping in bulk_upload(). Fixed all PostgreSQL sequence drifts. Import history table: clickable rows open 3-tab detail modal (New / Updated / Not in this import = term report). Pending/error batches deletable with × button. _detect_carrier() now handles all 7 carriers as XLSX BOB files.
- **System-aware theme ✅ (2026-05-04)** — Replaced Lux dark-only theme with dual-palette system using `prefers-color-scheme`. Light mode default (#F5F4F2 bg, #FFFFFF surface, #B8975A gold); dark mode preserves Lux palette. All templates swept — hardcoded rgba() replaced with `color-mix(in srgb, var(--token) N%, transparent)`. Border-radius 6px, larger card padding, base font 14px. labels.html untouched (print utility).
- **Readability pass ✅ (2026-05-04)** — Font sizes bumped (9px→11px, 10px→12px, 11px→13px across all templates). All card-like containers (metric cards, panels, carrier cards, commission cards, drop zones) now have border + border-radius + real gap (12–16px, was 2px). Fixed duplicate Unmatched Calls nav item.
- **Dashboard fixes ✅ (2026-05-04)** — Removed duplicate period-banner (same data as metric cards). Termination items in timeline, tasks, and alerts panels now link to customer profile (MBI→customer_id resolved in route). NC Enrollment Windows → SEP Quick Reference with accurate May 2026 status.
- **Customers page enhancements ✅ (2026-05-04)** — Sortable columns (name, stage, pharmacy) via sort=/dir= URL params, server-side order_by. Column visibility picker dropdown (MBI, Phone, Agent, Stage, Pharmacy); prefs in localStorage. Agent column hidden by default for non-admins. Pager carries sort params.
- **Terminations redesign ✅ (2026-05-04)** — Rebuilt around priority (high/low/death) not urgency tiers. 30-day window only. New Policy columns: term_reason, new_carrier, new_plan_name (migration 007). Inline AJAX reason editor per row. Member names link to customer profile via MBI→customer_id lookup. Death rows show condolences nudge.
- **Pharmacy enhancements ✅ (2026-05-05)** — Fixed agency_id NOT NULL bug on pharmacy insert (500 error). Added pharmacy_agents many-to-many join table (migration 008). Pharmacy list: agent count chip on main row, 2-col expand (agents+customers left, policies by carrier+agent right as proper table). Agent location assignment moved to Agent Settings as multi-checkbox (migration 010+011 added then dropped primary_pharmacy_id in favour of pharmacy_agents). Pharmacy.agents has backref User.pharmacies.
- **Carriers & Plans database ✅ (2026-05-05)** — New Plan model (migration 009): per-plan-per-year records with CMS plan ID, plan letter (Medigap), lifecycle status (current/legacy/sunset/discontinued), self-referential successor chain, D-SNP/C-SNP/5-star flags, benefits snapshot, commission rates (initial/renewal/true-up/HRA bonus), BOB alias matching. carriers_bp registered. Plan list (filtered by year/carrier/type/status, carrier group headers), plan detail (chain visualization, member count, commission highlights, matched active policies), admin add/edit form. 34 plans seeded from BOB/commission data across 6 carriers. Humana chain 137→291→335 linked. Commission rates updated to real 2025/2026 CMS max broker rates (NC = "all other states"): MAPD 2026 $57.83/$28.92 PMPM, MAPD 2025 $52.17/$26.08, PDP 2026 $9.50/$4.75. Legacy/sunset plans (Humana 137, 291) left at placeholder rates — historical data to be added later.
- **Policy commission_type ✅ (2026-05-06)** — Migration 012 adds `commission_type` VARCHAR(16) nullable to policies. Values: NULL=unknown, 'initial'=first-ever MA enrollment, 'renewal'=all else. Customer profile: inline dropdown per policy row, saves via AJAX to POST /policy/set-commission-type. Commission audit: line items enriched via MBI→Policy lookup; Comm Type column shows Initial/Renewal badge in detail table.
- **Payment Ledger ✅ (2026-05-06)** — Migration 013: `policy_payments` table — one row per member per statement. `app/commission/payments.py`: per-carrier extractors for all 7 carriers + 3-tier match logic (exact MBI → carrier ID → fuzzy name). Populated on every commission statement upload. Routes: `/commissions/ledger` (agent) + `/admin/commissions/ledger` (admin with agent selector tabs). UI: period/carrier/type filters, summary cards (members paid, total, chargebacks, net, unmatched count), match confidence dots (green=MBI/ID, amber=name, red=unmatched), carrier group headers, chargeback rows in red.
- **Agent AOR Visibility ✅ (2026-05-06)** — Agents see only current AOR customers by default. Toggle to show former customers (read-only). Former-AOR banner on profile. All write operations (notes, contacts, SMS, pharmacy) blocked for non-current-AOR agents. BOB upload closes previous agent's open AOR history row on ownership transfer. `_customer_query(include_former)` + `_is_current_aor()` helpers in customers.py.
- **AOR history backfill ✅ (2026-05-06)** — `scripts/backfill_aor_end_dates.py` closes stale open AOR rows where stored agent ≠ customer.primary_agent_id. Found 0 stale rows on first run (data was clean).
- **BOB parser fixes ✅ (2026-05-07)** — UHC and Healthspring parsers rewritten for actual portal download formats. _detect_carrier() now scans up to 15 rows (was 1) and handles HTML-XLS files. Policy dedup falls back to MBI match when member_id differs between import formats.
- **Data cleanup ✅ (2026-05-07)** — Deleted 4,941 seeded policies and 26 Devoted UUID policies. Real dataset: 524 policies (all with MBI or humana_id), 535 customers.
- **Phase 4 — Data Integrity + Reconciliation ✅ DEPLOYED (2026-05-08)** — Migration 014: Humana mbi=''→NULL backfill (196 policies + 2 BCBS outliers), partial unique index `WHERE mbi IS NOT NULL` on customers.mbi, `unresolvable_json` column on import_batches. 25 shell customers (no MBI/humana_id/dependents) hard-deleted — 510 customers remain. MBI duplicate detection + side-by-side merge UI with single-transaction AOR-safe migration. Unresolvable BOB quarantine tab (4th tab in import modal with inline assign/MBI/create resolution). BOB↔Commission reconciliation page (members in BOB not paid + payments not in BOB, per carrier+period). Per-customer Payment History section on customer profile.
- **UI Polish ✅ (2026-05-07)** — Enhanced base.html with subtle CSS micro-animations, glassmorphism on sidebars (backdrop-filter), and depth effects via hover states for cards, buttons, and nav items without changing the core layout.

## Next Steps / To-Do

### Phase 5 — Operations (NEXT — start fresh session)

Time logging, service tickets, lead source tracking, MedicareCenter PDF OCR, SOP hub.

Key items:
- Agent time log per customer interaction (minutes + activity type) from customer profile
- Service tickets (open/close/resolve) linked to customers
- Lead source field on customers for downstream analytics
- MedicareCenter enrollment PDF auto-parse into customer records
- SOP knowledge base (searchable)

### Future / backlog
- **Termination outcome tracker** — log of every termed policy since Jan 1, outcome (saved/converted/moved/deceased/fraud), contact history, ties to customer profile
- **AEP page** — dedicated AEP enrollment window tracker (separate from upcoming terminations)
- **Carriers & Plans** — customer profile → plan detail page link (match by carrier+plan_name)
- **Plan commission rates** — update seeded plans with real 2026 CMS rates per carrier (placeholders: $22 initial / $15 renewal MAPD, 20% Medigap, $3 PDP)
- **Medicare.gov API** — annual plan refresh script for western NC zip codes during AEP prep (`data.cms.gov`, no auth required)

## Agent Nav — what's in the sidebar (as of 2026-05-08)
My Book: Dashboard, Customers, Duplicates (count badge, hidden when 0), Upcoming Terms
Commissions: Commission Audit, Payment Ledger, Reconciliation
Tools: Birthday Labels, Upload BOB Files, Carriers & Plans, SMS Templates
Alerts: Unmatched Calls

Admin nav additionally shows: Agency Overview, Agent Settings, Partner Pharmacies
**/forecast is NOT implemented** — do not add it to nav until the route exists.

## Phase 3.06 External Blockers (as of 2026-04-02)
- **HealthSherpa** — Agency admin account created, awaiting provisioning email from HealthSherpa. Use agency account (not individual agent). Once provisioned: register webhook URL + get HEALTHSHERPA_WEBHOOK_SECRET.
- **Google Meet Pub/Sub** — Tim is Google Workspace admin. Needs: Meet recording + transcription enabled for domain, Pub/Sub topic + subscription created, GOOGLE_APPLICATION_CREDENTIALS service account on VPS, GOOGLE_MEET_PUBSUB_SUBSCRIPTION in .env.
- Code for 3.06 can be written now; services just need to be registered once accounts are active.

## Phase 2.5 Pre-Code Checklist ✅ COMPLETE (2026-03-26)
- [x] Install PostgreSQL on VPS
- [x] Create `founders_portal` database + user
- [x] Update `config.py` DATABASE_URL
- [x] Run `flask db upgrade` — verify clean migration
- [x] Verify all data (commissions, policies, customers) present in PostgreSQL
- [x] Update `.env` with new DATABASE_URL
- [x] Add 2GB swap file to VPS
- [x] Update Gunicorn: `--workers 2 --threads 4 --worker-class gthread`
- [x] Remove SQLite from `requirements.txt`

## VPS Deployment Gotcha
- Always use `./venv/bin/pip install -r requirements.txt` on VPS — plain `pip install` installs to system Python, causing ModuleNotFoundError on startup
- Deploy command: `cd /var/www/founders-portal && git pull && ./venv/bin/pip install -r requirements.txt && flask db upgrade && systemctl restart founders-portal`

## VPS-Only State (not in git)
- `.env` on VPS has `SECRET_KEY`, `DATABASE_URL` (PostgreSQL), `ADMIN_EMAILS=admin@foundersinsuranceagency.com` — never commit
- `app/templates/base.html` on VPS had an extra `{% endif %}` (fixed 2026-03-26 during UAT) — local copy and VPS are now in sync
- Admin login: `admin@foundersinsuranceagency.com` (shared AJ+Tim). Agent test login: `tim@foundersinsuranceagency.com`
- `is_admin` is recalculated from `ADMIN_EMAILS` on every OAuth login — DB value gets overwritten
- `OAUTHLIB_RELAX_TOKEN_SCOPE=1` set in auth.py — required because Google Cloud OAuth app has Meet/Pub/Sub scopes configured, causing scope mismatch on basic login flow

## Phase 3 Pre-Code Checklist
- [x] Quo (OpenPhone) account provisioned — QUO_WEBHOOK_SIGNING_KEY + QUO_API_KEY in .env
- [x] Quo webhook URL registered: `https://portal.foundersinsuranceagency.com/comms/webhook/quo`
- [x] Retell AI configured with Twilio SIP trunking
- [x] Twilio account SID + auth token in .env
- [x] Calendly webhook active — CALENDLY_WEBHOOK_SECRET in .env
- [ ] HealthSherpa agency account — created, awaiting provisioning. Register webhook once active. Add HEALTHSHERPA_WEBHOOK_SECRET to .env.
- [ ] Google Meet: enable recording + transcription in Workspace admin, create Pub/Sub topic/subscription, add service account credentials to VPS, add GOOGLE_MEET_PUBSUB_SUBSCRIPTION to .env
- [ ] Distribute HealthSherpa captive join code to LOA agents once provisioned

## Commission Parser Notes (app/commission/routes.py)

Parsers are keyed by carrier name. Detection via `_detect_carrier()` fingerprints column headers. Agent matching via `_detect_agent_id()` + `_normalize_name()`.

**Column indices per carrier (verified against March 2026 files):**
- UHC: agent=col1, action=col4, commission=col5. Gross summary row: `'$N x.55'` in col4 (skip). Paid row: `'$N + $N'` pattern in col4, paid value in col5.
- Aetna: **CSV format** — col0: Payment Date, col1: Medicare Number (MBI), col4: Member Name, col6: Sales Event (action), col9: Plan ID, col12: Coverage Period, col16: Writing Agent Name, col20: Payee Amount. Summary row scanned by `_scan_summary()`. **Split rate = 0.55 (55%)** — AJ's March file used 0.525 by mistake; contract rate is 55%.
- Humana: agent=col2, amount=col8 (PaidAmount). No separate paid row — Humana pays Tim directly, `paid = gross`. **Split rate = 1.0** in `agent_carrier_contracts` for Tim.
- BCBS: agent=col1, commission=col13. Summary row: `'$N x .55'` in col9, paid in col10.
- Devoted: agent=col2, amount=col11 (Base Amount). Summary row: `'N x .55'` in col8, paid in col9. Statement date is string `MM/DD/YYYY` in col0.
- Healthspring: agent=col3, amount=col7. Summary row: `'N x.55'` in col6, paid in col7.
- Wellable: agent=col3, advance_amount=col16. Summary row: `'$N x .55'` in col16, paid in col17. All line items flagged `is_advance=True` — clawback risk badge shown in UI.

**Split rates in agent_carrier_contracts (Tim, agent_id=1):**
- Aetna: 0.55 (55%) — corrected from 0.525; AJ's March file was wrong
- Humana: 1.0 (direct pay — no agency redistribution)
- All others: 0.55 (55%)

**Known UHC behavior:** UHC sometimes pays gross×55% + separate HA bonus in a single disbursement. This shows as a discrepancy of the HA bonus amount — this is expected and should be reviewed, not auto-resolved.

**Wellable advance commissions:** 1st-year advances are clawback-eligible if policy lapses within advance period. Flagged with orange "Advance" badge and warning banner in commission detail view. Do not treat as verified income.

## Key Files
- `FOUNDERS_PORTAL_CONTEXT.md` — full project context, agent roster, carrier details, roadmap
- `PRODUCT_VISION.md` — white-label SaaS vision
- `app/models.py` — all models
- `app/upload.py` — BOB import logic + `_upsert_customer_from_policy()`
- `.env` — secrets (not in git): GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SECRET_KEY, SENDGRID_API_KEY

## Color Token Reference (IMPORTANT — avoid light mode invisible text bugs)
In the dual-palette theme, token meanings flip between modes:
- `--ink` = **background** color (light grey in light, near-black in dark) — DO NOT use for text
- `--ivory` = **readable body text** (dark in light mode, light in dark mode) — use for text
- `--slate` = secondary/muted text (same role in both modes)
- `--gold` = accent color (darker in light, lighter in dark)
- `--surface` = card/panel background
- `--surface-low` = slightly recessed surface
- **Rule:** Any `color:` property for text must use `var(--ivory)` or `var(--slate)`, never `var(--ink)`.

## Session Protocol
At the end of every session (or after any push), update CLAUDE.md to reflect
what was completed. Commit the update. Do not leave decisions undocumented.