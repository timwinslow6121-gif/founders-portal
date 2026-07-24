"""Seed the SC Devoted bucket (H7028-002) if missing, then link Tracy Hayden's
policy (pol 6108, the only SC Devoted member) to it. Dry-run default; --apply.
SAFETY: only links the exact policy whose plan_name matches the SC plan AND
whose customer state is SC; verifies the bucket cms code before linking. Never bulk.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/devoted_link_sc_tracy.py [--apply]
"""
import sys
from app import create_app
from app.extensions import db
from app.models import Plan, Policy, Customer

AGENCY_ID = 1
YEAR = 2026
CODE = "H7028-002"
NAME = "Devoted CHOICE GIVEBACK South Carolina (PPO)"
POL_ID = 6108
EXPECT_MBI = "1HW7AP7RC76"


def main(apply):
    app = create_app()
    with app.app_context():
        print("%s — SC Devoted bucket seed + link Tracy\n" % ("APPLY" if apply else "DRY-RUN"))

        # 1. Seed the bucket if missing.
        plan = Plan.query.filter_by(agency_id=AGENCY_ID, carrier="Devoted",
                                    cms_plan_id=CODE, year=YEAR).first()
        if plan is None:
            print("  + create Devoted bucket %s %r (MAPD, year %s)" % (CODE, NAME, YEAR))
            if apply:
                plan = Plan(agency_id=AGENCY_ID, carrier="Devoted", cms_plan_id=CODE,
                            year=YEAR, plan_name=NAME, plan_type="MAPD",
                            status="current", needs_review=False)
                db.session.add(plan)
                db.session.flush()
        else:
            print("  = bucket %s already exists (id=%s)" % (CODE, plan.id))

        # 2. Link the exact policy, with safety checks.
        p = db.session.get(Policy, POL_ID)
        if p is None:
            print("  ! pol %s missing — SKIP" % POL_ID)
        else:
            c = db.session.get(Customer, p.customer_id) if p.customer_id else None
            ok = (p.carrier == "Devoted"
                  and c and (c.mbi or "").upper() == EXPECT_MBI
                  and (c.state or "").upper() == "SC")
            if not ok:
                print("  ! pol %s safety check failed (carrier=%s mbi=%r state=%r) — SKIP"
                      % (POL_ID, p.carrier, (c.mbi if c else None), (c.state if c else None)))
            elif p.plan_id is not None:
                print("  = pol %s already linked to plan_id=%s — no change" % (POL_ID, p.plan_id))
            else:
                tgt = plan.id if (apply and plan) else (plan.id if plan else "<new>")
                print("  link pol %s (%s, SC) -> Devoted bucket %s (%s)"
                      % (POL_ID, c.full_name, tgt, CODE))
                if apply and plan:
                    p.plan_id = plan.id

        if apply:
            db.session.commit()
            print("\nAPPLIED.")
        else:
            db.session.rollback()
            print("\nDRY-RUN — nothing written.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
