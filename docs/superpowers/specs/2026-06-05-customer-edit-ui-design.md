# Customer Inline Edit UI — Design Spec (Sub-project B)

**Date:** 2026-06-05
**Status:** Approved (brainstorm complete) — ready for implementation planning
**Part of:** the Customer Data-Integrity vision. Builds on **Sub-project A** (the field-provenance engine, merged 2026-06-05). B is the first *user-visible* piece.

## The larger vision (context)

Four sub-projects, order A→B→C (D parallelizable):
- **A. Customer field-provenance engine** — DONE/merged. `app/customer_provenance.py`: per-field source/trust/history + precedence; `set_human_value`, `set_import_value`, `list_conflicts`, `resolve_conflict`.
- **B. Customer inline edit UI** *(this spec)* — click-to-edit fields + Option-A conflict resolution on the profile, writing through A. Unblocks adding/correcting MBI, DOB, contact info.
- **B2. Proposed-changes workflow** *(deferred, own sub-project)* — non-AOR agent edits a customer they don't own → a *proposed* change (attributed, audit note) the AOR agent/admin reviews + accepts; notification (dashboard/SMS/email TBD). Structurally a 4th provenance source needing AOR confirm.
- **C. Import reconciliation** — BOB/commission imports call A's `set_import_value`; conflict review queue.
- **D. Filterability/reporting.**

B2/C/D are out of scope here.

## Problem (Sub-project B)

There is no UI to add or correct a customer's fields (e.g. a Humana customer missing their MBI). The provenance engine (A) exists but nothing writes to it from the UI. B gives current-AOR agents and admins inline editing that flows through `set_human_value`, plus a "painfully obvious" conflict-resolution affordance that flows through `resolve_conflict`.

## Architecture

Two small new routes in `app/customers.py` + targeted edits to `customer_profile.html` + a small JS block. Plus one additive enhancement to the A engine (`app/customer_provenance.py`): rejected-value memory.

### Editing model

Each field in `PROVENANCE_FIELDS` rendered on the customer profile becomes **click-to-edit in place** (matches the profile's existing inline patterns for notes/pharmacy/commission-type). No separate page, no modal.

- **Normal state (clean — "Option C"):** fields look like plain text. For editable users, a subtle pencil appears on hover; click → inline input → save. NO provenance chrome in everyday use (no badges/dots). Per-field history available on demand (a small clock/label affordance → shows the `history` list: who/when/from→to).
- **Conflict state (loud — "Option A"):** a field with an unresolved conflict renders as a **light-red filled cell** with: a red warning header (`⚠ <Field> — needs review`), both values inline (**Your value: X | <source> says: Y**), and two inline buttons **Keep mine** / **Use carrier's**. Resolving reverts the cell to clean normal state.

### Routes

```
POST /customers/<id>/field
  body: {field, value}
  - 404 if customer not visible to current_user (existing _customer_query scope)
  - 400 if field not in PROVENANCE_FIELDS
  - 403 if not (admin or current-AOR agent)   [reuses _is_current_aor]
  - calls customer_provenance.set_human_value(customer, field, value, current_user)
  - returns {ok: true, field, value, trust}

POST /customers/<id>/resolve-conflict
  body: {field, choose}   # choose in {keep_current, take_incoming}
  - same 404/403 gates
  - calls customer_provenance.resolve_conflict(customer, field, choose, current_user)
  - returns {ok: true, field, value, has_unresolved_conflicts}
```

Both AJAX; the profile updates the field in place on success.

### Permission

Reuses the existing AOR write-gate (same rule the profile already enforces for notes/contacts/pharmacy):
- **current-AOR agent or admin** → fields editable (hover pencil), conflicts resolvable.
- **former-AOR agent (read-only)** → fields render as plain text (no pencil); a conflict's red cell is VISIBLE (they can see review is needed) but shows NO resolve buttons.
Edits/resolutions attribute to `current_user` (recorded in provenance history).

### Engine enhancement (in `app/customer_provenance.py` — additive, first task of Plan B)

"Rejected-value memory" so an agent isn't re-nagged about a carrier value they already rejected:

1. **`resolve_conflict`** — on `keep_current`, record the rejected incoming value in `meta[field]["rejected_values"]` (a list). On `take_incoming`, nothing is rejected (agent took the incoming).
2. **`set_import_value`** — in the conflict branch (incoming differs from an `agent_entered`/`human_verified` value): if the incoming value is in `rejected_values`, return new action **`'suppressed'`** (log to history, NO new conflict). If it's a different new value, flag normally.
3. **New action `'suppressed'`** joins the set: `skipped | written | confirmed | conflict_flagged | suppressed`.
4. **A fresh human edit clears the field's `rejected_values`.** When `set_human_value` writes a new value for a field, it resets `rejected_values` to empty — the agent has changed their mind about the field, so prior rejections no longer apply (a carrier value previously rejected could now legitimately match the new human value, or warrant a fresh conflict). Keeps the suppression scoped to "the value I just affirmed," not forever.

Additive only — no existing engine behavior changes. Lives in the engine (not the route/template) so suppression holds for ALL callers (UI, BOB, commission, future HealthSherpa) — Sub-project C's import path inherits it for free.

## Testing

Local SQLite + Flask test client:
- **Engine enhancement** (additions to `tests/test_customer_provenance.py`): keep_current records the rejected carrier value; re-import of that same value → `'suppressed'` (no new conflict); re-import of a different new value → `'conflict_flagged'`; take_incoming records nothing rejected.
- **Field-save route** (`tests/test_customer_edit.py`): current-AOR agent saves → 200 + column/provenance updated + `agent_entered`; former-AOR → 403; admin → 200; field not in PROVENANCE_FIELDS → 400; unknown customer → 404.
- **Resolve-conflict route**: AOR agent resolves → conflict cleared, value applied, `human_verified`; former-AOR → 403.
- **Template smoke**: profile renders a conflict as the red cell (both values + buttons); clean fields otherwise; read-only user sees no pencils/buttons.

## Boundaries (what B is NOT)

- NOT the non-AOR propose/review/notify workflow (B2).
- NOT import reconciliation wiring (C) — the engine enhancement is exercised by unit tests, but BOB/commission don't call `set_import_value` yet.
- NOT new filters (D).
- Does NOT change `customer_new.html` (create form stays as-is; routing it through `set_human_value` is optional future cleanup, not required).

## Deliverable (user-visible)

Inline edit + Option-A conflict resolution on the customer profile, engine rejected-value memory, two routes, profile-template updates, full tests. After B deploys: an agent can add Mitchell Thoma's MBI (→ next commission upload matches him instead of stubbing) and resolve a carrier conflict in one click. No new migration (reuses A's columns + adds a `rejected_values` key inside the existing JSON blob).

## Open items (non-blocking)
- B2 (proposed-changes workflow) — its own brainstorm: pending-change model, review UI, notification delivery (dashboard/SMS/email).
- Per-field "history on demand" affordance styling — decided at build time; spec requires only that the `history` list is viewable per field.
