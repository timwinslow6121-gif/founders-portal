# Plan-Summary v2 — Slice 2: Service-Area Bar — Design

**Date:** 2026-07-30
**Status:** Approved (brainstorm complete) — ready for implementation plan
**Author:** Tim + assistant
**Context:** Slice 2 of the decomposed plan-summary v2 feature. Slice 1 (re-skin + Consumer/Pro toggle + Agent Quick-Info) shipped 2026-07-27 (merge d2ed2a8). Vision: memory `plan-summary-consumer-pro-redesign.md` (the ChatGPT mockup's "service-area bar" panel). Builds on the re-skinned `plan_detail.html` + `app/plan_sections.py` + `app/carriers.py plan_detail` route.

## What this builds

A slim service-area bar at the **top of the plan-detail page** (`/carriers/<id>`), above the KPI cards, in **both Consumer and Pro views** (customer-safe — geography only, no commission). It answers "where is this plan available?" at a glance, from CMS Landscape county data loaded into a new table.

## Grounding (verified against real data 2026-07-30)

- `Plan.service_area` today is inconsistent free text ("Western NC", "NC", "NC Statewide", "National") and **null on ~126 of ~154 current plans**. Not usable as-is for county counts.
- The **CMS Landscape CSV** (`docs/Medicare Landscape Files/CY2026_Landscape_202603/CY2026_Landscape_202603.csv`) has **one row per (Contract ID, Plan ID, Segment ID, County)** — columns `State Territory Abbreviation` (col 4), `County Name` (col 6), `Contract ID` (col 7), `Plan ID` (col 8), `Contract Year` (col 1). Verified: plan `H5253-041` → 100 distinct NC counties (statewide; NC has 100 counties). A Western-NC HMO yields its real subset.
- **Only Part C / PDP plans have a CMS contract ID** and appear in the Landscape. **Medigap / DVH / Hospital Indemnity have no CMS ID** and are absent from the file → no derivable county count for them.

## Section 1 — The bar (rendering)

Slim bar, Founders theme tokens (light + dark), above the KPI row, shared across both views (placed above the Consumer/Pro toggle so it renders once for both). Behavior by data availability, **never a fabricated/zero count**:

- **Has loaded county rows** (Part C / PDP): `📍 Available in NC · 100 counties` with a **"View all"** control that expands to show the county names (wrapped comma/chip list), vanilla-JS show/hide (same pattern as the slice-1 Consumer/Pro toggle). Collapsed by default.
- **No county rows** (Medigap / DVH / HI, OR a CMS plan not yet seeded / not in the file): a simple honest line — `📍 Available statewide in NC` if the plan's `service_area` free-text is empty, else `📍 {plan.service_area}`. No count, no "View all."
- Multi-state note: data carries `state`; the count/label is per state. Today the book is NC; if a plan has counties in >1 state the bar shows the primary (most-counties) state's line for this slice (multi-state expansion deferred — note only).

## Section 2 — Data model + seed

**New table `plan_service_areas`** (new migration — the next sequential number; current head is 038, so **verify the actual next number at build time** since other unbuilt specs also tentatively named 039):
- `id` (PK)
- `plan_id` (FK → plans.id, `ondelete="CASCADE"`, indexed)
- `agency_id` (FK → agencies.id, indexed, multi-tenant scoping)
- `state` (String, e.g. "NC")
- `county` (String, e.g. "Mecklenburg")
- Unique constraint on `(plan_id, state, county)` (idempotent re-seed, no dupes).

**Seed script `scripts/seed_plan_service_areas.py`** (idempotent, `--apply`/dry-run default, matches the existing `seed_plan_buckets.py` pattern):
- Reads the CMS Landscape CSV path (arg or default to the CY2026 file).
- Builds `(contract_id, plan_id, year) → set[(state, county)]` from the CSV, **skipping** rows whose `County Name` is a non-county sentinel (`All Counties`, blank).
- For each **`Plan` already in the DB** with a CMS ID (parse contract+plan from `cms_plan_id`, e.g. `H5253-041` → contract `H5253`, plan `041`) and matching `year`: **replace** that plan's `plan_service_areas` rows with the CSV's counties for it (delete-then-insert scoped to that plan_id, inside one transaction).
- Skips plans not carried (the ~40k Landscape plans not in the DB) and plans with no CMS ID (Medigap/DVH/HI).
- Prints a report: plans matched, counties loaded, plans skipped (no CMS ID / not in file), and any DB plan whose CMS ID wasn't found in the CSV.
- Re-runnable: safe to run again for a corrected file or a new-year Landscape (delete-then-insert per plan keeps it clean).

## Section 3 — Route + accessor + tests

**Accessor** (in `app/carriers.py` or a small helper): for the viewed plan, query `plan_service_areas` filtered by `plan_id` AND `agency_id=current_user.agency_id`. Return a `service_area` dict for the template:
- rows present → `{"mode": "counties", "state": <state with most counties>, "count": <int>, "counties": [<sorted county names>]}`
- no rows → `{"mode": "state", "label": plan.service_area or "Available statewide in NC"}`

**Route** (`plan_detail`): compute the dict, pass `service_area=<dict>` into the existing `render_template("plan_detail.html", ...)` (additive; no existing context key changed).

**Template** (`plan_detail.html`): bar markup above the toggle/KPI row + a small `{% block styles %}` addition (Founders tokens) + a vanilla-JS "View all" toggle (show/hide the county list; no round-trip). Autoescape on (county names are DB strings — no `|safe`).

**Tests:**
- `tests/test_plan_service_areas.py` (new): the accessor returns `counties` shape when rows exist (count + sorted list), `state` shape when none; agency-scoping enforced (a plan's rows under another agency are not returned).
- Seed-script test: given a small fixture CSV, matches a DB plan by CMS ID + year, loads its distinct counties, skips the "All Counties" sentinel and non-carried plans, and a second run produces no duplicates (idempotent).
- `tests/test_plan_detail_route.py` (extend): route passes `service_area`; template renders the county bar (count + expandable list present in DOM) for a plan with rows, and the state-line fallback for a plan with none.
- Headless-browser screenshot verification (the bar is a visual) — a Part C plan (county bar + expanded list) and a Medigap plan (state line), light + dark. Full suite green.

## Files
- Create: `app/models.py` → `PlanServiceArea` model + a new migration (the next sequential number — current head is 038; **verify the actual next number at build time**, as other unbuilt specs also tentatively named 039).
- Create: `scripts/seed_plan_service_areas.py`.
- Modify: `app/carriers.py` (`plan_detail` accessor + context).
- Modify: `app/templates/plan_detail.html` (bar + CSS + toggle JS).
- Create/modify tests as above.

## Out of scope (deferred to later slices / notes)
- **Per-client county match** ("is this plan available where *this customer* lives?") — needs client context the plan page lacks. Later slice.
- **County search box** on the bar.
- **Segment/benefit-by-county variation** (the `Segment ID` in the Landscape ties to `[[bcbs-cms-plan-segments]]`) — the count is per (contract, plan) across counties; segment detail is separate.
- **Editing UI** for service areas / manual county entry for Medigap/DVH/HI.
- **Multi-state plans** beyond showing the primary state's line.

## Deploy notes
The new migration (additive, new table — no change to existing rows). After deploy: `flask db upgrade`, then run `scripts/seed_plan_service_areas.py --apply` on the VPS (needs the Landscape CSV present — already in `docs/`). DB backup before the seed, per protocol. Standard restart.
