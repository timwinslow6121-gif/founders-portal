# Login Redesign + Agency Notice Board — Design Spec

**Date:** 2026-07-14
**Status:** Approved (design) — ready for implementation plan
**Author:** Tim + assistant (brainstorm)

## Why

Two goals in one build:

1. **Replace the login screen.** The current login (`app/templates/login.html`, 116 lines) uses an animated compounding-pestle logo. AJ dislikes it ("the pestle looks like a penis"). Retire it for a clean, professional split-screen that matches the Founders portal theme.
2. **Add a live Agency Notice Board.** The new login's left panel is an at-a-glance board of agency updates — an AEP countdown, next commission payout, carrier maintenance alerts — turning the login from a gate into the first useful screen of the day. Fits the "Agent Operating System" framing and is demo-worthy for Brian.

Approved mockups (interactive artifacts):
- Login v2 (split-screen, Founders-themed): `https://claude.ai/code/artifact/643d85fc-fbe0-436e-a36b-c6c2927dea01`
- Source inspiration: `docs/mockups/brokerage_crm_login (1).tsx` (Gemini variant 1). Teal accent translated to Founders blue `#266EA5` / green `#65BB84`; generic Shield swapped for the Founders blue/green mark (no pestle).

## Scope decisions (locked in brainstorm)

- **Content is public-safe only.** The notice board renders on the PRE-LOGIN page, visible to anyone who loads the URL. Notices must contain NO member names, dollar amounts, or internal specifics — only generic operational updates (AEP countdown, "commission run Friday", carrier-portal maintenance). The admin form carries an inline reminder of this.
- **AEP countdown is auto-computed** (server-side, not a DB row). All other notices are admin-typed cards.
- **Admin CRUD lives on a dedicated page** `/admin/notices` (mirrors the roadmap admin), NOT bolted onto the roadmap model.
- **Optional expiry, auto-hide.** Each notice has an optional `show_until` date; past it the notice drops off the board automatically (stays in the admin list, tagged Expired). No expiry = shows until manually deactivated.

## Architecture

Two independent, separately-testable units, consumed by one page.

### Unit 1 — `AgencyNotice` model (migration 037)

New table `agency_notices`, modeled on the existing `RoadmapItem` pattern (agency-scoped, admin-managed, one place for its display-filter logic).

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `agency_id` | Integer FK → agencies.id, **NOT NULL**, indexed | multi-tenant scoping (see Database Rules) |
| `notice_type` | String(16), NOT NULL, default `info` | allowlist: `info` / `payout` / `alert` → drives icon + accent color |
| `title` | String(200), NOT NULL | validated non-blank before insert |
| `body` | Text, NOT NULL | plain text; rendered autoescaped (no `|safe`) |
| `is_active` | Boolean, NOT NULL, default `True` | manual on/off |
| `show_until` | Date, nullable | optional auto-hide date |
| `priority` | Integer, NOT NULL, default `0` | display order (higher = earlier); ties broken by `created_at` desc |
| `created_at` | DateTime, server_default now | |
| `created_by_id` | Integer FK → users.id, nullable | who added it |

**Visibility rule** — one classmethod, single source of truth:

```python
@classmethod
def visible_for(cls, agency_id, today):
    """Notices to show on the login board for this agency, in display order."""
    return (cls.query
            .filter(cls.agency_id == agency_id,
                    cls.is_active.is_(True),
                    db.or_(cls.show_until.is_(None), cls.show_until >= today))
            .order_by(cls.priority.desc(), cls.created_at.desc())
            .all())
```

`notice_type` → presentation is a small module-level map (icon SVG name + CSS accent class): `info`→blue/info-icon, `payout`→green/dollar-icon, `alert`→rose/triangle-icon. One place, shared by template + tests.

### Unit 2 — AEP countdown helper (pure function)

```python
def next_aep(today):
    """Return (days, year): whole days from `today` (a date) until the next Annual
    Enrollment Period start (Oct 15), and the calendar year of that Oct 15. Rolls to
    next year once Oct 15 has passed. days >= 0 (0 on Oct 15 itself). e.g.
    next_aep(date(2026,7,14)) -> (93, 2026); next_aep(date(2026,11,1)) -> (348, 2027)."""
```

The template uses both: `days` for the count, `year` for the "AEP {year} Countdown" label.

Lives in a small helper module (e.g. `app/notices.py` alongside the board read). Pure, no DB, no `datetime.now()` inside (caller passes `today`) so it's trivially testable. The AEP widget is ALWAYS pinned as the first item on the board; it is not an `AgencyNotice` row.

### Unit 3 — login route read + template

- `auth.py` `login()` (currently `return render_template('login.html')`) gains a small read:
  ```python
  agency_id = current_app.config.get("DEFAULT_AGENCY_ID", 1)  # pre-auth: no current_user
  notices = AgencyNotice.visible_for(agency_id, date.today())
  aep_days, aep_year = next_aep(date.today())
  return render_template('login.html', notices=notices, aep_days=aep_days, aep_year=aep_year, error=error)
  ```
  Because the page is pre-auth (no `current_user`), the agency is hardcoded to `DEFAULT_AGENCY_ID`. This is acceptable and intentional for the single-tenant deployment; when white-labeled, login is per-subdomain and this becomes the resolved tenant.
- The existing `error` param (non-domain login attempt) still renders, now on the login panel.

### Unit 4 — admin CRUD (`notices_bp`)

New blueprint `app/notices.py` (mirrors `app/roadmap.py`), registered with the standard 3-line pattern. Routes (all admin-only via `abort(403)` BEFORE any lookup, all agency-scoped to `current_user.agency_id`):
- `GET /admin/notices` — list ALL notices (active / inactive / expired), expired visually tagged, priority order.
- `GET/POST /admin/notices/new` — add form.
- `GET/POST /admin/notices/<id>/edit` — edit form.
- `POST /admin/notices/<id>/delete` — hard delete (ephemeral announcements, not audit records).
- Form fields: `notice_type` picker, `title`, `body`, `priority`, `show_until` (optional), `is_active` toggle. Inline reminder: *"This shows on the public login page — no member names, dollar amounts, or internal details."*
- Admin nav gains a "Notices" link.

## Data flow

```
Admin → /admin/notices (CRUD) → AgencyNotice rows
                                        │
Anonymous visitor → GET /login ─────────┤
   ├─ AgencyNotice.visible_for(DEFAULT_AGENCY_ID, today) → notices[]
   ├─ next_aep(today) → (aep_days, aep_year)
   └─ render login.html: [AEP card pinned, aep_days/aep_year] + notices[]  |  right panel: Google SSO
```

OAuth flow, session handling, domain restriction, `prompt='select_account'` — ALL UNCHANGED. This is a template reskin + a read + a new admin surface.

## The login template (rebuild `login.html`)

Replaces the current file entirely. Layout per the approved artifact:

- **Left panel — Agency Notice Board** (dark "stage", single-dark by design — it's "the screen", a deliberate choice not an omission):
  - Heading "Agency Notice Board" + subtitle.
  - **AEP countdown card** pinned first (green accent, `aep_days` interpolated). Label uses the target AEP year — the calendar year of the next Oct 15 (`days_until_aep` can return it, or the template derives it): e.g. "AEP 2026 Countdown / 93 Days".
  - Then `notices` in order, each rendered by `notice_type` → icon + accent (info=blue, payout=green, alert=rose).
  - **Empty state:** if `notices` is empty, show the AEP card + a quiet "All clear — no active notices" line. Never an empty void.
- **Right panel — login** (theme-aware light/dark, device default + toggle, same no-flash pattern as the rest of the portal):
  - Founders blue→green logo mark (the real `app/static/img/founders-mark.svg`, NOT the pestle).
  - "Founders Portal" / "Agent Operating System".
  - Frosted card: **Sign in with Google** (→ existing `/auth/google`), `@foundersinsuranceagency.com` restriction line, HIPAA footer.
  - `error` (if present) renders as an inline message here.
- **Icons:** inline SVG only (no emoji-as-icon, no external icon CDN — CSP-safe).
- **Mobile:** stacks vertically, login panel FIRST (sign-in always immediately reachable), notice board below.

## Error handling

- Blank `title` or `body` on add/edit → form re-renders with a field error (NOT a 500 — the roadmap blank-title→500 bug is the known precedent; validate before insert).
- Invalid `notice_type` → rejected by the allowlist, form error.
- Malformed `show_until` → field error, not a 500.
- Non-admin hitting any `/admin/notices` route → `abort(403)` before any DB lookup.
- Login page with a DB read failure must still render the SSO button (the board is enhancement, not a gate) — wrap the notice read defensively so a board error never blocks login.

## Testing

- **`next_aep()`** (pure): before Oct 15 (e.g. Jul 14 → 93), on Oct 15 (→ 0), after Oct 15 (→ rolls to next year's Oct 15), across a year boundary, leap-year sanity.
- **`AgencyNotice.visible_for()`**: active shows / inactive hidden; `show_until` in past hidden, today shown, future shown, NULL shown; ordering by priority then created_at; **agency isolation** (agency 2's notice never returned for agency 1).
- **Routes**: `/login` renders notices + AEP unauthenticated (no `current_user`); `/admin/notices` list/add/edit/delete happy paths; non-admin → 403; blank title → re-render not 500; bad `notice_type` → rejected; expired notice appears in admin list but NOT on `/login`.

## Rollout

1. Migration **037** — create `agency_notices`. `down_revision = "036"`.
2. Idempotent seed script (`scripts/seed_agency_notices.py`, dry-run/`--apply`) — 2–3 public-safe starter notices so the board isn't empty on first deploy (e.g. a payout-date card + a generic "certification season" info card). Idempotent on `(agency_id, title)`.
3. Deploy to VPS (assistant does it, not handed to Tim): DB backup first (`PGPASSWORD=… pg_dump …`), `FLASK_APP=wsgi.py ./venv/bin/flask db upgrade`, restart, verify `/login` renders the board AND Google sign-in still completes end-to-end (the pre-auth read must not break login).

## Build method

Subagent-driven-development: fresh implementer per task + per-task spec+quality review + **opus whole-branch review** (this touches the pre-auth login path — the whole-branch review matters). All times EST/EDT.

## Out of scope (not this build)

- Per-agent / personalized notices (everyone sees the same board).
- Rich text / images / links in notice bodies (plain text only).
- A display cap on notice count (deferred; priority ordering + expiry is enough for now — revisit if the board ever overflows).
- Notice read-tracking / dismissal (it's a login-screen board, not an inbox).
