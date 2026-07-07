# Contract-Code Plan Database — Layer 1 (Data Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every active policy a correct link to the right *year's* Plan (`plan_id`), a captured full 3-part `contract_code`, and a `plan_year`, so contract-code customer counts become complete and accurate — the data foundation for the whole contract-code plan database.

**Architecture:** Add `Policy.contract_code` + `Policy.plan_year` + `Plan.needs_review` (migration 035). A new `app/plan_codes.py` module: `classify_plan` (year_bound vs medigap vs named, keyword-based since plan_type is messy), per-carrier code extraction (Humana/Healthspring regex on plan_name incl. underscore form; Aetna `CMS Contract Number`+`PBP Code`), and `plan_identity` (the plan-type-branched identity). BOB upload sets `contract_code`+`plan_year`, resolves `plan_id` by the identity (year-bound: `(carrier, cms_plan_id, year)`; medigap: `(carrier, plan_letter, PERPETUAL)`; named: `(carrier, plan_name, PERPETUAL)`), auto-creating a `needs_review` Plan when the identity has a key but no Plan. Year-bound rows with no extractable code (UHC/BCBS friendly names) fall to alias-match, else remain orphaned + reported. A one-time read-only `scripts/repair_plan_id_linkage.py` backfills existing orphans using the SAME resolver.

**Tech Stack:** Python 3.10, Flask-SQLAlchemy, Flask-Migrate (Alembic), PostgreSQL 16 (prod) / SQLite (tests), pytest, openpyxl/pandas.

## Global Constraints

- Unique plan identity = `(carrier, cms_plan_id, year)`. The `Plan` model already has `UniqueConstraint("agency_id","carrier","cms_plan_id","year", name="uq_plan_carrier_year")`.
- `plan_year` = the year of the BOB snapshot the policy was seen in, NOT `effective_date`'s year. `effective_date` (enrollment start / tenure) is untouched by this work.
- Contract code stored full 3-part where available (`H1036-335-001`); counting keys on `(year, cms_plan_id)` (2-part). The segment must never be discarded.
- Auto-created Plan rows carry `(carrier, cms_plan_id, year)` matching CMS import + BOB + commission keys, and are flagged `needs_review=True` (never presented as CMS-verified).
- Every query agency-scoped. The repair script is read-only planning + explicit `--apply`; DB backup first; dry-run → review WITH Tim → apply; real-Postgres verify.
- Migration head is currently `034`; new migration is `035`, `down_revision="034"`.
- Do NOT change `effective_date` handling, AOR logic, or the commission modules.
- **Per-carrier code-source reality (verified against the real July BOBs):** Humana embeds
  the code in `plan_name` (`H1036-335`); Aetna carries `CMS Contract Number`+`PBP Code`
  columns; Healthspring uses an underscore form (`H9725_015`) in some views. **UHC and BCBS
  BOBs carry NO CMS code** — only friendly names ("AARP Medicare Advantage from UHC NC-0015",
  "Blue Medicare Freedom+ PPO"). So those link ONLY by alias-match to a pre-seeded Plan;
  until their Plans+aliases exist, those policies remain a legitimate LEFTOVER (never a wrong
  link). The repair's leftover list is expected to be UHC/BCBS-heavy on a first run — that is
  correct, not a bug. `classify_plan` defaults unrecognized/blank plan_types to `year_bound`
  (they're annual-contract plans); it must NOT rely on `plan_type` alone (it's frequently the
  plan name or blank in real data).

---

### Task 1: Migration 035 + model columns (`Policy.contract_code`, `Policy.plan_year`, `Plan.needs_review`)

**Files:**
- Modify: `app/models.py` (Policy class + Plan class)
- Create: `migrations/versions/035_policy_contract_code_plan_year.py`
- Test: `tests/test_plan_codes.py`

**Interfaces:**
- Produces: `Policy.contract_code` (String(32), nullable, indexed), `Policy.plan_year` (Integer, nullable, indexed), `Plan.needs_review` (Boolean, default False, nullable=False).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_codes.py
def test_policy_and_plan_new_columns_exist(app, db_session):
    from app.models import Policy, Plan
    with app.app_context():
        p = Policy(carrier="Humana", member_id="M1", contract_code="H1036-335-001",
                   plan_year=2026, status="active")
        db_session.add(p); db_session.flush()
        got = Policy.query.filter_by(member_id="M1").first()
        assert got.contract_code == "H1036-335-001"
        assert got.plan_year == 2026
        pl = Plan(agency_id=1, carrier="Humana", plan_name="X", year=2026,
                  plan_type="mapd", needs_review=True)
        db_session.add(pl); db_session.flush()
        assert Plan.query.filter_by(plan_name="X").first().needs_review is True
```

(Use the project's existing `app` + `db_session` fixtures from `tests/conftest.py`. If they are named differently, adapt.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_plan_codes.py::test_policy_and_plan_new_columns_exist -v`
Expected: FAIL (`TypeError: 'contract_code' is an invalid keyword argument for Policy` or similar).

- [ ] **Step 3: Add the columns to the models**

In `app/models.py`, in the `Policy` class near `plan_name`/`plan_id`:

```python
    contract_code = db.Column(db.String(32), index=True)   # full 3-part CMS code H1036-335-001
    plan_year     = db.Column(db.Integer, index=True)       # BOB-snapshot year, NOT eff-date year
```

In the `Plan` class near `status`:

```python
    needs_review  = db.Column(db.Boolean, default=False, nullable=False)  # auto-created stub plan
```

- [ ] **Step 4: Create migration 035**

```python
# migrations/versions/035_policy_contract_code_plan_year.py
"""policy contract_code + plan_year, plan needs_review

Revision ID: 035
Revises: 034
"""
from alembic import op
import sqlalchemy as sa

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("policies", sa.Column("contract_code", sa.String(length=32)))
    op.add_column("policies", sa.Column("plan_year", sa.Integer()))
    op.create_index("ix_policies_contract_code", "policies", ["contract_code"])
    op.create_index("ix_policies_plan_year", "policies", ["plan_year"])
    op.add_column("plans", sa.Column("needs_review", sa.Boolean(),
                                     nullable=False, server_default=sa.false()))

def downgrade():
    op.drop_column("plans", "needs_review")
    op.drop_index("ix_policies_plan_year", table_name="policies")
    op.drop_index("ix_policies_contract_code", table_name="policies")
    op.drop_column("policies", "plan_year")
    op.drop_column("policies", "contract_code")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_plan_codes.py::test_policy_and_plan_new_columns_exist -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/models.py migrations/versions/035_policy_contract_code_plan_year.py tests/test_plan_codes.py
git commit -m "feat: Policy.contract_code + plan_year, Plan.needs_review (migration 035)"
```

---

### Task 2: `app/plan_codes.py` — per-carrier contract-code extraction

**Files:**
- Create: `app/plan_codes.py`
- Test: `tests/test_plan_codes.py`

**Interfaces:**
- Consumes: nothing (pure functions).
- Produces:
  - `PERPETUAL = 0` — the year sentinel for year-independent plans (Medigap/DVH/etc).
  - `extract_contract_code(carrier: str, rec: dict) -> Optional[str]` — the full contract code (`H1036-335-001` or 2-part `H1036-335`) for a BOB record, per carrier.
  - `cms_plan_id_of(contract_code: str) -> Optional[str]` — the 2-part `(contract, PBP)` key (`H1036-335`) from a full code, for Plan matching/counting.
  - `classify_plan(plan_type: str, plan_name: str) -> str` — returns `"medigap"` | `"named"` | `"year_bound"`. Because `plan_type` is a MESS in real data (often the plan NAME, blank, or a carrier code like AARPMODMEDSUP/MES/IDV), classification uses BOTH plan_type and plan_name keywords: medigap (supp/medsup/"plan G|N|F"/AARPMODMEDSUP/MES) → medigap; DVH/dental/vision/hospital-indemnity/IDV/GTL/"extend" → named; everything else → year_bound (the default — MA/MAPD/PDP/DSNP/CSNP and any unrecognized, since those are the annual-contract plans).
  - `medigap_letter(plan_name: str) -> Optional[str]` — the Medigap plan letter (G/N/F/...) from a plan name, else None.
  - `plan_identity(carrier: str, rec: dict, plan_year: int) -> dict` — the resolved identity for matching/creating a Plan. Returns `{"kind": "year_bound"|"medigap"|"named", "carrier": ..., "cms_plan_id": ...|None, "plan_letter": ...|None, "name_key": ...|None, "year": plan_year|PERPETUAL, "contract_code": ...|None}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_codes.py  (append)
def test_extract_humana_code_from_plan_name():
    from app.plan_codes import extract_contract_code, cms_plan_id_of
    rec = {"plan_name": "HUMANA GOLD PLUS HMO POS H1036-335"}
    assert extract_contract_code("Humana", rec) == "H1036-335"
    assert cms_plan_id_of("H1036-335-001") == "H1036-335"
    assert cms_plan_id_of("H1036-335") == "H1036-335"

def test_extract_aetna_code_from_contract_and_pbp():
    from app.plan_codes import extract_contract_code
    rec = {"plan_name": "Aetna Medicare Select (HMO-POS)",
           "cms_contract_number": "H5521", "pbp_code": "241"}
    assert extract_contract_code("Aetna", rec) == "H5521-241"

def test_extract_returns_none_when_no_code():
    from app.plan_codes import extract_contract_code
    assert extract_contract_code("UHC", {"plan_name": "AARP Medicare Advantage NC-0015"}) is None

def test_extract_handles_healthspring_underscore_code():
    # Healthspring uses H9725_015 (underscore) in some views — normalize to H9725-015
    from app.plan_codes import extract_contract_code
    rec = {"plan_name": "2026_NC_H9725_015_HealthSpring Preferred Savings (HMO)"}
    assert extract_contract_code("Healthspring", rec) == "H9725-015"

def test_classify_uses_name_when_plan_type_is_messy():
    from app.plan_codes import classify_plan
    # plan_type blank but name says supplement → medigap
    assert classify_plan("", "AARP MEDICARE SUPPLEMENT PLAN G") == "medigap"
    # carrier plan_type codes
    assert classify_plan("AARPMODMEDSUP", "") == "medigap"
    assert classify_plan("MES", "HUMANA MED SUPP PLAN G") == "medigap"
    # DVH / dental / hospital-indemnity / IDV → named
    assert classify_plan("DVH", "DVH 1000") == "named"
    assert classify_plan("Dental", "Dental Blue for Individuals PPO") == "named"
    assert classify_plan("IDV", "NC EXTEND 1250 MNTH DEL '23") == "named"
    # blank plan_type + an MA-looking name → year_bound (default)
    assert classify_plan("", "Blue Medicare Freedom+ PPO") == "year_bound"
    assert classify_plan("MA", "AARP Medicare Advantage from UHC NC-0001") == "year_bound"
    assert classify_plan("PDP", "HUMANA VALUE RX PLAN PDP") == "year_bound"

def test_generic_regex_picks_up_three_part_code():
    from app.plan_codes import extract_contract_code
    rec = {"plan_name": "Some Plan H1036-335-001 thing"}
    assert extract_contract_code("Humana", rec) == "H1036-335-001"

def test_medigap_letter_extraction():
    from app.plan_codes import medigap_letter
    assert medigap_letter("AARP MEDICARE SUPPLEMENT PLAN G") == "G"
    assert medigap_letter("MedSup N 2019") == "N"
    assert medigap_letter("HUMANA MED SUPP PLAN G") == "G"
    assert medigap_letter("Some Random Plan") is None

def test_plan_identity_year_bound_medigap_and_named():
    from app.plan_codes import plan_identity, PERPETUAL
    # year-bound MA → cms_plan_id + real year
    yb = plan_identity("Humana", {"plan_name": "HUMANA GOLD PLUS HMO POS H1036-335",
                                  "plan_type": "MAPD"}, 2026)
    assert yb["kind"] == "year_bound" and yb["cms_plan_id"] == "H1036-335" and yb["year"] == 2026
    # medigap → plan_letter + PERPETUAL, NOT the calendar year
    mg = plan_identity("BCBS", {"plan_name": "MEDSUP G 2019", "plan_type": "MS"}, 2026)
    assert mg["kind"] == "medigap" and mg["plan_letter"] == "G" and mg["year"] == PERPETUAL
    # DVH/named → name_key + PERPETUAL
    dv = plan_identity("UHC", {"plan_name": "DVH 1000", "plan_type": "DVH"}, 2026)
    assert dv["kind"] == "named" and dv["name_key"] and dv["year"] == PERPETUAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_plan_codes.py -k extract -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.plan_codes'`).

- [ ] **Step 3: Write the module**

```python
# app/plan_codes.py
"""Per-carrier CMS contract-code extraction. The contract code (H1036-335 or the
full 3-part H1036-335-001) is the plan identity (with year). Where the BOB carries
it in a dedicated column (Aetna) use that; where it is embedded in the plan_name
(Humana) extract it; else return None (UHC friendly names — resolved via alias)."""
import re
from typing import Optional

# H#### / S#### / R#### + PBP(3) + optional segment(3), separated by '-' OR '_'
# (Humana uses dashes: H1036-335; Healthspring uses underscores: H9725_015).
_CODE_RE = re.compile(r"([HSR]\d{4})[-_](\d{3})(?:[-_](\d{3}))?")


def _from_name(plan_name: str) -> Optional[str]:
    if not plan_name:
        return None
    m = _CODE_RE.search(plan_name.upper())
    if not m:
        return None
    # Normalize to dash form: H9725-015 or H1036-335-001
    parts = [m.group(1), m.group(2)] + ([m.group(3)] if m.group(3) else [])
    return "-".join(parts)


def extract_contract_code(carrier: str, rec: dict) -> Optional[str]:
    """Best contract code for a BOB record. Prefers a dedicated code column
    (Aetna CMS Contract Number + PBP Code), else regex on the plan name."""
    c = (carrier or "").strip().lower()
    if c == "aetna":
        contract = (rec.get("cms_contract_number") or "").strip().upper()
        pbp = (rec.get("pbp_code") or "").strip()
        if contract and pbp:
            return f"{contract}-{pbp.zfill(3)}"
        # fall through to name regex if the columns are absent
    return _from_name(rec.get("plan_name") or "")


def cms_plan_id_of(contract_code: str) -> Optional[str]:
    """The 2-part (contract, PBP) key used for Plan matching + counting."""
    if not contract_code:
        return None
    parts = contract_code.strip().upper().split("-")
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return None


PERPETUAL = 0   # year sentinel for plans whose benefits are NOT annual (medigap/DVH/etc.)

_MEDIGAP_LETTER_RE = re.compile(r"\bPLAN\s+([A-N])\b")

# Keyword signals. plan_type is unreliable (often the plan NAME, blank, or a carrier
# code), so classify on BOTH plan_type and plan_name text.
_MEDIGAP_KW = ("SUPP", "SUPPLEMENT", "MEDSUP", "AARPMODMEDSUP", "MES ", " MES", "MES")
_NAMED_KW = ("DVH", "DENTAL", "VISION", "HOSPITAL", "INDEMNITY", "IDV", "GTL", "EXTEND")


def classify_plan(plan_type: str, plan_name: str) -> str:
    """Which identity model applies: 'medigap' | 'named' | 'year_bound'. Uses keywords
    across plan_type AND plan_name because plan_type is messy in real data. year_bound
    is the DEFAULT (MA/MAPD/PDP/DSNP/CSNP + anything unrecognized — all annual contracts)."""
    blob = f"{plan_type or ''} {plan_name or ''}".upper()
    # medigap first (a supplement is never 'named'); the "PLAN G/N/F" pattern also = medigap
    if any(k in blob for k in _MEDIGAP_KW) or _MEDIGAP_LETTER_RE.search(blob):
        return "medigap"
    if any(k in blob for k in _NAMED_KW):
        return "named"
    return "year_bound"


def medigap_letter(plan_name: str) -> Optional[str]:
    m = _MEDIGAP_LETTER_RE.search((plan_name or "").upper())
    return m.group(1) if m else None


def _name_key(plan_name: str) -> str:
    """Normalized name key for year-independent named plans (DVH/dental/GTL)."""
    return " ".join((plan_name or "").upper().split())


def plan_identity(carrier: str, rec: dict, plan_year: int) -> dict:
    """Resolve the identity for matching/creating a Plan, branching on plan type.
    year_bound → cms_plan_id (may be None → caller alias-matches) + real year;
    medigap → plan_letter + PERPETUAL; named → name_key + PERPETUAL."""
    carrier = (carrier or "").strip()
    plan_type = rec.get("plan_type") or ""
    plan_name = rec.get("plan_name") or ""
    kind = classify_plan(plan_type, plan_name)
    if kind == "year_bound":
        code = extract_contract_code(carrier, rec)
        return {"kind": "year_bound", "carrier": carrier,
                "cms_plan_id": cms_plan_id_of(code) if code else None,
                "plan_letter": None, "name_key": None,
                "year": plan_year, "contract_code": code}
    if kind == "medigap":
        return {"kind": "medigap", "carrier": carrier, "cms_plan_id": None,
                "plan_letter": medigap_letter(plan_name), "name_key": None,
                "year": PERPETUAL, "contract_code": None}
    return {"kind": "named", "carrier": carrier, "cms_plan_id": None,
            "plan_letter": None, "name_key": _name_key(plan_name),
            "year": PERPETUAL, "contract_code": None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_plan_codes.py -k extract -v`
Expected: PASS (all 4)

- [ ] **Step 5: Commit**

```bash
git add app/plan_codes.py tests/test_plan_codes.py
git commit -m "feat: app/plan_codes.py — per-carrier code extraction + plan-type identity (year-bound vs medigap/named PERPETUAL)"
```

---

### Task 3: Aetna + UHC parsers emit the contract-code inputs

**Files:**
- Modify: `app/parsers/aetna.py` (add `cms_contract_number` + `pbp_code` to the record dict)
- Test: `tests/test_aetna_parser.py`

**Interfaces:**
- Consumes: `extract_contract_code` (Task 2) will read `rec["cms_contract_number"]` / `rec["pbp_code"]`.
- Produces: Aetna BOB records now include `cms_contract_number` and `pbp_code` keys (from the `CMS Contract Number` + `PBP Code` columns the real July Aetna BOB carries). Humana already embeds the code in `plan_name` (no parser change). UHC has no code column (no change — resolved via alias later).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_aetna_parser.py  (append)
def test_aetna_emits_contract_number_and_pbp(tmp_path):
    import openpyxl
    from app.parsers.aetna import parse
    p = tmp_path / "Aetna Book of Business.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Member ID", "Medicare Number", "First Name", "Last Name",
               "Coverage Effective Date", "Member Status", "Plan Name",
               "Writing Agent NPN", "Writing Agent First Name", "Writing Agent Last Name",
               "CMS Contract Number", "PBP Code"])
    ws.append(["NG1", "2AH6DF6NM54", "Denise", "Eddleman", "2026-07-01", "A",
               "Aetna Medicare Select (HMO-POS)", "123", "Justin", "Basinger",
               "H5521", "241"])
    wb.save(p)
    r = parse(str(p))[0]
    assert r["cms_contract_number"] == "H5521"
    assert r["pbp_code"] == "241"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_aetna_parser.py::test_aetna_emits_contract_number_and_pbp -v`
Expected: FAIL (KeyError / None — keys not emitted).

- [ ] **Step 3: Add the two fields to the Aetna record dicts**

In `app/parsers/aetna.py`, in BOTH `_parse_xlsx_format` and `_parse_csv_format`, add to the `records.append({...})` dict:

```python
            "cms_contract_number": _str(row, "CMS Contract Number"),
            "pbp_code": _str(row, "PBP Code"),
```

(These columns are absent in the old agency format — `_str` returns `""` there, which is fine; `extract_contract_code` falls back to the plan-name regex.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_aetna_parser.py -v`
Expected: PASS (new test + existing Aetna tests unchanged)

- [ ] **Step 5: Commit**

```bash
git add app/parsers/aetna.py tests/test_aetna_parser.py
git commit -m "feat: Aetna parser emits cms_contract_number + pbp_code for contract-code extraction"
```

---

### Task 4: BOB upload sets contract_code + plan_year and resolves plan_id by (code, year)

**Files:**
- Modify: `app/upload.py` (`_import_bob_row` — the Policy create/update block; `bulk_upload` — determine plan_year; add a Plan resolver by code+year)
- Test: `tests/test_bob_plan_linkage.py`

**Interfaces:**
- Consumes: `extract_contract_code`, `cms_plan_id_of` (Task 2); `Policy.contract_code`, `Policy.plan_year`, `Plan.needs_review` (Task 1).
- Produces: after a BOB import, each policy has `contract_code`, `plan_year`, and a `plan_id` linked to the `(carrier, cms_plan_id, plan_year)` Plan — auto-creating a `needs_review` Plan if none exists.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bob_plan_linkage.py
from datetime import date
import pytest

def _rec(**kw):
    base = {"carrier": "Humana", "member_id": "HM1", "mbi": "8QV9Q10TC36",
            "first_name": "A", "last_name": "B", "full_name": "A B",
            "plan_name": "HUMANA GOLD PLUS HMO POS H1036-335", "plan_type": "MAPD",
            "effective_date": date(2024, 1, 1), "term_date": None, "dob": None,
            "phone": "", "county": "", "agent_id": "", "status": "active"}
    base.update(kw); return base

def test_bob_row_sets_contract_code_plan_year_and_links_plan(db_session, app, agency, agent_user):
    """A Humana BOB row (code embedded in plan_name) gets contract_code + plan_year
    set, and links to the (carrier, cms_plan_id, year) Plan — auto-created (needs_review)
    when none exists. plan_year is the import year passed in, NOT the 2024 eff date."""
    from app.extensions import db
    from app.models import ImportBatch, Policy, Plan
    from app.upload import _import_bob_row
    with app.app_context():
        batch = ImportBatch(agency_id=agency.id, carrier="Humana", filename="h.xlsx",
                            uploaded_by_id=agent_user.id, status="pending")
        db.session.add(batch); db.session.commit()
        with db.session.begin_nested():
            # plan_year is a keyword arg (the import/snapshot year), passed by bulk_upload.
            _import_bob_row(_rec(), batch, agency.id, agent_user.id, date.today(), [],
                            plan_year=2026)
        db.session.commit()
        pol = Policy.query.filter_by(agency_id=agency.id, member_id="HM1").first()
        assert pol.contract_code == "H1036-335"
        assert pol.plan_year == 2026                    # import year, not eff-date 2024
        assert pol.plan_id is not None
        plan = Plan.query.get(pol.plan_id)
        assert plan.cms_plan_id == "H1036-335" and plan.year == 2026
        assert plan.needs_review is True                # auto-created

def test_medigap_bob_row_links_by_letter_and_perpetual_year(db_session, app, agency, agent_user):
    """A Medigap BOB row links to a (carrier, plan_letter, year=PERPETUAL) Plan —
    NOT split by calendar year. plan_year on the policy is the PERPETUAL sentinel."""
    from app.extensions import db
    from app.models import ImportBatch, Policy, Plan
    from app.upload import _import_bob_row
    from app.plan_codes import PERPETUAL
    with app.app_context():
        batch = ImportBatch(agency_id=agency.id, carrier="BCBS", filename="b.xlsx",
                            uploaded_by_id=agent_user.id, status="pending")
        db.session.add(batch); db.session.commit()
        rec = _rec(carrier="BCBS", member_id="BM1", mbi="9N85W96WY95",
                   plan_name="MEDSUP G 2019", plan_type="MS")
        with db.session.begin_nested():
            _import_bob_row(rec, batch, agency.id, agent_user.id, date.today(), [],
                            plan_year=2026)
        db.session.commit()
        pol = Policy.query.filter_by(agency_id=agency.id, member_id="BM1").first()
        assert pol.plan_year == PERPETUAL                 # not 2026 — medigap is year-independent
        plan = Plan.query.get(pol.plan_id)
        assert plan.plan_letter == "G" and plan.year == PERPETUAL and plan.plan_type == "medigap"
```

**Decision (resolves the plan_year source):** `_import_bob_row` gains a keyword-only
`plan_year` parameter (default `None` → the implementer defaults it to
`date.today().year` inside, so existing callers/tests that don't pass it still work).
`bulk_upload` computes `plan_year = date.today().year` and passes it. NO new ImportBatch
column (ImportBatch has none today, and a migration for it is unnecessary). The invariant:
**plan_year is the import/snapshot year, never the effective-date year.**

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bob_plan_linkage.py -v`
Expected: FAIL (contract_code None / plan_id None / no auto-created plan).

- [ ] **Step 3: Add a plan-resolver helper + wire it into `_import_bob_row`**

In `app/upload.py`, add a helper (near `_plan_alias_map`):

```python
def _resolve_or_create_plan(carrier, rec, plan_year, agency_id, alias_map):
    """Return (plan_id, contract_code) for this BOB row, branching on plan type:
    year-bound → match/create by (carrier, cms_plan_id, plan_year);
    medigap → by (carrier, plan_letter, year=PERPETUAL);
    named (DVH/dental/GTL) → by (carrier, plan_name, year=PERPETUAL).
    Auto-creates a needs_review Plan when none exists. Falls back to alias_map by
    plan_name when a year-bound row carries no extractable code (UHC friendly names)."""
    from app.plan_codes import plan_identity, PERPETUAL
    from app.models import Plan
    ident = plan_identity(carrier, rec, plan_year)
    plan = None
    if ident["kind"] == "year_bound":
        if ident["cms_plan_id"]:
            plan = Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                        cms_plan_id=ident["cms_plan_id"],
                                        year=ident["year"]).first()
            if plan is None:
                plan = Plan(agency_id=agency_id, carrier=carrier,
                            cms_plan_id=ident["cms_plan_id"], year=ident["year"],
                            plan_name=(rec.get("plan_name") or ident["cms_plan_id"]),
                            plan_type=(rec.get("plan_type") or "other"),
                            status="current", needs_review=True)
                db.session.add(plan); db.session.flush()
        else:
            # no code → alias match by plan_name (UHC etc.)
            pid = alias_map.get((rec.get("plan_name") or "").strip().lower())
            return pid, ident["contract_code"]
    elif ident["kind"] == "medigap" and ident["plan_letter"]:
        plan = Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                    plan_letter=ident["plan_letter"],
                                    year=PERPETUAL).first()
        if plan is None:
            plan = Plan(agency_id=agency_id, carrier=carrier,
                        plan_letter=ident["plan_letter"], year=PERPETUAL,
                        plan_name=(rec.get("plan_name") or f"Plan {ident['plan_letter']}"),
                        plan_type="medigap", status="current", needs_review=True)
            db.session.add(plan); db.session.flush()
    elif ident["kind"] == "named" and ident["name_key"]:
        plan = (Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                     year=PERPETUAL)
                .filter(db.func.upper(Plan.plan_name) == ident["name_key"]).first())
        if plan is None:
            plan = Plan(agency_id=agency_id, carrier=carrier, year=PERPETUAL,
                        plan_name=(rec.get("plan_name") or ""),
                        plan_type=(rec.get("plan_type") or "other"),
                        status="current", needs_review=True)
            db.session.add(plan); db.session.flush()
    return (plan.id if plan else None), ident["contract_code"]
```

Note: the `Plan` unique constraint is `(agency_id, carrier, cms_plan_id, year)`. Medigap/named
Plans have `cms_plan_id=NULL`, so multiple NULL-cms rows for the same carrier+year=PERPETUAL
do NOT collide on that constraint (Postgres treats NULLs as distinct in a unique index) —
which is why the match query filters on plan_letter / plan_name explicitly rather than
relying on the constraint. This is correct + intended.

Give `_import_bob_row` a keyword-only param: change its signature to end with
`..., unresolvable, *, plan_year=None, alias_map=None)` and, at the top, default
`plan_year = plan_year or date.today().year`. Thread `alias_map` from `bulk_upload`
(which already builds it via `_plan_alias_map`); if a caller passes `alias_map=None`,
rebuild it once inside. In `_import_bob_row`, where the Policy is created/updated, set the
three fields. For the NEW policy branch add to the `Policy(...)` kwargs:

```python
            contract_code=code,
            plan_year=effective_plan_year,
            plan_id=plan_id,
```

and for the EXISTING policy branch:

```python
        existing.contract_code = code or existing.contract_code
        existing.plan_year = effective_plan_year
        existing.plan_id = plan_id or existing.plan_id
```

where, computed once before both branches:

```python
    plan_id, code = _resolve_or_create_plan(rec["carrier"], rec, plan_year, agency_id, alias_map)
    # The policy's stored plan_year follows the plan-type identity: year-bound plans
    # store the import year; year-independent plans (medigap/DVH/…) store PERPETUAL.
    from app.plan_codes import plan_identity
    effective_plan_year = plan_identity(rec["carrier"], rec, plan_year)["year"]
```

Use `effective_plan_year` (NOT the raw `plan_year`) when setting `Policy.plan_year` in both
branches below. (Remove/replace the old single `alias_map.get(...)` line so it doesn't
double-resolve.)

In `bulk_upload`, determine `plan_year = date.today().year` and thread it + `alias_map` into
`_import_bob_row`.

**Also promote `_plan_alias_map` to module level:** it is currently a nested function inside
`bulk_upload`. Move it to a module-level `def _plan_alias_map(agency_id)` in `app/upload.py`
(same body) so Task 5's repair script can import it. `bulk_upload` calls the module-level one.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_bob_plan_linkage.py -v`
Expected: PASS

- [ ] **Step 5: Run the BOB upload suite (no regressions)**

Run: `python3 -m pytest tests/test_bob_upload.py tests/test_bob_upsert_characterization.py tests/test_aetna_parser.py tests/test_uhc_parser.py tests/test_devoted_parser.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add app/upload.py tests/test_bob_plan_linkage.py
git commit -m "feat: BOB upload sets contract_code+plan_year, links plan_id by (carrier,cms_plan_id,year), auto-creates needs_review plans"
```

---

### Task 5: One-time repair script for the existing orphaned policies

**Files:**
- Create: `scripts/repair_plan_id_linkage.py`
- Test: `tests/test_repair_plan_id_linkage.py`

**Interfaces:**
- Consumes: `plan_identity`, `PERPETUAL` (Task 2); `_resolve_or_create_plan` (Task 4) — **import it** to stay DRY, so the repair uses the IDENTICAL plan-type branching (year-bound/medigap/named) as live upload. (`_resolve_or_create_plan` is import-context-free: it only touches `db.session`, `Plan`, `alias_map`, and the passed `rec`/`plan_year` — safe to call from a script.)
- Produces: `plan_repairs(agency_id, year, apply=False) -> dict` (read-only planning by default: counts + a list of leftover unmatched plan_names) and a `main()` CLI (`--agency`, `--year`, `--apply`). Backfills `plan_id` + `contract_code` + `plan_year` on orphaned active policies via `_resolve_or_create_plan` — so medigap links by letter@PERPETUAL, year-bound by code@year, exactly like upload.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repair_plan_id_linkage.py
import pytest

@pytest.fixture
def ctx():
    from app import create_app
    from app.extensions import db
    from app.models import Agency
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        yield app, ag.id
        db.session.remove(); db.drop_all()

def test_repair_links_embedded_code_and_reports_leftovers(ctx):
    from app.extensions import db
    from app.models import Policy, Plan
    from scripts.repair_plan_id_linkage import plan_repairs
    app, agency_id = ctx
    # orphan with embedded code + no Plan yet → should link (auto-create), plan_year set
    db.session.add(Policy(agency_id=agency_id, carrier="Humana", member_id="M1",
                          plan_name="HUMANA GOLD PLUS HMO POS H1036-335",
                          status="active", plan_id=None))
    # orphan with NO code and no alias → leftover
    db.session.add(Policy(agency_id=agency_id, carrier="UHC", member_id="M2",
                          plan_name="AARP Medicare Advantage NC-0015",
                          status="active", plan_id=None))
    db.session.flush()
    res = plan_repairs(agency_id, year=2026, apply=True)
    assert res["linked"] == 1
    assert res["leftover"] == 1
    p1 = Policy.query.filter_by(member_id="M1").first()
    assert p1.plan_id is not None and p1.contract_code == "H1036-335" and p1.plan_year == 2026
    p2 = Policy.query.filter_by(member_id="M2").first()
    assert p2.plan_id is None                          # leftover, untouched link
    # leftover names surfaced for manual mapping
    assert any("AARP Medicare Advantage NC-0015" in n for n in res["leftover_names"])

def test_repair_dry_run_writes_nothing(ctx):
    from app.extensions import db
    from app.models import Policy, Plan
    from scripts.repair_plan_id_linkage import plan_repairs
    app, agency_id = ctx
    db.session.add(Policy(agency_id=agency_id, carrier="Humana", member_id="M1",
                          plan_name="HUMANA GOLD PLUS HMO POS H1036-335",
                          status="active", plan_id=None))
    db.session.flush()
    res = plan_repairs(agency_id, year=2026, apply=False)
    assert res["linked"] == 1                          # counted
    assert Policy.query.filter_by(member_id="M1").first().plan_id is None  # not written
    assert Plan.query.count() == 0                     # no plan created in dry-run

def test_repair_medigap_links_by_letter_perpetual(ctx):
    """A medigap orphan links to a (carrier, plan_letter, year=PERPETUAL) Plan, and the
    policy's plan_year is set to PERPETUAL — NOT the calendar year."""
    from app.extensions import db
    from app.models import Policy, Plan
    from app.plan_codes import PERPETUAL
    from scripts.repair_plan_id_linkage import plan_repairs
    app, agency_id = ctx
    db.session.add(Policy(agency_id=agency_id, carrier="BCBS", member_id="BM1",
                          plan_name="MEDSUP G 2019", plan_type="MS",
                          status="active", plan_id=None))
    db.session.flush()
    res = plan_repairs(agency_id, year=2026, apply=True)
    assert res["linked"] == 1
    pol = Policy.query.filter_by(member_id="BM1").first()
    assert pol.plan_year == PERPETUAL
    plan = Plan.query.get(pol.plan_id)
    assert plan.plan_letter == "G" and plan.year == PERPETUAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_repair_plan_id_linkage.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'scripts.repair_plan_id_linkage'`).

- [ ] **Step 3: Write the repair script**

```python
# scripts/repair_plan_id_linkage.py
"""One-time backfill: link orphaned active policies to their (carrier, cms_plan_id,
year) Plan, setting plan_id + contract_code + plan_year. Auto-creates a needs_review
Plan where the code is known but no Plan exists. Policies with no extractable code
and no alias match are LEFT untouched and reported for manual mapping.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/repair_plan_id_linkage.py \
      --agency 1 --year 2026 [--apply]
Dry-run by default; DB backup + dry-run review before --apply.
"""
import argparse
from collections import Counter

from app import create_app
from app.extensions import db
from app.models import Policy, Plan
from app.plan_codes import plan_identity
from app.upload import _resolve_or_create_plan, _plan_alias_map


def plan_repairs(agency_id, year, apply=False):
    """Backfill plan_id + contract_code + plan_year on orphaned active policies, using
    the SAME plan-type identity as live BOB upload (_resolve_or_create_plan). Read-only
    unless apply=True. Leftover = a policy that resolves to no plan (no code, no letter,
    no name/alias match) — surfaced for manual mapping, its link untouched."""
    counts = {"linked": 0, "leftover": 0}
    leftover_names = Counter()
    alias_map = _plan_alias_map(agency_id)
    orphans = (Policy.query
               .filter(Policy.agency_id == agency_id, Policy.status == "active",
                       Policy.plan_id.is_(None))
               .all())
    for pol in orphans:
        rec = {"plan_name": pol.plan_name, "plan_type": pol.plan_type}
        ident = plan_identity(pol.carrier, rec, year)
        plan_id, code = _resolve_or_create_plan(pol.carrier, rec, year, agency_id, alias_map)
        if plan_id:
            counts["linked"] += 1
            if apply:
                pol.plan_id = plan_id
                pol.contract_code = code
                pol.plan_year = ident["year"]     # PERPETUAL for medigap/named, else the year
        else:
            counts["leftover"] += 1
            leftover_names[(pol.carrier, pol.plan_name)] += 1
    counts["leftover_names"] = [f"{c} | {n} ({cnt})" for (c, n), cnt in leftover_names.most_common()]
    if apply:
        db.session.commit()
    else:
        db.session.rollback()
    return counts
```

Note: `_resolve_or_create_plan` *creates* a needs_review Plan when none exists — so on a
DRY-RUN it would stage a Plan add that the trailing `db.session.rollback()` then discards
(nothing persists). That's correct: dry-run reports what WOULD link (`linked` count +
leftover list) and writes nothing. On `--apply`, the created Plans + policy links commit
together.

The imports above require `_resolve_or_create_plan` and a module-level `_plan_alias_map`
in `app.upload`. `_plan_alias_map` is currently a NESTED function inside `bulk_upload` —
**Task 4 must promote it to a module-level `def _plan_alias_map(agency_id)`** so both upload
and this script share it (added to Task 4's wiring notes).

```python
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        res = plan_repairs(args.agency, args.year, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] plan_id linkage repair, agency {args.agency}, year {args.year}:")
        print(f"  linked:   {res['linked']}")
        print(f"  leftover: {res['leftover']}")
        if res["leftover_names"]:
            print("  leftover plan_names (map manually — add alias or create Plan):")
            for n in res["leftover_names"]:
                print(f"    {n}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_repair_plan_id_linkage.py -v`
Expected: PASS (both)

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `python3 -m pytest -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/repair_plan_id_linkage.py tests/test_repair_plan_id_linkage.py
git commit -m "feat: one-time repair_plan_id_linkage.py (dry-run/--apply) — backfill plan_id+contract_code+plan_year"
```

---

## Post-build (controller, NOT a task — human-gated deploy)

After the whole-branch opus review passes:
1. DB backup on VPS.
2. `flask db upgrade` 034→035; confirm head 035.
3. Deploy code; confirm `systemctl restart` cycled; login 200.
4. Run `scripts/repair_plan_id_linkage.py --agency 1 --year 2026` (DRY-RUN); **review the leftover plan_names list WITH Tim** (the ~non-embedded ones — Aetna/UHC friendly names needing an alias or a new Plan). Tim/AJ add aliases / create Plans for the leftovers.
5. Re-run dry-run until leftovers are acceptable, then `--apply` (real Postgres).
6. Verify: `plan_id_orphans` integrity invariant drops toward 0; spot-check a Humana
   contract-code count AND a medigap Plan-G count (confirm medigap didn't split by year and
   links at year=PERPETUAL).
7. Ratchet the `plan_id_orphans` baseline down. Update START HERE + BACKLOG.
8. **Layer 2 (single-source metrics + guard) is the next plan** — do NOT start it here.
