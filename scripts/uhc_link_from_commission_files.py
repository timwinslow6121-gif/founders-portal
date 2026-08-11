"""Link UHC active policies with plan_id=NULL to their Plan bucket, using the RAW
UHC COMMISSION FILES (not the BOB) as the source of contract-PBP.

WHY THIS EXISTS: the 40 "Unlinked / needs plan" UHC actives are commission-import
policies — they have a blank plan_name, no DOB, and no Plan bucket, because
commission import never writes plan_id at all (see app/commission/payments.py:
it creates payment rows only). Plan linkage has only ever come from the BOB path.

These 40 are absent from the UHC BOB entirely — verified against the Aug 2026
full export (30 cols, mbiNumber + memberNumber present, 2,174 active rows,
0 blank MBIs): 0/40 matched, while a 60-row control of KNOWN-LINKED actives
matched 58/60. So the matcher works and the absence is real. They are also not
cross-carrier switchers (0 of the 40 hold a policy with any other carrier).

But the raw UHC commission statements carry `Contract` + `PBP` columns per member
— exactly the contract-PBP needed to pick a bucket. The importer discards them.
So linkage does NOT depend on the BOB; it only depends on reading those columns.

  May 2026 file  -> 37 of the 40
  July 2026 file -> 4 of the 40   (union: 38; the other 2 were paid in June only)

⚠ USE MAY, NOT JULY, AS THE TRUSTED SOURCE. Per CLAUDE.md, UHC made an error in
the July 2026 file and notified AJ; July must not be used to derive dollar/split
rules. This script reads ONLY `Contract`/`PBP`/`Plan Type`/`Member Name` — identity
fields, not money — and cross-checks every row, so July is safe HERE. Money fields
are never read and never written.

SAFETY GATES (a wrong plan_id is invisible — money still ties to the penny — and
sticky, so every link must clear ALL of these or it is REFUSED):
  1. NEVER overwrite an existing plan_id. Only plan_id IS NULL rows are touched.
  2. Carrier + status pinned to UHC/active in the query AND re-asserted per row.
  3. Contract-PBP must be UNAMBIGUOUS across all files for that member (a member
     with two different contract-PBPs is refused, not guessed).
  4. The bucket must already exist. NEVER creates a Plan (the jelly-bean rule).
  5. NAME AGREEMENT: the commission file's Member Name must share >=2 tokens with
     the DB customer's name. This is the gate that caught a REAL mis-link during
     the ledger backfill (two identical "COUCHELL, JOHN" rows resolving to
     different customers). Suffixes (JR/SR/II/III/IV) and initials are ignored.
  6. TYPE CONSISTENCY: the plan family the commission file reports (DSNP/CSNP/
     MAPD/MA) must agree with the family already on Policy.plan_type. Critically,
     a policy typed MA must land on an MA bucket, never a MAPD one.

Touches Policy.plan_id (and backfills a blank Policy.plan_name for display).
NO money field is read or written.

Dry-run by default; --apply commits. Idempotent (a second run resolves 0).
Back up the DB before --apply.

Run on the VPS:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
    scripts/uhc_link_from_commission_files.py [--apply]
"""
import glob
import os
import re
import sys
from collections import defaultdict

import pandas as pd

from app import create_app
from app.extensions import db
from app.models import Customer, Plan, Policy

CARRIER = "UHC"
SHEET = "Commission Transactions"

# Raw UHC commission statements to read contract-PBP from. May is the TRUSTED
# month (July had a known carrier error — see module docstring). Globs so the
# script keeps working as new cycles land.
FILE_GLOBS = [
    "docs/Commission DL/_organized/2026-05_cycle/raw/UHC/statement-*.xlsx",
    "docs/Commission DL/_organized/2026-07_cycle/Founders_Commission_July_2026/statement-*.xlsx",
]

_NAME_SUFFIXES = {"JR", "SR", "II", "III", "IV"}


def norm(s):
    return "" if s is None or str(s) == "nan" else str(s).strip().upper()


def name_tokens(s):
    """Comparable name tokens: uppercase alpha words, no suffixes, no initials."""
    s = re.sub(r"[^A-Z ]", " ", (s or "").upper())
    return {t for t in s.split() if len(t) > 1 and t not in _NAME_SUFFIXES}


def plan_family(s):
    """Collapse a plan-type string to its family. MA is kept DISTINCT from MAPD —
    an MA-only member must never be linked to a drug plan."""
    s = norm(s)
    if "DSNP" in s or "D-SNP" in s:
        return "DSNP"
    if "CSNP" in s or "C-SNP" in s:
        return "CSNP"
    if s == "MA":
        return "MA"
    if "MAPD" in s:
        return "MAPD"
    return s


def families_agree(db_family, file_family, bucket_type):
    """Gate 6. The SNP families are all drug plans, so DSNP/CSNP/MAPD are mutually
    compatible and must sit on a 'mapd' bucket. MA is strict: it must land on an
    'ma' bucket, never a MAPD one."""
    bucket_type = (bucket_type or "").strip().lower()
    if db_family == "MA" or file_family == "MA":
        return db_family == file_family == "MA" and bucket_type == "ma"
    drug = {"DSNP", "CSNP", "MAPD"}
    return db_family in drug and file_family in drug and bucket_type == "mapd"


def read_commission_files():
    """member MBI -> {'cps': set of contract-pbp, 'types': set, 'names': set}."""
    found = defaultdict(lambda: {"cps": set(), "types": set(), "names": set()})
    files = []
    for pat in FILE_GLOBS:
        files.extend(sorted(glob.glob(pat)))
    if not files:
        print("  !! no commission files matched — run from the repo root.")
        return found, []
    for path in files:
        try:
            d = pd.read_excel(path, sheet_name=SHEET, header=0, dtype=str)
        except Exception as exc:                      # noqa: BLE001
            print(f"  !! skipping {os.path.basename(path)}: {exc}")
            continue
        d = d.dropna(how="all")
        need = {"MedicareID", "Contract", "PBP", "Plan Type", "Member Name"}
        if not need.issubset(set(d.columns)):
            print(f"  !! skipping {os.path.basename(path)}: missing {need - set(d.columns)}")
            continue
        for mbi, con, pbp, ptype, nm in zip(d["MedicareID"], d["Contract"], d["PBP"],
                                            d["Plan Type"], d["Member Name"]):
            mbi = norm(mbi)
            if not mbi:
                continue
            rec = found[mbi]
            if norm(con) and norm(pbp):
                rec["cps"].add(f"{norm(con)}-{norm(pbp)}")
            if norm(ptype):
                rec["types"].add(norm(ptype))
            if norm(nm):
                rec["names"].add(norm(nm))
        print(f"  read {len(d):5d} rows from {os.path.basename(path)}")
    return found, files


def find_bucket(agency_id, cms_dash):
    """Match a Plan bucket by cms_plan_id in dash OR underscore form. NEVER creates."""
    contract, _, pbp = cms_dash.partition("-")
    under = f"{contract}_{pbp}"
    return (Plan.query
            .filter_by(agency_id=agency_id, carrier=CARRIER)
            .filter(Plan.cms_plan_id.in_([cms_dash, under]))
            .first())


def main(apply):
    app = create_app()
    with app.app_context():
        agency_id = app.config.get("DEFAULT_AGENCY_ID", 1)
        print(f"{'APPLY' if apply else 'DRY-RUN'} — UHC plan linkage from commission files\n")

        print("Reading raw commission statements:")
        by_mbi, files = read_commission_files()
        if not files:
            return 1
        print(f"  -> {len(by_mbi)} distinct MBIs across {len(files)} file(s)\n")

        # Gate 1+2: only unlinked, active, UHC rows are even considered.
        unlinked = (Policy.query
                    .filter_by(agency_id=agency_id, carrier=CARRIER,
                               status="active", plan_id=None)
                    .all())
        print(f"UHC active policies with plan_id IS NULL: {len(unlinked)}\n")

        linked = 0
        refused = defaultdict(list)
        for p in unlinked:
            # Gate 2 re-assert: never trust the query alone for a write.
            if p.carrier != CARRIER or p.status != "active" or p.plan_id is not None:
                refused["safety re-assert failed"].append(p.id)
                continue

            rec = by_mbi.get(norm(p.mbi)) or by_mbi.get(norm(p.member_id))
            if not rec:
                refused["not in any commission file"].append(p.id)
                continue

            # Gate 3: one unambiguous contract-PBP, or refuse.
            if len(rec["cps"]) != 1:
                refused[f"ambiguous contract-pbp {sorted(rec['cps'])}"].append(p.id)
                continue
            cms = next(iter(rec["cps"]))

            # Gate 4: the bucket must already exist.
            bucket = find_bucket(agency_id, cms)
            if not bucket:
                refused[f"no Plan bucket for {cms}"].append(p.id)
                continue

            cust = (Customer.query
                    .filter_by(id=p.customer_id, agency_id=agency_id).first()
                    if p.customer_id else None)

            # Gate 5: name agreement between the file and the DB customer.
            db_name = (cust.full_name if cust else None) or p.full_name or ""
            db_toks = name_tokens(db_name)
            if not db_toks or not any(len(name_tokens(fn) & db_toks) >= 2
                                      for fn in rec["names"]):
                refused["NAME MISMATCH — needs a human"].append(
                    f"{p.id} db='{db_name}' file={sorted(rec['names'])}")
                continue

            # Gate 6: plan family must agree, and MA must not become MAPD.
            db_fam = plan_family(p.plan_type)
            file_fam = plan_family(next(iter(rec["types"]))) if len(rec["types"]) == 1 else ""
            if not families_agree(db_fam, file_fam, bucket.plan_type):
                refused[f"TYPE MISMATCH db={db_fam} file={file_fam} "
                        f"bucket={bucket.plan_type}"].append(p.id)
                continue

            print(f"  pid {p.id:>5}  {db_name[:26]:<26} {db_fam:<5} -> {cms} "
                  f"bucket {bucket.id} '{(bucket.plan_name or '')[:34]}'")
            if apply:
                p.plan_id = bucket.id
                if not (p.plan_name or "").strip():
                    p.plan_name = bucket.plan_name
            linked += 1

        print(f"\n  LINKABLE: {linked} of {len(unlinked)}")
        if refused:
            total = sum(len(v) for v in refused.values())
            print(f"  REFUSED : {total}")
            for reason, ids in sorted(refused.items()):
                shown = ", ".join(str(i) for i in ids[:6])
                more = f" (+{len(ids) - 6} more)" if len(ids) > 6 else ""
                print(f"     {len(ids):3d}  {reason}: {shown}{more}")

        if apply:
            db.session.commit()
            print("\nCOMMITTED.")
        else:
            db.session.rollback()
            print("\nDRY-RUN — nothing committed. Re-run with --apply to commit.")
        return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
