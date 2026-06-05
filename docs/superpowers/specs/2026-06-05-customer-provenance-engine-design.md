# Customer Field Provenance Engine — Design Spec (Sub-project A)

**Date:** 2026-06-05
**Status:** Approved (brainstorm complete) — ready for implementation planning
**Part of:** the Customer Data-Integrity vision (4 sub-projects). This spec covers **Sub-project A only**.

## The larger vision (context)

The portal must become a real CRM that *reconciles* sources of truth rather than blindly overwriting on import. Carriers/BOB are not absolute truth — a customer's preferred email, mobile, or mailing address often differs from the carrier record, and there was no UI to add/correct customer data (e.g. a Humana customer missing their MBI). This vision decomposes into four sub-projects, built in order A→B→C (D parallelizable):

- **A. Customer field-provenance engine** *(this spec)* — per-field source/trust/history + precedence. The keystone everything else writes through.
- **B. Customer edit UI** — profile edit form; writes through A. Unblocks adding/correcting MBI, DOB, contact info.
- **C. Import reconciliation + conflict review queue** — BOB & commission imports call A's `set_import_value`; conflicts surfaced for review.
- **D. Filterability & reporting** — DOB, pharmacy, plan, carrier, zip, county, payments, etc. as filter/report dimensions.

Each sub-project gets its own spec → plan → build cycle. B/C/D are out of scope here.

## Problem (Sub-project A)

`Customer` has a single blunt `manually_edited` boolean that protects ALL contact fields from import overwrite — it cannot express per-field truth ("the agent fixed the email and zip, but the carrier address may still sync"). There is no record of *where* each field's value came from, *who* set it, or *when* — so imports either clobber human corrections or are globally blocked. We need per-field provenance + precedence, modeled on the proven `app/plan_provenance.py` engine.

## Architecture

A new module **`app/customer_provenance.py`**, a sibling to (not a refactor of) `app/plan_provenance.py` — they share a *pattern*, not code, to keep plan and customer concerns decoupled. It is the single seam: **all reads/writes of per-field provenance metadata go through this module; nothing else touches the raw structure.** This localizes any future migration to a relational store.

### Storage

Migration 022 adds two columns to `customers`:
- `field_provenance` (Text, nullable) — JSON metadata blob.
- `has_unresolved_conflicts` (Boolean, default false, indexed) — cheap lookup for the review queue (mirrors `plans.has_unresolved_conflicts`).

The customer's **real typed columns** (`dob`, `zip_code`, `email`, …) remain the authoritative, filterable VALUES. The JSON holds only metadata:

```json
{
  "_meta": {
    "zip_code": {
      "value": "28205",
      "source": "agent_edit",
      "trust": "agent_entered",
      "updated_at": "2026-06-05T14:00:00",
      "updated_by": "Tim Winslow",
      "history": [ {"at": "...", "by": "...", "from": "...", "to": "...", "note": "..."} ]
    }
  },
  "_conflicts": {
    "zip_code": { "incoming": "28202", "source": "bob_import", "at": "...", "status": "pending" }
  }
}
```

Customer values are **plain scalars** (a zip is `"28205"`, a dob serialized as ISO date) — NOT the `{amount, period, unit}` structure plan benefits use. No `make_value` equivalent.

### Trust model

```
human_verified  (3)   # agent/AJ edit — top truth, never overwritten by import
agent_entered   (2)   # agent edit (not AJ-verified)
carrier_import  (1)   # any import: bob, commission, healthsherpa
empty           (0)   # field has no provenance / no value
```

The `source` string is always recorded precisely (`agent_edit | aj_verified | bob_import | commission_import | healthsherpa`) even though all imports share the `carrier_import` trust tier. This is deliberate forward-compat (see "Designed-for future consumers").

### Public API

```python
PROVENANCE_FIELDS = ["mbi", "humana_id", "first_name", "last_name", "dob",
                     "gender", "phone_primary", "phone_secondary", "email",
                     "address1", "city", "state", "zip_code", "county",
                     "medicaid_level", "medicaid_id"]

TRUST_ORDER = {"carrier_import": 1, "agent_entered": 2, "human_verified": 3}

# reads
get_field(customer, field)  -> {value, source, trust, updated_at, updated_by, history} | None
trust_of(customer, field)   -> "human_verified" | "agent_entered" | "carrier_import" | None

# human writes
set_human_value(customer, field, value, user, note=None, verify=False)
   # verify=False -> agent_entered ; verify=True -> human_verified (AJ).
   # Writes the real column AND _meta. Appends history. Sets customer.manually_edited=True.

# import write (the precedence engine — Sub-project C will call this from import paths)
set_import_value(customer, field, value, source) -> action
   # action in {'written', 'confirmed', 'conflict_flagged', 'skipped'}
   # incoming empty/blank               -> no-op                                ('skipped')
   # field empty (no value)             -> write value as carrier_import        ('written')
   # same value (any trust)             -> refresh as_of/updated_at             ('confirmed')
   # differs, stored trust == carrier   -> overwrite (newer carrier wins)       ('written')
   # differs, stored trust >= agent     -> record conflict, DON'T overwrite     ('conflict_flagged')

# conflicts (consumed by Sub-project C's review queue)
list_conflicts(customer, unresolved_only=True) -> [{field, current, incoming, source, at}]
resolve_conflict(customer, field, choose, user, note=None)
   # choose in {'keep_current', 'take_incoming'} -> applies choice, clears the conflict,
   # updates has_unresolved_conflicts.
```

Key invariants:
- **The engine owns both writes.** For a tracked field, callers never set `customer.<field>` directly — they call `set_human_value`/`set_import_value`, which set the real column AND the metadata so they never drift.
- `set_import_value` returning an explicit action lets Sub-project C report per-field outcomes ("3 filled, 1 conflict") in the import modal.
- Untracked fields (not in `PROVENANCE_FIELDS`) behave normally — no provenance overhead.

### Migration & backfill

**Migration 022** — `customers.field_provenance` + `customers.has_unresolved_conflicts`, chained off 021.

**`scripts/backfill_customer_provenance.py`** (run on VPS, idempotent — skips fields that already have provenance). Seeds provenance for the existing ~510 customers so the engine starts informed:
- `manually_edited=True` customers → **all** populated tracked fields (identity AND contact) seeded as **`agent_entered`**. Rationale: any field on a human-touched customer is human-trusted truth — a mistyped MBI or DOB is precisely the case where a later carrier import should *flag a conflict for review* rather than silently keep the typo or silently overwrite it. Uniform "protect everything a human touched" rule, no contact/identity special-casing.
- `manually_edited=False` customers → all populated tracked fields seeded as **`carrier_import`**.
- `source` recorded from the customer's existing `source` column where present, else `bob`.

Day-one result: every human correction (identity + contact) is protected and will flag a conflict if a carrier import disagrees (the typo-catcher); carrier-sourced data is overwritable-by-newer-carrier; nothing is falsely `human_verified`.

### Relationship to `manually_edited`

The engine supersedes the boolean as the source of truth for "can an import overwrite this field." The backfill migrates the boolean's intent into per-field provenance. The boolean column is RETAINED as a cheap "has any human edit" indicator (some UI/queries may use it; `set_human_value` keeps setting it True), but precedence logic reads provenance, not the boolean.

## Testing

Local SQLite (conftest fixtures), mirroring `tests/test_plan_provenance.py`:
- **Precedence** (`set_import_value`): incoming-blank→skipped (no-op); empty-field→written; same→confirmed; differs-from-agent_entered→conflict_flagged (column unchanged); differs-from-carrier_import→written (overwrite); differs-from-human_verified→conflict_flagged.
- **Human writes** (`set_human_value`): sets column + agent_entered; verify=True→human_verified; appends history; sets manually_edited=True.
- **Conflict lifecycle**: list_conflicts returns pending; resolve_conflict('keep_current') clears + keeps column; resolve_conflict('take_incoming') clears + writes column; has_unresolved_conflicts toggles.
- **Round-trip**: write via engine → read real column directly → matches (column + metadata in sync).
- **Backfill**: manually_edited=True customer's email AND mbi both → agent_entered (all populated fields protected uniformly); plain customer's zip → carrier_import; re-run is idempotent.

## Boundaries (what Sub-project A is NOT)

- Does NOT wire `set_import_value` into BOB/commission import paths — that's Sub-project C. A builds + unit-tests the function in isolation.
- Does NOT build the edit form (B), conflict review UI (C), or new filters (D).
- Does NOT modify `plan_provenance.py` (sibling module, shared pattern only).

## Deliverable (shippable on its own)

`app/customer_provenance.py` + migration 022 + `scripts/backfill_customer_provenance.py` + full test suite. Nothing user-visible yet; it is the foundation B and C build on, and the backfill makes existing data provenance-aware immediately.

## Designed-for future consumers (NOT built here, but the engine accommodates them)

- **HealthSherpa (inbound):** an additional `source='healthsherpa'`. For now it shares the `carrier_import` tier; its precise source is recorded. If point-of-sale freshness should later outrank BOB, that is a small precedence rule change — the data is already captured.
- **2-way carrier sync (outbound):** a future consumer that pushes only `trust=human_verified` fields back to carriers (and never pushes a value back to the carrier it came from). The engine enables this by recording source/trust faithfully; no engine change needed now.
- **Why this unblocks Humana matching:** BOB Humana customers store `humana_id`=`H########` (no MBI); commission files carry MBI + a 9-digit PID (no H-id) → no shared key, so commission rows can't auto-match BOB Humana customers by ID. Once Sub-project B (built on this engine) lets agents add a customer's MBI, commission matching by MBI starts working.

## Open items (non-blocking)
- None for A. (B/C/D each warrant their own brainstorm; the conflict review UI shape, edit-form field grouping, and filter dimensions are decided in those cycles.)
