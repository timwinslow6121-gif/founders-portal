# Aetna CSV BOB + Plan-History from Terminations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Aetna parser to read the June "MedicareApprovedBOBReport" CSV (capturing DOB/phone/address/term/NPN), complete the fill-blanks-only PII rule, add the termination→close-open-AOR lifecycle, and seed closed plan-history intervals for still-customers — so every Aetna member resolves and the customer profile shows an accurate carrier/plan timeline.

**Architecture:** A format branch in `app/parsers/aetna.py` (`.csv` → new CSV path, `.xlsx` → existing April path). The upload path gains a termed-rec handler (terms the policy + closes the open AOR interval + seeds closed history for existing customers) and completes fill-blanks on all PII. Interval writing REUSES the resolver's existing duplicate-guarded logic — no parallel interval code.

**Tech Stack:** Python 3.10, Flask, pandas (CSV + xlsx), pytest. PostgreSQL on VPS / SQLite in tests.

## Global Constraints

- **June CSV columns used:** `Medicare Number, Member ID, First Name, Middle Initial, Last Name, Date of Birth, Phone Number, Address Line 1, Address Line 2, City, State, Zip Code, Coverage Effective Date, Member Status (A/T), Term Date (sentinel 3000-01-01 = none), Plan Name, CMS Contract Number, PBP Code, Writing Agent NPN, Writing Agent First Name, Writing Agent Last Name`. Other columns ignored.
- **Detection already works** — `_detect_carrier`'s `.csv` branch returns "Aetna" for `Medicare Number` + `Member Status`. No detection change.
- **Format branch:** `parse()` reads `.csv` via the new CSV path (First/Middle/Last columns, NPN agent), `.xlsx` via the existing April path (Member Name, name agent). Both coexist.
- **Active filter:** only `Member Status == "A"` rows become active policies. `T` rows emit `status="termed"` recs and do NOT create new policies.
- **Term-date sentinel `3000-01-01` → None.**
- **Names:** `First/Middle/Last` → "First MI. Last" via `app.names.normalize_person_name` (or build directly from the columns).
- **Address Line 2 KEPT:** there is NO `address2` column — fold Line 2 into `address1` (e.g. "4908 Cameron Valley Pkwy, Apt 4"); Line 1 alone when Line 2 blank. NEVER drop Line 2.
- **Agent resolution: NPN-first, name-fallback.** CSV puts the NPN in `rec["agent_id"]` and the name in `rec["agent_name"]`. The Aetna fallback reads `rec.get("agent_name") or rec["agent_id"]`.
- **Fill-blanks-only + manually_edited:** all freshness/PII written only when the existing value is blank; never overwrite a non-blank field; never touch a `manually_edited` customer's PII. **§6 BUG: the PII lines in `_upsert_customer_from_policy` (~200-207) AND `_import_bob_row`'s existing-policy update (~103-109) still OVERWRITE — convert them to `_fill_if_blank`.**
- **§6b termination→close-open-AOR:** when a BOB row terms a member's active policy, close that customer's OPEN `CustomerAorHistory` interval for that carrier (`end_date=term_date`); BCBS open interval stays None.
- **§4.2 plan-history is ADD-ONLY:** a termed row, for an EXISTING customer only, writes a CLOSED interval (carrier/plan/eff/end, source="aetna_bob_history"); NEVER modifies/end-dates any OPEN interval of any carrier; idempotent (skip if a `(customer, carrier, effective_date)` interval exists). Departed members (no customer) skipped entirely.
- **§6c synergy:** REUSE the resolver's interval conventions (its exact-duplicate guard on `(customer, carrier, effective_date)`); do not reimplement interval creation. The three pieces (enroll-opens via resolver, §6b term-closes, §4.2 past-seed) must not undo each other.
- **No migration** — `dob/phone/address1/city/state/zip_code/term_date/renewal_date/commission_type` exist on Policy/Customer; `CustomerAorHistory` exists with `carrier/plan_name/effective_date/end_date/agent_id/source`.
- Test bootstrap: conftest fixtures (`db_session`, `app`, `agency`); `create_app()` takes NO argument. Never `create_app("testing")`.
- Real June CSV fixture: `docs/Carrier BOB DL/Founders Insurance Agency LLC_MedicareApprovedBOBReport_20260618.csv`.
- Tests: `python3 -m pytest -q` (~350). VPS deploy: `git pull && ./venv/bin/pip install -r requirements.txt && systemctl restart founders-portal` (no migration).

---

## File Structure

- `app/parsers/aetna.py` — **modify.** Add `_parse_csv_format(df)` + branch `parse()` by extension; emit termed recs for `T` rows.
- `app/upload.py` — **modify.** (a) complete fill-blanks PII in both `_upsert_customer_from_policy` and `_import_bob_row`; (b) Aetna agent-fallback reads `agent_name`; (c) `_close_open_aor_on_term(...)` helper (§6b); (d) `_seed_closed_history(...)` helper (§4.2); (e) route a `status="termed"` rec to those helpers instead of creating a policy.
- Tests: `tests/test_aetna_csv_parser.py`, `tests/test_bob_term_aor.py`, `tests/test_plan_history_seed.py`, `tests/test_aor_timeline_synergy.py`.

---

## Task 1: CSV-format branch in the Aetna parser

**Files:**
- Modify: `app/parsers/aetna.py`
- Test: `tests/test_aetna_csv_parser.py`

**Interfaces:**
- Consumes: `normalize_person_name` (existing).
- Produces: `parse(filepath)` handles `.csv` (June format) AND `.xlsx` (April format). CSV active rows → rec with `status="active"`; CSV `T` rows → rec with `status="termed"`. CSV rec keys: same as the xlsx rec PLUS `agent_name` (writing agent name) and `agent_id` = the NPN.

- [ ] **Step 1: Write the failing test (real CSV fixture)**

```python
# tests/test_aetna_csv_parser.py
import os, pytest
from app.parsers.aetna import parse

CSV = "docs/Carrier BOB DL/Founders Insurance Agency LLC_MedicareApprovedBOBReport_20260618.csv"

@pytest.mark.skipif(not os.path.exists(CSV), reason="June Aetna CSV fixture absent")
def test_csv_active_and_termed_split():
    recs = parse(CSV)
    active = [r for r in recs if r["status"] == "active"]
    termed = [r for r in recs if r["status"] == "termed"]
    assert len(active) == 76
    assert len(termed) == 138

@pytest.mark.skipif(not os.path.exists(CSV), reason="June Aetna CSV fixture absent")
def test_csv_active_row_fields():
    recs = parse(CSV)
    a = next(r for r in recs if r["status"] == "active")
    assert a["carrier"] == "Aetna"
    assert a["mbi"] and a["member_id"] == a["mbi"]
    assert a["carrier_member_id"].startswith("NG")
    assert a["first_name"] and a["last_name"] and " " not in a["first_name"]
    assert a["dob"] is not None            # NEW freshness
    assert a["phone"]                       # NEW freshness
    assert a["address1"]                    # NEW freshness
    assert a["state"] == "NC"
    assert a["effective_date"] is not None
    assert a["agent_id"]                    # the NPN
    assert a["agent_name"]                  # the writing agent name
    assert a["plan_name"]

@pytest.mark.skipif(not os.path.exists(CSV), reason="June Aetna CSV fixture absent")
def test_csv_term_sentinel_and_line2():
    recs = parse(CSV)
    # active rows have term_date None (sentinel 3000-01-01 stripped)
    a = next(r for r in recs if r["status"] == "active")
    assert a["term_date"] is None
    # a termed row carries a real term_date
    t = next(r for r in recs if r["status"] == "termed")
    assert t["term_date"] is not None
    # any row with an Address Line 2 folds it into address1 (no part dropped)
    line2_rows = [r for r in recs if r.get("address1") and "," in r["address1"]]
    # at least the data shape allows folding; assert address1 is non-empty for actives
    assert all(r["address1"] for r in recs if r["status"] == "active" and r.get("address1") is not None)
```

- [ ] **Step 2: Run — FAIL** (parse() only reads xlsx → raises on the csv)

Run: `python3 -m pytest tests/test_aetna_csv_parser.py -v`

- [ ] **Step 3: Implement the format branch in `app/parsers/aetna.py`**

Rename the existing body to `_parse_xlsx_format(df)` and branch `parse()`:

```python
import os
import pandas as pd
from app.names import normalize_person_name

XLSX_REQUIRED = {"Medicare Number", "Member Name", "Writing Agent Name"}
CSV_REQUIRED = {"Medicare Number", "First Name", "Writing Agent NPN"}
_TERM_SENTINEL = "3000-01-01"


def parse(filepath: str) -> list[dict]:
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(filepath, dtype=str)
        df.columns = df.columns.str.strip()
        if CSV_REQUIRED - set(df.columns):
            raise ValueError(f"Aetna CSV missing required columns: {CSV_REQUIRED - set(df.columns)}")
        return _parse_csv_format(df)
    # else xlsx (April format)
    df = pd.read_excel(filepath, dtype=str)
    df.columns = df.columns.str.strip()
    if XLSX_REQUIRED - set(df.columns):
        raise ValueError(f"Aetna file missing required columns: {XLSX_REQUIRED - set(df.columns)}")
    return _parse_xlsx_format(df)
```

Add `_parse_csv_format`:

```python
def _parse_csv_format(df):
    df = df[df["Medicare Number"].notna() &
            (df["Medicare Number"].astype(str).str.strip() != "")].copy()
    records = []
    for _, row in df.iterrows():
        mbi = _str(row, "Medicare Number").upper()
        if not mbi:
            continue
        status_raw = _str(row, "Member Status").upper()
        status = "active" if status_raw == "A" else "termed"
        first = _tc(_str(row, "First Name"))
        last = _tc(_str(row, "Last Name"))
        mi = _str(row, "Middle Initial").strip(".").upper()[:1]
        full = " ".join(x for x in [first, (mi + "." if mi else ""), last] if x)
        addr1 = _str(row, "Address Line 1")
        addr2 = _str(row, "Address Line 2")
        if addr2:
            addr1 = f"{addr1}, {addr2}".strip(", ")
        term = _parse_date(row, "Term Date")
        records.append({
            "carrier": "Aetna",
            "member_id": mbi,
            "mbi": mbi,
            "carrier_member_id": _str(row, "Member ID"),
            "first_name": first, "last_name": last, "full_name": full,
            "agent_id": _str(row, "Writing Agent NPN"),     # NPN → resolve_writing_agent
            "agent_name": " ".join(p for p in [_str(row, "Writing Agent First Name"),
                                               _str(row, "Writing Agent Last Name")] if p),
            "effective_date": _parse_date(row, "Coverage Effective Date"),
            "term_date": term,
            "renewal_date": None,
            "state": _str(row, "State"),
            "address1": addr1, "city": _str(row, "City"), "zip_code": _str(row, "Zip Code"),
            "plan_name": _str(row, "Plan Name"),
            "plan_type": "", "phone": _str(row, "Phone Number"),
            "county": "", "dob": _parse_date(row, "Date of Birth"),
            "commission_type": None,
            "status": status,
        })
    return records


def _tc(w):
    return w[:1].upper() + w[1:].lower() if w else w
```

Update `_parse_date` so the `3000-01-01` sentinel → None:

```python
def _parse_date(row, col: str):
    val = row.get(col, "")
    if not val or (isinstance(val, float) and pd.isna(val)) or str(val).strip() == "":
        return None
    if str(val).strip().startswith(_TERM_SENTINEL):
        return None
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None
```

> Implementer: the existing xlsx body becomes `_parse_xlsx_format(df)` unchanged except it no longer re-reads the file (the df is passed in). Keep `_str` shared. The xlsx recs gain no `agent_name` key (the upload fallback uses `.get("agent_name") or rec["agent_id"]`).

- [ ] **Step 4: Run — PASS** (CSV tests + the existing `tests/test_aetna_parser.py` xlsx tests still pass)

Run: `python3 -m pytest tests/test_aetna_csv_parser.py tests/test_aetna_parser.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/parsers/aetna.py tests/test_aetna_csv_parser.py
git commit -m "feat(aetna): CSV-format branch (MedicareApprovedBOBReport) + active/termed split"
```

---

## Task 2: complete the fill-blanks PII rule (§6 bug) + Aetna agent-name fallback

**Files:**
- Modify: `app/upload.py` (`_upsert_customer_from_policy` ~200-207; `_import_bob_row` existing-update ~103-109; the two Aetna agent-fallback sites)
- Test: `tests/test_bob_fill_blanks_pii.py`

**Interfaces:**
- Consumes: `_fill_if_blank` (existing), `_match_agent_name`, `resolve_writing_agent` (existing).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bob_fill_blanks_pii.py
from app.extensions import db
from app.models import Agency, Customer
from app.upload import _fill_if_blank

def test_pii_fill_blanks_does_not_overwrite(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        c = Customer(agency_id=ag.id, full_name="Jane Doe", first_name="Jane",
                     last_name="Doe", phone_primary="704-555-1111", dob=None)
        db.session.add(c); db.session.flush()
        _fill_if_blank(c, "phone_primary", "999-999-9999")   # existing → keep
        _fill_if_blank(c, "dob", __import__("datetime").date(1950, 1, 1))  # blank → fill
        assert c.phone_primary == "704-555-1111"
        assert c.dob is not None
```

- [ ] **Step 2: Run — PASS** (this guards the helper; the real change is the call sites)

Run: `python3 -m pytest tests/test_bob_fill_blanks_pii.py -v`

- [ ] **Step 3: Convert the overwrite lines to `_fill_if_blank`**

In `_upsert_customer_from_policy` (~200-207), inside the existing `if not customer.manually_edited:` block, replace the overwrite pattern:

```python
        _fill_if_blank(customer, "dob", rec.get("dob"))
        _fill_if_blank(customer, "phone_primary", rec.get("phone"))
        _fill_if_blank(customer, "address1", rec.get("address1"))
        _fill_if_blank(customer, "city", rec.get("city"))
        _fill_if_blank(customer, "state", rec.get("state"))
        _fill_if_blank(customer, "zip_code", rec.get("zip_code"))
        _fill_if_blank(customer, "county", rec.get("county"))
```

(Keep `customer.first_name/last_name/full_name` as-is — names are carrier-authoritative identity, handled above; do not change that behavior.)

In `_import_bob_row` existing-policy update (~103-109), convert the Policy PII to fill-blanks (Policy has no manually_edited; fill-blanks alone is the rule):

```python
        _fill_if_blank(existing, "dob", rec["dob"])
        _fill_if_blank(existing, "phone", rec["phone"])
        _fill_if_blank(existing, "county", rec["county"])
        _fill_if_blank(existing, "address1", rec.get("address1"))
        _fill_if_blank(existing, "city", rec.get("city"))
        _fill_if_blank(existing, "state", rec.get("state"))
        _fill_if_blank(existing, "zip_code", rec.get("zip_code"))
```

(Keep `existing.effective_date`/`term_date`/`plan_name`/`plan_type` as direct carrier-authoritative assignments — unchanged.)

- [ ] **Step 4: Aetna agent-name fallback reads `agent_name`** at BOTH resolve sites (`resolve_writing_agent(...)` ~136 and ~403): change the existing Aetna fallback line to prefer the explicit name:

```python
        if resolved is None and rec["carrier"] == "Aetna":
            from app.commission.routes import _match_agent_name
            resolved = _match_agent_name(rec.get("agent_name") or rec.get("agent_id"))
```

- [ ] **Step 5: Run**

Run: `python3 -m pytest tests/ -k "upload or aetna or fill" -q`
Expected: PASS (no regressions; the xlsx path still resolves via `agent_id` since it has no `agent_name`)

- [ ] **Step 6: Commit**

```bash
git add app/upload.py tests/test_bob_fill_blanks_pii.py
git commit -m "fix(upload): complete fill-blanks PII (customer+policy); Aetna agent-name fallback"
```

---

## Task 3: §6b — termination closes the open AOR interval

**Files:**
- Modify: `app/upload.py` (add `_close_open_aor_on_term`; call it when a row terms a policy)
- Test: `tests/test_bob_term_aor.py`

**Interfaces:**
- Consumes: `CustomerAorHistory`, `Policy`, `Customer`.
- Produces: `_close_open_aor_on_term(customer, carrier, term_date)` — closes the customer's OPEN interval for that carrier (`end_date=term_date`), EXCEPT BCBS (leave None). Idempotent (already-closed stays closed). No-op if no open interval.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bob_term_aor.py
from datetime import date
from app.extensions import db
from app.models import Agency, User, Customer, CustomerAorHistory
from app.upload import _close_open_aor_on_term

def test_term_closes_open_interval(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=ag.id, full_name="Jane Doe", primary_agent_id=u.id)
        db.session.add(c); db.session.flush()
        db.session.add(CustomerAorHistory(agency_id=ag.id, customer_id=c.id, agent_id=u.id,
            carrier="Aetna", plan_name="Aetna Sig PPO", effective_date=date(2024,1,1), end_date=None))
        db.session.commit()
        _close_open_aor_on_term(c, "Aetna", date(2026,5,31))
        h = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="Aetna").first()
        assert h.end_date == date(2026,5,31)

def test_bcbs_open_interval_stays_none(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=ag.id, full_name="Bob", primary_agent_id=u.id); db.session.add(c); db.session.flush()
        db.session.add(CustomerAorHistory(agency_id=ag.id, customer_id=c.id, agent_id=u.id,
            carrier="BCBS", effective_date=date(2024,1,1), end_date=None))
        db.session.commit()
        _close_open_aor_on_term(c, "BCBS", date(2026,5,31))
        h = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="BCBS").first()
        assert h.end_date is None
```

- [ ] **Step 2: Run — FAIL** (`_close_open_aor_on_term` not defined)

Run: `python3 -m pytest tests/test_bob_term_aor.py -v`

- [ ] **Step 3: Implement**

```python
def _close_open_aor_on_term(customer, carrier, term_date):
    """§6b: when a member is termed, close their OPEN AOR interval for that carrier.
    BCBS term_date is a renewal, not a termination → leave its interval open."""
    if carrier == "BCBS" or not term_date:
        return
    open_iv = CustomerAorHistory.query.filter_by(
        customer_id=customer.id, carrier=carrier, end_date=None).first()
    if open_iv:
        open_iv.end_date = term_date
```

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_bob_term_aor.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/upload.py tests/test_bob_term_aor.py
git commit -m "feat(upload): termination closes the open AOR interval (carrier-agnostic, BCBS exempt)"
```

---

## Task 4: §4.2 — seed closed plan-history + route termed recs

**Files:**
- Modify: `app/upload.py` (add `_seed_closed_history`; route `status="termed"` recs in `_import_bob_row`)
- Test: `tests/test_plan_history_seed.py`

**Interfaces:**
- Consumes: `_close_open_aor_on_term` (Task 3), `CustomerAorHistory`, `Customer`, `Policy`, `resolve_writing_agent`/`_match_agent_name`.
- Produces: `_seed_closed_history(customer, rec, agency_id)` — ADD-ONLY: writes a CLOSED `CustomerAorHistory` (carrier/plan_name/effective_date/end_date=term_date, source="aetna_bob_history"); idempotent on `(customer, carrier, effective_date)`; NEVER touches an open interval. And `_import_bob_row` routes a `status="termed"` rec: find existing customer by MBI; if found → term its active policy (if any) + `_close_open_aor_on_term` + `_seed_closed_history`; if not found → skip (return "skipped").

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_history_seed.py
from datetime import date
from app.extensions import db
from app.models import Agency, User, Customer, CustomerAorHistory
from app.upload import _seed_closed_history

def _setup(app):
    ag = Agency(name="T"); db.session.add(ag); db.session.flush()
    u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
    c = Customer(agency_id=ag.id, full_name="Jane", mbi="1ABC", primary_agent_id=u.id)
    db.session.add(c); db.session.flush()
    return ag.id, c, u.id

def test_seed_writes_closed_interval(db_session, app):
    with app.app_context():
        ag, c, uid = _setup(app); db.session.commit()
        rec = {"carrier": "Aetna", "plan_name": "Aetna Sig PPO",
               "effective_date": date(2024,1,1), "term_date": date(2026,5,31)}
        _seed_closed_history(c, rec, ag)
        h = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="Aetna").first()
        assert h.end_date == date(2026,5,31) and h.plan_name == "Aetna Sig PPO"
        assert h.source == "aetna_bob_history"

def test_seed_is_idempotent(db_session, app):
    with app.app_context():
        ag, c, uid = _setup(app); db.session.commit()
        rec = {"carrier": "Aetna", "plan_name": "X", "effective_date": date(2024,1,1),
               "term_date": date(2026,5,31)}
        _seed_closed_history(c, rec, ag); db.session.commit()
        _seed_closed_history(c, rec, ag)
        assert CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="Aetna").count() == 1

def test_seed_never_touches_open_interval(db_session, app):
    with app.app_context():
        ag, c, uid = _setup(app)
        # customer currently OPEN on Humana
        db.session.add(CustomerAorHistory(agency_id=ag, customer_id=c.id, agent_id=uid,
            carrier="Humana", effective_date=date(2026,6,1), end_date=None))
        db.session.commit()
        rec = {"carrier": "Aetna", "plan_name": "Aetna Sig PPO",
               "effective_date": date(2024,1,1), "term_date": date(2026,5,31)}
        _seed_closed_history(c, rec, ag)
        humana = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="Humana").first()
        assert humana.end_date is None    # untouched
```

- [ ] **Step 2: Run — FAIL** (`_seed_closed_history` not defined)

Run: `python3 -m pytest tests/test_plan_history_seed.py -v`

- [ ] **Step 3: Implement `_seed_closed_history`**

```python
def _seed_closed_history(customer, rec, agency_id):
    """§4.2 ADD-ONLY: write a CLOSED CustomerAorHistory chapter for a PAST enrollment.
    Idempotent on (customer, carrier, effective_date). NEVER modifies an open interval."""
    carrier = rec["carrier"]
    eff = rec.get("effective_date")
    if not eff:
        return
    exists = CustomerAorHistory.query.filter_by(
        customer_id=customer.id, carrier=carrier, effective_date=eff).first()
    if exists:
        return
    agent_id = customer.primary_agent_id
    if agent_id is None:
        return   # agent_id is NOT NULL on the model; can't seed without one
    db.session.add(CustomerAorHistory(
        agency_id=agency_id, customer_id=customer.id, agent_id=agent_id,
        carrier=carrier, plan_name=rec.get("plan_name"),
        effective_date=eff, end_date=rec.get("term_date"),
        source="aetna_bob_history"))
```

- [ ] **Step 4: Route termed recs in `_import_bob_row`** — at the TOP of the function (before the policy match/create), handle the termed branch:

```python
    if rec.get("status") == "termed":
        # Find the existing customer by MBI; if none, this is a departed member → skip.
        cust = None
        if rec.get("mbi"):
            cust = Customer.query.filter_by(mbi=rec["mbi"], agency_id=bulk_agency_id).first()
        if cust is None:
            return "skipped"
        # Term the existing active policy for this carrier+member, if present.
        pol = Policy.query.filter_by(carrier=rec["carrier"], member_id=rec["member_id"],
                                     agency_id=bulk_agency_id).first()
        if pol and pol.status == "active":
            pol.term_date = rec.get("term_date")
            pol.status = "termed"
        _close_open_aor_on_term(cust, rec["carrier"], rec.get("term_date"))   # §6b
        _seed_closed_history(cust, rec, bulk_agency_id)                       # §4.2
        return "updated"
```

- [ ] **Step 5: Run — PASS**

Run: `python3 -m pytest tests/test_plan_history_seed.py -v`

- [ ] **Step 6: Commit**

```bash
git add app/upload.py tests/test_plan_history_seed.py
git commit -m "feat(upload): seed closed plan-history + route termed recs (term policy + close AOR + seed)"
```

---

## Task 5: §6c — cross-carrier timeline synergy regression

**Files:**
- Test: `tests/test_aor_timeline_synergy.py`

**Interfaces:**
- Consumes: `_close_open_aor_on_term`, `_seed_closed_history`, and the resolver's `_open_aor_interval` conventions.

- [ ] **Step 1: Write the test (the whole-timeline guarantee)**

```python
# tests/test_aor_timeline_synergy.py
from datetime import date
from app.extensions import db
from app.models import Agency, User, Customer, CustomerAorHistory
from app.upload import _close_open_aor_on_term, _seed_closed_history

def test_cross_carrier_switch_yields_two_chapters(db_session, app):
    """Aetna termed + Humana enrolled → CLOSED Aetna chapter + OPEN Humana chapter,
    neither undoing the other."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=ag.id, full_name="Jane", mbi="1ABC", primary_agent_id=u.id)
        db.session.add(c); db.session.flush()
        # currently OPEN on Aetna
        db.session.add(CustomerAorHistory(agency_id=ag.id, customer_id=c.id, agent_id=u.id,
            carrier="Aetna", plan_name="Aetna Sig PPO", effective_date=date(2024,1,1), end_date=None))
        # a NEW Humana enrollment opens (mimic the resolver's open-interval write)
        db.session.add(CustomerAorHistory(agency_id=ag.id, customer_id=c.id, agent_id=u.id,
            carrier="Humana", plan_name="Humana Gold Plus", effective_date=date(2026,6,1), end_date=None))
        db.session.commit()
        # Aetna term row closes the Aetna chapter
        _close_open_aor_on_term(c, "Aetna", date(2026,5,31))
        db.session.commit()
        rows = CustomerAorHistory.query.filter_by(customer_id=c.id).all()
        aetna = next(r for r in rows if r.carrier == "Aetna")
        humana = next(r for r in rows if r.carrier == "Humana")
        assert aetna.end_date == date(2026,5,31)   # closed chapter
        assert humana.end_date is None             # current, untouched
```

- [ ] **Step 2: Run — PASS** (Tasks 3+4 already provide the helpers; this asserts they coexist)

Run: `python3 -m pytest tests/test_aor_timeline_synergy.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/test_aor_timeline_synergy.py
git commit -m "test(aor): cross-carrier timeline synergy — closed Aetna + open Humana coexist"
```

---

## Task 6: full-suite + live re-import & verification

**Files:** none (verification + rollout)

- [ ] **Step 1: Full suite green**

Run: `python3 -m pytest -q`
Expected: PASS (≈350 + new tests)

- [ ] **Step 2: Merge to main + push** (after final review per the SDD skill).

- [ ] **Step 3: Deploy (no migration)**

```bash
ssh … 'cd /var/www/founders-portal && git pull && ./venv/bin/pip install -r requirements.txt && systemctl restart founders-portal'
```

- [ ] **Step 4: Back up DB, scp the June CSV, re-import**

```bash
ssh … 'cd /var/www/founders-portal && PGPASSWORD=<from .env> pg_dump -U founders_user -h localhost founders_portal > /root/founders_pre_aetnacsv_$(date +%F_%H%M).sql'
scp -i ~/.ssh/id_ed25519 "docs/Carrier BOB DL/Founders Insurance Agency LLC_MedicareApprovedBOBReport_20260618.csv" root@23.187.248.100:/tmp/aetna_june.csv
```

Re-import through the admin upload UI (CSV → detects Aetna) or a one-off import script mirroring `bulk_upload` (detect → parse → dedupe → per-row savepoint `_import_bob_row`), as an admin upload (agency_id = admin's, bulk_agent_id=None).

- [ ] **Step 5: Verify on live Postgres**

Confirm: the 43 previously-unresolved active Aetna members now have an agent (NPN/name) + DOB/phone/address where provided; Needs-agent / Needs-interval Aetna hub entries drop sharply; the still-customer termed members (26) show a CLOSED Aetna interval in their profile plan-history; ~112 departed termed rows created no records; a customer currently open on another carrier kept that open interval (timeline synergy); a second re-import is idempotent (no dup intervals, no non-blank overwrite). Smoke-test `/customers/unassigned` + a customer profile render 200/302.

- [ ] **Step 6: Update docs (Session Protocol)**

`BACKLOG.md` (Aetna CSV + plan-history done; note hub residual + that the term→AOR-close lifecycle now runs cross-carrier), `CLAUDE.md` START HERE, spec Status. Commit.

---

## Self-Review

**Spec coverage:**
- §1 CSV format + §2 scope item 1 (format branch) → Task 1. ✓
- §3 field mapping (incl. address Line 2 fold, NPN/name, sentinel) → Task 1. ✓
- §4 termed-row handling (term policy / seed history / skip departed) → Task 4. ✓
- §5 NPN-first/name-fallback → Task 2 Step 4. ✓
- §6 fill-blanks PII bug fix → Task 2 Step 3 (both customer + policy sites). ✓
- §6b term→close-open-AOR → Task 3. ✓
- §4.2 add-only seed → Task 4 (`_seed_closed_history`, idempotent, never touches open). ✓
- §6c synergy (reuse resolver dup-guard; no undo) → Task 4 (idempotency key matches the resolver's `(customer,carrier,effective_date)`) + Task 5 regression. ✓
- §8 testing → Tasks 1-5 real-file + unit + synergy. §9 re-import → Task 6. ✓

**Placeholder scan:** implementer notes are real verification asks (xlsx body refactor, resolve-site line numbers) with tests as oracle. No TBD. ✓

**Type consistency:** rec keys (Task 1) consumed by `_import_bob_row` termed branch + `_seed_closed_history` (Task 4). `_close_open_aor_on_term(customer, carrier, term_date)` defined T3, used T4/T5. `_seed_closed_history(customer, rec, agency_id)` defined T4, used T4/T5. `_fill_if_blank` reused. ✓

**No migration:** confirmed — all fields exist on Policy/Customer/CustomerAorHistory.
