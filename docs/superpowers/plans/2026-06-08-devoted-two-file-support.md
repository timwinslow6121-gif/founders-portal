# Devoted Two-File Support (R1.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse BOTH Devoted monthly files — the agency book-of-business (`Total/Override/Agent Portion/HRA`, all agents except Rebekah) and Rebekah's per-agent statement (`Summary/Detail/Misc`) — into complete, balanced `CommissionLineItem` + `PolicyPayment` data under one monthly Devoted statement, so every Devoted cent is provable.

**Architecture:** Devoted extraction becomes format-aware: a `_devoted_format(sheets)` detector branches between the existing agency logic and a new statement-format branch (Detail→agent_commission/chargeback reusing the agency column indices; Misc→hra_bonus, or chargeback when negative; Summary ignored). Every Devoted `source_ref` gains a per-file token (`agency` or `npn<NPN>`) so two files coexist under one statement, and the replace-on-reupload delete in `routes.py` becomes file-scoped for Devoted. A negative-Override→chargeback consistency fix is folded in. No new model or migration — `source_ref` is the existing idempotency key.

**Tech Stack:** Python 3.10, Flask-SQLAlchemy, pytest + SQLite in-memory, openpyxl sheets (`{sheet_name: list[list[cell]]}`).

---

## Decisions locked before planning (from the approved spec)

- **No loader change** — the re-downloaded Rebekah `.xlsx` loads fine via existing `load_sheets`. Loader repair dropped.
- **No migration** — `source_ref` already exists on both `CommissionLineItem` and `PolicyPayment`.
- **Summary sheet is NOT extracted** — its "Balance" (−$375.93) is a prior-period carryforward; recording it double-counts. Ledger records current-period facts only (Detail + Misc).
- **classification = label; split_rate drives the math.** Negative Override → `chargeback` with `split_rate=None` (Founders absorbs full clawback). Negative Misc HRA → `chargeback` with the agent's split_rate (split applies). No `split_breakdown` change, no new classification.
- **Filetoken:** agency format → `agency`; statement format → `npn<AgentNPN from Detail col 1>` (e.g. `npn20182775`).
- **Verified column indices** (statement Detail == agency Agent Portion): Agent NPN=1, Agent Name=2, Member ID=3, Member HICN=4, First=5, Last=6, Eff=9, Disenroll=10, Commission Type=15, Base Amount=17. Misc == HRA: Rep=0, Rep ID=1, Amount=2, Note=3.
- **Verified Rebekah fixture money:** Detail 2 renewals @ $28.91 = +$57.82; Misc 8 clawbacks @ −$50 = −$400; current-period net = **−$342.18**.

## File structure

- **Modify** `app/commission/ledger.py` — add `_devoted_format`, `_devoted_filetoken`; make `extract_lineitems_devoted` + `money_rows_total_devoted` format-aware; file-token all Devoted `source_ref`s; negative-override→chargeback fix.
- **Modify** `app/commission/normalizers.py` — make `normalize_devoted` format-aware (statement branch → Detail MemberFacts + Misc NON_CUSTOMER facts); file-token its `source_ref`s.
- **Modify** `app/commission/routes.py` — file-scoped replace-on-reupload for Devoted (both `PolicyPayment` + `CommissionLineItem`).
- **Create** `tests/fixtures/commission/devoted_statement_sample.xlsx` — synthetic `Summary/Detail/Misc` fixture (built by a one-shot generator script committed alongside).
- **Create** `scripts/make_devoted_statement_fixture.py` — generates that fixture (kept for reproducibility, like a one-time script).
- **Modify** `tests/test_commission_ledger.py` — format detection, statement extractor, negative-override fix, filetoken, coexistence/file-scoped replace.
- **Modify** `tests/fixtures/commission/README.md` — document the new fixture.

---

### Task 1: Synthetic statement-format fixture

The Rebekah real file lives in `docs/` with real member data and is not a test fixture. Tests need a sanitized `Summary/Detail/Misc` fixture that reproduces the exact column layout and the verified totals (+$57.82 Detail, −$400 Misc).

**Files:**
- Create: `scripts/make_devoted_statement_fixture.py`
- Create (generated): `tests/fixtures/commission/devoted_statement_sample.xlsx`
- Modify: `tests/fixtures/commission/README.md`

- [ ] **Step 1: Write the generator script**

Create `scripts/make_devoted_statement_fixture.py`:

```python
"""
scripts/make_devoted_statement_fixture.py

One-shot generator for tests/fixtures/commission/devoted_statement_sample.xlsx —
a sanitized copy of Devoted's per-agent STATEMENT format (Summary/Detail/Misc),
matching the real 20182775_Rebekah_Long file's column layout and totals.

Run: python3 scripts/make_devoted_statement_fixture.py
"""
import os
import openpyxl

OUT = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures",
                   "commission", "devoted_statement_sample.xlsx")

DETAIL_HEADER = ["Statement Date", "Agent NPN", "Agent Name", "Member ID",
                 "Member HICN", "Member First", "Member Last", "Member State",
                 "Signature Date", "Effective Date", "Disenroll Date", "Contract",
                 "PBP", "Prior Plan Type", "CMS Cycle Year", "Commission Type",
                 "Period", "Base Amount", "Admin Amount", "Total Payment", "FMO",
                 "Payment Notations"]


def _detail_row(member_id, hicn, first, last, base):
    return ["05/29/2026", "20182775", "Rebekah Long", member_id, hicn, first, last,
            "NC", "11/06/2025", "12/01/2025", "", "H9700", "2", "NONE", "2",
            "Renewal - Monthly", "May", base, 0, base, "Tidewater Management", ""]


def main():
    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "Summary"
    for row in [
        ["Description", "Member Count", "Total", "", "Payee", "Payment Date"],
        ["Credits", 2, "$57.82", "", "Rebekah Long", "05/29/2026"],
        ["Debits", 0, "$0.00", "", "", ""],
        ["Miscellaneous", 8, "($400.00)", "", "", ""],
        ["Bonus", "", "$0.00", "", "", ""],
        ["Sub Total", 10, "($718.11)", "", "", ""],
        ["Balance", "", "($375.93)", "", "", ""],
        ["TOTAL", "", "($718.11)", "", "", ""],
    ]:
        ws.append(row)

    det = wb.create_sheet("Detail")
    det.append(DETAIL_HEADER)
    det.append(_detail_row("DAH887", "7QY9GM5CA40", "MICHELLE", "BROADWAY", 28.91))
    det.append(_detail_row("DAUU67", "6VT3RT2FM11", "BOBBY", "SMITH", 28.91))

    misc = wb.create_sheet("Misc")
    misc.append(["Rep Name", "Rep ID", "Amount", "Note"])
    for note in ["Debra", "James", "Sarah", "DAVID", "DONNA", "Mark", "RITA", "Charlie"]:
        misc.append(["Rebekah Long", "20182775", "($50.00)", f"HRA for member {note}"])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    wb.save(OUT)
    print("wrote", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate the fixture**

Run: `python3 scripts/make_devoted_statement_fixture.py`
Expected: prints `wrote .../tests/fixtures/commission/devoted_statement_sample.xlsx`

- [ ] **Step 3: Verify the fixture loads with the expected shape**

Run:
```bash
python3 -c "
from app.commission.sheet_loader import load_sheets
s = load_sheets('tests/fixtures/commission/devoted_statement_sample.xlsx')
print('sheets:', list(s))
print('detail rows:', len(s['Detail']))
print('misc rows:', len(s['Misc']))
"
```
Expected: `sheets: ['Summary', 'Detail', 'Misc']`, `detail rows: 3` (header + 2), `misc rows: 9` (header + 8).

- [ ] **Step 4: Document the fixture in README**

In `tests/fixtures/commission/README.md`, after the `devoted_sample.xlsx` line, add:

```markdown
- devoted_statement_sample.xlsx — Devoted per-agent STATEMENT format (Summary/Detail/Misc); synthetic, sanitized copy of 20182775_Rebekah_Long. Detail=2 renewals (+$57.82), Misc=8 HRA clawbacks (−$400); Summary carries a prior-period carryforward (Balance −$375.93). Built by scripts/make_devoted_statement_fixture.py.
```

- [ ] **Step 5: Commit**

```bash
git add scripts/make_devoted_statement_fixture.py tests/fixtures/commission/devoted_statement_sample.xlsx tests/fixtures/commission/README.md
git commit -m "test(devoted): synthetic statement-format fixture (Summary/Detail/Misc)"
```

---

### Task 2: `_devoted_format` detector

**Files:**
- Modify: `app/commission/ledger.py` (add helper near `_devoted_sheet_rows`, ~line 219)
- Test: `tests/test_commission_ledger.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_commission_ledger.py`:

```python
def test_devoted_format_detection():
    from app.commission.ledger import _devoted_format
    agency = _load_fixture("devoted_sample.xlsx")
    statement = _load_fixture("devoted_statement_sample.xlsx")
    assert _devoted_format(agency) == "agency"
    assert _devoted_format(statement) == "statement"


def test_devoted_format_unknown_raises():
    import pytest
    from app.commission.ledger import _devoted_format
    with pytest.raises(ValueError):
        _devoted_format({"Bogus": [["x"]]})
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_commission_ledger.py -k devoted_format -v`
Expected: FAIL — `cannot import name '_devoted_format'`

- [ ] **Step 3: Implement the detector**

In `app/commission/ledger.py`, immediately after the `_devoted_sheet_rows` function (~line 220), add:

```python
def _devoted_format(sheets):
    """Devoted ships two file shapes. Detect which by sheet names:
      - "agency"    : the agency book-of-business (Total/Override/Agent Portion/HRA)
      - "statement" : a per-agent statement (Summary/Detail/Misc)
    Raises ValueError on an unrecognized shape (fail loud, never silently 0 rows)."""
    if "Agent Portion" in sheets:
        return "agency"
    if "Detail" in sheets and "Misc" in sheets:
        return "statement"
    raise ValueError(
        f"Unrecognized Devoted file shape; sheets={list(sheets)}. "
        "Expected agency (Agent Portion) or statement (Detail+Misc).")
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_commission_ledger.py -k devoted_format -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/commission/ledger.py tests/test_commission_ledger.py
git commit -m "feat(devoted): format detector (agency vs statement)"
```

---

### Task 3: `_devoted_filetoken` + file-tag agency source_refs

This task introduces the filetoken and applies it to the **existing agency** extractor's `source_ref`s (the statement branch comes in Task 4). It also folds in the negative-Override→chargeback fix.

**Files:**
- Modify: `app/commission/ledger.py` (`_devoted_filetoken`, agency `source_ref`s ~lines 240/263/283, Override classification ~lines 252-272)
- Test: `tests/test_commission_ledger.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_commission_ledger.py`:

```python
def test_devoted_filetoken():
    from app.commission.ledger import _devoted_filetoken
    agency = _load_fixture("devoted_sample.xlsx")
    statement = _load_fixture("devoted_statement_sample.xlsx")
    assert _devoted_filetoken(agency) == "agency"
    assert _devoted_filetoken(statement) == "npn20182775"


def test_devoted_agency_source_refs_are_file_tagged():
    from app.commission.ledger import extract_lineitems_devoted
    sheets = _load_fixture("devoted_sample.xlsx")
    drafts = extract_lineitems_devoted(sheets, split_lookup=lambda raw: 0.55)
    assert drafts
    assert all(d.source_ref.startswith("devoted::agency::") for d in drafts)


def test_devoted_negative_override_is_chargeback_with_null_split():
    from app.commission.ledger import extract_lineitems_devoted, CHARGEBACK, FOUNDERS_OVERRIDE
    sheets = _load_fixture("devoted_sample.xlsx")
    drafts = extract_lineitems_devoted(sheets, split_lookup=lambda raw: 0.55)
    override_rows = [d for d in drafts if "::Override::" in d.source_ref]
    assert override_rows
    for d in override_rows:
        if d.raw_amount < 0:
            assert d.classification == CHARGEBACK
            assert d.split_rate is None
        else:
            assert d.classification == FOUNDERS_OVERRIDE
            assert d.split_rate is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_commission_ledger.py -k "filetoken or file_tagged or negative_override" -v`
Expected: FAIL — `cannot import name '_devoted_filetoken'` (and the source_ref / override assertions fail).

- [ ] **Step 3: Implement filetoken + retag agency source_refs + override fix**

In `app/commission/ledger.py`, add after `_devoted_format`:

```python
def _devoted_filetoken(sheets):
    """Stable per-file token so the two Devoted files coexist under one statement.
      - agency    → "agency"
      - statement → "npn" + the Agent NPN from the Detail sheet (col 1)
    """
    fmt = _devoted_format(sheets)
    if fmt == "agency":
        return "agency"
    detail = sheets.get("Detail", [])
    npn = ""
    for row in detail[1:]:
        if any(row) and len(row) > 1:
            npn = str(row[1] or "").strip()
            if npn:
                break
    return f"npn{npn}" if npn else "npn_unknown"
```

Then in `extract_lineitems_devoted`, change the three agency `source_ref` lines:
- `f"devoted::Agent Portion::{idx}"` → `f"devoted::agency::Agent Portion::{idx}"`
- `f"devoted::Override::{idx}"` → `f"devoted::agency::Override::{idx}"`
- `f"devoted::HRA::{idx}"` → `f"devoted::agency::HRA::{idx}"`

And replace the entire Override loop body (the block that currently builds a `FOUNDERS_OVERRIDE` draft, ~lines 252-272) with this version that classifies negatives as chargebacks:

```python
    # Override → founders_override (positive) / chargeback (negative clawback).
    # Either way no agent split: split_rate=None means Founders keeps/absorbs all.
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "Override")[1:], start=1):
        if not any(row) or len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::agency::Override::{idx}",
            raw_amount=amount,
            classification=CHARGEBACK if amount < 0 else FOUNDERS_OVERRIDE,
            split_rate=None,
            payment_type="override",
            member_name=f"{first} {last}".strip(),
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            writing_agent_raw=str(row[2] or "").strip(),
        ))
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_commission_ledger.py -k "filetoken or file_tagged or negative_override" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the existing Devoted balance test (no regression from retag)**

Run: `python3 -m pytest tests/test_commission_ledger.py -k devoted -v`
Expected: all PASS — including `test_devoted_produces_override_agent_and_hra` and the parametrized balance (the retag/override-fix don't change totals, only labels + source_ref strings).

- [ ] **Step 6: Commit**

```bash
git add app/commission/ledger.py tests/test_commission_ledger.py
git commit -m "feat(devoted): file-token agency source_refs + negative-override→chargeback"
```

---

### Task 4: Statement-format branch in the ledger extractor

Make `extract_lineitems_devoted` and `money_rows_total_devoted` handle the `statement` format.

**Files:**
- Modify: `app/commission/ledger.py` (`extract_lineitems_devoted`, `money_rows_total_devoted`)
- Test: `tests/test_commission_ledger.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_commission_ledger.py`:

```python
def test_devoted_statement_extracts_detail_and_misc():
    from app.commission.ledger import (extract_lineitems_devoted, AGENT_COMMISSION,
                                        CHARGEBACK, HRA_BONUS)
    sheets = _load_fixture("devoted_statement_sample.xlsx")
    drafts = extract_lineitems_devoted(sheets, split_lookup=lambda raw: 0.55)

    detail = [d for d in drafts if "::Detail::" in d.source_ref]
    misc = [d for d in drafts if "::Misc::" in d.source_ref]
    # 2 Detail renewals, 8 Misc clawbacks; Summary not extracted.
    assert len(detail) == 2
    assert len(misc) == 8
    assert all(d.classification == AGENT_COMMISSION for d in detail)
    assert all(d.classification == CHARGEBACK for d in misc)   # negative HRA
    # statement source_refs carry the npn filetoken
    assert all(d.source_ref.startswith("devoted::npn20182775::") for d in drafts)
    # No line item for the Summary carryforward.
    assert not any("Summary" in d.source_ref for d in drafts)
    # current-period net = +57.82 - 400 = -342.18
    assert round(sum(d.raw_amount for d in drafts), 2) == -342.18


def test_devoted_statement_misc_positive_is_hra_bonus():
    # Guard the sign branch: a positive Misc amount → hra_bonus (split applies).
    from app.commission.ledger import _extract_devoted_statement, HRA_BONUS
    sheets = {
        "Summary": [["Description"]],
        "Detail": [["Statement Date", "Agent NPN"], ["05/29/2026", "20182775"]],
        "Misc": [["Rep Name", "Rep ID", "Amount", "Note"],
                 ["Rebekah Long", "20182775", "$50.00", "HRA for member X"]],
    }
    drafts = _extract_devoted_statement(sheets, "npn20182775", lambda raw: 0.55)
    misc = [d for d in drafts if "::Misc::" in d.source_ref]
    assert len(misc) == 1
    assert misc[0].classification == HRA_BONUS
    assert misc[0].split_rate == 0.55


def test_devoted_statement_money_rows_total():
    from app.commission.ledger import money_rows_total_devoted
    sheets = _load_fixture("devoted_statement_sample.xlsx")
    assert round(money_rows_total_devoted(sheets), 2) == -342.18
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_commission_ledger.py -k "devoted_statement" -v`
Expected: FAIL — `cannot import name '_extract_devoted_statement'` / statement drafts not produced.

- [ ] **Step 3: Implement the statement branch**

In `app/commission/ledger.py`:

First, extract the existing agency body into a helper and add the statement helper. Rename the current `extract_lineitems_devoted` body into `_extract_devoted_agency(sheets, filetoken, split_lookup)` (it already uses `devoted::agency::` source_refs from Task 3 — make `filetoken` a param but agency always passes `"agency"`). Concretely, restructure so the module has:

```python
def _extract_devoted_agency(sheets, filetoken, split_lookup) -> List[LineItemDraft]:
    out = []
    # Agent Portion → agent_commission / chargeback
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "Agent Portion")[1:], start=1):
        if not any(row) or len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        disen = _parse_date(row[10])
        classification = CHARGEBACK if (amount < 0 or disen) else AGENT_COMMISSION
        writing = str(row[2] or "").strip()
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::{filetoken}::Agent Portion::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=str(row[15] or "").strip().lower() or None,
            member_name=f"{first} {last}".strip(),
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[9]),
            term_date=disen,
        ))
    # Override → founders_override (positive) / chargeback (negative); never split.
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "Override")[1:], start=1):
        if not any(row) or len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::{filetoken}::Override::{idx}",
            raw_amount=amount,
            classification=CHARGEBACK if amount < 0 else FOUNDERS_OVERRIDE,
            split_rate=None,
            payment_type="override",
            member_name=f"{first} {last}".strip(),
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            writing_agent_raw=str(row[2] or "").strip(),
        ))
    # HRA → hra_bonus (split applies)
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "HRA")[1:], start=1):
        if not any(row) or len(row) <= 3:
            continue
        rep = str(row[0] or "").strip()
        amt = _to_float(row[2])
        if not rep or amt == 0:
            continue
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::{filetoken}::HRA::{idx}",
            raw_amount=amt,
            classification=HRA_BONUS,
            split_rate=split_lookup(rep),
            payment_type="hra",
            member_name=str(row[3] or "").strip() or "HRA Bonus",
            writing_agent_raw=rep,
        ))
    return out


def _extract_devoted_statement(sheets, filetoken, split_lookup) -> List[LineItemDraft]:
    """Rebekah per-agent statement: Detail (member commissions) + Misc (HRA, often
    clawbacks). Summary is NOT extracted (its Balance is a prior-period carryforward
    that would double-count). Detail columns match the agency Agent Portion layout."""
    out = []
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "Detail")[1:], start=1):
        if not any(row) or len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        disen = _parse_date(row[10])
        classification = CHARGEBACK if (amount < 0 or disen) else AGENT_COMMISSION
        writing = str(row[2] or "").strip()
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::{filetoken}::Detail::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=str(row[15] or "").strip().lower() or None,
            member_name=f"{first} {last}".strip(),
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[9]),
            term_date=disen,
        ))
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "Misc")[1:], start=1):
        if not any(row) or len(row) <= 3:
            continue
        rep = str(row[0] or "").strip()
        amt = _to_float(row[2])
        if not rep or amt == 0:
            continue
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::{filetoken}::Misc::{idx}",
            raw_amount=amt,
            classification=CHARGEBACK if amt < 0 else HRA_BONUS,
            split_rate=split_lookup(rep),
            payment_type="hra",
            member_name=str(row[3] or "").strip() or "HRA",
            writing_agent_raw=rep,
        ))
    return out


def extract_lineitems_devoted(sheets, split_lookup) -> List[LineItemDraft]:
    fmt = _devoted_format(sheets)
    filetoken = _devoted_filetoken(sheets)
    if fmt == "statement":
        return _extract_devoted_statement(sheets, filetoken, split_lookup)
    return _extract_devoted_agency(sheets, filetoken, split_lookup)
```

Then update `money_rows_total_devoted` to be format-aware:

```python
def money_rows_total_devoted(sheets) -> float:
    fmt = _devoted_format(sheets)
    total = 0.0
    if fmt == "statement":
        for row in _devoted_sheet_rows(sheets, "Detail")[1:]:
            if not any(row) or len(row) <= 17 or not str(row[3] or "").strip():
                continue
            total += _to_float(row[17])
        for row in _devoted_sheet_rows(sheets, "Misc")[1:]:
            if not any(row) or len(row) <= 3:
                continue
            if not str(row[0] or "").strip() or _to_float(row[2]) == 0:
                continue
            total += _to_float(row[2])
        return total
    for row in _devoted_sheet_rows(sheets, "Agent Portion")[1:]:
        if not any(row) or len(row) <= 17 or not str(row[3] or "").strip():
            continue
        total += _to_float(row[17])
    for row in _devoted_sheet_rows(sheets, "Override")[1:]:
        if not any(row) or len(row) <= 17 or not str(row[3] or "").strip():
            continue
        total += _to_float(row[17])
    for row in _devoted_sheet_rows(sheets, "HRA")[1:]:
        if not any(row) or len(row) <= 3:
            continue
        if not str(row[0] or "").strip() or _to_float(row[2]) == 0:
            continue
        total += _to_float(row[2])
    return total
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_commission_ledger.py -k "devoted" -v`
Expected: PASS — new statement tests AND all prior agency/balance tests (agency behavior unchanged; only refactored into `_extract_devoted_agency`).

- [ ] **Step 5: Verify statement file balances internally**

Run:
```bash
python3 -c "
from app.commission.ledger import EXTRACTORS, verify_statement_balance
from app.commission.sheet_loader import load_sheets
s = load_sheets('tests/fixtures/commission/devoted_statement_sample.xlsx')
ext,_ = EXTRACTORS['Devoted']
d = ext(s, split_lookup=lambda raw: 0.55)
r = verify_statement_balance('Devoted', d, s)
print(r)
assert r.internal_ok and r.completeness_ok
print('OK: statement balances, total', r.lineitem_total)
"
```
Expected: `internal_ok=True completeness_ok=True`, total `-342.18`.

- [ ] **Step 6: Commit**

```bash
git add app/commission/ledger.py tests/test_commission_ledger.py
git commit -m "feat(devoted): statement-format ledger extractor (Detail+Misc, Summary ignored)"
```

---

### Task 5: Statement-format branch in the customer-sync normalizer

Keep `PolicyPayment` in sync: `normalize_devoted` must handle the statement format and file-token its `source_ref`s.

**Files:**
- Modify: `app/commission/normalizers.py` (`normalize_devoted` + its `source_ref`s)
- Test: `tests/test_commission_normalizers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_normalizers.py`:

```python
def test_normalize_devoted_statement_format():
    import os
    from app.commission.normalizers import normalize_devoted
    from app.commission.member_fact import RowClass
    FIX = os.path.join(os.path.dirname(__file__), "fixtures", "commission")
    from app.commission.sheet_loader import load_sheets
    sheets = load_sheets(os.path.join(FIX, "devoted_statement_sample.xlsx"))
    facts = normalize_devoted(sheets)

    # 2 Detail member renewals + 8 Misc HRA (NON_CUSTOMER) rows
    detail = [f for f in facts if f.row_class in (RowClass.RENEWAL, RowClass.ENROLLMENT, RowClass.CHARGEBACK)
              and f.carrier_member_id]
    hra = [f for f in facts if f.row_class == RowClass.NON_CUSTOMER]
    assert len(detail) == 2
    assert len(hra) == 8
    # all source_refs are file-tagged with the npn token
    assert all(f.source_ref.startswith("devoted::npn20182775::") for f in facts)
    # negative HRA flagged as a negative amount (chargeback semantics downstream)
    assert all(f.amount < 0 for f in hra)


def test_normalize_devoted_agency_source_refs_file_tagged():
    import os
    from app.commission.normalizers import normalize_devoted
    from app.commission.sheet_loader import load_sheets
    FIX = os.path.join(os.path.dirname(__file__), "fixtures", "commission")
    sheets = load_sheets(os.path.join(FIX, "devoted_sample.xlsx"))
    facts = normalize_devoted(sheets)
    assert facts
    assert all(f.source_ref.startswith("devoted::agency::") for f in facts)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k "devoted_statement or agency_source_refs" -v`
Expected: FAIL — statement facts not produced / source_refs not tagged.

- [ ] **Step 3: Implement format-aware `normalize_devoted`**

In `app/commission/normalizers.py`, add a `_devoted_format` + `_devoted_filetoken` (import from ledger to avoid duplication) and branch. At the top of `normalizers.py`, add:

```python
from app.commission.ledger import _devoted_format, _devoted_filetoken
```

Then restructure `normalize_devoted`. Keep the existing agency body but (a) wrap it so it only runs for the agency format, (b) file-tag its source_refs with `devoted::agency::`, and (c) add a statement branch. Replace the `normalize_devoted` function with:

```python
def normalize_devoted(sheets):
    fmt = _devoted_format(sheets)
    filetoken = _devoted_filetoken(sheets)
    if fmt == "statement":
        return _normalize_devoted_statement(sheets, filetoken)
    return _normalize_devoted_agency(sheets, filetoken)


def _normalize_devoted_agency(sheets, filetoken):
    facts = {}        # member_id -> MemberFact (from Agent Portion)
    agency = {}       # member_id -> Override admin amount

    for idx, row in enumerate(sheets.get("Agent Portion", [])[1:], start=1):
        if not any(row):
            continue
        if len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        disen = _parse_date(row[10])
        facts[member_id] = MemberFact(
            carrier="Devoted",
            full_name=f"{first} {last}".strip(),
            first_name=first,
            last_name=last,
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            effective_date=_parse_date(row[9]),
            term_date=disen,
            plan_contract=str(row[11] or "").strip() or None,
            plan_pbp=str(row[12] or "").strip() or None,
            row_class=_classify_devoted(row[15], amount, disen),
            amount=amount,
            writing_agent_raw=str(row[2] or "").strip(),
            source_ref=f"devoted::{filetoken}::Agent Portion::{idx}",
        )

    for idx, row in enumerate(sheets.get("Override", [])[1:], start=1):
        if not any(row):
            continue
        if len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if member_id:
            agency[member_id] = _to_float(row[17])

    for mid, fact in facts.items():
        fact.agency_share_amount = agency.get(mid)

    out = list(facts.values())

    for idx, row in enumerate(sheets.get("HRA", [])[1:], start=1):
        if not any(row):
            continue
        if len(row) <= 3:
            continue
        rep = str(row[0] or "").strip()
        amt = _to_float(row[2])
        if not rep or amt == 0:
            continue
        out.append(MemberFact(
            carrier="Devoted",
            full_name=str(row[3] or "").strip() or "HRA Bonus",
            row_class=RowClass.NON_CUSTOMER,
            amount=amt,
            writing_agent_raw=rep,
            source_ref=f"devoted::{filetoken}::HRA::{idx}",
        ))
    return out


def _normalize_devoted_statement(sheets, filetoken):
    """Rebekah per-agent statement → MemberFacts. Detail rows are member
    commissions; Misc rows are HRA (NON_CUSTOMER, often negative clawbacks).
    Summary is ignored (prior-period carryforward)."""
    out = []
    for idx, row in enumerate(sheets.get("Detail", [])[1:], start=1):
        if not any(row) or len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        disen = _parse_date(row[10])
        out.append(MemberFact(
            carrier="Devoted",
            full_name=f"{first} {last}".strip(),
            first_name=first,
            last_name=last,
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            effective_date=_parse_date(row[9]),
            term_date=disen,
            plan_contract=str(row[11] or "").strip() or None,
            plan_pbp=str(row[12] or "").strip() or None,
            row_class=_classify_devoted(row[15], amount, disen),
            amount=amount,
            writing_agent_raw=str(row[2] or "").strip(),
            source_ref=f"devoted::{filetoken}::Detail::{idx}",
        ))
    for idx, row in enumerate(sheets.get("Misc", [])[1:], start=1):
        if not any(row) or len(row) <= 3:
            continue
        rep = str(row[0] or "").strip()
        amt = _to_float(row[2])
        if not rep or amt == 0:
            continue
        out.append(MemberFact(
            carrier="Devoted",
            full_name=str(row[3] or "").strip() or "HRA",
            row_class=RowClass.NON_CUSTOMER,
            amount=amt,
            writing_agent_raw=rep,
            source_ref=f"devoted::{filetoken}::Misc::{idx}",
        ))
    return out
```

Note: there must be no circular import — `ledger.py` does not import `normalizers.py` (verify: `grep -n "import normalizers" app/commission/ledger.py` returns nothing). `normalizers.py` importing from `ledger.py` is safe.

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k "devoted" -v`
Expected: PASS — new statement + agency-tag tests AND existing `test_normalize_devoted_collapses_paired_rows` (agency behavior unchanged except the source_ref prefix; if that existing test asserts an exact old source_ref string like `devoted::Agent Portion::N`, update it to `devoted::agency::Agent Portion::N`).

- [ ] **Step 5: Commit**

```bash
git add app/commission/normalizers.py tests/test_commission_normalizers.py
git commit -m "feat(devoted): statement-format normalizer + file-tagged source_refs"
```

---

### Task 6: File-scoped replace-on-reupload in routes.py

Make the replace cleanup delete only the uploaded Devoted file's rows, so the two files coexist.

**Files:**
- Modify: `app/commission/routes.py` (`_ingest_normalized_upload`, replace block ~lines 884-891)
- Test: `tests/test_commission_ledger.py` (DB-backed coexistence test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_ledger.py`:

```python
def test_devoted_two_files_coexist_and_file_scoped_replace(db_session, agency):
    """Persist agency line items, then statement line items, under ONE statement.
    Both coexist. Re-persisting the statement file replaces only its rows."""
    from app.models import CommissionLineItem, CommissionStatement
    from app.commission.ledger import (extract_lineitems_devoted, persist_line_items,
                                        _devoted_filetoken)
    from app.extensions import db
    from datetime import date

    stmt = CommissionStatement(agency_id=agency.id, carrier="Devoted", agent_id=None,
                               period_label="April 2026", filename="d.xlsx",
                               statement_date=date(2026, 4, 1))
    db.session.add(stmt)
    db.session.flush()

    agency_sheets = _load_fixture("devoted_sample.xlsx")
    stmt_sheets = _load_fixture("devoted_statement_sample.xlsx")

    a_drafts = extract_lineitems_devoted(agency_sheets, split_lookup=lambda raw: 0.55)
    s_drafts = extract_lineitems_devoted(stmt_sheets, split_lookup=lambda raw: 0.55)

    persist_line_items("Devoted", a_drafts, stmt, agency.id)
    persist_line_items("Devoted", s_drafts, stmt, agency.id)
    db.session.flush()

    total = CommissionLineItem.query.filter_by(statement_id=stmt.id).count()
    assert total == len(a_drafts) + len(s_drafts)   # both files coexist

    # File-scoped delete of just the statement file's rows, then re-persist.
    token = _devoted_filetoken(stmt_sheets)          # "npn20182775"
    (CommissionLineItem.query
        .filter(CommissionLineItem.statement_id == stmt.id,
                CommissionLineItem.source_ref.like(f"devoted::{token}::%"))
        .delete(synchronize_session=False))
    db.session.flush()
    assert CommissionLineItem.query.filter_by(statement_id=stmt.id).count() == len(a_drafts)

    persist_line_items("Devoted", s_drafts, stmt, agency.id)
    db.session.flush()
    assert CommissionLineItem.query.filter_by(statement_id=stmt.id).count() == len(a_drafts) + len(s_drafts)
```

- [ ] **Step 2: Run to verify it passes at the model level**

Run: `python3 -m pytest tests/test_commission_ledger.py -k two_files_coexist -v`
Expected: PASS already (this test exercises the file-token + LIKE-scoped delete directly; it proves the data model supports coexistence). If it FAILS, the source_ref tokens from Task 3/4 are wrong — fix those before proceeding.

- [ ] **Step 3: Wire file-scoped replace into the upload path**

In `app/commission/routes.py`, the replace block currently reads (~lines 884-891):

```python
    if existing:
        PolicyPayment.query.filter_by(
            statement_id=stmt.id, agency_id=current_user.agency_id
        ).delete(synchronize_session=False)
        CommissionLineItem.query.filter_by(
            statement_id=stmt.id, agency_id=current_user.agency_id
        ).delete(synchronize_session=False)
        db.session.flush()
```

Replace it with a version that scopes the delete to the uploaded Devoted file when the carrier is Devoted:

```python
    if existing:
        # Default: blanket replace of the statement's rows (single-file carriers).
        # Devoted ships two files per month under one statement — scope the delete
        # to JUST the uploaded file's rows (by source_ref filetoken) so the other
        # file's line items survive a re-upload.
        pp_q = PolicyPayment.query.filter_by(
            statement_id=stmt.id, agency_id=current_user.agency_id)
        li_q = CommissionLineItem.query.filter_by(
            statement_id=stmt.id, agency_id=current_user.agency_id)
        if carrier == "Devoted":
            from app.commission.ledger import _devoted_filetoken
            token = _devoted_filetoken(sheets)
            prefix = f"devoted::{token}::%"
            pp_q = pp_q.filter(PolicyPayment.source_ref.like(prefix))
            li_q = li_q.filter(CommissionLineItem.source_ref.like(prefix))
        pp_q.delete(synchronize_session=False)
        li_q.delete(synchronize_session=False)
        db.session.flush()
```

- [ ] **Step 4: Run the full ledger + normalizer + ingest suites**

Run: `python3 -m pytest tests/test_commission_ledger.py tests/test_commission_normalizers.py tests/test_commission_ingest.py -v 2>&1 | tail -20`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/commission/routes.py tests/test_commission_ledger.py
git commit -m "feat(devoted): file-scoped replace-on-reupload (two files coexist)"
```

---

### Task 7: Full regression + end-to-end balance verification

**Files:**
- Test: `tests/test_commission_ledger.py`

- [ ] **Step 1: Add an end-to-end "both files, one statement, balanced" assertion**

Append to `tests/test_commission_ledger.py`:

```python
def test_devoted_both_files_each_balance_independently():
    from app.commission.ledger import EXTRACTORS, verify_statement_balance
    ext, _ = EXTRACTORS["Devoted"]
    for fixture, expected in [("devoted_sample.xlsx", None),
                              ("devoted_statement_sample.xlsx", -342.18)]:
        sheets = _load_fixture(fixture)
        drafts = ext(sheets, split_lookup=lambda raw: 0.55)
        report = verify_statement_balance("Devoted", drafts, sheets)
        assert report.internal_ok, report
        assert report.completeness_ok, report
        if expected is not None:
            assert round(report.lineitem_total, 2) == expected
```

- [ ] **Step 2: Run it**

Run: `python3 -m pytest tests/test_commission_ledger.py::test_devoted_both_files_each_balance_independently -v`
Expected: PASS.

- [ ] **Step 3: Run the ENTIRE suite (no regressions)**

Run: `python3 -m pytest -q 2>&1 | tail -3`
Expected: all pass (153 from R1 + the new Devoted tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_commission_ledger.py
git commit -m "test(devoted): both-file independent balance assertion"
```

---

### Task 8: Docs — spec status + CLAUDE.md + memory pointer

**Files:**
- Modify: `docs/superpowers/specs/2026-06-08-devoted-two-file-design.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Mark the spec delivered**

At the top of the spec, change the Status line to:

```markdown
**Status:** ✅ Implemented (on `feat/devoted-two-file`)
```

- [ ] **Step 2: Update CLAUDE.md**

In `CLAUDE.md`, in the R1 build-status entry, replace the "KNOWN LIMITATION (deferred to R2/R3): Devoted ships 2 files/month …" sentence with:

```markdown
Devoted two-file support ✅ (R1.1, 2026-06-08): the agency book-of-business (Total/Override/Agent Portion/HRA) and Rebekah's per-agent statement (Summary/Detail/Misc) now both parse into one monthly Devoted statement — format-detected by sheet names, file-scoped `source_ref` (`devoted::agency::…` / `devoted::npn<NPN>::…`) so the two files coexist and re-uploading one replaces only its rows. Statement Summary carryforward is excluded (current-period only). Negative Devoted overrides reclassified chargeback (split_rate NULL).
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-06-08-devoted-two-file-design.md CLAUDE.md
git commit -m "docs(devoted): mark two-file support delivered; update CLAUDE.md"
```

---

## Deployment (after merge)

Pure code — no migration. Standard VPS deploy:

```bash
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100
cd /var/www/founders-portal && git pull \
  && ./venv/bin/pip install -r requirements.txt \
  && systemctl restart founders-portal
```

Then AJ re-uploads BOTH Devoted files for the period (agency file + Rebekah statement). Verify both coexist:
```sql
SELECT split_part(source_ref,'::',2) AS filetoken, count(*), round(sum(raw_amount)::numeric,2)
FROM commission_line_items WHERE carrier='Devoted' GROUP BY 1;
```
Expected: an `agency` row and an `npn20182775` row.

**Note:** before re-uploading, the existing Devoted statement #41 (from the 2026-06-08 single-file upload) has old un-tagged source_refs (`devoted::Agent Portion::N`). Re-uploading the agency file writes new `devoted::agency::…` rows but the file-scoped delete (`LIKE 'devoted::agency::%'`) won't match the old un-tagged rows, leaving stale duplicates. One-time cleanup: delete the pre-R1.1 Devoted line items for that statement first, e.g. `DELETE FROM commission_line_items WHERE carrier='Devoted' AND source_ref NOT LIKE 'devoted::%::%::%';` (matches only the old 3-part refs, not the new 4-part). Run this once on the VPS before the first post-R1.1 Devoted re-upload.

---

## Self-review notes (done while writing)

- **Spec coverage:** Component 1 detection → Task 2; Component 2 statement extractor → Task 4 (ledger) + Task 5 (normalizer); Component 3 negative-override fix → Task 3; Component 4 filetoken + file-scoped replace → Task 3 (token + agency tags), Task 4 (statement tags), Task 6 (routes). Fixture → Task 1. Tests → every task + Task 7. Docs → Task 8. ✅
- **Naming consistency:** `_devoted_format`, `_devoted_filetoken`, `_extract_devoted_agency`, `_extract_devoted_statement`, `_normalize_devoted_agency`, `_normalize_devoted_statement` used identically across tasks. source_ref scheme `devoted::<filetoken>::<sheet>::<idx>` consistent everywhere (ledger + normalizer + routes delete).
- **Carryforward excluded:** Summary never read in either statement branch; money_rows_total statement = Detail+Misc only. ✅
- **Existing-test impact flagged:** the agency source_ref retag (Task 3/4) changes `devoted::Agent Portion::N` → `devoted::agency::Agent Portion::N`; Tasks 3/5 note any existing test asserting the old string must be updated. ✅
- **No circular import:** normalizers imports from ledger (one direction); ledger does not import normalizers. Step in Task 5 verifies. ✅
- **Migration:** none (source_ref reused). ✅
- **Real-data caveat:** statement column indices verified identical to agency Agent Portion against the real re-downloaded file; the synthetic fixture reproduces them exactly. The deploy note handles the pre-R1.1 stale-row cleanup.
