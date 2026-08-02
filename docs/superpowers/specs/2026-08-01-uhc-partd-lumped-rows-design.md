# UHC PARTD Lumped Rows — Decomposition & Fail-Loud Guard

**Status:** spec, awaiting review
**Date:** 2026-08-01
**Author:** Tim + Claude
**Migration:** none (parser + backfill only)

---

## 1. The problem

UHC emits a Part D renewal either as **two rows** (agent commission + a separate
$0.26 Founders override) or as **one lumped row** containing both. The ledger
extractor decomposes lumped rows for the MA families but **not for Part D**, so
a lumped PARTD row is written as a single `agent_commission` at the agent's
split rate. Founders' $0.26 stays inside the agent's splittable base instead of
being carved out.

Nothing flags it: the row has the right agent, the right rate and the right
total, so `Σ raw = Σ payout + keep` still holds and the statement balances to
the penny. **Only the grain is wrong.** It has been mis-grained since May 2026
and surfaced only because Tim noticed Mike Lauzurique's numbers on 2026-08-01.

### 1.1 UHC pays two different Part D commission rates

Verified across all three raw UHC files (May + July 2026):

| Base commission | Lumped form | Rows |
|---:|---:|---:|
| $4.59 | **$4.85** (= 4.59 + 0.26) | 60 |
| $4.17 | **$4.43** (= 4.17 + 0.26) | 15 |

### 1.2 The evidence: pair-presence, not arithmetic

Any two numbers can be made to add up. The decisive test is whether a member
has a *separate* $0.26 row. Counted per member across the raw files:

| Amount | Members | Have a paired $0.26 | Reading |
|---:|---:|---:|---|
| $4.17 | 4 | 4 — **100%** | bare commission; override is its own row |
| $4.59 | 37 | 37 — **100%** | bare commission; override is its own row |
| $4.43 | 1 | 0 — **0%** | **lumped** |
| $4.85 | 4 | 0 — **0%** | **lumped** |

The split is absolute — 100% vs 0%, across 41 vs 5 members. Bare amounts always
have a matching override row; lumped amounts never do. Row-level confirmation
(Tim's examples): NESTVED, JOANNE M. and KINCAID, SYLVIA W. each show `4.17`
**and** `0.26` as separate rows, with matching `-4.17` / `-0.26` chargeback
pairs.

⚠ **$4.43 is 15 rows / 1 member and has NOT been confirmed with AJ.** The
pairing evidence is strong but thin at one member. See §6.

### 1.3 Who is affected

Only agents whose Part D book contains lumped rows: **Mike Lauzurique** and
**Rebekah Long** (the latter writing as `FOUNDERS INSURANCE AGENCY, LLC`).
19 lumped rows remain in the DB:

| Period | Agent | Rows |
|---|---|---:|
| July 2026 | Rebekah Long | 13 |
| June 2026 | Mike Lauzurique | 3 |
| May 2026 | Mike Lauzurique | 3 |

Mike's July rows were split manually on 2026-08-01
(`scripts/split_uhc_lumped_485.py`) and are already correct.

---

## 2. Root cause

`app/commission/ledger.py`:

```python
_UHC_COMBINED_PAIRS = [(_UHC_RENEWAL_HMO, _UHC_COMBINED_HMO),   # 33.51 = 28.92+4.59
                       (_UHC_RENEWAL_PPO, _UHC_COMBINED_PPO)]   # 30.68 = 26.09+4.59
```

Both known lump shapes are *MA renewal + $4.59*. There is no Part D pair. A
`$4.85` row therefore reaches the PARTD branches and misses every one:

| Branch (line) | Test | $4.85 |
|---|---|---|
| partd override (853) | `≈ 0.26` | no |
| partd dust (860) | `abs < 1.00` | no |
| partd $4.59 split (869) | `≈ 4.59` | no |
| combined decomposition (883) | `≈ 33.51 / 30.68` | no |
| **fallback (896)** | *"any other amount = a plain renewal"* | **yes** |

The fallback is the bug. It is a silent catch-all on a money path.

`$4.17` also reaches the fallback. It happens to produce the correct result
(a bare commission splitting at the agent's rate) — but by accident, not by
rule, and it is therefore untested and unprotected.

---

## 3. Goals / non-goals

**Goals**

1. Decompose both Part D lump shapes into their two real components.
2. Recognise `$4.17` explicitly as a bare Part D commission.
3. **Quarantine any unrecognised PARTD renewal amount** instead of silently
   passing it through — so the next unknown shape announces itself.
4. Backfill the 19 lumped rows already in the DB.

**Non-goals**

- No migration; no schema change.
- No change to MA-family handling (`33.51` / `30.68` decomposition is correct).
- No change to `$0.26` handling (already correct).
- Not re-importing any statement — see §5.2.

---

## 4. Design

### 4.1 Part D lump table

Replace the implicit knowledge with an explicit, extensible table:

```python
# Part D pays two different base commissions, each of which may arrive bare
# (with the $0.26 Founders override as its own row) or LUMPED with it.
# Pair-presence is the discriminator: a bare amount always has a separate
# $0.26 row for that member; a lumped amount never does.
_UHC_PARTD_COMMISSIONS = (4.59, 4.17)
_UHC_PARTD_LUMPS = tuple(
    (c, round(c + _UHC_PARTD_OVERRIDE, 2)) for c in _UHC_PARTD_COMMISSIONS
)   # ((4.59, 4.85), (4.17, 4.43))
```

Deriving the lump from the base keeps the two in sync — adding a future rate is
one entry, not two.

### 4.2 PARTD branch order

Ordered most-specific first, with an explicit terminal:

1. `≈ 0.26` → `founders_override`, 100% Founders *(unchanged)*
2. `≈ any lump` → **two drafts**: commission at the agent's rate (`::r`) +
   `$0.26` override (`::o`). Sign-preserving, so a `-4.85` yields `-4.59` +
   `-0.26` and classifies as `chargeback`.
3. `≈ any bare commission` → single draft at the agent's rate
   (covers `4.59` today, `4.17` newly explicit)
4. **anything else → `NEEDS_MANUAL_REVIEW`** (`ptype="partd unrecognized"`)

Step 4 replaces both the `abs < 1.00` "partd dust" rule and the silent fallback.
Dust is subsumed: a sub-$1 PARTD amount that is not `$0.26` is simply
unrecognised.

### 4.3 Why quarantine rather than pass through

This is the durable fix. A quarantined row is **visible** (`/admin/commissions/
<id>/quarantine`, the `⚠ N review` badge, the period-level review queue) and
**resolvable** by AJ through the existing UI, and it still balances because
quarantine preserves `raw_amount`. A silently-passed row is invisible by
construction. The whole reason `$4.85` survived three statements is that the
fallback produced a plausible row.

Expected effect on the July file: `4.85`/`4.43` decompose (no longer
quarantined), and any genuinely new amount appears in AJ's queue.

### 4.4 Backfill

Generalise `scripts/split_uhc_lumped_485.py` into
`scripts/split_uhc_partd_lumps.py`:

- finds rows whose `abs(raw_amount)` matches any known lump, across **all** UHC
  statements and agents (not just Mike/July)
- splits via the existing `resolve_quarantine_line()` primitive so the `::ovr`
  sibling, the revision/undo trail and the `Σ raw` invariant all come from the
  same code path the UI uses
- override carries the **row's sign** (chargebacks mirror — Tim's call)
- dry-run by default; **aborts if `Σ raw` would change**
- idempotent: rows already at a bare amount are skipped

It never deletes and never re-parses money.

---

## 5. Constraints

### 5.1 Rate comes from the agent's contract

The commission part splits at the agent's `AgentCarrierContract.split_rate`
(Mike 0.525, Tim/Rebekah 0.55, …), never a hardcoded value. The 2026-08-01
incident was caused by a hand-edit that set `split_rate=1.0`; the script must
refuse to run for an agent with no active UHC contract rather than guess.

### 5.2 No re-import

`_ingest_normalized_upload` deletes a statement's ledger rows with **no
`manually_adjusted` exclusion** (routes.py:1006-1013), which would destroy AJ's
manual work (currently 24 `manually_adjusted` rows + 228 resolved-quarantine
rows). The parser fix applies to **future** uploads; existing rows are corrected
by the backfill script only.

---

## 6. Open question for AJ

**`$4.43` = `$4.17` + `$0.26`?** The pairing evidence says yes (0 of 1 members
has a separate $0.26, versus 4 of 4 for bare `$4.17`), but it rests on a single
member and 15 rows. Confirm before applying the backfill to `4.43`.

If AJ cannot confirm, ship the `(4.59, 4.85)` pair plus the quarantine guard;
`$4.43` then lands in AJ's review queue rather than being silently mis-grained —
which is strictly better than today either way.

Precise question: *"UHC Part D renewals come in at $4.59, $4.85, $4.17 and
$4.43. $4.85 = $4.59 + $0.26 override. Is $4.43 likewise $4.17 + $0.26, and
which plans pay the $4.17 base?"*

---

## 7. Testing

Part D currently has almost no ledger coverage — one draft fixture in
`tests/test_commission_ledger.py:268`. That gap is why this survived. Add:

1. Each lump (`4.85`, `4.43`) decomposes into commission + `$0.26`, at the
   agent's contract rate, positive and negative.
2. Each bare amount (`4.59`, `4.17`) yields ONE row at the agent's rate and no
   override sibling.
3. `$0.26` alone stays a 100% Founders override.
4. An unrecognised PARTD amount (e.g. `$3.11`) → `NEEDS_MANUAL_REVIEW`, **not**
   a plain renewal. This is the regression test for the class of bug.
5. MA-family amounts (`33.51`, `30.68`, `28.92`, `4.59` on MAPD/DSNP/CSNP/MA)
   are unchanged — guards against the PARTD branch capturing MA rows.
6. Balance: `Σ raw = Σ payout + keep` for every carrier
   (existing `test_commission_ledger.py` suite).
7. Backfill: splits only known lumps; preserves `Σ raw`; idempotent; refuses an
   agent with no active UHC contract.

---

## 8. Rollout

1. Merge → deploy (no migration).
2. Back up the DB (`/root/founders_pre_partd_lumps_<ts>.sql`).
3. Dry-run the backfill across all UHC statements; review the row list.
4. `--apply`; verify `Σ raw` unchanged per statement and that the 24
   `manually_adjusted` + 228 resolved rows are untouched.
5. Confirm the next UHC upload produces no `partd unrecognized` quarantine rows
   (or that any it produces are genuinely new shapes).

---

## 9. Follow-ups (not in scope)

- **Edit-form bug #3** (`docs/superpowers/specs/2026-06-26-uhc-hra-attribution-and-edit-fixes.md`):
  the inline edit form pre-fills the OLD agent's split, which is the likely
  reason the 2026-08-01 hand-edits came out at `split_rate=1.0`. Fixing the
  parser removes the need for those edits, but the form should still re-suggest
  the agent's contracted rate and warn on a `1.0` save for a non-1.0 contract.
- **`split_rate=1.0` is overloaded** — it means Anjana's legitimate non-Cannon
  100%, AJ's "exact dollars" edit convention, and genuine errors, all
  indistinguishable. Any off-contract audit needs these modelled apart.
- **Same fail-loud audit for other carriers.** The silent catch-all pattern
  ("any other amount = a plain renewal") may exist elsewhere; PARTD is simply
  where it was caught.
