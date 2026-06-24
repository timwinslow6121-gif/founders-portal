# Chronological BOB Dedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `_dedupe_bob_records`'s blind last-wins collision rule with a chronological rule (un-termed wins; then later term date; then later effective date) that only collapses policy-creating (active) rows, so an active enrollment is never overwritten by a member's older termed history row — and the older enrollment survives as a plan-history chapter.

**Architecture:** `_dedupe_bob_records` (app/upload.py) currently collapses every row sharing `(carrier, member_id)` to one via last-wins. We change it so (a) **termed rows are never collapsed onto active rows** — they pass through untouched so the shipped §4.2 termed-router can seed plan-history; and (b) when two *active* rows share `(carrier, member_id)`, the chronologically more-current one wins by **term date first, then effective date**: an un-termed row (sentinel/`None` term) beats a row with a real past term; tie → later `term_date`; tie → later `effective_date`; final tie → last-in-file. A small pure helper `_rec_is_more_current(new, kept)` encodes the precedence. No schema change, no migration.

**Tech Stack:** Python 3.10, Flask-SQLAlchemy, pytest. Records are plain dicts from `app/parsers/*` carrying `effective_date`/`term_date` as `datetime.date` or `None` (the parser already strips the `3000-01-01` sentinel to `None`), and `status` ∈ {`"active"`, `"termed"`}.

## Global Constraints

- No DB migration. The fix is pure logic in `_dedupe_bob_records` plus one helper.
- The rule must be **order-independent**: the same input rows in any order must produce the same surviving policy.
- **UHC must be unchanged.** UHC lists a member's plan-segments as multiple rows that all share ONE `effective_date` and are all `active` → they tie on effective date → fall through to last-wins → identical outcome to today.
- Records carry `effective_date`/`term_date` as `datetime.date` or `None`. `None`/sentinel term_date means "no termination / current" and is the STRONGEST signal of the live policy — it sorts as the LATEST and is checked BEFORE effective date.
- Precedence is **term date first, then effective date** (Tim 2026-06-24): un-termed beats a real past term (handles rapid-disenroll: a newer-but-already-termed row must not beat an older still-open one); then later term; then later effective; then last-in-file.
- `_dedupe_bob_records` runs once, BEFORE the per-row import loop (app/upload.py:912); only surviving recs reach `_import_bob_row`.
- The termed-rec router in `_import_bob_row` (app/upload.py:100-115) NEVER creates/updates a policy via the upsert path — it only terms an existing policy and seeds a closed history chapter. Therefore termed rows cannot trigger the `uq_carrier_member` collision the dedup exists to prevent, and may safely coexist with an active row of the same key.

---

### Task 1: Add the chronological precedence helper `_rec_is_more_current`

**Files:**
- Modify: `app/upload.py` (add helper directly above `_dedupe_bob_records`, currently at line 71)
- Test: `tests/test_bob_upload.py`

**Interfaces:**
- Produces: `_rec_is_more_current(new: dict, kept: dict) -> bool` — returns `True` iff `new` should replace `kept` as the surviving current policy for a shared `(carrier, member_id)`. Precedence (term date FIRST): (1) un-termed (`term_date` `None`/sentinel) beats a real past term; (2) if both un-termed or both real-termed, later `term_date` wins; (3) on a term-date tie, later `effective_date` wins; (4) on a full tie, return `True` (see caller contract below).

**Caller contract note (read before writing the helper):** In Task 2 the caller iterates rows in file order and, on a key collision, replaces the kept rec **only if `_rec_is_more_current(new, kept)` is True**. So for the final-tie case we want LAST-in-file to win (UHC parity). That means on a full tie the helper must return **`True`** (so the later-iterated row replaces the earlier one), NOT `False`. The §1 spec text says "last-wins" on the final tie; with this caller shape that requires returning `True` on a tie. Encode it that way.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_bob_upload.py`:

```python
def test_rec_more_current_untermed_beats_real_term():
    """Robbie Belk core: an un-termed (None term) row beats a real-past-termed row,
    even when the un-termed row has the EARLIER effective date is not the case here,
    but term date is checked first regardless of effective date."""
    from app.upload import _rec_is_more_current
    from datetime import date
    new = {"effective_date": date(2026, 1, 1), "term_date": None}            # current
    kept = {"effective_date": date(2023, 1, 1), "term_date": date(2025, 12, 31)}
    assert _rec_is_more_current(new, kept) is True
    # reverse: a real-past-termed row does NOT replace an un-termed one
    assert _rec_is_more_current(kept, new) is False


def test_rec_more_current_untermed_beats_real_term_even_when_older_effective():
    """Rapid-disenroll: a NEWER enrollment that already termed must NOT beat an OLDER
    still-open policy the member fell back to. Term date wins over effective date."""
    from app.upload import _rec_is_more_current
    from datetime import date
    open_older = {"effective_date": date(2025, 1, 1), "term_date": None}
    termed_newer = {"effective_date": date(2026, 1, 1), "term_date": date(2026, 2, 28)}
    # the older-but-open policy is the survivor
    assert _rec_is_more_current(open_older, termed_newer) is True
    assert _rec_is_more_current(termed_newer, open_older) is False


def test_rec_more_current_both_real_term_later_term_wins():
    """Both rows carry a real term -> the later term date wins; if those tie, the
    later effective date breaks it."""
    from app.upload import _rec_is_more_current
    from datetime import date
    new = {"effective_date": date(2024, 1, 1), "term_date": date(2026, 12, 31)}
    kept = {"effective_date": date(2024, 1, 1), "term_date": date(2025, 12, 31)}
    assert _rec_is_more_current(new, kept) is True


def test_rec_more_current_term_tie_later_effective_wins():
    """Term dates tie (both un-termed) -> later effective date wins."""
    from app.upload import _rec_is_more_current
    from datetime import date
    new = {"effective_date": date(2026, 1, 1), "term_date": None}
    kept = {"effective_date": date(2023, 1, 1), "term_date": None}
    assert _rec_is_more_current(new, kept) is True
    assert _rec_is_more_current(kept, new) is False


def test_rec_more_current_full_tie_last_wins():
    """Full tie (same term, same effective) -> later-iterated row wins (UHC parity)."""
    from app.upload import _rec_is_more_current
    from datetime import date
    eff = date(2026, 1, 1)
    new = {"effective_date": eff, "term_date": None}
    kept = {"effective_date": eff, "term_date": None}
    assert _rec_is_more_current(new, kept) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_bob_upload.py -k rec_more_current -v`
Expected: FAIL — `ImportError: cannot import name '_rec_is_more_current' from 'app.upload'`

- [ ] **Step 3: Write the helper**

Insert above `_dedupe_bob_records` (currently line 71) in `app/upload.py`:

```python
from datetime import date as _date


def _rec_is_more_current(new, kept):
    """True iff BOB rec `new` should replace `kept` as the surviving CURRENT policy
    for a shared (carrier, member_id). TERM DATE FIRST, then effective date — dates,
    not row order, decide (Tim 2026-06-24):
      1. un-termed wins: a None/sentinel-stripped term_date is the LIVE policy and beats
         a row carrying a real past term (handles rapid-disenroll: a newer-but-already-
         termed row must NOT beat an older still-open one). A term date is an affirmative
         carrier action — no real term = current.
      2. if both un-termed (None) or both real-termed, the later term_date wins;
      3. on a term-date tie, the later effective_date wins (None effective sorts EARLIEST
         so a dated row beats an undated one);
      4. on a full tie, `new` wins -> with the file-order caller this makes LAST-in-file
         win, preserving UHC plan-segment last-wins behavior.
    The parser already strips the 3000-01-01 / 2300-01-01 sentinel to None, so a None
    term_date here means BOTH 'blank' and 'sentinel far-future' — i.e. 'current'."""
    _MIN = _date.min
    _MAX = _date.max
    # term date first: None/sentinel == "no termination" == latest == current
    nt = new.get("term_date") or _MAX
    kt = kept.get("term_date") or _MAX
    if nt != kt:
        return nt > kt
    # term-date tie -> later effective_date wins; None effective sorts earliest
    ne = new.get("effective_date") or _MIN
    ke = kept.get("effective_date") or _MIN
    if ne != ke:
        return ne > ke
    return True   # full tie -> last-in-file wins (UHC parity)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_bob_upload.py -k rec_more_current -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add app/upload.py tests/test_bob_upload.py
git commit -m "feat: add _rec_is_more_current chronological precedence helper for BOB dedup"
```

---

### Task 2: Rewrite `_dedupe_bob_records` — chronological, active-only collapse

**Files:**
- Modify: `app/upload.py:71-92` (the `_dedupe_bob_records` body)
- Test: `tests/test_bob_upload.py`

**Interfaces:**
- Consumes: `_rec_is_more_current` (Task 1).
- Produces: `_dedupe_bob_records(records: list[dict]) -> list[dict]` — same signature. New behavior: only `status == "active"` rows with a truthy `member_id` participate in collision dedup (keyed on `(carrier, member_id)`); the surviving active rec is chosen by `_rec_is_more_current`. **Termed rows and member_id-less rows are passed through untouched**, preserving their original position.

**Why termed rows pass through (the bug fix):** an active row and a termed row sharing `(carrier, member_id)` must BOTH reach `_import_bob_row`. The termed-rec router (app/upload.py:100-115) seeds the plan-history chapter from the termed row and never touches the policy upsert — so it can't re-trigger the unique-constraint collision dedup guards against, and collapsing it (today's bug) is exactly what destroyed Robbie Belk's history + overwrote his active policy.

- [ ] **Step 1: Write the failing tests (new behavior)**

Add to `tests/test_bob_upload.py`. NOTE: Step 1 of Task 3 deletes/rewrites the two OLD tests that assert active+termed collapse; do that there, not here.

```python
def test_dedupe_active_and_termed_coexist():
    """Robbie Belk: an ACTIVE current enrollment and a TERMED old enrollment share
    the same (carrier, member_id). They must NOT collapse — both survive so the
    termed row can seed plan-history and the active row owns the policy."""
    from app.upload import _dedupe_bob_records
    from datetime import date
    records = [
        {"carrier": "Aetna", "member_id": "6274", "status": "termed",
         "plan_name": "Value Plus", "effective_date": date(2023, 1, 1),
         "term_date": date(2025, 12, 31)},
        {"carrier": "Aetna", "member_id": "6274", "status": "active",
         "plan_name": "Chronic Care C-SNP", "effective_date": date(2026, 1, 1),
         "term_date": None},
    ]
    out = _dedupe_bob_records(records)
    assert len(out) == 2
    statuses = sorted(r["status"] for r in out)
    assert statuses == ["active", "termed"]


def test_dedupe_two_active_latest_effective_wins_order_independent():
    """Two ACTIVE rows, same key, different effective dates -> the later-effective
    one is the surviving policy regardless of input order."""
    from app.upload import _dedupe_bob_records
    from datetime import date
    older = {"carrier": "Aetna", "member_id": "M1", "status": "active",
             "plan_name": "Old", "effective_date": date(2023, 1, 1), "term_date": None}
    newer = {"carrier": "Aetna", "member_id": "M1", "status": "active",
             "plan_name": "New", "effective_date": date(2026, 1, 1), "term_date": None}
    for records in ([older, newer], [newer, older]):
        out = _dedupe_bob_records(records)
        survivors = [r for r in out if r["member_id"] == "M1"]
        assert len(survivors) == 1
        assert survivors[0]["plan_name"] == "New"


def test_dedupe_uhc_plan_segments_last_wins_unchanged():
    """UHC plan-segments: multiple ACTIVE rows sharing key AND effective_date ->
    last-in-file wins, exactly as before this change."""
    from app.upload import _dedupe_bob_records
    from datetime import date
    eff = date(2026, 1, 1)
    records = [
        {"carrier": "UHC", "member_id": "U1", "status": "active",
         "plan_name": "Seg A", "effective_date": eff, "term_date": None},
        {"carrier": "UHC", "member_id": "U1", "status": "active",
         "plan_name": "Seg B", "effective_date": eff, "term_date": None},
    ]
    out = _dedupe_bob_records(records)
    survivors = [r for r in out if r["member_id"] == "U1"]
    assert len(survivors) == 1
    assert survivors[0]["plan_name"] == "Seg B"   # last wins


def test_dedupe_passes_through_rows_without_member_id_still():
    from app.upload import _dedupe_bob_records
    records = [
        {"carrier": "UHC", "member_id": None, "full_name": "A", "status": "active"},
        {"carrier": "UHC", "member_id": "", "full_name": "B", "status": "active"},
        {"carrier": "UHC", "member_id": "M9", "full_name": "C", "status": "active"},
    ]
    out = _dedupe_bob_records(records)
    assert len(out) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_bob_upload.py -k "dedupe_active_and_termed or two_active_latest or uhc_plan_segments" -v`
Expected: FAIL — `test_dedupe_active_and_termed_coexist` fails (current code collapses to 1); `test_dedupe_two_active_latest_effective_wins` fails (current last-wins picks `Old` when it's last in file).

- [ ] **Step 3: Rewrite `_dedupe_bob_records`**

Replace the body of `_dedupe_bob_records` (app/upload.py:71-92) with:

```python
def _dedupe_bob_records(records):
    """Collapse repeated (carrier, member_id) BOB rows so a member listed multiple
    times can't collide on the uq_carrier_member unique constraint mid-upload.

    Only ACTIVE (policy-creating) rows are deduped. Among active rows sharing a key,
    the CHRONOLOGICALLY most-current one wins (TERM DATE first: un-termed beats a real
    past term; then later term_date; then later effective_date; full tie -> last-in-file),
    via _rec_is_more_current — NOT blind row order. The surviving rec keeps its original
    slot so import order is stable.

    Termed rows and member_id-less rows are passed through UNTOUCHED: a termed row for
    the same key as an active row coexists with it (the termed-rec router only seeds
    plan-history + terms an existing policy, never upserts, so it can't trip the unique
    constraint). This is the fix for the active-enrollment-overwritten-by-old-termed-row
    bug (Robbie Belk): the latest active enrollment becomes the policy and every earlier
    enrollment's termed row becomes a closed plan-history chapter."""
    seen = {}          # (carrier, member_id) -> index in `out` of the kept ACTIVE rec
    out = []
    for rec in records:
        mid = rec.get("member_id")
        if not mid or rec.get("status") != "active":
            out.append(rec)               # termed / id-less rows pass through
            continue
        key = (rec.get("carrier"), mid)
        if key in seen:
            kept_idx = seen[key]
            if _rec_is_more_current(rec, out[kept_idx]):
                out[kept_idx] = rec        # chronologically newer active rec wins its slot
        else:
            seen[key] = len(out)
            out.append(rec)
    return out
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python3 -m pytest tests/test_bob_upload.py -k "dedupe_active_and_termed or two_active_latest or uhc_plan_segments or passes_through_rows_without_member_id_still or dedupe_scopes_by_carrier" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/upload.py tests/test_bob_upload.py
git commit -m "fix: chronological active-only BOB dedup (latest effective date wins; termed rows coexist)"
```

---

### Task 3: Update the two OLD dedup tests that encoded the bug

**Files:**
- Modify: `tests/test_bob_upload.py` — `test_dedupe_collapses_repeated_carrier_member_id_last_wins` (line 10) and `test_dedupe_prevents_in_file_duplicate_collision` (line 99)

**Interfaces:**
- Consumes: the rewritten `_dedupe_bob_records` (Task 2), `_import_bob_row`.

**Why this task exists:** both old tests assert that an active row + a termed row collapse to ONE row with the termed row winning. That is precisely the behavior we just fixed away. They will now FAIL and must be updated to assert the correct (coexist) behavior. Do NOT "fix" the code to make them pass — they encode the bug.

- [ ] **Step 1: Run the suite to see exactly which old tests now fail**

Run: `python3 -m pytest tests/test_bob_upload.py -v`
Expected: `test_dedupe_collapses_repeated_carrier_member_id_last_wins` FAILS (now 2 rows, not 1, because the termed row no longer collapses) and `test_dedupe_prevents_in_file_duplicate_collision` FAILS (now 2 policies/rows survive the dedup, or the surviving policy is active not termed). Note the exact assertion lines that break.

- [ ] **Step 2: Rewrite `test_dedupe_collapses_repeated_carrier_member_id_last_wins`**

Replace the test at line 10-25 with a version that (a) keeps the pure UHC plan-segment last-wins case (two ACTIVE rows, same effective date) and (b) drops the active+termed collapse assertion (now covered by `test_dedupe_active_and_termed_coexist` in Task 2):

```python
def test_dedupe_collapses_repeated_active_segments_last_wins():
    from app.upload import _dedupe_bob_records
    from datetime import date
    eff = date(2026, 1, 1)
    records = [
        {"carrier": "UHC", "member_id": "M1", "plan_name": "Plan A",
         "status": "active", "effective_date": eff, "term_date": None},
        {"carrier": "UHC", "member_id": "M2", "plan_name": "Other",
         "status": "active", "effective_date": eff, "term_date": None},
        {"carrier": "UHC", "member_id": "M1", "plan_name": "Plan B",
         "status": "active", "effective_date": eff, "term_date": None},
    ]
    out = _dedupe_bob_records(records)
    assert len(out) == 2
    m1 = [r for r in out if r["member_id"] == "M1"]
    assert len(m1) == 1
    assert m1[0]["plan_name"] == "Plan B"      # tie on effective date -> last wins
    assert [r["member_id"] for r in out] == ["M1", "M2"]   # original order preserved
```

- [ ] **Step 3: Rewrite `test_dedupe_prevents_in_file_duplicate_collision`**

Replace the test at line 99-134. Keep its real purpose — proving in-file duplicate ACTIVE rows don't collide on `uq_carrier_member` — but make both rows ACTIVE (the collision case dedup actually guards) and assert the latest-effective active row wins:

```python
def test_dedupe_prevents_in_file_duplicate_collision(db_session, app, agency, agent_user):
    """In-file duplicate ACTIVE rows for the same (carrier, member_id) must collapse
    to one BEFORE import so they never hit uq_carrier_member, and the surviving row is
    the chronologically latest active enrollment."""
    from app.extensions import db
    from app.models import ImportBatch, Policy
    from app.upload import _import_bob_row, _dedupe_bob_records
    from datetime import date

    with app.app_context():
        batch = ImportBatch(agency_id=agency.id, carrier="UHC", filename="f.xlsx",
                            uploaded_by_id=agent_user.id, status="pending")
        db.session.add(Policy(agency_id=agency.id, carrier="UHC", member_id="DUP1",
                              mbi="MBIDUP0001", first_name="A", last_name="B",
                              full_name="A B", plan_name="Plan A", status="active"))
        db.session.add(batch); db.session.commit()

        records = [
            _bob_rec("UHC", "DUP1", "MBIDUP0001", plan_name="Plan A",
                     effective_date=date(2024, 1, 1)),
            _bob_rec("UHC", "DUP1", "MBIDUP0001", plan_name="Plan B",
                     effective_date=date(2026, 1, 1)),
        ]
        for rec in _dedupe_bob_records(records):
            with db.session.begin_nested():
                _import_bob_row(rec, batch, agency.id, agent_user.id, date.today(), [])
        db.session.commit()   # MUST NOT raise UniqueViolation

        pols = Policy.query.filter_by(agency_id=agency.id, member_id="DUP1").all()
        assert len(pols) == 1                 # collapsed, no collision
        assert pols[0].status == "active"
        assert pols[0].plan_name == "Plan B"  # latest effective date wins
```

- [ ] **Step 4: Run the full upload test file**

Run: `python3 -m pytest tests/test_bob_upload.py -v`
Expected: PASS (all tests, old + new)

- [ ] **Step 5: Commit**

```bash
git add tests/test_bob_upload.py
git commit -m "test: update dedup tests to chronological active-only behavior (drop bug-encoding assertions)"
```

---

### Task 4: End-to-end test — active+termed import yields active policy + closed history chapter

**Files:**
- Test: `tests/test_bob_upload.py`

**Interfaces:**
- Consumes: `_dedupe_bob_records`, `_import_bob_row`, the shipped `_seed_closed_history` / termed-router path.

**Purpose:** this is the spec §6 "history preserved" oracle — the integration proof that the Robbie Belk scenario is fully repaired through the real import loop, not just the dedup helper. It exercises both the surviving active policy AND the seeded plan-history chapter.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_bob_upload.py`:

```python
def test_active_plus_termed_import_keeps_active_policy_and_seeds_history(
        db_session, app, agency, agent_user):
    """Robbie Belk end-to-end: a member with an old TERMED enrollment and a current
    ACTIVE enrollment imports to an ACTIVE policy (latest plan) AND a closed
    plan-history chapter for the old enrollment."""
    from app.extensions import db
    from app.models import ImportBatch, Policy, Customer, CustomerAorHistory
    from app.upload import _import_bob_row, _dedupe_bob_records
    from datetime import date

    with app.app_context():
        # Member already exists as a customer (so the termed router acts, not skips).
        db.session.add(Customer(agency_id=agency.id, first_name="Robbie",
                                last_name="Belk", full_name="Robbie Belk",
                                mbi="MBIROBBIE01", primary_agent_id=agent_user.id))
        db.session.add(Policy(agency_id=agency.id, carrier="Aetna", member_id="6274",
                              mbi="MBIROBBIE01", first_name="Robbie", last_name="Belk",
                              full_name="Robbie Belk", plan_name="Value Plus",
                              status="active", effective_date=date(2023, 1, 1)))
        batch = ImportBatch(agency_id=agency.id, carrier="Aetna", filename="f.csv",
                            uploaded_by_id=agent_user.id, status="pending")
        db.session.add(batch); db.session.commit()

        records = [
            _bob_rec("Aetna", "6274", "MBIROBBIE01", status="active",
                     plan_name="Chronic Care C-SNP",
                     effective_date=date(2026, 1, 1), term_date=None,
                     first_name="Robbie", last_name="Belk", full_name="Robbie Belk"),
            _bob_rec("Aetna", "6274", "MBIROBBIE01", status="termed",
                     plan_name="Value Plus",
                     effective_date=date(2023, 1, 1), term_date=date(2025, 12, 31),
                     first_name="Robbie", last_name="Belk", full_name="Robbie Belk"),
        ]
        for rec in _dedupe_bob_records(records):
            with db.session.begin_nested():
                _import_bob_row(rec, batch, agency.id, agent_user.id, date.today(), [])
        db.session.commit()

        pols = Policy.query.filter_by(agency_id=agency.id, member_id="6274").all()
        assert len(pols) == 1
        assert pols[0].status == "active"
        assert pols[0].plan_name == "Chronic Care C-SNP"
        assert pols[0].effective_date == date(2026, 1, 1)

        cust = Customer.query.filter_by(mbi="MBIROBBIE01").first()
        hist = CustomerAorHistory.query.filter_by(
            customer_id=cust.id, carrier="Aetna").all()
        closed = [h for h in hist if h.effective_date == date(2023, 1, 1)]
        assert len(closed) == 1
        assert closed[0].plan_name == "Value Plus"
        assert closed[0].end_date == date(2025, 12, 31)
```

- [ ] **Step 2: Run it to verify it passes (or surfaces a real gap)**

Run: `python3 -m pytest tests/test_bob_upload.py::test_active_plus_termed_import_keeps_active_policy_and_seeds_history -v`
Expected: PASS. If it FAILS on the history assertion, the dedup is dropping the termed row — re-check Task 2 Step 3 (the `status != "active"` pass-through). If it FAILS because the termed router runs BEFORE the active row exists in DB (order matters: the termed router terms an EXISTING policy), confirm the seed-history path keys off the customer (it does — it seeds a closed chapter from the termed rec regardless of policy state) and that the active row's upsert creates/updates the live policy. Do not weaken the assertions; fix the cause.

- [ ] **Step 3: Commit**

```bash
git add tests/test_bob_upload.py
git commit -m "test: e2e active+termed import keeps active policy and seeds closed history (Robbie Belk)"
```

---

### Task 5: Full suite green + branch review gate

**Files:** none (verification task)

- [ ] **Step 1: Run the entire test suite**

Run: `python3 -m pytest -q`
Expected: all pass. If any non-dedup test broke, investigate — dedup is a hot path on every BOB upload. Pay attention to `test_bob_term_aor.py`, `test_aetna_csv_parser.py`, `test_process_upload_termed.py`, and `test_bob_upsert_characterization.py`.

- [ ] **Step 2: Request whole-branch opus code review**

Per the session protocol (the opus whole-branch review caught a real bug in every data-path round), use `superpowers:requesting-code-review` on the full branch before merge. Focus the reviewer on: order-independence of the new rule; that termed rows truly coexist (no silent collapse); UHC parity; and any path where a member has ONLY termed rows (must still be handled by the termed router with no policy created).

- [ ] **Step 3: Address review findings, re-run suite**

Run: `python3 -m pytest -q`
Expected: all pass after any fixes.

---

### Task 6: Re-import the June Aetna CSV to repair the 13 (deploy + live verify)

**Files:** none in repo (operational task on the VPS)

**Prerequisite:** Tasks 1-5 merged to `main` and deployed to the VPS (`git pull` — no `pip install` deps, no `flask db upgrade` since there is no migration; `systemctl restart founders-portal`).

- [ ] **Step 1: Back up the live DB first**

```bash
ssh -i /home/timothywinslowlinux/.ssh/id_ed25519 root@23.187.248.100
PGPASSWORD=<from .env DATABASE_URL> pg_dump -U founders_user -h localhost founders_portal \
  > /root/founders_portal_pre_chrono_dedup_$(date +%Y%m%d_%H%M%S).sql
```

- [ ] **Step 2: Re-import the June Aetna `MedicareApprovedBOBReport` CSV**

Re-upload the same June Aetna CSV through the admin BOB upload UI (the import is idempotent). This is the same file referenced in the 2026-06-23 handoff (`MedicareApprovedBOBReport_20260618.csv`).

- [ ] **Step 3: Verify the 13 are repaired (Robbie Belk = grounding case)**

On the VPS (`PYTHONPATH=/var/www/founders-portal ./venv/bin/python3` or psql), confirm:
- Robbie Belk (customer 6274) now has the **active** C-SNP (eff 2026-01-01) as the current policy with a resolved agent.
- His old Value Plus is a **closed** `CustomerAorHistory` chapter (eff 2023-01-01, end 2025-12-31).
- The Aetna active count corrected upward (the 13 flipped termed→active).
- A second re-import is idempotent (no duplicate policies, no duplicate history intervals).
- Spot-check a UHC member's single policy is unchanged.

- [ ] **Step 4: Update docs per the Session Protocol**

- Mark the spec `docs/superpowers/specs/2026-06-24-chronological-bob-dedup-design.md` Status → shipped.
- Update CLAUDE.md "START HERE" (resolve the open RESUME-HERE thread).
- Reconcile `BACKLOG.md` (move to Recently shipped; keep the deferred AEP same-eff tie-break gap open with its ~Oct 2026 trigger).
- Update the latest `memory/session-handoff-*.md`.
- Commit.
