# Writing-Agent Provenance & Retired-Agent Visibility — Design

**Status:** spec, awaiting review
**Date:** 2026-08-01
**Author:** Tim + Claude
**Migration:** 040 (head is currently 039)

---

## 1. The problem

Cyndi Mortimer and Don Long are retired agents whose Aetna/UHC business rolls up
to Brian Freeman at his 50% rate (`app/commission/rollup.py`). The money is paid
correctly. **But nobody can see it.**

`apply_rollup()` rewrites the writing-agent *name* to "Brian Freeman" before
agent-matching, so both the split rate and the attribution come out right in one
place. That rewrite is **destructive**: the original name is consumed to resolve
an `agent_id` and then discarded. `CommissionLineItem` has 18 columns and none
of them holds the writing agent.

Measured from the May 2026 UHC raw file:

| Writing agent | Rows | Raw gross | Rolls to Brian @50% |
|---|---:|---:|---:|
| MORTIMER, CYNTHIA WALKUP | 69 | $2,304.64 | $1,152.32 |
| LONG, DONALD | 52 | $868.43 | $434.21 |
| **Total rolled** | **121** | **$3,173.07** | **$1,586.54** |

That is more than Betty, Anjana and Patricia Hill combined, and it is invisible
in the portal — the numbers above had to be computed from a raw file on disk.

Tim, 2026-08-01: *"Cyndi Mortimer has some business but currently there's no way
to verify what we are doing with those payments… we need to add a way to verify
who and how much is getting paid for her business."*

### 1.1 A latent correctness bug

`_RETIRED_ROLLUPS` keys on `_normalize_name()` output and contains only
`"cynthia mortimer"`. Verified against production:

```
MORTIMER, CYNTHIA WALKUP + UHC   -> Brian Freeman   ✓
MORTIMER, CYNDI          + UHC   -> (unchanged)     ✗
```

If a carrier ever writes her short name, those rows miss the rollup and fall to
the 0.55 agency fallback — paying the wrong amount to the wrong place, silently.
This is the same failure mode that produced Don Long's original "-$18"
discrepancy (CLAUDE.md, 2026-06-11).

---

## 2. Goals / non-goals

**Goals**

1. Persist the pre-rollup writing-agent name on every ledger row, for **all**
   agents (not just retired ones).
2. Report retired-agent business: of Brian's payout, how much is Cyndi's, how
   much is Don's, how much is his own.
3. Close the `"MORTIMER, CYNDI"` matching gap.
4. Backfill history **where a raw source file exists**, without re-importing.

**Non-goals**

- **No change to money flow.** Brian is paid exactly as today; `agent_id`,
  `split_rate`, `raw_amount` and `classification` are untouched.
- Not creating a User row for Cyndi (Don has one, `id=18`; Cyndi does not).
  Attribution stays on Brian — this is a *visibility* feature.
- Not re-importing any statement (see §5.1).
- Not changing `PolicyPayment`.

---

## 3. Key constraint: re-import is destructive

`_ingest_normalized_upload` (routes.py:1006-1013) deletes a statement's ledger
rows before re-inserting:

```python
li_q = CommissionLineItem.query.filter_by(statement_id=stmt.id, agency_id=agency_id)
...
li_q.delete(synchronize_session=False)
```

There is **no `manually_adjusted` exclusion**. Production currently holds:

| Manual work | Count |
|---|---:|
| `manually_adjusted` line items | 24 |
| Resolved-quarantine rows | 150 |
| Audit revisions (97 resolve + 24 edit) | 121 |

Re-importing UHC May/June/July would destroy **174 rows of AJ's work**. This
matches the existing warning in CLAUDE.md: *"do NOT re-upload a statement after
hand-editing — manual edits aren't preserved through re-parse yet."*

**Therefore the backfill must never re-import.** It reads raw files and issues a
single-column `UPDATE` matched on `source_ref`.

---

## 4. Design

### 4.1 Schema — migration 040

One nullable column on `commission_line_items`:

```python
writing_agent_raw = db.Column(db.String(128), nullable=True, index=True)
```

Nullable because historical rows without a recoverable source file stay NULL —
an honest "unknown", not a fabricated value. Indexed because the report groups
by it.

### 4.2 Capture at write time

`persist_line_items` (ledger.py:1251-1295) **already has the value** — it uses
`d.writing_agent_raw` at line 1271-1272 to resolve `agent_id`, then drops it.
All seven carriers populate it on their drafts. The change is one line:

```python
existing.agent_id = agent_id
existing.writing_agent_raw = (d.writing_agent_raw or "").strip()[:128] or None
```

This is why covering **all** writing agents costs nothing over retired-only: the
value is in the dataclass either way. It also makes the 473
`FOUNDERS INSURANCE AGENCY, LLC` rows (Rebekah's book) visible for free.

### 4.3 Rollup name-gap fix

Add short-name variants to `_RETIRED_ROLLUPS` in `rollup.py`:

```python
_RETIRED_ROLLUPS = {
    "donald long":     "Brian Freeman",
    "don long":        "Brian Freeman",
    "cynthia mortimer":"Brian Freeman",
    "cyndi mortimer":  "Brian Freeman",
}
```

Guarded by a test asserting every variant rolls on Aetna/UHC and **does not**
roll on other carriers, and that `"rebekah long"` (an active agent) is untouched.

### 4.4 Retired-agent report

New function in `app/commission/recap.py`:

```
retired_agent_breakdown(agency_id, period_label=None)
  -> [{writing_agent, rolled_to_agent_id, carrier, n_rows,
       raw_total, agent_payout, founders_keep}]
```

Groups `CommissionLineItem` by `writing_agent_raw` where the name normalizes to
a retired agent, deriving money via the existing `split_breakdown()` — never
recomputing it. Rendered admin-only under **Agent Commissions**, answering:

> July 2026 UHC — Brian's payout $15,449.01
>   · from Cyndi's book:  65 rows, raw $X, Brian paid $Y
>   · from Don's book:    48 rows, raw $X, Brian paid $Y
>   · Brian's own:        …

Rows with `writing_agent_raw IS NULL` are shown as **"unknown (no source
file)"** with the statement named — never silently folded into "own".

### 4.5 Backfill script

`scripts/backfill_writing_agent.py` — dry-run by default, `--apply` to write.

For each (statement, raw file) pair:
1. Load via `load_sheets()` (content-routed, post-e99344a).
2. Read the writing-agent column — UHC col 5, Aetna col 16 (per
   `payments.py:128,175`).
3. Rebuild each row's `source_ref` using the **same** index scheme the
   extractor used (`uhc::0::<idx>`), and `UPDATE` only `writing_agent_raw`.
4. `::ovr` siblings inherit the parent's value (their `source_ref` is
   `<parent>::ovr` and has no raw-file row).
5. Report per statement: matched / unmatched / already-set.

**It never deletes, never touches money fields, never re-parses amounts.**

Guards:
- Refuse to run unless the file's row count and carrier match the statement.
- Idempotent — re-running is a no-op.
- Verify `Σ raw_amount` before and after are identical (must be, since no money
  column is written) and abort if not.

---

## 5. Backfill coverage

Verified 2026-08-01 against local files and the VPS. The VPS does **not** retain
uploaded files (`instance/uploads` holds 6 unrelated April BOB files; the
commission path unlinks its temp file in a `finally`).

| Statement | Raw file | Coverage |
|---|---|---|
| UHC May (62) | ✅ `statement-2813549-20260501 (4).xlsx` | 121 retired rows |
| UHC June (69) | ❌ `UHC June 2026.xlsx` — **missing** | gap |
| UHC July (80) | ✅ `statement-2813549-20260701 (1).xlsx` | 113 retired rows |
| Aetna May (52) | ✅ `Aetna Founders - May 2026.xlsx` | 3 |
| Aetna June (72) | ❌ `Aetna - June 2026.csv.xlsx` — **missing** | gap |
| Aetna July (86) | ✅ `…med_comm_202607.csv` | 3 |

Pre-May statements have zero ledger rows (the ledger shipped in R1/migration 023,
June 2026) and are out of scope.

**June is the only gap.** Both files were uploaded by AJ on 2026-07-03, five
minutes apart, under the filenames recorded above. If he supplies them, re-run
the script — it is idempotent. Until then the report shows June as
"no source file", **not** a guessed number.

Rejected alternative: a lump-sum `CommissionAdjustment` for June. It would place
an unverifiable figure alongside four months of exact ones, and row-level
provenance is re-checkable where a lump sum is not.

---

## 6. Testing

1. `persist_line_items` stores `writing_agent_raw` for every carrier; NULL/blank
   names store NULL, not `""`.
2. Rollup: all four name variants roll on Aetna/UHC; none roll on other
   carriers; `"rebekah long"` untouched.
3. `retired_agent_breakdown` sums exactly to the agent's existing payout — the
   report must not invent or lose money.
4. Backfill: matches by `source_ref`; leaves `manually_adjusted` rows' money
   fields byte-identical; `::ovr` siblings inherit the parent; idempotent on
   re-run; aborts on carrier/row-count mismatch.
5. Regression: `Σ raw_amount = Σ agent_payout + Σ founders_keep` still holds for
   every carrier (existing `test_commission_ledger.py` balance suite).

---

## 7. Rollout

1. Merge → deploy → `flask db upgrade` (039 → 040). Column is nullable, so no
   backfill is required for the app to work.
2. Back up the DB (`/root/founders_pre_writing_agent_<ts>.sql`).
3. Dry-run the backfill on the four covered statements; review the report.
4. `--apply`; verify `Σ raw_amount` unchanged and the 174 manual rows intact.
5. Going forward, every upload captures provenance automatically.

---

## 8. Follow-ups (not in scope)

- **Retain uploaded commission files.** The portal discards source bytes after
  parsing, which is the root reason this backfill depends on AJ's downloads. A
  hash-addressed copy would make future provenance questions self-serve.
- **April UHC (stmt 14)** was uploaded with filename
  `UHC - March 2026 Book of business - Tim Winslow...` — a *BOB* file, not a
  commission statement — and holds 0 ledger and 0 payment rows. Likely why
  Marlene Johnson's $301.50 New Chargeback (July) has no matching original
  payment. Separate thread; AJ is checking.
- **Cyndi as a non-login User row** (as Don Long `id=18`), if her business ever
  needs its own customer/policy attribution rather than reporting alone.
