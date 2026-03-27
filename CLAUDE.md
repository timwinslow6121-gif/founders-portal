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

## UX Design System
- Navy `#1B2A4A`, Blue `#185FA5`, Gold `#C9A84C`
- 200px sidebar, system font stack
- CSS lives in `{% block styles %}` per template — no separate CSS files
- Class names: `.card`, `.data-table`, `.btn-primary`, `.btn-secondary`, `.badge`, `.nav-item`
- **Login page** uses its own dark theme (`#060e20` bg, glassmorphic card, Inter font, gold `#e6c364` label) — does not extend base.html

## Build Status
- **Phase 1 ✅** — BOB parsers (6 carriers), commission audit, agent dashboard, admin overview, birthday labels
- **Phase 2 ✅** — Customer master: Pharmacy, Customer, CustomerContact, CustomerNote, CustomerAorHistory models; customers_bp + pharmacies_bp blueprints; all 7 templates
- **Phase 2.5 ✅** — PostgreSQL 16 on VPS; Agency multi-tenant model; 2GB swap; Gunicorn gthread; 5,589 rows migrated; UAT passed 7/7; login page redesigned (dark glassmorphic, Inter font)
- **Phase 3 🔜 (NEXT)** — Quo (OpenPhone) + Twilio SIP + Retell AI + Google Meet + HealthSherpa + Calendly webhooks

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

## VPS-Only State (not in git)
- `.env` on VPS has `SECRET_KEY`, `DATABASE_URL` (PostgreSQL), `ADMIN_EMAILS=admin@foundersinsuranceagency.com` — never commit
- `app/templates/base.html` on VPS had an extra `{% endif %}` (fixed 2026-03-26 during UAT) — local copy and VPS are now in sync
- Admin login: `admin@foundersinsuranceagency.com` (shared AJ+Tim). Agent test login: `tim@foundersinsuranceagency.com`
- `is_admin` is recalculated from `ADMIN_EMAILS` on every OAuth login — DB value gets overwritten

## Phase 3 Pre-Code Checklist (after Phase 2.5 complete)
- [ ] Quo (OpenPhone) account provisioned — webhook signing key from Quo dashboard → QUO_WEBHOOK_SIGNING_KEY in .env
- [ ] Quo API key → QUO_API_KEY in .env (Authorization header, no Bearer prefix)
- [ ] Quo webhook URL registered: `https://portal.foundersinsuranceagency.com/comms/webhook/quo`
- [ ] Retell AI trial — call own number, evaluate quality with Medicare senior persona
- [ ] Twilio account SID + auth token in .env (required for Retell AI SIP trunking — Quo does not support SIP)
- [ ] HealthSherpa agency account + captive join code distributed to LOA agents
- [ ] Google Workspace admin: Meet recording + transcription enabled for domain
- [ ] Calendly plan tier confirmed for API (Professional or Teams)
- [ ] Secrets in .env: QUO_WEBHOOK_SIGNING_KEY, QUO_API_KEY, RETELL_WEBHOOK_SECRET, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, CALENDLY_WEBHOOK_SECRET, HEALTHSHERPA_WEBHOOK_SECRET, GOOGLE_MEET_WEBHOOK_SECRET

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