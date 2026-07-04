# Commission Audit Page — Visual Redesign

**Status:** Brainstormed + approved (mockup-confirmed) 2026-07-04. Ready for writing-plans.
**Origin:** The commission-upload UX overhaul (2026-07-03) shipped correct *behavior* but
a regressed *layout* — oversized elements, expandable-pill carrier chips rendering as
stretched capsules, an ungrouped full-width KPI bar with dead space, and a massive
upload box. Tim: "this needs some serious UI/UX improvements." A visual mockup of the
new layout was built + approved.

## Guiding principle (Tim, 2026-07-04)
**This page has ONE job: upload commission statements and track what's in / what's still
owed.** Show ONLY data that answers "what needs uploading, when, for what, and what's
left." Nothing about earnings/money/analysis (that lives in the recap/dashboard). This
is the loading dock, not the ledger.

## What's wrong now (from the screenshot)
1. **KPI strip:** one full-width card, 3 stats stretched edge-to-edge, oceans of dead space.
2. **Carrier checklist (worst):** `<details>` chips styled as pills (radius 999px) that
   expand VERTICALLY → stretched-capsule shapes; an expanded carrier (Devoted 7/7) balloons
   the whole row's height.
3. **Upload box:** ~150px-tall empty drop-zone for something that should be compact.
4. **Flat hierarchy:** everything the same visual weight; no grid discipline; no clear
   "status here / upload there" separation.

## The redesign (approved mockup)
Founders theme (blue `#266EA5`, green `#65BB84`, navy `#002E4D` headings, Plus Jakarta
Sans + Merriweather, light/dark tokens; `--radius:14px`, `--radius-sm:8px`). Everything on
one grid with consistent card styling. **This is CSS/markup only — no behavior change to
upload, parsing, per-agent status data, or the JS from the 2026-07-03 work.**

### 1. KPI strip → three compact cards, left-aligned
Replace the single full-width `.hero`/`.ca-strip` bar with **three small stat cards** in a
flex row (`gap:12px; flex-wrap`), each sized to its content (`min-width:~150px`), grouped at
the left — not stretched to the viewport. Cards wrap on narrow screens.
- **Statements uploaded** (`overview.statement_count`) — navy number.
- **Carriers received** (`carriers_uploaded / carriers_expected`) — blue; green when equal.
- **Payments to review** (`overview.total_quarantined`) — green when 0, gold when >0;
  links to the quarantine workbench when >0 (an actionable to-do, kept because "this month
  isn't done until it's zero"). Framed as a to-do, not a vanity stat.
- **NO dollar/earnings KPI** — out of scope by the guiding principle.

### 2. Carrier row → uniform chips + click-popover for per-agent carriers
Replace the `<details>`-pill mess. A tidy flex row of **uniform-height status chips**
(`.ca-chip`, pill radius fine on a SINGLE-LINE chip): `✓ Aetna` (green, uploaded) /
`○ GTL` (muted, missing).
- Per-agent carriers (`PER_AGENT_CARRIERS` = BCBS/Devoted/Healthspring) render a chip with
  a small `N/M` count + a ▾ caret and are **clickable** (`cursor:pointer`, `aria-expanded`).
- Clicking opens a **popover** — an absolutely-positioned floating card
  (`position:absolute; z-index:30; box-shadow`) anchored under the chip — listing each
  agent `✓/○` with their **upload date** on the right (`✓ Brian Freeman … Jul 3`,
  `○ Mike Lauzurique … —`). The popover floats OVER the layout; clicking a chip NEVER
  pushes the row taller (fixes the balloon). One popover open at a time; click-outside or
  Esc closes it; only ONE chip may be visually "active" at a time.
- **Upload date source:** per agent, the MAX `CommissionLineItem.created_at` across that
  agent's rows for the carrier+period (that's when their file landed). The
  `per_agent_upload_status` helper (recap.py) gains an `uploaded_at` field per agent
  (None → "—"). Format short: "Jul 3".
- Accessibility: chip is a `<button>` with `aria-expanded`; popover has `role="dialog"` or a
  labelled list; keyboard-openable + Esc-closable; the ✓/○ is not the ONLY signal (green
  text + word).

### 3. Upload box → compact single-row drop-zone
Collapse the huge drop-zone into a **slim horizontal row** inside one card:
`[icon] "Drop files here or click to browse" + sub-text | "Attribute to · June" month picker | [Upload & Parse]` — all in one compact row (~56–72px tall), not a 150px empty box.
- The staged-files list (from the 2026-07-03 JS) renders as **thin rows directly below**
  the drop-row; per-file results render below that. Unchanged behavior — just restyled
  compact (`.ca-staging`/`.ca-results` rows tightened).
- Drag-over highlight, `multiple`, the AJAX submit, and inline results are all UNCHANGED
  (2026-07-03 work). This task only resizes/restyles the container + the staging rows.

## Architecture
- **`app/templates/commission.html`:** the bulk of the change — rewrite the KPI strip
  markup + CSS (3 cards), the carrier-row markup + CSS (chips + popover, replacing the
  `<details>`), the upload-box markup + CSS (compact row). Add the small popover JS
  (open/close/position/Esc/click-outside, one-at-a-time) — vanilla, matching the existing
  script block. Keep the existing staging/AJAX/results JS intact; only its container CSS
  changes.
- **`app/commission/recap.py`:** `per_agent_upload_status(agency_id, carrier, period)`
  gains an `uploaded_at` per agent (max line-item `created_at` for that agent+carrier+period;
  None if not uploaded). `commission_audit_overview` passes it through the checklist
  `agents` entries (already wired from the 2026-07-03 Task 3/4).
- **Data note:** `CommissionLineItem.created_at` (server-default now) exists;
  `CommissionStatement.upload_date` exists as a whole-statement fallback. Per-agent uses the
  line-item max.
- **No migration. No new deps.** CSS/markup + a small JS popover + one helper field.

## Constraints (carry from the codebase)
- Text colors `var(--ivory)`/`var(--slate)`/`var(--green)` — NEVER `var(--ink)` (bg token).
- No `|safe` on agent names / any data (autoescape; JS uses textContent).
- Admin-only page; agency-scoped queries (helper already is).
- Works light + dark (tokens); responsive (chips + KPI cards wrap; popover repositions or
  stays within viewport on narrow screens).
- Reduced-motion respected on the popover (no motion, or a token-driven fade only).

## Testing
- `per_agent_upload_status` returns `uploaded_at` (a datetime) for an uploaded agent and
  `None` for a missing one; agency-scoped; unchanged for non-per-agent carriers.
- Render: `/admin/commissions` returns 200 for an admin; contains the 3 KPI cards, a
  chip row (not `<details>`), and a compact upload row; the popover markup + date present.
- Browser-verify (deploy): 3 tidy KPI cards; chips uniform height; clicking BCBS opens a
  floating popover with agent ✓/○ + dates that does NOT push the row taller; Esc/outside
  closes it; the upload row is compact; staged files + results still work; light + dark.
- Color-token + no-`|safe` compliance.

## Definition of done
- 3 compact KPI cards (upload-tracking only, no dollars).
- Uniform carrier chips; per-agent carriers open a floating popover (agent ✓/○ + upload
  date) that never balloons the row; keyboard + Esc + click-outside; one-at-a-time.
- Compact single-row upload with staged files + inline results below (behavior unchanged).
- Clean Material-3-ish hierarchy on the Founders grid; light + dark; responsive.
- Opus/UI review + browser-verify + deploy.

## Explicitly out of scope (YAGNI / separate projects)
- **Renaming "Commission Audit"** and any nav change → folded into the **SIDEBAR /
  NAVIGATION OVERHAUL** backlog project (rename decided as part of the IA redesign, not
  here). Also going on the /roadmap board.
- Grand-total $ KPI, "still missing" summary line — cut by the guiding principle (earnings
  = recap; missing = already answered by the ○ chips + popover).
- Any change to upload/parse/ingest/JS behavior (that shipped 2026-07-03 and is correct).
- Portal-wide Material-3 component system (its own spec).

## Reuse (don't rebuild)
- The 2026-07-03 upload JS (staging/AJAX/results), `per_agent_upload_status`,
  `commission_audit_overview`, `PER_AGENT_CARRIERS`, the Founders theme tokens in base.html.
