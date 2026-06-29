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
3. Let agents **submit a bug** they found — visible to ALL agents immediately (so the
   same bug isn't reported three times); the admin triages it (priority/status, accept
   onto the roadmap, or dismiss duplicates/non-bugs), and the submitter tracks its
   progress — all **in-portal** (no email).

It reinforces the project's "trust 100%, with verifiable proof" ethos: showing the
agency *we found this, here's exactly what we fixed* builds confidence.

## Decisions locked (brainstorm)

- **Content is admin-curated** — admins author entries; nothing is auto-generated from
  git/commits (commit wording is developer-facing). A submitted bug becomes a *draft*
  the admin promotes.
- **Everyone sees everything** (Tim, 2026-06-29) — ALL agents see ALL submissions
  immediately, so agent #2 sees a bug is already reported and doesn't file a duplicate.
  There is NO private/public visibility split. The two admin curation actions are:
  - **Promote** = accept it onto the official roadmap (status moves submitted →
    acknowledged/planned/in_progress) — NOT a visibility change (it was already visible).
  - **Dismiss** = hide a duplicate / non-bug / noise from the SHARED board (status =
    `dismissed`). Still visible to its submitter (shown as "Reviewed — not a bug" /
    "Duplicate") and to admins via a filter. Nothing is hard-deleted.
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
Mirrors the `UnmatchedCall` shape (agency_id, status, timestamps, submitted/resolved-by).
**No `visibility` column** — everything is visible to everyone; `dismissed` is the only
thing that drops an item off the shared board.

```
RoadmapItem:
  id            : int PK
  agency_id     : FK agencies.id, not null, indexed       (multi-tenant scoping)
  type          : str(16)  — bug_fix | feature | planned | known_issue
  title         : str(200), not null
  issue_text    : Text, nullable    — "what was wrong" (the problem)
  fix_text      : Text, nullable    — "the fix" / what we did (filled when resolved)
  status        : str(20), default 'submitted'
                  — submitted | acknowledged | planned | in_progress | shipped
                  | wont_fix | dismissed
  priority      : str(8), nullable  — low | medium | high
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
- **hidden** ← status ∈ {`wont_fix`, `dismissed`} — NOT shown on the shared board. An
  admin sees/reaches these via an admin-only filter (so a declined/duplicate submission
  isn't lost), and the SUBMITTER still sees their own dismissed/won't-fix item in their
  "My submissions" list with the explanatory badge ("Reviewed — not a bug" / "Won't fix"
  / "Duplicate"). So `hidden` means "off the shared board," not "invisible to everyone."

The board renders only `planned`/`in_progress`/`shipped` columns from the SHARED set;
`hidden` items appear only in the submitter's own My-submissions list + the admin filter.

### 2. Blueprint: `app/roadmap.py` (`roadmap_bp`)
Registered with the standard 3-line pattern in `app/__init__.py`. Routes:

- `GET /roadmap` — the board. **Everyone (agent AND admin) sees the SAME shared board:**
  all non-`hidden` items, `agency_id`-scoped, in the three columns. (No per-agent
  filtering — that's the whole point: agents see each other's reports so they don't
  duplicate.) Admins additionally get inline triage controls + access to the
  hidden/dismissed filter. A `mine=1` query param filters to the current user's own
  submissions (the "My submissions" view), which DOES include their hidden ones.
- `POST /roadmap/submit` — any logged-in agent submits a bug: title + description →
  `RoadmapItem(type='bug_fix', status='submitted', issue_text=description,
  submitted_by_id=current_user.id)`. It's immediately on the shared board (status
  "Reported / Under review"). Returns with an acknowledgement flash ("Got it — we've
  received your report").
- `POST /roadmap/<id>/edit` — **admin only** (`abort(403)` else): edit any field
  (title/issue/fix/type/status/priority). Status drives everything: `submitted` →
  `acknowledged`/`planned`/`in_progress` (promote onto the roadmap) → `shipped`, or
  `dismissed`/`wont_fix` to drop it off the shared board. `log_event` an audit row.
- (Optional) `POST /roadmap/<id>/delete` — admin only, for true garbage (prefer
  `dismissed` over delete so the submitter sees an outcome rather than a vanish).

Auth: every write is admin-gated except `submit` (any agent). There is no private-read
rule — the shared board is the same for everyone; only `hidden` items are off it (still
visible to their own submitter + admins).

### 3. Template: `app/templates/roadmap.html`
- Header (Merriweather title "Portal Roadmap & Changelog" + tagline) + **"Report an
  issue"** button (opens an inline/modal form: title + description).
- Three columns; each card: type badge (color-coded), priority dot, date, title; the
  card **expands in place** on click to show the issue/fix boxes + submitter + dates.
- **Founders theme** (the in-app blue/green tokens from `base.html`, NOT the all-white
  login mark): blue `#266EA5`, green `#65BB84` (shipped/positive), navy `#002E4D`
  headings, amber for known-issues, soft cards + 16px radius. Light + dark via the
  existing tokens.
- Admin-only inline controls (status/priority selects, edit, **Dismiss**) shown via
  `{% if current_user.is_admin %}`. (Promote = just moving status off `submitted`.)
- A "My submissions" affordance (`?mine=1`) for any agent — filters to their own items,
  including their dismissed/won't-fix ones, each with a status badge ("Reported / Under
  review / Acknowledged / In progress / Shipped / Won't fix / Duplicate").
- A duplicate report shows on the shared board, so an agent about to file the same bug
  sees it already there — the whole reason for the shared view.

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
- Model + migration applies cleanly; `RoadmapItem.column` maps each status correctly
  (incl. `wont_fix`/`dismissed` → `hidden`).
- Blueprint registered; `/roadmap` renders 200 for agent AND admin.
- **Shared visibility:** agent A sees agent B's submission on the board (the anti-
  duplicate guarantee). All non-hidden items appear for everyone, agency-scoped.
- **Dismissed/won't-fix:** a `dismissed` item is OFF the shared board for other agents,
  but still appears in its own submitter's `?mine=1` view and in the admin filter.
- `submit` creates a `bug_fix`/`submitted` item attributed to the submitter, immediately
  on the shared board, + shows the acknowledgement.
- `edit` is admin-only (`403` for a non-admin); a status change (e.g. → `in_progress`,
  `shipped`, `dismissed`) moves the item between columns / off the board accordingly.
- Multi-tenant: an item from another `agency_id` never appears.
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
- `tests/test_roadmap.py` — model, routes, shared-visibility, dismiss, auth, multi-tenant,
  seed idempotency.
