# Merge-Engine Autoflush Fix — Design Spec

**Date:** 2026-07-17
**Status:** Approved (design) — ready for implementation plan
**Author:** Tim + assistant (brainstorm)

## Why

`merge_customers(keeper_id, loser_ids, agency_id, actor)` in `app/customers.py` — the
engine that collapses duplicate customer records (used by BOTH the `scripts/
merge_no_mbi_clusters.py` batch tool AND the `/customers/merge` UI path) — has two
Postgres-only bugs that share one root cause. They blocked ~41 of the safe dob_match
duplicate merges on 2026-07-17 (the run committed ~100, then aborted mid-batch).

**Root cause:** the function performs a sequence of `synchronize_session=False` bulk
UPDATEs, per-row attribute changes, and deletes. SQLAlchemy **autoflush** fires between
these (any query in the sequence triggers it), pushing *partial* state to Postgres in an
order that violates a constraint. This is invisible on SQLite (looser constraint timing)
— which is exactly why it reached prod.

**Two observed failures, one cause:**
- **Bug 1 (MBI unique-index):** in the fill-blanks step, the keeper adopts a loser's MBI
  while the loser still holds it → both rows momentarily carry it → `UniqueViolation` on
  the partial unique index `ix_customers_mbi` at the next autoflush. The code already
  clears the donor's MBI in the same Python block (`_UNIQUE_FILL_FIELDS = {"mbi"}`), but a
  mid-function autoflush flushes the keeper's new MBI BEFORE the donor-clear flushes.
  Hit on the 3-way "Annie Maready" cluster (loser 2200 held MBI `7WY1YQ0NP99`, keeper
  7493 adopting).
- **Bug 2 (AOR customer_id):** the AOR-collision loop sets `row.customer_id = keeper.id`
  on loser AOR chapters; a mid-loop autoflush pushes a `customer_aor_history.customer_id`
  update with an unresolved value (`None` observed in the SQL trace). Hit whenever keeper
  + loser share a `(carrier, effective_date)` chapter (e.g. Humana eff 2024-01-01) — which
  is why all ~41 remaining dob_match clusters (they all have AOR history) are blocked,
  while the ~100 without overlapping AOR merged fine.

## The fix

Wrap the mutation sequence of `merge_customers` — reattach child models → AOR-collision
move/delete → CarrierIdCrosswalk move/delete → MatchSuggestion repoint → fill-blanks
(incl. the MBI donor-clear) → delete losers — in a single:

```python
with db.session.no_autoflush:
    ...  # all the reattach/move/clear/delete logic
# (caller still owns the commit, unchanged)
```

With autoflush suppressed, no partial state flushes mid-sequence; every move, clear, and
delete is staged in the session and lands together when the caller commits. The keeper's
MBI-adopt and the donor's MBI-clear settle atomically (no transient duplicate); the AOR
`customer_id` updates flush only after `keeper.id` is fully resolved.

**What stays OUTSIDE the block:** the early guards that run before any mutation — the
keeper/loser fetch (agency-scoped) and the contradiction check (`{ok: False, error:
"contradictory dob or mbi in cluster"}` when dobs/mbis differ). Those are reads/validation
and must be free to query normally; only the mutation sequence (from the first reattach
UPDATE through the loser deletes) is wrapped. Confirm the block does not swallow a needed
flush the `log_event` audit write depends on — `log_event` runs after the mutations and
before the caller's commit; verify it still records correctly under the wrap (it reads
`keeper.id`, already resolved).

**Why `no_autoflush` and not reordering:** it's the smallest, most surgical change —
directly kills the root cause for BOTH bugs at once, with the lowest blast radius. It's
the exact pattern already proven in this codebase (the UHC commission resolver
`_crosswalk`/`_match_by_mbi`/`_find_name_dob_match` no_autoflush fix, commit c1ba8c2).
The caller's transaction ownership (`merge_customers` never commits; the caller does) is
unchanged.

**Scope of the change:** `merge_customers` only. Because the `/customers/merge` UI path
(`execute_merge`) delegates to the same engine, it is fixed for free — the review
confirms this (no separate change needed).

## Architecture / data flow

Unchanged — this is a defect fix, not a redesign. The function's inputs, return dict
(`{ok, merged, filled, moved, error}`), caller-owns-commit contract, contradiction-refusal
(different dob/mbi across the cluster), and fill-blanks precedence all stay identical. The
only change is that its mutation body runs inside `no_autoflush`.

## Error handling

Unchanged behavior: the function still returns `{ok: False, error: "contradictory dob or
mbi in cluster"}` when dobs/mbis conflict, and the caller still owns rollback. With the
fix, a *legitimate* merge no longer raises a spurious `UniqueViolation`/`IntegrityError`
mid-sequence. The batch script's existing per-cluster try/rollback stays as a backstop.

## Testing

**1. SQLite regression tests** (`tests/test_dedup.py` or `tests/test_customer_merge.py`)
reproducing the two logical scenarios:
- **MBI-adopt:** a cluster where the keeper has no MBI and a loser carries one → after
  merge, the keeper holds the MBI, the loser is gone, and no integrity error is raised.
  Include the 3-way shape (keeper + two losers, one loser carrying the MBI).
- **Shared AOR chapter:** keeper + loser each have a `CustomerAorHistory` row with the
  SAME `(carrier, effective_date)` → after merge, the keeper has exactly one such chapter
  (the duplicate dropped), no AOR row has a NULL customer_id, and the loser is gone.

These lock the logic + document intent. (They may pass pre-fix on SQLite — that's
expected and fine; SQLite can't reproduce the flush-timing failure. Their value is
regression-locking the behavior + expressing the scenarios explicitly.)

**2. Real-Postgres gate (the DEFINITIVE proof — the hard-won lesson: "real-Postgres
`--apply` IS part of the test").** After the code lands + SQLite suite is green:
- Deploy to the VPS → DB backup → dry-run `scripts/merge_no_mbi_clusters.py` on the
  remaining ~41 dob_match clusters → `--apply` → verify: total money (CommissionLineItem
  raw_amount sum) unchanged, active-policy count unchanged, line-item count unchanged,
  **0 AOR rows with NULL customer_id, 0 orphaned policies**, and the dob_match cluster
  count drops to ~0. This single action both PROVES the fix on real Postgres AND clears
  the actual remaining duplicates.

## Rollout

1. Fix + SQLite tests on a branch → full suite green → per-task + opus whole-branch
   review (money/identity path).
2. Merge → deploy (no migration — pure logic change).
3. Run the real-Postgres gate above (backup first) → the ~41 clusters merge.
4. Follow-up (separate, after the engine is proven): batch-confirm the ~15 Jr/III
   `name_only` cases (real record + suffix-dropped stub, same person, only the real row
   has a DOB → currently human-confirm by design). The ~63 `conflict` clusters (2 different
   real MBIs — some legit coexistence like Jana Benson's Medigap+DVH, some cross-carrier
   switchers like Barbara Overcash) stay for human review, never auto-merged.

## Build method

Subagent-driven-development (fresh implementer + per-task review + opus whole-branch
review — it's a money/identity path). No migration. Assistant deploys + runs the
Postgres gate over SSH (DB backup first).

## Out of scope (noted for later)

- **Postgres-in-CI test harness** — running the suite against a real Postgres would catch
  this whole "SQLite hides Postgres constraint-timing bugs" class permanently. Genuinely
  valuable, but it's its own infrastructure project (a test Postgres + dual-DB fixtures),
  bigger than this fix. Logged in BACKLOG.
- **The Jr/III name_only batch-merge** — a follow-up once the engine is proven (above).
- **The 63 conflict clusters** — human review in the merge UI, never auto.
