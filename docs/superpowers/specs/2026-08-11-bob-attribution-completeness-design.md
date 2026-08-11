# BOB Attribution Completeness — design

**Status:** approved, not yet built
**Date:** 2026-08-11
**Author:** brainstormed with Tim
**Related:** `2026-08-06-ledger-customer-backlink-repair-design.md` (the commission-side
equivalent), `2026-06-25-data-integrity-remediation-roadmap.md` (item 3, plan_id linkage)

## The goal, in Tim's words

> "All BOB entries link to an existing customer with a plan or get quarantined to
> resolve by either adding a customer or a plan or whatever else. Use the same bucket
> analogy with the BOB customers and plans as we do with the commissions. Nothing lost,
> nothing ignored, 100% of entries attributed correctly with 100% confidence."

## Why this is needed

Plan linkage has only ever come from the BOB path — commission import never writes
`plan_id` at all. Three backfills on 2026-08-11 cleared 40 UHC + 12 Devoted + 1 Aetna
+ 3 Humana unlinked policies from raw commission files and BOBs. **Every one of those
was a backfill.** The ingest seam that produced them is unchanged, so the gap
regenerates every month.

The specific defect is that a plan-bucket miss is a **second-class citizen**.
`_import_bob_row` already sorts each row into a bucket via `find_plan_bucket`, but on a
miss it appends to a local `plan_review` list and emits a log summary. The comment at
`app/upload.py:1081-1084` states the intent outright:

> "Plan-bucket misses are a DIFFERENT category from unresolvable rows: the policy WAS
> created/updated, only plan_id is left NULL for later mapping (via the repair script /
> plan_id_orphans invariant) — do not pollute the quarantine modal, just log a summary
> for visibility."

A log line no one reads is how 4,656 orphans accumulated before anyone noticed. The
row imports "successfully" and the miss is invisible by design. That is the
"nothing ignored" violation.

## The asymmetry that shapes the design

Customers and plans are **deliberately not symmetric**, and the design must preserve
that rather than unify it:

- **Customers — BOB is the identity-creating door.** `_upsert_customer_from_policy`
  delegates to `resolve_customer()` (crosswalk → MBI → name+DOB → create). A brand-new
  member on a BOB row is a *solved problem*: they get created, correctly, by design.
  (Commission import was deliberately stripped of this power — remediation item 1 —
  so BOB is the only door.) The only leak is `result.customer is None` →
  silent `return` (`app/upload.py:361-362`), which leaves the policy with
  `customer_id` NULL and no record anywhere.
- **Plans — buckets are NEVER auto-created.** The jelly-bean rule: the parser sorts a
  bean into an existing bucket and a miss leaves `plan_id` NULL for human review.
  Inventing a bucket permanently mis-files members, and this repo has the bug class on
  record (the underscore-vs-dash seed silently orphaned all 130 buckets from the sorter).

So a new customer is safe to create automatically because identity is verifiable from
the row itself. A new plan is not.

### The rule

> **A BOB row always creates or matches its customer. It never creates its plan.
> Whatever it cannot resolve — customer or plan — is parked in a queue rather than
> logged and forgotten.**

Tim's combined case (new customer on a new plan) resolves as: customer created ✅,
policy created ✅, plan link parked → queue → a human maps it to an existing bucket or
creates one from CMS. The member is visible to their agent immediately; only the plan
link waits.

This matches the commission side's park-don't-drop shape (park the payment, keep the
money correct) — Tim: "match the commission side of it."

## Current debt (measured live, 2026-08-11, post-backfill)

| | count |
|---|---|
| Unlinked policies, all statuses | **49** (19 active + 30 termed) |
| — with a `plan_name` (type A, mappable) | 7 |
| — with no `plan_name` at all (type B) | 42 |
| Customers with no policy | 2 |

The 7 named ones are all type A — `UHC Dual Complete NC-S3`, `H5521-081` and similar
are buckets that **already exist under a different name**, so `find_plan_bucket` is
missing on aliases it could learn. This is small enough to drive to zero now.

## Design

### 1. Enforcement seam

One seam, in `_import_bob_row` / `_upsert_customer_from_policy`. Two existing branches
that currently drop information start parking it instead. **No new import path, no
parser changes, no change to how rows are read.**

| Miss | Today | After |
|---|---|---|
| Plan bucket | append to local `plan_review`, log a summary | park a `needs_plan` queue entry |
| Customer | silent `return` on `result.customer is None` | park a `needs_customer` queue entry |

### 2. Storage — one table, two kinds

New `AttributionQueue`:

- `kind` ∈ `needs_customer` | `needs_plan`
- `policy_id`, `agency_id`
- the raw values that failed: `carrier`, `plan_name`, `plan_type`, `member_id`, `full_name`
- `status` ∈ `open` | `resolved` | `dismissed`, plus `resolved_by_id`, `resolved_at`, `resolution_note`
- **unique on `(agency_id, kind, policy_id)`** so re-uploading the same BOB is idempotent
  and does not pile up duplicates (same property the commission ledger relies on)

**Why a table, not an extension of `unresolvable_json`:** that JSON is *per-batch*, so an
unresolved row is only findable by remembering which upload produced it. The goal is a
standing "is anything unattributed?" answer, which needs a queue that outlives the
batch. A table also lets the UI dedupe: `UHC Dual Complete NC-S3` on 40 rows is **one**
plan-name to resolve, not 40 (resolve once → all 40 link).

### 3. Resolution — two queues, reusing existing modules

Tim: "definitely need to reuse modules already built since we still need to organize and
simplify the modules later, don't want to add to the complexity."

**Customer misses → the EXISTING hub.** `/customers/unassigned` already has 4 categories
(`agent` / `match` / `name` / `interval`), an agents dropdown and set-agent actions. Add
a **5th category** `cat=unlinked`. No new page, no new template.

**Plan misses → a new queue, modeled on the EXISTING quarantine workbench** (same
table-with-inline-actions shape as `/admin/commissions/quarantine`). Two actions:

1. **Map to existing bucket** — pick from that carrier's buckets. On save, append the
   failed string to `Plan.plan_name_aliases`, so the same string **self-heals
   permanently** and never re-queues. This is what makes the queue converge instead of
   regenerate.
2. **Create from CMS** — search the CY2026 Landscape CSV (already on the VPS at
   `docs/Medicare Landscape Files/CY2026_Landscape_202603/`, 79MB) by contract-PBP or
   name, display what CMS says, confirm → seed the bucket, then link.
   **Never free-text.** The `plan_type` comes from **CMS, not from `Policy.plan_type`** —
   that field is the documented data trap (it holds carrier vocabulary; Humana is 81.5%
   "MA"-typed because the parser copies the carrier's product code). Seeding from the
   policy would bake the parser bug into a brand-new authoritative-looking bucket.

Seed **only the plan being resolved**, never a whole state — `seed_plan_buckets.py
--states SC` would create 21 SC Humana buckets for plans nobody holds.

### 4. One shared count

Tim: "two queues with one shared count."

Add `attribution_queue_count` to the existing `inject_counts` context processor in
`app/__init__.py`, following the same defensive `try/except → 0` pattern as the three
badges already there (`unassigned_customer_count`, `quarantine_count`,
`merge_cluster_count`). One number answers "is anything unattributed?"; clicking through
goes to whichever queue is non-empty.

Plus a new **integrity invariant** `unattributed_bob_rows` in `app/integrity.py`, so the
CI baseline-ratchet holds the line at 0 once cleared. That mechanism is already built and
is what stops this regressing a third time.

### 5. Backfill

One-time, dry-run-first script to enqueue today's 49 unlinked policies + 2 policy-less
customers, so the queue starts populated with real work rather than only catching future
rows.

## Testing

- **Unit:** a plan miss enqueues exactly one `needs_plan` row; a customer miss enqueues
  `needs_customer`; re-running the same import enqueues **zero** additional rows
  (idempotency via the unique constraint).
- **Alias self-heal:** map a failed name to a bucket → re-import the same BOB → the row
  links with **no** new queue entry. This is the convergence property; if it fails the
  whole design regenerates its own backlog.
- **CMS create:** seeds with the **CMS** plan type, not the policy's — assert explicitly
  that an `MA`-typed policy on an `MA-PD` CMS plan produces a `mapd` bucket.
- **Real-Postgres apply** for the backfill. Per CLAUDE.md this is part of the test, not
  an afterthought: SQLite has hidden Postgres-only failures here repeatedly
  (partial unique indexes, autoflush, column widths, `SERIAL` defaults).
- **Money invariant:** this touches `plan_id` / `customer_id` only. Assert ledger and
  payment totals are **identical to the penny** before and after any backfill, as all
  three 2026-08-11 backfills did.

## Scope

**In:** the two parked branches; `AttributionQueue`; the 5th hub category; the plan queue
with map + CMS-create; the shared badge; the integrity invariant; the backfill.

**Out:**
- Commission-side ingest — separate path, already parks correctly.
- `Policy.plan_type` normalization — documented trap, deliberately left (the UI already
  derives type from the linked bucket).
- Module reorganization — Tim's stated later goal. This design adds **one table and one
  route** and reuses three existing surfaces (the hub, the workbench shape, the badge
  plumbing), so it should not worsen that consolidation.

## Risks

- **The CMS-create path is where a careless click permanently mis-files members.**
  Mitigations: confirm-from-CMS rather than type-a-name; CMS-sourced plan type; an audit
  row on every create; seed one plan at a time.
- **Queue fatigue during AEP.** A large October upload could enqueue many distinct new
  plans at once. The dedupe-by-plan-name property is what keeps this tractable — 500 rows
  on 6 new plans is 6 decisions, not 500.
- **A row could be parked for both kinds at once** (no customer *and* no plan). The
  `(agency_id, kind, policy_id)` key permits exactly that — two entries, resolved
  independently — which is correct and must not be collapsed.
