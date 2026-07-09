"""Seed DVH (Dental/Vision/Hearing) plan buckets — HAND-MAINTAINED, name/identity only.

DVH plans are NOT in the CMS MA/PDP Landscape (they're carrier-filed ancillary products),
and they have a DIFFERENT benefit shape than MAPD/PDP/medigap (annual max + calendar-year
deductible + dental preventive/basic/major tiers + vision/hearing exams — NO MOOP, NO drug
tiers, NO PCP copay). So they're seeded here by identity only; the structured DVH benefit
fields are the job of the type-driven add-plan form (plan-taxonomy spec). One bucket per
(carrier, plan_name, year=PERPETUAL) — DVH benefits aren't annual like MA.

find_plan_bucket classifies DVH as 'named' and matches by plan_name at PERPETUAL, so the
BOB plan_name must match the bucket name (or an alias).

To maintain: add rows to _DVH_PLANS as agents write new DVH products.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_dvh_buckets.py \
      --agency 1 [--apply]
"""
import argparse

from app import create_app
from app.extensions import db
from app.models import Plan
from app.plan_codes import PERPETUAL

# (carrier, plan_name, alias-for-BOB-name). Verified against the carrier plan doc.
_DVH_PLANS = [
    # Humana Extend 1250 DVH (NC, policy NC-72032 1250). BOB writes it as
    # "NC EXTEND 1250 MNTH DEL '23" — aliased so those policies sort in.
    ("Humana", "Humana Extend 1250 (DVH)", "NC EXTEND 1250 MNTH DEL '23"),
]


def seed_dvh(agency_id, apply=False):
    counts = {"created": 0, "already": 0}
    for carrier, name, alias in _DVH_PLANS:
        plan = (Plan.query.filter_by(agency_id=agency_id, carrier=carrier, year=PERPETUAL)
                .filter(db.func.upper(Plan.plan_name) == name.upper()).first())
        if plan is not None:
            counts["already"] += 1
            continue
        counts["created"] += 1
        if apply:
            db.session.add(Plan(agency_id=agency_id, carrier=carrier, cms_plan_id=None,
                                year=PERPETUAL, plan_name=name, plan_type="dvh",
                                plan_name_aliases=alias, status="current",
                                needs_review=False))
    if apply:
        db.session.commit()
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        res = seed_dvh(args.agency, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] DVH bucket seed, agency {args.agency}:")
        print(f"  created: {res['created']}")
        print(f"  already: {res['already']}")


if __name__ == "__main__":
    main()
