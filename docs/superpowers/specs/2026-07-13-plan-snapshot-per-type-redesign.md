# Plan Snapshot (per-plan-type condensed SOB) — Design Spec

**Status:** Draft — brainstormed & validated 2026-07-13. Ready for user review → implementation plan.

**Context:** Founders portal, `/carriers/<plan_id>` (plan detail). The current page is a generic key-value dump that shows the SAME fields (medical benefits, drug tiers, PCP copay) for EVERY plan regardless of type — so a Medigap or DVH plan shows nonsense "PCP copay / Drug Tier 1" rows, and lots of empty "—". This redesigns it into a **condensed SOB reference card** that renders only the benefits relevant to each plan type, in the Founders theme, across all plans.

---

## 1. Purpose & framing (locked with Tim)

- This is a **quick benefit snapshot / condensed SOB**, NOT a KPI dashboard or deep analytics page. Tim: "just the normal plan benefits we typically discuss or the ones that cause a lot of questions."
- **No KPI cards.** The only headline number is **# of active members** (ties the plan back to the book, links to the member list). Everything else is benefit line-items, not KPIs.
- The page must render **only the fields relevant to the plan's type** — no empty "—" rows for irrelevant benefits.
- Founders theme (global pills already in base.html; cards/tokens; light+dark). Applied to ALL plans via one type-aware template.

## 2. Page skeleton (same for all types, contents vary)

1. **Header** — CMS ID (or plan letter for Medigap) + friendly name + carrier + the global plan-type pill + a small "N active members" stat (links to the members list) + star-rating badge if present.
2. **Benefit sheet** — grouped sections, showing only the current type's fields. Two compound benefits (OTC, Dental) render as dedicated **mini-blocks** (see §4).
3. **Admin/reference footer (collapsed by default)** — commission rates, BOB aliases, external IDs, service area, lifecycle chain. The technical stuff NOT discussed with customers, tucked away.

**One type-aware template** (`plan_detail.html`) driven by a `PLAN_TYPE_SECTIONS` config — not 5 separate templates. Consistent look, one place to maintain.

## 3. Per-type benefit sheets

### 3.1 Part C (MA / MAPD) — the richest
- **Costs:** Monthly premium · Medical deductible ($0 or amount) · Annual MOOP · Part-B giveback (if any)
- **Medical services:** PCP · Specialist · Outpatient hospital · Inpatient hospital · X-ray/MRI/CT (imaging) · PT/OT/ST (therapy) · ER · Urgent care · Ambulance (ground + air, copay/coinsurance) · SNF (days 1–20)
- **Extras:** Gym (SilverSneakers / Renew Active / etc.) · Transportation (# trips) · Vision (exam + eyewear) · Hearing (exam + aid) · **OTC mini-block** · **Dental mini-block**
- **Drugs (MAPD only — OMIT entirely for MA-only):** Rx deductible (+ which tiers) · Tiers 1–5
- Star rating in the header.

### 3.2 PDP (standalone Part D)
- Monthly premium · Annual Rx deductible (+ which tiers it applies to) · Drug tiers 1–5 · Preferred-pharmacy note · **Annual OOP cap** (year-driven: 2025 $2,000 / 2026 $2,100 / 2027 $2,400 — keyed off `plan.year`, NOT hardcoded).

### 3.3 Medigap (Medicare Supplement) — short
- Plan letter (prominent) · Monthly premium · What it covers (standardized benefit grid for that letter — e.g. G covers Part B deductible, N doesn't fully) · Household discount · Rate type (community / issue-age / attained-age). No copays/networks/OTC/dental (Medigap just pays the gaps).

### 3.4 DVH (standalone Dental/Vision/Hearing)
Grounded in the real Humana Extend 1250 sheet (`docs/Medicare Landscape Files/IDVH Plan Files/Humana/`):
- Monthly premium · Annual benefit maximum · Calendar-year deductible
- **Dental** (reuses the Part C dental mini-block): Preventive / Basic / Major, each **in-network vs OON %**, with **per-tier waiting period** (Humana: Prev none / Basic 6mo / Major 12mo)
- Vision (exam + eyewear allowance, in/out network) · Hearing (exam + hearing-aid allowance)
- Waiting periods surfaced per service.

### 3.5 Hospital Indemnity (GTL / Wellabe) — base + rider menu
HI is fundamentally different: a **base benefit set + a large menu of optional riders**, all per-plan-selectable (Tim: "super customizable... each agent will have to select as either not added or what the benefit amount is"). Grounded in the GTL Advantage Plus Elite + Wellabe docs (`docs/Medicare Landscape Files/Hospital Indemnity Files/`).
- **Base benefits** (daily-$ / per-event, values vary): Hospital Confinement (daily $ × max days) · Observation / short-duration stay · ER (injury) · Mental Health (daily $) · SNF (daily $ × days).
- **Rider menu** — each rider is *not added* OR *added with an amount/detail*. Seed catalog per carrier:
  - **GTL:** Ambulance ($50–400/use, 4×/yr, air incl.) · Cancer Lump Sum (+ Recurrence) · SNF Facility · Outpatient Therapy ($50/day) · Critical Accident · Guaranteed Purchase Option · Wellness ($100/yr).
  - **Wellabe:** Lump Sum Cancer · Lump Sum Hospital Confinement.
- The page shows the base benefits + only the **added** riders (not-added riders omitted/greyed).

## 4. Compound benefit mini-blocks (shared components)

Two benefits are structured, not single values — they get dedicated small formatted blocks reused across types:
- **OTC / flex card:** `{ amount, period, usage: online_only | in_store | both, retailers[] }`. Renders e.g. "$70/mo · in-store (CVS)" or "$50/qtr · online only". (Humana = online-only; UHC = in-store; Devoted = CVS-only — Tim's examples.)
- **Dental matrix:** `{ deductible, preventive: {in_net, oon}, basic: {in_net, oon}, major: {in_net, oon}, waiting: {...} }`. Renders a tiny 2-col grid (In-network / OON) × rows (Preventive / Basic / Major), e.g. UHC NC-0015: Prev 100%/100%, Major 50%/25%. Reused by Part C AND DVH.

## 5. Data model & rendering

- **`PLAN_TYPE_SECTIONS` config** (code): maps each `plan_type` → ordered list of benefit groups/fields to render. One source of truth. Part C also branches MAPD-vs-MA (drugs group only for MAPD).
- **Benefit values live in `details_json`** via the existing `app/plan_provenance.py` seam (`make_value` / `set_human_value` / `set_import_value`). Many keys already exist (otc_allowance, otc_note, dental_allowance, dental_note, ambulance, gym, snf, transportation, vision/hearing, inpatient_hospital, healthy_food_card). **New structured keys to add** to the provenance vocabulary: OTC `{usage, retailers}`, Dental matrix, imaging, PT/OT/ST, ambulance ground/air split, SNF day-range, HI `base_benefits[]` + `riders[]`, Medigap letter-grid ref, DVH annual_max/deductible/waiting.
- **Rendering:** `plan_detail.html` becomes type-aware — reads the config, renders only relevant groups, uses the two mini-block partials. Admin/reference footer collapsed.
- **OOP cap** = a small `{year: amount}` lookup keyed off `plan.year`.
- **Editing:** benefit fields are agent/admin inline-editable (same pattern as the customer-profile provenance fields), so agents fill/correct them — this is how HI riders + structured OTC/Dental get set. (Reuse the `editable_field` interaction.)
- **Star rating / commission / pills:** reuse existing model fields + the global `.plan-type-tag` classes.

## 6. Open items (confirm during build — not blockers)
1. **BCBS DVH product sheet** — get it to ground BCBS DVH fields (Humana Extend 1250 already in docs). BCBS HI is OUT of scope (under-65 only, per Tim).
2. **DVH rate standardization** — verify whether Humana/BCBS DVH premiums are standardized (like Medigap letters) vs vary by person; affects whether premium is a plan attribute or per-enrollment.
3. **Medigap standardized benefit grid** — source the letter→covered-gaps table (standard CMS Medigap chart) to render "what G/N covers".
4. **Which benefit fields to backfill vs. leave agent-entered** — most Part C benefit data isn't populated yet; the page will show what exists + let agents fill the rest. A CMS PBP backfill (the `pbp-benefits-2026/` files already on hand) could pre-populate copays/OTC/dental for Part C — optional enhancement.

## 7. Build sequencing (for the implementation plan)
1. **Provenance vocabulary + structured keys** (OTC, Dental matrix, HI base+riders, imaging, therapy, SNF-range) + the `PLAN_TYPE_SECTIONS` config.
2. **Mini-block partials** (OTC, Dental) — shared, tested in isolation.
3. **Type-aware `plan_detail.html`** — header + per-type benefit sheet + collapsed admin footer, Founders theme, light+dark.
4. **Inline editing** of benefit fields (reuse `editable_field` + a `/carriers/<id>/benefit` save endpoint through `set_human_value`).
5. **HI rider catalog seed** (GTL + Wellabe from the docs) + the base/rider render + edit.
6. **Optional:** CMS PBP backfill for Part C copays/OTC/dental from `pbp-benefits-2026/`.
Each phase tested; verify rendered output per plan type (Part C / PDP / Medigap / DVH / HI) via headless screenshots. No money paths touched (benefit metadata only).
