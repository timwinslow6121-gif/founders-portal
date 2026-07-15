"""UHC reconciliation — apply the SAFE buckets A + B only. Dry-run by default.

Bucket A (5): DB policies with a real term_date already set but status still 'active'
  → flip status to 'termed' (they genuinely left; term_date proves it).
Bucket B (20): synthetic `uhc::0::N` medigap stub policies on phantom customer records
  → merge each stub customer into the person's REAL customer (real dob+MBI, whose
  [MS]/[DVH] policy matches the BOB). Uses the proven merge_customers() from app.dedup.
  Collapses 20 phantom customers + 20 phantom policies; real coverage kept.

Bucket C (86 real-ID absent) and D (19 BOB-not-in-DB) are NOT handled here (C = the
cross-carrier switcher pass; D = a full BOB import).

Run on the VPS:
  # DRY RUN (no writes):
  FLASK_APP=wsgi.py PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/uhc_reconcile_apply_ab.py
  # APPLY:
  FLASK_APP=wsgi.py PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/uhc_reconcile_apply_ab.py --apply
"""
import sys
from app import create_app
from app.extensions import db
from app.models import Policy, Customer
from app.customers import merge_customers

# Bucket A: the 5 policy ids with term_date set but status=active (from the diff report).
BUCKET_A_POLICY_IDS = [428, 378, 300, 409, 380]

# Bucket B: {person: (keeper_customer_id, [loser stub customer_ids])}
# keeper = the real dob+MBI customer; losers = the uhc::0:: synthetic stub customers.
BUCKET_B = {
    "Judy Kendall":    (6256, [5987, 4256, 4264, 5978]),
    "Natalie Lambe":   (6263, [4253, 4262, 5973, 5985]),
    "Rocky Bostian":   (6250, [4251, 4260, 5983]),
    "James Bailey":    (5992, [4234, 4226]),
    "Sherry Ellsworth":(6267, [4248, 5966]),
    "Richard Moore":   (6268, [5967, 4249]),
    "Walter Storie":   (5993, [5949, 5950]),
    "Jana Benson":     (6247, [5965]),   # keeper 6247 = the MS record; DVH (6245) left alone
}


def main(apply):
    app = create_app()
    with app.app_context():
        agency_id = app.config.get("DEFAULT_AGENCY_ID", 1)
        print(f"{'APPLY' if apply else 'DRY-RUN'} — UHC reconciliation buckets A + B\n")

        # ---------- Bucket A ----------
        print("=== BUCKET A: flip termed-status (5) ===")
        a_done = 0
        for pid in BUCKET_A_POLICY_IDS:
            p = db.session.get(Policy, pid)
            if not p:
                print(f"  pid {pid}: NOT FOUND (skip)")
                continue
            if p.carrier != "UHC":
                print(f"  pid {pid}: carrier {p.carrier} != UHC (skip, SAFETY)")
                continue
            if not p.term_date:
                print(f"  pid {pid}: NO term_date (skip, SAFETY — should not happen)")
                continue
            if p.status != "active":
                print(f"  pid {pid}: status already {p.status} (skip)")
                continue
            cust = db.session.get(Customer, p.customer_id) if p.customer_id else None
            print(f"  pid {pid}: {cust.full_name if cust else '?'} | "
                  f"{p.plan_name} | term {p.term_date} | active -> termed")
            if apply:
                p.status = "termed"
            a_done += 1
        print(f"  bucket A: {a_done} to flip\n")

        # ---------- Bucket B ----------
        print("=== BUCKET B: merge synthetic medigap stubs into real customer (20 stubs -> 8 people) ===")
        b_merged = 0
        for name, (keeper_id, loser_ids) in BUCKET_B.items():
            keeper = db.session.get(Customer, keeper_id)
            if not keeper:
                print(f"  {name}: keeper {keeper_id} NOT FOUND (skip)")
                continue
            losers = [db.session.get(Customer, lid) for lid in loser_ids]
            missing = [lid for lid, l in zip(loser_ids, losers) if l is None]
            if missing:
                print(f"  {name}: loser(s) {missing} NOT FOUND (skip whole person, SAFETY)")
                continue
            # SAFETY: keeper must have a real MBI; losers must be the uhc:: stubs (no mbi)
            if not keeper.mbi:
                print(f"  {name}: keeper {keeper_id} has NO mbi (skip, SAFETY)")
                continue
            bad = [l.id for l in losers if l.mbi]
            if bad:
                print(f"  {name}: loser(s) {bad} HAVE an mbi (not a stub — skip, SAFETY)")
                continue
            print(f"  {name}: keep {keeper_id} (mbi {keeper.mbi}), merge stubs {loser_ids}")
            if apply:
                res = merge_customers(keeper_id, loser_ids, agency_id=agency_id,
                                      actor="uhc_reconcile_bucketB")
                if not res.get("ok"):
                    print(f"    ⚠ merge FAILED: {res.get('error')} — aborting (SAFETY)")
                    db.session.rollback()
                    return
                print(f"    merged={res.get('merged')} moved={res.get('moved')}")
            b_merged += len(loser_ids)
        print(f"  bucket B: {b_merged} stub customers merged into {len(BUCKET_B)} keepers\n")

        if apply:
            db.session.commit()
            print("COMMITTED.")
        else:
            db.session.rollback()
            print("DRY-RUN — no changes written.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
