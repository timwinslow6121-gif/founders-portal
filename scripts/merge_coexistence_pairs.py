"""Merge 2 COEXISTENCE duplicate pairs (same person, DOB+address confirmed, holding
a primary-medical plan + an ancillary plan that legitimately coexist). Keep BOTH
policies active. Dry-run default; --apply.

  Blanche Schwarz: Devoted MAPD (cust 14561, real MBI) + BCBS dental IDVH (cust 1610).
  Jana Benson:     UHC Medigap (cust 6247, real MBI) + UHC DVH (cust 6245).
                   ⚠ cust 6245's mbi = '45039665600' is a DVH POLICY NUMBER wrongly
                   in the mbi field (11 digits, fails CMS MBI format) — NULL it FIRST
                   so the merge engine's contradictory-MBI guard passes and the real
                   MBI (from the Medigap keeper) is the person's MBI.

Keeper = the record with the real MBI + most data. merge_customers reattaches the
loser's policy onto the keeper (both stay active — coexistence, nothing termed).

SAFETY: keeper+loser share DOB; keeper has a valid-format MBI; the only non-null
MBI on the loser (if any) is either equal to keeper's or a non-MBI policy number
that we null first. Dry-run default; --apply.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/merge_coexistence_pairs.py [--apply]
"""
import re
import sys
from app import create_app
from app.extensions import db
from app.models import Customer
from app.customers import merge_customers

AGENCY_ID = 1
_L = "ACDEFGHJKMNPQRTUVWXY"
_MBI_RE = re.compile(r"^[1-9][%(L)s][0-9%(L)s][0-9][%(L)s][0-9%(L)s][0-9][%(L)s][%(L)s][0-9][0-9]$" % {"L": _L})


def is_valid_mbi(v):
    return bool(v) and bool(_MBI_RE.match(str(v).strip().upper()))


# (keeper_id, loser_id) — keeper has the real MBI + full data.
PAIRS = [
    (14561, 1610),   # Blanche Schwarz: Devoted MAPD keeper <- BCBS dental
    (6247, 6245),    # Jana Benson: UHC Medigap keeper <- UHC DVH (null 45039665600 first)
]


def main(apply):
    app = create_app()
    with app.app_context():
        print("%s — merge 2 coexistence pairs (keep BOTH policies)\n" % ("APPLY" if apply else "DRY-RUN"))
        merged = 0
        for keeper_id, loser_id in PAIRS:
            k = db.session.get(Customer, keeper_id)
            l = db.session.get(Customer, loser_id)
            if not k or not l:
                print("  ! keeper %s / loser %s missing — SKIP" % (keeper_id, loser_id)); continue
            # SAFETY: same person = same name + same dob (both present)
            if (k.full_name or "").lower() != (l.full_name or "").lower():
                print("  ! %s: name mismatch %r/%r — SKIP" % (keeper_id, k.full_name, l.full_name)); continue
            if not k.dob or not l.dob or k.dob != l.dob:
                print("  ! %s: dob not equal/both-present (%s/%s) — SKIP (need DOB-confirmed)"
                      % (keeper_id, k.dob, l.dob)); continue
            if not is_valid_mbi(k.mbi):
                print("  ! keeper %s has no valid-format MBI (%r) — SKIP" % (keeper_id, k.mbi)); continue
            # If loser carries a non-MBI value in mbi (a policy number), null it first.
            if l.mbi and not is_valid_mbi(l.mbi):
                print("  %s (%s): loser mbi %r is NOT a valid MBI (policy number) -> NULL it"
                      % (l.full_name, loser_id, l.mbi))
                if apply:
                    l.mbi = None
                    db.session.flush()
            elif l.mbi and l.mbi.upper() != (k.mbi or "").upper():
                print("  ! %s: loser has a DIFFERENT valid MBI %r vs keeper %r — SKIP (not this tool)"
                      % (loser_id, l.mbi, k.mbi)); continue
            print("  merge %-18s keep %s (mbi %s) <- %s  [both policies stay active]"
                  % (k.full_name, keeper_id, k.mbi, loser_id))
            if apply:
                res = merge_customers(keeper_id, [loser_id], AGENCY_ID, "coexistence_merge")
                if not res.get("ok"):
                    print("     ! merge FAILED: %s — rollback, continue" % res.get("error"))
                    db.session.rollback(); continue
                db.session.commit()
                merged += 1
        if apply:
            print("\nAPPLIED — %d pairs merged." % merged)
        else:
            db.session.rollback()
            print("\nDRY-RUN — nothing written.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
