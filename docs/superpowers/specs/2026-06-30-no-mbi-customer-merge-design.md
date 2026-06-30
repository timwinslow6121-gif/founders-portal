# Item 2 — No-MBI Customer Merge (data-integrity remediation)

**Status:** Brainstormed + approved 2026-06-30. Ready for writing-plans.
**Roadmap:** `docs/superpowers/specs/2026-06-25-data-integrity-remediation-roadmap.md` §2.
**Handoff (read first):** `memory/session-handoff-2026-06-30-item2-no-mbi-merge.md`.

## Problem

The portal can only merge duplicate customers that share an **MBI**
(`customer_merge` in `app/customers.py:776`, `customer_duplicates` view at `:720`).
The no-MBI duplicate clusters — commission-import stubs, Humana-only records, and
the entire non-Medicare product world (hospital indemnity, DVH, eventually life) —
are invisible to it. They never collapse.

**Grounding case — John Connelly ×5 (live on prod 2026-06-30):**

```
id    first_name  last_name      full_name        mbi          dob         stub  source
1367  John        Connelly       John Connelly    4RH5X85DC65  1953-04-07  f     (keeper)
1419  John        Connelly Iii   John Connelly..  (none)       1953-04-07  f     same person
4239  (blank "")  (blank "")     CONNELLY, JOHN   (none)       (none)      t     commission_import
4243  (blank "")  (blank "")     CONNELLY, JOHN   (none)       1953-04-07  t     commission_import
5960  (blank "")  (blank "")     CONNELLY, JOHN   (none)       (none)      t     commission_import
```

All five are ONE person. Note:
- `first_name`/`last_name` are `nullable=False` → the stubs store **empty strings**,
  not NULL. The name lives only in `full_name` ("CONNELLY, JOHN"). A `last_name='connelly'`
  query misses them. **Detection MUST normalize `full_name`, not just first/last.**
- The radar's `duplicate_customers` invariant (=18, baseline) catches **none** of the
  five: it filters `stub.is_(False)` and `dob is None`, and `_norm_name` preserves token
  order. The 18 is a genuinely conservative *floor*, **not** the work list. Item 2 needs
  its own broader detector.

Live numbers (2026-06-30): `duplicate_customers`=18, loose name-only=277 clusters /
288 excess rows, `orphan_stub_customers`/`commission_import_stubs`=571.

## Goal

Collapse a no-MBI duplicate cluster into ONE profile: reconcile fields, reattach
**all** child records (Policies, PolicyPayments, AOR intervals, notes, contacts) to a
keeper, delete the emptied losers in one transaction. Plus remediation #4
(edit-an-already-used-MBI → offer merge). Drive `duplicate_customers` and
`orphan_stub_customers` down and ratchet their baselines.

## Decided behavior (Tim, 2026-06-30)

- **Suggest-only.** Nothing merges without a human reviewing the cluster and clicking.
  No auto-merge script that collapses without review.
- **Merge offered when:** normalized name matches **AND** (a shared non-null DOB **OR**
  a shared MBI / `carrier_member_id` somewhere in the cluster). Bare-name-only clusters
  are **shown** but the merge button is gated behind an explicit "I confirm same person"
  checkbox.
- **Fill-blanks-only reconcile.** The merge fills only fields the keeper is *missing*,
  pulling from losers by precedence **manual > real > stub**. It **never** overwrites an
  existing keeper value. A real-vs-real conflict (two non-null differing values) is left
  for a human to edit on the profile afterward.
- **Refuse contradictory merges.** If a cluster contains two **different non-null DOBs**
  or two **different non-null MBIs**, the merge is **blocked** (hard warning, no button) —
  different MBIs are definitionally different beneficiaries.
- **One place for dedup:** extend `/admin/customers/duplicates` to show MBI clusters AND
  no-MBI name clusters, each tagged with its signal.
- **Audit, not undo.** Each merge writes an `AuditLog` row via `log_event()` recording
  keeper, losers, fields filled, and child-record counts moved. Full reversal/undo is
  out of scope this round.

## Product-line robustness (this is not only Medicare)

The book covers Medicare Advantage/PDP today and hospital indemnity, dental-vision-hearing,
and eventually life — **none of which have an MBI**. Two consequences the design must
handle so a future life-insurance import is not read as mass duplication:

- **Multi-product-line is the new multi-AOR.** One person legitimately holds a MAPD + a
  dental + a hospital-indemnity policy = ONE customer with THREE policies across product
  lines, each on its own carrier, most with no MBI. The detector must treat "this customer
  has policies spanning product lines" as **normal**, never as a duplication signal, and a
  merge must cleanly **union** all product-line policies onto the keeper. (Mirrors the
  existing "a person with 2 concurrent AORs is ONE customer" rule.)
- **Carrier + policy-number is the durable per-product corroborator** where MBI doesn't
  exist. The detector treats a shared `carrier_member_id` (from the cluster's
  `CommissionLineItem`s) — and a shared `(carrier, Policy.member_id)` — as a real merge
  signal, not bare-name. This is how Connelly's no-DOB stubs corroborate.

## Architecture — four units + one script

### 1. Detection — `find_no_mbi_clusters(agency_id)` (new, `app/dedup.py`)

- Cluster customers by a **token-sorted, suffix-stripped normalized name** computed from
  `full_name` (falling back to `first_name`/`last_name` when `full_name` is blank).
  Reuse `integrity._norm_name` (already sorts tokens + strips iii/ii/iv/jr/sr). Handles the
  `""`-name + populated-`full_name` stub shape and the "LAST, FIRST" comma format.
- Include stubs and NULL-dob rows (unlike the radar invariant). For each name-cluster,
  gather corroboration signals across the rows:
  - shared non-null **DOB**, shared **MBI**, shared **humana_id**,
  - shared **`carrier_member_id`** (joined from the rows' `CommissionLineItem`s),
  - shared **`(carrier, member_id)`** policy.
- Emit a **signal tag** per cluster:
  - `dob_match` / `shared_id` → merge offered.
  - `name_only` (no DOB, no shared id) → shown, merge gated behind explicit confirm.
  - `conflict` (two different non-null DOBs OR two different non-null MBIs) → merge blocked.
- Returns clusters with their rows + signal + a suggested keeper (most-complete real row:
  non-stub, has MBI, has DOB — Connelly 1367). Coincidental same-name different-people
  (the 3 other Connellys) appear as separate clusters / are visible for human rejection.
- Product-line note: clusters are formed by identity (name + corroborator) only — never by
  carrier/product — so a person's multi-product policies never split them into fake dups.

### 2. Reconcile + merge engine — `merge_customers(keeper_id, loser_ids, agency_id, actor)` (rewrite of `customer_merge`)

Single transaction; re-fetch keeper + losers inside it (idempotent / concurrency-safe —
no-op a loser that's already gone). Steps:
1. **Refuse** if the resulting set has two different non-null DOBs or MBIs (defense in
   depth — the UI already gates, but the engine enforces).
2. **Reattach child records** to keeper: `Policy`, `PolicyPayment`, `CustomerAorHistory`,
   `CustomerNote`, `CustomerContact`. *(The current `customer_merge` moves only
   notes/contacts/AOR and misses Policy + PolicyPayment — that is a bug we fix here.)*
3. **Fill-blanks-only reconcile** for keeper-missing fields (mbi, humana_id, dob, phone,
   address, etc.) pulling from losers ordered by precedence **manual > real > stub**
   (`manually_edited` first, then non-stub, then stub). Never overwrite a keeper value.
4. **Delete** emptied losers.
5. **Audit:** one `log_event(action="customer_merge", category="admin", record_count=…)`
   with detail = {keeper_id, loser_ids, fields_filled, counts of each child type moved}.

### 3. UI — extend `/admin/customers/duplicates`

- One page renders MBI clusters (existing) + no-MBI clusters (new), each tagged with its
  signal badge (`dob_match` / `shared_id` / `name_only` / `conflict`).
- Keeper pre-selected to the suggested most-complete row; reviewer can change it.
- Merge button present for `dob_match`/`shared_id`; gated behind an "I confirm same person"
  checkbox for `name_only`; absent (replaced by a warning) for `conflict`.
- Reuses `customer_duplicates.html` + the existing nav badge. POST → `merge_customers`.

### 4. Remediation #4 — edit-an-already-used-MBI

In the customer-edit MBI path: when the entered MBI already belongs to another customer,
**do not save**; show a soft warning "That MBI belongs to *<other customer>* — same
person? [Review merge]" linking to the duplicates view scoped to those two. Keeps merge a
deliberate reviewed action (consistent with suggest-only). Replaces today's hard error.

### 5. Cleanup — `scripts/merge_no_mbi_clusters.py`

Dry-run by default, `--apply` to write. DB backed up first. Only collapses clusters whose
signal qualifies for an *unattended* merge — i.e. **`dob_match` or `shared_id`** (never
`name_only`, never `conflict`). Calls the same `merge_customers` engine so behavior is
identical to the UI. Reports counts. After apply: `duplicate_customers` and
`orphan_stub_customers` drop; ratchet `integrity_baseline.json` down.

## Testing

- Detector: Connelly fixture (5 rows incl. blank-name stubs) clusters to ONE; the 3
  coincidental Connellys stay separate; signal tags correct per row mix.
- Multi-product-line: one person with MAPD + dental + hospital-indemnity policies (no MBI
  on the latter two) is NOT flagged as a duplicate; merging two such records unions all
  policies onto the keeper.
- Merge engine: Policies + PolicyPayments + AOR + notes + contacts all reattach;
  fill-blanks-only never overwrites a keeper value; precedence manual>real>stub picks the
  right filler; contradictory-DOB / contradictory-MBI cluster is refused; idempotent
  (running twice is a no-op); AuditLog row written.
- Remediation #4: editing to a used MBI does not save + surfaces the merge link.
- Real-Postgres verify (partial-unique-index / autoflush / concurrency are invisible to
  SQLite — see item-1 hotfix history).

## Definition of done

- `/admin/customers/duplicates` surfaces no-MBI clusters with signal tags; merge gated per
  the rules above.
- `merge_customers` reattaches all five child types, fill-blanks-only, refuses
  contradictions, idempotent, audited.
- Remediation #4 soft-warn + merge link live.
- `scripts/merge_no_mbi_clusters.py` (dry-run→apply) collapses qualifying clusters.
- `duplicate_customers` + `orphan_stub_customers` drop; baselines ratcheted down.
- Opus whole-branch review (data path) + real-Postgres verify + restart cycled.

## Explicitly out of scope (deferred, noted so they're not lost)

- Merge **undo/reversal** (chose plain suggest-only + audit, not full undo).
- **Link-don't-merge** for related-but-distinct people (e.g. a spouse on a family dental
  plan) — the model shouldn't preclude it later, but no household/dependents modeling now.
- Auto-merging `name_only` clusters.
- Address/phone as *primary* corroboration (used only as soft display context this round).

## Reuse (don't rebuild)

- `app/customers.py:776` `customer_merge` (generalize), `:720` `customer_duplicates`
  (extend), `:836` `duplicates_list` + `get_duplicate_mbi_count`.
- `app/integrity.py` `_norm_name` (the normalizer), `_duplicate_customers` (the invariant
  item 2 drives down).
- `app/identity.py` + `app.commission.resolver` `_composite_match` / `_find_name_dob_match`
  (the corroborated same-person matcher).
- `app/audit.py` `log_event` (the audit seam, from S2).
