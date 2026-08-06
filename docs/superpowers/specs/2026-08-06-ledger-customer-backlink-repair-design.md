# Ledger Customer Back-Link Repair — Design

**Status:** spec, awaiting review
**Date:** 2026-08-06
**Migration:** none (no schema change)
**Grounding case:** BCBS linked 213/213 (May) → 199/216 (June) → **0/218 (July)**

---

## 1. Problem

`/customers/unassigned?cat=match` shows **641 commission line items with no `customer_id`** (~$16.6k of
`agent_commission` + `chargeback`). Tim asked whether the parsers are silently failing.

**They are not.** This is a linkage bug in one line, not an extraction bug, and it is NOT the
known "carriers share no ID" structural gap.

### Evidence it is a regression, not missing data

| Carrier | May | June | July |
|---|---|---|---|
| BCBS   | 0/213 unlinked (100% linked) | 17/216 | **218/218 (0% linked)** |
| Humana | 4/229 | 47/235 | **212/212 (0% linked)** |
| UHC    | 27 | 45 | 36 |
| Devoted| 10 | 20 | 4 |

- A structural "no shared ID" gap would fail in May too. BCBS linked **100%** in May.
- Row volume is flat (~213–235/month), so the files did not change shape.
- Identifiers are **present and unchanged**: BCBS carries `carrier_member_id` on all 218 July rows,
  same as the 213 in May.
- **The same July rows linked fine in the other pipeline**: 161 Humana + 207 BCBS `policy_payments`
  resolved to a customer.

### Root cause — `app/commission/ledger.py:1338`, in `persist_line_items`

```python
existing.customer_id = cust_by_mbi.get((d.mbi or "").strip())
```

Two defects in one line:

1. **Single-tier lookup.** It matches only on MBI (`humana_id` for Humana). It never tries
   `carrier_member_id` — the *only* identifier BCBS has, so BCBS can never link through this path.
   For Humana July, 41 rows carry an MBI and **0** match any `customers.humana_id` (they live in
   `customers.mbi`; the two columns hold different things per the crosswalk history).
2. **Unconditional assignment.** On a miss it writes `None`, *erasing* a link the row already had.
   This is the most likely cause of BCBS 199/216 → 0/218 on re-upload.

Meanwhile `policy_payments` uses `_match_policy` (MBI → carrier_member_id → fuzzy name) plus a
crosswalk step at ingest. The ledger reimplemented matching in a strictly weaker form.

**Ordering is already correct:** `ingest_statement` (creates/matches customers + payments) is called at
`routes.py:1022-1023` *before* `persist_line_items` at `routes.py:1030-1031`, inside the same `try`.
Identity exists when the ledger writes — it is simply looked up wrong.

### Measured recovery (against the real 641)

| Method | Recovers |
|---|---|
| Tier lookups only (`_match_policy` re-run) | 490 — **0 unique** |
| Via `source_ref` → `policy_payments` | 537 — **151 unique** |
| Both agree | 386 |
| **Neither** | **104** |

The payment path is a **strict superset**. There is no row the tiers recover that the payment
join does not.

---

## 2. Approach

Replace the MBI dict in `persist_line_items` with three ordered steps:

1. **`source_ref` → `policy_payments` → `policies.customer_id`.**
   The payment sibling already resolved at ingest with the full tier stack plus crosswalk.
   Both tables are written from the same statement in the same transaction, so the ledger
   *inherits* the payment's answer and the two become structurally incapable of disagreeing —
   which is precisely the failure being fixed.
2. **Fallback: the shared `_match_policy` resolver** for any row with no payment sibling.
   Recovers 0 additional rows today; covers future rows the payment path does not produce.
3. **Miss → leave the existing `customer_id` untouched.** Never write NULL over an established link.

**Rejected:** reusing `_match_policy` alone (recovers 490 vs 537, and 0 rows uniquely).
**Rejected:** payment-join only, with no resolver fallback (no coverage for rows lacking a payment sibling).

### Decisions (Tim, 2026-08-06)

- **Never overwrite a good link with NULL.** Consistent with how this codebase treats established
  data (`manually_edited`, fill-blanks-only merges).
- **The 104 unrecoverable rows stay NULL** and remain on `/customers/unassigned?cat=match`. That page
  drops 641 → ~104 and becomes actionable rather than overwhelming.
- **Devoted HRA in-string name parsing is OUT OF SCOPE** (own follow-up — see §6).
- **`_match_policy` is NOT widened to termed policies.** It stays `status="active"` as-is.

---

## 3. What the 104 actually are

Checked, not assumed: **only 4 of 104 match a customer by name.** These people are largely not in
the book at all.

| Carrier | Rows | $ | has mbi | has cmid |
|---|---|---|---|---|
| Humana | 46 | $3,789.81 | 42 | 42 |
| UHC | 38 | $1,138.58 | 22 | 0 |
| Devoted | 15 | −$1,149.99 | 7 | 7 |
| BCBS | 4 | −$115.64 | 0 | 4 |
| Healthspring | 1 | $144.58 | 1 | 1 |

Two sub-cases:

- **~15 Devoted HRA rows** carry the member name embedded in the description
  (`"HRA for member Charles Speight DF46G5 (NC)"`) with no mbi/cmid columns — the same shape the
  UHC extractor already parses for its HA rows. Recoverable in principle → §6.
- **~89 rows** are members genuinely absent from the book (e.g. BCBS `Earnhardt,Mary J`,
  `cmid=106703512`, four −$28.91 chargebacks, no such customer). No code fixes these; they need a
  BOB or a human.

**Honest limit:** three months of data is a thin base, and July's spike was caused by the bug being
fixed here. Whether a steady residue of genuinely-unknown members persists will only be visible
after a clean month runs post-fix.

---

## 4. Scope

**In:**
- `persist_line_items` resolution order (the three steps above).
- A shared helper so ledger and payments cannot drift apart again.
- One-time idempotent backfill script for the existing 641.

**Out:**
- Any change to `_match_policy`'s own tiers or its `status="active"` index.
- Devoted HRA description parsing (§6).
- Any money field. The fix touches `customer_id` **only** — never `raw_amount`, `split_rate`,
  `classification`, or `agent_id`.
- The legacy `build_payments` path (`routes.py:1274`).

---

## 5. Testing

- Unit test per resolution step: payment-sibling hit; resolver fallback when no sibling; miss.
- **Regression test for the erasure bug:** a row with an established `customer_id` that fails to
  resolve on re-upload must KEEP its link. This is the BCBS 199→0 case.
- BCBS-shaped test: row with `carrier_member_id` and **no** MBI resolves correctly (fails today).
- Humana-shaped test: MBI present in `customers.mbi` rather than `humana_id` still resolves.
- Idempotency: running the backfill twice changes nothing the second time.
- Agency scoping asserted on every new query.
- Full suite green (baseline 776).

## 5b. Verification before production (Tim's call)

1. Build with per-task reviews → **opus whole-branch review**.
2. Backfill `--dry-run` printing a sample of proposed links for Tim to eyeball.
3. DB backup.
4. `--apply`, then verify 641 → ~104 and confirm money totals unchanged to the penny.

---

## 6. Follow-ups (not this build)

- **Devoted HRA in-string member parsing** — mirrors `_uhc_ha_member`; would take ~104 → ~89.
- **After a clean post-fix month**, re-measure the residue to learn whether unknown-member rows are
  a steady trickle or a one-off.
- The `/customers/unassigned?cat=match` page becomes genuinely workable at ~104; consider whether it
  needs a resolve action (relates to remediation roadmap item 4).
