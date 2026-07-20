"""Merge confirmed reissued-MBI same-person pairs. Dry-run default; --apply.

These are same-person duplicates whose MBI was reissued by CMS (same dob/address/phone,
single carrier). The merge engine + UI both REFUSE different-MBI clusters (contradiction
guard) — correctly, to catch different people. Here we've confirmed same-person and which
MBI is CURRENT (present in the authoritative UHC active BOB), so we null the STALE MBI on
the loser first, then merge into the keeper (which holds the current MBI).

Confirmed 2026-07-18 (scripts/conflict_classify.py + BOB active-MBI check):
  Milton Frazier   : keeper 1647 (mbi 8U39K22PT26 current), loser 1243 (mbi 6RQ6RJ6RV66 stale)
  Lukisha Truesdale: keeper 4269 (mbi 9GV4NA8AV71 current), loser 1282 (mbi 2FQ4NC1DP01 stale)
"""
import sys
from app import create_app
from app.extensions import db
from app.models import Customer
from app.customers import merge_customers

# (keeper_id with CURRENT mbi, loser_id with STALE mbi, expected stale mbi to null)
PAIRS = [
    (1647, 1243, "6RQ6RJ6RV66"),   # Milton Frazier
    (4269, 1282, "2FQ4NC1DP01"),   # Lukisha Truesdale
]


def main(apply):
    app = create_app()
    with app.app_context():
        aid = app.config.get("DEFAULT_AGENCY_ID", 1)
        print(f"{'APPLY' if apply else 'DRY-RUN'} — reissued-MBI merges\n")
        for keeper_id, loser_id, stale_mbi in PAIRS:
            k = db.session.get(Customer, keeper_id)
            l = db.session.get(Customer, loser_id)
            if not k or not l:
                print(f"  ⚠ keeper {keeper_id}/loser {loser_id} missing — SKIP")
                continue
            # SAFETY: same name + same dob (the same-person corroboration)
            if k.full_name != l.full_name or k.dob != l.dob or k.dob is None:
                print(f"  ⚠ {k.full_name}: name/dob mismatch — SKIP (SAFETY)")
                continue
            if l.mbi != stale_mbi:
                print(f"  ⚠ loser {loser_id} mbi {l.mbi} != expected stale {stale_mbi} — SKIP (SAFETY)")
                continue
            print(f"  {k.full_name}: keep {keeper_id} (mbi {k.mbi}) <- {loser_id} "
                  f"(null stale mbi {l.mbi} then merge)")
            if apply:
                l.mbi = None                 # release the stale MBI so the merge guard passes
                db.session.flush()
                res = merge_customers(keeper_id, [loser_id], aid, "reissued_mbi_merge")
                if not res.get("ok"):
                    print(f"    ⚠ merge FAILED: {res.get('error')} — rollback, continue")
                    db.session.rollback()
                    continue
                db.session.commit()
                print(f"    merged={res.get('merged')} moved={res.get('moved')}")
        if not apply:
            db.session.rollback()
            print("\nDRY-RUN — nothing written.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
