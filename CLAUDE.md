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
- `upload.py` — BOB import + commission statements
- `labels.py` — birthday labels PDF
- `agent_settings.py` — carrier contracts, splits
- `commission/` — audit, forecast
- `customers.py` — customer list, profile, notes, contacts, merge (`customers_bp`)
- `pharmacies.py` — partner pharmacy CRUD, admin-only (`pharmacies_bp`)

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
- **Phase 3 🔄 (IN PROGRESS)** — Plans 01-05 deployed to VPS. Plan 06 blocked on external provisioning (see below). Plan 07 (agency_id scoping sweep) is next to execute.
- **Lux Theme ✅** — All templates rethemed to The Private Gallery design system (2026-04-02). Dashboard rebuilt to original spec (activity-first: Unified Timeline, Tasks, Alerts, NC Enrollment Windows). Mobile-responsive with off-canvas sidebar drawer. labels.html intentionally kept in light-mode (print utility).

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

## Phase 3 Pre-Code Checklist
- [x] Quo (OpenPhone) account provisioned — QUO_WEBHOOK_SIGNING_KEY + QUO_API_KEY in .env
- [x] Quo webhook URL registered: `https://portal.foundersinsuranceagency.com/comms/webhook/quo`
- [x] Retell AI configured with Twilio SIP trunking
- [x] Twilio account SID + auth token in .env
- [x] Calendly webhook active — CALENDLY_WEBHOOK_SECRET in .env
- [ ] HealthSherpa agency account — created, awaiting provisioning. Register webhook once active. Add HEALTHSHERPA_WEBHOOK_SECRET to .env.
- [ ] Google Meet: enable recording + transcription in Workspace admin, create Pub/Sub topic/subscription, add service account credentials to VPS, add GOOGLE_MEET_PUBSUB_SUBSCRIPTION to .env
- [ ] Distribute HealthSherpa captive join code to LOA agents once provisioned

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