# Chronological BOB Dedup (latest effective date wins) — Design

_Date: 2026-06-24 · Status: approved, ready for implementation plan_

## 0. Why this exists (the bug)

The 2026-06-23 Aetna CSV import created **Robbie Belk** (and 12 other current Aetna
members) as a **termed** policy with the wrong (old) plan and no agent — even though
they are currently active. Root cause: `_dedupe_bob_records` (`app/upload.py`) collapses
rows sharing `(carrier, member_id)` with **blind last-wins**. That logic was built for
UHC, which lists a member multiple times as plan *segments* of the SAME active
enrollment (all share one effective date). But the Aetna `MedicareApprovedBOBReport` CSV
lists a member's plan **history** — an old termed plan AND their current active plan,
same member_id. Last-wins picked whichever row was last in the file (the termed one for
all 13), overwriting the active enrollment.

**Live evidence:** 13 of the June CSV's 199 distinct members have BOTH an Active (`A`)
and a Termed (`T`) row; in all 13 the `T` row is last in the file, so the active
enrollment was lost. Robbie Belk: Value Plus eff 2023-01-01 → term 2025-12-31 (old) AND
Chronic Care C-SNP eff 2026-01-01 → term 3000-01-01/None (current); the stored policy
wrongly became the termed Value Plus.

## 1. The rule — dates are the source of truth, not row order or status

Among BOB rows sharing `(carrier, member_id)`, the **surviving current policy** is chosen
by **term date first, then effective date** (Tim 2026-06-24):

1. **Un-termed wins.** A row whose `term_date` is the sentinel (`3000-01-01`/`2300-01-01`,
   stripped to `None` by the parser) or blank is a LIVE policy and beats a row carrying a
   real (past) term date. (Robbie: C-SNP with no term beats Value Plus termed 2025-12-31.)
   Rationale: a term date is an *affirmative carrier action* — carriers default to a far-
   future sentinel and must explicitly apply a real term. No real term = the policy is
   current. This is the single most trustworthy signal, and it correctly handles a **rapid
   disenroll**: a newer enrollment that already termed (e.g. eff 2026-01, term 2026-02)
   must NOT win over an older still-open policy the member fell back to.
2. **Tie-break** (both un-termed, or both carrying a real term): the row with the later
   `term_date` wins (sentinel/`None` already treated as the latest in step 1); if term
   dates are equal, the row with the later `effective_date` wins.
3. **Final tie** (same term, same eff): **last-wins** (unchanged — preserves the UHC
   plan-segment outcome exactly). UHC plan-segments share one effective date AND the
   far-future sentinel term → they tie through steps 1–2 → last-wins → IDENTICAL to today.

**Row order in the file is NOT a source of truth.** The term/effective dates are; the rule
must produce the same result regardless of the order the rows appear.

**Carrier-agnostic + UHC-safe:** the rule only changes the outcome when rows differ on
term status or effective date (a genuine plan change / history — the Aetna case). UHC
segments of one enrollment share the sentinel term AND one effective date → tie →
last-wins → no change.

## 2. The earlier enrollment(s) become plan-history

The non-surviving (earlier) row(s) are NOT discarded as data — they are the member's past
chapters. They reach §4.2 plan-history (the shipped `_seed_closed_history` path) via the
existing termed-rec routing, carrying their OWN real `effective_date` → `term_date`. This
builds the chronological timeline on the profile (Aetna Value Plus 2023→2025-12-31, then
C-SNP 2026→now). The timeline chains naturally: the surviving policy's effective date
falls AFTER the prior chapter's term date.

## 3. Scope

**In scope:**
1. Replace `_dedupe_bob_records`'s last-wins collision rule with the chronological rule (§1).
2. Ensure the earlier row still flows to plan-history (§2) — confirm dedup collapses only
   the surviving *policy* and does not drop the earlier row's history contribution.
3. Re-import the Aetna June CSV to repair the 13 (§5).

**Out of scope:** any other carrier behavior (the rule is carrier-agnostic but only Aetna
exhibits the A+T pattern today); a gap/overlap audit of the timeline (the rule produces
chronologically-ordered chapters; an explicit integrity report is a future item).

**⚠ KNOWN GAP — AEP same-effective-date conflict (deferred, Tim 2026-06-24).** The §1
tie-break (equal effective_date → later/sentinel term → last-in-file) is correct for the
non-AEP world where a customer should never have two same-effective plans. **But during
AEP it's wrong:** two apps for two DIFFERENT plans can both be effective Jan 1, and CMS
honors the **LAST application submitted** (Dec 7 beats Nov 7), NOT last-in-file. The real
tie-break is the **latest Application Signed/Received Date** — which the Aetna CSV HAS
(`Application Signed Date`, `Application Received Date`) but the parser does NOT capture
today. Deferred to a future task (capture the signed date + make it the same-eff
tie-break). **Trigger: AEP ~Oct 2026, or the first real same-eff 2-plan conflict.** Logged
in `BACKLOG.md`.

## 4. Component

- `app/upload.py` `_dedupe_bob_records` — change the collision branch from
  unconditional `out[seen[key]] = rec` (last-wins) to: keep the incoming rec only if it is
  chronologically LATER than the currently-kept rec for that key, per §1's ordering. A
  small helper `_rec_is_more_current(new, kept) -> bool` encodes the precedence (latest
  effective_date; then sentinel/None-or-later term_date; else False so the kept one — the
  later in file — stays, preserving last-wins on a true tie).

**RESOLVED design decision (the key one):** `_dedupe_bob_records` runs BEFORE the per-row
loop, and only surviving recs reach `_import_bob_row`. So if dedup collapsed Robbie's two
rows to one, only that one rec would reach the loop — and plan-history (which consumes a
SEPARATE `status="termed"` rec) would lose the chapter. Therefore:

- **Dedup deduplicates ONLY among policy-CREATING rows** (i.e. `status="active"` rows).
  An active row and a termed row for the same `(carrier, member_id)` **coexist** — they
  do NOT collide, because the termed-rec routing (shipped §4.2) **never creates or updates
  a policy by the upsert path**; it only terms an existing policy + seeds a closed history
  chapter. So the `uq_carrier_member` hazard dedup exists to prevent applies only to the
  active (policy-creating) rows.
- Concretely: when collapsing, the chronological rule (§1) picks the surviving rec among
  rows of the SAME `(carrier, member_id)` that would each create/own the policy — in
  practice the active rows (and, if a member somehow has only termed rows, those are
  handled by the termed routing, no policy created). The earlier termed row is **passed
  through untouched** so it still reaches the loop and seeds plan-history.
- Net: the latest-effective **active** enrollment becomes the policy; every earlier
  enrollment (its own termed row) becomes a closed history chapter. Both survive. The §6
  "history preserved" test is the oracle.

## 5. Repair the 13 (re-import)

After merge + deploy, re-import the June Aetna CSV (DB backed up first; idempotent).
Verify on live Postgres:
- Robbie Belk (and the 13) now have their **active** plan (C-SNP, latest eff) as the
  current policy, with a resolved agent (NPN/name);
- their **old** plan is a CLOSED plan-history chapter (real eff→term);
- the Aetna active count corrects upward (the 13 flip back from termed→active);
- a second re-import is idempotent (no dup policies, no dup history intervals);
- UHC/other carriers unaffected (spot-check a UHC member's single policy is unchanged).

## 6. Testing (TDD)

- **A+T, file order BOTH ways:** a member with an active row (eff 2026-01-01, no term)
  and a termed row (eff 2023-01-01, term 2025-12-31) → the surviving policy rec is the
  2026 active one, regardless of which row is first in the input list.
- **UHC plan-segments unchanged:** two rows, same `(carrier, member_id)`, SAME
  effective_date, both active → last-wins (the second), exactly as today.
- **Sentinel handling:** a row with `term_date=None` (sentinel-stripped) beats a row with
  a real past term_date when effective dates tie.
- **History preserved:** after dedup + import, the earlier enrollment lands as a closed
  plan-history interval with its own eff→term (not lost).
- Real-Postgres verify on the re-import (§5).

## 7. Acceptance criteria

`_dedupe_bob_records` picks the current policy by **latest effective date** (tie → later
term/sentinel → last-wins), independent of file order; UHC plan-segment behavior is
unchanged; the earlier enrollment becomes a closed plan-history chapter; the 13 affected
Aetna members (incl. Robbie Belk) are repaired to active+agent+history on re-import; no
migration.
