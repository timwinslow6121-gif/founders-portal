# UHC Fidelity View — Performance + Filter Persistence

_Date: 2026-06-26 · Status: diagnosed against real code + live row counts; spec ready.
**Build after `feat/stub-creation-prevention` (item 1) deploys.** This is FRONT-END + one
endpoint's response shape — it does NOT change `edit_line_split` or any commission MATH
(the edit storage contract stays identical). Still a money-adjacent page → opus whole-branch
review + real-browser verify with a real UHC statement (the ~4k-row one) before done._

## The two problems (AJ, 2026-06-26)

1. **The UHC Fidelity view is slow / unresponsive / times out.**
2. **After AJ saves an edit, the agent filter resets** — he has to re-click the agent every
   time, which compounds painfully with #1 (each edit forces a slow full reload + a re-filter).

## Root causes (confirmed)

**The May UHC statement has 3,981 `commission_line_items`** (statement id=62). The Fidelity
template (`app/templates/commission_fidelity.html`) renders **every** row plus, for EACH row, a
hidden `<tr class="fd-editrow">` containing a **full edit form** — including an agent `<select>`
with ~10 `<option>`s. So the browser is handed roughly:
- ~4,000 data rows
- ~4,000 hidden edit-form rows
- ~40,000 `<option>` elements

= tens of thousands of DOM nodes in one payload. **The server query is fine** (`fidelity_view`
already batch-loads agent names — no N+1; the per-row helpers `split_breakdown`,
`_calc_explanation`, `friendly_payment_type`, `display_name` are pure, no DB). **The browser
chokes on DOM size** — that's the slowness/timeout. (A `template.fd-deferred` mechanism already
exists in the template, a prior partial attempt, but it's insufficient at 4k rows.)

**Filter reset:** the edit is a **full-page POST** (`commission_fidelity.html:100-103` →
`commission_line_edit`, routes.py:1354) that redirects to `next` (`request.full_path`). The
filter is **client-side JS only** (`agentSel.value` applied in the browser, never in the URL).
A full reload destroys the DOM → the JS filter resets to empty → AJ re-picks the agent. The
filter state lives only in the DOM, which the post-edit reload throws away.

**Both collapse into one fix:** if edits save via AJAX (repaint just that row, no reload) the
filter never resets, AND if the ~4,000 hidden forms aren't rendered up front, the page is light
and fast. Plus persist the filter so even a hard reload restores it.

## The fix (full — Tim's choice)

### A. Lazy edit forms (kills the main DOM bloat)
Do NOT render a hidden edit form per row. Render only the data rows + the small set of agents
once (in a JS-accessible form, e.g. a `<template>` or a JSON blob). When AJ clicks **Edit** on a
row, build the ONE edit form in JS from the template + that row's data attributes
(`data-raw`, `data-agent-id`, `data-agent`, `data-founders`, etc., already partly present on
`tr.fd-row`). This removes ~4,000 forms + ~40,000 `<option>`s — the bulk of the DOM. (Optionally
also windowing/virtualization for the data rows, but lazy forms alone should make the page
responsive; measure first, add row-virtualization only if still heavy.)

### B. AJAX edit-save (instant, and fixes the filter reset)
`commission_line_edit` (routes.py:1354) keeps its existing form-POST behavior for the no-JS
fallback, but when the request is AJAX (detect via `X-Requested-With: XMLHttpRequest` or
`Accept: application/json`), it returns **JSON** instead of a redirect:
```json
{ "ok": true,
  "row": { "id": <id>, "agent": <agent$>, "founders": <founders$>,
           "agent_id": <id>, "agent_name": "<name>",
           "classification": "<cls>", "type_label": "<label>",
           "split_rate": <rate> },
  "sibling": { ... } | null,        // the ::ovr override line if one was created/changed/removed
  "balances": { "raw_total": ..., "agent_total": ..., "founders_total": ... } }
```
The values come from the SAME `split_breakdown` / `fidelity_view` row-builder logic (reuse it for
one line — do NOT duplicate the math). On success the JS repaints that row's agent/founders/agent-
name/type cells in place and updates the totals, with NO page reload. Errors (the sum-≠-raw
guard, bad agent) return `{ok: false, error: "..."}` and the JS shows it inline by the form.
**`edit_line_split`'s storage contract is unchanged** — this is purely the response shape +
client repaint.

### C. Persist the filter (belt-and-suspenders)
Keep the selected filters (agent, type, search, min/max) in the **URL query string** (and/or
`localStorage`), applied on page load. So even a hard reload or a no-JS POST fallback restores the
filter. With AJAX saves (B) the page never reloads anyway, but URL-persisted filters also make the
view shareable/bookmarkable and survive the manual refresh AJ sometimes does.

## Out of scope / unchanged
- `edit_line_split` and all commission split MATH — untouched.
- The fidelity balance invariant (Σagent + Σfounders ≈ Σraw) — unchanged; AJAX repaint just keeps
  the displayed totals in sync after an edit.
- Other carriers' Fidelity views benefit automatically (they share the template) but are small, so
  the win is mostly UHC.

## Verify
- Real-browser test on the **May UHC statement (id=62, ~3,981 rows)**: page loads responsively
  (no timeout), Edit opens instantly, Save updates the one row WITHOUT a reload, and **the agent
  filter stays applied after a save**. Confirm an edit still persists correctly to the DB (re-open
  the page → the edited split is there) and the audit revision is still written.
- No-JS fallback: with JS disabled, the form still POSTs and redirects back with the filter
  restored from the URL (graceful degradation).
- The fidelity totals/balance line updates correctly after an AJAX edit (matches a fresh reload).

## Files (expected; confirm at build)
- `app/templates/commission_fidelity.html` — lazy edit form (one, built on demand); AJAX submit +
  in-place row repaint; filters read/written to the URL; render the agent list once.
- `app/commission/routes.py` `commission_line_edit` — return JSON on AJAX (keep redirect for
  no-JS), reusing the existing row-builder for the updated line('s) values.
- `app/commission/recap.py` — if helpful, a small `fidelity_row(line)` extraction so one line's
  JSON values come from the SAME code as the table (avoid duplicating split logic).
- No migration. No change to commission math.
