"""Apply the corrected lane-aware merge to Barbara Overcash — the confirmed
cross-carrier switcher (Aetna PLUS PDP 2024 + UHC MAPD 2026, same DOB, diff MBI).
The live proof case for the lane-aware merge. Dry-run default; --apply.

Expected: ONE record, current MBI = UHC's 1X88VQ0CP30 (newer plan), Aetna PDP
superseded->termed + its AOR closed, no coexisting product touched.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/apply_overcash_lane_merge.py [--apply]
"""
import sys
from app import create_app
from app.extensions import db
from app.models import Customer, Policy, User
from app.customers import merge_customers_lane_aware

AGENCY_ID = 1
# UHC record (current, newer) = keeper; Aetna record (older) = loser.
KEEPER_ID = 5609   # UHC MAPD, mbi 1X88VQ0CP30, eff 2026
LOSER_ID = 6295    # Aetna PLUS PDP, mbi 2WA7KC0TM50, eff 2024


def show(cid, label):
    c = db.session.get(Customer, cid)
    if not c:
        print("  %s cust %s: MISSING/MERGED" % (label, cid)); return
    print("  %s cust %s: %r dob=%s mbi=%r" % (label, cid, c.full_name, c.dob, c.mbi))
    for p in Policy.query.filter_by(customer_id=cid).all():
        print("      [%s] %s mid=%r plan=%r eff=%s term=%s"
              % (p.status, p.carrier, p.member_id, p.plan_name, p.effective_date, p.term_date))


def main(apply):
    app = create_app()
    with app.app_context():
        actor = User.query.filter_by(is_admin=True).first()
        print("%s — Overcash lane-aware merge\n" % ("APPLY" if apply else "DRY-RUN"))
        print("BEFORE:")
        show(KEEPER_ID, "keeper(UHC)")
        show(LOSER_ID, "loser(Aetna)")
        print()

        if apply:
            res = merge_customers_lane_aware(KEEPER_ID, [LOSER_ID], AGENCY_ID, actor)
            print("result:", res)
            if not res.get("ok"):
                db.session.rollback()
                print("FAILED — rolled back.")
                return
            print("\nAFTER:")
            show(KEEPER_ID, "keeper")
            show(LOSER_ID, "loser")
        else:
            print("DRY-RUN — nothing written. (merge_customers_lane_aware commits "
                  "internally, so we cannot rollback-preview it; --apply to run.)")


if __name__ == "__main__":
    main("--apply" in sys.argv)
