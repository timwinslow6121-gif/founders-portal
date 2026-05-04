# Founders Insurance Agency — Agent Portal

Flask CRM/portal for a Medicare insurance agency. 8 agents, ~5,500 policies across 6 carriers.

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
git pull && pip install -r requirements.txt && flask db upgrade && systemctl restart founders-portal
```

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
- `pharmacies.py` — partner pharmacy CRUD, admin-only (`pharmacies_bp`)
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
- **Lux Theme ✅** — All templates rethemed to The Private Gallery design system (2026-04-02). Dashboard rebuilt to original spec (activity-first: Unified Timeline, Tasks, Alerts, NC Enrollment Windows). Mobile-responsive with off-canvas sidebar drawer. labels.html intentionally kept in light-mode (print utility).
- **Commission Audit ✅ (2026-04-13)** — All 7 carriers now supported: UHC, Aetna, BCBS, Humana, Devoted, Healthspring, Wellable. Real March 2026 files uploaded and parsing correctly. See Commission Parser Notes below.
- **Commission override workflow ✅ (2026-04-13)** — Discrepancy → AJ submits explanation → agent accepts/disputes → AJ closes. stated_rate detection flags when AJ's formula rate contradicts contract rate.
- **BOB upload fixes ✅ (2026-04-29)** — Bulk upload now uses real form submit (flash messages work). Fixed agency_id/agent_id scoping in bulk_upload(). Fixed all PostgreSQL sequence drifts. Import history table: clickable rows open 3-tab detail modal (New / Updated / Not in this import = term report). Pending/error batches deletable with × button. _detect_carrier() now handles all 7 carriers as XLSX BOB files.

## Next Session Work Items (2026-05-04)
Discussed but NOT yet implemented — build in next session:

### Theme overhaul (HIGH PRIORITY)
Replace Lux dark theme with system-aware light/dark. See UX Design System section above for full spec. Touch base.html first (CSS vars), then all templates.

### Dashboard fixes
- Two metric bars are duplicated — merge into one bar
- Termination items and tasks in timeline must be clickable → customer profile
- Replace NC Enrollment Windows card with SEP info card (static, manually edited by admin)

### Customers page
- Sortable columns: name, stage, pharmacy
- Resizable columns: name, MBI, phone (CSS drag handles or click-to-resize)
- Column visibility picker: agent view hides Primary Agent; admin view shows it
  - Available columns: Name, MBI, DOB, Phone, Email, Address, Stage, Pharmacy, Carrier(s), Last Contact, Primary Agent (admin only)
- Duplicate detection: customers with same MBI or name+DOB should be flagged, one row per customer even with multiple policies
- CSV/Excel import for customer data (agents already have customer lists in spreadsheets)

### Upcoming Terminations page
- Simplify to next 30 days only (Medicare terms always hit on the 1st of the month)
- Remove 60/90 day tiers — not relevant outside AEP
- AEP gets its own dedicated page (future)

### Carriers & Plans database (new)
- New `Plan` model: carrier, plan_name, plan_type, year, service_area, premium, details_json
- New `carriers` blueprint with plan list + plan detail pages
- Plan detail shows: carrier, year, basic coverage info + "customers on this plan" list
- Customer profile links to their plan → plan detail page
- **Medicare.gov API** — investigate Plan Finder API (`data.medicare.gov`) for automated plan data
  - Applicable zip codes for Founders: western NC service area
  - Carriers in scope: UHC, Aetna, Healthspring/Cigna, BCBS-NC, Devoted, Wellable, GTL (supplemental)
  - GTL is life/supplemental (not Medicare Advantage) — handle separately

### Commission parser correction (CLAUDE.md note fix)
- Aetna col9 is Writing Agent Name (index 9, not 8) — already fixed in code, CLAUDE.md still says col8. Fix note.
- Aetna split_rate in DB is 0.55 (corrected from 0.525 — AJ's file was wrong). CLAUDE.md Commission Parser Notes still says 52.5% — fix that note too.

## Agent Nav — what's in the sidebar (as of 2026-04-03)
My Book: Dashboard, Customers, Upcoming Terms
Commissions: Commission Audit
Tools: Birthday Labels, Upload BOB Files, SMS Templates
Alerts: Unmatched Calls
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
- Aetna: agent=col9 (Writing Agent Name, index 9), amount=col10 (Payee Amount). Summary row scanned by `_scan_summary()`. **Split rate = 0.55 (55%)** — AJ's March file used 0.525 by mistake; contract rate is 55%.
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

## Session Protocol
At the end of every session, update the Build Status section of this file 
to reflect what was completed. Commit before closing. Do not leave decisions 
undocumented.