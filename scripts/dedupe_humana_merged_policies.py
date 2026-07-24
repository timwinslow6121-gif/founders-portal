"""Consolidate the 13 merged keepers' 2 active Humana policies into ONE.

After merging the Humana stubs (merge_humana_stub_pairs.py), each keeper has 2
active Humana policies for the SAME enrollment seen from 2 sources:
  - COMMISSION-side: numeric member_id (the commission PID), blank plan, holds the
    money (PolicyPayments).
  - BOB-side: Humana-ID member_id (H########), real plan_name + plan_id, $0.

Consolidate onto the BOB policy (real plan + Humana ID = matches future imports):
  1. Set BOB policy effective_date = EARLIEST of the two (the true start date).
  2. Re-point the commission policy's PolicyPayments -> the BOB policy.
  3. Delete the commission policy.

SAFETY per keeper: exactly ONE numeric-PID active Humana + exactly ONE Humana-ID
active Humana; re-point count must equal the source payment count; only delete
after 0 payments remain on it. Dry-run default; --apply.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/dedupe_humana_merged_policies.py [--apply]
"""
import sys
from app import create_app
from app.extensions import db
from app.models import Policy, PolicyPayment, Customer

KEEPERS = [7154, 7623, 6343, 7110, 6958, 7076, 7865, 6963, 7463, 7093, 7520, 7363, 6728]


def main(apply):
    app = create_app()
    with app.app_context():
        print("%s — consolidate 13 keepers' dup Humana policies\n" % ("APPLY" if apply else "DRY-RUN"))
        done = 0
        for k in KEEPERS:
            c = db.session.get(Customer, k)
            pols = Policy.query.filter_by(customer_id=k, carrier="Humana", status="active").all()
            comm = [p for p in pols if str(p.member_id).isdigit()]
            bob = [p for p in pols if not str(p.member_id).isdigit()]
            if len(pols) != 2 or len(comm) != 1 or len(bob) != 1:
                print("  ! %s (cust %s): expected 1 numeric + 1 Humana-ID active, got %d/%d — SKIP"
                      % ((c.full_name if c else k), k, len(comm), len(bob)))
                continue
            cp, bp = comm[0], bob[0]
            src_pp = PolicyPayment.query.filter_by(policy_id=cp.id).all()
            # BOB should have $0 (all money on the commission side)
            bob_pp = PolicyPayment.query.filter_by(policy_id=bp.id).count()
            if bob_pp:
                print("  ! %s: BOB policy already has %d payments — SKIP (unexpected)" % (c.full_name, bob_pp))
                continue
            earliest = min(d for d in (cp.effective_date, bp.effective_date) if d) if (cp.effective_date or bp.effective_date) else bp.effective_date
            print("  %-20s keep BOB pol %s (%s) eff %s->%s | move %d payments from comm pol %s, delete it"
                  % (c.full_name, bp.id, bp.plan_name, bp.effective_date, earliest, len(src_pp), cp.id))
            if apply:
                bp.effective_date = earliest
                for pp in src_pp:
                    pp.policy_id = bp.id
                db.session.flush()
                # safety: comm policy must now have 0 payments before delete
                if PolicyPayment.query.filter_by(policy_id=cp.id).count() != 0:
                    print("     ! payments still on comm pol %s — rollback this one" % cp.id)
                    db.session.rollback()
                    continue
                db.session.delete(cp)
                db.session.commit()
                done += 1
        if apply:
            print("\nAPPLIED — %d consolidated." % done)
        else:
            db.session.rollback()
            print("\nDRY-RUN — nothing written.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
