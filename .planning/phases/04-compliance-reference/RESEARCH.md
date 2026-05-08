# Phase 4: Data Integrity — Research

**Researched:** 2026-05-07
**Domain:** Flask/SQLAlchemy/PostgreSQL data cleanup, Alembic partial index migrations, inline UI resolution flows
**Confidence:** HIGH — all findings from direct code inspection, no speculation

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: Backfill script sets `mbi=""` → NULL on both `policies` and `customers` tables for all Humana records. Run on VPS before migration.
- D-02: Migration adds a partial unique index on `customers.mbi WHERE mbi IS NOT NULL` — replaces current simple unique index.
- D-03: Real MBI backfill from MedicareCenter or external BOB is deferred.
- D-04: Humana commission file provides no MBI (`mbi: None` in `extract_humana`). PolicyPayment has no Humana MBI data to backfill from — confirmed dead end.
- D-05: Hard delete the 29 shell customers with no MBI and no humana_id. No report-first step needed.
- D-06: Script verifies zero dependents (notes, contacts, AOR history, policies) before deleting. Any record with dependents is skipped and reported.
- D-07: Surface duplicate MBIs in agent-facing UI (not admin-only).
- D-08: Merge UI is side-by-side: agent sees both profiles and picks which fields/records to keep. All notes, contacts, policies, and AOR history from discarded record migrate to canonical before deletion.
- D-09: No auto-merge. Always flag, always let agent decide.
- D-10: Admin not required in merge workflow.
- D-11: Unresolvable rows (no MBI, not Humana) are quarantined in memory during import — not silently skipped, not used to create shell customers.
- D-12: Import modal gains a 4th tab: "Unresolvable".
- D-13: Agent resolves inline: assign to existing customer, enter MBI to create/match, or create new customer.
- D-14: No silent failures — Unresolvable tab shows count badge.
- D-15: Standalone reconciliation page in Commissions nav.
- D-16: Customer profile shows commission payment history per policy inline (PolicyPayment records).
- D-17: Reconciliation only compares periods where a matching carrier+period statement has been uploaded.
- D-18: Future-dated policies excluded from gap flagging.
- D-19: Post-death / lapsed gaps surface naturally as "in BOB, not paid."
- D-20: BOB uploads + commission statement uploads are the re-seedable source of truth.
- D-21: Deletion reserved for specific, verified scenarios only.
- D-22: Minimize agent friction — fewer input fields, fewer confirmation steps.

### Claude's Discretion
- Exact UI layout for side-by-side merge view (modal vs full page)
- Whether Unresolvable tab inline resolution uses a modal or inline expansion
- Reconciliation page filter controls (carrier, period, agent) — standard filter bar pattern
- Script output format for shell customer deletion report

### Deferred Ideas (OUT OF SCOPE)
- Humana MBI backfill from MedicareCenter / external BOB
- Commission forecast / future payment prediction
- CMS Plan Finder API, NIPR license sync, expense reimbursement
- Mass stale-customer cleanup beyond the 29 shell customers
</user_constraints>

---

## Summary

Phase 4 is entirely internal data-quality work across five discrete areas. All five areas operate on existing tables — no new models required. The single schema change is replacing the simple unique index on `customers.mbi` with a partial index; this is the only migration needed. The other four areas are code-only changes (backfill scripts, new/modified routes, new template sections).

The implementation order is strictly constrained by one dependency chain: the Humana mbi="" backfill script must run before the partial index migration, because the partial index will succeed only when all empty-string mbi values have already been converted to NULL. Everything else (shell deletion, duplicate detection, unresolvable tab, reconciliation page) can be implemented in any order after the index migration.

**Primary recommendation:** Implement in order — (1) backfill script, (2) partial index migration, (3) shell customer deletion script, (4) duplicate MBI UI, (5) unresolvable tab, (6) reconciliation page. Steps 3-6 are independent of each other once the index is in place.

---

## Work Area 1: Humana MBI Cleanup

### Problem
`app/parsers/humana.py` line 38 emits `mbi: ""` when `Medicare No` starts with `XXXXX`:
```python
"mbi": "" if raw_mbi.startswith("XXXXX") else raw_mbi.upper(),
```
This empty string flows into both `policies.mbi` and `customers.mbi` during `_upsert_customer_from_policy()`. The customer model at `models.py` line 397 declares `unique=True` on `mbi`, which currently only enforces uniqueness on non-NULL values in SQLite (old behavior). PostgreSQL enforces the constraint on all values including `""`, meaning a second Humana policy import attempt would collide on empty string if two Humana customers have empty mbi.

### Current Index (baseline migration, line 141)
```python
batch_op.create_index(batch_op.f('ix_customers_mbi'), ['mbi'], unique=True)
```
This is a standard unique index — it rejects duplicate empty strings in PostgreSQL (unlike NULL, where duplicates are allowed).

### Backfill Script (runs on VPS before migration)
**File:** `scripts/backfill_humana_mbi_null.py`

Two UPDATE statements needed:
1. `UPDATE policies SET mbi = NULL WHERE carrier = 'Humana' AND mbi = ''`
2. `UPDATE customers SET mbi = NULL WHERE mbi = ''` (no carrier filter on customers — a customer's mbi="" could only have come from Humana given how _upsert_customer_from_policy works)

Script must also fix the parser source — change `humana.py` line 38 to emit `None` instead of `""`:
```python
"mbi": None if raw_mbi.startswith("XXXXX") else raw_mbi.upper() or None,
```

Also fix `_upsert_customer_from_policy()` in `upload.py` line 39:
```python
mbi = rec.get("mbi") or None
```
This line already converts empty string to None via `or None`. So the parser fix is the primary fix — the upsert function already guards correctly.

Also fix `bulk_upload()` in `upload.py` line 679:
```python
mbi=rec["mbi"],
```
This passes the empty string directly into the Policy insert without the `or None` guard. Must change to `mbi=rec["mbi"] or None`.

### Migration 014: Replace Unique Index with Partial Index

**File:** `migrations/versions/014_humana_mbi_partial_index.py`

```python
revision = '014'
down_revision = '013'

def upgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.drop_index('ix_customers_mbi')
    op.create_index(
        'ix_customers_mbi',
        'customers',
        ['mbi'],
        unique=True,
        postgresql_where=sa.text('mbi IS NOT NULL'),
    )
    # Also update the ORM column definition behavior — no schema change needed,
    # just document that models.py Customer.mbi should remove unique=True
    # and instead note that uniqueness is enforced by the partial index.

def downgrade():
    op.drop_index('ix_customers_mbi', 'customers')
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_customers_mbi'), ['mbi'], unique=True)
```

**Critical:** `op.create_index` with `postgresql_where` cannot be expressed inside `batch_alter_table` — it must be called directly on `op`. The batch context is only needed to drop the old index.

**models.py change:** Remove `unique=True` from `Customer.mbi` column definition (line 397). The column becomes:
```python
mbi = db.Column(db.String(20), index=True)
```
The partial uniqueness is now enforced at the DB level only; SQLAlchemy's ORM `unique=True` on the column would try to recreate a full unique constraint on `flask db upgrade`.

### Risk
- If any `mbi=""` rows remain when the migration runs, the partial index creation will succeed (empty strings are not NULL, so the WHERE clause excludes them — wait, actually `mbi IS NOT NULL` covers `mbi = ''` as truthy, so empty strings ARE included in the partial index and WILL collide). This confirms the backfill script must convert all `""` to NULL before running the migration.
- Verify with: `SELECT COUNT(*) FROM customers WHERE mbi = '';` and `SELECT COUNT(*) FROM policies WHERE mbi = '';` — both must be 0 before running migration.

---

## Work Area 2: Shell Customer Deletion

### What is a Shell Customer
A customer with `mbi IS NULL` AND `humana_id IS NULL`. These were created from BOB rows that had no resolvable identifier — the old code path (lines 70-81 of `upload.py`) attempted a name-only match and if that failed, fell through to create a customer with `mbi=None, humana_id=None`.

### Deletion Script
**File:** `scripts/delete_shell_customers.py`

Logic (dry-run mode by default, `--execute` flag to apply):
```python
shells = Customer.query.filter(
    Customer.agency_id == agency_id,
    Customer.mbi.is_(None),
    Customer.humana_id.is_(None),
).all()

for c in shells:
    has_notes = c.notes.count() > 0
    has_contacts = c.contacts.count() > 0
    has_aor = c.aor_history.count() > 0
    has_policies = Policy.query.filter_by(
        customer_id=c.id, agency_id=agency_id
    ).count() > 0  # NOTE: policies don't FK to customer_id directly — see below
    ...
```

**IMPORTANT:** `Policy` has no `customer_id` foreign key. Policy linkage to Customer goes through `mbi` (matched at query time), not a stored FK. So "has policies" for a shell customer means: are there any Policy rows with `mbi = c.mbi`? Since shell customers have `mbi=NULL`, there are NO policies with `mbi=NULL` that would link to a specific customer. The dependent check for policies should be: `Policy.query.filter_by(agency_id=agency_id, mbi=None, carrier='Humana').count()` is irrelevant — shells have no MBI so no policies can be linked by MBI. The only risk is if a shell customer was also the `primary_agent_id` target of some AOR history. Check `CustomerAorHistory.customer_id` FK directly.

Correct dependent check:
```python
has_notes    = db.session.query(CustomerNote.id).filter_by(customer_id=c.id).first() is not None
has_contacts = db.session.query(CustomerContact.id).filter_by(customer_id=c.id).first() is not None
has_aor      = db.session.query(CustomerAorHistory.id).filter_by(customer_id=c.id).first() is not None
# No need to check Policy — Policy has no customer_id FK column
```

Shell customers that pass the check get hard-deleted: `db.session.delete(c)`.

### Risk
- Count first in dry run, verify the 29 expected. Any number significantly above 29 means the query is wrong.
- `CustomerContact` and `CustomerNote` have `ondelete="CASCADE"` FKs to customers — but use explicit pre-check anyway to avoid accidental data loss. Cascade will handle the physical delete if dependents do exist (script skips those rows rather than letting cascade fire silently).

---

## Work Area 3: Duplicate MBI Detection + Merge UI

### Detection Query
A duplicate MBI means two or more Customer rows with the same non-null MBI:
```sql
SELECT mbi, COUNT(*) as cnt
FROM customers
WHERE agency_id = :agency_id AND mbi IS NOT NULL
GROUP BY mbi
HAVING COUNT(*) > 1
```

This query should only return rows after the partial unique index is in place if the index is somehow bypassed (e.g., data inserted before the index existed). In practice, duplicates may already exist in the current dataset (inserted before the partial index migration). The query is the canonical source of truth.

SQLAlchemy version:
```python
from sqlalchemy import func
dupes = (db.session.query(Customer.mbi, func.count(Customer.id).label('cnt'))
         .filter(Customer.agency_id == agency_id, Customer.mbi.isnot(None))
         .group_by(Customer.mbi)
         .having(func.count(Customer.id) > 1)
         .all())
```

### New Routes in customers_bp

**`GET /customers/duplicates`** — list all duplicate MBI pairs for the current agent's customers (filtered by `primary_agent_id` for agents, unfiltered for admins).

**`GET /customers/merge/<int:a_id>/<int:b_id>`** — render side-by-side merge UI. Validates both customers exist, same agency, same MBI.

**`POST /customers/merge/<int:a_id>/<int:b_id>`** — execute the merge. Form body: `canonical_id=<id>` plus field-level overrides if implemented. The non-canonical customer is the "discarded" one.

### Merge Operation (atomic, single transaction)
```python
canonical = Customer.query.get(canonical_id)
discarded = Customer.query.get(discarded_id)

# Migrate notes
CustomerNote.query.filter_by(customer_id=discarded.id).update({'customer_id': canonical.id})

# Migrate contacts
CustomerContact.query.filter_by(customer_id=discarded.id).update({'customer_id': canonical.id})

# Migrate AOR history
CustomerAorHistory.query.filter_by(customer_id=discarded.id).update({'customer_id': canonical.id})

# Policy records: no customer_id FK on Policy — nothing to migrate there.
# Any Policy.mbi == discarded.mbi will naturally resolve to canonical after merge
# because canonical has the same MBI.

# Delete discarded customer
db.session.delete(discarded)
db.session.commit()
```

**No Policy migration needed** because Policy has no `customer_id` FK — policies link to customers via MBI match at query time. Since both records share the same MBI, all policy lookups will find the canonical customer after the merge.

### UI Approach (Claude's Discretion: Full Page Preferred)
A modal is too narrow for a side-by-side comparison of two full customer records. A full page at `/customers/merge/<a_id>/<b_id>` gives space for a 2-column layout. Keep it simple: show name, DOB, MBI, phone, address, and primary agent for each; radio buttons to select canonical; one submit button. No per-field granular selection (adds friction; agent picks the better record wholesale per D-22).

### Duplicates List Page
Simple table at `/customers/duplicates`: MBI, Name A, Name B, Agent A, Agent B, "Merge" button linking to the merge page. For agents: only show pairs where at least one customer's `primary_agent_id == current_user.id`. For admins: all pairs.

---

## Work Area 4: BOB Import — Unresolvable Records (4th Tab)

### Where to Hook In: `_upsert_customer_from_policy()` vs. Caller

The unresolvable quarantine does NOT live inside `_upsert_customer_from_policy()`. That function is called after the policy row has already been accepted. The quarantine decision happens BEFORE the policy upsert, in the record loop inside `bulk_upload()` (lines 636-697).

The quarantine condition is: `rec.get("mbi")` is falsy AND `rec["carrier"] != "Humana"`. Humana rows without MBI are expected and go through humana_id / name+DOB+zip matching — they are NOT unresolvable.

### Modified Logic in `bulk_upload()` (lines ~636-697)

Before the existing policy upsert block, add:
```python
# Quarantine check: non-Humana rows with no MBI cannot create a customer
is_unresolvable = (not rec.get("mbi")) and rec.get("carrier") != "Humana"
if is_unresolvable:
    unresolvable.append(rec)  # collect, don't skip entirely — policy still upserted if member_id known
    # NOTE: per D-11, do NOT create a shell customer. Still upsert the policy row (it has a member_id).
    # The customer upsert call below is skipped for unresolvable records.
```

Then at the `_upsert_customer_from_policy(...)` call (line ~695):
```python
if not is_unresolvable:
    try:
        _upsert_customer_from_policy(rec, effective_agent_id, batch.id, bulk_agency_id)
    except Exception as e:
        current_app.logger.warning(f"Customer upsert failed for {rec.get('member_id')}: {e}")
```

The `unresolvable` list is collected per-file. It needs to be persisted so the modal tab can display it after the redirect. Options:
- Store as JSON in `ImportBatch.error_message` field (currently only used for hard errors, reuse would be unclear)
- Add `unresolvable_json` column to `ImportBatch` (cleaner, requires migration)
- Store in server-side session (Flask session, 4KB cookie limit — too small for 196 Humana records)

**Recommendation:** Add `unresolvable_json` TEXT column to `import_batches` in migration 014 (or a separate 015 if preferred). Serialize the unresolvable list there on upload. The `batch_detail` route at `/upload/batch/<id>/detail` already returns a JSON blob — add `"unresolvable"` key to that response.

### Template Changes in `upload.html`

**Tab bar** (lines 101-104) — add 4th tab:
```html
<button class="modal-tab" onclick="showTab('unresolvable')" id="tab-unresolvable">
  Unresolvable <span id="cnt-unresolvable" class="modal-cnt"></span>
</button>
```
Tab button should turn amber (not red) when count > 0 — these need attention but aren't failures.

**Tab content div** — add:
```html
<div id="tab-content-unresolvable" style="display:none;"></div>
```

**`showTab()` function** — update to include `'unresolvable'` in the tab array (currently hardcoded to `['new','updated','missing']`).

**`openBatchDetail()` function** — populate `cnt-unresolvable` from `data.unresolvable.length`.

### Inline Resolution UI (Claude's Discretion: Inline Expansion)
Each unresolvable row in the tab expands inline (click to expand, no separate modal) showing:
- Raw carrier data (name, DOB, plan, effective date)
- Three action buttons: "Find Existing Customer" (search by name), "Enter MBI", "Create New"

"Find Existing Customer" opens a small search input within the row. "Enter MBI" shows an MBI text field + save button that calls a new route `POST /upload/unresolvable/resolve` which accepts `batch_id`, `member_id`, `mbi`, `action` and creates or links the customer. "Create New" is a convenience shortcut for "Enter MBI" → "save" with a generated placeholder. All resolution calls are AJAX.

The resolution route is new: `POST /upload/unresolvable/resolve` in `upload_bp`. It receives the raw carrier data + resolution choice, creates/links the customer, and returns `{ok: True}`.

---

## Work Area 5: BOB ↔ Commission Reconciliation Page

### Data Already Available
`PolicyPayment` model (models.py line 603) has:
- `carrier`, `period_label`, `statement_date` — which statement this came from
- `mbi`, `carrier_member_id`, `member_name_normalized` — member identifiers
- `policy_id` — FK to Policy (populated by match logic in payments.py)
- `match_confidence` — exact_mbi / exact_carrier_id / fuzzy_name / unmatched
- `paid_amount`, `is_chargeback`, `commission_action`

`CommissionStatement` has `agency_id`, `carrier`, `period_label`, `agent_id`.

### Reconciliation Logic
"In BOB, not paid" = a Policy row exists (active, effective_date <= statement_date) for a carrier/period where a CommissionStatement exists for that agent, but no PolicyPayment row matches that policy.

```sql
-- Policies eligible for reconciliation (scoped to agent + carrier + period):
-- Policy is active (status='active'), effective_date <= statement period end,
-- term_date IS NULL or term_date > statement period start

-- For each such policy, check if a PolicyPayment with matching policy_id or mbi exists
-- for that statement.

SELECT p.id, p.full_name, p.carrier, p.mbi, p.plan_name, p.effective_date
FROM policies p
WHERE p.agency_id = :agency_id
  AND p.agent_id = :agent_id
  AND p.carrier = :carrier
  AND p.status = 'active'
  AND p.effective_date <= :period_end_date
  AND (p.term_date IS NULL OR p.term_date > :period_start_date)
  AND NOT EXISTS (
    SELECT 1 FROM policy_payments pp
    WHERE pp.policy_id = p.id
      AND pp.period_label = :period_label
      AND pp.agent_id = :agent_id
  )
```

SQLAlchemy equivalent using `~Policy.id.in_(...)` subquery on PolicyPayment.

"Paid, not in BOB" = a PolicyPayment row with `match_confidence = 'unmatched'` (no Policy found). These already exist in the ledger — the reconciliation page can simply surface them with a different label.

### Route: New in `commission_bp`
**`GET /commissions/reconciliation`** (agent view)
**`GET /admin/commissions/reconciliation`** (admin view, with agent selector)

These closely parallel the existing ledger routes at lines 638-801. The existing ledger query pattern (filter by agent_id, agency_id, period_label, carrier) is directly reusable. The reconciliation page adds the "not paid" query on top.

The template extends the existing commission_ledger.html structure (period/carrier filter bar, summary cards). It adds two sections:
1. "In BOB, not paid" — policies with no matching payment
2. "Paid, not in BOB" — PolicyPayment rows with match_confidence='unmatched'

### Per-Customer Payment History on Customer Profile
New section in `app/templates/customer_profile.html`. The query:
```python
policy_ids = [p.id for p in policies]  # from get_customer_policies(customer)
payments = (PolicyPayment.query
            .filter(PolicyPayment.policy_id.in_(policy_ids),
                    PolicyPayment.agency_id == customer.agency_id)
            .order_by(PolicyPayment.statement_date.desc())
            .all())
```

For Humana customers (policy_id may be NULL on some payments if match was fuzzy): also query by `member_name_normalized` matching the customer's name.

Display as a collapsible table grouped by period: Period | Carrier | Action | Amount | Confidence dot.

### Period Boundary Dates
`period_label` is stored as `"March 2026"` format. The reconciliation query needs start/end dates for each period. Convert:
```python
from datetime import datetime
from dateutil.relativedelta import relativedelta

period_start = datetime.strptime(period_label, "%B %Y").date().replace(day=1)
period_end = period_start + relativedelta(months=1) - relativedelta(days=1)
```
`python-dateutil` is available (it's a transitive dependency of pandas). If not, use `calendar.monthrange`.

---

## Migration Plan

### Ordered Migrations (numbered sequentially from 013)

**014: `humana_mbi_partial_index`**
- Drop `ix_customers_mbi` (unique=True on mbi column)
- Create `ix_customers_mbi` partial unique index: `WHERE mbi IS NOT NULL`
- Add `unresolvable_json` TEXT column to `import_batches` (nullable)
- Prerequisite: backfill script must run first on VPS

Combining these two changes in one migration is appropriate — they're both part of the same "Humana MBI cleanup" work area.

No further migrations needed for Phase 4. All other changes are:
- Code-only (new routes, new scripts, template changes)
- No new tables
- No new columns beyond `import_batches.unresolvable_json`

### Pre-Migration VPS Steps (in order)
1. Run `scripts/backfill_humana_mbi_null.py` (dry-run, then `--execute`)
2. Verify: `SELECT COUNT(*) FROM customers WHERE mbi = '';` returns 0
3. Verify: `SELECT COUNT(*) FROM policies WHERE mbi = '';` returns 0
4. Run `flask db upgrade` to apply migration 014
5. Verify partial index: `\d customers` in psql shows index with WHERE clause

---

## Architecture Patterns

### Existing Patterns to Follow

**Backfill scripts:** Match `scripts/backfill_aor_end_dates.py` — dry-run flag, summary report, single-file standalone script using `app` factory context:
```python
from app import create_app
app = create_app()
with app.app_context():
    ...
```

**New routes in existing blueprints:** Follow the existing 3-line blueprint registration pattern in `app/__init__.py`. No new blueprints needed — merge UI and duplicate detection go in `customers_bp`, reconciliation goes in `commission_bp`.

**AJAX inline edits:** Pattern established by commission type dropdown (customers.py) — POST returns `{ok: True}` or `{error: "..."}`, JS updates DOM on success.

**Alembic partial index:** Must use `op.create_index()` directly (not inside `batch_alter_table`) with `postgresql_where=` kwarg:
```python
op.create_index(
    'ix_customers_mbi',
    'customers',
    ['mbi'],
    unique=True,
    postgresql_where=sa.text('mbi IS NOT NULL'),
)
```

---

## Common Pitfalls

### Pitfall 1: Empty String vs NULL in PostgreSQL Unique Index
PostgreSQL's unique index covers `""` (empty string) — only NULL values are excluded from uniqueness enforcement. If any `mbi=""` rows remain when the partial index is created, the index creation will still succeed (empty strings are NOT NULL), but two rows with `mbi=""` would violate the partial index on the next insert. The backfill script must be verified with a count check before running the migration.

### Pitfall 2: Policy Has No customer_id FK
There is no `Policy.customer_id` column. Policies join to customers via MBI match at query time. This has two implications:
- Shell customer deletion: no need to check Policy table for dependents using customer_id
- Merge operation: no Policy rows need to be updated when merging two customers (same MBI, policies resolve to canonical automatically)

This is also a constraint on the reconciliation query — the Policy→Customer join must go through MBI, not a FK.

### Pitfall 3: ImportBatch.error_message Collision
`import_batches.error_message` is currently only set when `batch.status = "error"`. Storing unresolvable rows in `error_message` would mix concerns. Use a separate `unresolvable_json` column.

### Pitfall 4: Duplicate AOR History After Merge
After migrating AOR history rows from discarded to canonical, the `uq_aor_customer_carrier_date` unique constraint (`customer_id`, `carrier`, `effective_date`) could be violated if both customers had AOR rows with the same carrier and effective date. The merge route must check for this before migrating. If a conflict exists, keep the canonical's AOR row and drop the discarded's duplicate.

### Pitfall 5: models.py unique=True on Customer.mbi
After migration 014, `models.py` line 397 still has `unique=True` on the mbi column. SQLAlchemy's ORM constraint declaration and the actual DB constraint are separate. The `unique=True` in the ORM column definition does not affect PostgreSQL directly (it's advisory for `db.create_all()` only), but it is misleading and could confuse future `flask db migrate` runs. Remove `unique=True` from the column definition — the partial index at DB level is the authoritative constraint.

### Pitfall 6: Reconciliation False Positives for Humana
Humana PolicyPayment rows have `mbi=None` and match by fuzzy name. A Humana policy without a PolicyPayment match will show as "in BOB, not paid." This is correct behavior, but agents need to understand that Humana payment matching is always fuzzy — not a clean MBI match. Add a note in the UI for Humana rows.

---

## Code Examples

### Partial Index Migration (verified pattern for PostgreSQL)
```python
# migrations/versions/014_humana_mbi_partial_index.py
from alembic import op
import sqlalchemy as sa

revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None

def upgrade():
    # Drop the existing full unique index
    op.drop_index('ix_customers_mbi', table_name='customers')
    # Create partial unique index — only enforces uniqueness on non-NULL values
    op.create_index(
        'ix_customers_mbi',
        'customers',
        ['mbi'],
        unique=True,
        postgresql_where=sa.text('mbi IS NOT NULL'),
    )
    # Add unresolvable_json column to import_batches
    op.add_column('import_batches', sa.Column('unresolvable_json', sa.Text(), nullable=True))

def downgrade():
    op.drop_index('ix_customers_mbi', table_name='customers')
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.create_index('ix_customers_mbi', ['mbi'], unique=True)
    op.drop_column('import_batches', 'unresolvable_json')
```

### Duplicate MBI Detection Query
```python
from sqlalchemy import func

def get_duplicate_mbis(agency_id):
    dupes = (db.session.query(Customer.mbi, func.count(Customer.id).label('cnt'))
             .filter(Customer.agency_id == agency_id, Customer.mbi.isnot(None))
             .group_by(Customer.mbi)
             .having(func.count(Customer.id) > 1)
             .all())
    mbi_list = [row.mbi for row in dupes]
    pairs = []
    for mbi in mbi_list:
        customers = Customer.query.filter_by(mbi=mbi, agency_id=agency_id).all()
        pairs.append(customers)
    return pairs
```

### Merge Execute (atomic)
```python
@customers_bp.route('/customers/merge/<int:a_id>/<int:b_id>', methods=['POST'])
@login_required
def execute_merge(a_id, b_id):
    canonical_id = request.form.get('canonical_id', type=int)
    discarded_id = a_id if canonical_id == b_id else b_id

    canonical = Customer.query.filter_by(id=canonical_id, agency_id=current_user.agency_id).first_or_404()
    discarded = Customer.query.filter_by(id=discarded_id, agency_id=current_user.agency_id).first_or_404()

    if canonical.mbi != discarded.mbi:
        flash("Cannot merge customers with different MBIs.", "error")
        return redirect(url_for('customers.duplicates_list'))

    # Handle AOR history constraint — check for duplicate (customer_id, carrier, effective_date)
    existing_aor_keys = {(a.carrier, a.effective_date) for a in canonical.aor_history}
    for aor in list(discarded.aor_history):
        if (aor.carrier, aor.effective_date) in existing_aor_keys:
            db.session.delete(aor)  # drop discarded's duplicate
        else:
            aor.customer_id = canonical.id

    CustomerNote.query.filter_by(customer_id=discarded.id).update({'customer_id': canonical.id})
    CustomerContact.query.filter_by(customer_id=discarded.id).update({'customer_id': canonical.id})

    db.session.delete(discarded)
    db.session.commit()
    flash(f"Merged successfully. {discarded.display_name} → {canonical.display_name}.", "success")
    return redirect(url_for('customers.customer_profile', customer_id=canonical.id))
```

### Unresolvable Quarantine in bulk_upload()
```python
# At the top of the per-file record loop in bulk_upload() (before line 636)
unresolvable = []

for rec in records:
    is_unresolvable = (not rec.get("mbi")) and rec.get("carrier") != "Humana"
    if is_unresolvable:
        unresolvable.append({
            "carrier": rec.get("carrier"),
            "member_id": rec.get("member_id"),
            "full_name": rec.get("full_name"),
            "dob": str(rec.get("dob")) if rec.get("dob") else None,
            "plan_name": rec.get("plan_name"),
            "effective_date": str(rec.get("effective_date")) if rec.get("effective_date") else None,
        })
    # ... existing policy upsert logic ...
    if not is_unresolvable:
        try:
            _upsert_customer_from_policy(rec, effective_agent_id, batch.id, bulk_agency_id)
        except Exception as e:
            current_app.logger.warning(f"Customer upsert failed for {rec.get('member_id')}: {e}")

# After the loop, store unresolvable list on the batch
if unresolvable:
    batch.unresolvable_json = json.dumps(unresolvable)
```

### Reconciliation "In BOB, Not Paid" Query
```python
from sqlalchemy import not_, exists

def get_unpaid_policies(agent_id, agency_id, carrier, period_label, period_start, period_end):
    paid_policy_ids = (db.session.query(PolicyPayment.policy_id)
                       .filter_by(agent_id=agent_id, agency_id=agency_id,
                                  carrier=carrier, period_label=period_label)
                       .filter(PolicyPayment.policy_id.isnot(None))
                       .subquery())
    return (Policy.query
            .filter_by(agent_id=agent_id, agency_id=agency_id, carrier=carrier, status='active')
            .filter(Policy.effective_date <= period_end)
            .filter(db.or_(Policy.term_date.is_(None), Policy.term_date > period_start))
            .filter(~Policy.id.in_(paid_policy_ids))
            .all())
```

---

## Environment Availability

Step 2.6: SKIPPED — no external dependencies. All work is internal Flask/SQLAlchemy/PostgreSQL changes. VPS environment confirmed operational with PostgreSQL 16.

---

## Validation Architecture

Tests are not currently in the project (no test directory found). Phase 4 is data-integrity work where correctness is verified by:
1. Backfill script dry-run output shows expected count (196 policies, ~196 customers)
2. Post-migration SQL count checks (mbi='' returns 0)
3. Shell deletion script dry-run shows 29 skippable/deletable customers
4. Manual smoke test: upload a Humana BOB file, verify no empty-string mbi is written to DB

No automated test framework is configured; this is consistent with the rest of the project.

---

## Sources

### Primary (HIGH confidence)
All findings from direct code inspection:
- `app/models.py` — Customer line 397, Policy line 73, PolicyPayment line 603, CustomerAorHistory line 558
- `app/upload.py` — `_upsert_customer_from_policy()` lines 23-165, `bulk_upload()` lines 576-718, `_detect_carrier()` lines 489-573, `batch_detail()` lines 396-458
- `app/parsers/humana.py` — mbi="" origin line 38
- `app/commission/payments.py` — `extract_humana()` lines 191-225 confirming mbi=None
- `app/commission/routes.py` — ledger routes lines 638-800
- `app/templates/upload.html` — 3-tab modal structure lines 100-113, JS lines 322-384
- `migrations/versions/d27f51392651_baseline_capture_existing_schema.py` — `ix_customers_mbi` line 141
- `migrations/versions/009_plans_table.py` — migration style reference
- `.planning/phases/04-compliance-reference/04-CONTEXT.md` — all decisions D-01 through D-22

### Secondary (MEDIUM confidence)
- Alembic `postgresql_where` kwarg behavior: consistent with SQLAlchemy/Alembic docs; partial index on PostgreSQL is a well-established pattern with no edge cases at this scale.

---

## Metadata

**Confidence breakdown:**
- Humana MBI cleanup: HIGH — source of `""` identified precisely in parser line 38; migration pattern is standard Alembic
- Shell customer deletion: HIGH — dependent model FKs confirmed; no customer_id FK on Policy confirmed
- Duplicate MBI merge: HIGH — merge atomicity pattern is straightforward; AOR unique constraint collision risk identified and handled
- Unresolvable tab: HIGH — hook point in bulk_upload() identified precisely; modal structure fully understood from upload.html
- Reconciliation page: HIGH — PolicyPayment schema fully supports the query; period boundary date handling identified

**Research date:** 2026-05-07
**Valid until:** 2026-06-07 (stable Flask/SQLAlchemy stack, no fast-moving dependencies)
