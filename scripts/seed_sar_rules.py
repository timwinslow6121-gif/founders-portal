"""
Seed the CONFIRMED 2027 service-area reductions.

Every rule here comes from Tim or a carrier notice -- never inferred from the
2027 first-look CSV, which is Source=FL (unverified) and, for H1036-335, lists
only segment -001. See docs/superpowers/specs/2026-09-17-aep-pipeline-design.md.

A SAR is the highest-severity triage rule: the member is auto-assigned or loses
coverage for 2027. Seeding a WRONG one tells a customer their plan is ending
when it is not; missing a right one leaves them uncalled. So this script:

  - seeds only what Tim confirmed, plan + county, nothing derived
  - reports the blind spot: customers on that plan with NO county on file can
    never match a county-scoped rule, and silence there reads as "nobody hit"
  - reports OTHER counties on the same plan for human review, because the
    first-look service area suggests the exit may be wider than confirmed

Usage:
  ./venv/bin/python3 scripts/seed_sar_rules.py            # dry run
  ./venv/bin/python3 scripts/seed_sar_rules.py --apply
"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.extensions import db
from app.models import Plan, Policy, Customer, SarRule
from sqlalchemy import func

# (cms_plan_id, county, why). Confirmed by Tim 2026-09-18.
CONFIRMED = [
    ("H5525-035", "Cabarrus",
     "HumanaChoice Giveback exits Cabarrus for 2027 (first-look Key notes + "
     "Brian's Humana letter)"),
    ("H1036-335", "Cabarrus",
     "Humana Gold Plus 335 SAR in Cabarrus (Tim). NOTE: portal stores 335 at "
     "2-part grain, so this cannot be scoped to segment -002"),
    ("H1036-137", "Cabarrus",
     "Humana Gold Plus 137 SAR in Cabarrus (Tim). Mostly crosswalked away, but "
     "not entirely -- see the review section"),
    ("H2001-084", "Cabarrus",
     "UHC Access NC-23 -- the only UHC SAR needing an active plan choice (IMO "
     "AEP rollout notes)"),
]


def run(apply=False, agency_id=1):
    seeded = skipped = 0
    print(f"{'APPLY' if apply else 'DRY RUN'} -- SAR rules (agency {agency_id})\n")

    for cms, county, why in CONFIRMED:
        plans = Plan.query.filter(Plan.agency_id == agency_id,
                                  Plan.cms_plan_id == cms).all()
        if not plans:
            print(f"  {cms:<12} {county:<10} NO PLAN ROW -- skipped")
            continue

        for p in plans:
            existing = (SarRule.query
                        .filter(SarRule.agency_id == agency_id,
                                SarRule.plan_id == p.id,
                                func.upper(func.trim(SarRule.county)) == county.upper())
                        .first())
            if existing:
                skipped += 1
                print(f"  {cms:<12} {county:<10} already present (plan id {p.id})")
                continue

            # who this actually moves
            hit = (db.session.query(func.count(Customer.id))
                   .join(Policy, Policy.customer_id == Customer.id)
                   .filter(Policy.plan_id == p.id, Policy.status == "active",
                           Policy.agency_id == agency_id,
                           Customer.deceased_date.is_(None),
                           func.upper(func.trim(Customer.county)) == county.upper())
                   .scalar())
            blind = (db.session.query(func.count(Customer.id))
                     .join(Policy, Policy.customer_id == Customer.id)
                     .filter(Policy.plan_id == p.id, Policy.status == "active",
                             Policy.agency_id == agency_id,
                             Customer.deceased_date.is_(None),
                             db.or_(Customer.county.is_(None),
                                    func.trim(Customer.county) == ""))
                     .scalar())

            print(f"  {cms:<12} {county:<10} plan id {p.id:<5} -> {hit} customers Tier 1"
                  + (f"   BLIND SPOT: {blind} on this plan have no county" if blind else ""))
            print(f"               {why}")

            if apply:
                db.session.add(SarRule(agency_id=agency_id, plan_id=p.id,
                                       county=county, state="NC"))
            seeded += 1

    if apply:
        db.session.commit()

    # Review: other counties on the same plans. The first-look service area for
    # H1036-335-001 excludes Rowan/Iredell/Mecklenburg entirely, so these may or
    # may not also be exiting. Tim confirms against the carrier notice.
    print("\n  REVIEW -- other counties on these plans (NOT seeded):")
    for cms, county, _ in CONFIRMED:
        for p in Plan.query.filter(Plan.agency_id == agency_id,
                                   Plan.cms_plan_id == cms).all():
            _cty = func.upper(func.trim(Customer.county))
            rows = (db.session.query(_cty.label("cty"), func.count(Customer.id))
                    .join(Policy, Policy.customer_id == Customer.id)
                    .filter(Policy.plan_id == p.id, Policy.status == "active",
                            Policy.agency_id == agency_id,
                            Customer.deceased_date.is_(None),
                            func.upper(func.trim(Customer.county)) != county.upper(),
                            Customer.county.isnot(None),
                            func.trim(Customer.county) != "")
                    .group_by(_cty).order_by(func.count(Customer.id).desc()).all())
            if rows:
                shown = ", ".join(f"{c} {n}" for c, n in rows[:6])
                print(f"    {cms:<12} {shown}")

    print(f"\n  {'seeded' if apply else 'would seed'}: {seeded}   already present: {skipped}")
    if not apply:
        print("  Nothing was written. Re-run with --apply.")
    return {"seeded": seeded, "skipped": skipped}


if __name__ == "__main__":
    from app import create_app
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--agency", type=int, default=1)
    args = ap.parse_args()
    with create_app().app_context():
        run(apply=args.apply, agency_id=args.agency)
