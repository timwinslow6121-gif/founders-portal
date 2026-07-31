"""Load each DB plan's service-area counties from the CMS Landscape CSV into
plan_service_areas (drives the plan-detail service-area bar). Matches DB plans by
CMS contract+plan ID (dash-form cms_plan_id, e.g. H5253-041) + year. Idempotent:
replaces a matched plan's county rows (delete-then-insert). Skips non-carried plans,
plans with no CMS ID (Medigap/DVH/HI), and the 'All Counties'/blank county sentinels.

Read-only unless --apply. Mirrors scripts/seed_plan_buckets.py.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_plan_service_areas.py \
      --agency 1 --file "docs/Medicare Landscape Files/CY2026_Landscape_202603/CY2026_Landscape_202603.csv" [--apply]
"""
import argparse
import csv

from app import create_app
from app.extensions import db
from app.models import Plan, PlanServiceArea

CMS_YEAR = 2026
_SENTINEL_COUNTIES = {"", "all counties"}


def seed_service_areas_from_rows(rows, agency_id, apply=False, states=("NC",)):
    """Build (contract, plan) -> {(state, county)} from CSV rows, then for each DB
    plan with a matching dash-form cms_plan_id + year, replace its county rows."""
    states_up = {s.strip().upper() for s in states}

    # contract+plan (dash-form) -> set[(state, county)]
    wanted = {}
    for row in rows:
        st = (row.get("State Territory Abbreviation") or "").strip().upper()
        if st not in states_up:
            continue
        county = (row.get("County Name") or "").strip()
        if county.lower() in _SENTINEL_COUNTIES:
            continue
        contract = (row.get("Contract ID") or "").strip()
        plan = (row.get("Plan ID") or "").strip()
        if not contract or not plan:
            continue
        cms_id = f"{contract}-{plan}"                 # dash-form, matches Plan.cms_plan_id
        wanted.setdefault(cms_id, set()).add((st, county))

    report = {"plans_matched": 0, "counties_loaded": 0,
              "plans_skipped_no_cms": 0, "cms_not_in_csv": []}

    plans = Plan.query.filter_by(agency_id=agency_id, year=CMS_YEAR).all()
    for p in plans:
        if not p.cms_plan_id:
            report["plans_skipped_no_cms"] += 1
            continue
        counties = wanted.get(p.cms_plan_id)
        if not counties:
            report["cms_not_in_csv"].append(p.cms_plan_id)
            continue
        report["plans_matched"] += 1
        report["counties_loaded"] += len(counties)
        if apply:
            PlanServiceArea.query.filter_by(plan_id=p.id).delete()
            for st, county in sorted(counties):
                db.session.add(PlanServiceArea(plan_id=p.id, agency_id=agency_id,
                                               state=st, county=county))
    if apply:
        db.session.commit()
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--states", default="NC", help="comma-separated state abbrevs")
    args = ap.parse_args()
    states = tuple(s.strip() for s in args.states.split(",") if s.strip())

    app = create_app()
    with app.app_context():
        with open(args.file, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        res = seed_service_areas_from_rows(rows, args.agency, apply=args.apply, states=states)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] plans_matched={res['plans_matched']} "
              f"counties_loaded={res['counties_loaded']} "
              f"skipped_no_cms={res['plans_skipped_no_cms']} "
              f"cms_not_in_csv={len(res['cms_not_in_csv'])}")
        if res["cms_not_in_csv"]:
            print("  CMS IDs in DB but not in CSV:", ", ".join(sorted(res["cms_not_in_csv"])[:40]))


if __name__ == "__main__":
    main()
