# Provider Intake-Form v2 — Design

**Date:** 2026-08-05
**Status:** Approved (brainstorm complete) — ready for implementation plan
**Author:** Tim + assistant
**Context:** Refines the Network Snapshot (shipped 2026-08-05, migration 041) based on Tim's real-world contracting knowledge. The base feature: a `Provider` directory + a plan-detail Pro panel. This v2 sharpens the intake model. Builds on `app/models.py` (`Provider`, `provider_carriers`), `app/providers.py` (`providers_bp`), `app/carriers.py` (`providers_for_plan`), `app/templates/providers_form.html` + `providers_list.html` + `plan_detail.html`.

## What this builds — three refinements

1. **Type suggestions** — expand the list + render it as a **grouped datalist** (category headers, free-typing preserved).
2. **Per-PPO-plan plays-nice** — replace the single whole-provider `bills_ppo_oon` flag with a **per-specific-Plan** flag layer, added as-needed, that surfaces on that plan's page.
3. **Name vs group** — add an optional `group`/affiliation text field.

## Section 1 — Two-layer network model (the core change)

Keep the existing **carrier layer**; add a **plan layer**.

- **Carrier layer (unchanged):** `provider_carriers` (provider → accepted carrier strings) = the broad in-network default. Still drives the plan panel for HMO plans (OON not a question there).
- **NEW plan layer — `provider_plans` join table:** a provider flagged against a **specific `Plan`**, added *as-needed* (NOT a full matrix — most providers have zero-to-few plan flags). Columns:
  - `id`, `provider_id` (FK providers.id, ondelete CASCADE), `plan_id` (FK plans.id, ondelete CASCADE), `agency_id` (FK, scoping)
  - `status`: `"in_network"` | `"out_of_network"`
  - `bills_oon`: `"yes"` | `"no"` | `"unknown"` (the plays-nice flag; only meaningful for PPO plans)
  - unique `(provider_id, plan_id)`.
- **Grounding:** on Humana Gold Plus `H1036-335` you see providers specifically flagged for it; on Devoted Choice PPO you see their plays-nice status. Only the plans Tim actually works with get flagged (there are 19 non-SNP PPOs in Cabarrus but most are HumanaChoice plans he never touches).

**Panel resolution / precedence** (in `providers_for_plan`): for a given plan, a provider's status = its **plan-specific `provider_plans` row if one exists** (status in/out), else the **carrier-level** default (accepts `plan.carrier` → in-network, else not). Plays-nice (`bills_oon`) is shown ONLY from a plan-specific row, and only when `is_ppo`.

**`Provider.bills_ppo_oon` is RETIRED** (dropped) — the per-plan `bills_oon` is strictly more accurate (a provider can bill Devoted OON but not Aetna).

**⚠ Data preservation (there is already 1 real provider on prod with a meaningful flag):** the migration must NOT silently lose the existing `bills_ppo_oon` value. Before dropping the column, for any provider whose `bills_ppo_oon` is non-null and not `"unknown"`, **append a line to `notes`**: `"[migrated] general PPO-OON billing: <value>"`. This preserves the human knowledge (there's no clean automatic per-plan target since the old flag was plan-agnostic) so Tim can re-enter it as a proper per-plan flag on next edit. The migration does this in a data step before `op.drop_column`.

## Section 2 — group field + expanded types

**`Provider.group`** — new optional `String(256)` column (affiliation / umbrella).
- Group-contracted big providers: `name`="Atrium Health" (type="Provider group"), `group` empty — OR `name`=practice, `group`="Atrium Health".
- Rare independent-doc-under-umbrella (the "salon chair" case): `name`="Dr. Tuttle", `group`="Novant".
- Renders as a muted sub-label under the name on the list + plan panel when set.

**Type suggestions** — the free-text `provider_type` (unchanged column) gets an expanded, **category-grouped** suggestion set. Since HTML `<datalist>` does not reliably support `<optgroup>` across browsers, render grouping via **category header rows** (a disabled/label `<option>` per category, or a small structured datalist) that still type-ahead-filters and still lets agents type anything. Categories + members:
- **Specialties:** Family medicine, Cardiology, Gastroenterology, Dermatology, OB/GYN, Urology, Nephrology, Pulmonology, ENT, Podiatry, Oncology, Orthopedics
- **Facilities & centers:** Hospital, Surgical center, Urgent care, Rehab center, Skilled nursing facility, Imaging / radiology, Lab
- **Groups & systems:** Provider group
- **Ancillary & equipment:** DME, Home health, Hospice, Physical therapy, Behavioral / mental health, Optometry / ophthalmology, Audiology, Chiropractic, Dentist

(Free text — the categories are browse aid only, not enforced. If `<datalist>` category-labeling proves flaky, fall back to a flat but complete alphabetized datalist; grouping is a nice-to-have, the full list is the requirement.)

## Section 3 — management page + plan panel

**Management form (`providers_form.html`):**
- Existing fields + **`group`** field (text, after name).
- Type input uses the grouped datalist.
- **NEW plan-flags section:** an as-needed way to flag this provider against specific plans:
  - A **searchable plan picker** (agency Plan records — reuse existing plan-search patterns if present, else a simple `<select>`/typeahead of `carrier — display_id — plan_name`). Selecting one + a status (in/out) + bills_oon (yes/no/unknown) adds a `provider_plans` row.
  - Existing plan-flags listed with a remove control.
  - Lazy — Tim adds only the plans that matter.
- The whole-provider `bills_ppo_oon` radio is REMOVED (replaced by per-plan `bills_oon`).

**List page (`providers_list.html`):** show `group` as a muted sub-label; the whole-provider plays-nice badge is removed (it's per-plan now — optionally show a small "N plan flags" count).

**Plan-detail Pro panel** (`providers_for_plan` + `plan_detail.html`): resolution per Section 1 — plan-specific flag wins over carrier default; PPO plays-nice from the plan-specific `bills_oon`; `group` sub-label. Not-in-network objection section unchanged in spirit (now honoring plan-specific out-of-network flags too).

**Blueprint routes (`providers.py`):** `provider_new`/`provider_edit` handle the `group` field + adding/removing `provider_plans` rows (a `set_plan_flags` helper on Provider, or inline in the route — agency-scoped, gated on `can_edit_shared_data` as today). Delete cascades plan flags.

## Section 4 — testing & safety

- **Model/migration:** `provider_plans` table (unique provider+plan, cascades); `Provider.group` added; `bills_ppo_oon` **data-preserved into notes then dropped**; migration valid (isolated-validate like prior ones). ⚠ The prod data step (preserve-then-drop) must be verified against the 1 existing provider.
- **Accessor precedence:** `providers_for_plan` returns in/out honoring plan-specific flags over carrier default; `bills_oon` surfaced only from a plan-specific PPO flag; agency-scoped (no cross-agency leak).
- **Management page:** add/remove a plan flag persists a `provider_plans` row; `group` persists; edit gate (`can_edit_shared_data`) unchanged + server-side.
- **Plan panel:** a provider flagged out-of-network on a specific plan shows as out even if carrier-accepted (plan flag wins); PPO plays-nice from plan flag; group sub-label; empty state intact.
- **Grouped datalist** renders the full category-labeled suggestion set; free text still accepted.
- **Headless screenshots** (edit form with plan-flags section + grouped types + group field; plan panel showing a plan-specific flag + plays-nice; list with group sub-label) + full suite green.

## Files
- Modify: `app/models.py` (`Provider.group` col; `provider_plans` table + a `set_plan_flags`/accessor helper) + migration (next sequential — verify head at build; head is 041, so 042).
- Modify: `app/providers.py` (group field + plan-flags add/remove; drop the bills_ppo_oon radio handling; expanded grouped TYPE list).
- Modify: `app/carriers.py` (`providers_for_plan` plan-layer precedence).
- Modify: `app/templates/providers_form.html` (group field, grouped datalist, plan-flags section), `providers_list.html` (group sub-label), `plan_detail.html` (plan-flag-aware panel + group sub-label).
- Tests: extend `tests/test_providers.py` + `tests/test_plan_detail_route.py`.

## Out of scope (deferred / noted)
- **Full group→provider hierarchy** (a ProviderGroup table with cascading contracts) — rejected in brainstorm; the optional `group` text field covers the rare umbrella case.
- **Enumerating all 19 Cabarrus PPOs** — no; plan flags are as-needed only.
- **Auto-deriving plan flags from carrier directories** — still manual tribal knowledge.
- Provider↔customer linkage; the AEP formulary-change segmentation engine — unrelated future features.

## Deploy notes
One migration (adds `provider_plans` + `Provider.group`; preserves-then-drops `bills_ppo_oon`). ⚠ DB backup before (there's 1 real provider row whose flag gets migrated to notes). `flask db upgrade`, restart. No seed. Verify the 1 existing provider's flag landed in its notes and its carriers/row survived.
