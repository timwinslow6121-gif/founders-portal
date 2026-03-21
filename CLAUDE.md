# Founders Insurance Agency — Agent Portal

Flask CRM/portal for a Medicare insurance agency. 8 agents, ~5,500 policies across 6 carriers.

## Stack
- Python 3.10, Flask 3.0, Flask-SQLAlchemy, Flask-Migrate (Alembic)
- SQLite (dev/prod) → PostgreSQL (planned for white-label)
- Nginx + Gunicorn on Ubuntu VPS (23.187.248.100)
- Google OAuth 2.0 — restricted to @foundersinsuranceagency.com
- Vanilla JS only — no React/Vue. Jinja2 templates extending base.html.
- SendGrid for email, OpenPhone for SMS/calls (Phase 3)

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

## UX Design System
- Navy `#1B2A4A`, Blue `#185FA5`, Gold `#C9A84C`
- 200px sidebar, system font stack
- CSS lives in `{% block styles %}` per template — no separate CSS files
- Class names: `.card`, `.data-table`, `.btn-primary`, `.btn-secondary`, `.badge`, `.nav-item`

## Build Status
- **Phase 1 ✅** — BOB parsers (6 carriers), commission audit, agent dashboard, admin overview, birthday labels
- **Phase 2 ✅** — Customer master: Pharmacy, Customer, CustomerContact, CustomerNote, CustomerAorHistory models; customers_bp + pharmacies_bp blueprints; all 7 templates
- **Phase 3 🔜** — OpenPhone + Calendly + Fireflies webhooks (OpenPhone account not yet set up)

## Phase 3 Pre-Code Checklist (must complete before writing comms code)
- [ ] OpenPhone account + numbers provisioned → get `phoneNumberId` per agent
- [ ] `OPENPHONE_API_KEY` in VPS .env
- [ ] Webhook URL registered: `https://portal.foundersinsuranceagency.com/comms/webhook/openphone`
  - Events: `call.completed`, `call.missed`, `message.received`, `message.sent`
- [ ] `OPENPHONE_WEBHOOK_SECRET` in VPS .env

## Key Files
- `FOUNDERS_PORTAL_CONTEXT.md` — full project context, agent roster, carrier details, roadmap
- `PRODUCT_VISION.md` — white-label SaaS vision
- `app/models.py` — all models
- `app/upload.py` — BOB import logic + `_upsert_customer_from_policy()`
- `instance/founders_portal.db` — SQLite database (not in git)
- `.env` — secrets (not in git): GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SECRET_KEY, SENDGRID_API_KEY
