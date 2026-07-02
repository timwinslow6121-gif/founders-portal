# Customer Name Normalization + Preferred Name + Merge UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make customer names consistent (so dedup + search work), add a `preferred_name` "goes-by" separate from the legal name, and give admins a rich review-and-merge UI for `name_only` duplicate clusters.

**Architecture:** Reuse `app/names.py normalize_person_name` (parser) + `app/dedup.py find_no_mbi_clusters` + `app/customers.py merge_customers` (item 2). Phase 1: a `before_insert`/`before_update` SQLAlchemy event keeps `full_name` in sync with first+last across all write paths (not a freeze — humans edit freely); a dry-run/apply backfill canonicalizes existing rows; a new `preferred_name` column + `address_as()` seam handle conversational addressing. Phase 2: extend the existing `/admin/customers/duplicates` view/template with per-row context + gated merge.

**Tech Stack:** Python 3.10, Flask, Flask-SQLAlchemy, Flask-Migrate (Alembic), Jinja2, pytest (SQLite in tests; real Postgres for the backfill apply).

**Spec:** `docs/superpowers/specs/2026-07-02-customer-name-normalization-and-merge-ui-design.md`

## Global Constraints

- Every customer query MUST be agency-scoped (`filter(... agency_id == ...)`). Missing scope = cross-tenant leak.
- Reuse `app.names.normalize_person_name(raw) -> (first, mi, last, full)` — do NOT write a new name parser.
- Migration head is **032**; the new migration is **033** (`down_revision = "032"`).
- The `full_name` sync event must NOT freeze names: a human editing `first_name`/`last_name` is always allowed; the event only recomputes `full_name` to match the parts. It must only override `full_name` when first/last are present (a blank-first stub keeps its raw `full_name`).
- `preferred_name` is human-set only (never written by imports); NULL/blank falls back to legal `first_name`.
- Backfill skips `manually_edited=True` rows. Dry-run default; `--apply` writes; idempotent.
- The middle initial has NO column — it rides inside `first_name` as `"First M."`.
- All times reported to humans in EST/EDT (DB is UTC).

---

### Task 1: `full_name` sync event (keep full_name = first + last, never freeze)

**Files:**
- Modify: `app/models.py` (add a SQLAlchemy event listener near the `Customer` class)
- Test: `tests/test_customer_name_sync.py`

**Interfaces:**
- Consumes: `Customer` model.
- Produces: an event that, on insert/update, sets `full_name = f"{first} {last}".strip()` when both parts are present; leaves `full_name` untouched when `first_name` is blank/empty.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_customer_name_sync.py
import pytest
from app import create_app
from app.extensions import db
from app.models import Customer, Agency


@pytest.fixture
def ctx():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        yield ag.id
        db.session.remove(); db.drop_all()


def test_full_name_synced_from_parts_on_insert(ctx):
    c = Customer(agency_id=ctx, first_name="John", last_name="Connelly")
    db.session.add(c); db.session.commit()
    assert c.full_name == "John Connelly"


def test_full_name_resynced_when_human_edits_first_name(ctx):
    c = Customer(agency_id=ctx, first_name="Jon", last_name="Smith")
    db.session.add(c); db.session.commit()
    assert c.full_name == "Jon Smith"
    c.first_name = "John"            # human corrects a carrier typo
    db.session.commit()
    assert c.full_name == "John Smith"   # event resynced, edit NOT blocked


def test_blank_first_name_keeps_raw_full_name(ctx):
    # commission stub: name only in full_name, blank first/last
    c = Customer(agency_id=ctx, first_name="", last_name="", full_name="CONNELLY, JOHN")
    db.session.add(c); db.session.commit()
    assert c.full_name == "CONNELLY, JOHN"   # event did NOT clobber it to " "
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_customer_name_sync.py -v`
Expected: FAIL — `test_full_name_synced_from_parts_on_insert` gets `full_name=None` (no event yet).

- [ ] **Step 3: Write minimal implementation**

Add to `app/models.py` after the `Customer` class definition:

```python
from sqlalchemy import event as _sa_event


def _sync_customer_full_name(mapper, connection, target):
    """Keep full_name = first + last when both parts are present.
    NOT a freeze: human edits to first/last are allowed and just re-sync full_name.
    A blank-first stub (name only in full_name) is left untouched."""
    first = (target.first_name or "").strip()
    last = (target.last_name or "").strip()
    if first or last:
        target.full_name = f"{first} {last}".strip()


_sa_event.listen(Customer, "before_insert", _sync_customer_full_name)
_sa_event.listen(Customer, "before_update", _sync_customer_full_name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_customer_name_sync.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite (event touches every Customer write)**

Run: `python3 -m pytest -q`
Expected: all green (was 457). If any existing test asserted a `full_name` that differed from `first+last`, that test encoded the drift bug — update it to the synced value and note it in the report.

- [ ] **Step 6: Commit**

```bash
git add app/models.py tests/test_customer_name_sync.py
git commit -m "feat: keep Customer.full_name in sync with first+last (event, not a freeze)"
```

---

### Task 2: `preferred_name` column (migration 033)

**Files:**
- Create: `migrations/versions/033_add_preferred_name.py`
- Modify: `app/models.py` (add the column to `Customer`)
- Test: `tests/test_customer_name_sync.py`

**Interfaces:**
- Consumes: `Customer` model.
- Produces: `Customer.preferred_name` (nullable String(128)).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_customer_name_sync.py
def test_preferred_name_column_exists_and_defaults_null(ctx):
    c = Customer(agency_id=ctx, first_name="Donald", last_name="Horstmann")
    db.session.add(c); db.session.commit()
    assert c.preferred_name is None
    c.preferred_name = "Craig"
    db.session.commit()
    assert c.preferred_name == "Craig"
    assert c.first_name == "Donald"   # legal name unchanged
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_customer_name_sync.py::test_preferred_name_column_exists_and_defaults_null -v`
Expected: FAIL — `AttributeError: 'Customer' object has no attribute 'preferred_name'`.

- [ ] **Step 3: Add the column + migration**

In `app/models.py`, in the `Customer` name block (after `full_name`):

```python
    # Preferred "goes-by" name — human-set only; blank => use legal first_name.
    preferred_name    = db.Column(db.String(128))
```

Create `migrations/versions/033_add_preferred_name.py`:

```python
"""add customers.preferred_name

Revision ID: 033
Revises: 032
"""
from alembic import op
import sqlalchemy as sa

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customers", sa.Column("preferred_name", sa.String(length=128), nullable=True))


def downgrade():
    op.drop_column("customers", "preferred_name")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_customer_name_sync.py::test_preferred_name_column_exists_and_defaults_null -v`
Expected: PASS (SQLite test DB uses `db.create_all()`, so the column exists from the model).

- [ ] **Step 5: Commit**

```bash
git add app/models.py migrations/versions/033_add_preferred_name.py tests/test_customer_name_sync.py
git commit -m "feat: add Customer.preferred_name column (migration 033)"
```

---

### Task 3: `address_as` seam + make `preferred_name` an editable provenance field

**Files:**
- Modify: `app/names.py` (add `address_as`)
- Modify: `app/customer_provenance.py` (add `preferred_name` to `PROVENANCE_FIELDS`)
- Test: `tests/test_customer_name_sync.py`

**Interfaces:**
- Consumes: `Customer` (fields `preferred_name`, `first_name`).
- Produces: `address_as(customer) -> str` (preferred_name if truthy, else first_name, else "").

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_customer_name_sync.py
from app.names import address_as


def test_address_as_prefers_goes_by_then_legal_first(ctx):
    c = Customer(agency_id=ctx, first_name="Donald", last_name="Horstmann")
    db.session.add(c); db.session.commit()
    assert address_as(c) == "Donald"          # no preferred set -> legal first
    c.preferred_name = "Craig"; db.session.commit()
    assert address_as(c) == "Craig"           # preferred wins for greetings


def test_preferred_name_is_a_provenance_editable_field():
    from app.customer_provenance import PROVENANCE_FIELDS
    assert "preferred_name" in PROVENANCE_FIELDS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_customer_name_sync.py -k "address_as or provenance_editable" -v`
Expected: FAIL — `ImportError: cannot import name 'address_as'`.

- [ ] **Step 3: Implement**

Add to `app/names.py`:

```python
def address_as(customer):
    """The single source of truth for what to CALL a customer in conversation
    (SMS, email, letters, greetings). Preferred "goes-by" name if set, else the
    legal first name. Legal name still governs enrollment/MBI/official docs."""
    return (getattr(customer, "preferred_name", None) or customer.first_name or "").strip()
```

In `app/customer_provenance.py`, add `"preferred_name"` to the `PROVENANCE_FIELDS` list (so the inline profile editor accepts it):

```python
PROVENANCE_FIELDS = [
    "mbi", "humana_id", "first_name", "last_name", "dob", "gender",
    "phone_primary", "phone_secondary", "email", "address1", "city",
    "state", "zip_code", "county", "medicaid_level", "medicaid_id",
    "preferred_name",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_customer_name_sync.py -k "address_as or provenance_editable" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/names.py app/customer_provenance.py tests/test_customer_name_sync.py
git commit -m "feat: address_as() seam + preferred_name is an editable provenance field"
```

---

### Task 3.5: Consistency guards — matcher/storage agree + BOB path stays canonical

**Files:**
- Modify (only if the BOB check finds a gap): `app/upload.py` (`_upsert_customer_from_policy`)
- Test: `tests/test_customer_name_sync.py`

**Interfaces:**
- Consumes: `normalize_person_name` (storage), `integrity._norm_name` (matcher), the `full_name` sync event (Task 1), `find_no_mbi_clusters` (item 2).
- Produces: two guard tests (durability #2 + spec 1c) that lock in the invariants.

- [ ] **Step 1: Write the failing/guard tests**

```python
# append to tests/test_customer_name_sync.py
from app.integrity import _norm_name
from app.names import normalize_person_name
from app.dedup import find_no_mbi_clusters


def test_storage_and_matcher_agree_on_identity(ctx):
    """A cluster a human can SEE (same person, messy shapes) must be one the engine can
    MERGE: after normalization, the matcher key is identical across shape variants."""
    # storage normalization of the messy shapes -> canonical full_name
    shapes = ["CONNELLY, JOHN", "John Connelly", "john  connelly"]
    canon_fulls = []
    for s in shapes:
        first, mi, last, full = normalize_person_name(s)
        canon_fulls.append(f"{first} {last}".strip())
    # the matcher key must be identical for all canonical forms (so they cluster + merge)
    keys = {_norm_name(f) for f in canon_fulls}
    assert len(keys) == 1, f"matcher disagrees across canonical shapes: {keys}"


def test_normalized_row_is_not_reflagged_as_drift(ctx):
    """A row the backfill 'fixed' (full_name == first+last) must NOT be seen as drift by
    the sync event on the next write."""
    c = Customer(agency_id=ctx, first_name="John", last_name="Connelly")
    db.session.add(c); db.session.commit()            # event sets full_name
    before = c.full_name
    c.phone_primary = "828-555-0000"                  # unrelated edit triggers before_update
    db.session.commit()
    assert c.full_name == before == "John Connelly"   # stable, no re-drift
```

- [ ] **Step 2: Run tests to verify they pass (they are guard/characterization tests)**

Run: `python3 -m pytest tests/test_customer_name_sync.py -k "agree or reflagged" -v`
Expected: PASS. If `test_storage_and_matcher_agree_on_identity` FAILS, the storage normalizer and matcher disagree on a real shape — report it; the fix is to align `_norm_name`'s token handling with `normalize_person_name`'s output (do not silently skip).

- [ ] **Step 3: Verify the BOB path stores canonical names (spec 1c)**

Read `_upsert_customer_from_policy` in `app/upload.py` (and the `rec["full_name"]`/first/last it receives). Determine whether BOB-parsed names already arrive canonical (the BOB parsers may already produce "First Last"; the Task-1 sync event also fixes `full_name` regardless). 
- If first/last already arrive clean (or a parser normalizes them), NO code change — state this in the report with the evidence (the parser/line that formats the name).
- If BOB names arrive raw (ALL-CAPS / comma), route them through `normalize_person_name` at the upsert seam (mirror the commission path). Add a test that a raw BOB name upserts canonical. Only change code if the gap is real.

- [ ] **Step 4: Run the suite**

Run: `python3 -m pytest tests/test_customer_name_sync.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_customer_name_sync.py app/upload.py
git commit -m "test: matcher/storage consistency + normalized rows don't re-drift (+ BOB canonical if gap)"
```

(Commit `app/upload.py` only if Step 3 found a real gap and changed it.)

---

### Task 4: preferred_name on the customer profile (editor + display hint)

**Files:**
- Modify: `app/templates/customer_profile.html` (add a `preferred_name` inline-editable field + a "goes by" display hint next to the legal name)
- Test: manual render-verify (documented) — the save path is the existing `customer_set_field` route, already tested; provenance acceptance was proven in Task 3.

**Interfaces:**
- Consumes: `address_as` (Task 3), `customer.preferred_name`, the existing `/customers/<id>/field` POST route (accepts any field in `PROVENANCE_FIELDS`).
- Produces: profile UI to set/see the goes-by name.

- [ ] **Step 1: Locate the profile's name header + an existing inline-editable field**

Run: `grep -n "full_name\|display_name\|data-field\|/field" app/templates/customer_profile.html | head`
Expected: find the name header near the top and at least one existing inline field editor to copy the pattern (the profile already inline-edits provenance fields like phone/address via POST `/customers/<id>/field`).

- [ ] **Step 2: Add the display hint next to the legal name**

Near the profile's name header, when preferred differs from legal first, show the goes-by. Match the file's existing markup/token idiom (text uses `var(--ivory)`/`var(--slate)`, never `var(--ink)`; autoescape on, no `|safe` on name data):

```html
<h1>{{ customer.full_name }}
  {% if customer.preferred_name and customer.preferred_name != customer.first_name %}
    <span style="color: var(--slate); font-size: 0.7em;">— goes by "{{ customer.preferred_name }}"</span>
  {% endif %}
</h1>
```

- [ ] **Step 3: Add the inline-editable preferred_name field**

In the profile's editable-fields section, copy the existing inline-field pattern (the one that POSTs `field=phone_primary` to `/customers/<id>/field`) and change it to `field=preferred_name`, labeled "Goes by (preferred name)". Reuse the page's existing inline-edit JS — do NOT invent a new save path (the route already accepts `preferred_name` after Task 3).

- [ ] **Step 4: Render-verify**

Start the app (or a test request context) as an admin and load a customer profile; confirm the page returns 200, the "Goes by" field renders, and setting it via the existing inline editor persists (POST `/customers/<id>/field` field=preferred_name). Document how you verified (test client or manual). Confirm no `var(--ink)` used as a text color and no `|safe` on `preferred_name`.

- [ ] **Step 5: Commit**

```bash
git add app/templates/customer_profile.html
git commit -m "feat: preferred_name editor + goes-by display hint on customer profile"
```

---

### Task 5: preferred_name survives a merge (fill-blanks-only)

**Files:**
- Modify: `app/customers.py` (`merge_customers` fill field list — `_MERGE_FILL_FIELDS`)
- Test: `tests/test_customer_merge.py`

**Interfaces:**
- Consumes: `merge_customers` (item 2).
- Produces: `preferred_name` included in the fill-blanks-only reconcile.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_customer_merge.py
def test_merge_inherits_preferred_name_into_blank_keeper(ctx):
    agency_id, actor = ctx
    keeper = _c(agency_id, first_name="Donald", last_name="Horstmann",
                full_name="Donald Horstmann")           # no preferred_name
    loser = _c(agency_id, first_name="Donald", last_name="Horstmann",
               full_name="Donald Horstmann", preferred_name="Craig")
    db.session.commit()
    merge_customers(keeper.id, [loser.id], agency_id, actor); db.session.commit()
    assert keeper.preferred_name == "Craig"     # goes-by not lost


def test_merge_does_not_overwrite_keeper_preferred_name(ctx):
    agency_id, actor = ctx
    keeper = _c(agency_id, first_name="A", last_name="B", full_name="A B",
                preferred_name="Keep")
    loser = _c(agency_id, first_name="A", last_name="B", full_name="A B",
               preferred_name="Lose")
    db.session.commit()
    merge_customers(keeper.id, [loser.id], agency_id, actor); db.session.commit()
    assert keeper.preferred_name == "Keep"      # fill-blanks-only, keeper wins
```

(Use the `ctx`/`_c` fixtures already in `tests/test_customer_merge.py`; if `_c` doesn't accept `preferred_name`, it passes `**kw` through to `Customer(...)` — confirm and use it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_customer_merge.py -k preferred_name -v`
Expected: FAIL — keeper.preferred_name is None (field not in the fill list).

- [ ] **Step 3: Add `preferred_name` to the fill list**

In `app/customers.py`, add `"preferred_name"` to `_MERGE_FILL_FIELDS`:

```python
_MERGE_FILL_FIELDS = (
    "mbi", "humana_id", "dob", "gender", "phone_primary", "phone_secondary",
    "email", "address1", "city", "state", "zip_code", "county",
    "medicaid_level", "medicaid_id", "lead_source", "preferred_name",
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_customer_merge.py -k preferred_name -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/customers.py tests/test_customer_merge.py
git commit -m "feat: merge_customers preserves preferred_name (fill-blanks-only)"
```

---

### Task 6: Name-normalization backfill script (dry-run / --apply)

**Files:**
- Create: `scripts/normalize_customer_names.py`
- Test: `tests/test_normalize_names_backfill.py`

**Interfaces:**
- Consumes: `normalize_person_name` (app/names.py), `Customer`.
- Produces: `plan_name_changes(agency_id) -> list[dict]` (importable, pure — computes `{id, old, new_first, new_last, new_full}` for non-manual rows that would change) + a `main(apply=False)` driver.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_normalize_names_backfill.py
import pytest
from app import create_app
from app.extensions import db
from app.models import Customer, Agency
from scripts.normalize_customer_names import plan_name_changes


@pytest.fixture
def ctx():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        yield ag.id
        db.session.remove(); db.drop_all()


def _c(agency_id, **kw):
    base = dict(agency_id=agency_id, first_name="", last_name="")
    base.update(kw); c = Customer(**base); db.session.add(c); db.session.flush(); return c


def test_blank_first_name_recovered_from_full_name(ctx):
    c = _c(ctx, first_name="", last_name="", full_name="CONNELLY, JOHN")
    db.session.commit()
    changes = plan_name_changes(ctx)
    ch = [x for x in changes if x["id"] == c.id][0]
    assert ch["new_first"] == "John" and ch["new_last"] == "Connelly"


def test_all_caps_and_comma_normalized(ctx):
    c = _c(ctx, first_name="", last_name="", full_name="BRYANT D,KATHERINE")
    db.session.commit()
    ch = [x for x in plan_name_changes(ctx) if x["id"] == c.id][0]
    assert ch["new_first"] == "Katherine D." and ch["new_last"] == "Bryant"


def test_already_clean_is_not_a_change(ctx):
    c = _c(ctx, first_name="John", last_name="Smith", full_name="John Smith")
    db.session.commit()
    assert [x for x in plan_name_changes(ctx) if x["id"] == c.id] == []


def test_manually_edited_is_skipped(ctx):
    c = _c(ctx, first_name="", last_name="", full_name="SMITH, BOB", manually_edited=True)
    db.session.commit()
    assert [x for x in plan_name_changes(ctx) if x["id"] == c.id] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_normalize_names_backfill.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.normalize_customer_names'`.

- [ ] **Step 3: Write the script**

```python
# scripts/normalize_customer_names.py
"""Normalize customer names to the agency's 'First MI. Last' standard.
Recovers first/last for blank-first stubs from full_name; fixes ALL-CAPS + comma shapes.
Skips manually_edited rows. Dry-run by default; --apply writes. Back up the DB before --apply.

Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/normalize_customer_names.py [--apply]
"""
import sys

from app import create_app
from app.extensions import db
from app.models import Customer, Agency
from app.names import normalize_person_name


def _desired(c):
    """Return (first, last, full) the row SHOULD have, or None if it's already correct."""
    # Best source: full_name if first is blank, else first+last.
    src = (c.full_name or "").strip() if not (c.first_name or "").strip() \
        else f"{c.first_name} {c.last_name}".strip()
    first, mi, last, full = normalize_person_name(src)
    if mi:
        first = f"{first} {mi}."           # MI rides inside first_name
        full = f"{first} {last}".strip()
    if not first and not last:
        return None                         # nothing parseable; leave it
    if (first, last, full) == (c.first_name, c.last_name, c.full_name):
        return None                         # already clean
    return (first, last, full)


def plan_name_changes(agency_id):
    out = []
    q = (Customer.query
         .filter(Customer.agency_id == agency_id, Customer.manually_edited.is_(False)))
    for c in q.all():
        d = _desired(c)
        if d:
            out.append({"id": c.id, "old": c.full_name,
                        "new_first": d[0], "new_last": d[1], "new_full": d[2]})
    return out


def main(apply=False):
    app = create_app()
    with app.app_context():
        total = 0
        for ag in Agency.query.all():
            changes = plan_name_changes(ag.id)
            print(f"agency {ag.id}: {len(changes)} names to normalize")
            for ch in changes:
                print(f"  {ch['id']}: {ch['old']!r} -> {ch['new_full']!r}")
                if apply:
                    c = db.session.get(Customer, ch["id"])
                    c.first_name, c.last_name, c.full_name = \
                        ch["new_first"], ch["new_last"], ch["new_full"]
                    total += 1
            if apply:
                db.session.commit()
        print(f"\n{'APPLIED ' + str(total) + ' changes.' if apply else 'DRY-RUN — nothing written. Re-run with --apply.'}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_normalize_names_backfill.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Confirm clean import (no side effects) + full suite**

Run: `python3 -c "import scripts.normalize_customer_names; print('import ok')"`
Then: `python3 -m pytest -q`
Expected: "import ok" (no agency output) + full suite green.

- [ ] **Step 6: Commit**

```bash
git add scripts/normalize_customer_names.py tests/test_normalize_names_backfill.py
git commit -m "feat: scripts/normalize_customer_names.py — dry-run/--apply name canonicalization"
```

---

### Task 7: Rich per-row context in the duplicates merge UI

**Files:**
- Modify: `app/customers.py` (`customer_duplicates` view — enrich each cluster row's context)
- Modify: `app/templates/customer_duplicates.html` (render DOB/MBI/policies/carriers/source/agent per row)
- Test: `tests/test_customer_merge.py`

**Interfaces:**
- Consumes: `find_no_mbi_clusters` (item 2) + the existing `no_mbi_clusters` render (item 2 Task 5).
- Produces: each `no_mbi_clusters` entry's rows carry display context (policy count + carriers, source, agent) for human judgment.

- [ ] **Step 1: Write the failing (data-layer) test**

```python
# append to tests/test_customer_merge.py
def test_duplicates_view_rows_expose_context(ctx):
    """The view must hand the template each row's policy carriers + source so a human
    can judge a name_only cluster."""
    agency_id, actor = ctx
    from app.customers import _cluster_row_context   # new helper
    from app.models import Policy
    a = _c(agency_id, first_name="Bob", last_name="Smith", full_name="Bob Smith",
           source="bob", stub=False)
    db.session.add(Policy(agency_id=agency_id, carrier="UHC", member_id="M1",
                          customer_id=a.id))
    db.session.commit()
    ctxrow = _cluster_row_context(a, agency_id)
    assert ctxrow["carriers"] == ["UHC"]
    assert ctxrow["policy_count"] == 1
    assert ctxrow["source"] == "bob"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_customer_merge.py::test_duplicates_view_rows_expose_context -v`
Expected: FAIL — `ImportError: cannot import name '_cluster_row_context'`.

- [ ] **Step 3: Add the context helper + wire it into the view**

In `app/customers.py`, add:

```python
def _cluster_row_context(customer, agency_id):
    """Per-row context for the duplicate-merge UI so a human can judge a name_only cluster."""
    pols = (Policy.query
            .filter(Policy.agency_id == agency_id, Policy.customer_id == customer.id)
            .with_entities(Policy.carrier).all())
    carriers = sorted({p.carrier for p in pols if p.carrier})
    return {
        "customer": customer,
        "carriers": carriers,
        "policy_count": len(pols),
        "source": customer.source or "-",
        "stub": customer.stub,
        "dob": customer.dob,
        "mbi": customer.mbi or "-",
        "agent": (customer.primary_agent.email if customer.primary_agent else "-"),
    }
```

In `customer_duplicates`, where item 2 built `no_mbi_clusters`, replace the plain `rows` list with context rows:

```python
        no_mbi_clusters.append({
            "signal": cl.signal,
            "keeper": keeper,
            "rows": [_cluster_row_context(r, current_user.agency_id) for r in rows],
        })
```

- [ ] **Step 4: Update the template to render the context**

In `app/templates/customer_duplicates.html`, in the no-MBI cluster section, each row is now a context dict (`row.customer`, `row.carriers`, `row.policy_count`, `row.source`, `row.dob`, `row.mbi`, `row.agent`). Render them in the row line (text colors `var(--ivory)`/`var(--slate)` only, no `var(--ink)`; no `|safe`), keeping the existing keeper marker + `secondary_id` checkbox keyed on `row.customer.id`. Example row cell:

```html
<li>
  {{ row.customer.display_name }}
  <span style="color: var(--slate);">DOB {{ row.dob or '—' }} · MBI {{ row.mbi }}
    · {{ row.policy_count }} policies{% if row.carriers %} ({{ row.carriers|join(', ') }}){% endif %}
    · src {{ row.source }} · {{ row.agent }}</span>
  {% if row.customer.id != cl.keeper.id %}
    <input type="checkbox" name="secondary_id" value="{{ row.customer.id }}"
           {{ 'checked' if cl.signal != 'conflict' else 'disabled' }}>
  {% else %}<em>(keeper)</em>{% endif %}
</li>
```

- [ ] **Step 5: Run tests + render-verify**

Run: `python3 -m pytest tests/test_customer_merge.py tests/test_dedup.py -q`
Then render `/admin/customers/duplicates` as an admin (test client or manual) with a seeded no-MBI cluster; confirm 200 + the context renders. Document how verified.
Expected: PASS + page renders.

- [ ] **Step 6: Commit**

```bash
git add app/customers.py app/templates/customer_duplicates.html tests/test_customer_merge.py
git commit -m "feat: rich per-row context (DOB/MBI/policies/source/agent) in duplicates merge UI"
```

---

### Task 8: Deploy + backfill + verify (operational — with Tim)

**Files:** none (deploy/verify steps documented for the deploy session)

- [ ] **Step 1: Full suite green locally**

Run: `python3 -m pytest -q`
Expected: all green (~470 with new tests).

- [ ] **Step 2: Merge to main + deploy the code (migration 033)**

Documented for the deploy session (controller + Tim):
```
# merge to main, push
# VPS: git pull && ./venv/bin/pip install -r requirements.txt && ./venv/bin/flask db upgrade  (032 -> 033)
#      systemctl restart founders-portal ; confirm ActiveEnterTimestamp advanced, login 200, no errors
```

- [ ] **Step 3: DB backup + dry-run the name backfill (Tim reviews)**

```
# DB backup: PGPASSWORD=... pg_dump ... > /root/founders_pre_name_normalize_$(date +%Y%m%d_%H%M%S).sql
# DRY-RUN:   PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/normalize_customer_names.py
# Tim reviews the old -> new list (spot-check COUCHELL/CONNELLY-family + anything surprising).
```

- [ ] **Step 4: Apply + verify**

```
# APPLY:  ... scripts/normalize_customer_names.py --apply
# Verify: the 496 drift / 313 caps / 252 comma / 44 blank-first counts drop; search finds
#         "COUCHELL, JOHN" as "John Couchell"; the Couchell cluster now surfaces mergeable
#         in /admin/customers/duplicates. Spot-check a labels PDF still renders (legal name).
```

- [ ] **Step 5: Opus whole-branch review before merge (data path)**

Dispatch the final whole-branch review on opus per the SDD skill; triage findings; then merge/deploy.

---

## Self-review notes (for the executor)

- **Opus whole-branch review is required** before merge (this touches a global Customer write event + a bulk name backfill — both data paths). Focus it on: the `full_name` sync event not breaking any existing Customer-writing flow (esp. the blank-first stub path + commission resolver `full_name=` assignments); the backfill's `_desired` never producing an empty name or a wrong split; agency scoping in the new view helper; and that the event + `normalize_person_name` agree (a row the backfill "fixed" shouldn't be re-flagged as drift by the event).
- After deploy: update CLAUDE.md START HERE, `BACKLOG.md`, the session-handoff.
- `address_as` has no forced retrofit this round (labels = legal mailing name; SMS templates are free-text with no auto-greeting today). The seam ships ready; greeting sites adopt it incrementally as found (per the spec).
