# Quarantine Workbench — Design Spec

**Date:** 2026-06-19
**Status:** 📝 SPEC — Tim-approved decisions; ready for plan. NOT built yet.
**Context:** Part of the Commission Trust System (Phase A polish). Today the only way to
reach quarantined commission rows is per-statement: Agent Commissions module → month picker →
pick month → Quarantine button. There's no left-nav link and no all-months view. AJ needs a
fast triage surface to drain quarantine to zero each cycle.

## Goal
A standalone **Quarantine Workbench** that surfaces every `needs_manual_review` commission
line item in one place, defaulting to ALL months, with quick filters and an amount sort so
identical amounts (e.g. the $125×7, $491.58×3 clusters) can be resolved in a batch. Quarantine
is a transient WORKING QUEUE (goal: near-empty) — so the design stays lightweight: no
pagination, no client-side data model.

## Decisions (Tim-approved 2026-06-19)
1. **Left-nav link** "Quarantine" in the admin Commissions section (base.html), with a count
   badge (total quarantined across all periods) — mirrors the Unassigned badge pattern.
2. **Server-side filters + sort via URL params** (mirrors the agent-commissions month picker —
   consistent, robust, survives refresh/bookmark, least code). Dropdowns submit on change.
3. **Default view:** all months/carriers/agents, **grouped by month header, newest month
   first** (e.g. ▾ June 2026 (32) … ▾ May 2026 (48) …).
4. **Filters (URL params, all optional):** `period` (month label), `carrier`, `agent` (id).
   Empty/absent = all. Carrier filter included even though all quarantine is UHC today (future-
   proof + consistent).
5. **Amount sort** `sort=amount_asc|amount_desc`: **flattens** the month grouping into ONE list
   sorted by amount (with a Month column), so identical amounts across months cluster together.
   Clearing the sort returns to month grouping. Default (no sort) = grouped by month.
6. **Rows reuse the existing resolve/undo/edit machinery** — same `_quarantine_row` shape +
   the in-line resolve form + (after Plan 1) the Undo/Edit controls. No new resolution logic.

## Architecture
- **New helper** `quarantine_workbench(agency_id, *, period=None, carrier=None, agent_id=None,
  sort=None)` in `app/commission/recap.py`: one query over `CommissionLineItem` filtered by
  `agency_id` + `classification="needs_manual_review"` + the optional filters; ordered by
  amount when `sort` is set, else by (period desc, carrier, member). Returns:
  `{count, total, sort, grouped: bool, groups: [{period_label, count, total, rows:[...]}],
  flat: [...], by_carrier: {...}, filter_options: {periods:[...], carriers:[...], agents:[...]}}`.
  When `sort` is set → `grouped=False`, `flat` populated; else → `grouped=True`, `groups`
  populated. `filter_options` lists the distinct periods/carriers/agents that HAVE quarantine
  (so the dropdowns only show meaningful choices).
- **New route** `GET /admin/commissions/quarantine` → `commission_quarantine_workbench`
  (admin-only, agency-scoped) reading the URL params, calling the helper, rendering a new
  template. (The existing per-statement route `/admin/commissions/<id>/quarantine` stays.)
- **New template** `commission_quarantine_workbench.html` — filter bar (period/carrier/agent
  selects + amount-sort toggle, all `onchange`-submit, styled like the agent-commissions
  picker), then either month-grouped sections or the flat amount-sorted table. Each row carries
  the existing resolve form + Undo/Edit controls (shared partial pattern from
  commission_quarantine.html).
- **Nav badge:** a small count helper (total needs_manual_review for the agency) exposed to
  base.html the same way `unassigned_customer_count` is (context processor or per-request).

## Non-goals / guardrails
- No pagination, no client-side filtering (quarantine is meant to be small/transient).
- Admin-only + agency-scoped on the route and every query.
- Do NOT duplicate resolve/undo/edit logic — reuse the existing routes + row template pattern.
- The existing per-statement and per-period (`/review`) quarantine views stay as-is.

## Verification
- Left-nav "Quarantine" link appears for admins with a correct count badge.
- Default page shows all months grouped newest-first; counts/totals per month correct.
- Filtering by period/carrier/agent narrows correctly; "all" when cleared.
- `sort=amount_desc` flattens + clusters identical amounts across months (a $491.58 from May
  and June sit adjacent); `sort=amount_asc` reverse; clearing returns to grouping.
- Resolve / Undo / Edit work from this page exactly as from the per-statement page.
- Suite green; verified on real Postgres (the live June/May UHC quarantine).
