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

## UX Design System — The Private Gallery (Lux Theme)
- **Palette:** Ink `#0A0A09` bg, Surface `#131312`, Surface-Low `#1C1C1A`, Gold `#DAC495`, Ivory `#E5E2DF`
- **No borders** — depth via tonal background shifts only. Ghost border fallback: `rgba(76,70,61,0.15)`
- **No border-radius** — all elements 0px (sharp, architectural)
- **Fonts:** Noto Serif (headlines/serif moments) + Inter (UI labels/body). Both loaded via Google Fonts in base.html.
- **Typography pattern:** labels `9-10px, uppercase, letter-spacing: 0.15-0.2em`. Serif numbers for metrics.
- **220px sidebar** (`var(--surface-low)`), uppercase nav items, thin 1px vertical rule dots
- CSS lives in `{% block styles %}` per template — no separate CSS files. CSS vars defined in base.html `:root`.
- Templates must NOT redefine `.page-title`, `.alert-*`, `.badge`, `.btn-primary`, `.btn-secondary`, `.card`, `.data-table` — these are owned by base.html. Override only if genuinely necessary.
- Class names: `.card`, `.data-table`, `.btn-primary`, `.btn-secondary`, `.badge`, `.nav-item` — same names, Lux styling
- **Mobile:** Sidebar is off-canvas drawer on ≤768px — `sidebar.open` class + `sidebar-overlay` backdrop. Hamburger + `mobile-topbar` in base.html. JS: `openSidebar()` / `closeSidebar()`.
- **Tables on mobile:** Wrap in `<div class="table-scroll">` — applies `overflow-x: auto` and sets `min-width` on the table. Already in base.html styles.
- **Mobile cards:** Customer list and search results render as `.cust-card` stacked list on ≤768px instead of table. Pattern reusable for other list views.
- **`--border` token:** `rgba(76,70,61,0.18)` — use this instead of raw rgba for consistent tonal borders. Defined in base.html `:root`.
- **`labels.html` exception:** Birthday labels template uses light-mode colors intentionally — white background/dark ink for print output. Do not Lux-theme it.
- **Google button stays white:** `login.html` Google OAuth button must remain `#fff` per Google brand guidelines regardless of Lux theme.
- **Stitch reference files:** `Founder_Portal_Lux_Design/*.html` — HTML mockups for each major view. `founders-portal-responsive.html` has the full mobile pattern reference.
- Status badges use muted jewel tones: error=`#FFB4AB`, progress=`#C9A84C`, resolved=`#8A9A5B`, waiting=`#9D8DF1`
- **Login page** extends its own split-screen layout (no base.html). Left: serif hero on `#131312`. Right: Google button on `#0A0A09`.
- Design reference: `stitch_founders_portal_lux.zip` — The Private Gallery spec

## Build Status
- **Phase 1 ✅** — BOB parsers (6 carriers), commission audit, agent dashboard, admin overview, birthday labels
- **Phase 2 ✅** — Customer master: Pharmacy, Customer, CustomerContact, CustomerNote, CustomerAorHistory models; customers_bp + pharmacies_bp blueprints; all 7 templates
- **Phase 2.5 ✅** — PostgreSQL 16 on VPS; Agency multi-tenant model; 2GB swap; Gunicorn gthread; 5,589 rows migrated; UAT passed 7/7; login page redesigned (dark glassmorphic, Inter font)
- **Phase 3 ✅ DEPLOYED (2026-04-13)** — Plans 01-07 complete and live on VPS. OAuth login fixed (https force + scope relaxation). Plan 06 still blocked on external provisioning (HealthSherpa + Google Meet Pub/Sub).
- **Lux Theme ✅** — All templates rethemed to The Private Gallery design system (2026-04-02). Dashboard rebuilt to original spec (activity-first: Unified Timeline, Tasks, Alerts, NC Enrollment Windows). Mobile-responsive with off-canvas sidebar drawer. labels.html intentionally kept in light-mode (print utility).
- **Commission Audit ✅ (2026-04-13)** — All 7 carriers now supported: UHC, Aetna, BCBS, Humana, Devoted, Healthspring, Wellable. Real March 2026 files uploaded and parsing correctly. See Commission Parser Notes below.

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
- Aetna: agent=col9, amount=col10. Summary row: `'N x.525'` in col9, paid in col10. **Split rate = 52.5%** (not 55%).
- Humana: agent=col2, amount=col8 (PaidAmount). No separate paid row — Humana pays Tim directly, `paid = gross`. **Split rate = 1.0** in `agent_carrier_contracts` for Tim.
- BCBS: agent=col1, commission=col13. Summary row: `'$N x .55'` in col9, paid in col10.
- Devoted: agent=col2, amount=col11 (Base Amount). Summary row: `'N x .55'` in col8, paid in col9. Statement date is string `MM/DD/YYYY` in col0.
- Healthspring: agent=col3, amount=col7. Summary row: `'N x.55'` in col6, paid in col7.
- Wellable: agent=col3, advance_amount=col16. Summary row: `'$N x .55'` in col16, paid in col17. All line items flagged `is_advance=True` — clawback risk badge shown in UI.

**Split rates in agent_carrier_contracts (Tim, agent_id=1):**
- Aetna: 0.525 (52.5%)
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