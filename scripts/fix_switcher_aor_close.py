"""One-time fix: close the OPEN UHC AOR chapter for the 2 switchers whose UHC
policy was already termed (term_devoted_switchers.py v1 termed the policy but not
the AOR interval, so the timeline showed UHC as still-current alongside Devoted).
Dry-run default; --apply. SAFETY: only closes a UHC chapter whose customer's UHC
policy is ALREADY termed, using that policy's term_date as the AOR end_date.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/fix_switcher_aor_close.py [--apply]
"""
import sys
from app import create_app
from app.extensions import db
from app.models import Policy, Customer, CustomerAorHistory

CUST_IDS = [5765, 5979]   # Timothy Elliott, Mary Coe


def main(apply):
    app = create_app()
    with app.app_context():
        print("%s — close open UHC AOR for termed switchers\n" % ("APPLY" if apply else "DRY-RUN"))
        fixed = 0
        for cid in CUST_IDS:
            c = db.session.get(Customer, cid)
            uhc = Policy.query.filter_by(customer_id=cid, carrier="UHC").first()
            if not uhc or uhc.status != "termed" or not uhc.term_date:
                print("  ! cust %s (%s): UHC policy not termed-with-date — SKIP"
                      % (cid, (c.full_name if c else "?")))
                continue
            open_iv = CustomerAorHistory.query.filter_by(
                customer_id=cid, carrier="UHC", end_date=None).first()
            if not open_iv:
                print("  = cust %s (%s): no open UHC AOR chapter — nothing to do" % (cid, c.full_name))
                continue
            print("  close UHC AOR for %-18s eff=%s  -> end_date=%s (= policy term)"
                  % (c.full_name, open_iv.effective_date, uhc.term_date))
            if apply:
                open_iv.end_date = uhc.term_date
                fixed += 1
        if apply:
            db.session.commit()
            print("\nAPPLIED — %d AOR chapters closed." % fixed)
        else:
            db.session.rollback()
            print("\nDRY-RUN — nothing written.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
