# Plan Data Integrity & Provenance — Design Spec

**Date:** 2026-06-02
**Status:** Approved (pending written-spec review)
**Author:** AJ / Tim (brainstormed with Claude)

---

## 1. Problem & Goal

The portal's plan benefit data must be **provably accurate and current**. The motivating failure:
BCBS released "first look" benefits for an upcoming plan year; those numbers were printed onto
agent appointment charts. CMS later published the *approved* benefits — higher premiums, lower
dental allowances, higher copays than the first looks. Charts had to be reprinted; some agents
never got the update and quoted seniors from stale/wrong data. The root cause was **no chain of
custody**: no one could answer "where did this number come from, and has it been superseded?"

**Goal:** For every benefit value on every plan, the portal can answer with confidence:
1. **Source** — where it came from (CMS PBP, CMS Landscape, carrier first-look, agent edit, AJ verification).
2. **Trust** — how authoritative it is (unverified → cms_authoritative → human_verified).
3. **Attribution** — who changed it, when, and what the change was (append-only history).
4. **Conflict status** — flagged when an authoritative source disagrees with an existing value, so it
   surfaces for human review instead of silently overwriting or being silently ignored.

The first concrete consumer of this system is **OTC and Meals benefit extraction** from the CMS PBP
`b13` file, which the current sync pipeline skips.

### Design principle: reference data has attribution, not ownership

A plan/carrier is **reference data** — it describes the world; it is not a sales object and has no
"owner." This deliberately departs from incumbent Medicare CRMs (AgencyBloc, Cavulus, etc.) that
impose a required "owner" field on every record. The only meaningful ownership in this domain is the
time-bounded **AOR relationship on a policy** (already modeled via `CustomerAorHistory`). Plan data
carries **attribution** (who-changed-what-when) for accountability, never **ownership**.

---

## 2. Scope

### In scope
- A **provenance data model** stored as structured values inside `Plan.details_json`, with a `_meta`
  map per field and a `_conflicts` list per plan.
- **Structured benefit values**: every rich benefit stored as `{amount, period, display, unit}` rather
  than a loose formatted string. Powers both numeric filtering and reliable conflict detection.
- A **provenance helper module** (`app/plan_provenance.py`) that owns *all* reads/writes of the
  provenance structure — the single seam to a future relational table.
- **Source + trust + precedence rules** (Section 4), including the auto-promote-on-match rule and the
  agent-vs-CMS conflict-flagging rule.
- **Plan-year isolation invariant**: provenance/conflict logic operates strictly within a single
  `(agency_id, carrier, cms_plan_id, year)`. Cross-year values are never compared. A first-look for
  2027 creates/updates the 2027 plan row and never touches 2026.
- **Conflict detection** in the sync path: an authoritative CMS value that disagrees with an existing
  agent-entered value writes a conflict flag and sets `Plan.has_unresolved_conflicts = true`.
- **Sync retrofit**: the three existing sync scripts (`sync_cms_plan_data.py`,
  `sync_pbp_benefit_data.py`, `sync_pbp_extended_benefits.py`) write through the provenance helper
  instead of blind-merging.
- **OTC extraction** (PBP `b13b`) and **Meals extraction** (PBP `b13c`) as the first new benefits,
  written through the provenance helper.
- **Agent editing**: any agent with the `can_edit_plans` capability may edit any plan benefit field;
  edits are attributed (who/when/what), append to history, and propagate agency-wide (single source
  of truth). Newbies without the capability are read-only.
- **Edit-permission gating**: a `can_edit_plans` capability on `User` (admins always allowed).
- **Conflict review queue**: an admin view listing plans with `has_unresolved_conflicts = true`,
  showing each conflict (existing vs. incoming with sources) and letting AJ resolve it.
- **Robust plan filtering**: a filter layer that queries on *both* real columns and structured-JSON
  benefit fields, supporting numeric comparisons (e.g. `plan_type=ppo AND annual_oopm<6000 AND
  dental_allowance.amount>2000`). Operates in the app layer over agency-scoped plans (≤ low
  thousands of rows; trivially fast at this scale).
- **Per-field source badges** in the plan detail/edit UI ("CMS 2026", "edited by Mike", "✓ verified").
- **`cms_synced_at`** timestamp + **`has_unresolved_conflicts`** boolean as real Plan columns
  (migration 019).

### Explicitly out of scope (with rationale)
- **CMS download crawler** — deferred. Low value (saves minutes a few times/year), fragile
  (HTML-scraping a government site). Manual download + scp continues; no regression.
- **Transportation / Gym-Fitness / Healthy Food Card extraction** — confirmed *not* reliably present
  in CMS PBP structured data. b13's c–g "Other" slots are free-text plan-entered strings
  ("annual wellness exam...", "MedMutual Travel Plus") with no consistent vocabulary; H5253-117
  has nothing in those slots despite offering Renew Active. These stay manual entry.
- **Relational `plan_benefit_values` table** — deferred to tenant #2 (white-label). The provenance
  helper module is designed as the seam: migrating storage later changes only that module.
- **Drug-Cost Evidence Capture (CYA)** — deferred as a named follow-on (Section 9). Different data
  model (per-drug, per-quote, time-sensitive snapshot) than plan-benefit provenance. Motivating case:
  Medicare.gov shows Adderall XR 30-day at ~$5 while pharmacy reality is ~$50; agents need
  timestamped evidence of what their authoritative source displayed at quote time, to defend against
  looking incompetent/dishonest when reality differs.
- **Formal agent→carrier/plan assignment/ownership** — explicitly rejected (see design principle).
  Any trusted agent can edit any plan; no ownership layer.
- **Plan list/detail/form template redesign** — only additive changes (source badges, filter controls,
  conflict queue). No structural redesign.

---

## 3. Data Model

### 3.1 Structured benefit value
Each rich benefit in `details_json` becomes an object, not a string:
```json
"dental_allowance": {
  "amount": 2000,
  "period": "yr",
  "unit": "usd",
  "display": "$2,000/yr"
}
```
- `amount` — numeric, enables filtering + conflict comparison. `null` if "offered but amount unknown".
- `period` — `mo` | `qtr` | `yr` | `2yr` | `3yr` | `period` | `null`.
- `unit` — `usd` | `pct` | `count` | `text` (so "$35", "18%", "24 trips", "$0 exam" all model cleanly).
- `display` — the human string shown in the UI (formatted from the structured parts, or carrier-exact).

Copay-style fields that are already columns (`pcp_copay`, etc.) remain columns but ALSO gain a
provenance entry in `_meta` keyed by the same name (the helper bridges column ↔ provenance).

### 3.2 Per-field provenance (`details_json._meta[field]`)
```json
"_meta": {
  "dental_allowance": {
    "source": "carrier_first_look",
    "trust": "unverified",
    "as_of": "2026",
    "updated_at": "2026-06-02T14:30:00",
    "updated_by": "Mike Lauzurique",
    "history": [
      {"at":"2026-06-02T14:30:00","by":"Mike Lauzurique","from":null,"to":"$2,000/yr","note":"BCBS first look"}
    ]
  }
}
```
- `source` — `cms_pbp` | `cms_landscape` | `carrier_first_look` | `agent_edit` | `aj_verified`.
- `trust` — `unverified` | `agent_entered` | `cms_authoritative` | `human_verified`.
- `updated_by` — display name, or `null` for CMS-sourced.
- `history` — append-only list of `{at, by, from, to, note}`. **Retained in full** (bounded in practice:
  benefit fields change a handful of times per plan-year). Revisit capping only if a field's history
  becomes pathological.

### 3.3 Per-plan conflicts (`details_json._conflicts`)
```json
"_conflicts": [
  {
    "field": "dental_allowance",
    "existing": {"value":"$2,000/yr","source":"agent_edit","by":"Mike","at":"2026-05-01T..."},
    "incoming": {"value":"$1,500/yr","source":"cms_pbp","at":"2026-06-02T..."},
    "flagged_at": "2026-06-02T...",
    "resolved": false,
    "resolved_by": null,
    "resolved_at": null,
    "resolution": null
  }
]
```

### 3.4 New Plan columns (migration 019)
- `cms_synced_at` — `DateTime`, nullable. Set on every CMS sync that touches the plan. Drives
  staleness display.
- `has_unresolved_conflicts` — `Boolean`, default `false`, **indexed**. Drives the review-queue
  badge/filter. Maintained by the provenance helper.

### 3.5 New User capability (migration 019)
- `can_edit_plans` — `Boolean`, default `false`. Admins bypass (always allowed). Gates the plan edit
  routes and edit UI affordances.

---

## 4. Source / Trust / Precedence Rules

All rules operate within a single `(agency_id, carrier, cms_plan_id, year)` — the **year invariant**.

| Source | Default trust | On CMS sync, if incoming CMS value differs from existing |
|---|---|---|
| (field empty) | — | Write CMS value (`cms_pbp`/`cms_landscape`, `cms_authoritative`) |
| `carrier_first_look` | `unverified` | **Overwrite** with CMS, append history (CMS beats first-looks) |
| `cms_pbp` / `cms_landscape` | `cms_authoritative` | **Refresh** (overwrite prior CMS value, append history) |
| `agent_edit` | `agent_entered` | **Flag conflict**, set `has_unresolved_conflicts=true`, do NOT overwrite |
| `aj_verified` | `human_verified` | **Skip** (human wins; AJ may know a carrier correction CMS lags) |

**Auto-promotion rule:** if an incoming CMS value **equals** an existing `agent_entered` value, promote
that field to `trust = human_verified`, `source = aj_verified`-equivalent "double-confirmed" state
(record both signals in history). Such a field is thereafter never auto-overwritten or re-flagged.

**Human edits** (`set_human_value`):
- An agent edit sets `source=agent_edit`, `trust=agent_entered`, attribution + history.
- An AJ "verify" action sets `source=aj_verified`, `trust=human_verified`.
- Human edits always apply immediately (humans are never blocked by CMS data); they only affect how
  *future* CMS syncs treat the field (per table above).

**Year invariant examples:**
- A 2027 first-look import → lands on the 2027 plan row (created if absent). 2026 row untouched.
- A 2026 CMS sync → only compares against 2026 provenance. Never sees 2027.

---

## 5. Provenance Helper Module (`app/plan_provenance.py`) — the seam

The single module that knows the `_meta` / `_conflicts` storage shape. Everything else calls it.
Migrating to a relational `plan_benefit_values` table later changes ONLY this module.

```
field_value(plan, field) -> value | None
    # plain value for templates/filters; reads column or structured-json transparently

get_field(plan, field) -> dict | None
    # full provenance record {value, source, trust, as_of, updated_at, updated_by, history}

set_cms_value(plan, field, structured_value, cms_source) -> action
    # applies Section 4 precedence rules. Returns one of:
    #   'written' | 'refreshed' | 'overwrote_firstlook' | 'skipped_human'
    #   | 'promoted_verified' | 'conflict_flagged'
    # maintains plan.cms_synced_at and plan.has_unresolved_conflicts

set_human_value(plan, field, structured_value, user, note, verify=False) -> None
    # agent edit (verify=False) or AJ verify (verify=True). Attribution + history.

list_conflicts(plan, unresolved_only=True) -> list
resolve_conflict(plan, field, chosen, user, note) -> None
    # AJ picks the surviving value; clears flag; recomputes has_unresolved_conflicts

iter_filterable_fields(plan) -> dict
    # flat {field: numeric_or_text} view across columns + structured-json, for the filter layer
```

Structured-value parsing/formatting helpers (`parse_money`, `fmt_money`, period maps) live here too,
so both sync scripts and the edit form produce identical structured shapes.

---

## 6. Sync Flow (retrofit)

Each sync script, per plan, per field:
1. Extract the CMS value → build a structured value `{amount, period, unit, display}`.
2. Call `provenance.set_cms_value(plan, field, structured_value, "cms_pbp")`.
3. The helper applies Section 4 rules and records the action.
4. After all fields: `db.session.commit()`; report includes per-action counts and a conflicts summary.

**Retrofit ordering:** introduce the helper + structured values first, migrate the *existing* extended
benefits to structured form, then add OTC/meals. The two new extractors:

- **OTC (`b13b`)**: gated by `pbp_b13b_bendesc_otc == "1"`. Amount from `b13b_maxplan_amt` /
  `b13b_maxenr_amt` (numeric, may be absent → amount `null`, display "Offered"). Period from
  `b13b_otc_maxplan_per`. ~4,244 plans offer OTC; ~2,403 have a dollar amount.
- **Meals (`b13c`)**: gated by `pbp_b13c_bendesc_service == "1"`. Meal type from
  `b13c_meal_type_chk`; amount/period where present. ~3,337 plans offer meals.

PDP plans (no b13 row) → fields simply absent (graceful, same as today).

---

## 7. Editing & Permissions

- **Capability:** `User.can_edit_plans` (admins always allowed). Enforced in `carriers.py` edit routes
  and used to show/hide edit affordances in templates.
- **Agency-wide:** plan data is already `agency_id`-scoped (not per-agent); every agent reads the full
  database; an authorized edit is visible to all agents immediately (single source of truth).
- **Attribution:** every edit records who/when/what via `set_human_value` (history entry).
- **Verify action:** authorized users (AJ/admin, or trusted agents) can mark a field `human_verified`.

---

## 8. Filtering & Display

- **Filter layer** (`carriers.py` + helper `iter_filterable_fields`): builds a flat per-plan view merging
  real columns and structured-JSON `amount`s, then applies the requested predicates in the app layer
  over agency-scoped plans. Supports `=`, `<`, `<=`, `>`, `>=`, `in`, `contains` per field as
  appropriate to its `unit`.
- **Example** (`plan_type=ppo AND annual_oopm<6000 AND dental_allowance.amount>2000`) resolves:
  `plan_type` (column) + `annual_oopm` (column) + `dental_allowance.amount` (structured-json) — all
  filterable uniformly.
- **Scale:** at ≤ low-thousands of plans, app-layer filtering is single-digit ms. If a tenant ever
  exceeds ~100k plans, promote hot filter fields to columns or move to the relational table (the
  helper seam makes this localized). Documented, not built.
- **UI:** filter bar mirrors the existing customers-module pattern (same CSS classes, flex sizing).
  Plan detail/edit shows per-field **source badges** + `cms_synced_at` staleness indicator.
- **Color tokens:** all UI uses CSS vars per the dual-palette theme; text uses `var(--ivory)` /
  `var(--slate)`, never `var(--ink)`.

---

## 9. Deferred / Follow-on Work (named, not lost)

1. **CMS download crawler** — auto-fetch newest PBP/Landscape files, chain the sync scripts.
2. **Relational `plan_benefit_values` table** — at white-label tenant #2; swap behind the helper seam.
3. **Conflict-review dashboard polish** — richer queue, bulk-resolve, notifications.
4. **Drug-Cost Evidence Capture (CYA)** — per-quote snapshot of the drug price an authoritative source
   (Medicare.gov / carrier) displayed, with timestamp + source, to defend agents when pharmacy reality
   differs (Adderall XR $5-vs-$50 case). Separate data model (per-drug, per-quote).
5. **Policy/AOR "ownership" model refinement** — the idea that an agent effectively owns the *policy*
   (time-bounded by AOR) rather than the customer. Tabled.

---

## 10. Testing Strategy

- **Provenance helper unit tests** — the precedence table (Section 4) is the core risk; one test per
  row + the auto-promotion rule + the year invariant. These tests ARE the BCBS-incident regression
  guard.
- **Conflict lifecycle test** — agent edit → CMS sync disagrees → conflict flagged →
  `has_unresolved_conflicts` true → AJ resolves → flag cleared → flag count recomputed.
- **Structured-value round-trip** — parse CMS raw → structured → display string; numeric filtering
  predicates against structured `amount`s.
- **OTC/Meals extractor tests** — against real PBP rows (H5253-117 = OTC offered/no-amount + meals;
  a plan with an OTC dollar amount; a PDP plan = absent).
- **Permission test** — non-`can_edit_plans` agent blocked from edit route; admin allowed.
- **Filter test** — the `ppo + moop<6000 + dental>2000` example returns the right plan set.

---

## 11. Migration Summary

**Migration 019** (`019_plan_provenance.py`):
- `plans.cms_synced_at` `DateTime NULL`
- `plans.has_unresolved_conflicts` `Boolean NOT NULL DEFAULT false`, indexed
- `users.can_edit_plans` `Boolean NOT NULL DEFAULT false`
- Data backfill: existing `details_json` benefit strings → structured `{amount, period, unit, display}`
  with `_meta` source `cms_pbp` / `cms_authoritative` (best-effort parse; unparseable kept as
  `display` with `amount=null`). Idempotent, reversible.
