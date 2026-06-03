# Commission Sync — Plan 1: MemberFact + Clean-Split Normalizers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the carrier-agnostic `MemberFact` contract and build normalizers that reduce each clean-split carrier's raw commission file (Healthspring, Devoted, BCBS, Aetna, Humana) into `MemberFact` lists — including paired-row collapse and row classification — with no database writes.

**Architecture:** A new module `app/commission/member_fact.py` holds the `MemberFact` dataclass + a shared row-class taxonomy. A new module `app/commission/normalizers.py` holds one `normalize_<carrier>(sheets) -> list[MemberFact]` function per carrier. Normalizers reuse existing helpers (`_norm`, `_parse_date`) from `payments.py`. This plan is pure transformation logic — the resolver and DB writes are Plan 2+. Tests are fixtured from the real raw files in `docs/Commission DL/Raw commissions docs from AJ/`.

**Tech Stack:** Python 3.10, `dataclasses`, pandas/openpyxl (already used), pytest with SQLite-in-memory (not needed here — these are pure-logic tests), `xml.etree.ElementTree` for Humana SpreadsheetML.

**Reference spec:** `docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md`

---

## File Structure

- **Create** `app/commission/member_fact.py` — `MemberFact` dataclass + `RowClass` constants. One responsibility: the data contract.
- **Create** `app/commission/normalizers.py` — per-carrier `normalize_*` functions. One responsibility: raw file → `MemberFact[]`.
- **Create** `app/commission/sheet_loader.py` — load any commission file (XLSX, PK-disguised-as-.xls, Humana SpreadsheetML) into `{sheet_name: list[list[cell]]}`. One responsibility: format detection + raw cell extraction.
- **Create** `tests/test_commission_normalizers.py` — normalizer unit tests fixtured from real raw files.
- **Create** `tests/fixtures/commission/` — small trimmed copies of the raw files for deterministic tests (see Task 1).

Note: the existing `extract_*` functions in `payments.py` use stale column indices and a payment-only dict shape; they are NOT modified here. They remain feeding the legacy payment path until Plan 4 swaps the pipeline. Do not delete them in this plan.

---

### Task 1: Create test fixtures from the real raw files

**Files:**
- Create: `tests/fixtures/commission/` (directory)
- Create: `tests/fixtures/commission/README.md`

- [ ] **Step 1: Create the fixtures directory and copy trimmed raw files**

The real raw files live in `docs/Commission DL/Raw commissions docs from AJ/`. Copy five into the fixtures dir under stable names (full files are small — 8KB–760KB — so copy whole; they are already representative).

Run:
```bash
cd /home/timothywinslowlinux/dev/founders-portal
mkdir -p tests/fixtures/commission
cp "docs/Commission DL/Raw commissions docs from AJ/68_486966.xlsx" tests/fixtures/commission/healthspring_sample.xlsx
cp "docs/Commission DL/Raw commissions docs from AJ/Founders Devoted April 2026 TM May 2026.xlsx" tests/fixtures/commission/devoted_sample.xlsx
cp "docs/Commission DL/Raw commissions docs from AJ/Brian Freeman (Founders) BCBS NC April 2026 TM May.xlsx" tests/fixtures/commission/bcbs_sample.xlsx
cp "docs/Commission DL/Raw commissions docs from AJ/Aetna Founders - May 2026.xlsx" tests/fixtures/commission/aetna_sample.xlsx
cp "docs/Commission DL/Raw commissions docs from AJ/CommissionData (5).xls" tests/fixtures/commission/humana_sample.xls
```

- [ ] **Step 2: Document the fixtures**

Create `tests/fixtures/commission/README.md`:
```markdown
# Commission test fixtures

Trimmed/whole copies of AJ's RAW commission files (2026-06-03), used by
`tests/test_commission_normalizers.py`. Source of truth for per-carrier
column layouts. See `docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md`
"Per-carrier reference" for the verified layouts.

- healthspring_sample.xlsx — 68_486966 (Summary/Detail/Legacy; 10 detail rows, paired Service Fee + Broker Level)
- devoted_sample.xlsx       — Founders Devoted (Total/Override/Agent Portion/HRA sheets)
- bcbs_sample.xlsx          — Brian Freeman BCBS (Sheet1; FY + RENEW + ADJUSTMENT group types)
- aetna_sample.xlsx         — Aetna Founders May 2026 (agency-level multi-agent; Renewal + Pro-Rata)
- humana_sample.xls         — CommissionData (5) (SpreadsheetML 2003 XML, broken `<xml version>` first line)
```

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/commission/
git commit -m "test(commission): add raw-file fixtures for normalizer tests"
```

---

### Task 2: Define the MemberFact contract

**Files:**
- Create: `app/commission/member_fact.py`
- Test: `tests/test_commission_normalizers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_commission_normalizers.py`:
```python
"""
tests/test_commission_normalizers.py

Pure-logic tests for the MemberFact contract and per-carrier normalizers.
Fixtured from real raw commission files in tests/fixtures/commission/.
No database needed.
"""
import os

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "commission")


def test_memberfact_defaults_and_required_fields():
    from app.commission.member_fact import MemberFact, RowClass

    mf = MemberFact(
        carrier="Devoted",
        full_name="ELIZABETH BOLDER",
        first_name="ELIZABETH",
        last_name="BOLDER",
        carrier_member_id="DS97W3",
        row_class=RowClass.CHARGEBACK,
        amount=-347.0,
    )
    assert mf.carrier == "Devoted"
    assert mf.mbi is None                 # optional, defaults None
    assert mf.is_agency_share is False    # defaults False
    assert mf.split_flag is None
    assert mf.row_class == RowClass.CHARGEBACK
    assert mf.amount == -347.0


def test_rowclass_constants_exist():
    from app.commission.member_fact import RowClass
    assert RowClass.ENROLLMENT == "enrollment"
    assert RowClass.RENEWAL == "renewal"
    assert RowClass.CHARGEBACK == "chargeback"
    assert RowClass.NON_CUSTOMER == "non_customer"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_normalizers.py::test_memberfact_defaults_and_required_fields -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.commission.member_fact'`

- [ ] **Step 3: Write minimal implementation**

Create `app/commission/member_fact.py`:
```python
"""
app/commission/member_fact.py

The carrier-agnostic contract between commission-file normalizers and the
customer-resolution service. Every carrier file is reduced to a list of
MemberFact; the resolver never sees a carrier's raw format.

See docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md §1.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional


class RowClass:
    """Common taxonomy each carrier's native row-type vocabulary maps onto."""
    ENROLLMENT = "enrollment"      # new sale → create/confirm customer + open AOR
    RENEWAL = "renewal"            # confirm existing AOR, record payment
    CHARGEBACK = "chargeback"      # negative/clawback → payment+lifecycle, NO customer create
    NON_CUSTOMER = "non_customer"  # HRA bonus, summary line → payment only, NO customer


@dataclass
class MemberFact:
    # identity
    carrier: str
    full_name: str
    first_name: str = ""
    last_name: str = ""
    mbi: Optional[str] = None
    carrier_member_id: Optional[str] = None
    dob: Optional[date] = None

    # lifecycle
    effective_date: Optional[date] = None
    term_date: Optional[date] = None
    plan_contract: Optional[str] = None   # "H9725"
    plan_pbp: Optional[str] = None        # "015"
    plan_type: Optional[str] = None       # "MAPD" / "DSNP" ...

    # classification + money
    row_class: str = RowClass.RENEWAL
    amount: float = 0.0                   # may be negative (chargeback)
    is_agency_share: bool = False         # Healthspring Service Fee / Devoted Override sheet

    # agent / split (populated by Plan 5; normalizer sets writing_agent_raw only)
    writing_agent_raw: str = ""
    resolved_agent_id: Optional[int] = None
    contract_active: Optional[bool] = None
    split_rate: Optional[float] = None
    agent_share: Optional[Decimal] = None
    split_flag: Optional[str] = None      # None | 'no_contract' | 'provenance_conditional'

    # audit / idempotency
    source_ref: str = ""                  # "file::sheet::rowindex"

    # carry the agency-share amount when paired rows are collapsed (Healthspring/Devoted)
    agency_share_amount: Optional[float] = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_commission_normalizers.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add app/commission/member_fact.py tests/test_commission_normalizers.py
git commit -m "feat(commission): add MemberFact contract + RowClass taxonomy"
```

---

### Task 3: Sheet loader — read all three file formats into raw cells

**Files:**
- Create: `app/commission/sheet_loader.py`
- Test: `tests/test_commission_normalizers.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_commission_normalizers.py`:
```python
def test_load_sheets_xlsx_healthspring():
    from app.commission.sheet_loader import load_sheets
    sheets = load_sheets(os.path.join(FIXTURES, "healthspring_sample.xlsx"))
    assert "Detail" in sheets
    assert "Summary" in sheets
    header = sheets["Detail"][0]
    assert header[0] == "Payment Type"
    assert header[9] == "Medicare Beneficiary Identifier"


def test_load_sheets_pk_disguised_as_xls():
    # Devoted per-agent file uses .xls extension but is real XLSX (PK header).
    # The agency Devoted fixture is a true .xlsx; assert loader handles xlsx multi-sheet.
    from app.commission.sheet_loader import load_sheets
    sheets = load_sheets(os.path.join(FIXTURES, "devoted_sample.xlsx"))
    assert "Override" in sheets
    assert "Agent Portion" in sheets
    assert sheets["Agent Portion"][0][17] == "Base Amount"


def test_load_sheets_humana_spreadsheetml():
    from app.commission.sheet_loader import load_sheets
    sheets = load_sheets(os.path.join(FIXTURES, "humana_sample.xls"))
    # Humana SpreadsheetML worksheet name
    assert any("CommissionData" in name for name in sheets)
    name = next(n for n in sheets if "CommissionData" in n)
    header = sheets[name][0]
    assert "WaName" in header        # writing agent
    assert "UMID" in header          # MBI-shaped id
    assert "PaidAmount" in header
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k load_sheets -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.commission.sheet_loader'`

- [ ] **Step 3: Write minimal implementation**

Create `app/commission/sheet_loader.py`:
```python
"""
app/commission/sheet_loader.py

Loads a commission file into {sheet_name: list[list[cell]]} regardless of the
three real formats AJ's carriers ship:
  - true XLSX (most carriers)
  - .xls extension that is actually XLSX (PK/zip bytes) — Devoted per-agent
  - SpreadsheetML 2003 XML with a broken `<xml version>` first line — Humana

See docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md
"Per-carrier reference".
"""
import re
import xml.etree.ElementTree as ET

import openpyxl


def _looks_like_zip(path):
    with open(path, "rb") as fh:
        return fh.read(2) == b"PK"


def _load_xlsx(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = {}
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append([("" if c is None else c) for c in row])
        out[ws.title] = rows
    wb.close()
    return out


_SS = "urn:schemas-microsoft-com:office:spreadsheet"


def _load_spreadsheetml(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    # Fix the broken first line `<xml version>` → strip it; keep <Workbook ...>
    raw = re.sub(r"^\s*<xml[^>]*>\s*", "", raw, count=1)
    root = ET.fromstring(raw)
    out = {}
    for ws in root.iter("{%s}Worksheet" % _SS):
        name = ws.get("{%s}Name" % _SS)
        table = ws.find("{%s}Table" % _SS)
        if table is None:
            continue
        rows = []
        for r in table.findall("{%s}Row" % _SS):
            cells = []
            for c in r.findall("{%s}Cell" % _SS):
                d = c.find("{%s}Data" % _SS)
                cells.append("" if d is None or d.text is None else d.text)
            rows.append(cells)
        out[name] = rows
    return out


def load_sheets(path):
    """Return {sheet_name: list[list[cell]]} for any supported commission file."""
    if path.lower().endswith(".xlsx") or _looks_like_zip(path):
        return _load_xlsx(path)
    # .xls that is not a zip → SpreadsheetML XML (Humana)
    return _load_spreadsheetml(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k load_sheets -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/commission/sheet_loader.py tests/test_commission_normalizers.py
git commit -m "feat(commission): sheet_loader handles xlsx, PK-as-xls, Humana SpreadsheetML"
```

---

### Task 4: Healthspring normalizer (paired-row collapse)

**Files:**
- Create: `app/commission/normalizers.py`
- Test: `tests/test_commission_normalizers.py`

Healthspring `Detail` columns (verified): 0 Payment Type, 1 Payment Description (Service Fee | Broker Level), 3 Writing Broker Name, 5 Earner Name, 7 Payment Amount, 8 Member ID, 9 MBI, 10 Member Name, 12 Effective Date, 13 Member Term Date, 18 Plan Type, 20 CMS Contract, 21 PBP. Each member has TWO rows: `Service Fee` (Earner = FOUNDERS, agency share) + `Broker Level` (Earner = agent). Collapse to ONE MemberFact: amount = Broker Level (agent share), agency_share_amount = Service Fee.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_normalizers.py`:
```python
def test_normalize_healthspring_collapses_paired_rows():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_healthspring
    from app.commission.member_fact import RowClass

    sheets = load_sheets(os.path.join(FIXTURES, "healthspring_sample.xlsx"))
    facts = normalize_healthspring(sheets)

    # 68_486966 Detail has 10 rows = 5 members x 2 rows (Service Fee + Broker Level)
    # except the two "Initial - New to CMS" rows are Broker Level only (no Service Fee).
    # Assert no fact is a bare Service Fee row, and member ids are unique per fact group.
    assert facts, "expected MemberFacts"
    for f in facts:
        assert f.carrier == "Healthspring"
        assert f.row_class in (RowClass.ENROLLMENT, RowClass.RENEWAL, RowClass.CHARGEBACK)
        # the collapsed fact's amount is the agent (Broker Level) share, never the $80 fee alone
        assert f.amount != 80.0 or f.agency_share_amount is None

    # WANDA LONG (member 71A2L3L49) appears as a single collapsed fact
    wanda = [f for f in facts if f.carrier_member_id == "71A2L3L49"]
    assert len(wanda) == 1
    assert wanda[0].mbi == "3AP7QV3RJ37"
    assert wanda[0].row_class == RowClass.ENROLLMENT   # "Initial - New to CMS"
    assert wanda[0].plan_contract == "H9725"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k healthspring -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.commission.normalizers'`

- [ ] **Step 3: Write minimal implementation**

Create `app/commission/normalizers.py`:
```python
"""
app/commission/normalizers.py

Per-carrier normalizers: raw sheets ({name: list[list[cell]]}) -> list[MemberFact].
Each carrier's native row-type vocabulary maps onto the common RowClass taxonomy.
Paired rows (Healthspring Service Fee + Broker Level; Devoted Override + Agent
Portion) are collapsed to ONE MemberFact per member.

See docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md §1 and
"Per-carrier reference".
"""
from app.commission.member_fact import MemberFact, RowClass
from app.commission.payments import _norm, _parse_date


def _to_float(v):
    try:
        return float(str(v).replace("$", "").replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _classify_healthspring(payment_type, amount):
    pt = str(payment_type or "").lower()
    if amount < 0 or "disenroll" in pt:
        return RowClass.CHARGEBACK
    if "renewal" in pt:
        return RowClass.RENEWAL
    if "initial" in pt:   # "Initial - New to CMS" / "Initial - NOT New to CMS"
        return RowClass.ENROLLMENT
    return RowClass.RENEWAL


def normalize_healthspring(sheets):
    rows = sheets.get("Detail", [])
    if not rows:
        return []
    facts_by_member = {}     # member_id -> MemberFact (Broker Level row)
    agency_by_member = {}    # member_id -> agency share amount (Service Fee row)

    for idx, row in enumerate(rows[1:], start=1):   # skip header
        if not any(row):
            continue
        member_id = str(row[8] or "").strip()
        if not member_id:
            continue
        desc = str(row[1] or "")                     # Service Fee | Broker Level
        amount = _to_float(row[7])

        if "service fee" in desc.lower():
            agency_by_member[member_id] = amount
            continue

        # Broker Level row → the agent-share fact
        name = str(row[10] or "").strip()
        fact = MemberFact(
            carrier="Healthspring",
            full_name=name,
            first_name=name.split()[0] if name else "",
            last_name=name.split()[-1] if name else "",
            mbi=str(row[9] or "").strip() or None,
            carrier_member_id=member_id,
            effective_date=_parse_date(row[12]),
            term_date=_parse_date(row[13]),
            plan_contract=str(row[20] or "").strip() or None,
            plan_pbp=str(row[21] or "").strip() or None,
            plan_type=str(row[18] or "").strip() or None,
            row_class=_classify_healthspring(row[0], amount),
            amount=amount,
            writing_agent_raw=str(row[3] or "").strip(),
            source_ref=f"healthspring::Detail::{idx}",
        )
        facts_by_member[member_id] = fact

    for mid, fact in facts_by_member.items():
        fact.agency_share_amount = agency_by_member.get(mid)
    return list(facts_by_member.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k healthspring -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/normalizers.py tests/test_commission_normalizers.py
git commit -m "feat(commission): Healthspring normalizer with Service Fee/Broker Level collapse"
```

---

### Task 5: Devoted normalizer (Override + Agent Portion collapse, HRA = non-customer)

**Files:**
- Modify: `app/commission/normalizers.py`
- Test: `tests/test_commission_normalizers.py`

Devoted sheets (verified): `Agent Portion` and `Override` share columns: 1 Agent NPN, 2 Agent Name, 3 Member ID, 4 Member HICN, 5 Member First, 6 Member Last, 9 Effective Date, 10 Disenroll Date, 11 Contract, 12 PBP, 15 Commission Type, 17 (Base Amount on Agent Portion / Admin Amount on Override). The same member appears in BOTH sheets. Agent Portion = agent share (the fact's `amount`); Override = agency share (`agency_share_amount`). The `HRA` sheet is $50 bonuses → NON_CUSTOMER facts (no Member ID).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_normalizers.py`:
```python
def test_normalize_devoted_collapses_and_flags_chargebacks():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_devoted
    from app.commission.member_fact import RowClass

    sheets = load_sheets(os.path.join(FIXTURES, "devoted_sample.xlsx"))
    facts = normalize_devoted(sheets)
    assert facts

    # Elizabeth Bolder (DS97W3): eff 01/01/2026, disenroll 03/31/2026, Base -347 = chargeback
    bolder = [f for f in facts if f.carrier_member_id == "DS97W3"]
    assert len(bolder) == 1
    assert bolder[0].carrier == "Devoted"
    assert bolder[0].row_class == RowClass.CHARGEBACK
    assert bolder[0].amount == -347.0
    assert bolder[0].term_date is not None

    # Rene Barger (DGFY27): Apr enrollment, Base 260.25, no disenroll
    barger = [f for f in facts if f.carrier_member_id == "DGFY27"]
    assert len(barger) == 1
    assert barger[0].row_class == RowClass.ENROLLMENT
    assert barger[0].amount == 260.25
    assert barger[0].agency_share_amount == 125.0   # Override row for same member


def test_normalize_devoted_hra_is_non_customer():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_devoted
    from app.commission.member_fact import RowClass

    sheets = load_sheets(os.path.join(FIXTURES, "devoted_sample.xlsx"))
    facts = normalize_devoted(sheets)
    hras = [f for f in facts if f.row_class == RowClass.NON_CUSTOMER]
    assert hras, "expected HRA bonus rows as NON_CUSTOMER"
    assert all(f.carrier_member_id is None for f in hras)
    assert all(f.amount == 50.0 for f in hras)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k devoted -v`
Expected: FAIL with `AttributeError` / `ImportError: cannot import name 'normalize_devoted'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/commission/normalizers.py`:
```python
def _classify_devoted(commission_type, amount, disenroll):
    if amount < 0 or disenroll:
        return RowClass.CHARGEBACK
    ct = str(commission_type or "").lower()
    if "new" in ct:        # "Initial - New" / "Initial - Not New"
        return RowClass.ENROLLMENT
    return RowClass.RENEWAL


def normalize_devoted(sheets):
    facts = {}        # member_id -> MemberFact (from Agent Portion)
    agency = {}       # member_id -> Override admin amount

    for idx, row in enumerate(sheets.get("Agent Portion", [])[1:], start=1):
        if not any(row):
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
            mbi=str(row[4] or "").strip() or None,    # HICN (MBI-shaped)
            carrier_member_id=member_id,
            effective_date=_parse_date(row[9]),
            term_date=disen,
            plan_contract=str(row[11] or "").strip() or None,
            plan_pbp=str(row[12] or "").strip() or None,
            row_class=_classify_devoted(row[15], amount, disen),
            amount=amount,
            writing_agent_raw=str(row[2] or "").strip(),
            source_ref=f"devoted::Agent Portion::{idx}",
        )

    for idx, row in enumerate(sheets.get("Override", [])[1:], start=1):
        if not any(row):
            continue
        member_id = str(row[3] or "").strip()
        if member_id:
            agency[member_id] = _to_float(row[17])

    for mid, fact in facts.items():
        fact.agency_share_amount = agency.get(mid)

    out = list(facts.values())

    # HRA sheet → NON_CUSTOMER bonus facts (Rep Name, Rep ID, Amount, Note)
    for idx, row in enumerate(sheets.get("HRA", [])[1:], start=1):
        if not any(row):
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
            source_ref=f"devoted::HRA::{idx}",
        ))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k devoted -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/commission/normalizers.py tests/test_commission_normalizers.py
git commit -m "feat(commission): Devoted normalizer (Override/Agent Portion collapse, HRA non-customer)"
```

---

### Task 6: BCBS normalizer (no MBI, Group Type taxonomy)

**Files:**
- Modify: `app/commission/normalizers.py`
- Test: `tests/test_commission_normalizers.py`

BCBS `Sheet1` columns (verified): 0 Agent #, 1 Agent Name, 2 Group Type (FY|RENEW|ADJUSTMENT|NEW), 3 Customer Type, 4 Customer Name, 5 Customer No, 6 Orig Eff Date, 7 Product, 8 Coverage From, 9 Coverage To, 14 Commission. No MBI. `Customer No` is the carrier_member_id. Skip the trailing `Total:` row.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_normalizers.py`:
```python
def test_normalize_bcbs_group_types_and_no_mbi():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_bcbs
    from app.commission.member_fact import RowClass

    sheets = load_sheets(os.path.join(FIXTURES, "bcbs_sample.xlsx"))
    facts = normalize_bcbs(sheets)
    assert facts
    for f in facts:
        assert f.carrier == "BCBS"
        assert f.mbi is None                     # BCBS never has MBI
        assert f.carrier_member_id                # always a Customer No

    # FY rows are enrollments; RENEW rows are renewals
    classes = {f.carrier_member_id: f.row_class for f in facts}
    # Buchanan,Andrea M 106815011 is FY
    assert classes.get("106815011") == RowClass.ENROLLMENT
    # Allen,Brenda M 106729743 is RENEW
    assert classes.get("106729743") == RowClass.RENEWAL


def test_normalize_bcbs_skips_total_row():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_bcbs
    sheets = load_sheets(os.path.join(FIXTURES, "bcbs_sample.xlsx"))
    facts = normalize_bcbs(sheets)
    assert all("total" not in f.full_name.lower() for f in facts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k bcbs -v`
Expected: FAIL with `ImportError: cannot import name 'normalize_bcbs'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/commission/normalizers.py`:
```python
def _classify_bcbs(group_type, amount):
    gt = str(group_type or "").upper().strip()
    if amount < 0 or gt == "ADJUSTMENT":
        return RowClass.CHARGEBACK
    if gt == "RENEW":
        return RowClass.RENEWAL
    if gt in ("FY", "NEW"):
        return RowClass.ENROLLMENT
    return RowClass.RENEWAL


def normalize_bcbs(sheets):
    rows = sheets.get("Sheet1", [])
    if not rows:
        return []
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row):
            continue
        name = str(row[4] or "").strip()
        customer_no = str(row[5] or "").strip()
        if not name or not customer_no:        # skips Total: row (no name/Customer No)
            continue
        # BCBS name is "Last,First M"
        if "," in name:
            last, first_rest = [p.strip() for p in name.split(",", 1)]
            first = first_rest.split()[0] if first_rest else ""
        else:
            last, first = name, ""
        amount = _to_float(row[14])
        out.append(MemberFact(
            carrier="BCBS",
            full_name=name,
            first_name=first,
            last_name=last,
            mbi=None,
            carrier_member_id=customer_no,
            effective_date=_parse_date(row[6]),
            term_date=_parse_date(row[9]),
            plan_type=str(row[7] or "").strip() or None,
            row_class=_classify_bcbs(row[2], amount),
            amount=amount,
            writing_agent_raw=str(row[1] or "").strip(),
            source_ref=f"bcbs::Sheet1::{idx}",
        ))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k bcbs -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/commission/normalizers.py tests/test_commission_normalizers.py
git commit -m "feat(commission): BCBS normalizer (Group Type taxonomy, no MBI)"
```

---

### Task 7: Aetna normalizer (agency-level, Sales Event taxonomy)

**Files:**
- Modify: `app/commission/normalizers.py`
- Test: `tests/test_commission_normalizers.py`

Aetna sheet name = the agency name (varies) — take the first sheet. Columns (verified): 1 Medicare Number (MBI), 2 Member ID, 4 Member Name ("Last F,First"), 6 Sales Event (Renewal|Pro-Rata Payment|Pro-Rata Disenroll), 9 Plan ID ("H3146-006"), 12 Effective Date, 13 Term Date, 16 Writing Agent Name, 20 Payee Amount, 21 CMS New (Y/N).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_normalizers.py`:
```python
def test_normalize_aetna_sales_events_and_mbi():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_aetna
    from app.commission.member_fact import RowClass

    sheets = load_sheets(os.path.join(FIXTURES, "aetna_sample.xlsx"))
    facts = normalize_aetna(sheets)
    assert facts
    for f in facts:
        assert f.carrier == "Aetna"

    # BOBBY ADERHOLD (6CM1RV8NW05) Renewal 28.92
    aderhold = [f for f in facts if f.mbi == "6CM1RV8NW05"]
    assert len(aderhold) >= 1
    assert aderhold[0].row_class == RowClass.RENEWAL
    assert aderhold[0].plan_contract == "H3146"
    assert aderhold[0].plan_pbp == "006"

    # DAVID BURNER (1KR6UW2KP73) has a Pro-Rata Disenroll of -347 → chargeback
    burner_cb = [f for f in facts if f.mbi == "1KR6UW2KP73" and f.amount < 0]
    assert burner_cb
    assert burner_cb[0].row_class == RowClass.CHARGEBACK
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k aetna -v`
Expected: FAIL with `ImportError: cannot import name 'normalize_aetna'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/commission/normalizers.py`:
```python
def _split_plan_id(plan_id):
    """'H3146-006' -> ('H3146', '006'); 'H5521-170' -> ('H5521','170')."""
    s = str(plan_id or "").strip()
    if "-" in s:
        a, b = s.split("-", 1)
        return a.strip() or None, b.strip() or None
    return (s or None), None


def _classify_aetna(sales_event, amount):
    se = str(sales_event or "").lower()
    if amount < 0 or "disenroll" in se:
        return RowClass.CHARGEBACK
    if "renewal" in se:
        return RowClass.RENEWAL
    if "pro-rata" in se or "new" in se:
        return RowClass.ENROLLMENT
    return RowClass.RENEWAL


def normalize_aetna(sheets):
    if not sheets:
        return []
    first = next(iter(sheets.values()))   # sheet named after the agency
    if not first:
        return []
    out = []
    for idx, row in enumerate(first[1:], start=1):
        if not any(row) or len(row) < 22:
            continue
        name = str(row[4] or "").strip()
        if not name:
            continue
        amount = _to_float(row[20])
        contract, pbp = _split_plan_id(row[9])
        out.append(MemberFact(
            carrier="Aetna",
            full_name=name,
            mbi=str(row[1] or "").strip() or None,
            carrier_member_id=str(row[2] or "").strip() or None,
            effective_date=_parse_date(row[12]),
            term_date=_parse_date(row[13]),
            plan_contract=contract,
            plan_pbp=pbp,
            plan_type=str(row[7] or "").strip() or None,
            row_class=_classify_aetna(row[6], amount),
            amount=amount,
            writing_agent_raw=str(row[16] or "").strip(),
            source_ref=f"aetna::0::{idx}",
        ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k aetna -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/normalizers.py tests/test_commission_normalizers.py
git commit -m "feat(commission): Aetna normalizer (agency-level, Sales Event taxonomy)"
```

---

### Task 8: Humana normalizer (SpreadsheetML, TxnTypeCd taxonomy)

**Files:**
- Modify: `app/commission/normalizers.py`
- Test: `tests/test_commission_normalizers.py`

Humana columns (verified, by header name not index — SpreadsheetML rows can vary): `WaName` (writing agent), `GrpName` (member name "LAST FIRST M"), `UMID` (MBI-shaped), `PID`, `PaidAmount`, `EffDate`, `Contract`, `TxnTypeCd` (ARCM=renewal, ARCF=first-yr, MED2=2nd-half first-yr; others rare), `Comment`. Negative `PaidAmount` = chargeback. Map by header position resolved at runtime.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_normalizers.py`:
```python
def test_normalize_humana_txntype_taxonomy():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_humana
    from app.commission.member_fact import RowClass

    sheets = load_sheets(os.path.join(FIXTURES, "humana_sample.xls"))
    facts = normalize_humana(sheets)
    assert facts
    for f in facts:
        assert f.carrier == "Humana"

    # VILLEGAS ANASTACIO Z (UMID 5EN4NW3VF63) ARCF first-year +231.33 → enrollment
    vill = [f for f in facts if f.mbi == "5EN4NW3VF63"]
    assert vill and vill[0].row_class == RowClass.ENROLLMENT
    assert vill[0].amount == 231.33

    # MURRAY member (UMID 8QV9Q10TC36) ARCF but -231.33 → chargeback (negative wins)
    murray = [f for f in facts if f.mbi == "8QV9Q10TC36"]
    assert murray and murray[0].row_class == RowClass.CHARGEBACK

    # at least one ARCM renewal present
    assert any(f.row_class == RowClass.RENEWAL for f in facts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k humana -v`
Expected: FAIL with `ImportError: cannot import name 'normalize_humana'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/commission/normalizers.py`:
```python
def _classify_humana(txn_type, amount):
    t = str(txn_type or "").upper().strip()
    if amount < 0:
        return RowClass.CHARGEBACK
    if t == "ARCM":          # renewal commissions
        return RowClass.RENEWAL
    if t in ("ARCF", "MED2", "ICCF", "ICFA"):   # first-year / 2nd-half first-year
        return RowClass.ENROLLMENT
    if t in ("HRAP",):       # HRA bonus
        return RowClass.NON_CUSTOMER
    return RowClass.RENEWAL


def _humana_name(grp_name):
    """'VILLEGAS ANASTACIO Z' -> full as-is; first/last best-effort."""
    s = str(grp_name or "").strip()
    parts = s.split()
    if len(parts) >= 2:
        return s, parts[1], parts[0]   # full, first(guess), last(guess)
    return s, "", s


def normalize_humana(sheets):
    if not sheets:
        return []
    name = next((n for n in sheets if "CommissionData" in n), None) or next(iter(sheets))
    rows = sheets.get(name, [])
    if not rows:
        return []
    header = rows[0]
    col = {h: i for i, h in enumerate(header)}

    def g(row, key):
        i = col.get(key)
        return row[i] if i is not None and i < len(row) else ""

    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row):
            continue
        umid = str(g(row, "UMID") or "").strip()
        grp = g(row, "GrpName")
        if not umid and not grp:
            continue
        amount = _to_float(g(row, "PaidAmount"))
        full, first, last = _humana_name(grp)
        out.append(MemberFact(
            carrier="Humana",
            full_name=full,
            first_name=first,
            last_name=last,
            mbi=umid or None,
            carrier_member_id=str(g(row, "PID") or "").strip() or None,
            effective_date=_parse_date(g(row, "EffDate")),
            plan_contract=str(g(row, "Contract") or "").strip() or None,
            row_class=_classify_humana(g(row, "TxnTypeCd"), amount),
            amount=amount,
            writing_agent_raw=str(g(row, "WaName") or "").strip(),
            source_ref=f"humana::{name}::{idx}",
        ))
    return out
```

Note: `_parse_date` must accept Humana's ISO `2026-05-01T00:00:00.000` strings. If the existing `_parse_date` returns None for that format, add a branch in Step 3a below.

- [ ] **Step 3a: Verify date parsing for ISO-with-T, patch if needed**

Run: `python3 -c "from app.commission.payments import _parse_date; print(_parse_date('2026-05-01T00:00:00.000'))"`
Expected: a `date(2026, 5, 1)`. If it prints `None`, append this format handling to `_parse_date` in `app/commission/payments.py` (inside the string branch, before `return None`):
```python
        # ISO with time component (Humana SpreadsheetML)
        try:
            return datetime.fromisoformat(val.strip().replace("Z", "")).date()
        except ValueError:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k humana -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/commission/normalizers.py tests/test_commission_normalizers.py app/commission/payments.py
git commit -m "feat(commission): Humana normalizer (SpreadsheetML, TxnTypeCd taxonomy)"
```

---

### Task 9: Normalizer registry + full-suite green

**Files:**
- Modify: `app/commission/normalizers.py`
- Test: `tests/test_commission_normalizers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_commission_normalizers.py`:
```python
def test_normalizer_registry_dispatch():
    from app.commission.normalizers import NORMALIZERS
    for carrier in ("Healthspring", "Devoted", "BCBS", "Aetna", "Humana"):
        assert carrier in NORMALIZERS
        assert callable(NORMALIZERS[carrier])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commission_normalizers.py -k registry -v`
Expected: FAIL with `ImportError: cannot import name 'NORMALIZERS'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/commission/normalizers.py`:
```python
NORMALIZERS = {
    "Healthspring": normalize_healthspring,
    "Devoted": normalize_devoted,
    "BCBS": normalize_bcbs,
    "Aetna": normalize_aetna,
    "Humana": normalize_humana,
    # "UHC": normalize_uhc,  # added in Plan 6 (inference-heavy, built last)
}
```

- [ ] **Step 4: Run the FULL normalizer suite**

Run: `python3 -m pytest tests/test_commission_normalizers.py -v`
Expected: PASS (all tests across Tasks 2–9)

- [ ] **Step 5: Run the entire test suite to confirm no regressions**

Run: `python3 -m pytest -q`
Expected: PASS (existing suites + new normalizer suite). The legacy `extract_*` in `payments.py` are untouched, so existing commission tests stay green.

- [ ] **Step 6: Commit**

```bash
git add app/commission/normalizers.py tests/test_commission_normalizers.py
git commit -m "feat(commission): normalizer registry for clean-split carriers"
```

---

## Self-Review

**1. Spec coverage (Plan 1 scope = spec §1 normalizers + §5 build step 1):**
- MemberFact contract (spec §1) → Task 2. ✓
- Paired-row collapse Healthspring/Devoted (spec §1) → Tasks 4, 5. ✓
- row_class taxonomy per carrier (spec §1 + Per-carrier reference) → Tasks 4–8. ✓
- Three file formats incl. Humana SpreadsheetML (spec Per-carrier reference) → Task 3. ✓
- Clean-split carriers first, UHC deferred (spec §5 sequencing) → Task 9 registry comments out UHC. ✓
- Fixtured from real raw files (spec §5 testing) → Task 1. ✓
- NOT in this plan (correctly deferred to later plans): resolver, crosswalk, DB writes, migration 020, split/auth math, duplicate guard, UHC. ✓

**2. Placeholder scan:** No TBD/TODO. Every code step shows complete code. Task 8 Step 3a is a conditional patch with the exact code given, not a placeholder.

**3. Type consistency:** `MemberFact` field names used in Tasks 4–8 (`carrier_member_id`, `agency_share_amount`, `row_class`, `plan_contract`, `plan_pbp`, `writing_agent_raw`, `source_ref`) all match the dataclass defined in Task 2. `RowClass` constants (`ENROLLMENT`/`RENEWAL`/`CHARGEBACK`/`NON_CUSTOMER`) consistent throughout. `load_sheets` return shape (`{name: list[list]}`) consistent between Task 3 and consumers. Helper `_to_float`/`_parse_date`/`_norm` usage consistent.

Plan is internally consistent and scoped to one shippable unit (tested normalizers).
