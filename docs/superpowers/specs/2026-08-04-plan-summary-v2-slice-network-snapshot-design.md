# Plan-Summary v2 — Network Snapshot — Design

**Date:** 2026-08-04
**Status:** Approved (brainstorm complete) — ready for implementation plan
**Author:** Tim + assistant
**Context:** A plan-summary v2 slice (the "PPO tribal-knowledge gem"). Slices 1 (re-skin + Consumer/Pro toggle + Agent Quick-Info) and 2 (service-area bar) shipped. The "your-book snapshot" slice was brainstormed and DROPPED (not actionable — see BACKLOG). Vision: memory `plan-summary-consumer-pro-redesign.md`. Builds on `plan_detail.html` + `app/carriers.py`.

## What this builds

A **provider-first, agency-shared tribal-knowledge directory** + a Pro-view panel on the plan page. It answers the make-or-break small-market question an agent hits mid-sale: *"For this plan's carrier, which local providers are in-network — and for a PPO, which ones will actually bill out-of-network?"*

**Grounding (Tim's real case):** In small markets (Kannapolis and nearby towns) there are often only 1–2 providers of a given type — one gastro clinic, a few family doctors/dentists. "NE Digestive is in-network with Humana + BCBS but NOT Devoted, and won't bill a Devoted PPO on an OON basis" is a single fact that decides which plan a customer can even use. In Charlotte (many options) it barely matters; in Kannapolis it's everything. Devoted (and other) PPO plans nominally let a customer see "any" doctor, but only if the provider will bill OON directly — some do ("nice of them"), some don't ("turds"), and the customer otherwise pays upfront and files for reimbursement. This is pure agent tribal knowledge that lives nowhere else; NOT parsed from carrier provider directories (one UHC directory ≈ 7,000 pages for one plan).

Two surfaces:
1. **Providers management page** (`/providers`) — agency-shared list / add / edit, modeled on the existing Pharmacies page.
2. **Plan-page Pro panel** — for the viewed plan, shows providers in-network with that plan's carrier, grouped by county/town, with the "plays nice / bills OON" flag surfaced for PPO plans + a collapsed "not in-network here" section.

## Section 1 — Data model

**New `Provider` table** (agency-scoped, mirrors `Pharmacy`), migration adds it:
- `id`, `agency_id` (FK agencies.id, indexed)
- `name` (String, not null)
- `provider_type` (String — free text with datalist suggestions like gastro / family / dentist / cardiology; specialties are open-ended, NOT a fixed enum)
- `city` (String), `county` (String, indexed — drives the plan-page grouping)
- `phone` (String, optional)
- `bills_ppo_oon` (String — `yes` | `no` | `unknown`, default `unknown`; the "plays nice with PPO OON" gem)
- `notes` (Text, optional — "only gastro in Kannapolis", "front desk hostile to PPO OON")
- `created_by_id` (FK users.id), `created_at`, `updated_at`

**`provider_carriers` join table** — which carriers a provider is IN-network with (a set per provider):
- `provider_id` (FK providers.id, PK), `carrier` (String, PK). One row per (provider, accepted-carrier). Carrier values from the existing `CARRIERS` list in `app/carriers.py`. Modeled on the `pharmacy_agents` join.

Example: "NE Digestive accepts Humana + BCBS, not Devoted, won't bill PPO OON" = one `Provider` row (`bills_ppo_oon='no'`, county 'Cabarrus', type 'gastro') + two `provider_carriers` rows (Humana, BCBS).

One migration (Provider table + provider_carriers join). No change to existing tables.

## Section 2 — Providers management page (`/providers`)

New `providers_bp` blueprint (`app/providers.py`) + templates, modeled on `pharmacies_bp`:
- **List** (`GET /providers`): all agency providers grouped by county. Each row: name, type, city/county, accepted-carrier chips, a plays-nice badge (green ✓ / red ✗ / grey ? for `bills_ppo_oon`), notes preview. Agency-scoped.
- **Add** (`GET/POST /providers/new`), **Edit** (`GET/POST /providers/<id>/edit`): name, type (text input + `<datalist>` suggestions), city, county, phone, carriers-accepted multi-checkbox (from `CARRIERS`), `bills_ppo_oon` radio (yes/no/unknown), notes.
- **Delete** (`POST /providers/<id>/delete`): confirm, admin-only (matches Pharmacies).
- **Access gate:** shared agency directory. **Edit (add/edit/delete) gated on `can_edit_shared_data(current_user)`** (senior_agent + admin edit; regular agents view — viewers see no edit controls). Every query agency-scoped (`agency_id=current_user.agency_id`). Delete stays admin-only.
- **Nav:** a "Providers" link under Tools in `base.html` (near Partner Pharmacies), visible to all agents; add/edit controls only render for editors.

## Section 3 — Plan-page Pro panel

A new panel in the **Pro view** of `plan_detail.html` (alongside Agent Quick-Info) — rendered ONLY in Pro (agent-facing; NOT in the customer-facing Consumer view), like the Agent Quick-Info panel.

- **Accessor** `providers_for_plan(plan, agency_id)` in `app/carriers.py` (agency-scoped) returns:
  - `in_network`: providers whose `provider_carriers` includes `plan.carrier`, grouped by county (dict county → sorted provider list).
  - `not_in_network`: ALL agency providers that do NOT accept `plan.carrier`, grouped by county (the objection set — "NE Digestive ✗ not in network on Devoted"). Scoped to all recorded providers, NOT only counties that happen to have an in-network provider — otherwise a town whose sole gastro clinic is out-of-network (exactly the Kannapolis case) would be silently dropped. This is the whole point: surface the provider that ISN'T available on this plan.
  - `is_ppo`: `(plan.plan_subtype or "").lower() == "ppo"` — drives whether the plays-nice flag is emphasized.
- **Render:**
  - Header "Network — local providers".
  - In-network providers grouped by county heading → rows (name · type · phone). **For PPO plans**, each row prominently shows the plays-nice flag: ✓ "bills OON" (green) / ✗ "won't bill OON — customer pays upfront" (red) / ? "OON billing unknown" (grey). For non-PPO plans the flag is omitted (OON isn't the HMO question).
  - A **collapsed "Not in-network here" section** (vanilla-JS toggle, like the service-area "View all") listing the `not_in_network` providers by county — the sharp objection, present but not dominating.
  - **Empty state:** if no providers recorded for this carrier → "No providers recorded for {carrier} yet." + (for editors) an "Add them on the Providers page" link. Same honest-empty-state pattern as the benefits note.
- Founders theme tokens (light + dark); text `var(--ivory)`/`var(--slate)` never `var(--ink)`; provider names/notes are DB strings via autoescape (no `|safe`).

## Section 4 — Testing & safety

- **Model/migration:** Provider + provider_carriers persist; agency-scoped; carrier link add/remove works; unique (provider_id, carrier) on the join.
- **Accessor** `providers_for_plan`: in-network grouped by county for the plan's carrier; not-in-network set = ALL agency providers not accepting the carrier, grouped by county (incl. a county with only out-of-network providers); agency-scoping enforced (a provider under another agency is never returned); `is_ppo` true only for `plan_subtype=='ppo'`.
- **Management page:** list groups by county; add/edit persists carriers + bills_ppo_oon; `can_edit_shared_data` gate — a viewer (regular agent) sees the list but the add/edit/delete controls + routes are gated (POST by a non-editor → 403); agency-scoped (no cross-agency rows).
- **Plan panel:** renders in Pro view DOM, NOT in the Consumer path; empty-state note when no providers for the carrier; PPO plan shows the plays-nice flag, HMO plan omits it; the not-in-network collapsed section renders when such providers exist.
- **Headless screenshot verification** (panel with in-network providers + PPO plays-nice flags + expanded not-in-network section; empty state; the management list + form) + full suite green. One migration.

## Files
- Modify: `app/models.py` (Provider model + provider_carriers join) + migration (next sequential number — verify head at build time).
- Create: `app/providers.py` (`providers_bp`) + register in `app/__init__.py` (3-line pattern).
- Create: `app/templates/providers_list.html`, `app/templates/providers_form.html`.
- Modify: `app/carriers.py` (`providers_for_plan` accessor + pass to plan_detail context).
- Modify: `app/templates/plan_detail.html` (the Pro-view Network panel + CSS + the not-in-network toggle JS).
- Modify: `app/templates/base.html` (Providers nav link under Tools).
- Tests: `tests/test_providers.py` (model + management page + gate), extend `tests/test_plan_detail_route.py` (accessor + panel render).

## Out of scope (deferred / noted)
- **Parsing carrier provider directories** — explicitly NOT done; this is manual tribal knowledge.
- **Per-individual-plan (PBP) network status** — rejected in brainstorm; network is provider→carrier, not per-PBP.
- **Provider ↔ customer linkage** ("which of my customers see Dr. X") — a possible future tie-in, not this slice.
- **Network-type (HMO vs PPO) granularity on the carrier link** — the carrier link is per-carrier; the PPO-OON question is handled by the plan's own `plan_subtype` + the provider's `bills_ppo_oon` flag, not a per-network carrier link. Sufficient for the grounding cases.
- The **your-book snapshot** slice (dropped) and the **AEP formulary-change segmentation engine** (its own future feature) are unrelated to this slice.

## Deploy notes
One migration (additive — new table + join, no change to existing rows). Standard deploy: `flask db upgrade`, restart. No seed required (agents build the directory); optionally Tim seeds a few real providers post-deploy to prove value. DB backup before migration, per protocol.
