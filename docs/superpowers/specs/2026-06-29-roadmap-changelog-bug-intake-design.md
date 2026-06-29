# Portal Roadmap & Changelog + Bug Intake

_Date: 2026-06-29 · Status: brainstorm approved by Tim, ready for writing-plans.
Visual companion used (board layout chosen over timeline; expand-in-place detail)._

## Overview

A `/roadmap` page in the portal showing a **board view** — three status columns
(**Planned / Known issues · In progress · Shipped**) of compact cards. Each card
**expands in place** to reveal the full "issue → fix" detail. Purpose (Tim):

1. Tell everyone what's been fixed/shipped (what the issue was + the fix), in a
   beautifully designed on-theme history "from day 1".
2. Show what's planned/coming and what known issues are being worked on.
3. Let agents **submit a bug** they found; the admin triages it, sets priority/status,
   optionally promotes it to a public card, and the submitter tracks its progress —
   all **in-portal** (no email).

It reinforces the project's "trust 100%, with verifiable proof" ethos: showing the
agency *we found this, here's exactly what we fixed* builds confidence.

## Decisions locked (brainstorm)

- **Content is admin-curated** — admins author entries; nothing is auto-generated from
  git/commits (commit wording is developer-facing). A submitted bug becomes a *draft*
  the admin promotes.
- **Submission → admin inbox → triage → optionally promote to public** — one unified
  system (not a separate tracker). Submissions start `private`; admin flips to `public`.
- **Notifications are in-portal only** — a "My submissions" view + live status badges +
  an instant on-submit acknowledgement. No email, no notification bell (v1).
- **Seed ~15–25 curated highlights** from the real shipped history, rewritten in plain
  agent-friendly language; Tim reviews before publishing.
- **Entry types:** bug_fix · feature · planned · known_issue (all four).
- **Layout:** board (3 status columns), compact cards, **expand-in-place** detail
  (same pattern as the Fidelity drill-down).

## Architecture

Three thin pieces, each one responsibility (follows existing portal patterns):

### 1. Model: `RoadmapItem` (one migration)
Mirrors the `UnmatchedCall` shape (agency_id, status, timestamps, submitted/resolved-by):

```
RoadmapItem:
  id            : int PK
  agency_id     : FK agencies.id, not null, indexed       (multi-tenant scoping)
  type          : str(16)  — bug_fix | feature | planned | known_issue
  title         : str(200), not null
  issue_text    : Text, nullable    — "what was wrong" (the problem)
  fix_text      : Text, nullable    — "the fix" / what we did (filled when resolved)
  status        : str(20), default 'submitted'
                  — submitted | acknowledged | planned | in_progress | shipped | wont_fix
  priority      : str(8), nullable  — low | medium | high
  visibility    : str(8), default 'private'  — private | public
  submitted_by_id : FK users.id, nullable   (null = admin-authored)
  shipped_on    : Date, nullable    — for shipped-column ordering / "from day 1" date
  created_at    : DateTime, server_default now()
  updated_at    : DateTime, onupdate now()
```

**Column → board mapping** — keep in ONE place, a `RoadmapItem.column` property, so the
template and tests agree. The property returns one of `planned` | `in_progress` |
`shipped` | `hidden`:
- **shipped** ← status = `shipped`
- **in_progress** ← status = `in_progress`
- **planned** (the "Planned / Known issues" column) ← status ∈ {`submitted`,
  `acknowledged`, `planned`} OR type ∈ {`planned`, `known_issue`}
- **hidden** ← status = `wont_fix` — NOT shown on the public board; an admin can still
  see/reach `wont_fix` items via an admin-only filter (so a declined submission isn't
  lost, and the submitter sees its status as "Won't fix" in their My-submissions list).

The board renders only `planned`/`in_progress`/`shipped` columns; `hidden` items are
excluded from the three public columns by construction.

### 2. Blueprint: `app/roadmap.py` (`roadmap_bp`)
Registered with the standard 3-line pattern in `app/__init__.py`. Routes:

- `GET /roadmap` — the board. Builds three column lists scoped to the viewer:
  - **agent:** `visibility='public'` items + the agent's OWN `private` submissions.
  - **admin:** ALL items (incl. every private submission), with inline triage controls.
  All queries `agency_id`-scoped (multi-tenant rule).
- `POST /roadmap/submit` — agent (any logged-in user) submits a bug: title + description
  → `RoadmapItem(type='bug_fix', status='submitted', visibility='private',
  issue_text=description, submitted_by_id=current_user.id)`. Returns to the board with
  an acknowledgement flash ("Got it — we've received your report").
- `POST /roadmap/<id>/edit` — **admin only** (`abort(403)` else): edit any field
  (title/issue/fix/type/status/priority), and set `visibility` (promote to public).
  `log_event` an audit row (admin action on shared data).
- (Optional) `POST /roadmap/<id>/delete` — admin only, for junk submissions.

Auth: every write is admin-gated except `submit` (any agent). Reads are filtered by the
visibility rule above so an agent NEVER sees another agent's private submission.

### 3. Template: `app/templates/roadmap.html`
- Header (Merriweather title "Portal Roadmap & Changelog" + tagline) + **"Report an
  issue"** button (opens an inline/modal form: title + description).
- Three columns; each card: type badge (color-coded), priority dot, date, title; the
  card **expands in place** on click to show the issue/fix boxes + submitter + dates.
- **Founders theme** (the in-app blue/green tokens from `base.html`, NOT the all-white
  login mark): blue `#266EA5`, green `#65BB84` (shipped/positive), navy `#002E4D`
  headings, amber for known-issues, soft cards + 16px radius. Light + dark via the
  existing tokens.
- Admin-only inline controls (status/priority selects, promote-to-public toggle, edit)
  shown via `{% if current_user.is_admin %}`.
- A small "My submissions" affordance for agents (filter to their own items + a
  "Received / Acknowledged / In progress / Shipped" badge each).

### Nav
Add a nav item. Agent: under **Tools** (or its own "What's New" entry). Admin: same.
A subtle "new since last visit" hint is OUT of scope for v1 (no per-user read tracking).

## Seeding "from day 1"
`scripts/seed_roadmap.py` (dry-run default, `--apply`, idempotent on title) creates
~15–25 `RoadmapItem` rows from the real shipped history, each rewritten in plain
language with a clean `issue_text`/`fix_text`. Candidate highlights (Tim edits before
publish): data-integrity radar; stub-creation prevention (commission = match-or-park);
the 4 UHC quirk fixes (HRA attribution, PARTD $4.59 split, Fidelity perf, override-
sibling customer_id); all-6 commission carriers reconciling; agent recap + Fidelity
view; the security milestone (off-site backups, access hardening, audit log); the
portal re-theme; BOB chronological dedup; AOR timeline reconciliation. A few `planned`
(no-MBI customer merge, plan_id linkage) + `known_issue` (plan-count mismatch) rows so
all three columns are populated at launch.

## Testing
- Model + migration applies cleanly; `RoadmapItem.column` maps each status correctly.
- Blueprint registered; `/roadmap` renders 200 for agent AND admin (different controls).
- **Visibility:** an agent sees public items + their OWN private submission but NOT
  another agent's private submission; admin sees all.
- `submit` creates a private bug_fix submission attributed to the submitter + shows the
  acknowledgement.
- `edit` is admin-only (`403` for a non-admin), updates fields, and promote flips
  `visibility` to public so the agent then sees it as public.
- Template renders the board columns + the expand-in-place detail markup; admin controls
  appear only for admins.
- Seed script is idempotent (re-run creates no duplicates).

## Out of scope (YAGNI v1 — addable later)
Email/notification-bell alerts; file/screenshot upload on submissions; comments/threads;
upvoting; per-user "new since last visit" tracking; auto-generation from git/BACKLOG.

## Files (all new except registration + nav)
- `app/models.py` — `RoadmapItem` model.
- migration — `roadmap_items` table.
- `app/roadmap.py` — `roadmap_bp` blueprint + routes.
- `app/templates/roadmap.html` — the board + submit form.
- `app/__init__.py` — register `roadmap_bp` (3-line pattern).
- `app/templates/base.html` — nav item (agent + admin).
- `scripts/seed_roadmap.py` — curated history seed (dry-run/--apply).
- `tests/test_roadmap.py` — model, routes, visibility, auth, seed idempotency.
