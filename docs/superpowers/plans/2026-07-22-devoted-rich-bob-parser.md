# Devoted Rich Application-Status BOB Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse the full Devoted "Application Status Report" BOB (rich variant with real MBIs) correctly — keyed by the real MBI, capturing plan ID / type / address / agent / application date — and resolve same-MBI competing applications by the winning-app flag, so the file can be reconciled into the DB.

**Architecture:** Add a `_parse_application_status_rich()` path in `app/parsers/devoted.py`, selected by detecting the `"Application Status Report Mbi"` column; the existing lossy path stays unchanged. Extend the shared dedup tie-break in `app/upload.py` (`_rec_is_more_current`) to prefer the winning application (flag, then application date) when dates tie, flagging genuinely-ambiguous pairs for review. No change to the import pipeline or `resolve_customer()`.

**Tech Stack:** Python, pandas, openpyxl (test fixtures), pytest.

## Global Constraints

- **Key by the real MBI.** The rich path sets `mbi` = the `Mbi` column (uppercased) and uses the MBI as `member_id` — NO synthetic `DVND-` ids. The existing lossy path (no `Mbi` column) is unchanged.
- **Active-status rule:** `Current Status` ∈ {`Enrolled`, `Approved`} → active; any other status → skip. `Is Winning App` is NOT a skip filter (it only resolves same-MBI duplicates).
- **Same-MBI resolution precedence:** (1) `is_winning_app=True` wins; (2) else later `application_date` wins; (3) else (flag AND application_date both tied) → do not guess, flag for review.
- **commission_type** from `Is New to Medicare Advantage`: `Yes` → `"initial"`, else `"renewal"`.
- **Detection:** rich vs lossy Application-Status = presence of the `Application Status Report Mbi` column. Non-Application-Status Devoted files (snake_case CSV) still use the CSV path.
- Carriers that don't set `is_winning_app` / `application_date` must be unaffected by the dedup change.
- Tests run with `python3 -m pytest`. Match `tests/test_devoted_parser.py` fixture style (openpyxl, header row + data rows).

---

### Task 1: Rich Application-Status parser path

**Files:**
- Modify: `app/parsers/devoted.py`
- Test: `tests/test_devoted_parser.py`

**Interfaces:**
- Produces: `parse(filepath)` now routes a file whose columns include `"Application Status Report Mbi"` to a new `_parse_application_status_rich(df)`, which returns a list of record dicts. Each rich record has these keys (in addition to those the existing paths emit): `mbi`, `member_id` (== mbi), `first_name`, `last_name`, `full_name`, `dob`, `phone`, `address1`, `city`, `state`, `zip_code`, `county`, `effective_date`, `term_date`, `plan_name`, `plan_type`, `agent_name`, `agent_id`, `application_date` (date|None), `is_winning_app` (bool), `commission_type` (`"initial"`|`"renewal"`), `status` (`"active"`), `carrier="Devoted"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_devoted_parser.py` (it already imports `openpyxl` and `parse`). Add a rich-format column list + fixture helper, then the tests:

```python
# Rich Application-Status format (the full BOB — has an Mbi column + more).
RICH_COLS = [
    "Application Status Report Agent Name",
    "Application Status Report Agent Npn",
    "Application Status Report Agent Primary Rts State",
    "Application Status Report Full Name",
    "Application Status Report Birth Date",
    "Application Status Report Mbi",
    "Application Status Report Phone Number",
    "Application Status Report Address",
    "Application Status Report City",
    "Application Status Report State",
    "Application Status Report Zip Code",
    "Application Status Report County",
    "Application Status Report Current Status",
    "Application Status Report Application Date",
    "Application Status Report Start Date",
    "Application Status Report Plan Name",
    "Application Status Report Plan ID",
    "Application Status Report Disenrollment Date",
    "Application Status Report Disenrollment Reason",
    "Application Status Report Is Plan Change (Yes / No)",
    "Application Status Report Is New to Medicare Advantage (Yes / No)",
    "Application Status Report Is New to Devoted (Yes / No)",
    "Application Status Report Is Application Is Currently Pending (Yes / No)",
    "Application Status Report Pending Reason",
    "Application Status Report Is Winning App (Yes / No)",
    "Application Status Report First Name",
    "Application Status Report Last Name",
    "Application Status Report Plan End Date",
    "Application Status Report Plan Type",
]


def _rich_xlsx(tmp_path, rows):
    p = tmp_path / "Devoted Book of business.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(RICH_COLS)
    for r in rows:
        ws.append(r)
    wb.save(p)
    return str(p)


def _rich_row(**kw):
    """One rich data row aligned to RICH_COLS, with sensible defaults."""
    d = dict(agent="Justin Basinger", npn="20446812", rts="NC",
             full="Praize Medley", dob="2004-06-17", mbi="2T74G35WQ90",
             phone="7045160684", addr="845 Highlander Ct", city="Concord",
             state="NC", zip="28025", county="CABARRUS", status="Enrolled",
             appdate="2025-10-21", start="2026-01-01",
             plan_name="DEVOTED DUAL FULL 013 NC", plan_id="H5299-013",
             disenr="", disenr_reason="", plan_change="No", new_ma="No",
             new_dev="Yes", pending="No", pending_reason="", winning="Yes",
             first="PRAIZE", last="MEDLEY", plan_end="", ptype="MAPD")
    d.update(kw)
    return [d["agent"], d["npn"], d["rts"], d["full"], d["dob"], d["mbi"],
            d["phone"], d["addr"], d["city"], d["state"], d["zip"], d["county"],
            d["status"], d["appdate"], d["start"], d["plan_name"], d["plan_id"],
            d["disenr"], d["disenr_reason"], d["plan_change"], d["new_ma"],
            d["new_dev"], d["pending"], d["pending_reason"], d["winning"],
            d["first"], d["last"], d["plan_end"], d["ptype"]]


def test_rich_row_captures_real_mbi_and_fields(tmp_path):
    p = _rich_xlsx(tmp_path, [_rich_row()])
    recs = parse(p)
    assert len(recs) == 1
    r = recs[0]
    assert r["mbi"] == "2T74G35WQ90"
    assert r["member_id"] == "2T74G35WQ90"        # MBI is the key, no DVND-
    assert r["first_name"] == "Praize" and r["last_name"] == "Medley"
    assert r["plan_name"] == "DEVOTED DUAL FULL 013 NC"
    assert r["plan_type"] == "MAPD"
    assert r["agent_name"] == "Justin Basinger"
    assert str(r["effective_date"]) == "2026-01-01"
    assert str(r["application_date"]) == "2025-10-21"
    assert r["city"] == "Concord" and r["county"] == "CABARRUS"
    assert r["is_winning_app"] is True
    assert r["commission_type"] == "renewal"       # New-to-MA = No
    assert r["status"] == "active"


def test_rich_new_to_ma_yes_is_initial(tmp_path):
    p = _rich_xlsx(tmp_path, [_rich_row(new_ma="Yes", mbi="3DJ9F94VV42")])
    assert parse(p)[0]["commission_type"] == "initial"


def test_rich_approved_is_active(tmp_path):
    p = _rich_xlsx(tmp_path, [_rich_row(status="Approved", mbi="4U76AC0RQ88")])
    recs = parse(p)
    assert len(recs) == 1
    assert recs[0]["status"] == "active"


def test_rich_other_status_skipped(tmp_path):
    p = _rich_xlsx(tmp_path, [_rich_row(status="Withdrawn", mbi="5CU9P00HW31")])
    assert parse(p) == []


def test_rich_lone_non_winning_still_active(tmp_path):
    # Peggy/Cynthia shape: a lone Is-Winning-App=No row that is Enrolled stays.
    p = _rich_xlsx(tmp_path, [_rich_row(winning="No", mbi="7G47C78AK61", full="Peggy Marsh")])
    recs = parse(p)
    assert len(recs) == 1
    assert recs[0]["is_winning_app"] is False
    assert recs[0]["status"] == "active"


def test_old_lossy_application_status_still_parses(tmp_path):
    # Regression: the OLD lossy file (APP_COLS, NO Mbi column) still uses the
    # synth-id path and must keep working.
    p = _app_status_xlsx(tmp_path, [
        ["Anjana Patel", "21041582", "NC", "BRANDI TUCKER", "1977-03-21",
         "Enrolled", "Yes", "2026-04-01", "2026-04-01", "Devoted CORE", "H1234-001",
         "No", "Yes", "Yes"],
    ])
    recs = parse(p)
    assert len(recs) == 1
    assert recs[0]["member_id"].startswith("DVND-")   # synth path unchanged
    assert recs[0]["mbi"] == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_devoted_parser.py -k "rich or lossy" -v`
Expected: the rich tests FAIL (rich path not implemented → routes to lossy path → no `Mbi`/wrong keys); the regression test may pass.

- [ ] **Step 3: Add the detection + rich parser**

In `app/parsers/devoted.py`, in `parse()`, change the Application-Status branch so it distinguishes rich vs lossy. Find (around line 46):

```python
        if any(str(c).strip().lower().startswith(_APP_PREFIX) for c in xdf.columns):
            return _parse_application_status(xdf)
```

Replace with:

```python
        if any(str(c).strip().lower().startswith(_APP_PREFIX) for c in xdf.columns):
            # Two Application-Status variants: the RICH full BOB has an Mbi column
            # (real CMS MBIs + plan ID/type/address); the older lossy one does not.
            has_mbi_col = any(
                str(c).strip().lower() == "application status report mbi"
                for c in xdf.columns
            )
            if has_mbi_col:
                return _parse_application_status_rich(xdf)
            return _parse_application_status(xdf)
```

Then add the rich parser function (place it right after `_parse_application_status`, near line 136). Note: this function uses the same `_str` / `_parse_date` helpers already in the file, which take a pandas row and a column name.

```python
def _yesno(row, col_short) -> bool:
    """True iff the 'Yes / No' column reads 'Yes' (case-insensitive)."""
    return _str(row, f"Application Status Report {col_short}").strip().lower() == "yes"


def _parse_application_status_rich(df):
    """The FULL Devoted BOB ('Application Status Report' with an Mbi column):
    real CMS MBI + plan ID/type + address + writing-agent name + application date
    + competing-app flags. Keyed by the real MBI (no synthetic id). Enrolled OR
    Approved => active; any other status skipped. Captures is_winning_app +
    application_date for the same-MBI dedup tie-break (app/upload.py)."""
    def col(short):
        return f"Application Status Report {short}"

    records = []
    for _, row in df.iterrows():
        status_raw = _str(row, col("Current Status")).strip().lower()
        if status_raw not in ("enrolled", "approved"):
            continue                                # active book only

        mbi = _str(row, col("Mbi")).upper()
        if not mbi:
            continue                                # rich path is MBI-keyed

        first = _str(row, col("First Name")).title()
        last = _str(row, col("Last Name")).title()
        full = _str(row, col("Full Name"))
        if not first and not last:
            first, last = _split_full_name(full)
            first, last = first.title(), last.title()

        records.append({
            "carrier": "Devoted",
            "member_id": mbi,                       # MBI is the key
            "mbi": mbi,
            "first_name": first,
            "last_name": last,
            "full_name": full or f"{first} {last}".strip(),
            "dob": _parse_date(row, col("Birth Date")),
            "phone": _str(row, col("Phone Number")),
            "address1": _str(row, col("Address")),
            "city": _str(row, col("City")),
            "state": _str(row, col("State")),
            "zip_code": _str(row, col("Zip Code")),
            "county": _str(row, col("County")),
            "effective_date": _parse_date(row, col("Start Date")),
            "term_date": (_parse_date(row, col("Plan End Date"))
                          or _parse_date(row, col("Disenrollment Date"))),
            "plan_name": _str(row, col("Plan Name")),
            "plan_type": _str(row, col("Plan Type")),
            "agent_name": _str(row, col("Agent Name")),
            "agent_id": _str(row, col("Agent Npn")),
            "application_date": _parse_date(row, col("Application Date")),
            "is_winning_app": _yesno(row, "Is Winning App (Yes / No)"),
            "commission_type": ("initial"
                                if _yesno(row, "Is New to Medicare Advantage (Yes / No)")
                                else "renewal"),
            "status": "active",
        })
    return records
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_devoted_parser.py -k "rich or lossy" -v`
Expected: PASS (6 new tests + regression).

- [ ] **Step 5: Run the full devoted parser suite (no regressions)**

Run: `python3 -m pytest tests/test_devoted_parser.py -q`
Expected: all pass (old CSV + old lossy Application-Status tests still green).

- [ ] **Step 6: Commit**

```bash
git add app/parsers/devoted.py tests/test_devoted_parser.py
git commit -m "feat: Devoted rich Application-Status parser (real MBI + plan/agent/appdate)"
```

---

### Task 2: Winning-app tie-break in the shared dedup

**Files:**
- Modify: `app/upload.py` (`_rec_is_more_current`, ~line 74-101)
- Test: `tests/test_devoted_parser.py` (or a dedup test file if one is preferred — keep with devoted for cohesion)

**Interfaces:**
- Consumes: records carrying `is_winning_app` (bool) and `application_date` (date|None) from Task 1.
- Produces: `_rec_is_more_current(new, kept)` now, when term_date AND effective_date tie, prefers the winning application: `is_winning_app=True` beats `False`; if that ties, a later `application_date` wins; if that also ties, falls through to the existing last-in-file `return True`. Records lacking these keys are unaffected.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_devoted_parser.py` (import the function):

```python
from app.upload import _rec_is_more_current
from datetime import date


def test_dedup_winning_app_beats_losing_on_date_tie():
    # Same term (None) + same eff date => winning-app decides.
    winner = {"term_date": None, "effective_date": date(2026, 1, 1),
              "is_winning_app": True, "application_date": date(2025, 11, 13)}
    loser = {"term_date": None, "effective_date": date(2026, 1, 1),
             "is_winning_app": False, "application_date": date(2025, 11, 18)}
    # winner should replace loser even though loser has a LATER app date
    assert _rec_is_more_current(winner, loser) is True
    # and the loser should NOT replace the winner
    assert _rec_is_more_current(loser, winner) is False


def test_dedup_later_appdate_wins_when_flag_ties():
    # Both same winning flag + same eff/term => later application_date wins.
    later = {"term_date": None, "effective_date": date(2026, 1, 1),
             "is_winning_app": True, "application_date": date(2025, 12, 5)}
    earlier = {"term_date": None, "effective_date": date(2026, 1, 1),
               "is_winning_app": True, "application_date": date(2025, 11, 21)}
    assert _rec_is_more_current(later, earlier) is True
    assert _rec_is_more_current(earlier, later) is False


def test_dedup_ignores_new_fields_for_other_carriers():
    # Records without is_winning_app/application_date behave exactly as before:
    # a later effective date still wins; a full tie still returns True (last-in-file).
    a = {"term_date": None, "effective_date": date(2026, 2, 1)}
    b = {"term_date": None, "effective_date": date(2026, 1, 1)}
    assert _rec_is_more_current(a, b) is True
    tie = {"term_date": None, "effective_date": date(2026, 1, 1)}
    assert _rec_is_more_current(dict(tie), dict(tie)) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_devoted_parser.py -k dedup -v`
Expected: the two winning-app tests FAIL (current code returns `True` on any full tie, so `_rec_is_more_current(loser, winner)` wrongly returns True); the "ignores new fields" test passes.

- [ ] **Step 3: Extend the tie-break**

In `app/upload.py`, in `_rec_is_more_current`, replace the final `return True` line (currently line 101, `return True   # full tie -> last-in-file wins (UHC parity)`) with the winning-app tie-break BEFORE the last-in-file fallback:

```python
    # term + effective tie -> prefer the WINNING application (Devoted competing
    # apps share an effective date, so this is the only signal that resolves them).
    # is_winning_app True beats False; then a later application_date wins. Records
    # from carriers that don't set these keys skip straight to last-in-file parity.
    nw = new.get("is_winning_app")
    kw = kept.get("is_winning_app")
    if nw is not None or kw is not None:
        if bool(nw) != bool(kw):
            return bool(nw)                 # winner replaces loser; loser never replaces winner
        na = new.get("application_date")
        ka = kept.get("application_date")
        if na and ka and na != ka:
            return na > ka                  # later-submitted application wins
    return True   # full tie -> last-in-file wins (UHC parity)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_devoted_parser.py -k dedup -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the dedup + upload regression tests**

Run: `python3 -m pytest tests/test_devoted_parser.py tests/test_chronological_dedup.py -q 2>/dev/null || python3 -m pytest tests/test_devoted_parser.py -q`
Expected: all pass (existing chronological-dedup behavior for non-Devoted carriers unchanged — the new branch only fires when `is_winning_app` is present).

- [ ] **Step 6: Commit**

```bash
git add app/upload.py tests/test_devoted_parser.py
git commit -m "feat: winning-app tie-break in BOB dedup (Devoted competing apps)"
```

---

### Task 3: Ambiguous-pair review flag (report, don't guess)

**Files:**
- Modify: `app/upload.py` (`_dedupe_bob_records`, ~line 144-175)
- Test: `tests/test_devoted_parser.py`

**Interfaces:**
- Consumes: the extended `_rec_is_more_current` (Task 2).
- Produces: `_dedupe_bob_records(records)` unchanged in return shape (still returns the deduped list). NEW: when it collapses a same-`(carrier, member_id)` active pair that is genuinely ambiguous — both rows tie on term_date, effective_date, `is_winning_app`, AND `application_date` — it appends a dict to a module-level list `AMBIGUOUS_WINNING_PAIRS` (cleared at the start of each call): `{"carrier", "member_id", "full_name"}`. This is a diagnostic surface for the reconcile report; it does NOT change which row is kept (last-in-file still wins so nothing is dropped).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_devoted_parser.py`:

```python
from app.upload import _dedupe_bob_records, AMBIGUOUS_WINNING_PAIRS
from datetime import date as _d


def test_dedupe_flags_ambiguous_winning_pair():
    # Two active rows, same MBI, same term/eff, SAME winning flag AND SAME app date
    # => unresolvable => flagged for review (but still deduped to one, not dropped).
    recs = [
        {"carrier": "Devoted", "member_id": "9ZZ9ZZ9ZZ99", "full_name": "Ambi Guous",
         "status": "active", "term_date": None, "effective_date": _d(2026, 1, 1),
         "is_winning_app": True, "application_date": _d(2025, 12, 1)},
        {"carrier": "Devoted", "member_id": "9ZZ9ZZ9ZZ99", "full_name": "Ambi Guous",
         "status": "active", "term_date": None, "effective_date": _d(2026, 1, 1),
         "is_winning_app": True, "application_date": _d(2025, 12, 1)},
    ]
    out = _dedupe_bob_records(recs)
    active = [r for r in out if r.get("status") == "active"]
    assert len(active) == 1                          # collapsed, nothing dropped
    assert any(a["member_id"] == "9ZZ9ZZ9ZZ99" for a in AMBIGUOUS_WINNING_PAIRS)


def test_dedupe_resolvable_pair_not_flagged():
    AMBIGUOUS_WINNING_PAIRS.clear()
    recs = [
        {"carrier": "Devoted", "member_id": "8YY8YY8YY88", "full_name": "Clear Winner",
         "status": "active", "term_date": None, "effective_date": _d(2026, 1, 1),
         "is_winning_app": True, "application_date": _d(2025, 12, 5)},
        {"carrier": "Devoted", "member_id": "8YY8YY8YY88", "full_name": "Clear Winner",
         "status": "active", "term_date": None, "effective_date": _d(2026, 1, 1),
         "is_winning_app": False, "application_date": _d(2025, 11, 1)},
    ]
    _dedupe_bob_records(recs)
    assert not any(a["member_id"] == "8YY8YY8YY88" for a in AMBIGUOUS_WINNING_PAIRS)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_devoted_parser.py -k ambiguous_or_resolvable -v` (or `-k "ambiguous or resolvable"`)
Expected: FAIL — `AMBIGUOUS_WINNING_PAIRS` does not exist yet (ImportError).

- [ ] **Step 3: Add the ambiguity flag**

In `app/upload.py`, add a module-level list near the top (after imports):

```python
# Diagnostic: same-MBI active pairs the winning-app tie-break could NOT resolve
# (same flag AND same application_date). Populated by _dedupe_bob_records; read by
# the reconcile report. Cleared at the start of each _dedupe_bob_records call.
AMBIGUOUS_WINNING_PAIRS = []
```

Then in `_dedupe_bob_records`, clear it at the start and detect the ambiguous case when replacing/keeping. The current loop (around line 160-174) is:

```python
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

Replace it with (adds the clear + the ambiguity check; keep-logic otherwise identical):

```python
    AMBIGUOUS_WINNING_PAIRS.clear()
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
            other = out[kept_idx]
            if _winning_pair_is_ambiguous(rec, other):
                AMBIGUOUS_WINNING_PAIRS.append({
                    "carrier": rec.get("carrier"), "member_id": mid,
                    "full_name": rec.get("full_name") or other.get("full_name"),
                })
            if _rec_is_more_current(rec, other):
                out[kept_idx] = rec        # chronologically newer active rec wins its slot
        else:
            seen[key] = len(out)
            out.append(rec)
    return out
```

And add the helper just above `_dedupe_bob_records`:

```python
def _winning_pair_is_ambiguous(a, b):
    """True iff two same-key active recs tie on term + effective date AND both carry
    a winning-app signal that cannot resolve them (same is_winning_app AND same
    application_date). Only meaningful when both carry is_winning_app."""
    if a.get("is_winning_app") is None or b.get("is_winning_app") is None:
        return False
    if (a.get("term_date") or _date.max) != (b.get("term_date") or _date.max):
        return False
    if (a.get("effective_date") or _date.min) != (b.get("effective_date") or _date.min):
        return False
    if bool(a.get("is_winning_app")) != bool(b.get("is_winning_app")):
        return False
    return a.get("application_date") == b.get("application_date")
```

(`_date` is already imported in upload.py — it is used by `_rec_is_more_current`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_devoted_parser.py -k "ambiguous or resolvable" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full devoted + upload suites**

Run: `python3 -m pytest tests/test_devoted_parser.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/upload.py tests/test_devoted_parser.py
git commit -m "feat: flag unresolvable winning-app pairs for review (don't guess)"
```

---

### Task 4: Full-suite verification + real-file smoke check

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `python3 -m pytest -q`
Expected: all pass (prior total + the ~11 new tests).

- [ ] **Step 2: Smoke-parse the REAL file (no DB writes)**

Run:
```bash
python3 -c "
from app.parsers.devoted import parse
from app.upload import _dedupe_bob_records, AMBIGUOUS_WINNING_PAIRS
recs = parse('docs/Carrier BOB DL/July 2026 period/Devoted/Devoted Book of business.xlsx')
print('parsed records:', len(recs))
deduped = _dedupe_bob_records(recs)
active = [r for r in deduped if r.get('status')=='active']
print('active after dedup:', len(active))
print('with real MBI:', sum(1 for r in active if r['mbi'] and r['mbi']==r['member_id']))
print('ambiguous pairs flagged:', len(AMBIGUOUS_WINNING_PAIRS), AMBIGUOUS_WINNING_PAIRS)
# spot-check Peggy + Cynthia survive (lone non-winning)
names = {r['full_name'].lower() for r in active}
print('Peggy Marsh present:', any('marsh' in n and 'peggy' in n for n in names))
print('Cynthia Cauthen present:', any('cauthen' in n for n in names))
"
```
Expected: ~523 active (522 Enrolled + Approved, minus the 6 collapsed losing-app duplicates ≈ 523), every active rec has a real MBI as its member_id, 0 ambiguous pairs (this file's pairs all resolve by flag), Peggy + Cynthia both present.

- [ ] **Step 3: Confirm no synthetic DVND ids leaked**

Run:
```bash
python3 -c "
from app.parsers.devoted import parse
recs = parse('docs/Carrier BOB DL/July 2026 period/Devoted/Devoted Book of business.xlsx')
print('DVND synth ids:', sum(1 for r in recs if str(r.get('member_id','')).startswith('DVND-')))
"
```
Expected: `DVND synth ids: 0`

- [ ] **Step 4: Commit any final note (optional, allow-empty)**

```bash
git commit --allow-empty -m "chore: Devoted rich parser verified against real file"
```

---

## Self-Review

**Spec coverage:**
- Rich column map → Task 1. ✓
- Active-status rule (Enrolled+Approved active, others skip; winning-app NOT a skip filter) → Task 1 (`test_rich_approved_is_active`, `test_rich_other_status_skipped`, `test_rich_lone_non_winning_still_active`). ✓
- commission_type from New-to-MA → Task 1. ✓
- application_date + is_winning_app captured → Task 1. ✓
- Same-MBI resolution precedence (flag → app date → review) → Task 2 (flag, app date) + Task 3 (review flag). ✓
- Detection (Mbi column) → Task 1. ✓
- Lossy path unchanged (regression) → Task 1 (`test_old_lossy_application_status_still_parses`). ✓
- Other carriers unaffected by dedup change → Task 2 (`test_dedup_ignores_new_fields_for_other_carriers`). ✓
- Real-file smoke → Task 4.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has expected output. ✓

**Type consistency:** `_parse_application_status_rich(df)` returns list-of-dict with `is_winning_app: bool` + `application_date: date|None`, consumed identically by `_rec_is_more_current` (Task 2) and `_winning_pair_is_ambiguous`/`_dedupe_bob_records` (Task 3). `AMBIGUOUS_WINNING_PAIRS` defined in Task 3, imported in its tests. `_str`/`_parse_date`/`_split_full_name`/`_date` all pre-exist. ✓

**Note for executor:** This is parser-only — NO DB writes, NO migration, NO deploy in this plan. The reconcile (read-only diff → backup → import → verify) and the cross-carrier switcher pass are the SEPARATE next phase, run after this ships and after opus review. Do the opus whole-branch review before considering the reconcile.
