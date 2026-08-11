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

DEVOTED + AETNA (added 2026-08-11) resolve from their BOBs instead, because those
BOBs DO carry a per-member plan id (unlike UHC's, which omits these members
entirely). Same six gates, different source:
  - Devoted: `application_status_report_2026_` sheet has Mbi + Plan ID. Only the
    WINNING app counts (`Is Winning App = Yes`) — Devoted keeps every application
    including superseded ones, so ignoring that flag would link a member to a plan
    they didn't end up on. Verified: each of the 12 has exactly ONE winning app and
    none carries a disenrollment date.
  - Aetna: BOB carries `CMS Contract Number` + `PBP Code` (PBP is unpadded, so
    "81" must be zero-filled to "081" to form H5521-081).

⚠ SOURCE STRENGTH DIFFERS. A commission payment is the CARRIER ASSERTING it paid
on that member+plan; a BOB is a snapshot that can lag or run ahead. The two
Devoted rows whose status is `Approved` rather than `Enrolled` are the softest
links here — they are winning apps with real plan ids, but they are not yet
confirmed enrollments.

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


def families_agree(db_family, file_family, bucket_type, *, type_optional=False):
    """Gate 6. The SNP families are all drug plans, so DSNP/CSNP/MAPD are mutually
    compatible and must sit on a 'mapd' bucket. MA is strict: it must land on an
    'ma' bucket, never a MAPD one — and vice versa.

    `type_optional` covers sources with no plan-type column (Devoted's BOB). There
    the bucket's own curated type is trusted, BUT the MA/MAPD guard still runs
    against whatever Policy.plan_type holds: an MA-typed policy may only land on an
    'ma' bucket, and an explicitly drug-typed policy may only land on 'mapd'. A
    policy with NO type at all is allowed through — the bucket is then the only
    claim being made, which is exactly the Devoted case.
    """
    bucket_type = (bucket_type or "").strip().lower()
    drug = {"DSNP", "CSNP", "MAPD"}
    if type_optional and not file_family:
        if db_family == "MA":
            return bucket_type == "ma"
        if db_family in drug:
            return bucket_type == "mapd"
        return bucket_type in ("ma", "mapd", "pdp", "medigap", "dvh")
    if db_family == "MA" or file_family == "MA":
        return db_family == file_family == "MA" and bucket_type == "ma"
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


DEVOTED_BOB = "docs/Carrier BOB DL/July 2026 period/Devoted/Devoted Book of business.xlsx"
DEVOTED_SHEET = "application_status_report_2026_"
DEVOTED_PREFIX = "Application Status Report "
AETNA_BOB = "docs/Carrier BOB DL/July 2026 period/Aetna/Aetna Book of Business.xlsx"


def read_devoted_bob():
    """member MBI -> {'cps', 'types', 'names'} from the Devoted BOB.

    ONLY the winning app counts. Devoted's report keeps every application a member
    ever submitted, including superseded ones; a member who switched plans has both
    rows. Ignoring `Is Winning App` would link them to the plan they left.
    Rows carrying a disenrollment date are skipped — that member is not active on it.
    """
    found = defaultdict(lambda: {"cps": set(), "types": set(), "names": set()})
    if not os.path.exists(DEVOTED_BOB):
        print(f"  !! Devoted BOB not found: {DEVOTED_BOB}")
        return found
    d = pd.read_excel(DEVOTED_BOB, sheet_name=DEVOTED_SHEET, dtype=str).dropna(how="all")
    p = DEVOTED_PREFIX
    kept = 0
    for _, r in d.iterrows():
        if norm(r.get(f"{p}Is Winning App (Yes / No)")) != "YES":
            continue
        if norm(r.get(f"{p}Disenrollment Date")):
            continue
        mbi = norm(r.get(f"{p}Mbi"))
        plan_id = norm(r.get(f"{p}Plan ID"))
        if not mbi or not plan_id:
            continue
        rec = found[mbi]
        rec["cps"].add(plan_id)
        rec["names"].add(norm(r.get(f"{p}Full Name")))
        # Devoted has no plan-type column; the bucket's own type is authoritative
        # and gate 6 falls back to it (see families_agree / TYPE_OPTIONAL_CARRIERS).
        kept += 1
    print(f"  read {kept:5d} winning-app rows from {os.path.basename(DEVOTED_BOB)}")
    return found


def read_aetna_bob():
    """member MBI -> {'cps', 'types', 'names'} from the Aetna BOB.

    PBP Code is UNPADDED in this export ("81"), but CMS ids are 3-digit
    ("H5521-081"), so it must be zero-filled or every lookup misses.
    """
    found = defaultdict(lambda: {"cps": set(), "types": set(), "names": set()})
    if not os.path.exists(AETNA_BOB):
        print(f"  !! Aetna BOB not found: {AETNA_BOB}")
        return found
    d = pd.read_excel(AETNA_BOB, dtype=str).dropna(how="all")
    kept = 0
    for _, r in d.iterrows():
        mbi = norm(r.get("Medicare Number"))
        contract = norm(r.get("CMS Contract Number"))
        pbp = norm(r.get("PBP Code"))
        if not mbi or not contract or not pbp:
            continue
        rec = found[mbi]
        rec["cps"].add(f"{contract}-{pbp.zfill(3)}")
        rec["names"].add(f"{norm(r.get('First Name'))} {norm(r.get('Last Name'))}")
        # NOTE: deliberately NOT populating rec["types"]. The Aetna BOB has no
        # plan-TYPE column — only a plan NAME ("AETNA MEDICARE SIGNATURE (PPO)"),
        # which names the network, not whether the plan carries drug coverage.
        # Feeding a name into plan_family() yields garbage and the gate refuses a
        # correct link. Aetna is therefore type-optional like Devoted: the bucket's
        # curated type is trusted, with the MA/MAPD guard still enforced against
        # Policy.plan_type.
        kept += 1
    print(f"  read {kept:5d} rows from {os.path.basename(AETNA_BOB)}")
    return found


# Carriers whose source has no usable plan-TYPE column. For these, gate 6 falls
# back to trusting the BUCKET's own type (the bucket is the curated record), but
# the MA/MAPD guard still applies against Policy.plan_type where it is set.
# Devoted's BOB has no type column at all; Aetna's has only a plan NAME, which
# describes the network (PPO/HMO), not drug coverage — see read_aetna_bob().
TYPE_OPTIONAL_CARRIERS = {"Devoted", "Aetna"}


def find_bucket(agency_id, cms_dash, carrier):
    """Match a Plan bucket by cms_plan_id in dash OR underscore form, scoped to the
    carrier. NEVER creates — a miss returns None and the row is refused."""
    contract, _, pbp = cms_dash.partition("-")
    under = f"{contract}_{pbp}"
    return (Plan.query
            .filter_by(agency_id=agency_id, carrier=carrier)
            .filter(Plan.cms_plan_id.in_([cms_dash, under]))
            .first())


def link_carrier(agency_id, carrier, by_mbi, apply):
    """Resolve + link one carrier's unlinked actives. Returns (linked, refused)."""
    type_optional = carrier in TYPE_OPTIONAL_CARRIERS

    # Gate 1+2: only unlinked, active rows for THIS carrier are even considered.
    unlinked = (Policy.query
                .filter_by(agency_id=agency_id, carrier=carrier,
                           status="active", plan_id=None)
                .all())
    print(f"\n{carrier}: active policies with plan_id IS NULL: {len(unlinked)}")

    linked = 0
    refused = defaultdict(list)
    for p in unlinked:
        # Gate 2 re-assert: never trust the query alone for a write.
        if p.carrier != carrier or p.status != "active" or p.plan_id is not None:
            refused["safety re-assert failed"].append(p.id)
            continue

        rec = by_mbi.get(norm(p.mbi)) or by_mbi.get(norm(p.member_id))
        if not rec:
            refused["not in the source file"].append(p.id)
            continue

        # Gate 3: one unambiguous contract-PBP, or refuse.
        if len(rec["cps"]) != 1:
            refused[f"ambiguous contract-pbp {sorted(rec['cps'])}"].append(p.id)
            continue
        cms = next(iter(rec["cps"]))

        # Gate 4: the bucket must already exist.
        bucket = find_bucket(agency_id, cms, carrier)
        if not bucket:
            refused[f"no Plan bucket for {cms}"].append(p.id)
            continue

        cust = (Customer.query
                .filter_by(id=p.customer_id, agency_id=agency_id).first()
                if p.customer_id else None)

        # Gate 5: name agreement between the source and the DB customer.
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
        if not families_agree(db_fam, file_fam, bucket.plan_type,
                              type_optional=type_optional):
            refused[f"TYPE MISMATCH db={db_fam} file={file_fam} "
                    f"bucket={bucket.plan_type}"].append(p.id)
            continue

        print(f"  pid {p.id:>5}  {db_name[:26]:<26} {db_fam or '-':<5} -> {cms} "
              f"bucket {bucket.id} '{(bucket.plan_name or '')[:34]}'")
        if apply:
            p.plan_id = bucket.id
            if not (p.plan_name or "").strip():
                p.plan_name = bucket.plan_name
        linked += 1

    print(f"  LINKABLE: {linked} of {len(unlinked)}")
    if refused:
        total = sum(len(v) for v in refused.values())
        print(f"  REFUSED : {total}")
        for reason, ids in sorted(refused.items()):
            shown = ", ".join(str(i) for i in ids[:6])
            more = f" (+{len(ids) - 6} more)" if len(ids) > 6 else ""
            print(f"     {len(ids):3d}  {reason}: {shown}{more}")
    return linked, refused


def main(apply):
    app = create_app()
    with app.app_context():
        agency_id = app.config.get("DEFAULT_AGENCY_ID", 1)
        print(f"{'APPLY' if apply else 'DRY-RUN'} — plan linkage (UHC / Devoted / Aetna)\n")

        print("Reading sources:")
        uhc_by_mbi, files = read_commission_files()
        if not files:
            return 1
        print(f"  -> UHC: {len(uhc_by_mbi)} distinct MBIs across {len(files)} file(s)")
        devoted_by_mbi = read_devoted_bob()
        aetna_by_mbi = read_aetna_bob()

        total_linked = 0
        for carrier, by_mbi in (("UHC", uhc_by_mbi),
                                ("Devoted", devoted_by_mbi),
                                ("Aetna", aetna_by_mbi)):
            if not by_mbi:
                print(f"\n{carrier}: no source data — skipped.")
                continue
            linked, _ = link_carrier(agency_id, carrier, by_mbi, apply)
            total_linked += linked

        print(f"\n=== TOTAL LINKABLE: {total_linked} ===")
        if apply:
            db.session.commit()
            print("COMMITTED.")
        else:
            db.session.rollback()
            print("DRY-RUN — nothing committed. Re-run with --apply to commit.")
        return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
