# Contract-Code Plan Database — Layer 1 (Buckets-First Data Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the authoritative NC plan "bucket" set (every real plan an NC agent can offer, from CMS + supplemental), then link every active policy to its correct bucket by SORTING BOB rows into EXISTING buckets — never auto-creating a plan on a guess — so contract-code customer counts are complete and accurate.

**Architecture (Tim's jelly-bean model):** The Plan DB is the authoritative set of buckets, seeded UP FRONT from the CMS CY2026 Landscape (187 NC MA/PDP plans, full contract-plan-segment codes) plus supplemental plans (medigap by letter, DVH/dental by name). When a BOB line arrives, the parser SORTS it into an existing bucket via a reviewed per-carrier name→bucket map. A bean whose bucket can't be confidently identified is NEVER auto-bucketed or auto-created — it goes to a human-confirm review queue. A genuinely-new plan gets a bucket only as a deliberate, verified action.

**Tech Stack:** Python 3.10, Flask-SQLAlchemy, Flask-Migrate (Alembic), PostgreSQL 16 (prod) / SQLite (tests), pytest, csv/openpyxl.

## Global Constraints

- **Buckets first, sort don't create.** The parser matches a BOB row to an EXISTING Plan bucket. It must NEVER auto-create a Plan on a failed match. Unmatched → review queue (`MatchSuggestion`-style), surfaced for a human to map or confirm-new. This is the anti-half-baked rule — it prevents "orange bean in the red bucket."
- **Bucket identity is plan-type-dependent:** MA/MAPD/PDP/DSNP/CSNP = `(carrier, cms_plan_id, year)` (`cms_plan_id` = full contract-plan or contract-plan-segment); medigap = `(carrier, plan_letter, year=PERPETUAL)`; DVH/dental/hospital-indemnity/GTL = `(carrier, plan_name, year=PERPETUAL)`. `PERPETUAL = 0`.
- **The segment matters** (BCBS Mecklenburg/Union seg 1-2 vs worse seg 3-4). CMS gives `Segment ID`; store the full `ContractPlanSegmentID` where the BOB/CMS provides it; `cms_plan_id` on the Plan is the contract-plan (2-part) OR contract-plan-segment (3-part) per what CMS lists as a distinct plan.
- **plan_year = the BOB snapshot year, NOT `effective_date`.** `effective_date` (tenure/AOR) is untouched. Year-independent plans store `PERPETUAL`.
- **The sorting map is REVIEWED data, not guessed logic.** The per-carrier BOB-name→bucket mapping is seed data a human verified (the ~77 bean decisions). The parser applies it; it does not invent mappings from string similarity.
- Every query agency-scoped. Repair/seed scripts are read-only planning + explicit `--apply`; DB backup first; dry-run → review WITH Tim → apply; real-Postgres verify.
- Migration head is currently `034`; migration `035` (Task 1) is DONE. Do NOT change `effective_date`, AOR logic, or the commission modules.
- **Reuse:** `scripts/sync_cms_plan_data.py` (already parses the CMS Landscape + upserts Plans via `_cms_id`), `scripts/seed_plan_aliases.py` (alias seeding), `MatchSuggestion` (review queue), `app/plan_provenance.py` (never blind-overwrite human-verified plan data).

---

### Task 1 — DONE (do not re-dispatch)

Migration 035 + `Policy.contract_code` + `Policy.plan_year` + `Plan.needs_review`. Committed `42b80a4`, suite 533. These columns are consumed by the tasks below.

---

### Task 2: Seed the NC plan buckets from the CMS Landscape

**Files:**
- Create: `scripts/seed_plan_buckets.py`
- Test: `tests/test_seed_plan_buckets.py`

**Interfaces:**
- Consumes: the CMS CY2026 Landscape CSV (`docs/Medicare Landscape Files/CY2026_Landscape_202603/CY2026_Landscape_202603.csv`), columns `State Territory Abbreviation, Contract ID, Plan ID, Segment ID, ContractPlanID, ContractPlanSegmentID, Plan Name, Plan Type, Organization Marketing Name, SNP Type`. Reuse `scripts/sync_cms_plan_data.py`'s CMS-org→carrier knowledge if present.
- Produces: `seed_buckets_from_rows(rows, agency_id, apply=False) -> dict` (counts: created/updated/skipped) — a pure function over parsed CMS rows (dicts), so it's testable without the file. A `main()` CLI (`--agency`, `--file`, `--apply`) reads the CSV, filters NC, groups by `ContractPlanID`, maps `Organization Marketing Name`→carrier, and upserts one `Plan` per `(carrier, cms_plan_id, year)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seed_plan_buckets.py
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

def _cms_row(**kw):
    base = {"State Territory Abbreviation": "NC", "Contract ID": "H1036",
            "Plan ID": "335", "Segment ID": "001", "ContractPlanID": "H1036-335",
            "ContractPlanSegmentID": "H1036-335-001",
            "Plan Name": "Humana Gold Plus HMO-POS", "Plan Type": "HMO-POS",
            "Organization Marketing Name": "Humana", "SNP Type": ""}
    base.update(kw); return base

def test_seed_creates_one_bucket_per_contract_plan(ctx):
    from app.extensions import db
    from app.models import Plan
    from scripts.seed_plan_buckets import seed_buckets_from_rows
    app, agency_id = ctx
    rows = [_cms_row(**{"County Name": "MECKLENBURG"}),
            _cms_row(**{"County Name": "UNION"})]   # same plan, 2 counties → ONE bucket
    res = seed_buckets_from_rows(rows, agency_id, apply=True)
    assert res["created"] == 1
    plans = Plan.query.filter_by(agency_id=agency_id, carrier="Humana").all()
    assert len(plans) == 1
    assert plans[0].cms_plan_id == "H1036-335" and plans[0].year == 2026

def test_seed_maps_org_name_to_carrier_and_skips_non_nc(ctx):
    from app.extensions import db
    from app.models import Plan
    from scripts.seed_plan_buckets import seed_buckets_from_rows
    app, agency_id = ctx
    rows = [
        _cms_row(**{"Organization Marketing Name": "Blue Cross and Blue Shield of North Carolina",
                    "Contract ID": "H3449", "Plan ID": "020", "ContractPlanID": "H3449-020",
                    "Plan Name": "Blue Medicare Enhanced"}),
        _cms_row(**{"State Territory Abbreviation": "SC"}),   # non-NC → skipped
    ]
    res = seed_buckets_from_rows(rows, agency_id, apply=True)
    assert Plan.query.filter_by(carrier="BCBS").count() == 1
    assert res["skipped"] >= 1   # the SC row

def test_seed_dry_run_writes_nothing(ctx):
    from app.models import Plan
    from scripts.seed_plan_buckets import seed_buckets_from_rows
    app, agency_id = ctx
    res = seed_buckets_from_rows([_cms_row()], agency_id, apply=False)
    assert res["created"] == 1
    assert Plan.query.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_seed_plan_buckets.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'scripts.seed_plan_buckets'`).

- [ ] **Step 3: Write the seed script**

```python
# scripts/seed_plan_buckets.py
"""Seed the authoritative NC plan buckets from the CMS CY2026 Landscape. One Plan per
(carrier, cms_plan_id, year). Idempotent upsert; does NOT overwrite human-verified plan
data (leaves existing benefit fields alone — only fills name/type on create). CMS
Organization Marketing Name → our carrier label. Read-only unless apply=True.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_plan_buckets.py \
      --agency 1 --file "docs/Medicare Landscape Files/CY2026_Landscape_202603/CY2026_Landscape_202603.csv" [--apply]
"""
import argparse
import csv

from app import create_app
from app.extensions import db
from app.models import Plan

CMS_YEAR = 2026

# CMS "Organization Marketing Name" (or parent org) → our carrier label.
_ORG_TO_CARRIER = {
    "humana": "Humana",
    "unitedhealthcare": "UHC",
    "aetna medicare": "Aetna",
    "aetna": "Aetna",
    "blue cross and blue shield of north carolina": "BCBS",
    "healthspring": "Healthspring",
    "cigna": "Healthspring",
    "devoted health": "Devoted",
}

# CMS Plan Type → our plan_type bucket-kind.
def _plan_type(cms_type: str) -> str:
    t = (cms_type or "").strip().lower()
    if "pdp" in t or "prescription" in t:
        return "PDP"
    if "hmo" in t or "ppo" in t or "pos" in t or "local" in t or "regional" in t:
        return "MA"
    return (cms_type or "other").strip()[:32]


def _carrier_of(org: str):
    return _ORG_TO_CARRIER.get((org or "").strip().lower())


def seed_buckets_from_rows(rows, agency_id, apply=False):
    """rows = iterable of CMS Landscape row dicts. Upsert one Plan per (carrier,
    ContractPlanID, year). NC only; unknown org → skipped."""
    counts = {"created": 0, "updated": 0, "skipped": 0}
    seen = set()   # (carrier, cms_plan_id) handled this run
    for row in rows:
        if (row.get("State Territory Abbreviation") or "").strip().upper() != "NC":
            counts["skipped"] += 1
            continue
        carrier = _carrier_of(row.get("Organization Marketing Name")
                              or row.get("Parent Organization Name"))
        cms_id = (row.get("ContractPlanID") or "").strip().upper()
        if not carrier or not cms_id:
            counts["skipped"] += 1
            continue
        key = (carrier, cms_id)
        if key in seen:
            continue                      # one bucket per plan, ignore extra county rows
        seen.add(key)
        plan = Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                    cms_plan_id=cms_id, year=CMS_YEAR).first()
        if plan is None:
            counts["created"] += 1
            if apply:
                db.session.add(Plan(
                    agency_id=agency_id, carrier=carrier, cms_plan_id=cms_id,
                    year=CMS_YEAR, plan_name=(row.get("Plan Name") or cms_id),
                    plan_type=_plan_type(row.get("Plan Type")),
                    status="current", needs_review=False))
        else:
            counts["updated"] += 1        # exists already — leave human data intact
    if apply:
        db.session.commit()
    else:
        db.session.rollback()
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        with open(args.file, encoding="latin-1") as f:
            rows = list(csv.DictReader(f))
        res = seed_buckets_from_rows(rows, args.agency, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] NC plan-bucket seed, agency {args.agency}:")
        for k, v in res.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_seed_plan_buckets.py -v`
Expected: PASS (all 3)

- [ ] **Step 5: Commit**

```bash
git add scripts/seed_plan_buckets.py tests/test_seed_plan_buckets.py
git commit -m "feat: seed_plan_buckets.py — seed NC plan buckets from CMS Landscape (one Plan per carrier+code+year)"
```

---

### Task 3: `app/plan_codes.py` — classify + extract the sorting KEY from a BOB row

**Files:**
- Create: `app/plan_codes.py`
- Test: `tests/test_plan_codes.py`

**Interfaces:**
- Consumes: nothing (pure functions).
- Produces (these are the SORTING keys — they identify which bucket a bean belongs to, they do NOT create buckets):
  - `PERPETUAL = 0`.
  - `classify_plan(plan_type: str, plan_name: str) -> str` — `"medigap"|"named"|"year_bound"` (keyword-based; plan_type is messy; year_bound is the default).
  - `extract_contract_code(carrier: str, rec: dict) -> Optional[str]` — full code (`H1036-335` or `H1036-335-001`) from a BOB record: Humana/Healthspring regex on plan_name (dash OR underscore, normalized to dash); Aetna from `cms_contract_number`+`pbp_code`; else None.
  - `cms_plan_id_of(contract_code: str) -> Optional[str]` — the 2-part `(contract, plan)` key for bucket matching.
  - `medigap_letter(plan_name: str) -> Optional[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_codes.py  (append to the file Task 1 created)
def test_extract_humana_code_from_plan_name():
    from app.plan_codes import extract_contract_code, cms_plan_id_of
    assert extract_contract_code("Humana", {"plan_name": "HUMANA GOLD PLUS HMO POS H1036-335"}) == "H1036-335"
    assert cms_plan_id_of("H1036-335-001") == "H1036-335"
    assert cms_plan_id_of("H1036-335") == "H1036-335"

def test_extract_aetna_code_from_contract_and_pbp():
    from app.plan_codes import extract_contract_code
    assert extract_contract_code("Aetna", {"plan_name": "Aetna Medicare Select (HMO-POS)",
        "cms_contract_number": "H5521", "pbp_code": "241"}) == "H5521-241"

def test_extract_healthspring_underscore_code():
    from app.plan_codes import extract_contract_code
    assert extract_contract_code("Healthspring",
        {"plan_name": "2026_NC_H9725_015_HealthSpring Preferred Savings (HMO)"}) == "H9725-015"

def test_extract_returns_none_when_no_code():
    from app.plan_codes import extract_contract_code
    assert extract_contract_code("UHC", {"plan_name": "AARP Medicare Advantage NC-0015"}) is None

def test_classify_uses_name_when_plan_type_is_messy():
    from app.plan_codes import classify_plan
    assert classify_plan("", "AARP MEDICARE SUPPLEMENT PLAN G") == "medigap"
    assert classify_plan("AARPMODMEDSUP", "") == "medigap"
    assert classify_plan("MES", "HUMANA MED SUPP PLAN G") == "medigap"
    assert classify_plan("DVH", "DVH 1000") == "named"
    assert classify_plan("Dental", "Dental Blue for Individuals PPO") == "named"
    assert classify_plan("IDV", "NC EXTEND 1250 MNTH DEL '23") == "named"
    assert classify_plan("", "Blue Medicare Freedom+ PPO") == "year_bound"
    assert classify_plan("MA", "AARP Medicare Advantage from UHC NC-0001") == "year_bound"
    assert classify_plan("PDP", "HUMANA VALUE RX PLAN PDP") == "year_bound"

def test_medigap_letter():
    from app.plan_codes import medigap_letter
    assert medigap_letter("AARP MEDICARE SUPPLEMENT PLAN G") == "G"
    assert medigap_letter("MedSup N 2019") == "N"
    assert medigap_letter("Some Random Plan") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_plan_codes.py -k "extract or classify or medigap" -v`
Expected: FAIL (`ImportError`/`AttributeError` — functions don't exist).

- [ ] **Step 3: Write the module**

```python
# app/plan_codes.py
"""Sorting keys for BOB plan rows → the plan buckets. Pure functions: they identify
which bucket a row belongs to; they NEVER create buckets. plan_type is unreliable in
real data (often the plan NAME, blank, or a carrier code), so classification uses
keywords across plan_type AND plan_name."""
import re
from typing import Optional

PERPETUAL = 0   # year sentinel for plans whose benefits are NOT annual (medigap/DVH/etc.)

# H#### / S#### / R#### + plan(3) + optional segment(3), '-' OR '_' (Humana dash,
# Healthspring underscore). Normalized to dash form.
_CODE_RE = re.compile(r"([HSR]\d{4})[-_](\d{3})(?:[-_](\d{3}))?")
_MEDIGAP_LETTER_RE = re.compile(r"\bPLAN\s+([A-N])\b")
_MEDIGAP_KW = ("SUPP", "SUPPLEMENT", "MEDSUP", "AARPMODMEDSUP", "MES")
_NAMED_KW = ("DVH", "DENTAL", "VISION", "HOSPITAL", "INDEMNITY", "IDV", "GTL", "EXTEND")


def classify_plan(plan_type: str, plan_name: str) -> str:
    blob = f"{plan_type or ''} {plan_name or ''}".upper()
    if any(k in blob for k in _MEDIGAP_KW) or _MEDIGAP_LETTER_RE.search(blob):
        return "medigap"
    if any(k in blob for k in _NAMED_KW):
        return "named"
    return "year_bound"


def extract_contract_code(carrier: str, rec: dict) -> Optional[str]:
    c = (carrier or "").strip().lower()
    if c == "aetna":
        contract = (rec.get("cms_contract_number") or "").strip().upper()
        pbp = (rec.get("pbp_code") or "").strip()
        if contract and pbp:
            return f"{contract}-{pbp.zfill(3)}"
    name = (rec.get("plan_name") or "").upper()
    m = _CODE_RE.search(name)
    if not m:
        return None
    parts = [m.group(1), m.group(2)] + ([m.group(3)] if m.group(3) else [])
    return "-".join(parts)


def cms_plan_id_of(contract_code: str) -> Optional[str]:
    if not contract_code:
        return None
    parts = contract_code.strip().upper().split("-")
    return f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else None


def medigap_letter(plan_name: str) -> Optional[str]:
    m = _MEDIGAP_LETTER_RE.search((plan_name or "").upper())
    return m.group(1) if m else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_plan_codes.py -v`
Expected: PASS (Task 1's test + all new ones)

- [ ] **Step 5: Commit**

```bash
git add app/plan_codes.py tests/test_plan_codes.py
git commit -m "feat: app/plan_codes.py — classify + extract the sorting key for BOB plan rows"
```

---

### Task 4: `find_plan_bucket` — SORT a BOB row into an EXISTING bucket (never create)

**Files:**
- Create: `app/plan_bucket.py`
- Test: `tests/test_plan_bucket.py`

**Interfaces:**
- Consumes: `classify_plan`, `extract_contract_code`, `cms_plan_id_of`, `medigap_letter`, `PERPETUAL` (Task 3); the seeded `Plan` buckets (Task 2); the existing `plan_name_aliases` on Plan rows.
- Produces: `find_plan_bucket(carrier, rec, plan_year, agency_id) -> dict` returning `{"plan_id": int|None, "contract_code": str|None, "plan_year": int, "matched_by": "code"|"letter"|"name"|"alias"|None}`. **plan_id is None when no existing bucket matches — it NEVER creates a Plan.** The caller decides what to do with a miss (park + review queue, Task 5).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_bucket.py
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

def _plan(db, agency_id, **kw):
    from app.models import Plan
    base = dict(agency_id=agency_id, plan_name="X", plan_type="MA", status="current")
    base.update(kw)
    p = Plan(**base); db.session.add(p); db.session.flush(); return p

def test_sorts_year_bound_row_into_existing_code_bucket(ctx):
    from app.extensions import db
    from app.plan_bucket import find_plan_bucket
    app, agency_id = ctx
    bucket = _plan(db, agency_id, carrier="Humana", cms_plan_id="H1036-335", year=2026)
    res = find_plan_bucket("Humana", {"plan_name": "HUMANA GOLD PLUS HMO POS H1036-335",
                                      "plan_type": "MAPD"}, 2026, agency_id)
    assert res["plan_id"] == bucket.id and res["matched_by"] == "code"
    assert res["contract_code"] == "H1036-335" and res["plan_year"] == 2026

def test_miss_returns_none_never_creates(ctx):
    from app.extensions import db
    from app.models import Plan
    from app.plan_bucket import find_plan_bucket
    app, agency_id = ctx
    # no bucket seeded for this code → MISS, and NO Plan is created
    res = find_plan_bucket("Humana", {"plan_name": "HUMANA MYSTERY PLAN H9999-999",
                                      "plan_type": "MAPD"}, 2026, agency_id)
    assert res["plan_id"] is None and res["matched_by"] is None
    assert Plan.query.count() == 0            # never auto-created

def test_sorts_medigap_by_letter_at_perpetual(ctx):
    from app.extensions import db
    from app.plan_bucket import find_plan_bucket
    from app.plan_codes import PERPETUAL
    app, agency_id = ctx
    bucket = _plan(db, agency_id, carrier="BCBS", plan_letter="G", plan_type="medigap",
                   year=PERPETUAL, cms_plan_id=None)
    res = find_plan_bucket("BCBS", {"plan_name": "MEDSUP G 2019", "plan_type": "MS"},
                           2026, agency_id)
    assert res["plan_id"] == bucket.id and res["matched_by"] == "letter"
    assert res["plan_year"] == PERPETUAL

def test_sorts_by_alias_when_no_code(ctx):
    from app.extensions import db
    from app.plan_bucket import find_plan_bucket
    app, agency_id = ctx
    # UHC friendly name, no code → matched via the reviewed alias on the bucket
    bucket = _plan(db, agency_id, carrier="UHC", cms_plan_id="H5253-117", year=2026,
                   plan_name_aliases="aarp medicare advantage from uhc nc-0015")
    res = find_plan_bucket("UHC", {"plan_name": "AARP Medicare Advantage from UHC NC-0015",
                                   "plan_type": "MA"}, 2026, agency_id)
    assert res["plan_id"] == bucket.id and res["matched_by"] == "alias"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_plan_bucket.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.plan_bucket'`).

- [ ] **Step 3: Write the module**

```python
# app/plan_bucket.py
"""Sort a BOB plan row into an EXISTING Plan bucket. NEVER creates a bucket — a miss
returns plan_id=None so the caller can park + queue it for human review. This is the
jelly-bean sorter: match a bean to a bucket that already exists."""
from typing import Optional
from app.extensions import db
from app.models import Plan
from app.plan_codes import (classify_plan, extract_contract_code, cms_plan_id_of,
                            medigap_letter, PERPETUAL)


def _alias_hit(carrier, plan_name, year, agency_id):
    """Match by the reviewed plan_name / plan_name_aliases on existing buckets."""
    nm = (plan_name or "").strip().lower()
    if not nm:
        return None
    with db.session.no_autoflush:
        for p in Plan.query.filter_by(agency_id=agency_id, carrier=carrier).all():
            if p.plan_name and p.plan_name.strip().lower() == nm:
                return p
            if p.plan_name_aliases:
                for a in p.plan_name_aliases.split(","):
                    if a.strip().lower() == nm:
                        return p
    return None


def find_plan_bucket(carrier, rec, plan_year, agency_id) -> dict:
    carrier = (carrier or "").strip()
    plan_name = rec.get("plan_name") or ""
    kind = classify_plan(rec.get("plan_type") or "", plan_name)
    out = {"plan_id": None, "contract_code": None, "plan_year": plan_year,
           "matched_by": None}
    if kind == "year_bound":
        code = extract_contract_code(carrier, rec)
        out["contract_code"] = code
        cms_id = cms_plan_id_of(code) if code else None
        if cms_id:
            with db.session.no_autoflush:
                p = Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                         cms_plan_id=cms_id, year=plan_year).first()
            if p:
                out.update(plan_id=p.id, matched_by="code")
                return out
        # no code, or code has no seeded bucket → try the reviewed alias
        p = _alias_hit(carrier, plan_name, plan_year, agency_id)
        if p:
            out.update(plan_id=p.id, matched_by="alias")
        return out
    if kind == "medigap":
        out["plan_year"] = PERPETUAL
        letter = medigap_letter(plan_name)
        if letter:
            with db.session.no_autoflush:
                p = Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                         plan_letter=letter, year=PERPETUAL).first()
            if p:
                out.update(plan_id=p.id, matched_by="letter")
        return out
    # named (DVH/dental/GTL/hospital-indemnity)
    out["plan_year"] = PERPETUAL
    p = _alias_hit(carrier, plan_name, PERPETUAL, agency_id)
    if p and p.year == PERPETUAL:
        out.update(plan_id=p.id, matched_by="name")
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_plan_bucket.py -v`
Expected: PASS (all 4)

- [ ] **Step 5: Commit**

```bash
git add app/plan_bucket.py tests/test_plan_bucket.py
git commit -m "feat: app/plan_bucket.find_plan_bucket — sort a BOB row into an existing bucket, never create"
```

---

### Task 5: Wire the sorter into BOB upload + one-time repair (both park misses, never create)

**Files:**
- Modify: `app/upload.py` (`_import_bob_row` + `bulk_upload` — set contract_code/plan_year/plan_id via `find_plan_bucket`; a miss leaves plan_id NULL + is recorded)
- Modify: `app/parsers/aetna.py` (emit `cms_contract_number` + `pbp_code`)
- Create: `scripts/repair_plan_id_linkage.py`
- Test: `tests/test_bob_plan_linkage.py`, `tests/test_aetna_parser.py`, `tests/test_repair_plan_id_linkage.py`

**Interfaces:**
- Consumes: `find_plan_bucket` (Task 4), the seeded buckets (Task 2).
- Produces: BOB upload sets `Policy.contract_code`, `Policy.plan_year`, `Policy.plan_id` from `find_plan_bucket`. On a MISS (plan_id None) the policy keeps `plan_id=NULL` (its plan is un-bucketed) and the (carrier, plan_name) is collected into the batch's unresolvable list for human review — NO Plan is created. The repair script does the same over existing orphans.

- [ ] **Step 1: Write the failing test (Aetna emits code inputs)**

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
    assert r["cms_contract_number"] == "H5521" and r["pbp_code"] == "241"
```

- [ ] **Step 2: Write the failing test (upload sorts into a bucket, miss stays NULL)**

```python
# tests/test_bob_plan_linkage.py
from datetime import date

def _rec(**kw):
    base = {"carrier": "Humana", "member_id": "HM1", "mbi": "8QV9Q10TC36",
            "first_name": "A", "last_name": "B", "full_name": "A B",
            "plan_name": "HUMANA GOLD PLUS HMO POS H1036-335", "plan_type": "MAPD",
            "effective_date": date(2024, 1, 1), "term_date": None, "dob": None,
            "phone": "", "county": "", "agent_id": "", "status": "active"}
    base.update(kw); return base

def test_bob_row_links_to_seeded_bucket_sets_code_and_year(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import ImportBatch, Policy, Plan
    from app.upload import _import_bob_row
    with app.app_context():
        bucket = Plan(agency_id=agency.id, carrier="Humana", cms_plan_id="H1036-335",
                      year=2026, plan_name="Gold Plus", plan_type="MA", status="current")
        db.session.add(bucket)
        batch = ImportBatch(agency_id=agency.id, carrier="Humana", filename="h.xlsx",
                            uploaded_by_id=agent_user.id, status="pending")
        db.session.add(batch); db.session.commit()
        with db.session.begin_nested():
            _import_bob_row(_rec(), batch, agency.id, agent_user.id, date.today(), [],
                            plan_year=2026)
        db.session.commit()
        pol = Policy.query.filter_by(agency_id=agency.id, member_id="HM1").first()
        assert pol.plan_id == bucket.id
        assert pol.contract_code == "H1036-335"
        assert pol.plan_year == 2026                # import year, not eff-date 2024

def test_bob_row_with_no_bucket_stays_null_and_is_recorded(db_session, app, agency, agent_user):
    """A row whose plan has no seeded bucket keeps plan_id NULL and is added to the
    review list — NO Plan is auto-created."""
    from app.extensions import db
    from app.models import ImportBatch, Policy, Plan
    from app.upload import _import_bob_row
    with app.app_context():
        batch = ImportBatch(agency_id=agency.id, carrier="Humana", filename="h.xlsx",
                            uploaded_by_id=agent_user.id, status="pending")
        db.session.add(batch); db.session.commit()
        review = []
        with db.session.begin_nested():
            _import_bob_row(_rec(member_id="HM2", plan_name="HUMANA MYSTERY H9999-999"),
                            batch, agency.id, agent_user.id, date.today(), [],
                            plan_year=2026, plan_review=review)
        db.session.commit()
        pol = Policy.query.filter_by(agency_id=agency.id, member_id="HM2").first()
        assert pol.plan_id is None
        assert Plan.query.filter_by(cms_plan_id="H9999-999").count() == 0   # not created
        assert any("H9999-999" in (r.get("plan_name") or "") for r in review)
```

- [ ] **Step 3: Write the failing test (repair over orphans, miss reported)**

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

def test_repair_links_to_bucket_and_reports_leftover(ctx):
    from app.extensions import db
    from app.models import Policy, Plan
    from scripts.repair_plan_id_linkage import plan_repairs
    app, agency_id = ctx
    db.session.add(Plan(agency_id=agency_id, carrier="Humana", cms_plan_id="H1036-335",
                        year=2026, plan_name="Gold Plus", plan_type="MA", status="current"))
    db.session.add(Policy(agency_id=agency_id, carrier="Humana", member_id="M1",
                          plan_name="HUMANA GOLD PLUS HMO POS H1036-335", plan_type="MAPD",
                          status="active", plan_id=None))
    db.session.add(Policy(agency_id=agency_id, carrier="Humana", member_id="M2",
                          plan_name="HUMANA MYSTERY H9999-999", plan_type="MAPD",
                          status="active", plan_id=None))
    db.session.flush()
    res = plan_repairs(agency_id, year=2026, apply=True)
    assert res["linked"] == 1 and res["leftover"] == 1
    assert Policy.query.filter_by(member_id="M1").first().plan_id is not None
    assert Policy.query.filter_by(member_id="M2").first().plan_id is None   # no bucket → untouched
    assert Plan.query.count() == 1                                          # none created
    assert any("H9999-999" in n for n in res["leftover_names"])

def test_repair_dry_run_writes_nothing(ctx):
    from app.extensions import db
    from app.models import Policy, Plan
    from scripts.repair_plan_id_linkage import plan_repairs
    app, agency_id = ctx
    db.session.add(Plan(agency_id=agency_id, carrier="Humana", cms_plan_id="H1036-335",
                        year=2026, plan_name="Gold Plus", plan_type="MA", status="current"))
    db.session.add(Policy(agency_id=agency_id, carrier="Humana", member_id="M1",
                          plan_name="HUMANA GOLD PLUS HMO POS H1036-335", plan_type="MAPD",
                          status="active", plan_id=None))
    db.session.flush()
    res = plan_repairs(agency_id, year=2026, apply=False)
    assert res["linked"] == 1
    assert Policy.query.filter_by(member_id="M1").first().plan_id is None   # not written
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_aetna_parser.py::test_aetna_emits_contract_number_and_pbp tests/test_bob_plan_linkage.py tests/test_repair_plan_id_linkage.py -v`
Expected: FAIL (fields/params/module not present).

- [ ] **Step 5: Implement — Aetna parser fields**

In `app/parsers/aetna.py`, add to BOTH `_parse_xlsx_format` and `_parse_csv_format` record dicts:

```python
            "cms_contract_number": _str(row, "CMS Contract Number"),
            "pbp_code": _str(row, "PBP Code"),
```

- [ ] **Step 6: Implement — BOB upload uses `find_plan_bucket`**

In `app/upload.py`, give `_import_bob_row` keyword params `*, plan_year=None, plan_review=None`
(default `plan_year = plan_year or date.today().year`; `plan_review` is a list the caller
passes to collect misses). Compute once before the create/update branches:

```python
    from app.plan_bucket import find_plan_bucket
    _b = find_plan_bucket(rec["carrier"], rec, plan_year, agency_id)
    if _b["plan_id"] is None and rec.get("plan_name") and plan_review is not None:
        plan_review.append({"carrier": rec["carrier"], "plan_name": rec.get("plan_name"),
                            "plan_type": rec.get("plan_type")})
```

Set on the NEW Policy: `contract_code=_b["contract_code"], plan_year=_b["plan_year"],
plan_id=_b["plan_id"]`. On the EXISTING Policy: `existing.contract_code = _b["contract_code"]
or existing.contract_code; existing.plan_year = _b["plan_year"]; existing.plan_id =
_b["plan_id"] or existing.plan_id`. REMOVE the old `alias_map.get(...)` plan_id line (the
bucket sorter replaces it). In `bulk_upload`, pass `plan_year=date.today().year` and a
`plan_review=[]` list; after the loop, merge `plan_review` into `batch.unresolvable_json`
(or append to the existing unresolvable list) so misses surface in the import modal for
human mapping.

- [ ] **Step 7: Implement — the repair script**

```python
# scripts/repair_plan_id_linkage.py
"""One-time backfill: sort orphaned active policies into their EXISTING plan bucket via
find_plan_bucket, setting plan_id + contract_code + plan_year. A policy whose plan has no
seeded bucket is LEFT untouched (plan_id stays NULL) and reported for manual mapping —
NEVER auto-bucketed. Read-only unless --apply.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/repair_plan_id_linkage.py \
      --agency 1 --year 2026 [--apply]
"""
import argparse
from collections import Counter

from app import create_app
from app.extensions import db
from app.models import Policy
from app.plan_bucket import find_plan_bucket


def plan_repairs(agency_id, year, apply=False):
    counts = {"linked": 0, "leftover": 0}
    leftover = Counter()
    orphans = (Policy.query
               .filter(Policy.agency_id == agency_id, Policy.status == "active",
                       Policy.plan_id.is_(None))
               .all())
    for pol in orphans:
        rec = {"plan_name": pol.plan_name, "plan_type": pol.plan_type,
               "cms_contract_number": "", "pbp_code": ""}
        b = find_plan_bucket(pol.carrier, rec, year, agency_id)
        if b["plan_id"]:
            counts["linked"] += 1
            if apply:
                pol.plan_id = b["plan_id"]
                pol.contract_code = b["contract_code"]
                pol.plan_year = b["plan_year"]
        else:
            counts["leftover"] += 1
            leftover[(pol.carrier, pol.plan_name)] += 1
    counts["leftover_names"] = [f"{c} | {n} ({k})" for (c, n), k in leftover.most_common()]
    if apply:
        db.session.commit()
    else:
        db.session.rollback()
    return counts


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
        print(f"[{mode}] plan bucket linkage, agency {args.agency}, year {args.year}:")
        print(f"  linked:   {res['linked']}")
        print(f"  leftover: {res['leftover']}  (no seeded bucket — map manually)")
        for n in res["leftover_names"]:
            print(f"    {n}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run all Task-5 tests + the BOB suite**

Run: `python3 -m pytest tests/test_aetna_parser.py tests/test_bob_plan_linkage.py tests/test_repair_plan_id_linkage.py tests/test_bob_upload.py -q`
Expected: all PASS

- [ ] **Step 9: Run the full suite (no regressions)**

Run: `python3 -m pytest -q`
Expected: all PASS

- [ ] **Step 10: Commit**

```bash
git add app/upload.py app/parsers/aetna.py scripts/repair_plan_id_linkage.py \
        tests/test_bob_plan_linkage.py tests/test_aetna_parser.py tests/test_repair_plan_id_linkage.py
git commit -m "feat: BOB upload + repair sort policies into existing plan buckets (miss → review, never create)"
```

---

## Post-build (controller, NOT a task — human-gated deploy)

After the whole-branch opus review passes:
1. DB backup on VPS; `flask db upgrade` 034→035; confirm head 035; deploy code; restart cycled; login 200.
2. **Seed the buckets:** `scripts/seed_plan_buckets.py --agency 1 --file <CMS Landscape CSV>` DRY-RUN → review counts WITH Tim → `--apply`. (Scp the CSV to the VPS first — it's not in git.)
3. **Seed the reviewed alias map** for the carriers whose BOB names don't carry a code (UHC/BCBS) — Tim/AJ map the ~≤32 UHC + ≤9 BCBS distinct BOB plan-names to their bucket's `plan_name_aliases`. (UHC BOB can also be regenerated WITH the H+PBP+segment columns — then those beans self-label and need no alias.)
4. **Repair:** `scripts/repair_plan_id_linkage.py --agency 1 --year 2026` DRY-RUN → review the leftover list WITH Tim (should be small once buckets+aliases are seeded) → `--apply`.
5. Verify `plan_id_orphans` drops toward 0; spot-check a Humana + a medigap-G count; ratchet the baseline.
6. **Layer 2 (single-source metrics + guard) is the next plan.**
