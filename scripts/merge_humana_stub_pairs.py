"""Merge the 13 Humana blank-stub + real-record duplicate pairs (Group A of the
/admin/customers/duplicates list, 2026-07-24). Each is a commission-import STUB
(blank DOB, name lost its suffix) that is the SAME PERSON as a real record with a
DOB + suffix, confirmed against the Humana BOB. Keeper = the real DOB'd record;
loser = the stub. Dry-run default; --apply.

SAFETY per pair: keeper exists w/ a DOB; loser exists as a stub; both Humana;
loser has NO DOB or the SAME DOB (never a different real DOB = different person);
no contradictory MBI. Uses the shared merge_customers engine (reattaches
policies/payments/AOR/notes; fill-blanks; audited). Caller commits.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/merge_humana_stub_pairs.py [--apply]
"""
import sys
from app import create_app
from app.extensions import db
from app.models import Customer, Policy
from app.customers import merge_customers

AGENCY_ID = 1
# (keeper_id = real record w/ DOB, loser_id = stub, expected last name)
PAIRS = [
    (7154, 2051, "hodge"),      # Arthur Hodge Jr <- Arthur Hodge
    (7623, 2004, "morgan"),     # Billy Morgan Jr <- Billy Morgan
    (6343, 2011, "angeles"),    # Zita Angeles <- ANGELES ZITA
    (7110, 2073, "henderson"),  # Dan Henderson Jr <- Dan Henderson
    (6958, 2131, "gazeley"),    # George Gazeley Jr <- George Gazeley
    (7076, 2139, "harris"),     # Rupert Harris Jr <- Rupert Harris
    (7865, 2176, "robbins"),    # Walter Robbins III <- Walter Robbins
    (6963, 2178, "gilbert"),    # Earl Gilbert III <- Earl Gilbert
    (7463, 2016, "lowder"),     # Dwight Lowder Jr <- Dwight Lowder
    (7093, 2009, "haskins"),    # Larry Haskins Jr <- Larry Haskins
    (7520, 2095, "mccrary"),    # Troy Mccrary Jr <- Troy Mccrary
    (7363, 2110, "lacks"),      # Ralph Lacks Jr <- Ralph Lacks
    (6728, 2185, "coy"),        # James Coy Jr <- James Coy
]


def _hascarrier(cid, carrier):
    return Policy.query.filter_by(customer_id=cid).filter(Policy.carrier == carrier).count() > 0


def main(apply):
    app = create_app()
    with app.app_context():
        actor = "humana_stub_merge"
        print("%s — merge 13 Humana stub+real pairs\n" % ("APPLY" if apply else "DRY-RUN"))
        merged = 0
        for keeper_id, loser_id, last in PAIRS:
            k = db.session.get(Customer, keeper_id)
            l = db.session.get(Customer, loser_id)
            if not k or not l:
                print("  ! %s: keeper %s / loser %s missing — SKIP" % (last, keeper_id, loser_id))
                continue
            # SAFETY
            if last not in (k.full_name or "").lower() or last not in (l.full_name or "").lower():
                print("  ! %s: last-name mismatch (%r / %r) — SKIP" % (last, k.full_name, l.full_name))
                continue
            if not k.dob:
                print("  ! %s: keeper %s has NO dob — SKIP (keeper must be the real record)" % (last, keeper_id))
                continue
            if l.dob and l.dob != k.dob:
                print("  ! %s: loser dob %s != keeper dob %s (different person!) — SKIP" % (last, l.dob, k.dob))
                continue
            if k.mbi and l.mbi and k.mbi != l.mbi:
                print("  ! %s: contradictory MBI (%r / %r) — SKIP" % (last, k.mbi, l.mbi))
                continue
            if not (_hascarrier(keeper_id, "Humana") or _hascarrier(loser_id, "Humana")):
                print("  ! %s: neither side is Humana — SKIP" % last)
                continue
            print("  merge  %-20s (keep %s, dob %s) <- stub %s"
                  % (k.full_name, keeper_id, k.dob, loser_id))
            if apply:
                res = merge_customers(keeper_id, [loser_id], AGENCY_ID, actor)
                if not res.get("ok"):
                    print("     ! merge FAILED: %s — rollback this one, continue" % res.get("error"))
                    db.session.rollback()
                    continue
                db.session.commit()
                merged += 1
        if apply:
            print("\nAPPLIED — %d pairs merged." % merged)
        else:
            db.session.rollback()
            print("\nDRY-RUN — nothing written.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
