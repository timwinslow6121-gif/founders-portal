# Merge-Engine Autoflush Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the mutation body of `merge_customers` in `db.session.no_autoflush` so a mid-function autoflush can no longer push partial state to Postgres in a constraint-violating order — fixing both the MBI-unique-index collision and the AOR customer_id=None bug that block ~41 duplicate-customer merges.

**Architecture:** A one-block defect fix in `app/customers.py merge_customers` (which also backs the `/customers/merge` UI). Two SQLite regression tests lock the logical scenarios; the definitive proof is a real-Postgres `--apply` of the fixed merge against the remaining ~41 clusters (done at deploy, not in this plan's tasks).

**Tech Stack:** Flask 3, Flask-SQLAlchemy, SQLAlchemy `db.session.no_autoflush`. PostgreSQL (prod) / SQLite (tests). No migration, no new dependency.

**Spec:** `docs/superpowers/specs/2026-07-17-merge-engine-autoflush-fix-design.md`

## Global Constraints

- **The fix is `with db.session.no_autoflush:` around the MUTATION body only** — from `loser_ids_resolved = [...]` (currently line ~916) through the end of the function (the `log_event` + `return`). The early guards (keeper/loser fetch, the `contradictory dob or mbi` contradiction check that returns `{ok: False, ...}`) stay OUTSIDE the block — they are reads/validation and must query normally.
- **`merge_customers`'s public contract is UNCHANGED:** same signature `(keeper_id, loser_ids, agency_id, actor)`, same return dict `{ok, merged, filled, moved, error}`, caller-owns-commit (the function NEVER commits — callers do).
- **No migration, no new dependency.** Pure logic change.
- **This ALSO fixes the `/customers/merge` UI path** (`execute_merge` delegates to `merge_customers`) — the whole-branch review must confirm this, no separate change.
- **Tests run on SQLite** (`python3 -m pytest -q`) — the regression tests document/lock the logic; they may pass pre-fix (SQLite can't reproduce the flush-timing failure). The REAL gate is the Postgres `--apply` at deploy (a rollout step, not a task here).
- Test harness: fixtures `app, db_session, agency` (or build an `Agency` inline like `tests/test_dedup.py`); all DB work in `with app.app_context():`; use the `_cust(agency_id, **kw)` helper pattern already in `tests/test_dedup.py`.

---

## File Structure

- **Modify** `app/customers.py` — wrap the mutation body of `merge_customers` (~L916–L1075) in `with db.session.no_autoflush:` (indent the block one level). No logic changes inside.
- **Modify** `tests/test_dedup.py` — add two regression tests (MBI-adopt 3-way; shared AOR chapter).

This is a single-task fix (the change + its tests are one reviewable unit), presented as one task with tight steps.

---

### Task 1: Wrap merge_customers mutation body in no_autoflush + regression tests

**Files:**
- Modify: `app/customers.py` (merge_customers, ~L916–L1075)
- Test: `tests/test_dedup.py` (append two tests)

**Interfaces:**
- Consumes: `merge_customers(keeper_id, loser_ids, agency_id, actor) -> dict` (existing), `CustomerAorHistory`, `Customer` models.
- Produces: no new interface — same function, same return contract.

- [ ] **Step 1: Write the failing/locking regression tests**

Append to `tests/test_dedup.py` (it already imports `db`, `Customer`, `Agency`, `Policy`, `date`, and has the `_cust` helper). Add `CustomerAorHistory` and `merge_customers` to the imports at the top of the file if not present:

```python
from app.models import CustomerAorHistory
from app.customers import merge_customers
```

Then append:

```python
def test_merge_adopts_loser_mbi_three_way(app, db_session):
    """A keeper with no MBI + a loser carrying one → keeper adopts it, loser gone,
    no IntegrityError. 3-way shape (keeper + two losers, one carries the MBI)."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        aid = ag.id
        keeper = _cust(aid, first_name="Annie", last_name="Maready",
                       full_name="Annie Maready", dob=date(1951, 5, 6))   # no mbi
        loser1 = _cust(aid, first_name="Annie", last_name="Maready",
                       full_name="Annie Maready", dob=date(1951, 5, 6),
                       mbi="7WY1YQ0NP99", stub=True)                       # carries mbi
        loser2 = _cust(aid, first_name="Annie", last_name="Maready",
                       full_name="Annie Maready", stub=True)              # no mbi/dob
        db.session.commit()
        res = merge_customers(keeper.id, [loser1.id, loser2.id], aid, "test")
        db.session.commit()
        assert res["ok"] is True and res["merged"] == 2
        k = db.session.get(Customer, keeper.id)
        assert k is not None and k.mbi == "7WY1YQ0NP99"
        assert db.session.get(Customer, loser1.id) is None
        assert db.session.get(Customer, loser2.id) is None


def test_merge_shared_aor_chapter_no_null_customer(app, db_session):
    """Keeper + loser each hold the SAME (carrier, effective_date) AOR chapter →
    after merge the keeper has exactly one, no AOR row has NULL customer_id, loser gone."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        aid = ag.id
        keeper = _cust(aid, first_name="Jerry", last_name="Goodman",
                       full_name="Jerry Goodman", dob=date(1945, 5, 16))
        loser = _cust(aid, first_name="Jerry", last_name="Goodman",
                      full_name="Jerry Goodman", dob=date(1945, 5, 16), stub=True)
        for cid in (keeper.id, loser.id):
            db.session.add(CustomerAorHistory(
                agency_id=aid, customer_id=cid, carrier="Humana",
                effective_date=date(2024, 1, 1)))
        db.session.commit()
        res = merge_customers(keeper.id, [loser.id], aid, "test")
        db.session.commit()
        assert res["ok"] is True
        chapters = CustomerAorHistory.query.filter_by(customer_id=keeper.id).all()
        assert len(chapters) == 1 and chapters[0].effective_date == date(2024, 1, 1)
        # no orphaned / null-customer AOR rows anywhere
        assert CustomerAorHistory.query.filter(
            CustomerAorHistory.customer_id.is_(None)).count() == 0
        assert db.session.get(Customer, loser.id) is None
```

- [ ] **Step 2: Run the new tests (they should PASS on SQLite even pre-fix)**

Run: `python3 -m pytest tests/test_dedup.py -k "adopts_loser_mbi or shared_aor" -v`
Expected: PASS (SQLite doesn't reproduce the flush-timing failure — that's expected; these lock the LOGIC + document intent per the spec). If either FAILS, that's a real logic problem — stop and report.

- [ ] **Step 3: Apply the fix — wrap the mutation body in no_autoflush**

In `app/customers.py`, in `merge_customers`, locate the line right after the contradiction-check `return` (~L914). The mutation body begins at:

```python
    loser_ids_resolved = [l.id for l in losers]
```

Wrap everything from that line through the end of the function (the `log_event(...)` call and the final `return {...}`) in a `with db.session.no_autoflush:` block — indent that whole span one additional level. The guards ABOVE it (keeper/loser fetch, `everyone`/`dobs`/`mbis` contradiction check + its `return`) stay OUTSIDE, unchanged.

Concretely, change:

```python
    loser_ids_resolved = [l.id for l in losers]

    # Count PolicyPayments that will follow transitively ...
    loser_policy_ids = [ ... ]
    ...
    log_event(
        action="customer_merge",
        ...
    )

    return {
        "ok": True,
        "merged": len(losers),
        ...
    }
```

to:

```python
    with db.session.no_autoflush:
        loser_ids_resolved = [l.id for l in losers]

        # Count PolicyPayments that will follow transitively ...
        loser_policy_ids = [ ... ]
        ...
        log_event(
            action="customer_merge",
            ...
        )

        return {
            "ok": True,
            "merged": len(losers),
            ...
        }
```

(Everything inside is unchanged — only the added `with` line and the one-level re-indent of the existing body. The `return` staying inside the `with` is fine — exiting the block on return does not roll back; the caller still commits.)

Add a brief comment above the `with` explaining WHY:

```python
    # All mutations run under no_autoflush: this function does a sequence of
    # synchronize_session=False bulk UPDATEs + per-row changes + deletes, and a
    # mid-sequence autoflush (any query triggers one) can push partial state to
    # Postgres in a constraint-violating order — the keeper adopting a loser's MBI
    # before the donor-clear flushes (ix_customers_mbi UniqueViolation), or an AOR
    # customer_id update flushing before keeper.id is settled. Suppressing autoflush
    # stages everything and lets it land together at the caller's commit. Invisible
    # on SQLite; reproduced live on Postgres 2026-07-17 (Annie Maready 3-way + shared
    # Humana AOR chapters). See docs/superpowers/specs/2026-07-17-merge-engine-autoflush-fix-design.md.
```

- [ ] **Step 4: Run the merge tests + full dedup/merge suites**

Run: `python3 -m pytest tests/test_dedup.py tests/test_customer_merge.py -v`
Expected: PASS (all — the two new tests + all existing merge/dedup tests; the fix must not regress any).

- [ ] **Step 5: Run the FULL suite**

Run: `python3 -m pytest -q`
Expected: PASS — baseline was 638 + the 2 new tests, no regressions.

- [ ] **Step 6: Commit**

```bash
git add app/customers.py tests/test_dedup.py
git commit -m "fix: wrap merge_customers mutations in no_autoflush (Postgres MBI + AOR bugs)"
```

---

## Deployment + real-Postgres gate (assistant runs after the whole-branch review — NOT a task the reviewer gates)

1. Merge branch to main.
2. Back up prod DB: `PGPASSWORD=<from .env> pg_dump -U founders_user -h localhost founders_portal > /root/founders_pre_mergefix_$(date +%Y%m%d_%H%M%S).sql`.
3. `cd /var/www/founders-portal && git pull && systemctl restart founders-portal` (no migration).
4. **The real-Postgres gate (proves the fix AND clears the data):** record pre-state (customer count, CommissionLineItem raw_amount sum, active-policy count, line-item count), then dry-run `scripts/merge_no_mbi_clusters.py` → `--apply`. Verify: money sum unchanged, active-policy + line-item counts unchanged, **0 AOR rows with NULL customer_id, 0 orphaned policies**, and the dob_match cluster count drops to ~0 (from ~41). If ANY invariant moves or an error recurs, restore from the backup and report.
5. Confirm restart cycled + `/admin/customers/duplicates` loads.

---

## Self-Review

**Spec coverage:** the `no_autoflush` wrap (spec §The fix) → Task 1 Step 3 ✓; guards-stay-outside (spec's "What stays OUTSIDE the block") → Step 3 explicitly keeps the contradiction check outside ✓; the two SQLite regression scenarios (spec §Testing 1) → the two tests in Step 1 ✓; real-Postgres gate (spec §Testing 2) → Deployment step 4 ✓; UI path fixed-for-free → Global Constraints + review note ✓; unchanged contract → Global Constraints ✓; no migration → header + Global Constraints ✓.

**Placeholder scan:** the `...` inside the Step-3 before/after code blocks represent the EXISTING unchanged body (explicitly stated as "everything inside is unchanged") — not a placeholder for the implementer to fill, but the real code they leave alone. All test code is complete and runnable.

**Type consistency:** `merge_customers(keeper_id, loser_ids, agency_id, actor)` and its `{ok, merged, filled, moved, error}` return are used identically in both tests and match the existing signature (verified against app/customers.py L881). `CustomerAorHistory(agency_id, customer_id, carrier, effective_date)` matches the model. `_cust(aid, **kw)` matches the helper in tests/test_dedup.py.
