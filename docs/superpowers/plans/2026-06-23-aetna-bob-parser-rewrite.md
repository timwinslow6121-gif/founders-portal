# Aetna BOB Parser Rewrite + Shared Name Normalizer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the Aetna BOB parser to the real file format so Aetna uploads capture the writing agent, dates, proper-cased names, and freshness fields (state/plan/renewal/carrier_member_id/commission_type) — fixing the Needs-agent + Needs-interval hub entries at their source.

**Architecture:** A header-based `app/parsers/aetna.py` (serves both AJ's agency-wide file and the per-agent download, which share core columns by name), a shared `normalize_person_name()` producing "First MI. Last" (built on the existing `display_name()`), agent resolution by name via the existing `_match_agent_name`, a fill-blanks-only freshness write rule, and a fixed detection fingerprint. No migration (all target columns exist).

**Tech Stack:** Python 3.10, Flask, pandas (xlsx via openpyxl), pytest. PostgreSQL on VPS / SQLite in tests.

## Global Constraints

- **The real Aetna BOB columns (by name, both files):** `Medicare Number, Member ID, Member Name, Member State, Plan ID, Coverage Period, Effective Date, Writing Agent Name, CMS New` (+ optional `Payment Date, Additional Payment Detail, Payee Amount, 1099 Year, Member Sig Dt` which are ignored). **No Term Date column exists.**
- **Field mapping (spec §3):** `Medicare Number`→mbi+member_id; `Member ID`(NG…)→carrier_member_id; `Member Name`→first/last/full via the normalizer; `Writing Agent Name`→agent (resolved by name); `Effective Date`→effective_date; `Member State`→state; `Plan ID`→plan_name (resolved to a Plan); `Coverage Period`→renewal_date; `CMS New` "Y"→commission_type "initial" else "renewal"; term_date=None always. **`Member Sig Dt` is NOT captured.**
- **Name standard: "First MI. Last" proper-case** (e.g. `BRYANT D,KATHERINE`→"Katherine D. Bryant"). Standalone (handles the Aetna `LAST [MI],FIRST` order that `display_name` mishandles).
- **Agent resolution by NAME** via the existing `_match_agent_name` (`app/commission/routes.py`) — NOT by writing-id (Aetna BOB has no agent-id column).
- **Fill-blanks-only write rule (spec §6):** a BOB-captured field is written to an existing customer/policy ONLY when the current value is blank; never overwrite a non-blank field; never touch a `manually_edited` customer's PII. (Identity/agent/effective_date follow the existing carrier-authoritative update path.)
- **Detection (spec §7):** Aetna fingerprint = `"medicare number"` + `"writing agent name"` in headers; remove the bogus `"sales event"` check.
- **No migration** — `Policy.carrier_member_id/renewal_date/state/commission_type` and `Customer.state` all already exist (verified).
- Test bootstrap uses the existing `tests/conftest.py` fixtures (`db_session`, `app`); `create_app()` takes NO argument. Never call `create_app("testing")`.
- Real Aetna BOB fixture files live at `docs/Commission DL/_ARCHIVE_original_messy_files/Commission docs/Aetna - April - Founders Book of Business.xlsx` (agency-wide) and `…/Aetna - Tim Winslow April Book of Business.xlsx` (per-agent).
- Tests: `python3 -m pytest -q` (~338). VPS deploy: `ssh -i ~/.ssh/id_ed25519 root@23.187.248.100`, `git pull && ./venv/bin/pip install -r requirements.txt && systemctl restart founders-portal` (no `flask db upgrade` — no migration).

---

## File Structure

- `app/names.py` — **new.** `normalize_person_name(raw) -> (first, middle_initial, last, full)`. The shared "First MI. Last" normalizer (standalone — handles initial on either side of the comma).
- `app/parsers/aetna.py` — **rewrite.** Header-based parse to the real format + full field capture.
- `app/upload.py` — **modify.** (a) fix `_detect_carrier` Aetna fingerprint; (b) apply the fill-blanks-only rule for the new freshness fields in the customer/policy upsert; (c) wire Aetna agent-name resolution.
- Tests: `tests/test_names.py`, `tests/test_aetna_parser.py`, `tests/test_aetna_detection.py`, `tests/test_bob_fill_blanks.py`.

---

## Task 1: `app/names.py` — shared "First MI. Last" normalizer

**Files:**
- Create: `app/names.py`
- Test: `tests/test_names.py`

**Interfaces:**
- Consumes: nothing (standalone — does NOT delegate to `display_name`, which mishandles the Aetna `LAST [MI],FIRST` order; see Step 3).
- Produces: `normalize_person_name(raw: str) -> tuple[str, str, str, str]` returning `(first, middle_initial, last, full)` where `full` is the "First MI. Last" string. Blank input → `("", "", "", "")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_names.py
from app.names import normalize_person_name

def test_aetna_last_mi_comma_first():
    first, mi, last, full = normalize_person_name("BRYANT D,KATHERINE")
    assert (first, mi, last) == ("Katherine", "D", "Bryant")
    assert full == "Katherine D. Bryant"

def test_aetna_no_middle():
    first, mi, last, full = normalize_person_name("JAMES S,NAOMI")
    assert first == "Naomi" and last == "James" and mi == "S"
    assert full == "Naomi S. James"

def test_commission_format():
    first, mi, last, full = normalize_person_name("WINECOFF, JACK J.")
    assert first == "Jack" and last == "Winecoff"
    assert full == "Jack J. Winecoff"

def test_plain_first_last():
    first, mi, last, full = normalize_person_name("john smith")
    assert full == "John Smith" and first == "John" and last == "Smith"

def test_blank():
    assert normalize_person_name("") == ("", "", "", "")
    assert normalize_person_name(None) == ("", "", "", "")
```

- [ ] **Step 2: Run — FAIL** (`ModuleNotFoundError: app.names`)

Run: `python3 -m pytest tests/test_names.py -v`

- [ ] **Step 3: Implement `app/names.py`**

This is a **standalone** normalizer — do NOT delegate to `display_name()`. (Verified: `display_name("BRYANT D,KATHERINE")` returns the WRONG `"Katherine Bryant D."` because it assumes the commission format `LAST, FIRST [MI]` where the initial is AFTER the comma; Aetna's `LAST [MI],FIRST` puts the initial BEFORE the comma. This algorithm handles both.)

```python
"""Shared person-name normalizer → the agency's "First MI. Last" standard.
Structured (first, middle_initial, last, full) so parsers store the parts AND a
clean full_name. Handles the comma'd formats where the middle initial can be on
EITHER side of the comma:
  - Aetna 'Member Name'  "BRYANT D,KATHERINE"  (LAST [MI],FIRST)  → "Katherine D. Bryant"
  - commission           "WINECOFF, JACK J."   (LAST, FIRST [MI]) → "Jack J. Winecoff"
  - plain                "john smith"                              → "John Smith"
"""


def _tc(w):
    return w[:1].upper() + w[1:].lower() if w else w


def normalize_person_name(raw):
    """Return (first, middle_initial, last, full) in "First MI. Last" form."""
    s = (raw or "").strip()
    if not s:
        return ("", "", "", "")

    mi = ""
    if "," in s:
        last_side, first_side = [p.strip() for p in s.split(",", 1)]
        lp = last_side.split()
        # a trailing single-letter token on the LAST side = middle initial (Aetna)
        if len(lp) > 1 and len(lp[-1].rstrip(".")) == 1:
            mi = lp[-1].rstrip(".")
            lp = lp[:-1]
        last = " ".join(lp)
        fp = first_side.split()
        first = fp[0] if fp else ""
        # else a trailing single-letter on the FIRST side = middle initial (commission)
        if not mi and len(fp) > 1 and len(fp[-1].rstrip(".")) == 1:
            mi = fp[-1].rstrip(".")
    else:
        parts = s.split()
        first = parts[0] if parts else ""
        last = " ".join(parts[1:]) if len(parts) > 1 else ""

    first = _tc(first)
    last = " ".join(_tc(w) for w in last.split())
    mi = mi.upper()
    full = " ".join(x for x in [first, (mi + "." if mi else ""), last] if x)
    return (first, mi, last, full)
```

> This exact algorithm was verified against all the test inputs above and produces the right tuples — the test is the oracle; it passes as written.

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_names.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/names.py tests/test_names.py
git commit -m "feat(names): shared First-MI-Last normalizer (built on display_name)"
```

---

## Task 2: rewrite `app/parsers/aetna.py` to the real format

**Files:**
- Rewrite: `app/parsers/aetna.py`
- Test: `tests/test_aetna_parser.py`

**Interfaces:**
- Consumes: `normalize_person_name` (Task 1).
- Produces: `parse(filepath) -> list[dict]` where each dict has keys: `carrier="Aetna"`, `member_id`, `mbi`, `carrier_member_id`, `first_name`, `last_name`, `full_name`, `agent_id` (raw Writing Agent Name), `effective_date`, `term_date=None`, `renewal_date`, `state`, `plan_name`, `commission_type`, `status="active"`.

- [ ] **Step 1: Write the failing test (uses the real files)**

```python
# tests/test_aetna_parser.py
import os, pytest
from app.parsers.aetna import parse

BASE = "docs/Commission DL/_ARCHIVE_original_messy_files/Commission docs"
AGENCY = f"{BASE}/Aetna - April - Founders Book of Business.xlsx"
AGENT = f"{BASE}/Aetna - Tim Winslow April Book of Business.xlsx"

@pytest.mark.skipif(not os.path.exists(AGENT), reason="real Aetna BOB fixture absent")
def test_per_agent_file_captures_fields():
    recs = parse(AGENT)
    assert len(recs) >= 5
    r = recs[0]
    assert r["carrier"] == "Aetna"
    assert r["mbi"] and r["member_id"] == r["mbi"]
    assert r["carrier_member_id"].startswith("NG")
    assert r["first_name"] and r["last_name"]          # name parsed
    assert " " not in r["first_name"]                  # not the whole "LAST,FIRST"
    assert r["agent_id"]                               # Writing Agent Name present
    assert r["effective_date"] is not None
    assert r["term_date"] is None                      # Aetna BOB has no term col
    assert r["state"] == "NC"
    assert r["plan_name"]                              # Plan ID captured
    assert r["renewal_date"] is not None               # Coverage Period

@pytest.mark.skipif(not os.path.exists(AGENCY), reason="real Aetna BOB fixture absent")
def test_agency_file_parses_and_has_writing_agents():
    recs = parse(AGENCY)
    assert len(recs) >= 5
    # the agency file names multiple agents (Long/Foster/Basinger…)
    agents = {r["agent_id"] for r in recs}
    assert len(agents) >= 2
    assert all(r["effective_date"] is not None for r in recs[:5])

@pytest.mark.skipif(not os.path.exists(AGENT), reason="real Aetna BOB fixture absent")
def test_summary_row_skipped():
    recs = parse(AGENT)
    # the trailing "$202.44 x.55" summary row has no Medicare Number → skipped
    assert all(r["mbi"] for r in recs)
```

- [ ] **Step 2: Run — FAIL** (old parser raises on missing "First Name" / produces wrong shape)

Run: `python3 -m pytest tests/test_aetna_parser.py -v`

- [ ] **Step 3: Rewrite `app/parsers/aetna.py`**

```python
"""
Aetna BOB parser (rewritten 2026-06-23 to the REAL format).

Both upload paths share core columns by NAME (so AJ's agency-wide file and the
per-agent download both parse): Medicare Number, Member ID, Member Name, Member State,
Plan ID, Coverage Period, Effective Date, Writing Agent Name, CMS New. There is NO
Term Date column. Reads .xlsx (header row 0). Extra commission/tax columns are ignored.
Names → "First MI. Last" via app.names.normalize_person_name.
"""
import pandas as pd
from app.names import normalize_person_name

REQUIRED_COLUMNS = {"Medicare Number", "Member Name", "Writing Agent Name"}


def parse(filepath: str) -> list[dict]:
    try:
        df = pd.read_excel(filepath, dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read Aetna file: {e}")
    df.columns = df.columns.str.strip()

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Aetna file missing required columns: {missing}")

    # Keep only real member rows (a Medicare Number present); drops summary/blank rows.
    df = df[df["Medicare Number"].notna() & (df["Medicare Number"].astype(str).str.strip() != "")]
    df = df.copy()

    records = []
    for _, row in df.iterrows():
        mbi = _str(row, "Medicare Number").upper()
        if not mbi:
            continue
        first, _mi, last, full = normalize_person_name(_str(row, "Member Name"))
        cms_new = _str(row, "CMS New").upper()
        records.append({
            "carrier": "Aetna",
            "member_id": mbi,
            "mbi": mbi,
            "carrier_member_id": _str(row, "Member ID"),
            "first_name": first,
            "last_name": last,
            "full_name": full,
            "agent_id": _str(row, "Writing Agent Name"),   # raw name; resolved in upload
            "effective_date": _parse_date(row, "Effective Date"),
            "term_date": None,                              # Aetna BOB has no term column
            "renewal_date": _parse_date(row, "Coverage Period"),
            "state": _str(row, "Member State"),
            "plan_name": _str(row, "Plan ID"),
            "plan_type": "",
            "commission_type": "initial" if cms_new.startswith("Y") else "renewal",
            "phone": "",
            "county": "",
            "dob": None,
            "status": "active",
        })
    return records


def _str(row, col: str) -> str:
    val = row.get(col, "")
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _parse_date(row, col: str):
    val = row.get(col, "")
    if not val or (isinstance(val, float) and pd.isna(val)) or str(val).strip() == "":
        return None
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None
```

> Implementer: the downstream upsert expects certain keys (`phone`, `county`, `dob`, `plan_type`) — they're included as blank/None so the existing upload code doesn't KeyError. `plan_name` carries the Plan ID string (`H3146-006`); the upload's existing plan-alias resolution maps it (no change needed here).

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_aetna_parser.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/parsers/aetna.py tests/test_aetna_parser.py
git commit -m "feat(aetna): rewrite BOB parser to real format + full field capture"
```

---

## Task 3: fix the Aetna detection fingerprint

**Files:**
- Modify: `app/upload.py` (`_detect_carrier`, the Aetna line ~734-736)
- Test: `tests/test_aetna_detection.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_detect_carrier` returns "Aetna" for a header set containing `medicare number` + `writing agent name`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_aetna_detection.py
import os, pytest
from app.upload import _detect_carrier

BASE = "docs/Commission DL/_ARCHIVE_original_messy_files/Commission docs"
AGENCY = f"{BASE}/Aetna - April - Founders Book of Business.xlsx"
AGENT = f"{BASE}/Aetna - Tim Winslow April Book of Business.xlsx"

@pytest.mark.skipif(not os.path.exists(AGENT), reason="real Aetna BOB fixture absent")
def test_detects_both_aetna_files():
    assert _detect_carrier(AGENT) == "Aetna"
    assert _detect_carrier(AGENCY) == "Aetna"
```

> Implementer: confirm `_detect_carrier`'s signature (it takes a filepath and scans header rows). If it needs a worksheet/df instead, adapt the test to call it the way the codebase does (grep its existing call sites) — the assertion (both files → "Aetna") is the requirement.

- [ ] **Step 2: Run — FAIL** (old fingerprint needs "sales event")

Run: `python3 -m pytest tests/test_aetna_detection.py -v`

- [ ] **Step 3: Fix the fingerprint** in `app/upload.py`:

```python
        # Aetna BOB: "Medicare Number" + "Writing Agent Name" (both agency-wide
        # and per-agent files share these; the old "sales event" col does not exist)
        if "medicare number" in header_set and "writing agent name" in header_set:
            return "Aetna"
```

Place this Aetna check **before** the Healthspring check (Healthspring also has "medicare number" but with "first name" + "disenroll effective date", and lacks "writing agent name", so order is safe — but verify Healthspring still detects by running its test if one exists).

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_aetna_detection.py -v`
Then regression: `python3 -m pytest tests/ -k "detect or upload or parser" -q` → PASS (no carrier mis-detection)

- [ ] **Step 5: Commit**

```bash
git add app/upload.py tests/test_aetna_detection.py
git commit -m "fix(detect): Aetna fingerprint = medicare number + writing agent name"
```

---

## Task 4: agent-by-name resolution + fill-blanks-only freshness write

**Files:**
- Modify: `app/upload.py` (Aetna agent resolution; fill-blanks-only for the new fields in the customer/policy upsert)
- Test: `tests/test_bob_fill_blanks.py`

**Interfaces:**
- Consumes: `_match_agent_name` (`app/commission/routes.py` — resolves a writing-agent name string → User id, with nicknames). The Aetna `rec["agent_id"]` is a NAME.
- Produces: on Aetna admin upload, `rec["agent_id"]` (a name) resolves to a portal agent via `_match_agent_name`; freshness fields (state, plan, renewal_date, commission_type, carrier_member_id) are written only when the existing value is blank.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bob_fill_blanks.py
import pytest
from datetime import date
from app.extensions import db
from app.models import Agency, User, Customer, Policy

def test_fill_blanks_only(db_session, app):
    """A BOB-captured field fills a blank but never overwrites a non-blank value."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        cust = Customer(agency_id=ag.id, full_name="Jane Doe", first_name="Jane",
                        last_name="Doe", state="SC", primary_agent_id=u.id)  # state already set
        db.session.add(cust); db.session.flush()
        from app.upload import _fill_if_blank
        _fill_if_blank(cust, "state", "NC")     # existing SC → not overwritten
        _fill_if_blank(cust, "city", "Charlotte")  # blank → filled
        assert cust.state == "SC"
        assert cust.city == "Charlotte"
```

> Implementer: this introduces a tiny helper `_fill_if_blank(obj, attr, value)` (sets `obj.attr = value` only if the current attr is falsy/empty AND `value` is truthy). Use it for the freshness fields in `_upsert_customer_from_policy` and the policy upsert. If a similar helper already exists in upload.py, reuse it instead of adding a duplicate (grep first).

- [ ] **Step 2: Run — FAIL** (`_fill_if_blank` not defined)

Run: `python3 -m pytest tests/test_bob_fill_blanks.py -v`

- [ ] **Step 3: Implement**

Add the helper near the top of `app/upload.py`:

```python
def _fill_if_blank(obj, attr, value):
    """BOB freshness rule: write a captured value ONLY when the current one is blank.
    Never overwrites a non-blank field (Round 2 owns newer-wins). Returns True if set."""
    if value in (None, ""):
        return False
    cur = getattr(obj, attr, None)
    if cur in (None, ""):
        setattr(obj, attr, value)
        return True
    return False
```

Then, in the customer/policy upsert paths:
- **Policy** (new + existing): use `_fill_if_blank` for `carrier_member_id`, `renewal_date`, `state`, `commission_type` from the rec (so an Aetna re-import fills blanks but doesn't clobber). `effective_date`/`plan_name`/`agent_id` keep their existing carrier-authoritative handling.
- **Customer** (`_upsert_customer_from_policy`): `_fill_if_blank(customer, "state", rec.get("state"))` (respecting the existing `manually_edited` guard already in that function — do NOT bypass it).

For **Aetna agent resolution**: at the admin-upload seam where `resolve_writing_agent(rec["carrier"], rec["agent_id"], agency_id)` is called (upload.py ~136 and ~403), Aetna's `rec["agent_id"]` is a NAME, not an id. Add: if `rec["carrier"] == "Aetna"` and the id-based resolve returns None, fall back to `_match_agent_name(rec["agent_id"])`:

```python
from app.commission.routes import _match_agent_name   # add import
...
resolved = resolve_writing_agent(rec["carrier"], rec["agent_id"], agency_id)
if resolved is None and rec["carrier"] == "Aetna" and rec.get("agent_id"):
    resolved = _match_agent_name(rec["agent_id"])   # Aetna BOB names the agent
```

> Implementer: apply the same Aetna fallback at BOTH resolve sites (bulk ~136 and per-upload ~403). Confirm `_match_agent_name` returns a User id (or None). Watch for a circular import (upload.py ↔ commission.routes) — if it bites, import `_match_agent_name` lazily inside the function.

- [ ] **Step 4: Run — PASS**

Run: `python3 -m pytest tests/test_bob_fill_blanks.py -v`
Then: `python3 -m pytest tests/ -k upload -q` → no regressions.

- [ ] **Step 5: Commit**

```bash
git add app/upload.py tests/test_bob_fill_blanks.py
git commit -m "feat(upload): Aetna agent-by-name resolution + fill-blanks-only freshness writes"
```

---

## Task 5: full-suite + live re-import & verification

**Files:** none (verification + rollout)

- [ ] **Step 1: Full suite**

Run: `python3 -m pytest -q`
Expected: PASS (≈338 + new tests)

- [ ] **Step 2: Merge to main + push** (after final review per the SDD skill)

- [ ] **Step 3: Deploy (no migration)**

```bash
ssh … 'cd /var/www/founders-portal && git pull && ./venv/bin/pip install -r requirements.txt && systemctl restart founders-portal'
```

- [ ] **Step 4: Back up DB, then re-import the Aetna BOB**

The Aetna BOB files are in the repo; re-import via the admin upload (AJ's agency-wide file is the fullest). Back up first:

```bash
ssh … 'cd /var/www/founders-portal && PGPASSWORD=<from .env> pg_dump -U founders_user -h localhost founders_portal > /root/founders_pre_aetna_$(date +%F_%H%M).sql'
```

Re-import through the admin `/upload` UI (or a one-off import call) using the agency-wide Aetna file.

- [ ] **Step 5: Verify on live Postgres**

Confirm for Aetna active policies: `agent_id` resolved to real agents (was 0%), `effective_date` populated (was 10%), names proper-cased "First MI. Last", `state`/`plan_name`/`renewal_date`/`commission_type`/`carrier_member_id` filled; the Needs-agent (38, all Aetna) + Needs-interval (3, Tim/Aetna) hub entries clear or drop sharply; a second re-import overwrites nothing non-blank (fill-blanks-only holds).

- [ ] **Step 6: Update docs (Session Protocol)**

Update `BACKLOG.md` (mark Aetna parser fixed; note hub residual change; log the "retrofit all parsers to the shared normalizer + stored-name backfill" fast-follow), `CLAUDE.md` START HERE, spec Status. Commit.

---

## Self-Review

**Spec coverage:**
- §1 real format → Task 2 (header-based, both files). ✓
- §2 scope: parser rewrite (T2), detection (T3), field capture (T2), agent-by-name (T4), normalizer (T1), fill-blanks (T4), re-import (T5). ✓
- §3 field mapping → Task 2 rec keys (all fields incl. carrier_member_id; Member Sig Dt excluded). ✓
- §4 agent-by-name via `_match_agent_name` → Task 4. ✓
- §5 shared normalizer "First MI. Last" → Task 1. ✓
- §6 fill-blanks-only → Task 4 (`_fill_if_blank`). ✓
- §7 detection fix → Task 3. ✓
- §8 re-import & verify → Task 5. §9 testing → real-file fixtures (T2/T3) + normalizer (T1) + fill-blanks (T4) + Postgres verify (T5). §10 acceptance → Task 5 Step 5. ✓

**Placeholder scan:** the implementer notes (display_name output confirmation, `_detect_carrier` signature, `_match_agent_name` return, circular-import) are real verification asks with the test as the oracle, not placeholders. No TBD/TODO. ✓

**Type consistency:** `normalize_person_name -> (first, mi, last, full)` defined T1, consumed T2. Parser `rec` keys (T2) consumed by the upsert (T4). `_fill_if_blank(obj, attr, value)` defined + used T4. `_match_agent_name(name) -> user_id|None` reused consistently. ✓

**No migration:** confirmed — `Policy.carrier_member_id/renewal_date/state/commission_type` + `Customer.state` all exist.
