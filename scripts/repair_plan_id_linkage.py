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
from app.models import Plan, Policy
from app.plan_bucket import find_plan_bucket

# Generic plan-type CATEGORIES (not plan names). If plan_type is one of these it is a
# real category; anything else in plan_type (e.g. "Blue Medicare Medical Only (HMO-POS)")
# is a mis-columned plan NAME from an older parser and should be used for matching.
_GENERIC_TYPES = {"", "mapd", "ma", "pdp", "csnp", "dsnp", "d-snp", "c-snp",
                  "medigap", "ms", "dvh", "dental", "gtl", "other", "medicare supplement"}


def _miscolumned_name(pol):
    """If plan_name is blank but plan_type holds a real plan NAME (not a generic
    category), return that name; else None. Recovers the legacy BCBS mis-column."""
    if (pol.plan_name or "").strip():
        return None
    pt = (pol.plan_type or "").strip()
    if pt and pt.lower() not in _GENERIC_TYPES:
        return pt
    return None


def plan_repairs(agency_id, year, apply=False):
    counts = {"linked": 0, "leftover": 0, "miscolumn_fixed": 0}
    leftover = Counter()
    orphans = (Policy.query
               .filter(Policy.agency_id == agency_id, Policy.status == "active",
                       Policy.plan_id.is_(None))
               .all())
    for pol in orphans:
        recovered = _miscolumned_name(pol)          # legacy plan-name-in-plan_type
        match_name = pol.plan_name or recovered or ""
        rec = {"plan_name": match_name, "plan_type": pol.plan_type,
               "cms_contract_number": "", "pbp_code": ""}
        b = find_plan_bucket(pol.carrier, rec, year, agency_id)
        if b["plan_id"]:
            counts["linked"] += 1
            if apply:
                pol.plan_id = b["plan_id"]
                pol.contract_code = b["contract_code"]
                pol.plan_year = b["plan_year"]
                if recovered:
                    # Fix the mis-columned data: move the name into plan_name and reset
                    # plan_type to the matched bucket's real category.
                    pol.plan_name = recovered
                    bucket = Plan.query.get(b["plan_id"])
                    if bucket and bucket.plan_type:
                        pol.plan_type = bucket.plan_type
                    counts["miscolumn_fixed"] += 1
        else:
            counts["leftover"] += 1
            leftover[(pol.carrier, pol.plan_name or recovered)] += 1
    counts["leftover_names"] = [f"{c} | {n} ({k})" for (c, n), k in leftover.most_common()]
    if apply:
        db.session.commit()
    # Dry-run: plan_id/contract_code/plan_year are only mutated inside `if apply:`
    # above, so there is nothing of ours to undo here. Do NOT call db.session.rollback()
    # unconditionally — that would also discard the CALLER's own uncommitted work
    # (e.g. a caller that flush()'d fixture rows without committing).
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
        print(f"  miscolumn_fixed: {res['miscolumn_fixed']}  (plan name recovered from plan_type)")
        print(f"  leftover: {res['leftover']}  (no seeded bucket — map manually)")
        for n in res["leftover_names"]:
            print(f"    {n}")


if __name__ == "__main__":
    main()
