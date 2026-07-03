# Commission Audit Upload — UX Overhaul

**Status:** Brainstormed + approved 2026-07-03. Ready for writing-plans.
**Origin:** AJ's five pain points on the admin Commission Audit upload flow
(`app/templates/commission.html` + `commission_upload` in `app/commission/routes.py`).

## Hard constraint (Tim, 2026-07-03)
**Everything happens INLINE on the Commission Audit page — no redirect, no page
reload, no leaving the view.** The upload flow becomes AJAX: the form posts via
`fetch()`, the route returns JSON, and JS renders results + refreshes the checklist
in the DOM. This mirrors the existing `commission_line_edit` JSON pattern
(routes.py:1364, the UHC Fidelity AJAX edit) and reuses the existing vanilla
drop-zone JS (commission.html:523-530). No new dependencies.

## The five items

### 1. One themed success banner (fix the double banner)
Flash messages render TWICE — in `base.html:906` AND `commission.html:196` — so every
message shows above AND below the page title. **Fix:** delete the duplicate
`get_flashed_messages` block from `commission.html`; keep the single render in
`base.html`. Restyle the `.alert`/`.alert-success` classes to the Founders theme
(green success via `--green`/`--surface`, rounded `--radius`, brand type) so it
matches the rest of the UI. NOTE: with the AJAX upload (below) the upload path no
longer flashes at all — results render inline — so this mainly cleans up flashes
from *other* actions (delete, etc.); the double-render fix still applies to all.

### 2. Two clearly-labeled month controls; upload defaults to current − 1
Two DIFFERENT month controls that AJ conflates today:
- **Viewing period** (top, `ca-period-form`, `name="period"`, GET) — filters WHICH
  month's statements are shown. Relabel to **"Viewing: [month] ▾"**.
- **Upload attribution** (in the upload box, `name="statement_month"`) — what month an
  uploaded file is ATTRIBUTED to. Relabel to **"Attribute this statement to: [month]"**.
  **Default it to current month − 1** (commissions pay a month behind: in July it
  defaults to **June**). Helper text: *"Commissions pay one month behind, so this
  defaults to last month — change it only if this file is for a different month."*
- Keep them visually distinct (viewing top-left as-is; upload month lives inside the
  upload card with its explicit label) so it's obvious each does a different thing.
- **Backend:** the route already resolves `statement_month` from the form → keep that;
  the DEFAULT the template renders changes from `current_month` to `current_month − 1`.
  Compute a `default_upload_month`/`default_upload_month_iso` in the view (previous
  calendar month) and use it for the `<input type="month">` value + the label.

### 3. Multi-file staging with per-file remove (before upload)
- The file input becomes `multiple`; the drop-zone accepts MANY files (drag-drop all
  at once OR browse-select multiple). Files ACCUMULATE across successive drops.
- A **staging list** renders each staged file BEFORE submit: **full filename** + a
  **✕ remove** control per row. "Change" = remove + re-add (standard). Held
  client-side in a JS array / `DataTransfer` (no upload happens yet).
- One button: **"Upload & Parse (N files)"** (N updates live). Disabled when 0 files.
- Vanilla JS, extending the existing `caDrop`/`caFile` handlers — no framework.

### 4. Per-agent breakdown for per-agent carriers (BCBS)
The carrier checklist (`ca-checklist`, commission.html:493-500) shows carrier-level
(✓/○). For carriers in `PER_AGENT_CARRIERS` (BCBS, Devoted, Healthspring) add an
**expandable per-agent sub-list**: each agent with an **active contract** for that
carrier shows **✓ (their file is in this period)** or **○ (missing)**.
- **Expected agents** = `AgentCarrierContract` rows with `carrier=<carrier>` and
  `is_active=True` (the authoritative "who writes this carrier").
- **Uploaded signal** = the distinct `agent_id`s on the selected period's persisted
  `CommissionLineItem` rows for that carrier. Verified on prod: BCBS June rows are
  100% agent_id-populated (205/205), so `agent_id` alone is the reliable signal — an
  agent is "uploaded" iff they have ≥1 line item for that carrier+period. (A
  P-Number→`AgentCarrierContract.id_value` fallback is only needed if a future statement
  has null-agent rows; treat as optional hardening, not required.)
- New helper `per_agent_upload_status(agency_id, carrier, period_label)` →
  `[{agent_name, uploaded: bool}, …]` sorted by name. Lives in `recap.py` (near the
  other overview builders) or `routes.py`; pure read, agency-scoped.
- AJ sees who's in / still owed WITHOUT triggering the duplicate guard.

### 5. Multi-file upload: import the good, reject the bad with reason + fix
`commission_upload` changes from single-file to `request.files.getlist("file")` and
processes each file **independently**:
- Each file: its own `try` + a **savepoint (`db.session.begin_nested()`)** so one
  file's failure rolls back ONLY that file and never blocks the others.
- On success: commit that file's nested transaction; record a result
  `{filename, ok: true, carrier, agent_or_scope, rows, gross, period}`.
- On failure (parse error / `BcbsColumnError` / unsupported carrier / no rows):
  rollback that file's savepoint; record `{filename, ok: false, error: <specific
  reason>, fix: <how to fix, if known>}`. Reuse the specific messages already built
  (BcbsColumnError names the missing column; unsupported-carrier names the carrier).
- Route returns **`jsonify(results=[…], summary={imported: n, rejected: m},
  overview=<refreshed checklist data>)`** — NO redirect, NO flash.
- **JS renders inline:** a per-file outcome list appears below the upload box —
  green **"✓ BCBS · Brian Freeman — 69 rows, $2,216.97 → June 2026"**, red
  **"✗ AnjPatel.xlsx — could not find a 'Commission' column (headers seen: …). Fix:
  check the column names / re-export from Tidewater."** The carrier checklist +
  per-agent status + trust strip repaint from the returned `overview` (or a small
  follow-up GET of the overview fragment). The staging list clears the succeeded
  files, leaving failed ones staged for a fix-and-retry.

## Architecture

- **`app/templates/commission.html`:** relabel the two month controls (#2); the upload
  box gets `multiple` + a staging-list container + a results container; a `<script>`
  block (extending the existing drop-zone JS) for staging (add/remove/accumulate),
  the fetch submit, and rendering results + repainting the checklist; the per-agent
  expandable checklist markup (#4). Remove the duplicate flash block (#1).
- **`app/commission/routes.py` `commission_upload`:** multi-file loop with per-file
  savepoint + result accumulation; return JSON instead of redirect. The existing
  per-file ingest logic (detect → normalize → ingest → ledger) is wrapped in the loop
  unchanged. Compute `default_upload_month` (current − 1) for the GET render of the
  page.
- **New helper `per_agent_upload_status(agency_id, carrier, period_label)`** (#4) — in
  `recap.py`. Consumed by the page's overview builder (`commission_audit_overview`) so
  the checklist template has per-agent data.
- **`app/templates/base.html`:** theme the `.alert` classes (#1). No structural change.
- **Backwards-compat:** if a non-AJAX POST hits `commission_upload` (JS off), fall back
  to the current redirect+flash behavior so the page still works. (The route detects
  `X-Requested-With`/`Accept: application/json` like `commission_line_edit` does.)

## Testing
- **#5 partial success:** post 2 good + 1 bad file → JSON `summary.imported == 2`,
  `rejected == 1`, the bad result carries the specific reason; the 2 good statements
  persist; the bad one wrote nothing (savepoint rolled back).
- **#2 default month:** the page renders the upload `statement_month` defaulting to the
  previous calendar month (July → `2026-06`).
- **#1 single banner:** `commission.html` no longer contains a `get_flashed_messages`
  block; base.html renders exactly one.
- **#4 per-agent status:** an agent with an active BCBS contract + no line items this
  period → `uploaded: False`; with line items → `True`; agency-scoped.
- **#3 staging:** JS unit-lite / manual — staging accumulates, remove drops one, the
  count + button label update. (Render-verify in a browser on deploy.)
- **AJAX contract:** `commission_upload` returns JSON for an XHR post; a non-XHR post
  still redirects (back-compat).
- Real-file smoke on deploy: multi-select the June BCBS files → all import, checklist
  shows each agent ✓, no redirect.

## Definition of done
- One themed success banner; no double render.
- Two unmistakably-labeled month controls; upload defaults to current − 1.
- Drag/select MANY files; staging list with full names + remove; one Upload & Parse.
- Good files import, bad files rejected inline with specific reason + fix; nothing
  half-written; no redirect / no page reload.
- Per-agent ✓/○ breakdown for BCBS (and other `PER_AGENT_CARRIERS`) from active
  contracts × this period's uploaded rows.
- Opus whole-branch review (money/upload path) + browser-verify + deploy.

## Explicitly out of scope (YAGNI)
- Changing the parsers themselves (done separately; this only orchestrates them).
- A separate results page/route (everything is inline per the hard constraint).
- Reworking the viewing-period picker's data (only its label changes).
- Per-agent status for agency-wide carriers (Humana/Aetna/UHC are one file — carrier-
  level ✓/○ is correct for them; the per-agent sub-list is only for `PER_AGENT_CARRIERS`).

## Reuse (don't rebuild)
- `commission_line_edit` (routes.py:1364) — the JSON-return + XHR-detection pattern.
- The existing `caDrop`/`caFile` drop-zone JS (commission.html:523-530).
- `PER_AGENT_CARRIERS` + `file_scoped_prefix` (ledger.py) — per-agent file model.
- `AgentCarrierContract` (`carrier`, `is_active`, `id_value`) — expected-agents source.
- `commission_audit_overview` / `recap.py` builders — where the checklist data comes from.
- The per-file ingest pipeline in `commission_upload` — wrapped in the loop, unchanged.
- `BcbsColumnError` + unsupported-carrier messages — the specific rejection reasons.
