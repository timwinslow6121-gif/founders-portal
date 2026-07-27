# Plan-Summary v2 — Slice 1: Re-skin + Agent Quick-Info — Design

**Date:** 2026-07-25
**Status:** Approved (brainstorm complete) — ready for implementation plan
**Author:** Tim + assistant
**Visual reference:** `docs/mockups/Plan Summary Mockup/plan_benefits_redesign.tsx` (Gemini, React/Tailwind, hardcoded for one UHC MAPD plan) + the ChatGPT mockup PNG. Full vision + decisions: memory `plan-summary-consumer-pro-redesign.md`.

## Context: this is SLICE 1 of a decomposed feature

Plan-summary v2 is 6 separable pieces. This spec is **only** the re-skin + the
Agent Quick-Info panel — the piece that ships a visible win with **NO new data
model**. The other five are explicitly deferred, each to its own follow-on spec:

- **IN/OON global toggle** — needs an in-net/OON value *pair* per benefit (we
  store one value today). Data-model change. OUT.
- **Drug-tier checker** — needs the messy 133-page per-carrier formulary parsed.
  OUT (Tim's earlier decision).
- **Network Snapshot** (Pro) — needs a new agent-maintained `Provider` table +
  "plays nice / bills OON" flag. OUT.
- **Service-area bar** + **Enrollment "your-book" snapshot** (Pro) — derivable
  but their own logic. OUT.

## What slice 1 builds

Re-skin the existing plan-detail page (`/carriers/<id>`, `plan_detail.html` +
`app/plan_sections.py`) to the Gemini look, **type-adaptive across all 5 plan
types**, with a **Consumer/Pro view toggle**, and add the **Agent Quick-Info**
Pro panel. Everything renders from the existing `Plan.details_json` + the
`plan_sections.py` per-type config built 2026-07-13. No migration.

## Section 1 — Consumer / Pro toggle

A top-right toggle (styled like the existing theme sun/moon toggle), vanilla JS.
**Both views are rendered into the page server-side; JS shows one and hides the
other** — instant, no round-trip — persisted to `localStorage['fp-plan-view']`
(default **Consumer**). A no-flash pre-paint pattern is not needed (the page is
behind login; a brief default-Consumer paint is fine), but the JS applies the
saved choice on load.

- **Consumer view** = customer-facing rich layout (KPI cards + benefit cards) —
  the view an agent flips to while screen-sharing with a customer.
- **Pro view** = the agent layout — KPI cards stay, adds the Agent Quick-Info
  panel (Section 4).
- **Role gating:** the Agent Quick-Info panel (commission) is rendered into the
  DOM **only for a logged-in agent/admin** — so it never appears in a
  customer-facing screen's source. The whole portal is behind OAuth, so
  "Consumer" is not public; it is simply the customer-safe view.

## Section 2 — Type-adaptive KPI cards

Each plan type gets its own top KPI row in the new visual treatment (card /
gradient style translated from the mockup to Founders theme tokens). Driven by a
new per-type KPI config in `plan_sections.py` (alongside the existing
`sections_for(plan)`), so **no type ever shows an N/A card**:

- **Part C (MAPD / MA)**: **Premium** card (with a Part-B-premium transparency
  note — a single hardcoded current-year constant in `plan_sections.py`, e.g.
  `PART_B_PREMIUM_2026 = 185.00`, rendered as "+ $185.00/mo Part B (2026)"; NOT
  stored per-plan, NOT invented — one labeled constant, updated yearly), **MOOP**
  card, and the **gradient "Top Extra Benefits" card** (OTC / Dental / Eyewear —
  the one Tim specifically loves).
- **PDP**: Premium, Rx deductible, drug-tier summary.
- **Medigap**: Premium (age-rated note "Age-rated — see quote"); body = the
  static Medigap coverage grid.
- **DVH**: Annual max, dental / vision / hearing summary.
- **Hospital Indemnity**: base benefit + riders.

Values come from `details_json` via the existing provenance/section accessors;
the KPI config only chooses *which* keys surface as headline cards per type.

## Section 3 — Benefit body (re-styled sections)

The existing per-type sections (`sections_for(plan)` — Costs / Medical / Extras /
Drugs for Part C, the Medigap grid, the DVH matrix, etc.) are re-styled into the
mockup's card/section look. **Same data, nicer presentation.** Founders theme
tokens replace the mockup's generic blue/slate (`--blue`, `--green`, `--surface`,
etc.; light + dark). Member count stays the sole headline stat (as today). The
visual hospitalization Days-1-6-vs-7+ bar (mockup) is a nice-to-have for Part C
if the data is present; otherwise a plain SNF row (no fabricated data).

## Section 4 — Agent Quick-Info panel (Pro only)

Replaces the current "collapsed admin footer" home for commission. Rendered
**only in the Pro view, only for a logged-in agent/admin**. Shows, for THIS plan
at the **viewing agent's own** contract split:

- **New-enrollment commission** = `Plan.comm_initial` (the plan's rate).
- **Renewal commission** = `Plan.comm_renewal`.
- **Agency split** = the viewing agent's `AgentCarrierContract.split_rate` for
  this plan's carrier (fall back to the agency default 0.55 if no contract row).
- **Agent take** / **Projected annual** = derived from the plan rate × the
  agent's split (display-only; reuse the existing split math if a helper exists,
  else compute inline — no stored value).
- **HRA bonus** = `Plan.hra_bonus` if set.

Because the split is read from the **viewing agent's own** contract, two
different agents see two different numbers and there is **no cross-agent leak**.
Admins see it too (their own contract / the agency default).

## Section 5 — Testing & safety

- Renders without error for a plan of **each of the 5 types**; the right KPI set
  per type; **no N/A cards**.
- **Consumer/Pro toggle:** both views present in the DOM; JS switches + persists
  to localStorage; the **Agent Quick-Info panel is ABSENT from the DOM** when
  there is no logged-in agent context (role-gate test) — never leaks into a
  customer-facing source.
- **Commission is the viewing agent's own rate:** two agents with different
  `split_rate` on the carrier → two different displayed numbers; no other agent's
  numbers appear.
- Founders theme **light + dark** both render.
- **Headless-browser screenshot verification** (the visual IS the deliverable) +
  opus whole-branch review. No migration.

## Files

- Modify: `app/plan_sections.py` (add a per-type **KPI config** + any accessor for
  the headline values; keep `sections_for` as the body config).
- Modify: `app/templates/plan_detail.html` (the re-skin: KPI card row, Consumer/Pro
  wrappers + toggle, re-styled sections, Agent Quick-Info Pro panel).
- Modify: `app/carriers.py` (the plan-detail route — pass the viewing agent's
  `AgentCarrierContract.split_rate` for the plan's carrier + the computed
  Agent-Quick-Info numbers to the template; role flag).
- Possibly: a small CSS block in `plan_detail.html`'s `{% block styles %}` using
  Founders tokens (no new global CSS unless a reusable card class earns it).

## Out of scope (each its own follow-on spec)

IN/OON toggle · drug-tier checker · Network Snapshot (Provider table) ·
service-area bar · Enrollment "your-book" snapshot. See the memory note for their
designs.
