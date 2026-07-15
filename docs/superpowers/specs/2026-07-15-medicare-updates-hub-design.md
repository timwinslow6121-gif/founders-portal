# Medicare Updates Hub — Design Spec

**Date:** 2026-07-15
**Status:** Approved (design) — ready for implementation plan
**Author:** Tim + assistant (brainstorm)

## Why

Agents need ONE place to stay current on the things that move commissions and sales:
a carrier making a top-selling Part C plan **non-commissionable** mid-year (Humana Gold
Plus is the grounding case), a **network change** ("Humana added Tryon Medical for 2026"
— huge for selling), carrier notices, **AHIP/training dates and webinars**, and general
Medicare rule/regulation news. Today this lives in scattered emails and agents' heads.
The Medicare Updates Hub is the single behind-login destination that gathers it.

Distinct from the **login Agency Notice Board** (`AgencyNotice`, pre-auth, public-safe,
admin-only): this hub is **behind login, agent-posted, internally-focused** — it can
carry confidential intel (commission changes, member counts) the login board cannot. It
follows the proven **Roadmap board** pattern (shared board, any agent posts, admins
curate).

## Scope decisions (locked in brainstorm)

- **One hub, two streams.** Curated internal intel is the HERO; external RSS news is a
  secondary supplementary panel. Build the curated hub first (Phase 1); RSS is Phase 2.
- **Curated posts are TYPED + carrier-tagged** (so agents filter to "Humana commission
  changes"), with an **optional plan link** (→ "affects Gold Plus — N of your members").
- **Any agent posts**, everyone sees it immediately (shared board). **Own posts editable
  by the poster; delete + pin are admin-only** (Roadmap trust model).
- **RSS is scheduled + cached + keyword-filtered from admin-vetted sources** — NEVER a
  live fetch on page load. RSS gives EVERYTHING a source publishes; a keyword filter cuts
  noise automatically and admins PIN the important items up into the main feed.

## Architecture

Phase 1 = the curated hub (3 units). Phase 2 = the cached RSS stream (adds 2-3 models + a
cron job). Both render on ONE page `/updates`.

### Unit 1 — `CarrierUpdate` model (Phase 1, migration 038)

New table `carrier_updates`, modeled on the `RoadmapItem` / `AgencyNotice` patterns.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `agency_id` | Integer FK → agencies.id, **NOT NULL**, indexed | scoping |
| `update_type` | String(24), NOT NULL, default `general` | allowlist: `commission` / `network` / `carrier_notice` / `training` / `important_date` / `general` — drives icon+color+filter |
| `carrier` | String(64), nullable | optional tag (Humana/UHC/Aetna/BCBS/Devoted/HealthSpring/Wellabe/GTL) |
| `title` | String(200), NOT NULL | |
| `body` | Text, NOT NULL | plain text, autoescaped (no `\|safe`) |
| `plan_id` | Integer FK → plans.id, nullable, **ondelete SET NULL** | optional "affects this plan" link |
| `event_date` | Date, nullable | for training/webinar/important-date items |
| `is_pinned` | Boolean, NOT NULL, default False | admin-pinned to top |
| `is_active` | Boolean, NOT NULL, default True | |
| `show_until` | Date, nullable | optional auto-hide (e.g. "non-commissionable for the rest of 2026") |
| `posted_by_id` | Integer FK → users.id, nullable | who posted |
| `created_at` | DateTime, server_default now | |
| `updated_at` | DateTime, server_default now, onupdate now | |

`UPDATE_TYPES = ("commission","network","carrier_notice","training","important_date","general")`.
Presentation map `update_type → {icon, accent}` in `app/updates.py` (one place, template+tests agree).
The six types cover v1; the list is intentionally extensible — adding a type later is one
tuple entry + one presentation-map entry (Tim: "might need to add some later").

**Visibility rule** — one classmethod:
```python
@classmethod
def visible_for(cls, agency_id, today, *, update_type=None, carrier=None):
    q = cls.query.filter(cls.agency_id == agency_id, cls.is_active.is_(True),
                         db.or_(cls.show_until.is_(None), cls.show_until >= today))
    if update_type: q = q.filter(cls.update_type == update_type)
    if carrier:     q = q.filter(cls.carrier == carrier)
    return q.order_by(cls.is_pinned.desc(), cls.created_at.desc()).all()
```

**Plan-link member count** (the standout): when a post has `plan_id`, the hub computes
the live **agency** active-member count for that plan (`Policy.plan_id == plan_id,
status='active', agency_id`) — the SAME key + grain the carrier list/detail pages use, so
the number matches those pages exactly (agency-wide, not per-agent) — and shows "Affects
[Plan name] · N active members →" linking to `/carriers/<plan_id>`. The count read is
**defensive**: a failure shows the post WITHOUT the count, never errors the page.

### Unit 2 — `updates_bp` blueprint (Phase 1)

New `app/updates.py`, registered with the standard 3-line pattern. Routes:
- `GET /updates` — the hub (login_required; agent + admin). Reads `visible_for` with the
  `update_type`/`carrier` query params; computes plan-link counts; (Phase 2) also reads
  cached `NewsItem`s.
- `GET/POST /updates/new` — post form (any agent). Type picker, optional carrier, title,
  body, optional **plan picker** (searchable against the plan DB — NOT hand-typed, to
  protect the FK link), optional event_date. Validated: blank title/body → flash +
  re-render (NOT 500); invalid `update_type`/`carrier` → allowlist-rejected.
- `GET/POST /updates/<id>/edit` — edit. Allowed if `current_user.is_admin` OR
  `posted_by_id == current_user.id` (own-post editable); else `abort(403)`.
- `POST /updates/<id>/delete` — **admin-only** (`abort(403)` before lookup).
- `POST /updates/<id>/pin` — **admin-only** toggle `is_pinned`.
- All agency-scoped to `current_user.agency_id`.

Nav: "Medicare Updates" link (agent + admin).

### Unit 3 — the hub template + filter bar

`updates.html`: filter bar (type pills All/Commission/Network/Carrier notice/Training/
Important date/General + carrier dropdown; submit-on-change, URL-param-persisted), main
feed (pinned-first cards: type icon+accent, carrier pill, title, body, poster+date,
optional plan-affect line, optional event_date), a "+ Post an update" button, and
(Phase 2) the "From around Medicare" RSS panel. Founders theme, light+dark, autoescape.

### Phase 2 — cached external RSS (separate migration 039 + deploy)

- **Dep:** `feedparser` (standard RSS/Atom parser). One new dependency.
- **`NewsSource`**: `id`, `agency_id`, `name`, `feed_url`, `is_active`, `added_by_id`,
  `created_at`. Admin-managed vetted feeds. ⚠ Not every site has a feed — verify each
  `feed_url` parses when added; find an alternate or skip if none.
- **`NewsItem`**: `id`, `agency_id`, `source_id` FK, `title`, `link`, `summary`,
  `published_at`, `fetched_at`, `is_pinned` (admin promotes into the main feed),
  `dedup_key` (unique per source+link — idempotent re-fetch).
- **`NewsKeyword`** (or a config list): admin-editable keyword allowlist; seeded with
  defaults (commission, AHIP, AEP, OEP, D-SNP, C-SNP, "CMS final rule", carrier names…).
- **`scripts/fetch_news.py`** (nightly cron, like `backup.sh`): per source, fetch with a
  short timeout + per-source try/except (one bad feed NEVER aborts the run), parse
  entries, KEEP only items whose title/summary match a keyword (case-insensitive), upsert
  `NewsItem` by `dedup_key`, trim to the latest N per source, log a summary. The hub only
  ever READS cached rows → a fetch failure never affects the page.
- **Admin `/admin/news-sources`**: add/remove/toggle feed sources; edit keywords.

## Data flow

```
Agent → /updates/new → CarrierUpdate (typed, carrier, optional plan_id, optional date)
                              │
Agent/admin → GET /updates ───┤
   ├─ CarrierUpdate.visible_for(agency, today, type?, carrier?)  → main feed (pinned first)
   ├─ per post with plan_id → live active-member count (defensive) → "affects N members"
   └─ (Phase 2) NewsItem cached rows (keyword-filtered) → "From around Medicare" panel
Admin → pin/delete/edit-any; poster → edit-own.

Nightly cron → fetch_news.py → each NewsSource.feed_url → feedparser → keyword filter →
   upsert NewsItem (dedup) → trim. (never touches the request path)
```

## Error handling

- Blank title/body → re-render with flash, 200 (not 500 — the roadmap blank-title bug class).
- Invalid `update_type`/`carrier` → allowlist-rejected, form error.
- Malformed `event_date`/`show_until` → field error, not 500.
- Plan-link count read wrapped defensively → post shows without the count on failure.
- Delete/pin: `abort(403)` before any lookup for non-admins. Edit: 403 unless admin or owner.
- Autoescape everywhere (agent-entered).
- (Phase 2) one source's fetch failure logged + skipped; the batch continues; the page
  reads cache regardless.

## Testing

- `CarrierUpdate.visible_for()` — active/inactive; expiry past/today/future/none;
  pinned-first then newest ordering; `update_type` + `carrier` filters; agency isolation.
- Plan-link count — post with `plan_id` reports the correct live member count; post
  without renders fine; a metrics failure degrades gracefully (post shows, no count).
- Routes — hub renders for a plain agent; any agent can post; blank title → re-render not
  500; type/carrier allowlist; edit allowed for owner + admin, 403 for a non-owner
  non-admin; delete/pin 403 for non-admin.
- Phase 2 — `fetch_news` keyword filter keeps/drops correctly (case-insensitive); dedup
  on re-run (idempotent); one bad feed doesn't abort the batch; expired/trim logic.

## Rollout

- **Phase 1:** migration **038** (`carrier_updates`; `down_revision="037"`) → seed 2-3
  example updates (idempotent, e.g. a Gold-Plus commission note linked to plan 19) →
  deploy (DB backup, `FLASK_APP=wsgi.py flask db upgrade`, restart, verify `/updates`
  renders + post/filter work + a plan-linked post shows the live count).
- **Phase 2 (separate deploy):** migration **039** (NewsSource/NewsItem/NewsKeyword) →
  add `feedparser` to requirements → **Tim provides 5–10 sources** (KFF.org is a confirmed
  starter — Tim is asking colleagues for their go-to Medicare sources) → verify each feed
  parses → seed sources + default keywords → add cron entry → run `fetch_news.py` once
  manually → verify the "From around Medicare" panel populates.

## Build method

Subagent-driven-development (fresh implementer per task + per-task spec+quality review +
opus whole-branch review). Phase 1 first as its own branch/deploy; Phase 2 as a second
branch/deploy. All times EST/EDT. Assistant deploys over SSH (DB backup before migrate).

## Out of scope (not this build)

- AI relevance scoring of news (keyword filter + admin pin is enough for v1; revisit only
  if keywords prove too noisy).
- Per-agent read tracking / "mark as read" (it's a shared board, not an inbox).
- Push notifications / email digests of updates (possible later).
- Rich text / images in post bodies (plain text v1).
- Comments/threads on updates.
