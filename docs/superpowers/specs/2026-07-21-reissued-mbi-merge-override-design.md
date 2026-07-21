# Reissued-MBI Merge Override — Design

**Date:** 2026-07-21
**Status:** Approved (brainstorm complete) — ready for implementation plan
**Author:** Tim + assistant

## Problem

When CMS reissues a member's MBI (on a re-enrollment / plan switch), the portal
ends up with **two customer records for one person**: same DOB, same address,
same phone, but a **different MBI** and a separate policy keyed under each MBI.

The merge engine (`merge_customers`, `app/customers.py`) and both merge UIs
**hard-block any cluster whose records carry different MBIs** — correct behavior
for catching two genuinely *different* people, but it **false-blocks** a
legitimate reissued-MBI same-person reconcile.

Today these are resolved by a one-off script (`scripts/merge_reissued_mbi.py`,
run for Milton Frazier + Lukisha Truesdale on 2026-07-20): null the stale MBI on
the loser, then `merge_customers`, then term the stale-keyed policy. This design
moves that proven sequence into the merge UI, behind a per-case confirmation,
so Tim can reconcile these himself.

### What this is NOT

Not every different-MBI conflict is a reissued MBI. The override must stay
**per-case, admin-confirmed, and narrowly gated** — never bulk:

- **Cross-carrier switcher** (e.g. Barbara Overcash, UHC+Aetna both active) →
  term the stale row in the cross-carrier switcher pass; do **not** merge.
- **Real coexistence** (e.g. Jana Benson, Medigap + DVH) → two legitimate
  products; never merge. (This case shares an MBI so it is not even a
  `conflict` cluster.)
- **Bare stub** (e.g. Carroll Mullis) → needs data first.

The gate below (same DOB, different MBI, exactly 2 records) structurally
excludes the different-DOB cases (possible different people) and the null-data
cases, and the required confirmation keeps the human in the loop for every one.

## Approach

**Approach A — thin override route, merge engine unchanged.** The
`merge_customers` "one non-null MBI only" guard is correct and load-bearing for
every other caller; we do **not** relax it or add a bypass flag inside it.
Instead we add a **separate, explicit, admin-only override route** that
reproduces the script's sequence server-side (null stale MBI → `merge_customers`
→ term stale policy). The conflict-cluster card surfaces the override sub-form
only when a cluster matches the reissued-MBI shape.

(Rejected: B = an `allow_reissued_mbi` flag inside `merge_customers` — leaks a
"bypass the safety" mode into the safety-critical function all callers share.
C = client-side null-then-submit — puts an identity/money mutation in the
browser with no server gate or audit.)

**Scope:** the `/admin/customers/duplicates` conflict-cluster cards **only**.
The older `/customers/merge/<a>/<b>` (`merge_view`/`execute_merge`) path is left
alone — its premise is "customers already share an MBI", so a reissued-MBI pair
never lands there.

## Section 1 — The gate (`app/dedup.py`)

New helper `is_reissued_mbi_candidate(rows)` → `bool`. Returns True **only** for
the exact reissued-MBI shape:

- exactly **2** records (a clean pair; 3-way reissued is vanishingly rare and
  stays manual),
- both have a **non-null DOB** and the DOBs are **equal**,
- both have a **non-null MBI** and the MBIs **differ**.

Everything else (different DOB, any null DOB, any null MBI, >2 records) returns
False and the cluster stays hard-blocked exactly as today.

The per-cluster dict built in `customer_duplicates()` (`app/customers.py`) gains
`"reissued_candidate": is_reissued_mbi_candidate(rows)` so the template knows
whether to render the override sub-form. Only `conflict`-signal clusters are
evaluated (a reissued pair is always a `conflict`, since its MBIs differ).

## Section 2 — The card UI (`customer_duplicates.html`)

For a `conflict` cluster where `reissued_candidate` is True, replace the red
"merge blocked" message with a **"Reissued MBI? Reconcile these two records"**
panel:

- Both records listed with **DOB, MBI, address**, and each record's **active
  policy + latest effective date** (so the current MBI is visible).
- A **radio pair — "Keep this MBI as current"** — the admin picks which
  record's MBI is current. That record's id becomes the form's `keeper_id`; the
  other record is the `loser_id` and its MBI is the **stale** one to null.
  (So "keeper" = the record holding the current MBI, chosen by the radio — the
  form carries the cluster's two customer ids and which one the radio selected.)
- A **required confirm checkbox:** "I confirm this is the same person and CMS
  reissued their MBI."
- A **"Merge (reissued MBI)"** submit button. The form posts only with a radio
  chosen and the box checked (HTML `required` on both; server re-validates).

Conflict clusters that are **not** reissued candidates keep today's rendering:
disabled checkboxes, no merge button, "review manually — merge blocked".

## Section 3 — The override route (`app/customers.py`)

`POST /admin/customers/merge-reissued-mbi` → `customer_merge_reissued_mbi()`,
`@login_required @_admin_required`. Sequence (mirrors
`scripts/merge_reissued_mbi.py`):

1. Read `keeper_id` (the record whose MBI to KEEP as current) and `loser_id`
   from the form; load both agency-scoped (`first_or_404`).
2. **Re-validate the gate server-side** via `is_reissued_mbi_candidate([keeper,
   loser])` — never trust the form. On failure → flash error, redirect, no
   changes.
3. Capture `stale_mbi = loser.mbi`. **Null it on the loser + `db.session.flush()`**
   (releases the `ix_customers_mbi` partial unique index so the merge guard
   passes).
4. Call `merge_customers(keeper.id, [loser.id], agency_id, current_user)`. The
   engine now sees a single non-null MBI → its guard passes; it moves the
   loser's policies/payments/notes/AOR onto the keeper (fill-blanks, audited,
   `no_autoflush`-safe — unchanged). If it returns `ok=False` → rollback, flash
   `res["error"]`, no changes.
5. **Term the stale policy:** on the keeper, find the moved policy whose
   `member_id == stale_mbi`; if found and `status != 'termed'`, set
   `status='termed'` (idempotent — skip if already termed; no-op if not found).
6. `db.session.commit()`. Write an `AuditLog` / `log_event` row: reissued-MBI
   merge, keeper id, loser id, stale MBI, terminated policy id (if any).
7. Flash success, redirect to the keeper's profile.

Any exception around the commit → rollback + flash "no changes made"
(mirrors the existing `customer_merge` handler).

## Section 4 — Testing & safety

Unit (`app/dedup.py` gate helper):
- reissued shape (2 rows, same DOB, different MBI) → True;
- different DOB → False; any null DOB → False; any null MBI → False;
- 3 rows → False; same MBI → False.

Route (against a same-DOB / different-MBI pair, each with a policy keyed to its
own MBI):
- merge succeeds → **one** customer remains, current MBI kept, stale MBI gone,
  the stale-keyed policy is `termed`, the keeper's other policies untouched,
  total money (`CommissionLineItem` / `PolicyPayment` sums) unchanged.
- tampered form (posts a different-DOB pair, or a non-candidate cluster) →
  refused server-side, no changes, even if the button were forced.
- idempotency: stale policy already `termed` → route still succeeds, no error.

Regression:
- the existing `merge_customers` contradiction-guard test stays green (engine
  unchanged);
- a non-reissued `conflict` cluster still renders blocked (no override form).

Process (per CLAUDE.md protocol, money/identity path):
- opus whole-branch review before merge;
- real-Postgres `--apply`-equivalent verify (the merge engine's two prior
  Postgres-only bugs — MBI-donation autoflush + AOR-chapter collision — are
  already fixed and covered; this route exercises the same engine);
- DB backup before any live use; confirm restart cycled after deploy.

## Out of scope / follow-ups

- The older `/customers/merge/<a>/<b>` path (never sees this case).
- 3-way reissued clusters (stay manual / scripted).
- The cross-carrier switcher pass (Overcash et al.) — separate work, still
  blocked on AJ's remaining full BOBs.
- Auto-detecting the current MBI from the active BOB — deliberately NOT built;
  the admin picks it in the UI (the human judgment the script made offline).
