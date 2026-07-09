"""Aetna MBI-crosswalk plan backfill — resolve blank-plan Aetna orphans from the Aetna BOB.

Aetna's commission and BOB SHARE the MBI (the Aetna BOB keys member_id = MBI), so unlike
Humana these are 100% joinable. The BOB also carries the full CMS code (CMS Contract
Number + PBP Code columns). This script:
  1. parses the Aetna BOB → index by MBI (plan_name + cms_contract_number + pbp_code)
  2. for each active Aetna policy with NO plan_id, if its MBI is in the BOB, builds a rec
     from the BOB and runs find_plan_bucket (sorts by the full code) — setting plan_id +
     filling plan_name/contract_code. A policy whose plan has no seeded bucket is left
     untouched + reported (never auto-bucketed).

This is the per-carrier crosswalk pattern (memory commission-bob-crosswalk-diagnosis.md),
Aetna-first because it's the clean 100%-MBI-match case. NEVER creates a Plan bucket.
Read-only unless --apply. Seed any missing buckets (e.g. S5601-017 SilverScript Plus PDP)
BEFORE running so those policies link too.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/crosswalk_aetna_plan_from_bob.py \
      --agency 1 --bob "docs/Carrier BOB DL/July 2026 period/Aetna/Aetna Book of Business.xlsx" [--apply]
"""
import argparse
from collections import Counter

from app import create_app
from app.extensions import db
from app.models import Policy
from app.parsers import parse_carrier_file
from app.plan_bucket import find_plan_bucket


def _bob_index(bob_path):
    """MBI (upper) → {plan_name, cms_contract_number, pbp_code} from the Aetna BOB."""
    idx = {}
    for r in parse_carrier_file("Aetna", bob_path):
        mbi = (r.get("mbi") or "").strip().upper()
        if mbi:
            idx[mbi] = {"plan_name": r.get("plan_name") or "",
                        "cms_contract_number": r.get("cms_contract_number") or "",
                        "pbp_code": r.get("pbp_code") or ""}
    return idx


def crosswalk(agency_id, bob_path, year=2026, apply=False):
    idx = _bob_index(bob_path)
    counts = {"linked": 0, "no_bob_match": 0, "no_bucket": 0}
    leftover = Counter()
    orphans = (Policy.query
               .filter(Policy.agency_id == agency_id, Policy.carrier == "Aetna",
                       Policy.status == "active", Policy.plan_id.is_(None))
               .all())
    for pol in orphans:
        mbi = (pol.mbi or "").strip().upper()
        bob = idx.get(mbi)
        if not bob:
            counts["no_bob_match"] += 1
            continue
        rec = {"plan_name": bob["plan_name"], "plan_type": pol.plan_type or "",
               "cms_contract_number": bob["cms_contract_number"], "pbp_code": bob["pbp_code"]}
        b = find_plan_bucket("Aetna", rec, year, agency_id)
        if b["plan_id"]:
            counts["linked"] += 1
            if apply:
                pol.plan_id = b["plan_id"]
                pol.contract_code = b["contract_code"]
                pol.plan_year = b["plan_year"]
                if bob["plan_name"]:
                    pol.plan_name = bob["plan_name"]     # fill the real name from the BOB
        else:
            counts["no_bucket"] += 1
            leftover[bob["plan_name"] or f"{bob['cms_contract_number']}-{bob['pbp_code']}"] += 1
    counts["leftover_plans"] = [f"{n} ({k})" for n, k in leftover.most_common()]
    if apply:
        db.session.commit()
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--bob", required=True)
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        res = crosswalk(args.agency, args.bob, year=args.year, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] Aetna plan crosswalk from BOB, agency {args.agency}:")
        print(f"  linked:       {res['linked']}")
        print(f"  no_bob_match: {res['no_bob_match']}")
        print(f"  no_bucket:    {res['no_bucket']}  (BOB has plan but no seeded bucket)")
        for n in res["leftover_plans"]:
            print(f"    {n}")


if __name__ == "__main__":
    main()
